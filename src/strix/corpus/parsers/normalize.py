"""Deterministic UTF-8 decoding and line normalization, versioned.

No encoding is ever guessed: decoding is strict UTF-8, with an optional
leading BOM stripped. No wall clock, environment, network, or LLM
dependency anywhere in this module.
"""

from __future__ import annotations

import re

#: Version of the decode + line-splitting + trailing-whitespace policy
#: below. Bump this whenever the policy's observable output changes —
#: every DocumentAnchor/ParseResult that used it records this value.
NORMALIZATION_POLICY_VERSION = "1.0.0"

_UTF8_BOM = b"\xef\xbb\xbf"

#: CRLF, lone CR, and LF are each exactly one line ending. No other
#: Unicode line/paragraph separator (vertical tab, form feed, U+2028,
#: U+2029, etc.) is treated as one -- unlike str.splitlines(), which
#: would, this is deliberately narrower and exactly these three.
_LINE_ENDING = r"\r\n|\r|\n"
_LINE_SPLIT_PATTERN = re.compile(_LINE_ENDING)
_TRAILING_LINE_ENDING_PATTERN = re.compile(f"(?:{_LINE_ENDING})$")


def decode_utf8(raw: bytes) -> str:
    """Strict UTF-8 decode; strips one leading BOM if present.

    Raises ``UnicodeDecodeError`` for anything that is not valid UTF-8 --
    callers turn that into a typed ``ParseFailureCode.INVALID_ENCODING``
    failure; no other encoding is ever attempted or guessed.
    """
    if raw.startswith(_UTF8_BOM):
        raw = raw[len(_UTF8_BOM) :]
    return raw.decode("utf-8", errors="strict")


def normalize_text(text: str) -> tuple[str, ...]:
    """Split *text* into physical, 1-based-numbered lines.

    Policy (version :data:`NORMALIZATION_POLICY_VERSION`):

    - CRLF, CR, and LF are each exactly one line ending (see
      :data:`_LINE_ENDING`); nothing else is.
    - A single trailing line ending at the very end of the text is a
      terminator, not an additional empty line after it -- "a\\n" is one
      line ("a"), not two. A terminator in the *middle* of the text still
      introduces a line exactly as normal, including an empty one for
      "a\\n\\n".
    - Trailing spaces and tabs are stripped from the end of every line.
      Leading whitespace and blank lines themselves are preserved exactly
      -- this never collapses, reflows, or otherwise rewrites content.
    - An empty (0-character) document has zero lines. A document
      consisting of exactly one line ending has exactly one (blank) line
      -- these are deliberately distinct.
    """
    if text == "":
        return ()
    stripped = _TRAILING_LINE_ENDING_PATTERN.sub("", text, count=1)
    if stripped == "":
        return ("",)
    return tuple(line.rstrip(" \t") for line in _LINE_SPLIT_PATTERN.split(stripped))
