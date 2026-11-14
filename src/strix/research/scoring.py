"""Deterministic, versioned, fully auditable lexical scoring.

Formula (all Decimal arithmetic -- no floating-point value anywhere):

    term_frequency_score = sum over DISTINCT query tokens t of
        min(count of t in the chunk's tokens, MAX_TERM_MATCHES_PER_TOKEN)

    phrase_bonus = sum over query phrases p (any query_terms entry that
        tokenizes to 2+ tokens) of
        min(number of times p's exact token sequence appears
            contiguously in the chunk's tokens, MAX_PHRASE_MATCHES)
        * PHRASE_BONUS_PER_MATCH

    total_score = term_frequency_score + phrase_bonus

Repeated QUERY terms are deduplicated before scoring (so repeating a word
in the query cannot inflate its own weight); repeated terms IN THE CHUNK
contribute up to a capped amount, not unboundedly. This keeps the method
simple enough to recompute by hand from the chunk text and query terms --
no embeddings, no language-model tokenizer, no network, ever. A more
sophisticated ranking method can replace this behind the same
:func:`score_chunk` signature without changing anything upstream of it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from decimal import Decimal

from strix.research.models import ScoreComponents
from strix.research.normalize import tokenize

SCORING_POLICY_VERSION = "1.0.0"

#: A single query token's contribution to term_frequency_score is capped
#: at this many occurrences in the chunk, so one repeated word cannot
#: dominate the score.
MAX_TERM_MATCHES_PER_TOKEN = 5
#: A single query phrase's contribution to phrase_bonus is capped at this
#: many occurrences in the chunk.
MAX_PHRASE_MATCHES = 3
PHRASE_BONUS_PER_MATCH = Decimal(3)


class PreparedQuery:
    """A query's deduplicated tokens and registered phrases, ready to
    score any number of chunks without re-tokenizing the query each time.
    """

    __slots__ = ("phrases", "tokens")

    def __init__(self, tokens: frozenset[str], phrases: tuple[tuple[str, ...], ...]) -> None:
        self.tokens = tokens
        self.phrases = phrases


def prepare_query(query_terms: Sequence[str], *, max_query_terms: int) -> PreparedQuery:
    """Tokenize every entry in *query_terms*.

    Each entry may be a single word or a multi-word phrase; an entry
    tokenizing to 2+ tokens is also registered as a phrase. The flat
    token stream across all entries is capped at *max_query_terms*
    (the compute-limit budget) before deduplication, in entry order --
    this bounds the candidates x terms work scoring does, deterministically.
    """
    all_tokens: list[str] = []
    phrases: list[tuple[str, ...]] = []
    for entry in query_terms:
        entry_tokens = tokenize(entry)
        if not entry_tokens:
            continue
        remaining = max_query_terms - len(all_tokens)
        if remaining <= 0:
            break
        all_tokens.extend(entry_tokens[:remaining])
        if len(entry_tokens) >= 2:
            phrases.append(entry_tokens)
    return PreparedQuery(tokens=frozenset(all_tokens), phrases=tuple(phrases))


def _count_phrase_occurrences(chunk_tokens: Sequence[str], phrase: Sequence[str]) -> int:
    phrase_length = len(phrase)
    if phrase_length == 0 or phrase_length > len(chunk_tokens):
        return 0
    occurrences = 0
    for start in range(len(chunk_tokens) - phrase_length + 1):
        if tuple(chunk_tokens[start : start + phrase_length]) == tuple(phrase):
            occurrences += 1
    return occurrences


def score_chunk(chunk_text: str, query: PreparedQuery) -> ScoreComponents:
    """Score one chunk's text against a prepared query. Pure, deterministic,
    Decimal-only -- recomputing this by hand from the same inputs always
    yields the same result."""
    chunk_tokens = tokenize(chunk_text)
    chunk_counts = Counter(chunk_tokens)

    term_frequency_score = Decimal(
        sum(min(chunk_counts.get(token, 0), MAX_TERM_MATCHES_PER_TOKEN) for token in query.tokens)
    )

    phrase_bonus = Decimal(0)
    for phrase in query.phrases:
        occurrences = min(_count_phrase_occurrences(chunk_tokens, phrase), MAX_PHRASE_MATCHES)
        phrase_bonus += occurrences * PHRASE_BONUS_PER_MATCH

    return ScoreComponents(
        term_frequency_score=term_frequency_score,
        phrase_bonus=phrase_bonus,
        total_score=term_frequency_score + phrase_bonus,
    )
