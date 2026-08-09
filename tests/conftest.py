"""Shared fixtures: no network, fixed clock, deterministic pipeline bundles."""

from __future__ import annotations

import socket
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from strix import PIPELINE_VERSION
from strix.models import ResearchSpec, SourceType
from strix.pipeline import DeterministicOutcome, compute
from strix.reasoning.deterministic_demo import DeterministicDemoReasoner
from strix.sources.demo import FIXTURE_NAME, load_fixture_bytes, parse_demo_fixture

FIXED_NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
AS_OF = date(2026, 8, 8)


class FixedClock:
    """Deterministic injectable clock."""

    def __init__(self, now: datetime = FIXED_NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def compute_demo(spec: ResearchSpec, raw: bytes) -> DeterministicOutcome:
    """Run the deterministic core over demo fixture bytes with a fixed stamp."""
    return compute(
        spec,
        raw,
        source_type=SourceType.SYNTHETIC_FIXTURE,
        source_name=FIXTURE_NAME,
        reasoner=DeterministicDemoReasoner(),
        checked_at=FIXED_NOW,
    )


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if anything attempts to open a network socket."""

    def guard(*args: object, **kwargs: object) -> object:
        raise RuntimeError("network access is forbidden in the STRIX test suite")

    monkeypatch.setattr(socket, "socket", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock()


@pytest.fixture
def raw_fixture() -> bytes:
    return load_fixture_bytes()


@pytest.fixture
def spec(raw_fixture: bytes) -> ResearchSpec:
    document = parse_demo_fixture(raw_fixture)
    return ResearchSpec(
        company_id=document.company_id,
        ticker=document.ticker,
        company_name=document.company_name,
        question="Is operating profitability improving?",
        as_of_date=AS_OF,
        historical_periods=document.periods,
        pipeline_version=PIPELINE_VERSION,
    )


@pytest.fixture
def outcome(spec: ResearchSpec, raw_fixture: bytes) -> DeterministicOutcome:
    return compute_demo(spec, raw_fixture)


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "research_runs"
