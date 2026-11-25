"""Governed DuckDB analytics over Parquet datasets (§7).

Exposes only a fixed set of parameterized aggregations (sum, group-sum, reconcile)
over a Parquet file. Column names are validated against the file's actual schema
before use, so no caller — including the autonomous agent — can inject arbitrary
SQL. Decimal columns aggregate to exact :class:`~decimal.Decimal` values.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from strix.errors import StrixError


class AnalyticsError(StrixError):
    """Raised on an unknown column or an invalid analytical request."""


def _columns(path: Path) -> set[str]:
    return set(pq.read_schema(path).names)


def _require_column(path: Path, column: str) -> None:
    if column not in _columns(path):
        raise AnalyticsError(f"unknown column {column!r} in dataset {path.name}")


def _ident(column: str) -> str:
    """A safely-quoted SQL identifier (defense in depth; column is whitelisted too)."""
    return '"' + column.replace('"', '""') + '"'


def _connect(path: Path) -> duckdb.DuckDBPyConnection:
    if not path.is_file():
        raise AnalyticsError(f"dataset not found: {path}")
    return duckdb.connect(database=":memory:")


def sum_column(path: Path | str, column: str) -> Decimal:
    """Exact sum of a numeric/decimal column over the dataset."""
    path = Path(path)
    _require_column(path, column)
    con = _connect(path)
    try:
        # The file path is bound as a parameter; the (validated) column is a quoted
        # identifier — no user string is interpolated as SQL.
        row = con.execute(
            f'SELECT sum({_ident(column)}) FROM read_parquet(?)', [str(path)]
        ).fetchone()
    finally:
        con.close()
    value = row[0] if row else None
    return Decimal(0) if value is None else Decimal(str(value))


def group_sum(
    path: Path | str, *, group_column: str, value_column: str
) -> dict[str, Decimal]:
    """Exact sum of ``value_column`` grouped by ``group_column``."""
    path = Path(path)
    _require_column(path, group_column)
    _require_column(path, value_column)
    con = _connect(path)
    try:
        rows = con.execute(
            f'SELECT {_ident(group_column)}, sum({_ident(value_column)}) FROM read_parquet(?) '
            f'GROUP BY {_ident(group_column)}',
            [str(path)],
        ).fetchall()
    finally:
        con.close()
    return {str(key): Decimal(str(total)) for key, total in rows}


def reconcile_sum(path: Path | str, column: str, *, expected: Decimal) -> bool:
    """True iff the DuckDB sum of ``column`` equals ``expected`` exactly."""
    return sum_column(path, column) == expected
