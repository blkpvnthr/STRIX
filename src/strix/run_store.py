"""Atomic, replayable persistence of research runs.

Commit protocol (crash-safe by construction):

1. A hidden staging directory (``.staging-*``) is created *inside* the state
   directory, so the final rename never crosses a filesystem boundary.
2. Every artifact is written into staging via temp-file + ``os.replace`` +
   ``fsync``. The raw fixture copy is re-read and its SHA-256 re-verified
   against the original bytes. ``manifest.json`` is always written last.
3. The staging directory is committed with a single atomic
   ``os.rename(staging, state_dir/RUN-...)``.

A visible ``RUN-*`` directory therefore always contains a complete run; a
crash leaves only an ignorable hidden staging directory, and an existing
completed run can never be overwritten (rename onto an existing directory
fails and a fresh run ID is chosen).

Run IDs identify an *execution* (``RUN-YYYYMMDD-NNN``); they are not
content-derived. Any run ID accepted from user input is validated against a
strict pattern and resolved paths must stay inside the state directory.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from strix.canonical import pretty_json_bytes, sha256_hex
from strix.errors import InvalidRunIdError, RunNotFoundError, RunStoreError
from strix.models import ResearchReport, ResearchSpec, RunManifest
from strix.rendering.terminal import report_text

if TYPE_CHECKING:
    from strix.pipeline import DeterministicOutcome

#: Default state directory, relative to the working directory (gitignored).
DEFAULT_STATE_DIR = Path("research_runs")

#: Environment variable that overrides the state directory.
STATE_DIR_ENV_VAR = "STRIX_STATE_DIR"

# re.ASCII: \d must mean 0-9 only — Unicode digits would corrupt sequence
# parsing and produce lookalike directory names.
RUN_ID_PATTERN = re.compile(r"^RUN-\d{8}-\d{3}$", re.ASCII)

#: Artifact file names inside a run: plain names only, never a path. This
#: also guards replay against a tampered manifest steering reads outside the
#: run directory.
ARTIFACT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,254}$", re.ASCII)

_MAX_SEQUENCE = 999


def sanitize_run_id(run_id: str) -> str:
    """Validate a user-supplied run ID (format only; no filesystem access)."""
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise InvalidRunIdError(f"invalid run ID {run_id!r}; expected the form RUN-YYYYMMDD-NNN")
    return run_id


def sanitize_artifact_name(name: str) -> str:
    """Validate an artifact file name (no separators, no traversal)."""
    if not ARTIFACT_NAME_PATTERN.fullmatch(name) or ".." in name:
        raise RunStoreError(f"invalid artifact name {name!r}")
    return name


class RunStore:
    """Creates, locates, and loads run directories under one state directory."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir

    # -- lookup ------------------------------------------------------------

    def run_dir(self, run_id: str) -> Path:
        """Resolve a sanitized run ID to a directory, enforcing containment."""
        sanitize_run_id(run_id)
        state = self.state_dir.resolve()
        candidate = (self.state_dir / run_id).resolve()
        if candidate.parent != state:
            raise InvalidRunIdError(f"run ID {run_id!r} escapes the state directory")
        if not candidate.is_dir():
            raise RunNotFoundError(f"no completed run named {run_id!r} in {state}")
        return candidate

    def load_json(self, run_id: str, name: str) -> Any:
        """Load one JSON artifact from a completed run."""
        path = self.run_dir(run_id) / sanitize_artifact_name(name)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise RunNotFoundError(f"run {run_id} is missing artifact {name}") from exc
        except json.JSONDecodeError as exc:
            raise RunStoreError(f"artifact {name} of run {run_id} is not valid JSON") from exc

    def read_raw(self, run_id: str, name: str) -> bytes:
        """Read preserved raw source bytes from a completed run."""
        path = self.run_dir(run_id) / "raw" / sanitize_artifact_name(name)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise RunNotFoundError(f"run {run_id} is missing raw artifact {name}") from exc

    # -- persistence -------------------------------------------------------

    def persist_run(
        self,
        *,
        spec: ResearchSpec,
        raw_name: str,
        raw_bytes: bytes,
        outcome: DeterministicOutcome,
        build_manifest: Callable[[str], RunManifest],
        build_report: Callable[[str], ResearchReport],
        today: date,
    ) -> tuple[str, Path, RunManifest, ResearchReport]:
        """Write a complete run atomically; returns (run_id, dir, manifest, report)."""
        # Capture the finalized models so the caller gets them back after commit.
        finalized: dict[str, RunManifest | ResearchReport] = {}

        def finalize(run_id: str) -> tuple[dict[str, bytes], bytes]:
            report = build_report(run_id)
            manifest = build_manifest(run_id)
            finalized["report"] = report
            finalized["manifest"] = manifest
            return (
                {"report.txt": report_text(report).encode("utf-8")},
                pretty_json_bytes(manifest),
            )

        run_id, target = self.persist_generic(
            json_artifacts={
                "spec.json": spec,
                "facts.json": outcome.facts,
                "calculations.json": outcome.calculations,
                "evidence.json": outcome.evidence,
                "claims.json": outcome.claims,
                "verification.json": outcome.verification,
            },
            raw_files={raw_name: raw_bytes},
            finalize=finalize,
            today=today,
        )
        manifest = finalized["manifest"]
        report = finalized["report"]
        assert isinstance(manifest, RunManifest) and isinstance(report, ResearchReport)
        return run_id, target, manifest, report

    def persist_generic(
        self,
        *,
        json_artifacts: Mapping[str, object],
        raw_files: Mapping[str, bytes],
        finalize: Callable[[str], tuple[Mapping[str, bytes], bytes]],
        today: date,
    ) -> tuple[str, Path]:
        """Write an arbitrary run atomically.

        ``json_artifacts`` are pretty-printed JSON files; ``raw_files`` are
        preserved byte-exact under ``raw/`` with per-file hash re-verification.
        ``finalize(run_id)`` returns per-run text files plus the manifest
        bytes; ``manifest.json`` is always the structurally last file written.
        Commit is a single atomic rename; a crash leaves only an ignorable
        hidden ``.staging-*`` directory, never a visible ``RUN-*``.
        """
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(dir=self.state_dir, prefix=".staging-"))
        except OSError as exc:
            raise RunStoreError(f"state directory {self.state_dir} is not writable: {exc}") from exc
        try:
            for name, payload in json_artifacts.items():
                self._write_atomic(
                    staging / sanitize_artifact_name(name), pretty_json_bytes(payload)
                )
            self._preserve_raw_files(staging, raw_files)
            return self._commit(staging, finalize, today)
        except BaseException:
            _cleanup_staging(staging)
            raise

    def _commit(
        self,
        staging: Path,
        finalize: Callable[[str], tuple[Mapping[str, bytes], bytes]],
        today: date,
    ) -> tuple[str, Path]:
        """Allocate a run ID, write per-run files (manifest last), and rename."""
        sequence = self._next_sequence(today)
        while True:
            # Guard BEFORE building the id: sequence 1000 would format as
            # four digits and commit an invalid, unreplayable run name.
            if sequence > _MAX_SEQUENCE:
                raise RunStoreError(f"exhausted run IDs for {today:%Y%m%d}")
            run_id = f"RUN-{today:%Y%m%d}-{sequence:03d}"
            per_run_files, manifest_bytes = finalize(run_id)
            for name, data in per_run_files.items():
                self._write_atomic(staging / sanitize_artifact_name(name), data)
            # The manifest is always the last artifact written.
            self._write_atomic(staging / "manifest.json", manifest_bytes)
            self._fsync_dir(staging)
            target = self.state_dir / run_id
            try:
                os.rename(staging, target)
            except OSError as exc:
                if exc.errno in (errno.EEXIST, errno.ENOTEMPTY, errno.EISDIR):
                    sequence += 1
                    continue
                raise RunStoreError(f"could not commit run directory: {exc}") from exc
            self._fsync_dir(self.state_dir)
            return run_id, target

    def _next_sequence(self, today: date) -> int:
        prefix = f"RUN-{today:%Y%m%d}-"
        highest = 0
        if self.state_dir.is_dir():
            for entry in self.state_dir.iterdir():
                name = entry.name
                if name.startswith(prefix) and RUN_ID_PATTERN.fullmatch(name):
                    highest = max(highest, int(name[len(prefix) :]))
        return highest + 1

    def _preserve_raw_files(self, staging: Path, files: Mapping[str, bytes]) -> None:
        """Copy raw source bytes exactly and re-verify every copy's hash."""
        raw_dir = staging / "raw"
        raw_dir.mkdir()
        for raw_name, raw_bytes in files.items():
            original_hash = sha256_hex(raw_bytes)
            target = raw_dir / sanitize_artifact_name(raw_name)
            self._write_atomic(target, raw_bytes)
            preserved_hash = sha256_hex(target.read_bytes())
            if preserved_hash != original_hash:
                raise RunStoreError(
                    f"preserved raw artifact hash {preserved_hash} does not match "
                    f"source hash {original_hash}"
                )
        self._fsync_dir(raw_dir)

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        """Write bytes via temp file + fsync + atomic replace in one directory."""
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
            raise RunStoreError(f"could not write {path.name}: {exc}") from exc

    @staticmethod
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
    """Remove a failed staging directory; never raises."""
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


def resolve_state_dir(cli_value: str | None, environ: Mapping[str, str] | None = None) -> Path:
    """State directory precedence: --state-dir flag, STRIX_STATE_DIR, default."""
    if cli_value:
        return Path(cli_value)
    env = os.environ if environ is None else environ
    from_env = env.get(STATE_DIR_ENV_VAR)
    if from_env:
        return Path(from_env)
    return DEFAULT_STATE_DIR
