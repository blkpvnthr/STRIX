"""Tests for deterministic paragraph-aware chunking, chunk IDs, and the
standalone chunk/source-integrity verification."""

from __future__ import annotations

import pytest

from strix.canonical import sha256_hex
from strix.corpus.parsers.chunking import (
    ChunkLimitExceededError,
    chunk_document,
    compute_chunk_id,
    verify_chunks_resolve_to_source,
)
from strix.corpus.parsers.models import AnchorType, DocumentAnchor, DocumentChunk
from strix.errors import ParseIntegrityError

DOC_ID = "DOC-abc123"


def _chunk(lines: tuple[str, ...], *, max_chunk_characters: int = 4000, max_chunks: int = 10_000):
    return chunk_document(
        DOC_ID,
        lines,
        max_chunk_characters=max_chunk_characters,
        max_chunks=max_chunks,
        parser_version="1.0.0",
    )


# --------------------------------------------------------------------------
# Paragraph grouping
# --------------------------------------------------------------------------


def test_a_single_paragraph_becomes_one_chunk() -> None:
    lines = ("line one", "line two", "line three")
    chunks = _chunk(lines)
    assert len(chunks) == 1
    assert chunks[0].anchor.start_line == 1
    assert chunks[0].anchor.end_line == 3
    assert chunks[0].text == "line one\nline two\nline three"


def test_blank_lines_separate_paragraphs_into_distinct_chunks() -> None:
    lines = ("para one line one", "", "para two line one", "para two line two")
    chunks = _chunk(lines)
    assert len(chunks) == 2
    assert (chunks[0].anchor.start_line, chunks[0].anchor.end_line) == (1, 1)
    assert (chunks[1].anchor.start_line, chunks[1].anchor.end_line) == (3, 4)


def test_leading_and_trailing_blank_lines_belong_to_no_chunk() -> None:
    lines = ("", "", "content", "")
    chunks = _chunk(lines)
    assert len(chunks) == 1
    assert (chunks[0].anchor.start_line, chunks[0].anchor.end_line) == (3, 3)


def test_blank_only_document_produces_zero_chunks() -> None:
    assert _chunk(("", "", "")) == ()


def test_empty_document_produces_zero_chunks() -> None:
    assert _chunk(()) == ()


def test_grouping_is_deterministic_across_repeated_calls() -> None:
    lines = ("a", "b", "", "c", "d", "e")
    assert _chunk(lines) == _chunk(lines)


# --------------------------------------------------------------------------
# Oversized paragraph splitting
# --------------------------------------------------------------------------


def test_oversized_paragraph_is_split_into_multiple_chunks() -> None:
    lines = tuple(f"line{i}" for i in range(20))  # one paragraph, 20 lines
    chunks = _chunk(lines, max_chunk_characters=30)
    assert len(chunks) > 1
    # Every line is covered by exactly one chunk, in order, no gaps or overlap.
    covered = []
    for chunk in chunks:
        covered.extend(range(chunk.anchor.start_line, chunk.anchor.end_line + 1))
    assert covered == list(range(1, 21))


def test_oversized_paragraph_split_respects_the_character_bound() -> None:
    lines = tuple(f"line number {i}" for i in range(50))
    chunks = _chunk(lines, max_chunk_characters=50)
    for chunk in chunks:
        if chunk.anchor.start_line != chunk.anchor.end_line:
            assert len(chunk.text) <= 50


def test_a_single_line_exceeding_the_limit_becomes_its_own_chunk() -> None:
    huge_line = "x" * 1000
    lines = ("short", huge_line, "short again")
    chunks = _chunk(lines, max_chunk_characters=10)
    matching = [c for c in chunks if c.anchor.start_line == 2 and c.anchor.end_line == 2]
    assert len(matching) == 1
    assert matching[0].text == huge_line


# --------------------------------------------------------------------------
# Chunk-count limit
# --------------------------------------------------------------------------


