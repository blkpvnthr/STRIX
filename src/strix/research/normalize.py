"""Deterministic Unicode normalization, case folding, and tokenization for
lexical retrieval. No language-model tokenizer, no network, no wall
clock, no environment dependency.

Policy (versioned independently so either can be revised without the
other): normalize with Unicode NFKC, then Unicode case-fold
(``str.casefold()`` — stronger and more correct across scripts than
``str.lower()``); a token is a maximal run of Unicode alphanumeric
characters, excluding the underscore. Punctuation, whitespace, and every
other symbol is a separator and is discarded outright — "don't" tokenizes
to ("don", "t"), not ("don't",) or ("dont",); this is a deliberate,
simple, fully specified choice, not an oversight.
"""

from __future__ import annotations

import re
import unicodedata

NORMALIZATION_POLICY_VERSION = "1.0.0"
TOKENIZATION_POLICY_VERSION = "1.0.0"

#: Maximal runs of word characters, excluding underscore (`\\w` includes
#: `_`; `[^\\W_]` is word-char-and-not-underscore, i.e. alphanumeric only,
#: Unicode-aware since `re` defaults to Unicode matching for `str` input).
_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


def normalize_text(text: str) -> str:
    """NFKC-normalize, then Unicode case-fold *text*."""
    return unicodedata.normalize("NFKC", text).casefold()


def tokenize(text: str) -> tuple[str, ...]:
    """Normalize *text*, then split it into alphanumeric tokens.

    Punctuation and whitespace are discarded as separators; repeated
    adjacent runs collapse naturally since each match is already maximal.
    """
    return tuple(_TOKEN_PATTERN.findall(normalize_text(text)))
