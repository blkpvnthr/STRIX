"""Default ingestion universe + builders for fetcher and extractors."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence

from strix.lakehouse.ingest.contracts import SourceExtractor
from strix.lakehouse.ingest.extractors import (
    AlpacaBarsExtractor,
    BlsTimeseriesExtractor,
    EdgarCompanyFactsExtractor,
    FredObservationsExtractor,
    TreasuryYieldCurveExtractor,
)
from strix.lakehouse.ingest.rate_limit import HttpFetcher, RateLimiter

#: Default universes (overridable via the CLI).
DEFAULT_EQUITY_SYMBOLS = (
    "SPY", "QQQ", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC",
)
DEFAULT_SEC_TICKERS = ("AAPL",)
DEFAULT_FRED_SERIES = ("CPIAUCSL", "DGS10", "DGS2")
DEFAULT_BLS_SERIES = ("CUUR0000SA0",)  # CPI-U, all urban consumers


def build_fetcher(
    *,
    min_interval: float = 0.35,
    max_retries: int = 3,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> HttpFetcher:
    """A shared, rate-limited, retrying HTTP fetcher (SEC fair-access safe)."""
    limiter = RateLimiter(min_interval=min_interval, sleep_fn=sleep_fn)
    return HttpFetcher(rate_limiter=limiter, max_retries=max_retries, sleep_fn=sleep_fn)


def build_extractors(
    env: Mapping[str, str],
    fetcher: HttpFetcher,
    *,
    symbols: Sequence[str] = DEFAULT_EQUITY_SYMBOLS,
    tickers: Sequence[str] = DEFAULT_SEC_TICKERS,
    fred_series: Sequence[str] = DEFAULT_FRED_SERIES,
    bls_series: Sequence[str] = DEFAULT_BLS_SERIES,
) -> dict[str, SourceExtractor]:
    """Build the default extractor set, keyed ``<source>.<dataset>``."""
    extractors: dict[str, SourceExtractor] = {
        "alpaca.equity_bars_daily": AlpacaBarsExtractor.from_env(env, symbols, fetcher),
        "sec_edgar.company_facts": EdgarCompanyFactsExtractor(tickers, fetcher=fetcher),
        "us_treasury.daily_treasury_yield_curve": TreasuryYieldCurveExtractor(fetcher=fetcher),
        "bls.timeseries": BlsTimeseriesExtractor(bls_series, fetcher=fetcher),
        "fred.series_observations": FredObservationsExtractor.from_env(env, fred_series, fetcher),
    }
    return extractors
