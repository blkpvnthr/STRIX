"""Offline OFX/QFX statement import: Bronze (raw) -> Silver (normalized).

This is the bank-statement sibling of :mod:`strix.finance.imports` (CSV). It
parses an *in-memory* OFX or QFX string (never a file handle, path, or URL —
no I/O, no network) into two parallel, typed, content-addressed layers:

* **Bronze** — :class:`RawOfxTransaction`: each original ``<STMTTRN>`` block
  preserved verbatim, its extracted leaf tags, and a canonical SHA-256 digest
  of the raw block text. This layer is lossless; it is what later auditing and
  reconciliation steps replay.
* **Silver** — :class:`NormalizedTransaction`: the OFX tags mapped onto the one
  shared normalized shape. ``<TRNAMT>`` becomes an exact signed
  :class:`~decimal.Decimal` (negative = outflow/debit, positive = inflow);
  ``<DTPOSTED>`` (``YYYYMMDD`` with an optional ``HHMMSS`` time and ``[tz]``
  suffix) becomes a :class:`datetime.date`; ``<NAME>`` (falling back to
  ``<MEMO>``) becomes the description. Every normalized row carries the digest
  of its originating block and a deterministic ``TXN-`` content identifier.

OFX is SGML-like: leaf elements are commonly written *without* a closing tag
(``<TRNAMT>-42.50`` followed by a newline), while some exporters do close them
(``<TRNAMT>-42.50</TRNAMT>``). QFX is OFX with a Quicken-specific header; the
statement body is identical. This parser is tolerant of both: a leaf value runs
from ``<TAG>`` to the next ``<`` or line break, and ``<STMTTRN>`` blocks are
split whether or not ``</STMTTRN>`` is present.

Design rules this module upholds (shared with :mod:`strix.finance.ledger`):

* Models are frozen and closed (``strix.models.StrixModel``).
* Monetary amounts use ``strix.models.DecimalValue`` — binary ``float`` is
  rejected at the model boundary; no amount is ever a ``float``.
* Content-derived identifiers and digests come from ``strix.canonical``; an id
  never participates in its own payload.
* Malformed input (unparseable/missing amount or date) raises
  :class:`~strix.finance.ledger.FinanceError` naming the offending transaction
  index (its 0-based ordinal among the ``<STMTTRN>`` blocks).

Exact-duplicate blocks are *not* collapsed here: every block is preserved.
Dedup / duplicate detection is a deliberately separate downstream step.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from strix.canonical import sha256_hex
from strix.finance.ledger import FinanceError
from strix.finance.transactions import NormalizedTransaction, make_transaction
from strix.models import StrixModel

__all__ = [
    "NormalizedTransaction",
    "RawOfxTransaction",
    "import_ofx",
]

#: Inner content of each ``<STMTTRN>`` block. Lazily consumes up to the next
#: ``</STMTTRN>``, the next ``<STMTTRN>``, the end of the transaction list, or
#: the end of the document — tolerating both closed and unclosed blocks.
_BLOCK_RE = re.compile(
    r"<STMTTRN>(.*?)(?=</STMTTRN>|<STMTTRN>|</BANKTRANLIST>|\Z)",
    re.DOTALL | re.IGNORECASE,
)

#: Leaf-tag value: from ``<TAG>`` to the next ``<`` or line break. Captures the
#: value whether the element is closed (``<TAG>v</TAG>``) or not (``<TAG>v``).
_TAG_NAMES = ("TRNTYPE", "DTPOSTED", "TRNAMT", "FITID", "NAME", "MEMO")


class RawOfxTransaction(StrixModel):
    """Bronze layer: one ``<STMTTRN>`` block preserved exactly as read.

    ``raw`` is the verbatim inner text of the block; ``tags`` maps each
    recognized leaf tag (``FITID``, ``TRNAMT``, ``DTPOSTED``, ``NAME``,
    ``MEMO``, ``TRNTYPE``) to its extracted value; ``source_digest`` is the
    SHA-256 of ``raw`` (UTF-8) and binds the preserved block to its downstream
    normalized form.
    """

    block_index: int
    #: Verbatim inner text of the ``<STMTTRN>`` block.
    raw: str
    #: Extracted leaf tags keyed by tag name (e.g. ``FITID``).
    tags: dict[str, str]
    #: SHA-256 hex digest of the UTF-8 bytes of ``raw``.
    source_digest: str


def _extract_tag(block: str, tag: str) -> str | None:
    """Extract a single leaf-tag value from a ``<STMTTRN>`` block.

    Returns the stripped value, or ``None`` when the tag is absent. Tolerant of
    both closed (``<TAG>v</TAG>``) and unclosed (``<TAG>v``) leaf elements.
    """
    match = re.search(rf"<{tag}>([^<\r\n]*)", block, re.IGNORECASE)
    if match is None:
        return None
    return match.group(1).strip()


def _extract_tags(block: str) -> dict[str, str]:
    """Extract every recognized leaf tag present in *block* into a mapping."""
    tags: dict[str, str] = {}
    for name in _TAG_NAMES:
        value = _extract_tag(block, name)
        if value is not None:
            tags[name] = value
    return tags


def _parse_amount(text: str | None, *, index: int) -> Decimal:
    """Parse a signed, finite :class:`~decimal.Decimal` from ``<TRNAMT>``.

    Raises :class:`FinanceError` (naming the transaction ``index``) when the
    tag is missing, empty, or not an exact finite decimal.
    """
    if text is None or not text.strip():
        raise FinanceError(
            f"transaction {index}: missing or empty amount (<TRNAMT>)"
        )
    try:
        amount = Decimal(text.strip())
    except InvalidOperation as exc:
        raise FinanceError(
            f"transaction {index}: malformed amount {text!r}"
        ) from exc
    if not amount.is_finite():
        raise FinanceError(
            f"transaction {index}: non-finite amount {text!r}"
        )
    return amount


def _parse_date(text: str | None, *, index: int) -> date:
    """Parse a :class:`datetime.date` from an OFX ``<DTPOSTED>`` value.

    OFX datetimes are ``YYYYMMDD`` with an optional ``HHMMSS`` time and an
    optional ``[offset:TZ]`` suffix; only the ``YYYYMMDD`` date portion is
    used. Raises :class:`FinanceError` (naming the transaction ``index``) when
    the tag is missing or the date portion is not a valid calendar date.
    """
    if text is None or not text.strip():
        raise FinanceError(
            f"transaction {index}: missing or empty date (<DTPOSTED>)"
        )
    core = text.strip().split("[", 1)[0].strip()
    if len(core) < 8 or not core[:8].isdigit():
        raise FinanceError(
            f"transaction {index}: malformed date {text!r} "
            f"(expected YYYYMMDD[HHMMSS])"
        )
    try:
        return datetime.strptime(core[:8], "%Y%m%d").date()
    except ValueError as exc:
        raise FinanceError(
            f"transaction {index}: malformed date {text!r} "
            f"(expected YYYYMMDD[HHMMSS])"
        ) from exc


def import_ofx(
    ofx_text: str,
    *,
    account_id: str,
) -> tuple[tuple[RawOfxTransaction, ...], tuple[NormalizedTransaction, ...]]:
    """Parse an in-memory OFX/QFX string into Bronze + Silver transactions.

    Each ``<STMTTRN>`` block becomes one :class:`RawOfxTransaction` (verbatim
    block text, extracted leaf tags, and the SHA-256 of the block) and one
    :class:`NormalizedTransaction` (``<TRNAMT>`` as a signed exact
    :class:`~decimal.Decimal`, ``<DTPOSTED>`` parsed to a date, ``<NAME>`` —
    or ``<MEMO>`` when ``<NAME>`` is absent — as the description).
    ``account_id`` is attached to every normalized row as its owning account.

    Returns a pair of equal-length tuples ``(raw, normalized)`` in document
    order; input with no ``<STMTTRN>`` blocks (including the empty string)
    returns ``((), ())``. Blocks are never deduplicated. Raises
    :class:`FinanceError` (naming the transaction index) for a missing or
    unparseable amount or date.
    """
    raw_txns: list[RawOfxTransaction] = []
    normalized_txns: list[NormalizedTransaction] = []

    for index, match in enumerate(_BLOCK_RE.finditer(ofx_text)):
        block = match.group(1)
        tags = _extract_tags(block)
        source_digest = sha256_hex(block.encode("utf-8"))
        raw_txns.append(
            RawOfxTransaction(
                block_index=index,
                raw=block,
                tags=tags,
                source_digest=source_digest,
            )
        )

        amount = _parse_amount(tags.get("TRNAMT"), index=index)
        posted_date = _parse_date(tags.get("DTPOSTED"), index=index)
        description = tags.get("NAME") or tags.get("MEMO") or ""

        normalized_txns.append(
            make_transaction(
                posted_date=posted_date,
                amount=amount,
                account_id=account_id,
                description=description,
                raw_digest=source_digest,
            )
        )

    return tuple(raw_txns), tuple(normalized_txns)
