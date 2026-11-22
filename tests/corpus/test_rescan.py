"""End-to-end tests for rescan(): real scan -> snapshot -> diff, through
a real CorpusStore. Every evidence_root/snapshot_root here is a pytest
tmp_path; nothing touches /Users/blkpvnthr/STRIX/docs/.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from strix.corpus.models import DocumentChangeType
from strix.corpus.rescan import rescan
from strix.corpus.scanner import DEFAULT_EVIDENCE_ROOT, scan_corpus
from strix.corpus.snapshot import CorpusStore
from strix.errors import CorpusSnapshotIntegrityError


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    for relative_path, data in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def test_identical_rescan_reuses_the_prior_corpus_id(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    snapshot_root = tmp_path / "snapshots"
    _write_tree(evidence_root, {"a.txt": b"hello"})

    store = CorpusStore(snapshot_root)

    first_manifest, _directory = store.snapshot(scan_corpus(evidence_root))

    result = rescan(
        evidence_root=evidence_root,
        snapshot_root=snapshot_root,
        prior_corpus_id=first_manifest.corpus_id,
    )

    assert result.manifest.corpus_id == first_manifest.corpus_id
    assert result.diff.old_corpus_id == result.diff.new_corpus_id == first_manifest.corpus_id
    assert all(
        change.change_type is DocumentChangeType.UNCHANGED
        for change in result.diff.document_changes
    )


def test_changed_rescan_produces_a_new_corpus_id(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    snapshot_root = tmp_path / "snapshots"
    _write_tree(evidence_root, {"a.txt": b"hello"})

    store = CorpusStore(snapshot_root)

    first_manifest, _directory = store.snapshot(scan_corpus(evidence_root))

    (evidence_root / "b.txt").write_bytes(b"a new document")

    result = rescan(
        evidence_root=evidence_root,
        snapshot_root=snapshot_root,
        prior_corpus_id=first_manifest.corpus_id,
    )

    assert result.manifest.corpus_id != first_manifest.corpus_id
    added = [c for c in result.diff.document_changes if c.change_type is DocumentChangeType.ADDED]
    assert len(added) == 1
    assert added[0].new_relative_path == "b.txt"


def test_prior_snapshot_remains_readable_after_rescan(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    snapshot_root = tmp_path / "snapshots"
    _write_tree(evidence_root, {"a.txt": b"original"})

    store = CorpusStore(snapshot_root)

    first_manifest, _directory = store.snapshot(scan_corpus(evidence_root))

    (evidence_root / "a.txt").write_bytes(b"changed")
    rescan(
        evidence_root=evidence_root,
        snapshot_root=snapshot_root,
        prior_corpus_id=first_manifest.corpus_id,
    )

    # The prior snapshot is untouched and still fully readable/verifiable.
    store.verify(first_manifest.corpus_id)
    assert store.read_document(first_manifest.corpus_id, "a.txt") == b"original"


def test_source_deletion_after_snapshot_is_reflected_as_removed(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    snapshot_root = tmp_path / "snapshots"
    _write_tree(evidence_root, {"a.txt": b"keep", "b.txt": b"delete me"})

    store = CorpusStore(snapshot_root)

    first_manifest, _directory = store.snapshot(scan_corpus(evidence_root))

    (evidence_root / "b.txt").unlink()

    result = rescan(
        evidence_root=evidence_root,
        snapshot_root=snapshot_root,
        prior_corpus_id=first_manifest.corpus_id,
    )

    removed = [
        c for c in result.diff.document_changes if c.change_type is DocumentChangeType.REMOVED
    ]
    assert len(removed) == 1
    assert removed[0].old_relative_path == "b.txt"
    # The prior snapshot still preserves b.txt's bytes despite the live deletion.
    assert store.read_document(first_manifest.corpus_id, "b.txt") == b"delete me"


def test_tampered_prior_snapshot_is_detected_not_silently_diffed(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    snapshot_root = tmp_path / "snapshots"
    _write_tree(evidence_root, {"a.txt": b"original"})

    store = CorpusStore(snapshot_root)

    first_manifest, directory = store.snapshot(scan_corpus(evidence_root))
    (directory / "documents" / "a.txt").write_bytes(b"tampered")

    with pytest.raises(CorpusSnapshotIntegrityError):
        rescan(
            evidence_root=evidence_root,
            snapshot_root=snapshot_root,
            prior_corpus_id=first_manifest.corpus_id,
        )


# --------------------------------------------------------------------------
# Isolation: zero use of the real evidence root
# --------------------------------------------------------------------------


# Real default evidence-root contents at import time (may hold documentation,
# since the corpus default root is the docs directory). The guard tolerates that
# and asserts these tests ADD nothing — they must use tmp_path only.
_EVIDENCE_BASELINE = (
    set(DEFAULT_EVIDENCE_ROOT.iterdir()) if DEFAULT_EVIDENCE_ROOT.exists() else set()
)


def test_nothing_in_this_module_touches_the_real_evidence_root() -> None:
    current = set(DEFAULT_EVIDENCE_ROOT.iterdir()) if DEFAULT_EVIDENCE_ROOT.exists() else set()
    assert current <= _EVIDENCE_BASELINE, "tests must not write into the real evidence root"
