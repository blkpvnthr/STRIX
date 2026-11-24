"""Tests for the structured conversational response contracts (spec §6, §7, §9)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.agent.models import (
    AgentClaimType,
    AnalyticalInference,
    ConditionalScenario,
    DirectionalIndicator,
    EpistemicClass,
    EvidenceStrength,
    MarketAssessment,
    MarketStance,
    MonitoringIndicator,
    ResearchAnswer,
    ResearchResponse,
    SupportingFact,
)

_NOW = datetime(2026, 11, 23, tzinfo=UTC)


def _bare_answer() -> ResearchAnswer:
    return ResearchAnswer(
        run_id="RUN-X",
        question="q",
        data_as_of=_NOW,
        summary="s",
        verified_claims=(),
        unresolved_claims=(),
        evidence=(),
        limitations=(),
        disclaimer="d",
    )


def test_epistemic_and_verification_are_distinct_vocabularies() -> None:
    # No value overlaps between the two enums — they must never collapse.
    from strix.agent.models import AgentVerificationStatus

    epistemic = {e.value for e in EpistemicClass}
    verdicts = {v.value for v in AgentVerificationStatus}
    assert epistemic.isdisjoint(verdicts)


def test_inference_id_is_deterministic() -> None:
    a = AnalyticalInference.make_id("x", ("CL-1",))
    b = AnalyticalInference.make_id("x", ("CL-1",))
    assert a == b and a.startswith("INF-")


def test_scenario_id_is_deterministic() -> None:
    a = ConditionalScenario.make_id("if X", "then Y")
    assert a.startswith("SCN-")
    assert a == ConditionalScenario.make_id("if X", "then Y")


def test_market_assessment_defaults_to_insufficient_strength() -> None:
    ma = MarketAssessment(
        stance=MarketStance.INSUFFICIENT_EVIDENCE,
        horizon="next session",
        analysis_timestamp=_NOW,
    )
    assert ma.evidence_strength is EvidenceStrength.INSUFFICIENT
    assert ma.supporting_indicators == ()


def test_full_research_response_constructs() -> None:
    assessment = MarketAssessment(
        stance=MarketStance.BEARISH,
        horizon="next session",
        analysis_timestamp=_NOW,
        latest_session="2026-11-20",
        supporting_indicators=(
            DirectionalIndicator(
                label="Negative 5-day momentum",
                detail="SPY -8.2% over trailing window",
                claim_ids=("CL-1",),
            ),
        ),
        missing_indicators=("index futures", "market breadth"),
        evidence_strength=EvidenceStrength.MODERATE,
        invalidation_conditions=("SPY reclaims its 20-day moving average",),
    )
    resp = ResearchResponse(
        run_id="RUN-X",
        question="how will the market perform tomorrow?",
        question_intent="predictive",
        direct_answer="No single session can be predicted; the weight of evidence is bearish.",
        analysis="Trailing momentum is negative and volatility elevated.",
        market_assessment=assessment,
        supporting_facts=(
            SupportingFact(
                claim_id="CL-1",
                statement="SPY trailing return was -8.2%.",
                epistemic_class=EpistemicClass.VERIFIED_FACT,
                evidence_ids=("EV-1",),
                computed_value=Decimal("-0.082"),
                method="period_return",
            ),
        ),
        analytical_inferences=(
            AnalyticalInference(
                inference_id="INF-1",
                epistemic_class=EpistemicClass.FORECAST,
                statement="Momentum may persist, but mean reversion is also plausible.",
                supporting_claim_ids=("CL-1",),
                uncertainty="directional only; no probability asserted",
            ),
        ),
        monitoring_indicators=(
            MonitoringIndicator(label="VIX", rationale="A spike would confirm stress."),
        ),
        diagnostics={"model": "gpt-6-luna", "synthesis_version": "1.0.0"},
        verified_answer=_bare_answer(),
    )
    assert resp.market_assessment.stance is MarketStance.BEARISH
    assert resp.analytical_inferences[0].epistemic_class is EpistemicClass.FORECAST
    assert resp.verified_answer.run_id == "RUN-X"


def test_response_rejects_empty_direct_answer() -> None:
    with pytest.raises(ValidationError):
        ResearchResponse(
            run_id="RUN-X",
            question="q",
            question_intent="factual",
            direct_answer="",
            analysis="",
            verified_answer=_bare_answer(),
        )


def test_supporting_fact_only_holds_factual_epistemic_classes_by_convention() -> None:
    # The model permits any EpistemicClass, but the builder uses only these two;
    # confirm both construct so the builder can rely on them.
    for cls in (EpistemicClass.VERIFIED_FACT, EpistemicClass.ATTRIBUTED_REPORT):
        fact = SupportingFact(
            claim_id="CL-1",
            statement="x",
            epistemic_class=cls,
            evidence_ids=("EV-1",),
        )
        assert fact.epistemic_class is cls


def test_claim_type_has_forecast_distinct_from_epistemic() -> None:
    # Sanity: the claim-type FORECAST and epistemic FORECAST are separate enums.
    assert AgentClaimType.FORECAST.value == "forecast"
    assert EpistemicClass.FORECAST.value == "forecast"
    assert AgentClaimType.FORECAST is not EpistemicClass.FORECAST
