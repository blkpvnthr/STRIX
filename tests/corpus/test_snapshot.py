"""Tests for the Phase 3 corpus manifest and immutable snapshot.

All scans and snapshots run against pytest's tmp_path — never against the
real evidence root, and snapshot_root is always a tmp_path subdirectory,
never the real docs/ tree. The suite-wide no_network autouse fixture
(tests/conftest.py) also guards against any accidental network use.
"""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from strix.canonical import sha256_hex
from strix.corpus.models import (
    CorpusManifest,
    DiscoveredEntry,
    DiscoveryFailureCode,
    DiscoveryStatus,
    DocumentArtifact,
    ScanLimits,
    ScanResult,
)
from strix.corpus.scanner import SCANNER_VERSION, scan_corpus
from strix.corpus.snapshot import CorpusStore, compute_corpus_id, compute_document_id
from strix.errors import CorpusSnapshotIntegrityError, SourceChangedError


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    for relative_path, data in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _scan_and_snapshot(
    source_root: Path, snapshot_root: Path, **scan_kwargs: object
) -> tuple[CorpusManifest, Path]:
    scan = scan_corpus(source_root, **scan_kwargs)  # type: ignore[arg-type]
    store = CorpusStore(snapshot_root)
    return store.snapshot(scan)


# --------------------------------------------------------------------------
# Corpus-ID determinism
# --------------------------------------------------------------------------


def test_identical_bytes_and_paths_produce_the_same_corpus_id(tmp_path: Path) -> None:
    files = {"a.txt": b"hello", "sub/b.txt": b"world"}
    first_root, second_root = tmp_path / "first", tmp_path / "second"
    _write_tree(first_root, files)
    _write_tree(second_root, files)

    first_manifest, _ = _scan_and_snapshot(first_root, tmp_path / "snap1")
    second_manifest, _ = _scan_and_snapshot(second_root, tmp_path / "snap2")

    assert first_manifest.corpus_id == second_manifest.corpus_id


def test_one_byte_change_produces_a_different_corpus_id(tmp_path: Path) -> None:
    original_root, changed_root = tmp_path / "original", tmp_path / "changed"
    _write_tree(original_root, {"a.txt": b"hello"})
    _write_tree(changed_root, {"a.txt": b"hellp"})  # last byte differs

    original_manifest, _ = _scan_and_snapshot(original_root, tmp_path / "snap1")
    changed_manifest, _ = _scan_and_snapshot(changed_root, tmp_path / "snap2")

    assert original_manifest.corpus_id != changed_manifest.corpus_id


def test_renaming_a_document_changes_the_corpus_id(tmp_path: Path) -> None:
    original_root, renamed_root = tmp_path / "original", tmp_path / "renamed"
    _write_tree(original_root, {"a.txt": b"hello"})
    _write_tree(renamed_root, {"b.txt": b"hello"})  # same bytes, different name

    original_manifest, _ = _scan_and_snapshot(original_root, tmp_path / "snap1")
    renamed_manifest, _ = _scan_and_snapshot(renamed_root, tmp_path / "snap2")

    assert original_manifest.corpus_id != renamed_manifest.corpus_id


def test_compute_corpus_id_is_independent_of_supplied_order() -> None:
    documents = [
        DocumentArtifact(
            document_id=compute_document_id(f"{name}.txt", "a" * 64, 1),
            relative_path=f"{name}.txt",
            content_hash="a" * 64,
            byte_size=1,
        )
        for name in ("c", "a", "b", "z", "m")
    ]
    forward = compute_corpus_id(documents)
    shuffled = documents.copy()
    random.Random(42).shuffle(shuffled)
    assert shuffled != documents  # the shuffle actually changed the order
    assert compute_corpus_id(shuffled) == forward


def test_corpus_id_stable_regardless_of_filesystem_creation_order(tmp_path: Path) -> None:
    forward_root, reverse_root = tmp_path / "forward", tmp_path / "reverse"
    names = ["alpha.txt", "beta.txt", "gamma.txt", "delta.txt"]

    forward_root.mkdir()
    for name in names:
        (forward_root / name).write_bytes(name.encode())

    reverse_root.mkdir()
    for name in reversed(names):
        (reverse_root / name).write_bytes(name.encode())

    forward_manifest, _ = _scan_and_snapshot(forward_root, tmp_path / "snap1")
    reverse_manifest, _ = _scan_and_snapshot(reverse_root, tmp_path / "snap2")

    assert forward_manifest.corpus_id == reverse_manifest.corpus_id
    paths = [doc.relative_path for doc in forward_manifest.documents]
    assert paths == sorted(paths)


