from __future__ import annotations

import pytest

from strix.errors import StrixError
from strix.market.universe import (
    DEFAULT_UNIVERSE,
    FeedType,
    Instrument,
    InstrumentKind,
    UniverseError,
    UniverseRegistry,
    feed_disclaimer,
)


def test_universe_error_is_strix_error() -> None:
    assert issubclass(UniverseError, StrixError)


def test_spy_is_etf_proxy_for_sp500_index_distinct_entries() -> None:
    spy = DEFAULT_UNIVERSE.get("SPY")
    sp500 = DEFAULT_UNIVERSE.get("SPX")
    # The ETF proxy and the actual index are two distinct registry entries.
    assert spy.symbol != sp500.symbol
    assert spy.kind is InstrumentKind.ETF
    assert spy.proxy_for == "S&P 500"
    # The thing SPY is a proxy for is a real index entry, never itself an ETF.
    assert sp500.kind is InstrumentKind.INDEX
    assert sp500.name == "S&P 500"
    assert sp500.proxy_for is None


def test_index_never_mislabeled_as_its_etf() -> None:
    # Each index must be kind=index and must NOT carry an ETF kind or a proxy.
    for index_symbol in ("DJIA", "SPX", "NDX", "RUT"):
        index = DEFAULT_UNIVERSE.get(index_symbol)
        assert index.kind is InstrumentKind.INDEX
        assert index.proxy_for is None
    for etf_symbol in ("DIA", "SPY", "QQQ", "IWM"):
        etf = DEFAULT_UNIVERSE.get(etf_symbol)
        assert etf.kind is InstrumentKind.ETF
        assert etf.proxy_for is not None


def test_vix_is_volatility_index_not_etf() -> None:
    vix = DEFAULT_UNIVERSE.get("VIX")
    assert vix.kind is InstrumentKind.VOLATILITY_INDEX
    assert vix.kind is not InstrumentKind.ETF
    assert vix.proxy_for is None


def test_by_kind_filters() -> None:
    etfs = DEFAULT_UNIVERSE.by_kind(InstrumentKind.ETF)
    etf_symbols = {i.symbol for i in etfs}
    assert "SPY" in etf_symbols
    assert "QQQ" in etf_symbols
    # No index or volatility index leaks into the ETF bucket.
    assert "SPX" not in etf_symbols
    assert "VIX" not in etf_symbols
    assert all(i.kind is InstrumentKind.ETF for i in etfs)

    indexes = DEFAULT_UNIVERSE.by_kind(InstrumentKind.INDEX)
    assert {i.symbol for i in indexes} >= {"DJIA", "SPX", "NDX", "RUT"}
    assert all(i.kind is InstrumentKind.INDEX for i in indexes)

    vol = DEFAULT_UNIVERSE.by_kind(InstrumentKind.VOLATILITY_INDEX)
    assert {i.symbol for i in vol} == {"VIX"}


def test_proxies_map_etf_to_index() -> None:
    proxies = DEFAULT_UNIVERSE.proxies()
    assert proxies["SPY"] == "S&P 500"
    assert proxies["DIA"] == "Dow Jones Industrial Average"
    assert proxies["QQQ"] == "Nasdaq-100"
    assert proxies["IWM"] == "Russell 2000"
    # Pure indexes are never keys in the ETF->index proxy map.
    assert "SPX" not in proxies
    assert "VIX" not in proxies


def test_is_proxy() -> None:
    assert DEFAULT_UNIVERSE.is_proxy("SPY") is True
    assert DEFAULT_UNIVERSE.is_proxy("SPX") is False
    assert DEFAULT_UNIVERSE.is_proxy("VIX") is False
    # Unknown symbols are not proxies (and do not raise here).
    assert DEFAULT_UNIVERSE.is_proxy("NOPE") is False


def test_validate_passes_on_default_universe() -> None:
    # Returns the registry for chaining; raises nothing on a well-formed set.
    assert DEFAULT_UNIVERSE.validate() is DEFAULT_UNIVERSE


def test_get_unknown_symbol_raises() -> None:
    with pytest.raises(UniverseError):
        DEFAULT_UNIVERSE.get("NOT_A_SYMBOL")


def test_default_universe_includes_bond_and_commodity_and_sector() -> None:
    for symbol in ("GLD", "BND", "SGOV", "TLT", "GOVT", "IEF", "HYG"):
        assert DEFAULT_UNIVERSE.get(symbol).symbol == symbol
    assert DEFAULT_UNIVERSE.get("GLD").kind is InstrumentKind.COMMODITY_ETF
    assert DEFAULT_UNIVERSE.get("TLT").kind is InstrumentKind.BOND_ETF
    for sector in ("XLK", "XLF", "XLE", "XLV"):
        assert DEFAULT_UNIVERSE.get(sector).kind is InstrumentKind.ETF


def test_feed_disclaimer_text_present() -> None:
    assert (
        feed_disclaimer(FeedType.IEX_ONLY)
        == "IEX-only feed is not consolidated SIP market activity"
    )
    # Every feed type yields a non-empty disclaimer.
    for feed in FeedType:
        assert feed_disclaimer(feed).strip() != ""


def test_registry_rejects_duplicate_symbols() -> None:
    dup = (
        Instrument(symbol="AAA", name="One", kind=InstrumentKind.INDEX, asset_class="x"),
        Instrument(symbol="AAA", name="Two", kind=InstrumentKind.INDEX, asset_class="x"),
    )
    with pytest.raises(UniverseError):
        UniverseRegistry(dup)


def test_validate_detects_unresolved_proxy() -> None:
    broken = (
        Instrument(
            symbol="ZZZ",
            name="Mystery ETF",
            kind=InstrumentKind.ETF,
            asset_class="equity",
            proxy_for="Nonexistent Index",
        ),
    )
    registry = UniverseRegistry(broken)
    with pytest.raises(UniverseError):
        registry.validate()
