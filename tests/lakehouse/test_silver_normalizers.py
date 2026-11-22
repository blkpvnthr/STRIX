"""Tests for the five Bronze->Silver normalizers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from tests.lakehouse.silver_fixtures import (
    ALPACA_BARS,
    BLS_PAYLOAD,
    FRED_PAYLOAD,
    SEC_FACTS,
    TREASURY_XML,
    mk_manifest,
)

from strix.lakehouse.contracts import DataSource
from strix.lakehouse.silver.normalizers import (
    normalize_alpaca_bars,
    normalize_bls,
    normalize_fred,
    normalize_sec_company_facts,
    normalize_treasury_yields,
)


def test_alpaca_decimal_precision_and_session_date() -> None:
    m = mk_manifest(DataSource.ALPACA, "equity_bars_daily", entity="SPY",
                    params={"timeframe": "1Day"})
    rows = normalize_alpaca_bars(ALPACA_BARS, m)
    assert len(rows) == 2
    assert rows[1]["close"] == Decimal("102.25")  # exact Decimal, no float drift
    assert rows[1]["session_date"] == date(2026, 11, 20)
    assert rows[0]["symbol"] == "SPY"
    assert rows[0]["volume"] == 1000000


def test_sec_nested_observation_with_lineage() -> None:
    m = mk_manifest(DataSource.SEC_EDGAR, "company_facts", entity="AAPL")
    rows = normalize_sec_company_facts(SEC_FACTS, m)
    assert len(rows) == 1
    row = rows[0]
    assert row["cik"] == "CIK0000320193"
    assert row["concept"] == "Revenues"
    assert row["value"] == Decimal("102000000000")
    assert row["accession"] == "0000320193-25-000100"
    assert row["source_locator"] == "/facts/us-gaap/Revenues/units/USD/0"


def test_treasury_tenors_skip_empty() -> None:
    m = mk_manifest(DataSource.US_TREASURY, "daily_treasury_yield_curve", entity=None)
    rows = normalize_treasury_yields(TREASURY_XML, m)
    tenors = {r["tenor"]: r["yield_pct"] for r in rows}
    assert tenors == {"2Y": Decimal("4.12"), "10Y": Decimal("4.45")}  # empty 30Y skipped
    assert rows[0]["date"] == date(2026, 11, 20)


def test_bls_monthly_not_daily() -> None:
    m = mk_manifest(DataSource.BLS, "timeseries", entity="CUUR0000SA0")
    rows = normalize_bls(BLS_PAYLOAD, m)
    assert len(rows) == 2
    assert rows[0]["frequency"] == "monthly"
    assert rows[0]["period"] == "M10"
    assert rows[0]["observation_date"] == date(2026, 10, 1)  # first-of-month, NOT daily
    assert rows[0]["value"] == Decimal("315.5")


def test_fred_missing_value_is_null_not_rejected() -> None:
    m = mk_manifest(DataSource.FRED, "series_observations", entity="DGS10",
                    params={"series_id": "DGS10"})
    rows = normalize_fred(FRED_PAYLOAD, m)
    assert len(rows) == 2
    assert rows[0]["value"] == Decimal("4.45")
    assert rows[1]["value"] is None  # '.' -> null, kept (not discarded)
    assert rows[0]["realtime_start"] == date(2026, 11, 20)  # vintage retained
