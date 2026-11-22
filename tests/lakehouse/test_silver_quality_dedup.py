"""Tests for Silver quality gates and observation-level deduplication."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from tests.lakehouse.silver_fixtures import enrich

from strix.lakehouse.silver.dedup import deduplicate
from strix.lakehouse.silver.models import QuarantineReason
from strix.lakehouse.silver.quality import check_row
from strix.lakehouse.silver.schemas import SILVER_SCHEMAS

_T1 = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)
_T2 = datetime(2026, 11, 22, 11, 0, tzinfo=UTC)
_ALPACA = SILVER_SCHEMAS["alpaca_equity_bars_daily"]


def _bar(
    close: str = "101.0", high: str = "102.0", low: str = "99.0", volume: int = 1000
) -> dict[str, Any]:
    return {
        "symbol": "SPY", "timeframe": "1Day", "session_date": date(2026, 11, 20),
        "observation_ts": datetime(2026, 11, 20, 5, tzinfo=UTC),
        "open": Decimal("100.0"), "high": Decimal(high), "low": Decimal(low),
        "close": Decimal(close), "volume": volume, "trade_count": 10, "vwap": Decimal("100.5"),
        "source_locator": "/bars/0",
    }


# -- quality ---------------------------------------------------------------


def test_valid_bar_passes() -> None:
    assert check_row(_ALPACA, enrich("alpaca_equity_bars_daily", [_bar()])[0]) is None


def test_high_below_low_quarantined() -> None:
    row = enrich("alpaca_equity_bars_daily", [_bar(high="98.0", low="99.0")])[0]
    verdict = check_row(_ALPACA, row)
    assert verdict and verdict[0] is QuarantineReason.INVALID_OHLC


def test_negative_volume_quarantined() -> None:
    row = enrich("alpaca_equity_bars_daily", [_bar(volume=-5)])[0]
    verdict = check_row(_ALPACA, row)
    assert verdict and verdict[0] is QuarantineReason.NEGATIVE_VOLUME


def test_missing_required_field_quarantined() -> None:
    bar = _bar()
    bar["close"] = None
    row = enrich("alpaca_equity_bars_daily", [bar])[0]
    verdict = check_row(_ALPACA, row)
    assert verdict and verdict[0] is QuarantineReason.MISSING_REQUIRED_FIELD


def test_negative_economic_value_not_rejected() -> None:
    schema = SILVER_SCHEMAS["fred_observations"]
    row = enrich(
        "fred_observations",
        [{
            "series_id": "REALRATE", "observation_date": date(2026, 1, 1),
            "realtime_start": date(2026, 1, 2), "realtime_end": date(9999, 12, 31),
            "value": Decimal("-0.75"), "source_locator": "/observations/0",
        }],
    )[0]
    assert check_row(schema, row) is None  # negative rate is valid


# -- dedup -----------------------------------------------------------------


def test_identical_observations_dedup_to_one() -> None:
    a = enrich("alpaca_equity_bars_daily", [_bar()], retrieved_at=_T1, bronze_artifact_id="RAW-1")
    b = enrich("alpaca_equity_bars_daily", [_bar()], retrieved_at=_T2, bronze_artifact_id="RAW-2")
    result = deduplicate(_ALPACA, [a[0], b[0]])
    assert len(result.canonical) == 1
    assert result.duplicates == 1
    assert result.conflicts == []


def test_conflicting_value_keeps_latest_and_quarantines_prior() -> None:
    old = enrich("alpaca_equity_bars_daily", [_bar(close="101.0")], retrieved_at=_T1)[0]
    new = enrich("alpaca_equity_bars_daily", [_bar(close="101.5")], retrieved_at=_T2)[0]
    result = deduplicate(_ALPACA, [old, new])
    assert len(result.canonical) == 1
    assert result.canonical[0]["close"] == Decimal("101.5")  # latest retrieval wins
    assert len(result.conflicts) == 1  # prior value quarantined, not discarded


def test_sec_restatements_retained_as_revisions() -> None:
    schema = SILVER_SCHEMAS["sec_company_facts"]

    def fact(accn: str, val: str) -> dict[str, Any]:
        return {
            "cik": "CIK0000320193", "taxonomy": "us-gaap", "concept": "Revenues", "unit": "USD",
            "period_start": date(2025, 6, 29), "period_end": date(2025, 9, 27),
            "fiscal_year": 2025, "fiscal_period": "Q4", "form": "10-K",
            "filed_date": date(2025, 10, 31), "accession": accn, "frame": None,
            "value": Decimal(val), "source_locator": "/x",
        }

    rows = enrich("sec_company_facts", [fact("accn-1", "100"), fact("accn-2", "102")])
    result = deduplicate(schema, rows)
    assert len(result.canonical) == 2  # distinct accessions -> both kept
    assert result.duplicates == 0
    assert result.revisions_retained == 1  # one restatement of the same period
