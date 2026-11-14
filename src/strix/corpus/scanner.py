"""Safe recursive discovery scan of the evidence root.

Phase 2 of the neuro-symbolic platform: pure discovery. ``scan_corpus``
never parses document content beyond a one-byte readability probe, never
follows symlinks, and never mutates, deletes, downloads, or snapshots
anything under the scanned root — see
``architecture/development/neuro-symbolic-platform.md`` for the phase plan.

Traversal order is a deterministic, lexically sorted pre-order walk (directory
entries are sorted by name before recursion), so the result is stable across
operating systems and filesystems, and so limit truncation always drops the
same, lexically-last entries rather than whatever order the OS happened to
return.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from strix.corpus.models import (
    DEFAULT_SUPPORTED_EXTENSIONS,
    DiscoveredEntry,
    DiscoveryFailureCode,
    DiscoveryStatus,
    ScanLimits,
    ScanResult,
)
from strix.errors import CorpusRootError, PathTraversalError

#: Version of the discovery scan contract, recorded on every ScanResult.
SCANNER_VERSION = "1.0.0"

#: Default evidence root. Tests must always pass an explicit root under
#: tests/data/corpus/ to scan_corpus — never rely on or scan this default.
DEFAULT_EVIDENCE_ROOT = Path("/Users/blkpvnthr/STRIX/docs")

#: Environment variable that overrides the evidence root.
EVIDENCE_ROOT_ENV_VAR = "STRIX_EVIDENCE_ROOT"


def resolve_evidence_root(
    explicit: str | Path | None = None, environ: Mapping[str, str] | None = None
) -> Path:
    """Evidence-root precedence: explicit argument, STRIX_EVIDENCE_ROOT, default.

    Mirrors :func:`strix.run_store.resolve_state_dir`'s precedence pattern.
    Resolution only — never touches the filesystem or scans anything.
    """
    if explicit:
        return Path(explicit)
    env = os.environ if environ is None else environ
    from_env = env.get(EVIDENCE_ROOT_ENV_VAR)
    if from_env:
        return Path(from_env)
    return DEFAULT_EVIDENCE_ROOT


def scan_corpus(
    root: Path,
    *,
    limits: ScanLimits | None = None,
    supported_extensions: frozenset[str] | None = None,
) -> ScanResult:
    """Recursively discover candidate evidence files under *root*.

    Returns a stable, lexically ordered result distinguishing successfully
    discovered files from rejected ones (unsupported type, unreadable,
    symlink, a resolved path escaping *root*, or over a configured limit).
    Raises :class:`CorpusRootError` if *root* does not exist or is not a
    directory — a configuration error, not a per-entry discovery outcome.
    """
    resolved_limits = limits if limits is not None else ScanLimits()
    extensions = (
        supported_extensions if supported_extensions is not None else DEFAULT_SUPPORTED_EXTENSIONS
    )

    root_resolved = root.resolve()
    if not root_resolved.is_dir():
        raise CorpusRootError(f"evidence root {root} is not an existing directory")

    state = _ScanState(root=root_resolved, limits=resolved_limits, extensions=extensions)
    _walk(root_resolved, depth=0, state=state)

    ordered = tuple(sorted(state.entries, key=lambda entry: entry.relative_path))
    return ScanResult(
        evidence_root=str(root_resolved),
        scanner_version=SCANNER_VERSION,
        limits=resolved_limits,
        entries=ordered,
        truncated=state.truncated,
        truncation_reason=state.truncation_reason,
    )


def resolve_within_root(root: Path, relative: str) -> Path:
    """Resolve a caller-supplied relative path against *root* safely.

    Rejects an absolute path or any ``".."`` component outright — an
    explicit traversal request — without touching the filesystem, then
    rejects a resolved target that still escapes *root* (for example
    through a symlinked ancestor). Raises :class:`PathTraversalError` in
    either case. This is for later phases that accept a relative path
    string (manifest entries, request parameters); the scanner's own walk
    never receives caller-supplied strings and instead checks containment
    directly on each entry it discovers (see ``_is_contained`` below).
    """
    if Path(relative).is_absolute() or PurePosixPath(relative).is_absolute():
        raise PathTraversalError(f"path {relative!r} must be relative to the evidence root")
    if ".." in PurePosixPath(relative).parts:
        raise PathTraversalError(f"path {relative!r} contains a '..' traversal component")
    root_resolved = root.resolve()
    candidate = (root_resolved / relative).resolve()
    if not _is_contained(candidate, root_resolved):
        raise PathTraversalError(f"path {relative!r} resolves outside the evidence root")
    return candidate


def _is_contained(resolved: Path, root: Path) -> bool:
    return resolved == root or resolved.is_relative_to(root)


def _extension(path: Path) -> str | None:
    return path.suffix.lower() or None


@dataclass
class _ScanState:
    root: Path
    limits: ScanLimits
    extensions: frozenset[str]
    entries: list[DiscoveredEntry] = field(default_factory=list)
    file_count: int = 0
    total_bytes: int = 0
    truncated: bool = False
    truncation_reason: DiscoveryFailureCode | None = None
    stop: bool = False

    def should_stop(self) -> bool:
        # A plain method call, rather than a bare attribute read, so mypy's
        # flow analysis never treats `stop` as narrowed to a literal across
        # the state-mutating calls below.
        return self.stop


def _walk(directory: Path, *, depth: int, state: _ScanState) -> None:
    if state.should_stop():
        return
    try:
        children = sorted(os.scandir(directory), key=lambda entry: entry.name)
    except OSError as exc:
        state.entries.append(
            _rejected(directory, state.root, DiscoveryFailureCode.UNREADABLE, str(exc))
        )
        return

    for child in children:
        child_path = Path(child.path)

        if child.is_symlink():
            state.entries.append(
                _rejected(
                    child_path,
                    state.root,
                    DiscoveryFailureCode.SYMLINK_SKIPPED,
                    "symlinks are not followed",
                )
            )
            continue

        try:
            resolved = child_path.resolve()
        except OSError as exc:
            state.entries.append(
                _rejected(child_path, state.root, DiscoveryFailureCode.UNREADABLE, str(exc))
            )
            continue
        if not _is_contained(resolved, state.root):
            state.entries.append(
                _rejected(
                    child_path,
                    state.root,
                    DiscoveryFailureCode.OUTSIDE_EVIDENCE_ROOT,
                    "resolved path escapes the evidence root",
                )
            )
            continue

        if child.is_dir(follow_symlinks=False):
            if depth + 1 > state.limits.max_depth:
                state.entries.append(
                    _rejected(
                        child_path,
                        state.root,
                        DiscoveryFailureCode.DEPTH_LIMIT_EXCEEDED,
                        f"directory exceeds max_depth={state.limits.max_depth}",
                    )
                )
                continue
            _walk(child_path, depth=depth + 1, state=state)
            if state.should_stop():
                return
            continue

        if not child.is_file(follow_symlinks=False):
            state.entries.append(
                _rejected(
                    child_path,
                    state.root,
                    DiscoveryFailureCode.UNSUPPORTED_FILE_TYPE,
                    "not a regular file",
                )
            )
            continue

        _process_file(child_path, child, state)
        if state.should_stop():
            return


def _process_file(path: Path, entry: os.DirEntry[str], state: _ScanState) -> None:
    if state.file_count >= state.limits.max_files:
        state.stop = True
        state.truncated = True
        state.truncation_reason = DiscoveryFailureCode.FILE_COUNT_LIMIT_EXCEEDED
        return
    state.file_count += 1

    try:
        size = entry.stat(follow_symlinks=False).st_size
    except OSError as exc:
        state.entries.append(_rejected(path, state.root, DiscoveryFailureCode.UNREADABLE, str(exc)))
        return

    extension = _extension(path)
    if extension not in state.extensions:
        state.entries.append(
            _rejected(
                path,
                state.root,
                DiscoveryFailureCode.UNSUPPORTED_FILE_TYPE,
                f"extension {extension or '(none)'} is not a supported evidence type",
            )
        )
        return

    if size > state.limits.max_file_size_bytes:
        state.entries.append(
            _rejected(
                path,
                state.root,
                DiscoveryFailureCode.FILE_SIZE_LIMIT_EXCEEDED,
                f"{size} bytes exceeds max_file_size_bytes={state.limits.max_file_size_bytes}",
            )
        )
        return

    if state.total_bytes + size > state.limits.max_total_size_bytes:
        state.stop = True
        state.truncated = True
        state.truncation_reason = DiscoveryFailureCode.TOTAL_SIZE_LIMIT_EXCEEDED
        return

    readability_error = _probe_readable(path)
    if readability_error is not None:
        state.entries.append(
            _rejected(path, state.root, DiscoveryFailureCode.UNREADABLE, readability_error)
        )
        return

    state.total_bytes += size
    state.entries.append(
        DiscoveredEntry(
            relative_path=_relative(path, state.root),
            status=DiscoveryStatus.DISCOVERED,
            byte_size=size,
            extension=extension,
        )
    )


def _probe_readable(path: Path) -> str | None:
    """Confirm the file opens and yields at least one readable byte.

    Reads at most one byte — a readability probe, not content parsing.
    Malformed-content detection belongs to the parser phase.
    """
    try:
        with path.open("rb") as handle:
            handle.read(1)
    except OSError as exc:
        return str(exc)
    return None


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _rejected(path: Path, root: Path, code: DiscoveryFailureCode, detail: str) -> DiscoveredEntry:
    try:
        relative_path = _relative(path, root)
    except ValueError:
        relative_path = path.as_posix()
    extension = _extension(path)
    return DiscoveredEntry(
        relative_path=relative_path,
        status=DiscoveryStatus.REJECTED,
        extension=extension,
        failure_code=code,
        detail=detail,
    )
