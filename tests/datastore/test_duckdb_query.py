"""Tests for governed DuckDB analytics over Parquet datasets (§7)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pytest

from strix.datastore.duckdb_query import AnalyticsError, group_sum, reconcile_sum, sum_column
from strix.datastore.parquet_dataset import write_dataset

_SCHEMA = pa.schema([("category", pa.string()), ("amount", pa.decimal128(18, 2))])


def _dataset(tmp_path: Path) -> Path:
    table = pa.table(
        {
            "category": ["groceries", "dining", "groceries"],
            "amount": [Decimal("10.50"), Decimal("20.25"), Decimal("5.25")],
        },
        schema=_SCHEMA,
    )
    write_dataset(name="spend", table=table, directory=tmp_path, version=1)
    return tmp_path / "spend-v1.parquet"


def test_sum_column_is_exact_decimal(tmp_path: Path) -> None:
    total = sum_column(_dataset(tmp_path), "amount")
    assert total == Decimal("36.00")  # 10.50 + 20.25 + 5.25


def test_group_sum(tmp_path: Path) -> None:
    grouped = group_sum(_dataset(tmp_path), group_column="category", value_column="amount")
    assert grouped == {"groceries": Decimal("15.75"), "dining": Decimal("20.25")}


def test_reconcile_sum(tmp_path: Path) -> None:
    path = _dataset(tmp_path)
    assert reconcile_sum(path, "amount", expected=Decimal("36.00")) is True
    assert reconcile_sum(path, "amount", expected=Decimal("99.99")) is False


def test_unknown_column_is_rejected_no_injection(tmp_path: Path) -> None:
    path = _dataset(tmp_path)
    # A column name not in the schema (incl. a SQL-injection attempt) must be rejected.
    with pytest.raises(AnalyticsError):
        sum_column(path, "amount; DROP TABLE x;--")
    with pytest.raises(AnalyticsError):
        group_sum(path, group_column="nope", value_column="amount")


def test_column_name_with_quote_is_handled_safely(tmp_path: Path) -> None:
    # A legitimately-present column whose name contains a double-quote must be
    # safely quoted (escaped), not allow identifier-break injection.
    schema = pa.schema([('we"ird', pa.decimal128(18, 2))])
    table = pa.table({'we"ird': [Decimal("1.00"), Decimal("2.00")]}, schema=schema)
    write_dataset(name="q", table=table, directory=tmp_path, version=1)
    assert sum_column(tmp_path / "q-v1.parquet", 'we"ird') == Decimal("3.00")
