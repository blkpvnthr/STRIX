"""Normalized source-document contract shared by every connector."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Protocol

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field

from strix.models import Concept, SourceType, Unit


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("float values are forbidden; supply Decimal, str, or int")
    return value


class _SourceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NormalizedFact(_SourceModel):
    """One observation extracted from a source, before fact-ID assignment."""

    concept: Concept
    value: Annotated[Decimal, BeforeValidator(_reject_float)]
    unit: Unit
    observation_period: str
    #: When this observation became knowable (fixture timestamp or SEC
    #: filing date) — deterministic content, never wall clock.
    known_at: AwareDatetime
    #: Locator of the observation inside the raw source (JSON pointer).
    locator: str = Field(min_length=1)


class SourceDocument(_SourceModel):
    """A connector's normalized view of one company's raw source bytes."""

    company_id: str = Field(min_length=1)
    ticker: str
    company_name: str = Field(min_length=1)
    source_type: SourceType
    #: Content-derived version label (fixture version, or filed-through date).
    source_version: str
    synthetic: bool
    #: When the source as a whole became knowable (max of fact known_at for
    #: EDGAR; the fixture's created_at for the demo).
    created_at: AwareDatetime
    #: Role-ordered comparison periods: (previous, current).
    periods: tuple[str, str]
    facts: tuple[NormalizedFact, ...]


class FetchedSource(_SourceModel):
    """Raw bytes plus source identity, as acquired by a connector."""

    raw: bytes
    source_type: SourceType
    #: File name used for the preserved copy under ``raw/`` in the run dir.
    source_name: str
    #: Human-readable line for the CLI scope summary.
    description: str
    #: Report disclaimer appropriate to this source.
    disclaimer: str


class SourceConnector(Protocol):
    """Acquires raw source bytes for a ticker (parsing happens separately)."""

    def fetch(self, ticker: str) -> FetchedSource: ...
