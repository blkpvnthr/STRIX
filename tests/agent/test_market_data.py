"""Tests for the Alpaca market-data connector (offline, injected HTTP)."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from strix.agent.connectors.market_data import AlpacaConnector, _HttpError
from strix.agent.sources import BarsData, QuoteData, UnavailableSource

_BARS_JSON = (
    b'{"symbol":"SPY","bars":['
    b'{"t":"2024-01-02T05:00:00Z","o":100,"h":101,"l":99,"c":100.5,"v":1000},'
    b'{"t":"2024-01-03T05:00:00Z","o":100.5,"h":103,"l":100,"c":102.25,"v":1200}'
    b'],"next_page_token":null}'
)
_TRADE_JSON = b'{"symbol":"SPY","trade":{"t":"2024-01-03T20:00:00Z","p":452.17,"s":100}}'


def _connector(http_get: object, *, creds: bool = True) -> AlpacaConnector:
    return AlpacaConnector(
        key_id="k" if creds else None,
        secret_key="s" if creds else None,
        http_get=http_get,  # type: ignore[arg-type]
    )


def test_unavailable_without_credentials() -> None:
    conn = AlpacaConnector(key_id=None, secret_key=None)
    assert conn.available is False
    result = conn.get_historical_bars("SPY", start="2024-01-01", end="2024-02-01")
    assert isinstance(result, UnavailableSource)
    assert result.reason == "no_credentials"


def test_from_env_reads_credentials() -> None:
    conn = AlpacaConnector.from_env(
        {"ALPACA_API_KEY_ID": "abc", "ALPACA_API_SECRET_KEY": "def"}
    )
    assert conn.available is True


def test_historical_bars_parsed_as_decimal() -> None:
    captured: dict[str, Mapping[str, str]] = {}

    def http_get(url: str, headers: Mapping[str, str]) -> bytes:
        captured["headers"] = headers
        captured["url"] = url  # type: ignore[assignment]
        return _BARS_JSON

    result = _connector(http_get).get_historical_bars("SPY", start="2024-01-01", end="2024-02-01")
    assert isinstance(result, BarsData)
    assert [p.close for p in result.points] == [Decimal("100.5"), Decimal("102.25")]
    assert [p.at for p in result.points] == ["2024-01-02", "2024-01-03"]
    assert result.raw == _BARS_JSON
    assert captured["headers"]["APCA-API-KEY-ID"] == "k"


def test_historical_bars_no_data() -> None:
    result = _connector(lambda u, h: b'{"bars":[]}').get_historical_bars(
        "SPY", start="2024-01-01", end="2024-02-01"
    )
    assert isinstance(result, UnavailableSource)
    assert result.reason == "no_data"


def test_historical_bars_http_error() -> None:
    def boom(url: str, headers: Mapping[str, str]) -> bytes:
        raise _HttpError("HTTP 429")

    result = _connector(boom).get_historical_bars("SPY", start="2024-01-01", end="2024-02-01")
    assert isinstance(result, UnavailableSource)
    assert result.reason == "http_error"
    assert "429" in (result.detail or "")


def test_latest_quote_parsed() -> None:
    result = _connector(lambda u, h: _TRADE_JSON).get_latest_quote("SPY")
    assert isinstance(result, QuoteData)
    assert result.price == Decimal("452.17")
    assert result.symbol == "SPY"
