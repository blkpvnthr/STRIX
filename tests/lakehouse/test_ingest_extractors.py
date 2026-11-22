"""Tests for provider extractors (offline fake transport)."""

from __future__ import annotations

import json
from collections.abc import Mapping

from strix.lakehouse.contracts import DataSource
from strix.lakehouse.ingest.contracts import ExtractionWindow
from strix.lakehouse.ingest.extractors import (
    FRED_OBSERVATIONS,
    AlpacaBarsExtractor,
    BlsTimeseriesExtractor,
    EdgarCompanyFactsExtractor,
    FredObservationsExtractor,
    TreasuryYieldCurveExtractor,
)
from strix.lakehouse.ingest.rate_limit import HttpFetcher, RateLimiter
from strix.sources.edgar import COMPANYFACTS_URL, TICKER_MAP_URL

_WINDOW = ExtractionWindow(start=__import__("datetime").date(2026, 1, 1),
                           end=__import__("datetime").date(2026, 11, 20))


def _fetcher(router) -> tuple[HttpFetcher, list[str]]:  # type: ignore[no-untyped-def]
    seen: list[str] = []

    def transport(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
        seen.append(url)
        return 200, router(url, headers)

    return HttpFetcher(
        rate_limiter=RateLimiter(0.0), transport=transport, sleep_fn=lambda s: None
    ), seen


def test_alpaca_paginates_and_hides_secret_in_provenance() -> None:
    page1 = json.dumps(
        {"bars": [{"t": "2026-11-19T05:00:00Z", "c": 1}], "next_page_token": "TOK"}
    ).encode()
    page2 = json.dumps(
        {"bars": [{"t": "2026-11-20T05:00:00Z", "c": 2}], "next_page_token": None}
    ).encode()

    def router(url: str, headers: Mapping[str, str]) -> bytes:
        assert headers["APCA-API-KEY-ID"] == "kid"  # key travels in headers
        return page2 if "page_token=TOK" in url else page1

    fetcher, _ = _fetcher(router)
    ex = AlpacaBarsExtractor(["SPY"], key_id="kid", secret="sec", fetcher=fetcher)
    batches = list(ex.extract("SPY", _WINDOW))
    assert len(batches) == 2
    assert batches[-1].watermark == "2026-11-20"
    # Provenance endpoint/params carry no secret.
    assert "kid" not in batches[0].endpoint
    assert "APCA" not in json.dumps(batches[0].request_params)


def test_edgar_resolves_cik_and_preserves_snapshot() -> None:
    ticker_map = json.dumps({"0": {"ticker": "AAPL", "cik_str": 320193}}).encode()
    facts = json.dumps({"cik": 320193, "entityName": "Apple Inc.", "facts": {}}).encode()

    def router(url: str, headers: Mapping[str, str]) -> bytes:
        return ticker_map if url == TICKER_MAP_URL else facts

    fetcher, _ = _fetcher(router)
    ex = EdgarCompanyFactsExtractor(["AAPL"], fetcher=fetcher)
    [batch] = list(ex.extract("AAPL", _WINDOW))
    assert batch.ref.entity == "CIK0000320193"
    assert batch.endpoint == COMPANYFACTS_URL.format(cik=320193)
    assert batch.raw == facts


def test_treasury_yields_per_year() -> None:
    xml = b"<feed><entry>1</entry><entry>2</entry></feed>"
    fetcher, _seen = _fetcher(lambda u, h: xml)
    ex = TreasuryYieldCurveExtractor(fetcher=fetcher)
    window = ExtractionWindow(
        start=__import__("datetime").date(2025, 6, 1),
        end=__import__("datetime").date(2026, 2, 1),
    )
    batches = list(ex.extract(None, window))
    assert {b.ref.partition for b in batches} == {"2025", "2026"}
    assert batches[0].media_type == "application/xml"
    assert batches[0].record_count == 2


def test_bls_counts_observations() -> None:
    payload = json.dumps(
        {"Results": {"series": [{"data": [{"year": "2026"}, {"year": "2025"}]}]}}
    ).encode()
    fetcher, _ = _fetcher(lambda u, h: payload)
    ex = BlsTimeseriesExtractor(["CUUR0000SA0"], fetcher=fetcher)
    [batch] = list(ex.extract("CUUR0000SA0", _WINDOW))
    assert batch.record_count == 2
    assert batch.ref.source is DataSource.BLS


def test_fred_unavailable_without_key() -> None:
    fetcher, _ = _fetcher(lambda u, h: b"{}")
    ex = FredObservationsExtractor.from_env({}, ["CPIAUCSL"], fetcher)
    assert ex.available() is False


def test_fred_key_sent_live_but_never_persisted() -> None:
    payload = json.dumps({"observations": [{"date": "2026-01-01", "value": "1"}]}).encode()
    fetcher, seen = _fetcher(lambda u, h: payload)
    ex = FredObservationsExtractor(["CPIAUCSL"], api_key="SECRETKEY", fetcher=fetcher)
    [batch] = list(ex.extract("CPIAUCSL", _WINDOW))
    # The live request carried the key...
    assert any("api_key=SECRETKEY" in u for u in seen)
    # ...but provenance does not.
    assert batch.endpoint == FRED_OBSERVATIONS
    assert "SECRETKEY" not in batch.endpoint
    assert "api_key" not in batch.request_params
    assert "SECRETKEY" not in json.dumps(batch.request_params)
    assert batch.record_count == 1
