"""End-to-end tests for TextParser: the .txt/.md/.markdown parser."""

from __future__ import annotations

from strix.canonical import sha256_hex
from strix.corpus.parsers.models import (
    ParseFailureCode,
    ParseLimits,
    ParseRequest,
    ParseStatus,
)
from strix.corpus.parsers.text_parser import TextParser

DOC_ID = "DOC-abc123"
CORPUS_ID = "CORPUS-xyz789"


def _request(raw: bytes, *, relative_path: str = "a.txt", limits: ParseLimits | None = None):
    return ParseRequest(
        corpus_id=CORPUS_ID,
        document_id=DOC_ID,
        relative_path=relative_path,
        content_hash=sha256_hex(raw),
        limits=limits if limits is not None else ParseLimits(),
    )


def _parse(raw: bytes, **kwargs: object):
    return TextParser().parse(_request(raw, **kwargs), raw)


# --------------------------------------------------------------------------
# Plain UTF-8, BOM, invalid encoding
# --------------------------------------------------------------------------


def test_plain_utf8_text_parses_successfully() -> None:
    raw = b"line one\nline two\n"
    result = _parse(raw)
    assert result.status is ParseStatus.SUCCEEDED
    assert result.total_lines == 2
    assert len(result.chunks) == 1
    assert result.chunks[0].text == "line one\nline two"


def test_utf8_bom_is_stripped_and_does_not_appear_in_chunk_text() -> None:
    raw = b"\xef\xbb\xbf" + b"hello\n"
    result = _parse(raw)
    assert result.status is ParseStatus.SUCCEEDED
    assert result.chunks[0].text == "hello"


def test_invalid_utf8_is_a_typed_failure() -> None:
    raw = b"\xff\xfe invalid"
    result = _parse(raw)
    assert result.status is ParseStatus.FAILED
    assert result.failure is not None
    assert result.failure.code is ParseFailureCode.INVALID_ENCODING
    assert result.chunks == ()


# --------------------------------------------------------------------------
# Content-hash verification (parse only matches what the snapshot recorded)
# --------------------------------------------------------------------------


def test_a_content_hash_mismatch_is_a_typed_failure() -> None:
    raw = b"actual bytes"
    request = ParseRequest(
        corpus_id=CORPUS_ID,
        document_id=DOC_ID,
        relative_path="a.txt",
        content_hash=sha256_hex(b"different bytes entirely"),
        limits=ParseLimits(),
    )
    result = TextParser().parse(request, raw)
    assert result.status is ParseStatus.FAILED
    assert result.failure is not None
    assert result.failure.code is ParseFailureCode.CONTENT_HASH_MISMATCH


# --------------------------------------------------------------------------
# Markdown treated as anchored text, not rendered
# --------------------------------------------------------------------------


def test_markdown_is_treated_as_plain_anchored_text() -> None:
    raw = b"# Heading\n\nSome **bold** text and a [link](http://example.com).\n"
    result = _parse(raw, relative_path="doc.md")
    assert result.status is ParseStatus.SUCCEEDED
    # No rendering/stripping of Markdown syntax -- the raw markup survives verbatim.
    assert "# Heading" in result.chunks[0].text
    assert "**bold**" in result.chunks[1].text
    assert "[link](http://example.com)" in result.chunks[1].text


def test_markdown_extension_variant_is_also_supported() -> None:
    raw = b"content\n"
    result = _parse(raw, relative_path="doc.markdown")
    assert result.status is ParseStatus.SUCCEEDED


# --------------------------------------------------------------------------
# Stable physical line anchors
# --------------------------------------------------------------------------


def test_anchors_report_correct_physical_line_numbers() -> None:
    raw = b"a\nb\n\nc\nd\n"
    result = _parse(raw)
    assert result.total_lines == 5
    assert (result.chunks[0].anchor.start_line, result.chunks[0].anchor.end_line) == (1, 2)
    assert (result.chunks[1].anchor.start_line, result.chunks[1].anchor.end_line) == (4, 5)


# --------------------------------------------------------------------------
# Limits: decoded characters, lines, chunk size, chunk count
# --------------------------------------------------------------------------


def test_decoded_character_limit_is_enforced() -> None:
    raw = ("x" * 100).encode()
    result = _parse(raw, limits=ParseLimits(max_decoded_characters=10))
    assert result.status is ParseStatus.FAILED
    assert result.failure is not None
    assert result.failure.code is ParseFailureCode.DECODED_CHARACTER_LIMIT_EXCEEDED


def test_line_count_limit_is_enforced() -> None:
    raw = ("\n".join(f"line{i}" for i in range(100))).encode()
    result = _parse(raw, limits=ParseLimits(max_lines=10))
    assert result.status is ParseStatus.FAILED
    assert result.failure is not None
    assert result.failure.code is ParseFailureCode.LINE_LIMIT_EXCEEDED


def test_chunk_size_limit_splits_an_oversized_paragraph() -> None:
    raw = ("\n".join(f"line number {i}" for i in range(50))).encode()
    result = _parse(raw, limits=ParseLimits(max_chunk_characters=50))
    assert result.status is ParseStatus.SUCCEEDED
    assert len(result.chunks) > 1


def test_chunk_count_limit_is_enforced() -> None:
    paragraphs = "\n\n".join(f"para {i}" for i in range(20))
    result = _parse(paragraphs.encode(), limits=ParseLimits(max_chunks=5))
    assert result.status is ParseStatus.FAILED
    assert result.failure is not None
    assert result.failure.code is ParseFailureCode.CHUNK_LIMIT_EXCEEDED


def test_oversized_single_line_warns_but_still_succeeds() -> None:
    raw = ("x" * 1000).encode()
    result = _parse(raw, limits=ParseLimits(max_chunk_characters=10))
    assert result.status is ParseStatus.SUCCEEDED
    assert len(result.chunks) == 1
    assert any("exceeding max_chunk_characters" in warning for warning in result.warnings)


# --------------------------------------------------------------------------
# Empty / blank-only documents succeed with zero chunks and a warning
# --------------------------------------------------------------------------


def test_empty_document_succeeds_with_zero_chunks() -> None:
    result = _parse(b"")
    assert result.status is ParseStatus.SUCCEEDED
    assert result.chunks == ()
    assert result.total_lines == 0


def test_blank_only_document_succeeds_with_zero_chunks() -> None:
    result = _parse(b"\n\n\n")
    assert result.status is ParseStatus.SUCCEEDED
    assert result.chunks == ()
    assert result.total_lines == 3
    assert any("no non-blank lines" in warning for warning in result.warnings)


# --------------------------------------------------------------------------
# Stable output across repeated runs
# --------------------------------------------------------------------------


def test_parsing_the_same_bytes_twice_produces_identical_results() -> None:
    raw = b"alpha\nbeta\n\ngamma\n"
    assert _parse(raw) == _parse(raw)
