"""Provider extraction contracts for the five sources.

Each extractor reuses the authoritative endpoints/parsers of the existing
connectors and performs rate-limited, retrying raw fetches via a shared
:class:`HttpFetcher`, yielding :class:`RawBatch` payloads for immutable Bronze
preservation. Provider credentials (FRED) are sent only in the live request URL
and are **never** written into provenance (endpoint/request_params are redacted).
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Iterator, Mapping, Sequence
from datetime import date

from strix.agent.connectors.market_data import ALPACA_BARS_URL
from strix.lakehouse.contracts import DatasetRef, DataSource
from strix.lakehouse.ingest.contracts import ExtractionWindow, RawBatch
from strix.lakehouse.ingest.rate_limit import HttpFetcher
from strix.sources.edgar import COMPANYFACTS_URL, TICKER_MAP_URL, resolve_cik

TREASURY_YIELD_XML = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
BLS_V1_SERIES = "https://api.bls.gov/publicAPI/v1/timeseries/data/{series}"
FRED_OBSERVATIONS = "https://api.stlouisfed.org/fred/series/observations"


def _win_part(window: ExtractionWindow) -> str:
    return f"{window.start.isoformat()}_{window.end.isoformat()}"


def _json(raw: bytes) -> object:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


# --------------------------------------------------------------------------
# Alpaca daily bars (credentials in headers, paginated)
# --------------------------------------------------------------------------


class AlpacaBarsExtractor:
    source = DataSource.ALPACA
    dataset = "equity_bars_daily"

    def __init__(
        self,
        symbols: Sequence[str],
        *,
        key_id: str | None,
        secret: str | None,
        fetcher: HttpFetcher,
        feed: str = "iex",
        timeframe: str = "1Day",
        page_limit: int = 10_000,
    ) -> None:
        self._symbols = tuple(s.upper() for s in symbols)
        self._key_id = key_id
        self._secret = secret
        self._fetcher = fetcher
        self._feed = feed
        self._timeframe = timeframe
        self._limit = page_limit

    @classmethod
    def from_env(
        cls, env: Mapping[str, str], symbols: Sequence[str], fetcher: HttpFetcher, **kw: object
    ) -> AlpacaBarsExtractor:
        return cls(
            symbols,
            key_id=(env.get("ALPACA_API_KEY_ID") or "").strip() or None,
            secret=(env.get("ALPACA_API_SECRET_KEY") or "").strip() or None,
            fetcher=fetcher,
            **kw,  # type: ignore[arg-type]
        )

    def available(self) -> bool:
        return bool(self._key_id and self._secret)

    def unavailable_reason(self) -> str:
        return "ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY not set"

    def entities(self) -> tuple[str | None, ...]:
        return self._symbols

    def _headers(self) -> dict[str, str]:
        assert self._key_id and self._secret
        return {
            "APCA-API-KEY-ID": self._key_id,
            "APCA-API-SECRET-KEY": self._secret,
            "Accept": "application/json",
        }

    def extract(self, entity: str | None, window: ExtractionWindow) -> Iterator[RawBatch]:
        assert entity is not None
        page_token: str | None = None
        while True:
            params = {
                "timeframe": self._timeframe,
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
                "feed": self._feed,
                "limit": str(self._limit),
                "adjustment": "all",
            }
            query = dict(params)
            if page_token:
                query["page_token"] = page_token
            base = ALPACA_BARS_URL.format(symbol=urllib.parse.quote(entity))
            url = f"{base}?{urllib.parse.urlencode(query)}"
            raw = self._fetcher.get(url, self._headers())
            count, max_date, next_token = _parse_alpaca(raw)
            if count:
                yield RawBatch(
                    ref=DatasetRef(
                        source=self.source, dataset=self.dataset, entity=entity,
                        partition=_win_part(window),
                    ),
                    raw=raw,
                    endpoint=ALPACA_BARS_URL.format(symbol=entity),
                    request_params=query,
                    media_type="application/json",
                    record_count=count,
                    observation_window=(
                        window.start.isoformat(), max_date or window.end.isoformat()
                    ),
                    watermark=max_date,
                )
            if not next_token:
                break
            page_token = next_token


def _parse_alpaca(raw: bytes) -> tuple[int, str | None, str | None]:
    payload = _json(raw)
    if not isinstance(payload, dict):
        return 0, None, None
    next_token = payload.get("next_page_token")
    bars = payload.get("bars")
    if not isinstance(bars, list):
        return 0, None, (str(next_token) if next_token else None)
    dates = [str(b["t"])[:10] for b in bars if isinstance(b, dict) and b.get("t")]
    return len(bars), (max(dates) if dates else None), (str(next_token) if next_token else None)


# --------------------------------------------------------------------------
# SEC EDGAR company facts (public snapshot)
# --------------------------------------------------------------------------


class EdgarCompanyFactsExtractor:
    source = DataSource.SEC_EDGAR
    dataset = "company_facts"

    def __init__(self, tickers: Sequence[str], *, fetcher: HttpFetcher) -> None:
        self._tickers = tuple(t.upper() for t in tickers)
        self._fetcher = fetcher
        self._ticker_map_raw: bytes | None = None

    def available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    def entities(self) -> tuple[str | None, ...]:
        return self._tickers

    def _ticker_map(self) -> bytes:
        if self._ticker_map_raw is None:
            self._ticker_map_raw = self._fetcher.get(TICKER_MAP_URL, {})
        return self._ticker_map_raw

    def extract(self, entity: str | None, window: ExtractionWindow) -> Iterator[RawBatch]:
        assert entity is not None
        cik = resolve_cik(entity, self._ticker_map())
        url = COMPANYFACTS_URL.format(cik=cik)
        raw = self._fetcher.get(url, {})
        yield RawBatch(
            ref=DatasetRef(
                source=self.source, dataset=self.dataset, entity=f"CIK{cik:010d}", partition="full"
            ),
            raw=raw,
            endpoint=url,
            request_params={"ticker": entity, "cik": str(cik)},
            media_type="application/json",
            record_count=None,  # a full snapshot; observation-level counting is DE-3
            observation_window=None,
            watermark=window.end.isoformat(),
        )


# --------------------------------------------------------------------------
# US Treasury daily par yield curve (public XML, per year)
# --------------------------------------------------------------------------


class TreasuryYieldCurveExtractor:
    source = DataSource.US_TREASURY
    dataset = "daily_treasury_yield_curve"

    def __init__(self, *, fetcher: HttpFetcher) -> None:
        self._fetcher = fetcher

    def available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    def entities(self) -> tuple[str | None, ...]:
        return (None,)

    def extract(self, entity: str | None, window: ExtractionWindow) -> Iterator[RawBatch]:
        for year in range(window.start.year, window.end.year + 1):
            url = TREASURY_YIELD_XML.format(year=year)
            raw = self._fetcher.get(url, {"Accept": "application/xml"})
            y_start = max(window.start, date(year, 1, 1)).isoformat()
            y_end = min(window.end, date(year, 12, 31)).isoformat()
            yield RawBatch(
                ref=DatasetRef(
                    source=self.source, dataset=self.dataset, entity=None, partition=str(year)
                ),
                raw=raw,
                endpoint=url,
                request_params={"year": str(year)},
                media_type="application/xml",
                record_count=raw.count(b"<entry"),
                observation_window=(y_start, y_end),
                watermark=y_end,
            )


# --------------------------------------------------------------------------
# BLS public v1 timeseries (no key; limited)
# --------------------------------------------------------------------------


class BlsTimeseriesExtractor:
    source = DataSource.BLS
    dataset = "timeseries"

    def __init__(self, series_ids: Sequence[str], *, fetcher: HttpFetcher) -> None:
        self._series = tuple(series_ids)
        self._fetcher = fetcher

    def available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    def entities(self) -> tuple[str | None, ...]:
        return self._series

    def extract(self, entity: str | None, window: ExtractionWindow) -> Iterator[RawBatch]:
        assert entity is not None
        params = {"startyear": str(window.start.year), "endyear": str(window.end.year)}
        base = BLS_V1_SERIES.format(series=urllib.parse.quote(entity))
        url = f"{base}?{urllib.parse.urlencode(params)}"
        raw = self._fetcher.get(url, {"Accept": "application/json"})
        yield RawBatch(
            ref=DatasetRef(
                source=self.source, dataset=self.dataset, entity=entity,
                partition=f"{window.start.year}_{window.end.year}",
            ),
            raw=raw,
            endpoint=BLS_V1_SERIES.format(series=entity),
            request_params=params,
            media_type="application/json",
            record_count=_count_bls(raw),
            observation_window=(window.start.isoformat(), window.end.isoformat()),
            watermark=window.end.isoformat(),
        )


def _count_bls(raw: bytes) -> int | None:
    data = _json(raw)
    if not isinstance(data, dict):
        return None
    try:
        return len(data["Results"]["series"][0]["data"])
    except (KeyError, IndexError, TypeError):
        return None


# --------------------------------------------------------------------------
# FRED observations (API key — kept OUT of provenance)
# --------------------------------------------------------------------------


class FredObservationsExtractor:
    source = DataSource.FRED
    dataset = "series_observations"

    def __init__(
        self, series_ids: Sequence[str], *, api_key: str | None, fetcher: HttpFetcher
    ) -> None:
        self._series = tuple(series_ids)
        self._api_key = api_key
        self._fetcher = fetcher

    @classmethod
    def from_env(
        cls, env: Mapping[str, str], series_ids: Sequence[str], fetcher: HttpFetcher
    ) -> FredObservationsExtractor:
        return cls(
            series_ids, api_key=(env.get("FRED_API_KEY") or "").strip() or None, fetcher=fetcher
        )

    def available(self) -> bool:
        return bool(self._api_key)

    def unavailable_reason(self) -> str:
        return "FRED_API_KEY not set"

    def entities(self) -> tuple[str | None, ...]:
        return self._series

    def extract(self, entity: str | None, window: ExtractionWindow) -> Iterator[RawBatch]:
        assert entity is not None and self._api_key
        # Params recorded in provenance (NO api_key).
        safe_params = {
            "series_id": entity,
            "file_type": "json",
            "observation_start": window.start.isoformat(),
            "observation_end": window.end.isoformat(),
        }
        # The live request adds the key; it is never persisted.
        live_query = urllib.parse.urlencode({**safe_params, "api_key": self._api_key})
        fetch_url = f"{FRED_OBSERVATIONS}?{live_query}"
        raw = self._fetcher.get(fetch_url, {"Accept": "application/json"})
        yield RawBatch(
            ref=DatasetRef(
                source=self.source, dataset=self.dataset, entity=entity, partition=_win_part(window)
            ),
            raw=raw,
            endpoint=FRED_OBSERVATIONS,  # redacted: base URL only, no key
            request_params=safe_params,
            media_type="application/json",
            record_count=_count_fred(raw),
            observation_window=(window.start.isoformat(), window.end.isoformat()),
            watermark=window.end.isoformat(),
        )


def _count_fred(raw: bytes) -> int | None:
    data = _json(raw)
    if not isinstance(data, dict):
        return None
    obs = data.get("observations")
    if isinstance(obs, list):
        return len(obs)
    try:
        return int(data["count"])
    except (KeyError, TypeError, ValueError):
        return None
