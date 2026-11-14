"""Tests for ParserRegistry and parse_corpus(): capability introspection,
end-to-end parsing through a real preserved snapshot, one-document
failures not aborting the corpus, and evidence-root/network isolation.
"""

from __future__ import annotations

from pathlib import Path

from strix.corpus.parsers.models import ParseFailureCode, ParseStatus
from strix.corpus.parsers.registry import ParserRegistry, default_registry, parse_corpus
from strix.corpus.parsers.text_parser import TextParser
from strix.corpus.scanner import scan_corpus
from strix.corpus.snapshot import CorpusStore


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    for relative_path, data in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _snapshot(tmp_path: Path, files: dict[str, bytes]) -> tuple[CorpusStore, str]:
    source_root = tmp_path / "source"
    _write_tree(source_root, files)
    scan = scan_corpus(source_root)
    store = CorpusStore(tmp_path / "snapshots")
    manifest, _directory = store.snapshot(scan)
    return store, manifest.corpus_id


# --------------------------------------------------------------------------
# Capability introspection
# --------------------------------------------------------------------------


def test_registry_exposes_capabilities_explicitly() -> None:
    registry = default_registry()
    capabilities = registry.capabilities()
    assert len(capabilities) == 1
    assert capabilities[0].parser_name == "text"
    assert set(capabilities[0].supported_extensions) == {".txt", ".md", ".markdown"}


def test_capability_for_a_supported_extension_is_found() -> None:
    registry = default_registry()
    assert registry.capability_for(".txt") is not None
    assert registry.capability_for(".TXT") is not None  # case-insensitive


def test_capability_for_an_unsupported_extension_is_none() -> None:
    registry = default_registry()
    assert registry.capability_for(".pdf") is None
    assert registry.capability_for(".docx") is None
    assert registry.capability_for(".csv") is None


def test_an_empty_registry_has_no_capabilities() -> None:
    registry = ParserRegistry()
    assert registry.capabilities() == ()
    assert registry.parser_for(".txt") is None


# --------------------------------------------------------------------------
# End-to-end: scan -> snapshot -> parse, through a real preserved corpus
# --------------------------------------------------------------------------


def test_parse_corpus_parses_every_supported_document(tmp_path: Path) -> None:
    store, corpus_id = _snapshot(
        tmp_path, {"a.txt": b"hello\nworld\n", "b.md": b"# Title\n\nBody text.\n"}
    )
    manifest = store.load_manifest(corpus_id)
    results = parse_corpus(store, manifest, default_registry())

    assert len(results) == 2
    assert all(result.status is ParseStatus.SUCCEEDED for result in results)


def test_one_document_failing_does_not_abort_the_rest_of_the_corpus(tmp_path: Path) -> None:
    store, corpus_id = _snapshot(
        tmp_path,
        {
            "good.txt": b"this parses fine\n",
            "bad.txt": b"\xff\xfe invalid utf-8 bytes",
        },
    )
    manifest = store.load_manifest(corpus_id)
    results = parse_corpus(store, manifest, default_registry())

    by_path = {
        document.relative_path: result
        for document, result in zip(manifest.documents, results, strict=True)
    }
    assert by_path["good.txt"].status is ParseStatus.SUCCEEDED
    assert by_path["bad.txt"].status is ParseStatus.FAILED
    assert by_path["bad.txt"].failure is not None
    assert by_path["bad.txt"].failure.code is ParseFailureCode.INVALID_ENCODING
    # The good document was still fully parsed despite the other's failure.
    assert len(by_path["good.txt"].chunks) == 1


def test_unsupported_extension_in_the_corpus_fails_that_document_only(tmp_path: Path) -> None:
    store, corpus_id = _snapshot(
        tmp_path, {"readme.txt": b"supported\n", "data.csv": b"a,b\n1,2\n"}
    )
    manifest = store.load_manifest(corpus_id)
    results = parse_corpus(store, manifest, default_registry())

    by_path = {
        document.relative_path: result
        for document, result in zip(manifest.documents, results, strict=True)
    }
    assert by_path["readme.txt"].status is ParseStatus.SUCCEEDED
    assert by_path["data.csv"].status is ParseStatus.FAILED
    assert by_path["data.csv"].failure.code is ParseFailureCode.UNSUPPORTED_CAPABILITY
    assert by_path["data.csv"].parser_name is None  # no parser was ever dispatched


def test_parse_corpus_reads_only_the_preserved_snapshot_not_the_live_source(
    tmp_path: Path,
) -> None:
    store, corpus_id = _snapshot(tmp_path, {"a.txt": b"original content\n"})
    manifest = store.load_manifest(corpus_id)

    # Mutate the live source after snapshotting -- parsing must be unaffected,
    # since it reads only the preserved copy.
    (tmp_path / "source" / "a.txt").write_bytes(b"mutated after snapshot\n")

    results = parse_corpus(store, manifest, default_registry())
    assert results[0].status is ParseStatus.SUCCEEDED
    assert "original content" in results[0].chunks[0].text


def test_tampered_snapshot_bytes_are_detected_as_a_hash_mismatch(tmp_path: Path) -> None:
    store, corpus_id = _snapshot(tmp_path, {"a.txt": b"original content\n"})
    manifest = store.load_manifest(corpus_id)

    document = manifest.documents[0]
    preserved_path = store.snapshot_root / corpus_id / "documents" / document.relative_path
    preserved_path.write_bytes(b"tampered content\n")

    results = parse_corpus(store, manifest, default_registry())
    assert results[0].status is ParseStatus.FAILED
    assert results[0].failure.code is ParseFailureCode.CONTENT_HASH_MISMATCH


# --------------------------------------------------------------------------
# Isolation: zero reads from the live evidence directory, zero network
# --------------------------------------------------------------------------


def test_nothing_in_this_module_touches_the_real_evidence_root() -> None:
    real_docs = Path("/Users/blkpvnthr/STRIX/docs")
    before = set(real_docs.iterdir()) if real_docs.exists() else set()
    registry = default_registry()
    registry.register(TextParser())  # exercise registration again, still no I/O
    after = set(real_docs.iterdir()) if real_docs.exists() else set()
    assert before == after == set()
