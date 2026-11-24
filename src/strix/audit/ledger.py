"""Durable, append-only, hash-chained audit ledger (GAP-002, R1 §19).

One JSONL file per run holds the committed :class:`EventRecord` stream (one
canonical-JSON object per line), accompanied by a small manifest that anchors
the committed head and count. Writes reuse the crash-safe protocol of
:mod:`strix.run_store`: each file is written to a temp file, ``fsync``-ed,
atomically ``os.replace``-d into place, and the directory entry is ``fsync``-ed.

Appends rewrite the whole JSONL file atomically rather than streaming a partial
line, so the file on disk always contains only complete, valid records — a crash
can never leave a torn line. The log is *logically* append-only: records are only
ever added, never mutated or removed.

**What hash-chaining detects.** Because every ``event_id`` commits to its
``sequence`` and ``previous_event_digest``, any in-place edit of a committed
record — a changed payload, a rewritten field, a reordered or duplicated entry,
a severed link — is detectable by recomputing digests and walking the chain
(:meth:`EventLedger.verify_chain`).

**What it cannot detect, and the anchor that closes the gap.** Chaining alone
cannot detect *tail truncation*: deleting the most recent k records leaves a
shorter chain that is still internally consistent. The per-run manifest records
the committed ``event_count`` and ``head_event_id`` as a lightweight external
anchor, so a truncated tail is caught. Full non-repudiation against an adversary
who can rewrite both the log *and* the manifest requires anchoring the head
digest in an independent store (e.g. a signed external timestamp or a separate
append-only medium); that external anchoring is out of scope here and is called
out so it is never assumed.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from enum import StrEnum
from pathlib import Path

from strix.audit import AUDIT_SCHEMA_VERSION
from strix.audit.events import (
    AuditError,
    EventDraft,
    EventRecord,
    EventType,
    make_event_record,
    recompute_event_id,
)
from strix.canonical import canonical_bytes, canonical_hash, pretty_json_bytes
from strix.models import StrixModel

__all__ = [
    "ChainIssue",
    "ChainIssueType",
    "ChainReport",
    "EventLedger",
    "LifecycleReplay",
]

#: File-name suffixes for the per-run ledger and its integrity anchor.
LEDGER_SUFFIX = ".events.jsonl"
MANIFEST_SUFFIX = ".manifest.json"

# re.ASCII so the token stays filesystem-safe and lookalike-free.
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$", re.ASCII)


class ChainIssueType(StrEnum):
    """Categories of integrity defect :meth:`EventLedger.verify_chain` reports."""

    CORRUPT_RECORD = "corrupt_record"
    PAYLOAD_DIGEST_MISMATCH = "payload_digest_mismatch"
    EVENT_ID_MISMATCH = "event_id_mismatch"
    SEQUENCE_GAP = "sequence_gap"
    BROKEN_CHAIN_LINK = "broken_chain_link"
    DUPLICATE_SEQUENCE = "duplicate_sequence"
    DUPLICATE_IDEMPOTENCY_KEY = "duplicate_idempotency_key"
    TAIL_TRUNCATION = "tail_truncation"
    MANIFEST_MISMATCH = "manifest_mismatch"


class ChainIssue(StrixModel):
    """One concrete integrity defect found while verifying a run's chain."""

    issue_type: ChainIssueType
    #: Line index (0-based) the defect anchors to, or ``None`` for whole-log
    #: findings such as a manifest anchor mismatch.
    index: int | None
    detail: str


class ChainReport(StrixModel):
    """Result of verifying one run's hash-chained ledger."""

    run_id: str
    ok: bool
    event_count: int
    issues: tuple[ChainIssue, ...]


class LifecycleReplay(StrixModel):
    """A reconstructed, verified lifecycle for one research run."""

    run_id: str
    ok: bool
    events: tuple[EventRecord, ...]
    event_type_sequence: tuple[EventType, ...]


def _sanitize_run_id(run_id: str) -> str:
    """Validate a run id for use as a file-name stem (no traversal/separators)."""
    if ".." in run_id or not _RUN_ID_RE.fullmatch(run_id):
        raise AuditError(f"invalid research_run_id {run_id!r} for an audit ledger")
    return run_id


