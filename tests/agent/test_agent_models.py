"""Tests for agent domain contracts (evidence, series, claims, verification)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.agent.models import (
    AgentCalculation,
    AgentClaim,
    AgentClaimType,
    AgentEvidence,
    AgentVerificationStatus,
    CalculationMethod,
    ClaimVerification,
    FreshnessStatus,
    Observation,
    ObservationSeries,
    SourceKind,
)

_HASH = "a" * 64
_NOW = datetime(2026, 11, 22, tzinfo=UTC)


def test_claim_defaults_to_pending_verification() -> None:
    claim = AgentClaim(
        claim_id="CL-1",
        claim_type=AgentClaimType.QUANTITATIVE,
        statement="SPY 20-day realized volatility was 14%.",
        evidence_ids=("EV-1",),
    )
    assert claim.verification.status is AgentVerificationStatus.PENDING
    assert claim.is_verified is False


def test_claim_id_is_deterministic() -> None:
    a = AgentClaim.make_id(AgentClaimType.QUANTITATIVE, "x", ("EV-1",))
    b = AgentClaim.make_id(AgentClaimType.QUANTITATIVE, "x", ("EV-1",))
    assert a == b and a.startswith("CL-")


def test_evidence_id_is_content_derived() -> None:
    a = AgentEvidence.make_id(_HASH, "https://x", "sec1")
    b = AgentEvidence.make_id(_HASH, "https://x", "sec1")
    c = AgentEvidence.make_id(_HASH, "https://y", "sec1")
    assert a == b and a != c and a.startswith("EV-")


def test_evidence_rejects_bad_hash() -> None:
    with pytest.raises(ValidationError):
        AgentEvidence(
            evidence_id="EV-1",
            source_type=SourceKind.WEB_PAGE,
            provider="Example",
            source_title="t",
            retrieved_at=_NOW,
            content_hash="not-a-hash",
        )


def test_evidence_freshness_default() -> None:
    ev = AgentEvidence(
        evidence_id="EV-1",
        source_type=SourceKind.ECONOMIC_RELEASE,
        provider="BLS",
        source_title="CPI",
        retrieved_at=_NOW,
        content_hash=_HASH,
    )
    assert ev.freshness_status is FreshnessStatus.UNKNOWN


def test_observation_series_values_and_id() -> None:
    obs = (
        Observation(at="2026-11-20", value=Decimal("100")),
        Observation(at="2026-11-21", value=Decimal("110")),
    )
    series = ObservationSeries(
        series_id=ObservationSeries.make_id("SPY", "close", obs),
        subject="SPY",
        concept="close",
        unit="USD",
        observations=obs,
        source_evidence_id="EV-1",
    )
    assert series.values == (Decimal("100"), Decimal("110"))
    assert series.series_id.startswith("SER-")


def test_observation_rejects_float() -> None:
    with pytest.raises(ValidationError):
        Observation(at="2026-11-20", value=1.5)  # type: ignore[arg-type]


def test_calculation_carries_claimed_value() -> None:
    c = AgentCalculation(
        method=CalculationMethod.PERIOD_RETURN,
        calculation_version="1.0.0",
        input_series_ids=("SER-1",),
        claimed_value=Decimal("0.10"),
        units="ratio",
    )
    assert c.method is CalculationMethod.PERIOD_RETURN
    assert c.claimed_value == Decimal("0.10")


def test_verification_is_frozen() -> None:
    v = ClaimVerification()
    with pytest.raises(ValidationError):
        v.status = AgentVerificationStatus.VERIFIED  # type: ignore[misc]
