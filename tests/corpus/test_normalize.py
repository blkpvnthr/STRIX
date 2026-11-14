"""Tests for strict UTF-8 decoding and versioned line normalization."""

from __future__ import annotations

import pytest

from strix.corpus.parsers.normalize import decode_utf8, normalize_text

# --------------------------------------------------------------------------
# Decoding: UTF-8, optional BOM, no guessing
# --------------------------------------------------------------------------


def test_decode_utf8_decodes_plain_ascii() -> None:
    assert decode_utf8(b"hello world") == "hello world"


def test_decode_utf8_decodes_multibyte_utf8() -> None:
    assert decode_utf8("héllo wörld".encode()) == "héllo wörld"


def test_decode_utf8_strips_a_leading_bom() -> None:
    raw = b"\xef\xbb\xbfhello"
    assert decode_utf8(raw) == "hello"


def test_decode_utf8_without_a_bom_is_unaffected() -> None:
    assert decode_utf8(b"hello") == "hello"


def test_decode_utf8_rejects_invalid_utf8() -> None:
    with pytest.raises(UnicodeDecodeError):
        decode_utf8(b"\xff\xfe\x00invalid")


def test_decode_utf8_rejects_invalid_continuation_bytes() -> None:
    with pytest.raises(UnicodeDecodeError):
        decode_utf8(b"abc\x80def")  # a lone continuation byte, never valid UTF-8


# --------------------------------------------------------------------------
# Line splitting: LF, CRLF, lone CR, trailing-terminator handling
# --------------------------------------------------------------------------


def test_normalize_text_splits_on_lf() -> None:
    assert normalize_text("a\nb\nc") == ("a", "b", "c")


def test_normalize_text_splits_on_crlf() -> None:
    assert normalize_text("a\r\nb\r\nc") == ("a", "b", "c")


def test_normalize_text_splits_on_lone_cr() -> None:
    assert normalize_text("a\rb\rc") == ("a", "b", "c")


def test_normalize_text_handles_mixed_line_endings_identically() -> None:
    assert normalize_text("a\r\nb\nc\rd") == ("a", "b", "c", "d")


def test_normalize_text_trailing_terminator_is_not_an_extra_line() -> None:
    assert normalize_text("a\nb\n") == ("a", "b")
    assert normalize_text("a\nb") == ("a", "b")  # same result with or without one


def test_normalize_text_middle_terminator_still_introduces_a_line() -> None:
    assert normalize_text("a\n\nb") == ("a", "", "b")


def test_normalize_text_trailing_whitespace_is_stripped_per_line() -> None:
    assert normalize_text("a   \nb\t\t\n") == ("a", "b")


def test_normalize_text_leading_whitespace_is_preserved() -> None:
    assert normalize_text("   a\n  b") == ("   a", "  b")


# --------------------------------------------------------------------------
# Empty and blank-only documents (deliberately distinct)
# --------------------------------------------------------------------------


def test_normalize_text_empty_document_has_zero_lines() -> None:
    assert normalize_text("") == ()


def test_normalize_text_single_terminator_has_one_blank_line() -> None:
    assert normalize_text("\n") == ("",)
    assert normalize_text("\r\n") == ("",)


def test_normalize_text_blank_only_document_preserves_every_blank_line() -> None:
    assert normalize_text("\n\n\n") == ("", "", "")


def test_normalize_text_is_deterministic_across_repeated_calls() -> None:
    text = "a\r\n  b  \n\nc\n"
    assert normalize_text(text) == normalize_text(text)
