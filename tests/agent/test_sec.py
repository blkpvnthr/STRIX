"""Tests for the SEC EDGAR concept-series connector (offline, injected fetch)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from strix.agent.connectors.sec import SecConnector
from strix.agent.sources import BarsData, UnavailableSource
from strix.sources.edgar import COMPANYFACTS_URL, TICKER_MAP_URL

_TICKER_MAP = json.dumps({"0": {"ticker": "AAPL", "cik_str": 320193, "title": "Apple"}}).encode()

_COMPANYFACTS = json.dumps(
    {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"start": "2024-07-01", "end": "2024-09-28", "filed": "2024-11-01",
                             "val": 94930000000},
                            {"start": "2025-06-29", "end": "2025-09-27", "filed": "2025-10-31",
                             "val": 102000000000},
                        ]
                    }
                }
            }
        },
    }
).encode()


def _fetch(url: str) -> bytes:
    if url == TICKER_MAP_URL:
        return _TICKER_MAP
    if url == COMPANYFACTS_URL.format(cik=320193):
        return _COMPANYFACTS
    raise AssertionError(f"unexpected url {url}")


def test_extracts_quarterly_revenue_series() -> None:
    conn = SecConnector(as_of=date(2026, 1, 1), fetch=_fetch)
    result = conn.get_concept_series("AAPL", "revenue")
    assert isinstance(result, BarsData)
    assert [p.at for p in result.points] == ["2024-09-28", "2025-09-27"]
    assert [p.close for p in result.points] == [
        Decimal("94930000000"),
        Decimal("102000000000"),
    ]
    assert result.provider == "SEC EDGAR"


def test_as_of_excludes_later_filings() -> None:
    # as_of before either filing -> nothing available.
    conn = SecConnector(as_of=date(2024, 1, 1), fetch=_fetch)
    result = conn.get_concept_series("AAPL", "revenue")
    assert isinstance(result, UnavailableSource)
    assert result.reason == "no_data"
