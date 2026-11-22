"""SEC EDGAR concept-series connector for the agent.

Reuses the existing EDGAR primitives (:mod:`strix.sources.edgar`) to fetch a
company's preserved companyfacts bytes and extract one us-gaap concept as a
quarterly series (earliest-filed value per period, filed on or before the as-of
date — the value the market learned first). Returns preserved raw bytes plus
parsed points, or a structured :class:`UnavailableSource`.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from strix.agent.sources import BarPoint, BarsData, UnavailableSource
from strix.errors import SourceError
from strix.sources.edgar import (
    COMPANYFACTS_URL,
    OPERATING_INCOME_TAG,
    REVENUE_TAGS,
    TICKER_MAP_URL,
    fetch_url,
    resolve_cik,
)

_PROVIDER = "SEC EDGAR"
_QUARTER_MIN_DAYS = 80
_QUARTER_MAX_DAYS = 100

#: Friendly concept names -> ordered candidate us-gaap tags.
_CONCEPT_TAGS: dict[str, tuple[str, ...]] = {
    "revenue": REVENUE_TAGS,
    "operating_income": (OPERATING_INCOME_TAG,),
    "net_income": ("NetIncomeLoss",),
}


class SecConnector:
    """Fetches us-gaap concept series from SEC EDGAR company facts."""

    def __init__(self, *, as_of: date, fetch=fetch_url) -> None:  # type: ignore[no-untyped-def]
        self._as_of = as_of
        self._fetch = fetch

    def get_concept_series(self, ticker: str, concept: str) -> BarsData | UnavailableSource:
        """Return a quarterly series for ``concept`` (BarsData reuses at/close)."""
        tags = _CONCEPT_TAGS.get(concept.lower(), (concept,))
        try:
            ticker_map = self._fetch(TICKER_MAP_URL)
            cik = resolve_cik(ticker, ticker_map)
            raw = self._fetch(COMPANYFACTS_URL.format(cik=cik))
        except SourceError as exc:
            return UnavailableSource(source=_PROVIDER, reason="fetch_failed", detail=str(exc))
        points = _extract_concept(raw, tags, self._as_of)
        if not points:
            return UnavailableSource(
                source=_PROVIDER,
                reason="no_data",
                detail=f"no quarterly {concept} facts for {ticker} on or before {self._as_of}",
            )
        url = COMPANYFACTS_URL.format(cik=cik)
        return BarsData(
            symbol=ticker.upper(),
            timeframe=f"quarterly:{concept}",
            start=points[0].at,
            end=points[-1].at,
            provider=_PROVIDER,
            source_url=url,
            retrieved_at=datetime.now(UTC),
            raw=raw,
            points=points,
        )


def _extract_concept(raw: bytes, tags: tuple[str, ...], as_of: date) -> tuple[BarPoint, ...]:
    try:
        payload: Any = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ()
    us_gaap = ((payload or {}).get("facts") or {}).get("us-gaap")
    if not isinstance(us_gaap, dict):
        return ()
    for tag in tags:
        best: dict[date, tuple[date, Decimal]] = {}
        units = ((us_gaap.get(tag) or {}).get("units") or {}).get("USD")
        if not isinstance(units, list):
            continue
        for item in units:
            if not isinstance(item, dict):
                continue
            try:
                start = date.fromisoformat(str(item["start"]))
                end = date.fromisoformat(str(item["end"]))
                filed = date.fromisoformat(str(item["filed"]))
                value = item["val"]
            except (KeyError, ValueError, TypeError):
                continue
            if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
                continue
            if filed > as_of or not (_QUARTER_MIN_DAYS <= (end - start).days <= _QUARTER_MAX_DAYS):
                continue
            existing = best.get(end)
            if existing is None or filed < existing[0]:
                best[end] = (filed, Decimal(value))
        if best:
            return tuple(
                BarPoint(at=end.isoformat(), close=value)
                for end, (_filed, value) in sorted(best.items())
            )
    return ()
