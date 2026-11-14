"""Immutable, content-addressed corpus snapshots.

Phase 3 of the neuro-symbolic platform. :class:`CorpusStore` turns an
already-accepted :class:`~strix.corpus.models.ScanResult` into a
:class:`~strix.corpus.models.CorpusManifest` plus a preserved, byte-exact
copy of every discovered document — stored outside the evidence root, under
a content-derived ``corpus_id`` directory, committed by a single atomic
rename (the same staging-directory pattern :mod:`strix.run_store` uses for
research runs).

Two layers of responsibility, deliberately distinct:

- **Scanning** (:mod:`strix.corpus.scanner`) establishes *inventory*: an
  approximate, point-in-time listing of what exists and roughly how large
  it is.
- **Snapshotting** (this module) establishes *content identity*: every
  preserved document's hash is computed from the exact bytes this module
  itself just read and wrote, so it is correct by construction regardless
  of what the scan's inventory said. A source that changed between
  scanning and snapshotting in a way the inventory can detect (grew past
  its recorded size, disappeared, became a symlink, started escaping the
  evidence root) fails the snapshot closed, because that is a reasonable
  bound on what "re-reading the same file the scan saw" means. A content
  change that happens to preserve the exact recorded size is *not* an
  integrity failure: the resulting snapshot hash still identifies exactly
  the bytes that were actually preserved. Detecting that narrower case
  would require hashing at scan time, which scanning deliberately does
  not do.

Durability: every preserved document and ``manifest.json`` are written via
temp-file + ``fsync`` + atomic replace (mirroring
:meth:`strix.run_store.RunStore._write_atomic`); every directory created
under staging (including nested ``documents/`` subdirectories) is fsynced
before the commit rename, and the snapshot root is fsynced after it, where
the platform supports it.

Crash semantics: an exception handled *in-process* (anything this module's
own code raises or catches) always cleans up its staging directory via a
``finally`` block before propagating. An abrupt process or machine crash
(``kill -9``, power loss) does **not** run that cleanup and may leave a
hidden ``.staging-*`` directory behind under ``snapshot_root``. Such a
directory is never mistaken for a completed snapshot — it does not sit at
a ``corpus_id`` path, and nothing in this module ever reads from or
verifies a ``.staging-*`` path as if it were one — but it is not
automatically removed by anything in this module either; see
``CorpusStore``'s docstring for why.
"""

from __future__ import annotations

import contextlib
import errno
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from strix.canonical import make_id, pretty_json_bytes, sha256_hex
from strix.corpus.models import (
    CorpusManifest,
    DiscoveredEntry,
    DiscoveryStatus,
    DocumentArtifact,
    ScanResult,
)
from strix.corpus.scanner import resolve_within_root
from strix.errors import (
    CorpusSnapshotError,
    CorpusSnapshotIntegrityError,
    PathTraversalError,
    SourceChangedError,
)

#: Version of the corpus manifest schema, recorded on every CorpusManifest.
CORPUS_MANIFEST_SCHEMA_VERSION = "1.0.0"

#: Default root under which immutable corpus snapshots are stored —
#: deliberately outside the evidence root (never under
#: /Users/blkpvnthr/STRIX/docs/).
DEFAULT_SNAPSHOT_ROOT = Path("corpus_snapshots")

#: Environment variable that overrides the snapshot root.
SNAPSHOT_ROOT_ENV_VAR = "STRIX_CORPUS_SNAPSHOT_DIR"

_CORPUS_ID_PATTERN = re.compile(r"^CORPUS-[0-9a-f]{12}$")


def resolve_snapshot_root(
    explicit: str | Path | None = None, environ: Mapping[str, str] | None = None
) -> Path:
    """Snapshot-root precedence: explicit argument, env var, default.

    Mirrors :func:`strix.run_store.resolve_state_dir`'s precedence pattern.
    Resolution only — never touches the filesystem.
    """
    if explicit:
        return Path(explicit)
    env = os.environ if environ is None else environ
    from_env = env.get(SNAPSHOT_ROOT_ENV_VAR)
    if from_env:
        return Path(from_env)
    return DEFAULT_SNAPSHOT_ROOT


def compute_document_id(relative_path: str, content_hash: str, byte_size: int) -> str:
    """Content-derived document identity: path, hash, and size — no clock."""
    return make_id(
        "DOC",
        {"relative_path": relative_path, "content_hash": content_hash, "byte_size": byte_size},
    )


def compute_corpus_id(documents: Iterable[DocumentArtifact]) -> str:
    """Content-derived corpus identity from preserved document identities only.

    Sorts by ``relative_path`` first, so the result never depends on the
    order documents happen to be supplied in (filesystem iteration order,
    scan order, etc.). Takes no wall-clock input, no rejected entries, no
    limits — only the preserved document inventory.
    """
    ordered = sorted(documents, key=lambda doc: doc.relative_path)
    payload = {
        "documents": [
            {"relative_path": doc.relative_path, "document_id": doc.document_id} for doc in ordered
        ]
    }
    return make_id("CORPUS", payload)


