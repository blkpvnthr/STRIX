"""Tests for the deterministic lexical scoring formula."""

from __future__ import annotations

from decimal import Decimal

from strix.research.scoring import (
    MAX_PHRASE_MATCHES,
    MAX_TERM_MATCHES_PER_TOKEN,
    PHRASE_BONUS_PER_MATCH,
    prepare_query,
    score_chunk,
)


def _prepare(*terms: str, max_query_terms: int = 64):
    return prepare_query(terms, max_query_terms=max_query_terms)


def test_term_frequency_counts_distinct_query_tokens_present() -> None:
    query = _prepare("fox", "dog")
    score = score_chunk("the quick fox jumps over the lazy dog", query)
    assert score.term_frequency_score == Decimal(2)
    assert score.phrase_bonus == Decimal(0)
    assert score.total_score == Decimal(2)


def test_repeated_query_terms_do_not_double_count() -> None:
    # "fox" appears twice in the query terms but is deduplicated.
    query = _prepare("fox", "fox")
    score = score_chunk("a fox", query)
    assert score.term_frequency_score == Decimal(1)


def test_repeated_terms_in_the_chunk_are_capped() -> None:
    query = _prepare("fox")
    many_foxes = " ".join(["fox"] * 50)
    score = score_chunk(many_foxes, query)
    assert score.term_frequency_score == Decimal(MAX_TERM_MATCHES_PER_TOKEN)


def test_phrase_match_earns_a_bonus_beyond_term_frequency() -> None:
    query = _prepare("operating margin")
    with_phrase = score_chunk("the operating margin improved", query)
    without_phrase = score_chunk("margin operating improved", query)  # reversed order
    assert with_phrase.phrase_bonus == PHRASE_BONUS_PER_MATCH
    assert without_phrase.phrase_bonus == Decimal(0)
    # Both still get term_frequency credit for the individual words.
    assert with_phrase.term_frequency_score == without_phrase.term_frequency_score == Decimal(2)
    assert with_phrase.total_score > without_phrase.total_score


def test_repeated_phrase_matches_are_capped() -> None:
    query = _prepare("fast fox")
    text = " ".join(["fast fox"] * 10)
    score = score_chunk(text, query)
    assert score.phrase_bonus == MAX_PHRASE_MATCHES * PHRASE_BONUS_PER_MATCH


def test_no_query_match_scores_zero() -> None:
    query = _prepare("xylophone")
    score = score_chunk("completely unrelated text", query)
    assert score.total_score == Decimal(0)


def test_score_is_deterministic() -> None:
    query = _prepare("fox", "operating margin")
    text = "the fox discussed the operating margin twice: operating margin."
    assert score_chunk(text, query) == score_chunk(text, query)


def test_max_query_terms_bounds_the_flat_token_stream() -> None:
    # Only the first 2 tokens across all query_terms entries are kept.
    query = _prepare("alpha", "beta", "gamma", max_query_terms=2)
    assert query.tokens == frozenset({"alpha", "beta"})
