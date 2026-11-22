"""Shared types for research-data connectors.

A connector returns either real preserved data or a structured
:class:`UnavailableSource` — it never fabricates values and never raises for the
ordinary "this source isn't configured / has no data" case (that is data, not an
error). Hard failures (malformed responses, integrity problems) still raise.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class UnavailableSource:
    """A source that could not supply data, reported transparently."""

    source: str
    reason: str
    detail: str | None = None

    @property
    def available(self) -> bool:
        return False


@dataclass(frozen=True)
class BarPoint:
    """One preserved daily bar reduced to the fields the agent uses."""

    at: str  # ISO date
    close: Decimal


@dataclass(frozen=True)
class BarsData:
    """Preserved historical bars plus the raw bytes to register as evidence."""

    symbol: str
    timeframe: str
    start: str
    end: str
    provider: str
    source_url: str
    retrieved_at: datetime
    raw: bytes
    points: tuple[BarPoint, ...]

    @property
    def available(self) -> bool:
        return True


@dataclass(frozen=True)
class QuoteData:
    """A latest-trade snapshot plus the raw bytes to register as evidence."""

    symbol: str
    price: Decimal
    at: str
    provider: str
    source_url: str
    retrieved_at: datetime
    raw: bytes

    @property
    def available(self) -> bool:
        return True