class CorpusStore:
    """Creates, locates, verifies, and loads immutable corpus snapshots.

    Does not clean up stale ``.staging-*`` directories left behind by a
    crashed process, by design: a safe cleanup needs either an age
    threshold (which risks deleting a slow, still-active concurrent
    writer's staging directory) or an ownership/lock mechanism, neither of
    which is implemented yet. This is an explicit deferral, not an
    oversight — a leftover ``.staging-*`` directory wastes disk space but
    is harmless: it is never visible at a ``corpus_id`` path and nothing
    ever treats it as a completed snapshot. Operators should inspect and
    remove old ``.staging-*`` directories manually if disk usage becomes a
    concern.
    """

    def __init__(self, snapshot_root: Path) -> None:
        self.snapshot_root = snapshot_root

    # -- snapshot creation ---------------------------------------------

    def snapshot(
        self, scan: ScanResult, *, created_at: datetime | None = None
    ) -> tuple[CorpusManifest, Path]:
        """Preserve *scan*'s discovered documents into an immutable snapshot.

        Reuses the already-accepted *scan* rather than rescanning. If a
        snapshot with the resulting corpus ID already exists, it is fully
        re-verified (never blindly trusted or overwritten) and returned as
        the result; otherwise a fresh snapshot is staged, fsynced, and
        committed by one atomic rename. Any exception raised while this
        method is running is handled in-process: its staging directory is
        always cleaned up before the exception propagates. That guarantee
        does not extend to an abrupt process or machine crash — see the
        module docstring.
        """
        source_root = Path(scan.evidence_root)
        rejected = tuple(
            sorted(
                (entry for entry in scan.entries if entry.status is DiscoveryStatus.REJECTED),
                key=lambda entry: entry.relative_path,
            )
        )

        self.snapshot_root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=self.snapshot_root, prefix=".staging-"))
        try:
            documents_dir = staging / "documents"
            documents_dir.mkdir()

            documents: list[DocumentArtifact] = []
            discovered = sorted(
                (entry for entry in scan.entries if entry.status is DiscoveryStatus.DISCOVERED),
                key=lambda entry: entry.relative_path,
            )
            for entry in discovered:
                documents.append(self._preserve_one(source_root, documents_dir, entry))

            ordered_documents = tuple(sorted(documents, key=lambda doc: doc.relative_path))
            corpus_id = compute_corpus_id(ordered_documents)
            target = self.snapshot_root / corpus_id

            if target.is_dir():
                # Nothing will be committed from this staging directory;
                # the finally block below discards it.
                return self.verify_and_load(corpus_id), target

            manifest = CorpusManifest(
                corpus_id=corpus_id,
                schema_version=CORPUS_MANIFEST_SCHEMA_VERSION,
                scanner_version=scan.scanner_version,
                evidence_root=scan.evidence_root,
                limits=scan.limits,
                truncated=scan.truncated,
                truncation_reason=scan.truncation_reason,
                documents=ordered_documents,
                rejected_entries=rejected,
                created_at=created_at if created_at is not None else datetime.now(UTC),
            )
            _write_atomic(staging / "manifest.json", pretty_json_bytes(manifest))

            # Every directory level under staging (staging itself and every
            # documents/ subdirectory created above) must be durable before
            # the commit rename, not just the files within them.
            for dirpath, _dirnames, _filenames in os.walk(staging):
                _fsync_dir(Path(dirpath))

            try:
                os.rename(staging, target)
            except OSError as exc:
                if exc.errno in (errno.EEXIST, errno.ENOTEMPTY, errno.EISDIR):
                    # Lost a race with a concurrent, content-identical snapshot.
                    return self.verify_and_load(corpus_id), target
                raise CorpusSnapshotError(f"could not commit corpus snapshot: {exc}") from exc
            _fsync_dir(self.snapshot_root)
            return manifest, target
        finally:
            _cleanup_staging(staging)

    def _preserve_one(
        self, source_root: Path, documents_dir: Path, entry: DiscoveredEntry
    ) -> DocumentArtifact:
        data = self._reread_and_verify_source(source_root, entry)
        content_hash = sha256_hex(data)

        destination = resolve_within_root(documents_dir, entry.relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(destination, data)
        if sha256_hex(destination.read_bytes()) != content_hash:
            raise CorpusSnapshotError(
                f"preserved copy of {entry.relative_path!r} does not match its source hash"
            )

        return DocumentArtifact(
            document_id=compute_document_id(entry.relative_path, content_hash, len(data)),
            relative_path=entry.relative_path,
            content_hash=content_hash,
            byte_size=len(data),
            extension=entry.extension,
        )

    def _reread_and_verify_source(self, source_root: Path, entry: DiscoveredEntry) -> bytes:
        """Re-validate and re-read one source file immediately before copying.

        Checked, in order: not a symlink (checked on the literal path, which
        never follows); resolves within *source_root* (catches an ancestor
        directory having been swapped for a symlink since scanning too);
        still a regular file; and reads at most ``recorded_size + 1`` bytes
        so a file that grew unexpectedly is both detected and never read
        unbounded. Any failure raises :class:`SourceChangedError`.

        This is a bound on how stale the scan's inventory may be, not the
        snapshot's source of integrity: the hash recorded for whatever is
        actually returned here is always correct, because it is computed
        from these exact bytes. A same-size content change between
        scanning and this read is not detected here and is not a failure —
        the snapshot faithfully preserves and hashes whatever it reads.
        """
        raw_path = source_root / entry.relative_path
        if raw_path.is_symlink():
            raise SourceChangedError(
                f"source {entry.relative_path!r} became a symlink since scanning"
            )
        try:
            source_path = resolve_within_root(source_root, entry.relative_path)
        except PathTraversalError as exc:
            raise SourceChangedError(
                f"source {entry.relative_path!r} escaped the evidence root since scanning"
            ) from exc
        if not source_path.is_file():
            raise SourceChangedError(
                f"source {entry.relative_path!r} disappeared or is no longer a regular file"
            )

        expected_size = entry.byte_size
        try:
            with source_path.open("rb") as handle:
                data = (
                    handle.read(expected_size + 1) if expected_size is not None else handle.read()
                )
        except OSError as exc:
            raise SourceChangedError(
                f"source {entry.relative_path!r} could not be read: {exc}"
            ) from exc
        if expected_size is not None and len(data) != expected_size:
            raise SourceChangedError(
                f"source {entry.relative_path!r} no longer matches the "
                f"{expected_size}-byte size recorded at scan time"
            )
        return data

    # -- lookup, verification, replay -----------------------------------
    #
    # None of these methods ever resolve a path through `manifest.evidence_root`.
    # That field is audit metadata recording where the originating scan ran —
    # useful for a human or a later rescan comparison — and is never used to
    # locate bytes. Every read here goes through `self._corpus_dir(corpus_id)`,
    # i.e. the preserved snapshot, never the live evidence root.

    def load_manifest(self, corpus_id: str) -> CorpusManifest:
        """Load a previously-committed snapshot's manifest, unverified.

        Parses and returns the manifest as recorded on disk. Does not
        re-check documents against their hashes or recompute corpus_id —
        use :meth:`verify` or :meth:`verify_and_load` when that assurance
        is required (in particular, before trusting a snapshot found by an
        external corpus_id rather than one this process just produced).
        """
        directory = self._corpus_dir(corpus_id)
        try:
            raw = (directory / "manifest.json").read_bytes()
        except OSError as exc:
            raise CorpusSnapshotIntegrityError(
                f"no corpus snapshot named {corpus_id!r}: {exc}"
            ) from exc
        try:
            return CorpusManifest.model_validate_json(raw)
        except ValidationError as exc:
            raise CorpusSnapshotIntegrityError(
                f"manifest of corpus {corpus_id!r} does not conform to the "
                f"CorpusManifest schema: {exc}"
            ) from exc

    def read_document(self, corpus_id: str, relative_path: str) -> bytes:
        """Read one preserved document's bytes back from a snapshot.

        A direct accessor, not a full verification — use :meth:`verify`
        first if the snapshot's integrity (not just its on-disk presence)
        needs to be established.
        """
        directory = self._corpus_dir(corpus_id)
        path = resolve_within_root(directory / "documents", relative_path)
        return path.read_bytes()

    def verify(self, corpus_id: str) -> None:
        """Fully re-verify an existing snapshot. See :meth:`verify_and_load`."""
        self.verify_and_load(corpus_id)

    def verify_and_load(self, corpus_id: str) -> CorpusManifest:
        """Fully re-verify an existing snapshot, then return its manifest.

        Checks, in order: the manifest parses against the current schema
        version; its declared ``corpus_id`` matches both the directory it
        was loaded from and a fresh recomputation from its own documents
        list; the set of files actually present under ``documents/``
        exactly matches the manifest's declared document paths (no
        undeclared file, nothing missing); and for every document, its
        ``document_id`` is internally consistent with its own declared
        path/hash/size, and the preserved bytes on disk match that hash
        and size exactly. Raises :class:`CorpusSnapshotIntegrityError` on
        any mismatch; never repairs or rewrites anything.
        """
        manifest = self.load_manifest(corpus_id)

        if manifest.schema_version != CORPUS_MANIFEST_SCHEMA_VERSION:
            raise CorpusSnapshotIntegrityError(
                f"manifest of corpus {corpus_id!r} declares schema_version "
                f"{manifest.schema_version!r}, expected {CORPUS_MANIFEST_SCHEMA_VERSION!r}"
            )
        if manifest.corpus_id != corpus_id:
            raise CorpusSnapshotIntegrityError(
                f"manifest declares corpus_id {manifest.corpus_id!r} but was "
                f"loaded from directory {corpus_id!r}"
            )
        recomputed_id = compute_corpus_id(manifest.documents)
        if recomputed_id != manifest.corpus_id:
            raise CorpusSnapshotIntegrityError(
                f"corpus {corpus_id!r}: recomputed corpus id {recomputed_id!r} "
                "does not match the manifest's declared corpus id"
            )

        directory = self._corpus_dir(corpus_id)
        documents_dir = directory / "documents"
        declared_paths = {document.relative_path for document in manifest.documents}
        actual_paths = _list_preserved_files(documents_dir)
        if actual_paths != declared_paths:
            raise CorpusSnapshotIntegrityError(
                f"corpus {corpus_id!r}: documents/ does not match its manifest "
                f"(undeclared: {sorted(actual_paths - declared_paths)}, "
                f"missing: {sorted(declared_paths - actual_paths)})"
            )

        for document in manifest.documents:
            if document.document_id != compute_document_id(
                document.relative_path, document.content_hash, document.byte_size
            ):
                raise CorpusSnapshotIntegrityError(
                    f"corpus {corpus_id!r}: document_id for "
                    f"{document.relative_path!r} is inconsistent with its own "
                    "declared path, hash, and size"
                )
            try:
                path = resolve_within_root(documents_dir, document.relative_path)
            except PathTraversalError as exc:
                raise CorpusSnapshotIntegrityError(
                    f"corpus {corpus_id!r}: document {document.relative_path!r} "
                    "has an unsafe relative path"
                ) from exc
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise CorpusSnapshotIntegrityError(
                    f"preserved document {document.relative_path!r} of corpus "
                    f"{corpus_id!r} is missing or unreadable: {exc}"
                ) from exc
            if len(data) != document.byte_size or sha256_hex(data) != document.content_hash:
                raise CorpusSnapshotIntegrityError(
                    f"preserved document {document.relative_path!r} of corpus "
                    f"{corpus_id!r} no longer matches its recorded hash"
                )
        return manifest

    def _corpus_dir(self, corpus_id: str) -> Path:
        if not _CORPUS_ID_PATTERN.fullmatch(corpus_id):
            raise CorpusSnapshotIntegrityError(f"invalid corpus id {corpus_id!r}")
        return self.snapshot_root / corpus_id


def _list_preserved_files(documents_dir: Path) -> set[str]:
    """POSIX-style relative paths of every file actually under *documents_dir*.

    Does not follow symlinks — a symlink appearing under ``documents/``
    is something :meth:`CorpusStore.snapshot` never creates, so one found
    during verification is itself a sign of tampering and is reported as
    an "undeclared file" like any other unexpected entry (it will not
    match any declared document's relative_path as a symlink, and is not
    silently followed to see what it points at).
    """
    if not documents_dir.is_dir():
        return set()
    found: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(documents_dir, followlinks=False):
        rel_dir = Path(dirpath).relative_to(documents_dir)
        for name in filenames:
            relative = name if str(rel_dir) == "." else (rel_dir / name).as_posix()
            found.add(relative)
    return found


def _write_atomic(path: Path, data: bytes) -> None:
    """Write bytes via temp file + fsync + atomic replace in one directory.

    Deliberately mirrors :meth:`strix.run_store.RunStore._write_atomic`
    exactly, rather than importing its private implementation across
    module boundaries (the same documented tradeoff as ``_cleanup_staging``
    below — a small, intentional duplication of generic atomic-write
    plumbing, not a divergent reimplementation).
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
        raise CorpusSnapshotError(f"could not write {path.name}: {exc}") from exc


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


def _cleanup_staging(staging: Path) -> None:
    """Remove a staging directory tree; never raises.

    Only ever called from within this process's own ``try``/``finally``
    around a single :meth:`CorpusStore.snapshot` call — it cleans up
    in-process failures, not stale directories left by a different,
    possibly crashed, process (see :class:`CorpusStore`'s docstring).
    Deliberately mirrors :mod:`strix.run_store`'s own cleanup routine
    (manual walk + unlink/rmdir rather than ``shutil.rmtree``) rather than
    importing its private helper across module boundaries.
    """
    try:
        if staging.is_dir():
            for root, dirs, files in os.walk(staging, topdown=False):
                for name in files:
                    os.unlink(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
            os.rmdir(staging)
    except OSError:
        pass
