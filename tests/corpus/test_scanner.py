"""Tests for the Phase 2 corpus discovery scanner.

All scans run against fixtures under tests/data/corpus/ or pytest's
tmp_path — never against the real evidence root. The suite-wide
``no_network`` autouse fixture (tests/conftest.py) also guards against any
accidental network use, though this module never imports anything
network-capable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from strix.corpus.models import (
    DiscoveredEntry,
    DiscoveryFailureCode,
    DiscoveryStatus,
    ScanLimits,
)
from strix.corpus.scanner import (
    DEFAULT_EVIDENCE_ROOT,
    EVIDENCE_ROOT_ENV_VAR,
    SCANNER_VERSION,
    resolve_evidence_root,
    resolve_within_root,
    scan_corpus,
)
from strix.errors import CorpusRootError, PathTraversalError

BASIC_ROOT = Path(__file__).parent.parent / "data" / "corpus" / "basic"


def _by_path(entries: tuple[DiscoveredEntry, ...]) -> dict[str, DiscoveredEntry]:
    return {entry.relative_path: entry for entry in entries}


# --------------------------------------------------------------------------
# Basic discovery
# --------------------------------------------------------------------------


def test_discovers_supported_files_and_rejects_unsupported() -> None:
    result = scan_corpus(BASIC_ROOT)
    entries = _by_path(result.entries)

    discovered = {
        "readme.txt",
        "notes.md",
        "data.csv",
        "manifest.json",
        "archive.xml",
        "page.html",
        "sub/deeper.txt",
        "sub/sub2/deepest.txt",
    }
    for relative_path in discovered:
        entry = entries[relative_path]
        assert entry.status is DiscoveryStatus.DISCOVERED
        assert entry.failure_code is None
        assert entry.byte_size is not None and entry.byte_size > 0

    unsupported = {"unsupported.bin", "no_extension_file"}
    for relative_path in unsupported:
        entry = entries[relative_path]
        assert entry.status is DiscoveryStatus.REJECTED
        assert entry.failure_code is DiscoveryFailureCode.UNSUPPORTED_FILE_TYPE

    assert not result.truncated
    assert result.truncation_reason is None
    assert result.scanner_version == SCANNER_VERSION
    assert result.evidence_root == str(BASIC_ROOT.resolve())


def test_result_is_stable_and_lexically_ordered() -> None:
    first = scan_corpus(BASIC_ROOT)
    second = scan_corpus(BASIC_ROOT)
    assert first == second

    paths = [entry.relative_path for entry in first.entries]
    assert paths == sorted(paths)


def test_relative_paths_never_contain_the_root() -> None:
    result = scan_corpus(BASIC_ROOT)
    for entry in result.entries:
        assert not entry.relative_path.startswith("/")
        assert str(BASIC_ROOT) not in entry.relative_path


# --------------------------------------------------------------------------
# Depth limit
# --------------------------------------------------------------------------


def test_depth_limit_rejects_deep_directory_without_aborting_scan() -> None:
    result = scan_corpus(BASIC_ROOT, limits=ScanLimits(max_depth=1))
    entries = _by_path(result.entries)

    assert entries["sub/sub2"].status is DiscoveryStatus.REJECTED
    assert entries["sub/sub2"].failure_code is DiscoveryFailureCode.DEPTH_LIMIT_EXCEEDED
    assert "sub/sub2/deepest.txt" not in entries
    # Sibling content outside the capped branch is still discovered.
    assert entries["readme.txt"].status is DiscoveryStatus.DISCOVERED
    assert entries["sub/deeper.txt"].status is DiscoveryStatus.DISCOVERED
    assert not result.truncated  # per-branch rejection, not a scan-wide stop


# --------------------------------------------------------------------------
# File-count and total-size limits (dynamic fixtures: exact byte control)
# --------------------------------------------------------------------------


def test_file_count_limit_truncates_the_whole_scan(tmp_path: Path) -> None:
    for name in ("a.txt", "b.txt", "c.txt"):
        (tmp_path / name).write_text("x")

    result = scan_corpus(tmp_path, limits=ScanLimits(max_files=2))
    entries = _by_path(result.entries)

    assert entries["a.txt"].status is DiscoveryStatus.DISCOVERED
    assert entries["b.txt"].status is DiscoveryStatus.DISCOVERED
    assert "c.txt" not in entries
    assert result.truncated
    assert result.truncation_reason is DiscoveryFailureCode.FILE_COUNT_LIMIT_EXCEEDED


def test_total_size_limit_truncates_the_whole_scan(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"x" * 10)
    (tmp_path / "b.txt").write_bytes(b"x" * 10)

    result = scan_corpus(tmp_path, limits=ScanLimits(max_total_size_bytes=15))
    entries = _by_path(result.entries)

    assert entries["a.txt"].status is DiscoveryStatus.DISCOVERED
    assert "b.txt" not in entries
    assert result.truncated
    assert result.truncation_reason is DiscoveryFailureCode.TOTAL_SIZE_LIMIT_EXCEEDED


def test_per_file_size_limit_rejects_one_file_without_truncating(tmp_path: Path) -> None:
    (tmp_path / "small.txt").write_bytes(b"x" * 5)
    (tmp_path / "big.txt").write_bytes(b"x" * 50)

    result = scan_corpus(tmp_path, limits=ScanLimits(max_file_size_bytes=10))
    entries = _by_path(result.entries)

    assert entries["small.txt"].status is DiscoveryStatus.DISCOVERED
    assert entries["big.txt"].status is DiscoveryStatus.REJECTED
    assert entries["big.txt"].failure_code is DiscoveryFailureCode.FILE_SIZE_LIMIT_EXCEEDED
    assert not result.truncated  # a single oversized file does not stop the scan


# --------------------------------------------------------------------------
# Symlinks are never followed
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlinks require elevated privileges on Windows"
)
def test_symlink_to_file_inside_root_is_skipped_not_followed(tmp_path: Path) -> None:
    real = tmp_path / "real.txt"
    real.write_text("content")
    link = tmp_path / "link.txt"
    link.symlink_to(real)

    result = scan_corpus(tmp_path)
    entries = _by_path(result.entries)

    assert entries["real.txt"].status is DiscoveryStatus.DISCOVERED
    assert entries["link.txt"].status is DiscoveryStatus.REJECTED
    assert entries["link.txt"].failure_code is DiscoveryFailureCode.SYMLINK_SKIPPED


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlinks require elevated privileges on Windows"
)
def test_symlink_escaping_root_is_skipped(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("outside the root")

    root = tmp_path / "root"
    root.mkdir()
    (root / "escape.txt").symlink_to(secret)

    result = scan_corpus(root)
    entries = _by_path(result.entries)

    assert entries["escape.txt"].status is DiscoveryStatus.REJECTED
    assert entries["escape.txt"].failure_code is DiscoveryFailureCode.SYMLINK_SKIPPED


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlinks require elevated privileges on Windows"
)
def test_symlinked_directory_is_skipped_not_descended(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "hidden.txt").write_text("should never be discovered")

    root = tmp_path / "root"
    root.mkdir()
    (root / "link_dir").symlink_to(outside, target_is_directory=True)

    result = scan_corpus(root)
    entries = _by_path(result.entries)

    assert entries["link_dir"].status is DiscoveryStatus.REJECTED
    assert entries["link_dir"].failure_code is DiscoveryFailureCode.SYMLINK_SKIPPED
    assert "link_dir/hidden.txt" not in entries


# --------------------------------------------------------------------------
# Unreadable files (platform-dependent: see report)
# --------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits don't apply on Windows")
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses permission bits, so this cannot be exercised as root",
)
def test_unreadable_file_is_recorded_not_fatal(tmp_path: Path) -> None:
    unreadable = tmp_path / "secret.txt"
    unreadable.write_text("content")
    unreadable.chmod(0o000)
    try:
        result = scan_corpus(tmp_path)
    finally:
        unreadable.chmod(0o644)  # restore so tmp_path cleanup can remove it

    entries = _by_path(result.entries)
    assert entries["secret.txt"].status is DiscoveryStatus.REJECTED
    assert entries["secret.txt"].failure_code is DiscoveryFailureCode.UNREADABLE


# --------------------------------------------------------------------------
# Root validation
# --------------------------------------------------------------------------


def test_missing_root_raises_corpus_root_error(tmp_path: Path) -> None:
    with pytest.raises(CorpusRootError):
        scan_corpus(tmp_path / "does-not-exist")


def test_root_that_is_a_file_raises_corpus_root_error(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x")
    with pytest.raises(CorpusRootError):
        scan_corpus(not_a_dir)


# --------------------------------------------------------------------------
# resolve_within_root: explicit traversal rejection
# --------------------------------------------------------------------------


def test_resolve_within_root_accepts_a_safe_relative_path(tmp_path: Path) -> None:
    (tmp_path / "doc.txt").write_text("x")
    assert resolve_within_root(tmp_path, "doc.txt") == (tmp_path / "doc.txt").resolve()


def test_resolve_within_root_rejects_dotdot_component(tmp_path: Path) -> None:
    with pytest.raises(PathTraversalError):
        resolve_within_root(tmp_path, "../escape.txt")


def test_resolve_within_root_rejects_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(PathTraversalError):
        resolve_within_root(tmp_path, "/etc/passwd")


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlinks require elevated privileges on Windows"
)
def test_resolve_within_root_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("x")

    root = tmp_path / "root"
    root.mkdir()
    (root / "escape.txt").symlink_to(secret)

    with pytest.raises(PathTraversalError):
        resolve_within_root(root, "escape.txt")


# --------------------------------------------------------------------------
# Evidence-root resolution (precedence only — never touches the filesystem)
# --------------------------------------------------------------------------


def test_resolve_evidence_root_precedence() -> None:
    assert resolve_evidence_root(explicit=None, environ={}) == DEFAULT_EVIDENCE_ROOT
    assert resolve_evidence_root(explicit="/custom/root", environ={}) == Path("/custom/root")
    assert resolve_evidence_root(
        explicit=None, environ={EVIDENCE_ROOT_ENV_VAR: "/from/env"}
    ) == Path("/from/env")
    assert resolve_evidence_root(
        explicit="/explicit", environ={EVIDENCE_ROOT_ENV_VAR: "/from/env"}
    ) == Path("/explicit")


# --------------------------------------------------------------------------
# Model invariant: status and failure_code must agree
# --------------------------------------------------------------------------


def test_discovered_entry_rejects_inconsistent_status_and_failure_code() -> None:
    with pytest.raises(ValidationError):
        DiscoveredEntry(
            relative_path="x.txt",
            status=DiscoveryStatus.DISCOVERED,
            failure_code=DiscoveryFailureCode.UNREADABLE,
        )
    with pytest.raises(ValidationError):
        DiscoveredEntry(relative_path="x.txt", status=DiscoveryStatus.REJECTED, failure_code=None)
