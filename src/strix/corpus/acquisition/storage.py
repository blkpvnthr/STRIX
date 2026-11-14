"""Content-addressed storage for acquired documents.

Writes only beneath ``<evidence_root>/acquired/``, reusing the same
containment guard (:func:`strix.corpus.scanner.resolve_within_root`) the
rest of the corpus subsystem uses. Filenames are deterministic and
content-addressed (``<sha256>.pdf``); DOI or other persistent-identifier
metadata is never encoded into the filename — it lives on the
:class:`~strix.corpus.acquisition.models.AcquisitionRecord` instead.

Commit is staged (temp file, ``fsync``, then an atomic, create-only
``os.link`` into place rather than a rename — a rename would silently
replace an existing file of a different name; a hard link fails outright
if the target already exists, which is exactly the "never overwrite a
different existing file" guarantee this needs) so an ordinary exception
during staging is cleaned up by a ``finally`` block and never leaves a
partially-written file visible at the final path. The same crash-vs-
exception distinction documented in
:mod:`strix.corpus.snapshot` applies here: an abrupt process or machine
crash may leave a stale hidden ``.staging-*`` directory, which is never
mistaken for a committed document because it does not sit at the
content-addressed path.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from strix.canonical import sha256_hex
from strix.corpus.acquisition.downloader import FetchedPdf, PdfDownloader
from strix.corpus.acquisition.models import (
    AcquisitionRecord,
    SearchPlan,
    SearchResult,
    compute_acquisition_id,
)
from strix.corpus.acquisition.redaction import redact_url
from strix.corpus.scanner import resolve_within_root
from strix.errors import AcquiredDocumentIntegrityError, AcquisitionError

_ACQUIRED_SUBDIR = "acquired"


class AcquiredDocumentStore:
    """Commits acquired document bytes beneath ``<evidence_root>/acquired/``."""

    def __init__(self, evidence_root: Path) -> None:
        self.evidence_root = evidence_root
        self.acquired_dir = evidence_root / _ACQUIRED_SUBDIR

    def commit(self, data: bytes) -> tuple[str, Path]:
        """Write *data* at its content-addressed path; return (relative
        path, absolute path). If a file with that name already exists, it
        is verified (re-read and re-hashed) rather than trusted or
        overwritten; a mismatch raises
        :class:`AcquiredDocumentIntegrityError` and nothing is written.
        """
        content_hash = sha256_hex(data)
        relative_path = f"{content_hash}.pdf"
        self.acquired_dir.mkdir(parents=True, exist_ok=True)
        target = resolve_within_root(self.acquired_dir, relative_path)

        if target.exists():
            return relative_path, self._verify_existing(target, content_hash, relative_path)

        staging_dir = Path(tempfile.mkdtemp(dir=self.acquired_dir, prefix=".staging-"))
        try:
            staged_file = staging_dir / relative_path
            _write_atomic(staged_file, data)
            _fsync_dir(staging_dir)
            try:
                os.link(staged_file, target)
            except FileExistsError:
                # Lost a race with a concurrent, content-identical commit.
                self._verify_existing(target, content_hash, relative_path)
            except OSError as exc:
                raise AcquisitionError(f"could not commit acquired document: {exc}") from exc
            else:
                _fsync_dir(self.acquired_dir)
            return relative_path, target
        finally:
            _cleanup_staging(staging_dir)

    @staticmethod
    def _verify_existing(target: Path, content_hash: str, relative_path: str) -> Path:
        existing = target.read_bytes()
        if sha256_hex(existing) != content_hash:
            raise AcquiredDocumentIntegrityError(
                f"a different file already exists at {relative_path!r}; refusing to overwrite"
            )
        return target


def acquire_pdf(
    downloader: PdfDownloader,
    store: AcquiredDocumentStore,
    result: SearchResult,
    plan: SearchPlan,
    *,
    user_authorized: bool = False,
    retrieved_at: datetime | None = None,
) -> AcquisitionRecord:
    """Fetch, validate, and commit one PDF; build its AcquisitionRecord.

    The record is constructed, and therefore ever returned, only after
    :meth:`AcquiredDocumentStore.commit` has succeeded — a failed fetch
    (policy, network-safety, or PDF-validation rejection) or a failed
    commit never produces one.
    """
    fetched: FetchedPdf = downloader.fetch(result, plan, user_authorized=user_authorized)
    relative_path, _absolute_path = store.commit(fetched.data)

    # Redact once, up front, so the id computation and the stored fields
    # agree on the exact (redacted) URL strings — compute_acquisition_id
    # does not redact on its own (see its docstring).
    original_url = redact_url(fetched.original_url)
    redirect_chain = tuple(redact_url(url) for url in fetched.redirect_chain)
    final_url = redact_url(fetched.final_url)

    content_hash = sha256_hex(fetched.data)
    acquisition_id = compute_acquisition_id(
        result_id=result.result_id,
        plan_id=plan.plan_id,
        original_url=original_url,
        redirect_chain=redirect_chain,
        final_url=final_url,
        provider=result.provider,
        persistent_identifier=result.persistent_identifier,
        persistent_identifier_scheme=result.persistent_identifier_scheme,
        license=result.license,
        access_status=result.access_status,
        media_type=fetched.media_type,
        byte_size=len(fetched.data),
        content_hash=content_hash,
        stored_relative_path=relative_path,
        policy_version=downloader.policy.policy_version,
        downloader_version=downloader.DOWNLOADER_VERSION,
    )
    return AcquisitionRecord(
        acquisition_id=acquisition_id,
        result_id=result.result_id,
        plan_id=plan.plan_id,
        original_url=original_url,
        redirect_chain=redirect_chain,
        final_url=final_url,
        provider=result.provider,
        persistent_identifier=result.persistent_identifier,
        persistent_identifier_scheme=result.persistent_identifier_scheme,
        license=result.license,
        access_status=result.access_status,
        media_type=fetched.media_type,
        byte_size=len(fetched.data),
        content_hash=content_hash,
        stored_relative_path=relative_path,
        policy_version=downloader.policy.policy_version,
        downloader_version=downloader.DOWNLOADER_VERSION,
        retrieved_at=retrieved_at if retrieved_at is not None else datetime.now(UTC),
    )


def _write_atomic(path: Path, data: bytes) -> None:
    """Write bytes via temp file + fsync + atomic replace in one directory.

    Deliberately mirrors :func:`strix.corpus.snapshot._write_atomic` (and,
    in turn, :meth:`strix.run_store.RunStore._write_atomic`) exactly —
    the same documented, intentional duplication of generic atomic-write
    plumbing rather than importing a private helper across module
    boundaries.
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
        raise AcquisitionError(f"could not write {path.name}: {exc}") from exc


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
    """Remove a staging directory tree; never raises. See
    :func:`strix.corpus.snapshot._cleanup_staging` for the identical
    pattern and the same reasoning for not importing it directly."""
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
