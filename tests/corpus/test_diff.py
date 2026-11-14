"""Tests for the pure, deterministic compute_diff() comparison."""

from __future__ import annotations

import pytest
from tests.corpus.diff_fixtures import make_manifest, make_rejected

from strix.corpus.diff import compute_diff
from strix.corpus.models import (
    CompatibilityWarningCode,
    DiscoveryFailureCode,
    DocumentChangeType,
    RejectedEntryChangeType,
    ScanLimits,
)
from strix.errors import IncompatibleSchemaVersionError


def _change(diff, path: str):
    """Find the DocumentChange whose new (or old, for REMOVED) path matches."""
    for change in diff.document_changes:
        if path in (change.new_relative_path, change.old_relative_path):
            return change
    raise AssertionError(f"no change found for path {path!r}")


# --------------------------------------------------------------------------
# Basic classifications
# --------------------------------------------------------------------------


def test_identical_manifests_are_all_unchanged() -> None:
    manifest = make_manifest({"a.txt": b"hello", "b.txt": b"world"})
    diff = compute_diff(manifest, manifest)

    assert {c.change_type for c in diff.document_changes} == {DocumentChangeType.UNCHANGED}
    assert diff.compatibility_warnings == ()
    assert diff.incomplete is False
    assert diff.affected_document_ids == ()
    assert diff.affected_relative_paths == ()


def test_added_document() -> None:
    old = make_manifest({"a.txt": b"hello"})
    new = make_manifest({"a.txt": b"hello", "b.txt": b"new file"})
    diff = compute_diff(old, new)

    assert _change(diff, "b.txt").change_type is DocumentChangeType.ADDED
    assert "b.txt" in diff.affected_relative_paths


def test_removed_document() -> None:
    old = make_manifest({"a.txt": b"hello", "b.txt": b"going away"})
    new = make_manifest({"a.txt": b"hello"})
    diff = compute_diff(old, new)

    assert _change(diff, "b.txt").change_type is DocumentChangeType.REMOVED
    assert "b.txt" in diff.affected_relative_paths


def test_same_path_modification() -> None:
    old = make_manifest({"a.txt": b"version one"})
    new = make_manifest({"a.txt": b"version two"})
    diff = compute_diff(old, new)

    change = _change(diff, "a.txt")
    assert change.change_type is DocumentChangeType.MODIFIED
    assert change.old_relative_path == change.new_relative_path == "a.txt"
    assert change.old_content_hash != change.new_content_hash


# --------------------------------------------------------------------------
# Rename detection
# --------------------------------------------------------------------------


def test_unambiguous_rename_is_detected() -> None:
    old = make_manifest({"old_name.txt": b"same content"})
    new = make_manifest({"new_name.txt": b"same content"})
    diff = compute_diff(old, new)

    assert len(diff.document_changes) == 1
    change = diff.document_changes[0]
    assert change.change_type is DocumentChangeType.RENAMED
    assert change.old_relative_path == "old_name.txt"
    assert change.new_relative_path == "new_name.txt"
    assert change.old_content_hash == change.new_content_hash
    assert set(diff.affected_relative_paths) == {"old_name.txt", "new_name.txt"}


def test_ambiguous_duplicate_content_rename_reports_added_and_removed() -> None:
    # Two old paths share content with one new path -- ambiguous: which
    # old path did the new one come from? Never guessed.
    old = make_manifest({"a.txt": b"shared", "b.txt": b"shared"})
    new = make_manifest({"c.txt": b"shared"})
    diff = compute_diff(old, new)

    types_by_path = {
        (c.old_relative_path or c.new_relative_path): c.change_type for c in diff.document_changes
    }
    assert types_by_path == {
        "a.txt": DocumentChangeType.REMOVED,
        "b.txt": DocumentChangeType.REMOVED,
        "c.txt": DocumentChangeType.ADDED,
    }


