"""The bundled synthetic demonstration source (fully offline).

The DEMO ticker resolves to a fictional company whose figures live in a
committed JSON fixture. The fixture must declare ``synthetic: true``; STRIX
refuses to run a demo document that does not label itself synthetic.
"""

from __future__ import annotations

import json
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from strix.errors import FixtureError
from strix.models import Concept, SourceType, Unit
from strix.sources.base import FetchedSource, NormalizedFact, SourceDocument

DEMO_TICKER = "DEMO"

#: Name of the bundled fixture (and of the preserved copy under ``raw/``).
FIXTURE_NAME = "demo-company-facts.json"

DEMO_DESCRIPTION = "Synthetic bundled fixture"

DEMO_DISCLAIMER = "Synthetic demonstration data — not investment advice."


class _FixtureModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FixtureFact(_FixtureModel):
    concept: Concept
    value: str = Field(pattern=r"^-?\d+(\.\d+)?$")
    unit: Unit
    locator: str = Field(min_length=1)


class FixturePeriod(_FixtureModel):
    period: str = Field(pattern=r"^\d{4}-Q[1-4]$")
    known_at: AwareDatetime
    facts: tuple[FixtureFact, ...]


class FixtureCompany(_FixtureModel):
    company_id: str = Field(min_length=1)
    ticker: str
    name: str = Field(min_length=1)


class FixtureDocument(_FixtureModel):
    fixture_name: str
    fixture_version: str
    synthetic: bool
    notice: str
    source_type: SourceType
    created_at: AwareDatetime
    company: FixtureCompany
    periods: tuple[FixturePeriod, ...]


def _forbid_float(text: str) -> None:
    raise FixtureError(f"fixture contains a JSON float ({text!r}); numeric values must be strings")


def load_fixture_bytes(fixture_path: Path | None = None) -> bytes:
    """Read the bundled demonstration fixture (or an explicit test path)."""
    if fixture_path is not None:
        try:
            return fixture_path.read_bytes()
        except OSError as exc:
            raise FixtureError(f"cannot read fixture {fixture_path}: {exc}") from exc
    resource = files("strix").joinpath("fixtures").joinpath(FIXTURE_NAME)
    try:
        return resource.read_bytes()
    except OSError as exc:  # pragma: no cover - packaging failure
        raise FixtureError(f"bundled fixture {FIXTURE_NAME} is missing: {exc}") from exc


def parse_demo_fixture(raw: bytes) -> SourceDocument:
    """Strictly parse and validate demo fixture bytes into a SourceDocument."""
    try:
        payload: Any = json.loads(raw.decode("utf-8"), parse_float=_forbid_float, parse_int=int)
    except UnicodeDecodeError as exc:
        raise FixtureError(f"fixture is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise FixtureError(f"fixture is not valid JSON: {exc}") from exc
    try:
        document = FixtureDocument.model_validate(payload)
    except ValidationError as exc:
        raise FixtureError(f"fixture failed schema validation: {exc}") from exc
    if not document.synthetic:
        raise FixtureError("fixture must declare synthetic=true; refusing to proceed")
    if document.source_type is not SourceType.SYNTHETIC_FIXTURE:
        raise FixtureError("demo fixture must declare source_type synthetic_fixture")
    if len(document.periods) != 2:
        raise FixtureError(f"fixture must contain exactly two periods, got {len(document.periods)}")
    facts: list[NormalizedFact] = []
    for period in document.periods:
        concepts = sorted(fact.concept.value for fact in period.facts)
        if concepts != [Concept.OPERATING_INCOME.value, Concept.REVENUE.value]:
            raise FixtureError(
                f"period {period.period} must contain exactly one revenue and one "
                f"operating_income fact, got {concepts}"
            )
        facts.extend(
            NormalizedFact(
                concept=fact.concept,
                value=Decimal(fact.value),
                unit=fact.unit,
                observation_period=period.period,
                known_at=period.known_at,
                locator=fact.locator,
            )
            for fact in period.facts
        )
    return SourceDocument(
        company_id=document.company.company_id,
        ticker=document.company.ticker,
        company_name=document.company.name,
        source_type=SourceType.SYNTHETIC_FIXTURE,
        source_version=document.fixture_version,
        synthetic=True,
        created_at=document.created_at,
        periods=(document.periods[0].period, document.periods[1].period),
        facts=tuple(facts),
    )


class DemoConnector:
    """Offline connector for the bundled synthetic fixture."""

    def __init__(self, fixture_path: Path | None = None) -> None:
        self._fixture_path = fixture_path

    def fetch(self, ticker: str) -> FetchedSource:
        if ticker.upper() != DEMO_TICKER:
            raise FixtureError(
                f"the demo connector only serves ticker {DEMO_TICKER}, not {ticker!r}"
            )
        return FetchedSource(
            raw=load_fixture_bytes(self._fixture_path),
            source_type=SourceType.SYNTHETIC_FIXTURE,
            source_name=FIXTURE_NAME,
            description=DEMO_DESCRIPTION,
            disclaimer=DEMO_DISCLAIMER,
        )
