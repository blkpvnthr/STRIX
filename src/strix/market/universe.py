"""Configurable market-universe registry.

This module records *what* an instrument is, keeping the honest distinction
between an actual index (a non-tradable statistical construct, e.g. the
S&P 500) and the exchange-traded fund that is commonly used as its tradable
*proxy* (e.g. SPY). Conflating the two is a common and material error: an
index has no shares, no bid/ask, no expense ratio, and no tracking error,
whereas its ETF proxy has all four. Every ETF that stands in for an index
therefore carries an explicit ``proxy_for`` link to the index it approximates,
and the two are stored as distinct registry entries.

The registry also records *feed semantics* so that downstream reporting can
disclose provenance. A quote drawn from a single venue (IEX) is not the same
observation as the consolidated SIP national best bid/offer, and a delayed
provider feed is not real-time. ``feed_disclaimer`` returns the plain-language
caveat for each :class:`FeedType`.

The registry holds only descriptive metadata. It performs no market data
retrieval and makes no numeric computation.
"""

from __future__ import annotations

from enum import StrEnum

from strix.errors import StrixError
from strix.models import StrixModel

__all__ = [
    "DEFAULT_UNIVERSE",
    "FeedType",
    "Instrument",
    "InstrumentKind",
    "UniverseError",
    "UniverseRegistry",
    "feed_disclaimer",
]


class UniverseError(StrixError):
    """A universe operation failed: duplicate symbol, unknown symbol lookup,
    or an ETF whose declared ``proxy_for`` index is absent from the registry."""


class InstrumentKind(StrEnum):
    """The nature of an instrument.

    ``index`` is a non-tradable statistical construct; ``etf``,
    ``commodity_etf`` and ``bond_etf`` are tradable funds (an ETF may be a
    *proxy* for an index). ``volatility_index`` is an index measuring implied
    volatility (e.g. VIX) and is deliberately distinct from both ``index`` and
    ``etf``. ``economic_series`` is a published macro series, and ``equity`` is
    a single listed company.
    """

    INDEX = "index"
    ETF = "etf"
    EQUITY = "equity"
    COMMODITY_ETF = "commodity_etf"
    BOND_ETF = "bond_etf"
    ECONOMIC_SERIES = "economic_series"
    VOLATILITY_INDEX = "volatility_index"


class FeedType(StrEnum):
    """Provenance of a price/quote observation.

    ``consolidated_sip`` is the full national-market consolidated tape;
    ``iex_only`` is a single venue's activity (not the national best
    bid/offer); ``provider_delayed`` is a non-real-time vendor feed; and
    ``unknown`` marks unverified provenance.
    """

    CONSOLIDATED_SIP = "consolidated_sip"
    IEX_ONLY = "iex_only"
    PROVIDER_DELAYED = "provider_delayed"
    UNKNOWN = "unknown"


class Instrument(StrixModel):
    """One registry entry describing a market instrument.

    ``proxy_for`` names the index that this instrument approximates when it is
    a tradable stand-in (e.g. ``SPY`` has ``proxy_for="S&P 500"``). It is
    ``None`` for actual indexes and for funds that track no registered index.
    The value, when set, must equal the :attr:`name` of an ``index`` or
    ``volatility_index`` entry in the same registry (enforced by
    :meth:`UniverseRegistry.validate`).
    """

    symbol: str
    name: str
    kind: InstrumentKind
    asset_class: str
    proxy_for: str | None = None
    note: str = ""


# Plain-language provenance caveats, one per FeedType. Keeping them in a module
# constant (rather than inline) makes the full vocabulary auditable at a glance.
_FEED_DISCLAIMERS: dict[FeedType, str] = {
    FeedType.CONSOLIDATED_SIP: (
        "Consolidated SIP feed reflects full national market activity"
    ),
    FeedType.IEX_ONLY: "IEX-only feed is not consolidated SIP market activity",
    FeedType.PROVIDER_DELAYED: (
        "Provider feed is delayed and does not reflect real-time market activity"
    ),
    FeedType.UNKNOWN: (
        "Feed provenance is unknown; treat as unverified market activity"
    ),
}


def feed_disclaimer(feed: FeedType) -> str:
    """Return the plain-language provenance caveat for ``feed``.

    The caveat is suitable for direct inclusion in a research report so that a
    reader never mistakes single-venue or delayed data for consolidated
    real-time market activity.
    """
    return _FEED_DISCLAIMERS[feed]