def test_same_path_content_change_is_never_a_rename() -> None:
    old = make_manifest({"a.txt": b"before"})
    new = make_manifest({"a.txt": b"after"})
    diff = compute_diff(old, new)
    assert diff.document_changes[0].change_type is DocumentChangeType.MODIFIED


# --------------------------------------------------------------------------
# Simultaneous changes and deterministic ordering
# --------------------------------------------------------------------------


def test_simultaneous_add_remove_modify_rename() -> None:
    old = make_manifest(
        {
            "unchanged.txt": b"same",
            "to_modify.txt": b"old content",
            "to_remove.txt": b"going away",
            "to_rename.txt": b"rename me",
        }
    )
    new = make_manifest(
        {
            "unchanged.txt": b"same",
            "to_modify.txt": b"new content",
            "renamed.txt": b"rename me",
            "brand_new.txt": b"fresh content",
        }
    )
    diff = compute_diff(old, new)

    by_type = {c.change_type for c in diff.document_changes}
    assert by_type == {
        DocumentChangeType.UNCHANGED,
        DocumentChangeType.MODIFIED,
        DocumentChangeType.REMOVED,
        DocumentChangeType.RENAMED,
        DocumentChangeType.ADDED,
    }
    assert _change(diff, "to_remove.txt").change_type is DocumentChangeType.REMOVED
    assert _change(diff, "brand_new.txt").change_type is DocumentChangeType.ADDED
    assert _change(diff, "renamed.txt").change_type is DocumentChangeType.RENAMED


def test_document_changes_are_deterministically_ordered() -> None:
    old = make_manifest({"z.txt": b"1", "a.txt": b"2", "m.txt": b"3"})
    new = make_manifest({"z.txt": b"1z", "a.txt": b"2z", "m.txt": b"3z"})
    diff = compute_diff(old, new)
    paths = [c.new_relative_path for c in diff.document_changes]
    assert paths == sorted(paths)


def test_diff_is_deterministic_across_repeated_calls() -> None:
    old = make_manifest({"a.txt": b"1", "b.txt": b"2"})
    new = make_manifest({"a.txt": b"1z", "c.txt": b"3"})
    assert compute_diff(old, new) == compute_diff(old, new)


# --------------------------------------------------------------------------
# Rejected-entry changes
# --------------------------------------------------------------------------


def test_rejected_entry_changes_cover_all_four_categories() -> None:
    old = make_manifest(
        rejected=(
            make_rejected("gone.exe"),
            make_rejected("stable.bin", detail="same detail"),
            make_rejected(
                "will_change.dat", DiscoveryFailureCode.UNSUPPORTED_FILE_TYPE, "old detail"
            ),
        )
    )
    new = make_manifest(
        rejected=(
            make_rejected("stable.bin", detail="same detail"),
            make_rejected("will_change.dat", DiscoveryFailureCode.UNREADABLE, "new detail"),
            make_rejected("new.exe"),
        )
    )
    diff = compute_diff(old, new)
    by_path = {c.relative_path: c.change_type for c in diff.rejected_entry_changes}

    assert by_path["gone.exe"] is RejectedEntryChangeType.NO_LONGER_REJECTED
    assert by_path["new.exe"] is RejectedEntryChangeType.NEWLY_REJECTED
    assert by_path["stable.bin"] is RejectedEntryChangeType.UNCHANGED
    assert by_path["will_change.dat"] is RejectedEntryChangeType.CHANGED


def test_rejected_entries_never_appear_as_document_changes() -> None:
    old = make_manifest({"a.txt": b"x"}, rejected=(make_rejected("b.exe"),))
    new = make_manifest({"a.txt": b"x"}, rejected=(make_rejected("b.exe"),))
    diff = compute_diff(old, new)
    paths = {p for c in diff.document_changes for p in (c.old_relative_path, c.new_relative_path)}
    assert "b.exe" not in paths


