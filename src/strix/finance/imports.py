"""Offline CSV transaction import: Bronze (raw) -> Silver (normalized).

This is the miniature ingestion stage of the offline personal-finance engine.
It parses an *in-memory* CSV string (never a file handle, path, or URL — no
I/O, no network) from an arbitrary provider export into two parallel, typed,
content-addressed layers:

* **Bronze** — :class:`RawTransaction`: every original cell preserved verbatim
  under its header, plus a canonical SHA-256 digest of the raw row. This layer
  is lossless; it is what later auditing and reconciliation steps replay.
* **Silver** — :class:`NormalizedTransaction`: the provider columns mapped onto
  a normalized shape via a :class:`CsvSchema`. Dates are parsed with the
  schema's format; amounts are exact signed :class:`~decimal.Decimal` values
  (negative = outflow/debit from the account, positive = inflow). Every
  normalized row carries the digest of its originating raw row and a
  deterministic ``TXN-`` content identifier.

Design rules this module upholds (shared with :mod:`strix.finance.ledger`):

* Models are frozen and closed (``strix.models.StrixModel``).
* Monetary amounts use ``strix.models.DecimalValue`` — binary ``float`` is
  rejected at the model boundary; no amount is ever a ``float``.
* Content-derived identifiers and digests come from ``strix.canonical``; an id
  never participates in its own payload.
* Malformed input (unparseable amount or date, a missing mapped column) raises
  :class:`~strix.finance.ledger.FinanceError` naming the offending row index.

Exact-duplicate rows are *not* collapsed here: every row is preserved. Dedup /
duplicate detection is a deliberately separate downstream step.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from strix.canonical import canonical_hash, make_id
from strix.finance.ledger import FinanceError
from strix.finance.transactions import NormalizedTransaction
from strix.models import StrixModel

__all__ = [
    "CsvSchema",
    "NormalizedTransaction",
    "RawTransaction",
    "import_csv",
]


class RawTransaction(StrixModel):
    """Bronze layer: one CSV data row preserved exactly as read.

    ``raw`` maps each header name to its original cell text (verbatim, never
    coerced); ``source_digest`` is the canonical SHA-256 of ``raw`` and binds
    the preserved row to its downstream normalized form.
    """

    row_index: int
    #: Original cells keyed by header, preserved verbatim.
    raw: dict[str, str]
    #: SHA-256 hex digest of the canonical serialization of ``raw``.
    source_digest: str


class CsvSchema(StrixModel):
    """Mapping from a provider's CSV columns onto the normalized fields.

    ``date_format`` is a :func:`datetime.datetime.strptime` pattern applied to
    the ``date_col`` cell (default ISO ``%Y-%m-%d``).
    """

    date_col: str
    amount_col: str
    description_col: str
    date_format: str = "%Y-%m-%d"


def _parse_amount(text: str, *, row_index: int) -> Decimal:
    """Parse a signed, finite :class:`~decimal.Decimal` amount from a cell.

    Raises :class:`FinanceError` (naming ``row_index``) for an empty cell or
    any value that is not an exact finite decimal.
    """
    stripped = text.strip()
    if not stripped:
        raise FinanceError(f"row {row_index}: amount cell is empty")
    try:
        amount = Decimal(stripped)
    except InvalidOperation as exc:
        raise FinanceError(
            f"row {row_index}: malformed amount {text!r}"
        ) from exc
    if not amount.is_finite():
        raise FinanceError(
            f"row {row_index}: non-finite amount {text!r}"
        )
    return amount


def _parse_date(text: str, *, date_format: str, row_index: int) -> date:
    """Parse a :class:`datetime.date` from a cell under ``date_format``.

    Raises :class:`FinanceError` (naming ``row_index``) for any value that
    does not match the schema's date format.
    """
    try:
        return datetime.strptime(text.strip(), date_format).date()
    except ValueError as exc:
        raise FinanceError(
            f"row {row_index}: malformed date {text!r} "
            f"(expected format {date_format!r})"
        ) from exc


def import_csv(
    csv_text: str,
    schema: CsvSchema,
    *,
    account_id: str,
) -> tuple[tuple[RawTransaction, ...], tuple[NormalizedTransaction, ...]]:
    """Parse an in-memory CSV string into Bronze + Silver transactions.

    The first non-blank line is the header. Each subsequent non-blank line
    becomes one :class:`RawTransaction` (cells preserved verbatim, keyed by
    header) and one :class:`NormalizedTransaction` (columns mapped via
    *schema*, amount as a signed exact :class:`~decimal.Decimal`, date parsed
    with the schema format). ``account_id`` is attached to every normalized
    row as its owning account.

    Returns a pair of equal-length tuples ``(raw, normalized)`` in file order;
    an empty or header-only input returns ``((), ())``. Rows are never
    deduplicated. Raises :class:`FinanceError` (naming the row index) for a
    missing mapped column or an unparseable amount or date.
    """
    reader = csv.reader(io.StringIO(csv_text))
    rows = [row for row in reader if row]
    if not rows:
        return (), ()

    header = rows[0]
    for required in (schema.date_col, schema.amount_col, schema.description_col):
        if required not in header:
            raise FinanceError(
                f"CSV header is missing required column {required!r}; "
                f"header has {header!r}"
            )

    raw_txns: list[RawTransaction] = []
    normalized_txns: list[NormalizedTransaction] = []

    for row_index, cells in enumerate(rows[1:]):
        raw_row: dict[str, str] = dict(zip(header, cells, strict=False))
        missing = [
            col
            for col in (
                schema.date_col,
                schema.amount_col,
                schema.description_col,
            )
            if col not in raw_row
        ]
        if missing:
            raise FinanceError(
                f"row {row_index}: short row is missing cells for {missing!r}"
            )

        source_digest = canonical_hash(raw_row)
        raw_txns.append(
            RawTransaction(
                row_index=row_index,
                raw=raw_row,
                source_digest=source_digest,
            )
        )

        amount = _parse_amount(raw_row[schema.amount_col], row_index=row_index)
        posted_date = _parse_date(
            raw_row[schema.date_col],
            date_format=schema.date_format,
            row_index=row_index,
        )
        description = raw_row[schema.description_col]

        payload: Mapping[str, object] = {
            "posted_date": posted_date,
            "amount": amount,
            "description": description,
            "raw_digest": source_digest,
            "account_id": account_id,
        }
        normalized_txns.append(
            NormalizedTransaction(
                txn_id=make_id("TXN", payload),
                posted_date=posted_date,
                amount=amount,
                description=description,
                raw_digest=source_digest,
                account_id=account_id,
            )
        )

    return tuple(raw_txns), tuple(normalized_txns)