def test_corpus_id_excludes_created_at_timestamp(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"hello"})
    scan = scan_corpus(source_root)

    manifest1, _ = CorpusStore(tmp_path / "snap1").snapshot(
        scan, created_at=datetime(2020, 1, 1, tzinfo=UTC)
    )
    manifest2, _ = CorpusStore(tmp_path / "snap2").snapshot(
        scan, created_at=datetime(2030, 6, 15, tzinfo=UTC)
    )

    assert manifest1.corpus_id == manifest2.corpus_id
    assert manifest1.created_at != manifest2.created_at


# --------------------------------------------------------------------------
# Preservation survives source changes; replay reads preserved bytes
# --------------------------------------------------------------------------


def test_snapshot_survives_source_deletion(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"hello", "sub/b.txt": b"world"})
    snapshot_root = tmp_path / "snap"
    manifest, directory = _scan_and_snapshot(source_root, snapshot_root)

    import shutil

    shutil.rmtree(source_root)

    store = CorpusStore(snapshot_root)
    store.verify(manifest.corpus_id)  # does not raise: source absence is irrelevant
    assert store.read_document(manifest.corpus_id, "a.txt") == b"hello"
    assert store.read_document(manifest.corpus_id, "sub/b.txt") == b"world"
    assert directory.exists()


def test_replay_reads_preserved_bytes_not_the_live_source(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"original"})
    snapshot_root = tmp_path / "snap"
    manifest, _ = _scan_and_snapshot(source_root, snapshot_root)

    # Mutate the live source after the snapshot — replay must be unaffected.
    (source_root / "a.txt").write_bytes(b"mutated!")

    store = CorpusStore(snapshot_root)
    loaded = store.load_manifest(manifest.corpus_id)
    assert loaded == manifest
    assert store.read_document(manifest.corpus_id, "a.txt") == b"original"
    store.verify(manifest.corpus_id)  # still matches its own preserved copy


# --------------------------------------------------------------------------
# Manifest content: rejected entries, truncation, schema fields
# --------------------------------------------------------------------------


def test_rejected_entries_appear_in_manifest_and_are_never_preserved(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"good.txt": b"ok", "bad.exe": b"nope"})
    manifest, directory = _scan_and_snapshot(source_root, tmp_path / "snap")

    rejected_paths = {entry.relative_path: entry for entry in manifest.rejected_entries}
    assert rejected_paths["bad.exe"].status is DiscoveryStatus.REJECTED
    assert rejected_paths["bad.exe"].failure_code is DiscoveryFailureCode.UNSUPPORTED_FILE_TYPE

    document_paths = {doc.relative_path for doc in manifest.documents}
    assert "bad.exe" not in document_paths
    assert not (directory / "documents" / "bad.exe").exists()
    assert (directory / "documents" / "good.txt").read_bytes() == b"ok"


def test_truncated_scan_is_represented_explicitly_in_manifest(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"a", "b.txt": b"b"})

    manifest, _ = _scan_and_snapshot(source_root, tmp_path / "snap", limits=ScanLimits(max_files=1))

    assert manifest.truncated is True
    assert manifest.truncation_reason is DiscoveryFailureCode.FILE_COUNT_LIMIT_EXCEEDED
    assert len(manifest.documents) == 1


def test_manifest_schema_fields_are_populated(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"hello"})
    manifest, _ = _scan_and_snapshot(source_root, tmp_path / "snap")

    assert manifest.schema_version
    assert manifest.scanner_version == SCANNER_VERSION
    assert manifest.evidence_root == str(source_root.resolve())
    assert isinstance(manifest.limits, ScanLimits)
    assert manifest.truncated is False
    assert manifest.truncation_reason is None
    assert manifest.created_at is not None
    assert manifest.corpus_id.startswith("CORPUS-")