class UniverseRegistry:
    """An ordered, immutable collection of :class:`Instrument` entries.

    Symbols are unique. Construction fails with :class:`UniverseError` on a
    duplicate symbol; :meth:`validate` additionally fails if any ETF names a
    ``proxy_for`` index that is not itself a registered ``index`` (or
    ``volatility_index``) entry.
    """

    def __init__(self, instruments: tuple[Instrument, ...]) -> None:
        by_symbol: dict[str, Instrument] = {}
        for instrument in instruments:
            if instrument.symbol in by_symbol:
                raise UniverseError(
                    f"duplicate symbol in universe: {instrument.symbol!r}"
                )
            by_symbol[instrument.symbol] = instrument
        self._instruments: tuple[Instrument, ...] = tuple(instruments)
        self._by_symbol: dict[str, Instrument] = by_symbol

    def get(self, symbol: str) -> Instrument:
        """Return the entry for ``symbol`` or raise :class:`UniverseError`."""
        try:
            return self._by_symbol[symbol]
        except KeyError as exc:
            raise UniverseError(f"unknown symbol: {symbol!r}") from exc

    def by_kind(self, kind: InstrumentKind) -> tuple[Instrument, ...]:
        """Return all entries of the given ``kind`` in registration order."""
        return tuple(i for i in self._instruments if i.kind is kind)

    def is_proxy(self, symbol: str) -> bool:
        """Return whether ``symbol`` is a registered tradable proxy.

        Returns ``False`` for unknown symbols and for entries without a
        ``proxy_for`` link; never raises.
        """
        instrument = self._by_symbol.get(symbol)
        return instrument is not None and instrument.proxy_for is not None

    def proxies(self) -> dict[str, str]:
        """Return the ETF-symbol -> index-name map for every proxy entry."""
        return {
            i.symbol: i.proxy_for
            for i in self._instruments
            if i.proxy_for is not None
        }

    def validate(self) -> UniverseRegistry:
        """Assert every ``proxy_for`` resolves to a registered index entry.

        Returns ``self`` to allow chaining. Raises :class:`UniverseError` if an
        instrument declares a ``proxy_for`` name that no ``index`` or
        ``volatility_index`` entry carries.
        """
        index_names = {
            i.name
            for i in self._instruments
            if i.kind in (InstrumentKind.INDEX, InstrumentKind.VOLATILITY_INDEX)
        }
        for instrument in self._instruments:
            if instrument.proxy_for is None:
                continue
            if instrument.proxy_for not in index_names:
                raise UniverseError(
                    f"{instrument.symbol!r} proxy_for "
                    f"{instrument.proxy_for!r} resolves to no index entry"
                )
        return self


# --------------------------------------------------------------------------
# Default registry
# --------------------------------------------------------------------------
#
# Indexes are listed first, each followed by the ETF that proxies it, so the
# proxy relationship is readable in source. Funds that track no registered
# index (sector slices, bond funds, gold) carry proxy_for=None and document
# their reference in ``note`` instead, keeping validate() honest.

