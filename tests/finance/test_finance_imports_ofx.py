"""Tests for offline OFX/QFX statement import (Bronze -> Silver)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.canonical import sha256_hex
from strix.finance.imports_ofx import (
    NormalizedTransaction,
    RawOfxTransaction,
    import_ofx,
)
from strix.finance.ledger import FinanceError

_ACCOUNT_ID = "ACCT-000000000000"

# A minimal but realistic OFX (SGML) body with unclosed leaf tags, the common
# shape real banks export. Two STMTTRN blocks.
_TWO_TXN_OFX = (
    "OFXHEADER:100\n"
    "DATA:OFXSGML\n"
    "VERSION:102\n"
    "\n"
    "<OFX>\n"
    "<BANKMSGSRSV1>\n"
    "<STMTTRNRS>\n"
    "<BANKTRANLIST>\n"
    "<STMTTRN>\n"
    "<TRNTYPE>DEBIT\n"
    "<DTPOSTED>20240105120000[-5:EST]\n"
    "<TRNAMT>-42.50\n"
    "<FITID>F001\n"
    "<NAME>Coffee Shop\n"
    "</STMTTRN>\n"
    "<STMTTRN>\n"
    "<TRNTYPE>CREDIT\n"
    "<DTPOSTED>20240106\n"
    "<TRNAMT>1500.00\n"
    "<FITID>F002\n"
    "<NAME>Paycheck\n"
    "<MEMO>Monthly salary\n"
    "</STMTTRN>\n"
    "</BANKTRANLIST>\n"
    "</STMTTRNRS>\n"
    "</BANKMSGSRSV1>\n"
    "</OFX>\n"
)

# QFX uses the exact same statement body; the extension differs, the parse
# does not.
_TWO_TXN_QFX = _TWO_TXN_OFX


def test_two_transaction_ofx_imports_two_normalized() -> None:
    raw, normalized = import_ofx(_TWO_TXN_OFX, account_id=_ACCOUNT_ID)

    assert len(raw) == 2
    assert len(normalized) == 2

    assert [n.amount for n in normalized] == [
        Decimal("-42.50"),
        Decimal("1500.00"),
    ]
    assert [n.posted_date for n in normalized] == [
        date(2024, 1, 5),
        date(2024, 1, 6),
    ]
    assert [n.description for n in normalized] == ["Coffee Shop", "Paycheck"]
    assert all(n.account_id == _ACCOUNT_ID for n in normalized)
    assert all(n.txn_id.startswith("TXN-") for n in normalized)


def test_signed_amounts_are_exact_decimal() -> None:
    _, normalized = import_ofx(_TWO_TXN_OFX, account_id=_ACCOUNT_ID)
    for n in normalized:
        assert isinstance(n.amount, Decimal)
        assert not isinstance(n.amount, float)


def test_fitid_preserved_in_raw() -> None:
    raw, _ = import_ofx(_TWO_TXN_OFX, account_id=_ACCOUNT_ID)
    assert isinstance(raw[0], RawOfxTransaction)
    assert raw[0].tags["FITID"] == "F001"
    assert raw[1].tags["FITID"] == "F002"
    # The verbatim block text also carries the FITID.
    assert "F001" in raw[0].raw


def test_raw_block_digest_matches_sha256_of_block() -> None:
    raw, _ = import_ofx(_TWO_TXN_OFX, account_id=_ACCOUNT_ID)
    first = raw[0]
    assert first.source_digest == sha256_hex(first.raw.encode("utf-8"))
    assert len(first.source_digest) == 64


def test_raw_digest_links_normalized_to_raw() -> None:
    raw, normalized = import_ofx(_TWO_TXN_OFX, account_id=_ACCOUNT_ID)
    for r, n in zip(raw, normalized, strict=True):
        assert n.raw_digest == r.source_digest


def test_block_index_is_ordinal() -> None:
    raw, _ = import_ofx(_TWO_TXN_OFX, account_id=_ACCOUNT_ID)
    assert [r.block_index for r in raw] == [0, 1]


def test_memo_used_when_name_absent() -> None:
    text = (
        "<OFX><STMTTRN>"
        "<DTPOSTED>20240201<TRNAMT>-20.00<FITID>F010"
        "<MEMO>Grocery Market"
        "</STMTTRN></OFX>"
    )
    _, normalized = import_ofx(text, account_id=_ACCOUNT_ID)
    assert normalized[0].description == "Grocery Market"


def test_qfx_body_parses_identically() -> None:
    raw_ofx, norm_ofx = import_ofx(_TWO_TXN_OFX, account_id=_ACCOUNT_ID)
    raw_qfx, norm_qfx = import_ofx(_TWO_TXN_QFX, account_id=_ACCOUNT_ID)
    assert [n.txn_id for n in norm_ofx] == [n.txn_id for n in norm_qfx]
    assert [r.source_digest for r in raw_ofx] == [
        r.source_digest for r in raw_qfx
    ]


def test_malformed_amount_raises_finance_error_naming_index() -> None:
    bad = (
        "<OFX>"
        "<STMTTRN><DTPOSTED>20240105<TRNAMT>-42.50<FITID>A"
        "<NAME>Good</STMTTRN>"
        "<STMTTRN><DTPOSTED>20240106<TRNAMT>not-a-number<FITID>B"
        "<NAME>Bad</STMTTRN>"
        "</OFX>"
    )
    with pytest.raises(FinanceError) as excinfo:
        import_ofx(bad, account_id=_ACCOUNT_ID)
    assert "1" in str(excinfo.value)
    assert "amount" in str(excinfo.value).lower()


def test_missing_amount_raises_finance_error() -> None:
    bad = (
        "<OFX><STMTTRN>"
        "<DTPOSTED>20240105<FITID>A<NAME>No amount"
        "</STMTTRN></OFX>"
    )
    with pytest.raises(FinanceError) as excinfo:
        import_ofx(bad, account_id=_ACCOUNT_ID)
    assert "0" in str(excinfo.value)
    assert "amount" in str(excinfo.value).lower()


def test_malformed_date_raises_finance_error_naming_index() -> None:
    bad = (
        "<OFX>"
        "<STMTTRN><DTPOSTED>20240105<TRNAMT>-1.00<FITID>A"
        "<NAME>Good</STMTTRN>"
        "<STMTTRN><DTPOSTED>2024-13-99<TRNAMT>-2.00<FITID>B"
        "<NAME>Bad</STMTTRN>"
        "</OFX>"
    )
    with pytest.raises(FinanceError) as excinfo:
        import_ofx(bad, account_id=_ACCOUNT_ID)
    assert "1" in str(excinfo.value)
    assert "date" in str(excinfo.value).lower()


def test_missing_date_raises_finance_error() -> None:
    bad = (
        "<OFX><STMTTRN>"
        "<TRNAMT>-1.00<FITID>A<NAME>No date"
        "</STMTTRN></OFX>"
    )
    with pytest.raises(FinanceError) as excinfo:
        import_ofx(bad, account_id=_ACCOUNT_ID)
    assert "date" in str(excinfo.value).lower()


def test_empty_input_yields_empty_tuples() -> None:
    raw, normalized = import_ofx("", account_id=_ACCOUNT_ID)
    assert raw == ()
    assert normalized == ()


def test_no_transactions_yields_empty_tuples() -> None:
    text = "<OFX><BANKMSGSRSV1></BANKMSGSRSV1></OFX>"
    raw, normalized = import_ofx(text, account_id=_ACCOUNT_ID)
    assert raw == ()
    assert normalized == ()


def test_ids_are_deterministic() -> None:
    _, first = import_ofx(_TWO_TXN_OFX, account_id=_ACCOUNT_ID)
    _, second = import_ofx(_TWO_TXN_OFX, account_id=_ACCOUNT_ID)
    assert [n.txn_id for n in first] == [n.txn_id for n in second]


def test_raw_transaction_is_frozen() -> None:
    raw, _ = import_ofx(_TWO_TXN_OFX, account_id=_ACCOUNT_ID)
    with pytest.raises(ValidationError):
        raw[0].block_index = 99  # type: ignore[misc]


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


def test_closed_leaf_tags_also_parse() -> None:
    # Some exporters DO close leaf tags; tolerant extraction handles both.
    text = (
        "<OFX><STMTTRN>"
        "<DTPOSTED>20240105</DTPOSTED>"
        "<TRNAMT>-7.25</TRNAMT>"
        "<FITID>Z9</FITID>"
        "<NAME>Closed Tags</NAME>"
        "</STMTTRN></OFX>"
    )
    raw, normalized = import_ofx(text, account_id=_ACCOUNT_ID)
    assert normalized[0].amount == Decimal("-7.25")
    assert normalized[0].posted_date == date(2024, 1, 5)
    assert normalized[0].description == "Closed Tags"
    assert raw[0].tags["FITID"] == "Z9"