# --------------------------------------------------------------------------
# TOCTOU: traversal, symlink substitution, mutation between scan and copy
# --------------------------------------------------------------------------


def test_snapshot_rejects_a_fed_traversal_path(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    snapshot_root = tmp_path / "snap"

    hostile_entry = DiscoveredEntry(
        relative_path="../escape.txt",
        status=DiscoveryStatus.DISCOVERED,
        byte_size=5,
        extension=".txt",
    )
    fake_scan = ScanResult(
        evidence_root=str(source_root.resolve()),
        scanner_version=SCANNER_VERSION,
        limits=ScanLimits(),
        entries=(hostile_entry,),
        truncated=False,
    )

    with pytest.raises(SourceChangedError):
        CorpusStore(snapshot_root).snapshot(fake_scan)

    assert not snapshot_root.exists() or list(snapshot_root.iterdir()) == []


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlinks require elevated privileges on Windows"
)
def test_symlink_substitution_between_scan_and_snapshot_fails_closed(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"original"})
    scan = scan_corpus(source_root)

    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"swapped in after scanning")
    (source_root / "a.txt").unlink()
    (source_root / "a.txt").symlink_to(outside)

    snapshot_root = tmp_path / "snap"
    with pytest.raises(SourceChangedError):
        CorpusStore(snapshot_root).snapshot(scan)

    assert not snapshot_root.exists() or list(snapshot_root.iterdir()) == []


def test_content_mutation_between_scan_and_snapshot_fails_closed(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"original-content"})
    scan = scan_corpus(source_root)

    # Changes size relative to what the scan recorded.
    (source_root / "a.txt").write_bytes(b"short")

    snapshot_root = tmp_path / "snap"
    with pytest.raises(SourceChangedError):
        CorpusStore(snapshot_root).snapshot(scan)

    assert not snapshot_root.exists() or list(snapshot_root.iterdir()) == []


def test_source_disappearance_between_scan_and_snapshot_fails_closed(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"original"})
    scan = scan_corpus(source_root)

    (source_root / "a.txt").unlink()

    snapshot_root = tmp_path / "snap"
    with pytest.raises(SourceChangedError):
        CorpusStore(snapshot_root).snapshot(scan)

    assert not snapshot_root.exists() or list(snapshot_root.iterdir()) == []


# --------------------------------------------------------------------------
# Atomicity: interrupted staging, never silently overwriting an existing
# snapshot
# --------------------------------------------------------------------------


def test_interrupted_staging_leaves_no_completed_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"a", "b.txt": b"b", "c.txt": b"c"})
    scan = scan_corpus(source_root)
    snapshot_root = tmp_path / "snap"

    original = CorpusStore._reread_and_verify_source
    calls = {"count": 0}

    def flaky(self: CorpusStore, root: Path, entry: DiscoveredEntry) -> bytes:
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("simulated crash mid-staging")
        return original(self, root, entry)

    monkeypatch.setattr(CorpusStore, "_reread_and_verify_source", flaky)

    with pytest.raises(RuntimeError):
        CorpusStore(snapshot_root).snapshot(scan)

    assert calls["count"] == 2  # proves we were interrupted mid-copy, not before starting
    assert list(snapshot_root.iterdir()) == []  # no .staging-*, no completed corpus dir


def test_existing_snapshot_is_verified_not_silently_overwritten(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"original"})
    scan = scan_corpus(source_root)
    snapshot_root = tmp_path / "snap"
    store = CorpusStore(snapshot_root)
    _manifest, directory = store.snapshot(scan)

    # Simulate on-disk corruption of the already-committed snapshot.
    (directory / "documents" / "a.txt").write_bytes(b"tampered")

    with pytest.raises(CorpusSnapshotIntegrityError):
        store.snapshot(scan)

    # Not silently repaired or overwritten.
    assert (directory / "documents" / "a.txt").read_bytes() == b"tampered"


# --------------------------------------------------------------------------
# Hardening: durability (fsync)
# --------------------------------------------------------------------------