_DEFAULT_INSTRUMENTS: tuple[Instrument, ...] = (
    # --- Actual indexes (non-tradable) ---
    Instrument(
        symbol="DJIA",
        name="Dow Jones Industrial Average",
        kind=InstrumentKind.INDEX,
        asset_class="equity_index",
        note="Price-weighted index of 30 large-cap US companies.",
    ),
    Instrument(
        symbol="DIA",
        name="SPDR Dow Jones Industrial Average ETF Trust",
        kind=InstrumentKind.ETF,
        asset_class="equity_index_etf",
        proxy_for="Dow Jones Industrial Average",
    ),
    Instrument(
        symbol="SPX",
        name="S&P 500",
        kind=InstrumentKind.INDEX,
        asset_class="equity_index",
        note="Float-weighted index of 500 large-cap US companies.",
    ),
    Instrument(
        symbol="SPY",
        name="SPDR S&P 500 ETF Trust",
        kind=InstrumentKind.ETF,
        asset_class="equity_index_etf",
        proxy_for="S&P 500",
    ),
    Instrument(
        symbol="NDX",
        name="Nasdaq-100",
        kind=InstrumentKind.INDEX,
        asset_class="equity_index",
        note="Modified cap-weighted index of 100 large non-financial Nasdaq names.",
    ),
    Instrument(
        symbol="QQQ",
        name="Invesco QQQ Trust",
        kind=InstrumentKind.ETF,
        asset_class="equity_index_etf",
        proxy_for="Nasdaq-100",
    ),
    Instrument(
        symbol="RUT",
        name="Russell 2000",
        kind=InstrumentKind.INDEX,
        asset_class="equity_index",
        note="Cap-weighted index of ~2000 US small-cap companies.",
    ),
    Instrument(
        symbol="IWM",
        name="iShares Russell 2000 ETF",
        kind=InstrumentKind.ETF,
        asset_class="equity_index_etf",
        proxy_for="Russell 2000",
    ),
    # --- Volatility index (distinct from both index and etf) ---
    Instrument(
        symbol="VIX",
        name="CBOE Volatility Index",
        kind=InstrumentKind.VOLATILITY_INDEX,
        asset_class="volatility",
        note="30-day implied volatility of S&P 500 options; not directly tradable.",
    ),
    # --- Commodity ETF ---
    Instrument(
        symbol="GLD",
        name="SPDR Gold Shares",
        kind=InstrumentKind.COMMODITY_ETF,
        asset_class="commodity",
        note="Tracks the spot price of gold bullion; references no registered index.",
    ),
    # --- Bond ETFs ---
    Instrument(
        symbol="BND",
        name="Vanguard Total Bond Market ETF",
        kind=InstrumentKind.BOND_ETF,
        asset_class="fixed_income",
        note="Broad US investment-grade taxable bond market.",
    ),
    Instrument(
        symbol="SGOV",
        name="iShares 0-3 Month Treasury Bond ETF",
        kind=InstrumentKind.BOND_ETF,
        asset_class="fixed_income",
        note="Ultra-short US Treasury bills.",
    ),
    Instrument(
        symbol="TLT",
        name="iShares 20+ Year Treasury Bond ETF",
        kind=InstrumentKind.BOND_ETF,
        asset_class="fixed_income",
        note="Long-duration US Treasury bonds.",
    ),
    Instrument(
        symbol="GOVT",
        name="iShares US Treasury Bond ETF",
        kind=InstrumentKind.BOND_ETF,
        asset_class="fixed_income",
        note="Broad-maturity US Treasury bonds.",
    ),
    Instrument(
        symbol="IEF",
        name="iShares 7-10 Year Treasury Bond ETF",
        kind=InstrumentKind.BOND_ETF,
        asset_class="fixed_income",
        note="Intermediate-duration US Treasury notes.",
    ),
    Instrument(
        symbol="HYG",
        name="iShares iBoxx High Yield Corporate Bond ETF",
        kind=InstrumentKind.BOND_ETF,
        asset_class="fixed_income",
        note="US high-yield (below investment grade) corporate bonds.",
    ),
    # --- Sector ETFs (SPDR Select Sector slices of the S&P 500) ---
    Instrument(
        symbol="XLK",
        name="Technology Select Sector SPDR Fund",
        kind=InstrumentKind.ETF,
        asset_class="equity_sector_etf",
        note="S&P 500 information-technology sector slice.",
    ),
    Instrument(
        symbol="XLF",
        name="Financial Select Sector SPDR Fund",
        kind=InstrumentKind.ETF,
        asset_class="equity_sector_etf",
        note="S&P 500 financials sector slice.",
    ),
    Instrument(
        symbol="XLE",
        name="Energy Select Sector SPDR Fund",
        kind=InstrumentKind.ETF,
        asset_class="equity_sector_etf",
        note="S&P 500 energy sector slice.",
    ),
    Instrument(
        symbol="XLV",
        name="Health Care Select Sector SPDR Fund",
        kind=InstrumentKind.ETF,
        asset_class="equity_sector_etf",
        note="S&P 500 health-care sector slice.",
    ),
    Instrument(
        symbol="XLI",
        name="Industrial Select Sector SPDR Fund",
        kind=InstrumentKind.ETF,
        asset_class="equity_sector_etf",
        note="S&P 500 industrials sector slice.",
    ),
    Instrument(
        symbol="XLY",
        name="Consumer Discretionary Select Sector SPDR Fund",
        kind=InstrumentKind.ETF,
        asset_class="equity_sector_etf",
        note="S&P 500 consumer-discretionary sector slice.",
    ),
    Instrument(
        symbol="XLP",
        name="Consumer Staples Select Sector SPDR Fund",
        kind=InstrumentKind.ETF,
        asset_class="equity_sector_etf",
        note="S&P 500 consumer-staples sector slice.",
    ),
    Instrument(
        symbol="XLU",
        name="Utilities Select Sector SPDR Fund",
        kind=InstrumentKind.ETF,
        asset_class="equity_sector_etf",
        note="S&P 500 utilities sector slice.",
    ),
    Instrument(
        symbol="XLB",
        name="Materials Select Sector SPDR Fund",
        kind=InstrumentKind.ETF,
        asset_class="equity_sector_etf",
        note="S&P 500 materials sector slice.",
    ),
    Instrument(
        symbol="XLRE",
        name="Real Estate Select Sector SPDR Fund",
        kind=InstrumentKind.ETF,
        asset_class="equity_sector_etf",
        note="S&P 500 real-estate sector slice.",
    ),
    Instrument(
        symbol="XLC",
        name="Communication Services Select Sector SPDR Fund",
        kind=InstrumentKind.ETF,
        asset_class="equity_sector_etf",
        note="S&P 500 communication-services sector slice.",
    ),
)

#: The bundled, self-consistent default registry (passes :meth:`validate`).
DEFAULT_UNIVERSE: UniverseRegistry = UniverseRegistry(_DEFAULT_INSTRUMENTS).validate()
