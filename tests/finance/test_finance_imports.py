"""Tests for offline CSV transaction import (Bronze -> Silver)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.canonical import canonical_hash
from strix.finance.imports import (
    CsvSchema,
    NormalizedTransaction,
    RawTransaction,
    import_csv,
)
from strix.finance.ledger import FinanceError

_ACCOUNT_ID = "ACCT-000000000000"

_SCHEMA = CsvSchema(
    date_col="Date",
    amount_col="Amount",
    description_col="Description",
)

_THREE_ROWS = (
    "Date,Amount,Description\n"
    "2024-01-05,-42.50,Coffee Shop\n"
    "2024-01-06,1500.00,Paycheck\n"
    "2024-01-07,-9.99,Streaming\n"
)


def test_three_row_csv_imports_three_raw_and_normalized() -> None:
    raw, normalized = import_csv(_THREE_ROWS, _SCHEMA, account_id=_ACCOUNT_ID)

    assert len(raw) == 3
    assert len(normalized) == 3

    # Signed amounts: negative outflow, positive inflow.
    assert [n.amount for n in normalized] == [
        Decimal("-42.50"),
        Decimal("1500.00"),
        Decimal("-9.99"),
    ]
    assert [n.posted_date for n in normalized] == [
        date(2024, 1, 5),
        date(2024, 1, 6),
        date(2024, 1, 7),
    ]
    assert [n.description for n in normalized] == [
        "Coffee Shop",
        "Paycheck",
        "Streaming",
    ]
    assert all(n.account_id == _ACCOUNT_ID for n in normalized)
    assert all(n.txn_id.startswith("TXN-") for n in normalized)


def test_raw_row_preserved_verbatim_with_digest() -> None:
    raw, _ = import_csv(_THREE_ROWS, _SCHEMA, account_id=_ACCOUNT_ID)

    first = raw[0]
    assert isinstance(first, RawTransaction)
    assert first.row_index == 0
    assert first.raw == {
        "Date": "2024-01-05",
        "Amount": "-42.50",
        "Description": "Coffee Shop",
    }
    assert first.source_digest == canonical_hash(first.raw)
    assert len(first.source_digest) == 64


def test_raw_digest_links_normalized_to_raw() -> None:
    raw, normalized = import_csv(_THREE_ROWS, _SCHEMA, account_id=_ACCOUNT_ID)
    for r, n in zip(raw, normalized, strict=True):
        assert n.raw_digest == r.source_digest


def test_malformed_amount_raises_finance_error_naming_row() -> None:
    bad = (
        "Date,Amount,Description\n"
        "2024-01-05,-42.50,Coffee\n"
        "2024-01-06,not-a-number,Mystery\n"
    )
    with pytest.raises(FinanceError) as excinfo:
        import_csv(bad, _SCHEMA, account_id=_ACCOUNT_ID)
    assert "1" in str(excinfo.value)
    assert "amount" in str(excinfo.value).lower()


def test_malformed_date_raises_finance_error_naming_row() -> None:
    bad = (
        "Date,Amount,Description\n"
        "2024-01-05,-42.50,Coffee\n"
        "05/13/2024,10.00,Bad Date\n"
    )
    with pytest.raises(FinanceError) as excinfo:
        import_csv(bad, _SCHEMA, account_id=_ACCOUNT_ID)
    assert "1" in str(excinfo.value)
    assert "date" in str(excinfo.value).lower()


def test_missing_column_raises_finance_error() -> None:
    schema = CsvSchema(
        date_col="PostedOn",
        amount_col="Amount",
        description_col="Description",
    )
    with pytest.raises(FinanceError) as excinfo:
        import_csv(_THREE_ROWS, schema, account_id=_ACCOUNT_ID)
    assert "PostedOn" in str(excinfo.value)


def test_comma_and_quote_escaped_field_parses() -> None:
    text = (
        "Date,Amount,Description\n"
        '2024-02-01,-20.00,"Groceries, Market & Co ""deli"""\n'
    )
    raw, normalized = import_csv(text, _SCHEMA, account_id=_ACCOUNT_ID)
    assert len(normalized) == 1
    assert normalized[0].description == 'Groceries, Market & Co "deli"'
    assert raw[0].raw["Description"] == 'Groceries, Market & Co "deli"'


def test_empty_csv_yields_empty_tuples() -> None:
    raw, normalized = import_csv("", _SCHEMA, account_id=_ACCOUNT_ID)
    assert raw == ()
    assert normalized == ()


def test_header_only_csv_yields_empty_tuples() -> None:
    raw, normalized = import_csv(
        "Date,Amount,Description\n", _SCHEMA, account_id=_ACCOUNT_ID
    )
    assert raw == ()
    assert normalized == ()


def test_blank_lines_are_skipped() -> None:
    text = (
        "Date,Amount,Description\n"
        "2024-01-05,-42.50,Coffee\n"
        "\n"
        "2024-01-06,1500.00,Paycheck\n"
    )
    _raw, normalized = import_csv(text, _SCHEMA, account_id=_ACCOUNT_ID)
    assert len(normalized) == 2


def test_ids_are_deterministic() -> None:
    _, first = import_csv(_THREE_ROWS, _SCHEMA, account_id=_ACCOUNT_ID)
    _, second = import_csv(_THREE_ROWS, _SCHEMA, account_id=_ACCOUNT_ID)
    assert [n.txn_id for n in first] == [n.txn_id for n in second]


def test_float_amount_rejected_at_model_boundary() -> None:
    with pytest.raises(ValidationError):
        NormalizedTransaction(
            txn_id="TXN-000000000000",
            posted_date=date(2024, 1, 1),
            amount=1.5,
            description="float money",
            raw_digest="0" * 64,
            account_id=_ACCOUNT_ID,
        )


def test_raw_transaction_is_frozen() -> None:
    raw, _ = import_csv(_THREE_ROWS, _SCHEMA, account_id=_ACCOUNT_ID)
    with pytest.raises(ValidationError):
        raw[0].row_index = 99  # type: ignore[misc]


def test_custom_date_format_parses() -> None:
    schema = CsvSchema(
        date_col="Date",
        amount_col="Amount",
        description_col="Description",
        date_format="%m/%d/%Y",
    )
    text = "Date,Amount,Description\n01/05/2024,-42.50,Coffee\n"
    _, normalized = import_csv(text, schema, account_id=_ACCOUNT_ID)
    assert normalized[0].posted_date == date(2024, 1, 5)


def test_empty_amount_cell_raises_finance_error() -> None:
    bad = "Date,Amount,Description\n2024-01-05,,Coffee\n"
    with pytest.raises(FinanceError) as excinfo:
        import_csv(bad, _SCHEMA, account_id=_ACCOUNT_ID)
    assert "amount" in str(excinfo.value).lower()
