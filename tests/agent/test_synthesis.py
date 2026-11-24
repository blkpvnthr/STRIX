"""Tests for the analytical synthesis layer (spec §5, §6).

Regression anchor: RUN-20261123-001 answered "how will the market perform
tomorrow?" by echoing a trailing return. Synthesis must instead directly address
the question, derive the stance deterministically, and never publish a number or
probability that is not grounded in a verified claim.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from tests.agent.agent_fixtures import build_config

from strix.agent.budget import BudgetTracker
from strix.agent.contracts import ModelResponse, TokenUsage, estimate_cost
from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import (
    AgentCalculation,
    AgentClaim,
    AgentClaimType,
    AgentVerificationStatus,
    CalculationMethod,
    ClaimVerification,
    EvidenceStrength,
    MarketStance,
    Observation,
    SourceKind,
)
from strix.agent.question import classify_question
from strix.agent.synthesis import synthesize

_NOW = datetime(2026, 11, 23, tzinfo=UTC)
_AS_OF = date(2026, 11, 23)
_FWD = "how will the market perform tomorrow?"


def _verified_index_return(subject: str, *, value: str):
    collector = EvidenceCollector()
    ev = collector.register(
        source_type=SourceKind.MARKET_DATA,
        provider="Alpaca Market Data",
        source_title=f"{subject} closes",
        raw=f"{subject}{value}".encode(),
        retrieved_at=_NOW,
        source_url=f"https://data.alpaca.markets/{subject}",
    )
    obs = (
        Observation(at="2026-11-19", value=Decimal("100")),
        Observation(at="2026-11-20", value=Decimal("92")),
    )
    series = collector.add_series(
        subject=subject,
        concept="close",
        unit="USD",
        observations=obs,
        source_evidence_id=ev.evidence_id,
    )
    calc = AgentCalculation(
        method=CalculationMethod.PERIOD_RETURN,
        calculation_version="1.0.0",
        parameters={"start": "2026-11-19", "end": "2026-11-20"},
        input_series_ids=(series.series_id,),
        claimed_value=Decimal(value),
        units="ratio",
    )
    claim = AgentClaim(
        claim_id=f"CL-{subject}",
        claim_type=AgentClaimType.QUANTITATIVE,
        statement=f"{subject} trailing return was {value}.",
        evidence_ids=(ev.evidence_id,),
        calculation=calc,
        verification=ClaimVerification(
            status=AgentVerificationStatus.VERIFIED,
            computed_value=Decimal(value),
            method="period_return",
        ),
    )
    return collector, claim


class _JsonProvider:
    """A synthesis provider that returns a fixed JSON object as output_text."""

    def __init__(self, config: Any, payload: dict) -> None:
        self.config = config
        self.payload = payload
        self.calls = 0

    def create_response(self, **kwargs: Any) -> ModelResponse:
        self.calls += 1
        usage = TokenUsage(input_tokens=200, output_tokens=120, total_tokens=320)
        return ModelResponse(
            response_id="resp_syn",
            model=self.config.model,
            status="completed",
            output_text=json.dumps(self.payload),
            usage=usage,
            cost=estimate_cost(usage, self.config.pricing),
        )


class _BrokenProvider:
    def create_response(self, **kwargs: Any) -> ModelResponse:
        raise RuntimeError("provider down")


def _synth(provider: Any, collector, claims, question_text: str, config):
    rq = classify_question(question_text, as_of=_AS_OF)
    budget = BudgetTracker(config)
    return synthesize(
        question=rq,
        verified=claims,
        unresolved=(),
        collector=collector,
        sanity_flags=(),
        as_of=_AS_OF,
        now=_NOW,
        provider=provider,
        budget=budget,
        config=config,
    )


def test_bearish_stance_derived_deterministically() -> None:
    config = build_config()
    collector, spy = _verified_index_return("SPY", value="-0.08")
    provider = _JsonProvider(
        config,
        {
            "direct_answer": "No single session can be predicted; conditions are bearish.",
            "analysis": "Trailing momentum is negative.",
            "analytical_inferences": [],
            "conditional_scenarios": [],
            "invalidation_conditions": ["SPY turns positive"],
            "monitoring_indicators": [],
        },
    )
    draft = _synth(provider, collector, (spy,), _FWD, config)
    assert draft.market_assessment is not None
    assert draft.market_assessment.stance is MarketStance.BEARISH
    assert draft.market_assessment.evidence_strength is not EvidenceStrength.INSUFFICIENT
    # The direct answer addresses the question, not a bare restatement of a finding.
    assert "predicted" in draft.direct_answer.lower() or "bearish" in draft.direct_answer.lower()


def test_insufficient_evidence_when_no_directional_claims() -> None:
    config = build_config()
    q = "should i expect bullish conditions?"
    draft = _synth(_BrokenProvider(), EvidenceCollector(), (), q, config)
    assert draft.market_assessment is not None
    assert draft.market_assessment.stance is MarketStance.INSUFFICIENT_EVIDENCE
    # Forward-looking + no evidence → an explicit "cannot justify" answer.
    assert "does not support" in draft.direct_answer.lower() or "no " in draft.direct_answer.lower()


def test_numeric_guard_strips_unsupported_numbers() -> None:
    config = build_config()
    collector, spy = _verified_index_return("SPY", value="-0.08")
    # The model fabricates a precise figure (-3.7%) that is not in any verified claim.
    provider = _JsonProvider(
        config,
        {
            "direct_answer": "The market fell 3.7% and will keep falling.",
            "analysis": "Momentum is negative.",
            "analytical_inferences": [],
            "conditional_scenarios": [],
            "invalidation_conditions": [],
            "monitoring_indicators": [],
        },
    )
    draft = _synth(provider, collector, (spy,), "why is the market selling off?", config)
    # The fabricated figure must not survive into the direct answer.
    assert "3.7" not in draft.direct_answer
    assert any("not traceable" in lim for lim in draft.limitations)


def test_probability_guard_strips_fabricated_probability() -> None:
    config = build_config()
    collector, spy = _verified_index_return("SPY", value="-0.08")
    provider = _JsonProvider(
        config,
        {
            "direct_answer": "",
            "analysis": "There is a 70% probability of further declines.",
            "analytical_inferences": [],
            "conditional_scenarios": [],
            "invalidation_conditions": [],
            "monitoring_indicators": [],
        },
    )
    draft = _synth(provider, collector, (spy,), _FWD, config)
    assert "70%" not in draft.analysis
    assert any("probability" in lim.lower() for lim in draft.limitations)


def test_falls_back_deterministically_when_provider_fails() -> None:
    config = build_config()
    collector, spy = _verified_index_return("SPY", value="-0.08")
    draft = _synth(_BrokenProvider(), collector, (spy,), _FWD, config)
    assert draft.diagnostics["llm_synthesis"].startswith("skipped")
    assert draft.direct_answer  # non-empty deterministic answer
    assert draft.market_assessment.stance is MarketStance.BEARISH


def test_forward_looking_answer_distinguishes_current_from_future() -> None:
    config = build_config()
    collector, spy = _verified_index_return("SPY", value="-0.08")
    # Deterministic path (broken provider) still must not just echo the finding.
    draft = _synth(_BrokenProvider(), collector, (spy,), _FWD, config)
    answer = draft.direct_answer.lower()
    assert "trailing return was -0.08" not in answer  # not a bare restatement
    assert "predict" in answer or "future" in answer or "session" in answer


def test_inference_classified_as_forecast_for_forward_question() -> None:
    config = build_config()
    collector, spy = _verified_index_return("SPY", value="-0.08")
    provider = _JsonProvider(
        config,
        {
            "direct_answer": "Conditions are bearish.",
            "analysis": "Momentum negative.",
            "analytical_inferences": [
                {
                    "statement": "Weakness may persist near term.",
                    "epistemic_class": "analytical_inference",
                    "supporting_claim_ids": ["CL-SPY"],
                    "uncertainty": "directional only",
                }
            ],
            "conditional_scenarios": [
                {"condition": "breadth improves", "outcome": "stabilization"}
            ],
            "invalidation_conditions": ["SPY turns positive"],
            "monitoring_indicators": [{"label": "VIX", "rationale": "stress gauge"}],
        },
    )
    draft = _synth(provider, collector, (spy,), _FWD, config)
    from strix.agent.models import EpistemicClass

    assert draft.analytical_inferences
    # Forward-looking question upgrades the inference to FORECAST.
    assert draft.analytical_inferences[0].epistemic_class is EpistemicClass.FORECAST
    assert draft.analytical_inferences[0].supporting_claim_ids == ("CL-SPY",)
    assert draft.conditional_scenarios
    assert draft.monitoring_indicators
