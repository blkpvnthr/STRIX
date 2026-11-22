"""Alpaca market-data connector (live prices; credentials from the environment).

Uses the Alpaca Market Data v2 REST API. The network is touched only inside
:meth:`AlpacaConnector._http_get`, which is injectable so unit tests run offline.
Numbers parse straight to :class:`~decimal.Decimal` (``parse_float=Decimal``) so
binary floating point never enters a preserved value. When credentials are
absent, every method returns a structured :class:`UnavailableSource` rather than
raising — unavailable market data is a transparent limitation, not a crash.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from strix.agent.sources import BarPoint, BarsData, QuoteData, UnavailableSource

# Public endpoint templates (reused by the lakehouse ingestion extractors).
ALPACA_BARS_URL = "https://data.alpaca.markets/v2/stocks/{symbol}/bars"
ALPACA_LATEST_TRADE_URL = "https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest"
_BARS_URL = ALPACA_BARS_URL
_LATEST_TRADE_URL = ALPACA_LATEST_TRADE_URL
_TIMEOUT_SECONDS = 30
_PROVIDER = "Alpaca Market Data"

HttpGet = Callable[[str, Mapping[str, str]], bytes]


class AlpacaConnector:
    """Fetches historical bars and latest trades from Alpaca."""

    def __init__(
        self,
        *,
        key_id: str | None,
        secret_key: str | None,
        http_get: HttpGet | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._key_id = key_id
        self._secret_key = secret_key
        self._http_get = http_get or self._default_http_get
        self._clock = clock or (lambda: datetime.now(UTC))

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str],
        *,
        http_get: HttpGet | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> AlpacaConnector:
        return cls(
            key_id=(env.get("ALPACA_API_KEY_ID") or "").strip() or None,
            secret_key=(env.get("ALPACA_API_SECRET_KEY") or "").strip() or None,
            http_get=http_get,
            clock=clock,
        )

    @property
    def available(self) -> bool:
        return bool(self._key_id and self._secret_key)

    # -- public API --------------------------------------------------------

    def get_historical_bars(
        self,
        symbol: str,
        *,
        start: str,
        end: str,
        timeframe: str = "1Day",
        feed: str = "iex",
        limit: int = 10_000,
    ) -> BarsData | UnavailableSource:
        """Daily (or other) bars for ``symbol`` between ``start`` and ``end`` (ISO)."""
        if not self.available:
            return UnavailableSource(
                source=_PROVIDER,
                reason="no_credentials",
                detail="ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY are not set",
            )
        query = urllib.parse.urlencode(
            {
                "timeframe": timeframe,
                "start": start,
                "end": end,
                "feed": feed,
                "limit": str(limit),
                "adjustment": "all",
            }
        )
        url = f"{_BARS_URL.format(symbol=urllib.parse.quote(symbol))}?{query}"
        try:
            raw = self._http_get(url, self._headers())
        except _HttpError as exc:
            return UnavailableSource(source=_PROVIDER, reason="http_error", detail=str(exc))
        points = _parse_bars(raw)
        if not points:
            return UnavailableSource(
                source=_PROVIDER,
                reason="no_data",
                detail=f"no bars returned for {symbol} in {start}..{end}",
            )
        return BarsData(
            symbol=symbol.upper(),
            timeframe=timeframe,
            start=start,
            end=end,
            provider=_PROVIDER,
            source_url=url,
            retrieved_at=self._clock(),
            raw=raw,
            points=points,
        )

    def get_latest_quote(self, symbol: str) -> QuoteData | UnavailableSource:
        """Latest trade price for ``symbol``."""
        if not self.available:
            return UnavailableSource(
                source=_PROVIDER,
                reason="no_credentials",
                detail="ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY are not set",
            )
        url = _LATEST_TRADE_URL.format(symbol=urllib.parse.quote(symbol)) + "?feed=iex"
        try:
            raw = self._http_get(url, self._headers())
        except _HttpError as exc:
            return UnavailableSource(source=_PROVIDER, reason="http_error", detail=str(exc))
        price, at = _parse_latest_trade(raw)
        if price is None:
            return UnavailableSource(
                source=_PROVIDER, reason="no_data", detail=f"no latest trade for {symbol}"
            )
        return QuoteData(
            symbol=symbol.upper(),
            price=price,
            at=at or "",
            provider=_PROVIDER,
            source_url=url,
            retrieved_at=self._clock(),
            raw=raw,
        )

    # -- internals ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        assert self._key_id and self._secret_key  # guarded by `available`
        return {
            "APCA-API-KEY-ID": self._key_id,
            "APCA-API-SECRET-KEY": self._secret_key,
            "Accept": "application/json",
        }

    @staticmethod
    def _default_http_get(url: str, headers: Mapping[str, str]) -> bytes:
        request = urllib.request.Request(url, headers=dict(headers))
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
                return bytes(response.read())
        except urllib.error.HTTPError as exc:
            raise _HttpError(f"Alpaca returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise _HttpError(f"could not reach Alpaca: {exc}") from exc


class _HttpError(Exception):
    """Internal: a connector HTTP failure, converted to UnavailableSource."""


def _parse_bars(raw: bytes) -> tuple[BarPoint, ...]:
    payload = _load_json(raw)
    bars = payload.get("bars") if isinstance(payload, dict) else None
    if not isinstance(bars, list):
        return ()
    points: list[BarPoint] = []
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        timestamp = str(bar.get("t", ""))
        close = bar.get("c")
        if not timestamp or not isinstance(close, (int, Decimal)) or isinstance(close, bool):
            continue
        points.append(BarPoint(at=timestamp[:10], close=Decimal(close)))
    return tuple(points)


def _parse_latest_trade(raw: bytes) -> tuple[Decimal | None, str | None]:
    payload = _load_json(raw)
    trade = payload.get("trade") if isinstance(payload, dict) else None
    if not isinstance(trade, dict):
        return None, None
    price = trade.get("p")
    at = str(trade.get("t", "")) or None
    if not isinstance(price, (int, Decimal)) or isinstance(price, bool):
        return None, at
    return Decimal(price), at


def _load_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