def test_fsync_is_used_for_durability(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"a", "b.txt": b"b"})
    scan = scan_corpus(source_root)

    calls = {"count": 0}
    original_fsync = os.fsync

    def counting_fsync(fd: int) -> None:
        calls["count"] += 1
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)

    CorpusStore(tmp_path / "snap").snapshot(scan)

    # At least: 2 preserved files + manifest.json, each via _write_atomic's
    # own fsync, plus the staging/documents directory fsyncs before rename
    # and the snapshot_root fsync after it.
    assert calls["count"] >= 3


# --------------------------------------------------------------------------
# Hardening: same-size content change is preserved faithfully, not rejected
# --------------------------------------------------------------------------


def test_same_size_content_mutation_is_preserved_faithfully_not_rejected(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"original"})  # 8 bytes
    scan = scan_corpus(source_root)

    # Same byte length, different content: scanning only ever recorded a
    # size, never a hash, so this change is invisible to the TOCTOU size
    # check. That is not a bug — the resulting snapshot still correctly
    # identifies exactly the bytes it actually read and preserved.
    (source_root / "a.txt").write_bytes(b"mutated!")  # also 8 bytes

    manifest, directory = CorpusStore(tmp_path / "snap").snapshot(scan)

    document = manifest.documents[0]
    assert document.byte_size == 8
    assert document.content_hash == sha256_hex(b"mutated!")
    assert (directory / "documents" / "a.txt").read_bytes() == b"mutated!"


# --------------------------------------------------------------------------
# Hardening: deeper reuse verification
# --------------------------------------------------------------------------


def _tamper_manifest(directory: Path, mutate: object) -> None:
    manifest_path = directory / "manifest.json"
    data = json.loads(manifest_path.read_text())
    mutate(data)  # type: ignore[operator]
    manifest_path.write_text(json.dumps(data))


def test_verify_detects_wrong_schema_version(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"hello"})
    scan = scan_corpus(source_root)
    store = CorpusStore(tmp_path / "snap")
    manifest, directory = store.snapshot(scan)

    _tamper_manifest(directory, lambda data: data.update(schema_version="9.9.9"))

    with pytest.raises(CorpusSnapshotIntegrityError):
        store.verify(manifest.corpus_id)


def test_verify_detects_corpus_id_disagreeing_with_recomputed_value(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"hello"})
    scan = scan_corpus(source_root)
    store = CorpusStore(tmp_path / "snap")
    manifest, directory = store.snapshot(scan)

    # relative_path feeds compute_corpus_id directly; changing it without
    # touching the top-level corpus_id field makes the recomputed id disagree.
    _tamper_manifest(
        directory, lambda data: data["documents"][0].update(relative_path="renamed.txt")
    )

    with pytest.raises(CorpusSnapshotIntegrityError):
        store.verify(manifest.corpus_id)


def test_verify_detects_document_id_inconsistent_with_its_own_fields(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"hello"})
    scan = scan_corpus(source_root)
    store = CorpusStore(tmp_path / "snap")
    manifest, directory = store.snapshot(scan)

    # content_hash does not feed compute_corpus_id, so this survives the
    # corpus-id recompute check and is caught by the per-document
    # document_id-consistency check instead.
    _tamper_manifest(directory, lambda data: data["documents"][0].update(content_hash="0" * 64))

    with pytest.raises(CorpusSnapshotIntegrityError):
        store.verify(manifest.corpus_id)


def test_verify_detects_an_undeclared_file_under_documents(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"hello"})
    scan = scan_corpus(source_root)
    store = CorpusStore(tmp_path / "snap")
    manifest, directory = store.snapshot(scan)

    (directory / "documents" / "sneaked_in.txt").write_bytes(b"not declared anywhere")

    with pytest.raises(CorpusSnapshotIntegrityError):
        store.verify(manifest.corpus_id)


def test_identical_snapshot_is_reused_not_rewritten(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _write_tree(source_root, {"a.txt": b"original"})
    scan = scan_corpus(source_root)
    snapshot_root = tmp_path / "snap"
    store = CorpusStore(snapshot_root)

    manifest1, directory1 = store.snapshot(scan)
    preserved = directory1 / "documents" / "a.txt"
    recorded_mtime = preserved.stat().st_mtime_ns

    manifest2, directory2 = store.snapshot(scan)

    assert manifest1.corpus_id == manifest2.corpus_id
    assert directory1 == directory2
    assert preserved.stat().st_mtime_ns == recorded_mtime  # never rewritten
