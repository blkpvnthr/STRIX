"""Tests for strix.research's deterministic Unicode normalization,
case folding, and tokenization."""

from __future__ import annotations

from strix.research.normalize import normalize_text, tokenize


def test_case_folding_is_case_insensitive() -> None:
    assert tokenize("Operating Margin") == tokenize("OPERATING MARGIN")
    assert tokenize("OPERATING MARGIN") == ("operating", "margin")


def test_unicode_normalization_folds_equivalent_forms() -> None:
    # NFKC folds the full-width form down to its ASCII equivalent.
    assert tokenize("ａｂｃ") == ("abc",)


def test_punctuation_is_a_separator_not_part_of_a_token() -> None:
    assert tokenize("don't stop") == ("don", "t", "stop")
    assert tokenize("hello, world!") == ("hello", "world")


def test_repeated_whitespace_and_punctuation_collapse() -> None:
    assert tokenize("a    b,,,c") == ("a", "b", "c")


def test_empty_and_punctuation_only_text_tokenizes_to_nothing() -> None:
    assert tokenize("") == ()
    assert tokenize("!!! ... ---") == ()


def test_tokenize_is_deterministic() -> None:
    text = "The Quick-Brown Fox, don't jump!"
    assert tokenize(text) == tokenize(text)


def test_normalize_text_is_idempotent_for_already_normalized_text() -> None:
    assert normalize_text("abc") == "abc"