# --------------------------------------------------------------------------
# Scanner-version / limit changes: warnings, not failures
# --------------------------------------------------------------------------


def test_changed_scan_limits_produce_a_compatibility_warning_not_a_failure() -> None:
    old = make_manifest({"a.txt": b"x"}, limits=ScanLimits(max_files=10))
    new = make_manifest({"a.txt": b"x"}, limits=ScanLimits(max_files=20))
    diff = compute_diff(old, new)  # must not raise
    codes = {w.code for w in diff.compatibility_warnings}
    assert CompatibilityWarningCode.LIMITS_CHANGED in codes


def test_changed_scanner_version_produces_a_compatibility_warning_not_a_failure() -> None:
    old = make_manifest({"a.txt": b"x"}, scanner_version="1.0.0")
    new = make_manifest({"a.txt": b"x"}, scanner_version="2.0.0")
    diff = compute_diff(old, new)  # must not raise
    codes = {w.code for w in diff.compatibility_warnings}
    assert CompatibilityWarningCode.SCANNER_VERSION_CHANGED in codes
    assert diff.old_scanner_version == "1.0.0"
    assert diff.new_scanner_version == "2.0.0"


def test_incompatible_schema_version_raises() -> None:
    old = make_manifest({"a.txt": b"x"}, schema_version="1.0.0")
    new = make_manifest({"a.txt": b"x"}, schema_version="2.0.0")
    with pytest.raises(IncompatibleSchemaVersionError):
        compute_diff(old, new)


# --------------------------------------------------------------------------
# Truncation semantics
# --------------------------------------------------------------------------


def test_old_truncated_manifest_marks_diff_incomplete() -> None:
    old = make_manifest({"a.txt": b"x"}, truncated=True)
    new = make_manifest({"a.txt": b"x"})
    diff = compute_diff(old, new)
    assert diff.incomplete is True
    codes = {w.code for w in diff.compatibility_warnings}
    assert CompatibilityWarningCode.INCOMPLETE_DUE_TO_TRUNCATION in codes


def test_new_truncated_manifest_marks_diff_incomplete() -> None:
    old = make_manifest({"a.txt": b"x"})
    new = make_manifest({"a.txt": b"x"}, truncated=True)
    diff = compute_diff(old, new)
    assert diff.incomplete is True


def test_new_truncation_suppresses_false_removal_claims() -> None:
    old = make_manifest({"a.txt": b"x", "b.txt": b"y"})
    # The new scan was truncated and simply never reached b.txt again --
    # it must not be reported as REMOVED.
    new = make_manifest({"a.txt": b"x"}, truncated=True)
    diff = compute_diff(old, new)

    paths_reported = {
        p for c in diff.document_changes for p in (c.old_relative_path, c.new_relative_path)
    }
    assert "b.txt" not in paths_reported
    assert diff.incomplete is True


def test_old_truncation_suppresses_false_addition_claims() -> None:
    # The old scan was truncated and never reached c.txt, which may have
    # already existed back then -- it must not be reported as ADDED.
    old = make_manifest({"a.txt": b"x"}, truncated=True)
    new = make_manifest({"a.txt": b"x", "c.txt": b"z"})
    diff = compute_diff(old, new)

    paths_reported = {
        p for c in diff.document_changes for p in (c.old_relative_path, c.new_relative_path)
    }
    assert "c.txt" not in paths_reported
    assert diff.incomplete is True


def test_truncation_does_not_suppress_same_path_modification() -> None:
    # A document present in BOTH manifests' documents lists was actually
    # captured by both scans, so comparing it is still trustworthy even
    # if one of the scans was truncated elsewhere.
    old = make_manifest({"a.txt": b"before"}, truncated=True)
    new = make_manifest({"a.txt": b"after"})
    diff = compute_diff(old, new)
    assert _change(diff, "a.txt").change_type is DocumentChangeType.MODIFIED