def _write_atomic(path: Path, data: bytes) -> None:
    """Write bytes via temp file + fsync + atomic replace in one directory.

    A module-level function (not a method) so it is a single, test-observable
    seam for the durable-write contract. Any OS failure raises
    :class:`AuditError`; a durable write never fails silently.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise AuditError(f"could not durably write {path.name}: {exc}") from exc


def _fsync_dir(path: Path) -> None:
    """Best-effort fsync of a directory entry (platform-dependent)."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class EventLedger:
    """A durable per-run append-only ledger rooted at one directory."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)

    # -- paths -------------------------------------------------------------

    def ledger_path(self, run_id: str) -> Path:
        """Path of the JSONL event stream for *run_id*."""
        return self.root_dir / f"{_sanitize_run_id(run_id)}{LEDGER_SUFFIX}"

    def manifest_path(self, run_id: str) -> Path:
        """Path of the integrity manifest for *run_id*."""
        return self.root_dir / f"{_sanitize_run_id(run_id)}{MANIFEST_SUFFIX}"

    # -- append ------------------------------------------------------------

    def append(self, event: EventDraft) -> EventRecord:
        """Append one event durably; idempotent on ``idempotency_key``.

        Assigns the next contiguous ``sequence`` and sets
        ``previous_event_digest`` to the prior event's ``event_id`` (the chain
        link). Re-appending an event whose ``idempotency_key`` already exists
        returns the stored record without writing a duplicate. Any failure to
        durably persist raises :class:`AuditError` — never a silent drop.
        """
        run_id = _sanitize_run_id(event.research_run_id)
        try:
            self.root_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise AuditError(f"audit root {self.root_dir} is not writable: {exc}") from exc

        existing = self.read(run_id)
        for prior in existing:
            if prior.idempotency_key == event.idempotency_key:
                return prior

        record = make_event_record(
            research_run_id=run_id,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            sequence=len(existing),
            event_type=event.event_type,
            schema_version=event.schema_version,
            event_timestamp=event.event_timestamp,
            actor=event.actor,
            policy_version=event.policy_version,
            payload=event.payload,
            previous_event_digest=existing[-1].event_id if existing else None,
            idempotency_key=event.idempotency_key,
        )
        self._commit(run_id, (*existing, record))
        return record

    def _commit(self, run_id: str, records: tuple[EventRecord, ...]) -> None:
        """Durably write the full event stream, then its manifest anchor."""
        payload = b"".join(canonical_bytes(record) + b"\n" for record in records)
        head = records[-1].event_id if records else None
        manifest = {
            "run_id": run_id,
            "schema_version": AUDIT_SCHEMA_VERSION,
            "event_count": len(records),
            "head_event_id": head,
        }
        try:
            # The JSONL stream is the authoritative record and is committed
            # first; the manifest is a derived integrity anchor written after.
            _write_atomic(self.ledger_path(run_id), payload)
            _write_atomic(self.manifest_path(run_id), pretty_json_bytes(manifest))
        except OSError as exc:  # pragma: no cover - _write_atomic already wraps
            raise AuditError(f"could not commit audit ledger for {run_id}: {exc}") from exc
        _fsync_dir(self.root_dir)

    # -- read --------------------------------------------------------------

    def read(self, run_id: str) -> tuple[EventRecord, ...]:
        """Return all committed events for *run_id* in sequence order.

        A run with no committed events (including one never written) returns an
        empty tuple. A line that cannot be decoded into an :class:`EventRecord`
        raises :class:`AuditError` — a corrupt authoritative record is never
        silently skipped. Use :meth:`verify_chain` to survey corruption without
        raising.
        """
        lines = self._read_raw_lines(run_id)
        records: list[EventRecord] = []
        for index, line in enumerate(lines):
            try:
                records.append(EventRecord.model_validate(json.loads(line)))
            except (ValueError, TypeError) as exc:
                raise AuditError(
                    f"audit ledger for {run_id} is corrupt at line {index}: {exc}"
                ) from exc
        return tuple(records)

    def _read_raw_lines(self, run_id: str) -> list[str]:
        """Read non-empty raw JSONL lines, or ``[]`` if the ledger is absent."""
        path = self.ledger_path(run_id)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise AuditError(f"could not read audit ledger for {run_id}: {exc}") from exc
        # Split on the record delimiter '\n' ONLY. str.splitlines() also breaks
        # on U+2028/U+2029/U+0085, which appear raw in canonical JSON
        # (ensure_ascii=False) and would corrupt a payload containing them.
        return [line for line in text.split("\n") if line.strip()]

    def _read_manifest(self, run_id: str) -> dict[str, object] | None:
        path = self.manifest_path(run_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise AuditError(f"could not read audit manifest for {run_id}: {exc}") from exc

    # -- verify ------------------------------------------------------------

    def verify_chain(self, run_id: str) -> ChainReport:
        """Verify the hash chain for *run_id*, reporting every defect found.

        Detects: undecodable records, payload-digest mismatches (tamper),
        event-id mismatches (any identifying field changed after commit),
        sequence gaps, broken chain links, duplicate sequences or idempotency
        keys, and — via the manifest anchor — tail truncation. This surveys
        rather than raises, so a tampered log yields ``ok=False`` with details.
        """
        lines = self._read_raw_lines(run_id)
        issues: list[ChainIssue] = []
        decoded: list[EventRecord | None] = []
        for index, line in enumerate(lines):
            try:
                decoded.append(EventRecord.model_validate(json.loads(line)))
            except (ValueError, TypeError) as exc:
                decoded.append(None)
                issues.append(
                    ChainIssue(
                        issue_type=ChainIssueType.CORRUPT_RECORD,
                        index=index,
                        detail=f"line {index} is not a valid event record: {exc}",
                    )
                )

        seen_sequences: dict[int, int] = {}
        seen_keys: dict[str, int] = {}
        prev_event_id: str | None = None
        prev_decoded = True
        for index, record in enumerate(decoded):
            if record is None:
                prev_event_id = None
                prev_decoded = False
                continue

            if canonical_hash(dict(record.payload)) != record.payload_digest:
                issues.append(
                    ChainIssue(
                        issue_type=ChainIssueType.PAYLOAD_DIGEST_MISMATCH,
                        index=index,
                        detail=f"payload of event {record.event_id} does not match its digest",
                    )
                )
            if recompute_event_id(record) != record.event_id:
                issues.append(
                    ChainIssue(
                        issue_type=ChainIssueType.EVENT_ID_MISMATCH,
                        index=index,
                        detail=f"event id {record.event_id} does not match its content",
                    )
                )
            if record.sequence != index:
                issues.append(
                    ChainIssue(
                        issue_type=ChainIssueType.SEQUENCE_GAP,
                        index=index,
                        detail=f"expected sequence {index}, found {record.sequence}",
                    )
                )
            if prev_decoded and record.previous_event_digest != prev_event_id:
                issues.append(
                    ChainIssue(
                        issue_type=ChainIssueType.BROKEN_CHAIN_LINK,
                        index=index,
                        detail=(
                            f"previous_event_digest {record.previous_event_digest!r} "
                            f"does not link to prior event id {prev_event_id!r}"
                        ),
                    )
                )
            if record.sequence in seen_sequences:
                issues.append(
                    ChainIssue(
                        issue_type=ChainIssueType.DUPLICATE_SEQUENCE,
                        index=index,
                        detail=f"sequence {record.sequence} already seen at line "
                        f"{seen_sequences[record.sequence]}",
                    )
                )
            seen_sequences[record.sequence] = index
            if record.idempotency_key in seen_keys:
                issues.append(
                    ChainIssue(
                        issue_type=ChainIssueType.DUPLICATE_IDEMPOTENCY_KEY,
                        index=index,
                        detail=f"idempotency_key {record.idempotency_key!r} already seen at "
                        f"line {seen_keys[record.idempotency_key]}",
                    )
                )
            seen_keys[record.idempotency_key] = index

            prev_event_id = record.event_id
            prev_decoded = True

        issues.extend(self._manifest_issues(run_id, decoded))
        return ChainReport(
            run_id=run_id, ok=not issues, event_count=len(lines), issues=tuple(issues)
        )

    def _manifest_issues(
        self, run_id: str, decoded: list[EventRecord | None]
    ) -> list[ChainIssue]:
        """Compare the log against its external integrity anchor (the manifest)."""
        manifest = self._read_manifest(run_id)
        if manifest is None:
            return []
        issues: list[ChainIssue] = []
        anchored = manifest.get("event_count")
        if isinstance(anchored, int) and anchored > len(decoded):
            issues.append(
                ChainIssue(
                    issue_type=ChainIssueType.TAIL_TRUNCATION,
                    index=None,
                    detail=f"manifest anchors {anchored} events but only "
                    f"{len(decoded)} are present (tail truncated)",
                )
            )
        elif isinstance(anchored, int) and anchored < len(decoded):
            issues.append(
                ChainIssue(
                    issue_type=ChainIssueType.MANIFEST_MISMATCH,
                    index=None,
                    detail=f"manifest anchors {anchored} events but {len(decoded)} are present",
                )
            )
        head = decoded[-1].event_id if decoded and decoded[-1] is not None else None
        if anchored == len(decoded) and manifest.get("head_event_id") != head:
            issues.append(
                ChainIssue(
                    issue_type=ChainIssueType.MANIFEST_MISMATCH,
                    index=None,
                    detail="manifest head_event_id does not match the committed head",
                )
            )
        return issues

    # -- replay ------------------------------------------------------------

    def replay(self, run_id: str) -> LifecycleReplay:
        """Reconstruct the ordered lifecycle for *run_id* (fail-closed).

        Verifies the chain first; a run whose chain does not verify cannot be
        trusted to replay and raises :class:`AuditError`. On success the full
        ordered trace is returned, confirming a committed trace is fully
        reconstructable (R1 §19 / H10).
        """
        report = self.verify_chain(run_id)
        if not report.ok:
            raise AuditError(
                f"cannot replay run {run_id}: chain verification failed with "
                f"{len(report.issues)} issue(s)"
            )
        records = self.read(run_id)
        return LifecycleReplay(
            run_id=run_id,
            ok=True,
            events=records,
            event_type_sequence=tuple(record.event_type for record in records),
        )