def test_chunk_count_limit_is_enforced() -> None:
    # Each line is its own paragraph (separated by blanks) -> many chunks.
    lines = []
    for i in range(10):
        lines.append(f"para {i}")
        lines.append("")
    with pytest.raises(ChunkLimitExceededError):
        _chunk(tuple(lines), max_chunks=3)


# --------------------------------------------------------------------------
# Chunk IDs: stable, content-derived, order-independent of wall clock
# --------------------------------------------------------------------------


def test_chunk_ids_are_stable_across_repeated_runs() -> None:
    lines = ("alpha", "beta", "", "gamma")
    first = _chunk(lines)
    second = _chunk(lines)
    assert tuple(c.chunk_id for c in first) == tuple(c.chunk_id for c in second)


def test_changed_content_produces_a_different_chunk_id() -> None:
    chunks_a = _chunk(("alpha", "beta"))
    chunks_b = _chunk(("alpha", "betX"))
    assert chunks_a[0].chunk_id != chunks_b[0].chunk_id


def test_chunk_id_changes_with_document_id() -> None:
    lines = ("same", "content")
    chunks_doc1 = chunk_document(
        "DOC-one", lines, max_chunk_characters=4000, max_chunks=10, parser_version="1.0.0"
    )
    chunks_doc2 = chunk_document(
        "DOC-two", lines, max_chunk_characters=4000, max_chunks=10, parser_version="1.0.0"
    )
    assert chunks_doc1[0].chunk_id != chunks_doc2[0].chunk_id


def test_compute_chunk_id_matches_what_chunk_document_assigns() -> None:
    chunks = _chunk(("solo line",))
    anchor = chunks[0].anchor
    expected = compute_chunk_id(DOC_ID, anchor, anchor.normalized_content_hash, "1.0.0")
    assert chunks[0].chunk_id == expected


# --------------------------------------------------------------------------
# Ordering and sequencing
# --------------------------------------------------------------------------


def test_chunks_are_returned_in_ascending_line_order_with_sequential_index() -> None:
    lines = ("a", "", "b", "", "c")
    chunks = _chunk(lines)
    assert [c.sequence_index for c in chunks] == list(range(len(chunks)))
    starts = [c.anchor.start_line for c in chunks]
    assert starts == sorted(starts)


# --------------------------------------------------------------------------
# Source/anchor-hash integrity verification
# --------------------------------------------------------------------------


def test_verify_chunks_resolve_to_source_accepts_correct_chunks() -> None:
    lines = ("one", "two", "", "three")
    chunks = _chunk(lines)
    verify_chunks_resolve_to_source(lines, chunks)  # must not raise


def test_verify_chunks_resolve_to_source_rejects_a_tampered_anchor_range() -> None:
    lines = ("one", "two", "three")
    chunks = _chunk(lines)
    tampered_anchor = chunks[0].anchor.model_copy(update={"start_line": 2, "end_line": 3})
    tampered_chunk = chunks[0].model_copy(update={"anchor": tampered_anchor})
    with pytest.raises(ParseIntegrityError):
        verify_chunks_resolve_to_source(lines, (tampered_chunk,))


def test_verify_chunks_resolve_to_source_rejects_an_out_of_range_anchor() -> None:
    lines = ("one", "two")
    text = "one\ntwo"
    out_of_range_hash = sha256_hex(text.encode())
    anchor = DocumentAnchor(
        document_id=DOC_ID,
        anchor_type=AnchorType.LINE_RANGE,
        start_line=1,
        end_line=5,  # beyond the document's 2 lines
        normalized_content_hash=out_of_range_hash,
        parser_version="1.0.0",
    )
    chunk = DocumentChunk(
        chunk_id=compute_chunk_id(DOC_ID, anchor, out_of_range_hash, "1.0.0"),
        document_id=DOC_ID,
        sequence_index=0,
        anchor=anchor,
        text=text,
        normalized_content_hash=out_of_range_hash,
        byte_size=len(text.encode()),
        char_count=len(text),
        chunking_policy_version="1.0.0",
    )
    with pytest.raises(ParseIntegrityError):
        verify_chunks_resolve_to_source(lines, (chunk,))
