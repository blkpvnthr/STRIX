"""Tests for anomalous-observation sanity checks (spec §4)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import (
    AgentCalculation,
    AgentClaim,
    AgentClaimType,
    AgentVerificationStatus,
    CalculationMethod,
    ClaimVerification,
    Observation,
    SourceKind,
)
from strix.agent.sanity import check_claims

_NOW = datetime(2026, 11, 23, tzinfo=UTC)
_AS_OF = date(2026, 11, 23)


def _collector_with_series(subject: str, closes: list[str], dates: list[str]):
    collector = EvidenceCollector()
    ev = collector.register(
        source_type=SourceKind.MARKET_DATA,
        provider="Alpaca Market Data",
        source_title=f"{subject} closes",
        raw=f"{subject}-{closes}".encode(),
        retrieved_at=_NOW,
        source_url=f"https://data.alpaca.markets/{subject}",
    )
    obs = tuple(
        Observation(at=d, value=Decimal(c)) for d, c in zip(dates, closes, strict=True)
    )
    series = collector.add_series(
        subject=subject,
        concept="close",
        unit="USD",
        observations=obs,
        source_evidence_id=ev.evidence_id,
    )
    return collector, series, ev


def _verified_return_claim(series, ev, *, value: str, start: str, end: str):
    calc = AgentCalculation(
        method=CalculationMethod.PERIOD_RETURN,
        calculation_version="1.0.0",
        parameters={"start": start, "end": end},
        input_series_ids=(series.series_id,),
        claimed_value=Decimal(value),
        units="ratio",
    )
    return AgentClaim(
        claim_id="CL-ret",
        claim_type=AgentClaimType.QUANTITATIVE,
        statement=f"{series.subject} period return was {value}.",
        evidence_ids=(ev.evidence_id,),
        calculation=calc,
        verification=ClaimVerification(
            status=AgentVerificationStatus.VERIFIED,
            computed_value=Decimal(value),
            method="period_return",
        ),
    )


def test_anomalous_short_horizon_return_flagged() -> None:
    # SPY -11.28% over 6 observations (a week) — the RUN-002 anomaly shape.
    dates = ["2026-11-13", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]
    closes = ["100", "98", "95", "93", "91", "88.7"]
    collector, series, ev = _collector_with_series("SPY", closes, dates)
    claim = _verified_return_claim(
        series, ev, value="-0.112818", start="2026-11-13", end="2026-11-20"
    )
    flags = check_claims((claim,), collector, as_of=_AS_OF)
    codes = {f.code for f in flags}
    assert "anomalous_short_horizon_return" in codes


def test_inverted_date_range_flagged() -> None:
    dates = ["2026-11-19", "2026-11-20"]
    collector, series, ev = _collector_with_series("SPY", ["100", "101"], dates)
    claim = _verified_return_claim(
        series, ev, value="0.01", start="2026-11-20", end="2026-11-13"
    )
    flags = check_claims((claim,), collector, as_of=_AS_OF)
    assert any(f.code == "inverted_date_range" for f in flags)


def test_anomalous_price_step_flagged() -> None:
    # A 40% single-day drop (split/adjustment artifact).
    dates = ["2026-11-18", "2026-11-19", "2026-11-20"]
    collector, series, ev = _collector_with_series("SPY", ["100", "60", "61"], dates)
    claim = _verified_return_claim(
        series, ev, value="-0.39", start="2026-11-18", end="2026-11-20"
    )
    flags = check_claims((claim,), collector, as_of=_AS_OF)
    assert any(f.code == "anomalous_price_step" for f in flags)


def test_future_dated_window_flagged() -> None:
    dates = ["2026-11-19", "2026-11-20"]
    collector, series, ev = _collector_with_series("SPY", ["100", "101"], dates)
    claim = _verified_return_claim(
        series, ev, value="0.01", start="2026-11-19", end="2026-12-01"
    )
    flags = check_claims((claim,), collector, as_of=_AS_OF)
    assert any(f.code == "future_dated_window" for f in flags)


def test_clean_series_produces_no_anomaly_flags() -> None:
    dates = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]
    closes = ["100", "100.5", "101", "100.8", "101.2"]
    collector, series, ev = _collector_with_series("SPY", closes, dates)
    claim = _verified_return_claim(
        series, ev, value="0.012", start="2026-11-16", end="2026-11-20"
    )
    flags = check_claims((claim,), collector, as_of=_AS_OF)
    anomaly_codes = {
        "anomalous_short_horizon_return",
        "anomalous_price_step",
        "inverted_date_range",
        "future_dated_window",
        "nonpositive_price",
    }
    assert anomaly_codes.isdisjoint({f.code for f in flags})


def test_unverified_claims_are_not_checked() -> None:
    dates = ["2026-11-19", "2026-11-20"]
    collector, series, ev = _collector_with_series("SPY", ["100", "50"], dates)
    claim = _verified_return_claim(
        series, ev, value="-0.5", start="2026-11-19", end="2026-11-20"
    ).model_copy(
        update={"verification": ClaimVerification(status=AgentVerificationStatus.CONTRADICTED)}
    )
    flags = check_claims((claim,), collector, as_of=_AS_OF)
    assert flags == ()
