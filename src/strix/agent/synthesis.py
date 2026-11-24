"""Analytical reasoning and response synthesis (spec §5, §6).

After evidence collection and independent verification, STRIX performs a
dedicated synthesis step so the response directly answers the user's *actual*
question instead of merely echoing the first verified finding (the failure in
RUN-20261123-001).

Two parts, with a hard separation of authority:

1. A **deterministic market assessment** — the directional stance (BULLISH /
   BEARISH / NEUTRAL / MIXED / INSUFFICIENT_EVIDENCE) and evidence strength are
   *computed* from the verified claims, never asserted by the language model.
   The stance summarizes the weight of current evidence, not a probability about
   the future.

2. A single **GPT-6 Luna narrative call** that writes the direct answer, the
   analytical explanation, conditional scenarios, and monitoring indicators from
   a compact structured brief (not raw datasets — spec §12). Its output passes a
   numeric guard: any number that does not trace to a verified claim is stripped,
   and the text falls back to a deterministic answer rather than publish an
   unsupported figure. The model never assigns a verification verdict and never
   invents probabilities (spec §6).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from strix.agent.budget import BudgetTracker
from strix.agent.config import AgentConfig
from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import (
    AgentClaim,
    AnalyticalInference,
    CalculationMethod,
    ConditionalScenario,
    DirectionalIndicator,
    EpistemicClass,
    EvidenceStrength,
    MarketAssessment,
    MarketStance,
    MonitoringIndicator,
)
from strix.agent.question import QuestionIntent, ResearchQuestion
from strix.agent.sanity import SanityFlag
from strix.errors import ProviderError

SYNTHESIS_VERSION = "synthesis/1.0.0"

#: Index proxies whose returns drive the directional tally.
_INDEX_PROXIES = {"SPY", "QQQ", "DIA", "IWM", "VTI", "VOO"}
#: Questions that warrant a directional market assessment.
_ASSESSMENT_INTENTS = {QuestionIntent.PREDICTIVE, QuestionIntent.CURRENT_MARKET}
#: Phrases that would fabricate a probability — forbidden unless from a model.
_PROBABILITY_RE = re.compile(
    r"\b\d{1,3}(?:\.\d+)?\s?%?\s?(?:probability|chance|likelihood|odds|confidence)\b",
    re.IGNORECASE,
)
#: Any numeric token (percent, decimal, or integer) for the support guard.
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?%?")


@dataclass(frozen=True)
class SynthesisDraft:
    """Run-independent synthesis output assembled into a response at persist time."""

    direct_answer: str
    analysis: str
    market_assessment: MarketAssessment | None
    analytical_inferences: tuple[AnalyticalInference, ...] = ()
    conditional_scenarios: tuple[ConditionalScenario, ...] = ()
    monitoring_indicators: tuple[MonitoringIndicator, ...] = ()
    limitations: tuple[str, ...] = ()
    #: Diagnostic breadcrumbs (model, whether the LLM call ran, guard hits).
    diagnostics: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def synthesize(
    *,
    question: ResearchQuestion,
    verified: tuple[AgentClaim, ...],
    unresolved: tuple[AgentClaim, ...],
    collector: EvidenceCollector,
    sanity_flags: tuple[SanityFlag, ...],
    as_of: date,
    now: datetime,
    provider: object,
    budget: BudgetTracker,
    config: AgentConfig,
    prior_context: str | None = None,
) -> SynthesisDraft:
    """Produce the conversational draft for one research question."""
    assessment = _derive_market_assessment(question, verified, collector, now)
    allowed_numbers = _allowed_numbers(verified)
    brief = _build_brief(
        question, verified, unresolved, assessment, sanity_flags, prior_context
    )

    llm_result: dict[str, Any] | None = None
    diagnostics = {"synthesis_version": SYNTHESIS_VERSION, "model": config.model}
    try:
        budget.ensure_can_call_model()
        llm_result = _call_model(provider, brief, config, budget)
        diagnostics["llm_synthesis"] = "ok"
    except Exception as exc:
        diagnostics["llm_synthesis"] = f"skipped:{type(exc).__name__}"

    limitations: list[str] = []
    if llm_result is None:
        direct, analysis, inferences, scenarios, monitoring = _deterministic_narrative(
            question, verified, unresolved, assessment
        )
    else:
        direct, analysis, inferences, scenarios, monitoring, assessment, guard_notes = _from_llm(
            llm_result, question, verified, assessment, allowed_numbers
        )
        limitations.extend(guard_notes)
        if not direct.strip():
            direct, analysis, inferences, scenarios, monitoring = _deterministic_narrative(
                question, verified, unresolved, assessment
            )
            diagnostics["llm_synthesis"] = "rejected:empty_or_unsupported"

    if assessment is not None and assessment.stance is MarketStance.INSUFFICIENT_EVIDENCE:
        limitations.append(
            "Available evidence does not support a directional market assessment; "
            "additional indicators (breadth, futures, macro releases) are needed."
        )

    return SynthesisDraft(
        direct_answer=direct or _fallback_direct(question, verified),
        analysis=analysis,
        market_assessment=assessment,
        analytical_inferences=inferences,
        conditional_scenarios=scenarios,
        monitoring_indicators=monitoring,
        limitations=tuple(dict.fromkeys(limitations)),
        diagnostics=diagnostics,
    )


# --------------------------------------------------------------------------
# Deterministic market assessment
# --------------------------------------------------------------------------


def _derive_market_assessment(
    question: ResearchQuestion,
    verified: tuple[AgentClaim, ...],
    collector: EvidenceCollector,
    now: datetime,
) -> MarketAssessment | None:
    if "directional_market_assessment" not in question.objectives and (
        question.intent not in _ASSESSMENT_INTENTS
    ):
        return None

    supporting: list[DirectionalIndicator] = []
    contradictory: list[DirectionalIndicator] = []
    bullish = bearish = 0
    latest_session: str | None = None

    for claim in verified:
        calc = claim.calculation
        value = claim.verification.computed_value
        if calc is None or value is None:
            continue
        subject = _subject_of(claim, collector)
        latest_session = _max_session(latest_session, _latest_obs_date(claim, collector))

        if calc.method in (CalculationMethod.PERIOD_RETURN, CalculationMethod.CUMULATIVE_RETURN):
            if subject in _INDEX_PROXIES:
                indicator = DirectionalIndicator(
                    label=f"{subject} trailing return",
                    detail=f"{_pct(value)} over the measured window",
                    claim_ids=(claim.claim_id,),
                )
                if value > 0:
                    supporting.append(indicator)
                    bullish += 1
                elif value < 0:
                    contradictory.append(indicator)
                    bearish += 1
        elif calc.method is CalculationMethod.MAX_DRAWDOWN and value < Decimal("-0.10"):
            contradictory.append(
                DirectionalIndicator(
                    label=f"{subject} drawdown",
                    detail=f"{_pct(value)} peak-to-trough",
                    claim_ids=(claim.claim_id,),
                )
            )
            bearish += 1
        elif calc.method is CalculationMethod.REALIZED_VOLATILITY and value > Decimal("0.25"):
            contradictory.append(
                DirectionalIndicator(
                    label=f"{subject} realized volatility",
                    detail=f"elevated at {_pct(value)} annualized",
                    claim_ids=(claim.claim_id,),
                )
            )

    stance, strength = _stance(bullish, bearish, supporting, contradictory)
    missing = _missing_indicators(question, verified, collector)

    return MarketAssessment(
        stance=stance,
        horizon=_horizon_label(question),
        analysis_timestamp=now,
        latest_session=latest_session,
        supporting_indicators=tuple(supporting),
        contradictory_indicators=tuple(contradictory),
        missing_indicators=missing,
        evidence_strength=strength,
    )


def _stance(
    bullish: int,
    bearish: int,
    supporting: list[DirectionalIndicator],
    contradictory: list[DirectionalIndicator],
) -> tuple[MarketStance, EvidenceStrength]:
    total = bullish + bearish
    if total == 0:
        return MarketStance.INSUFFICIENT_EVIDENCE, EvidenceStrength.INSUFFICIENT
    if bullish > 0 and bearish > 0:
        stance = MarketStance.MIXED
    elif bullish > bearish:
        stance = MarketStance.BULLISH
    elif bearish > bullish:
        stance = MarketStance.BEARISH
    else:
        stance = MarketStance.NEUTRAL
    strength = (
        EvidenceStrength.STRONG
        if total >= 3
        else EvidenceStrength.MODERATE
        if total == 2
        else EvidenceStrength.WEAK
    )
    return stance, strength


def _missing_indicators(
    question: ResearchQuestion,
    verified: tuple[AgentClaim, ...],
    collector: EvidenceCollector,
) -> tuple[str, ...]:
    have_methods = {
        c.calculation.method for c in verified if c.calculation is not None
    }
    missing: list[str] = []
    wants = set(question.evidence_requirements)
    if "momentum" in wants and CalculationMethod.MOVING_AVERAGE not in have_methods:
        missing.append("moving-average trend")
    if "realized_volatility" in wants and (
        CalculationMethod.REALIZED_VOLATILITY not in have_methods
    ):
        missing.append("realized volatility")
    if "drawdown" in wants and CalculationMethod.MAX_DRAWDOWN not in have_methods:
        missing.append("drawdown")
    if "sector_relative_performance" in wants and (
        CalculationMethod.RELATIVE_PERFORMANCE not in have_methods
    ):
        missing.append("sector rotation")
    # Evidence categories STRIX cannot yet source are always missing for outlook.
    if question.intent in _ASSESSMENT_INTENTS:
        missing += ["market breadth", "index futures", "economic calendar"]
    return tuple(dict.fromkeys(missing))


# --------------------------------------------------------------------------
# LLM narrative call
# --------------------------------------------------------------------------


def _call_model(
    provider: object, brief: str, config: AgentConfig, budget: BudgetTracker
) -> dict[str, Any] | None:
    instructions = _synthesis_instructions()
    response = provider.create_response(  # type: ignore[attr-defined]
        input=[{"role": "user", "content": brief}],
        instructions=instructions,
        tools=None,
        max_output_tokens=min(config.max_output_tokens, 1200),
    )
    budget.record_model_call(response.usage)
    text = (response.output_text or "").strip()
    if not text:
        raise ProviderError("empty synthesis response")
    return _parse_json_object(text)


def _parse_json_object(text: str) -> dict[str, Any]:
    # Tolerate a fenced ```json block or leading prose around the object.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ProviderError("synthesis response is not a JSON object")
    parsed: dict[str, Any] = json.loads(text[start : end + 1])
    return parsed


def _from_llm(
    result: dict[str, Any],
    question: ResearchQuestion,
    verified: tuple[AgentClaim, ...],
    assessment: MarketAssessment | None,
    allowed_numbers: set[str],
) -> tuple[
    str,
    str,
    tuple[AnalyticalInference, ...],
    tuple[ConditionalScenario, ...],
    tuple[MonitoringIndicator, ...],
    MarketAssessment | None,
    list[str],
]:
    notes: list[str] = []
    valid_claim_ids = {c.claim_id for c in verified}

    direct = _guard_text(str(result.get("direct_answer", "")).strip(), allowed_numbers, notes)
    analysis = _guard_text(str(result.get("analysis", "")).strip(), allowed_numbers, notes)

    inferences: list[AnalyticalInference] = []
    for item in result.get("analytical_inferences", []) or []:
        statement = _guard_text(str(item.get("statement", "")).strip(), allowed_numbers, notes)
        if not statement:
            continue
        klass = (
            EpistemicClass.FORECAST
            if str(item.get("epistemic_class", "")).lower() == "forecast"
            or question.is_forward_looking
            else EpistemicClass.ANALYTICAL_INFERENCE
        )
        support = tuple(
            cid for cid in (item.get("supporting_claim_ids") or []) if cid in valid_claim_ids
        )
        inferences.append(
            AnalyticalInference(
                inference_id=AnalyticalInference.make_id(statement, support),
                epistemic_class=klass,
                statement=statement,
                supporting_claim_ids=support,
                uncertainty=(str(item.get("uncertainty")).strip() or None)
                if item.get("uncertainty")
                else None,
            )
        )

    scenarios: list[ConditionalScenario] = []
    for item in result.get("conditional_scenarios", []) or []:
        condition = _guard_text(str(item.get("condition", "")).strip(), allowed_numbers, notes)
        outcome = _guard_text(str(item.get("outcome", "")).strip(), allowed_numbers, notes)
        if condition and outcome:
            scenarios.append(
                ConditionalScenario(
                    scenario_id=ConditionalScenario.make_id(condition, outcome),
                    condition=condition,
                    outcome=outcome,
                )
            )

    monitoring: list[MonitoringIndicator] = []
    for item in result.get("monitoring_indicators", []) or []:
        label = str(item.get("label", "")).strip()
        rationale = _guard_text(str(item.get("rationale", "")).strip(), allowed_numbers, notes)
        if label:
            monitoring.append(MonitoringIndicator(label=label[:120], rationale=rationale))

    # Merge model-authored invalidation conditions into the assessment.
    if assessment is not None:
        invalidation = tuple(
            _guard_text(str(x).strip(), allowed_numbers, notes)
            for x in (result.get("invalidation_conditions") or [])
            if str(x).strip()
        )
        if invalidation:
            assessment_scenarios = tuple(f"{s.condition} → {s.outcome}" for s in scenarios)
            assessment = assessment.model_copy(
                update={
                    "invalidation_conditions": invalidation,
                    "conditional_scenarios": assessment_scenarios,
                }
            )

    return (
        direct,
        analysis,
        tuple(inferences),
        tuple(scenarios),
        tuple(monitoring),
        assessment,
        notes,
    )


def _guard_text(text: str, allowed_numbers: set[str], notes: list[str]) -> str:
    """Strip a statement that invents a probability or an unsupported number."""
    if not text:
        return text
    if _PROBABILITY_RE.search(text):
        notes.append("Removed a synthesized statement that asserted a fabricated probability.")
        return ""
    for token in _NUMBER_RE.findall(text):
        if _normalize_number(token) not in allowed_numbers:
            notes.append(
                "Removed a synthesized statement containing a number not traceable to a "
                "verified calculation."
            )
            return ""
    return text


# --------------------------------------------------------------------------
# Deterministic fallback narrative
# --------------------------------------------------------------------------


def _deterministic_narrative(
    question: ResearchQuestion,
    verified: tuple[AgentClaim, ...],
    unresolved: tuple[AgentClaim, ...],
    assessment: MarketAssessment | None,
) -> tuple[
    str,
    str,
    tuple[AnalyticalInference, ...],
    tuple[ConditionalScenario, ...],
    tuple[MonitoringIndicator, ...],
]:
    direct = _fallback_direct(question, verified)
    if assessment is not None and assessment.stance is not MarketStance.INSUFFICIENT_EVIDENCE:
        indicators = assessment.supporting_indicators + assessment.contradictory_indicators
        pieces = [i.detail for i in indicators]
        analysis = (
            f"On the weight of current evidence the stance is {assessment.stance.value}. "
            + ("Signals observed: " + "; ".join(pieces) + "." if pieces else "")
        )
    elif verified:
        analysis = (
            "This reading rests only on the verified findings below; it is a summary of "
            "observed data, not a forecast."
        )
    else:
        analysis = (
            "No assertion met the independent verification bar, so no evidence-based "
            "analysis can be offered for this question."
        )
    return direct, analysis, (), (), ()


def _fallback_direct(question: ResearchQuestion, verified: tuple[AgentClaim, ...]) -> str:
    if question.is_forward_looking:
        if verified:
            return (
                "No single future session can be predicted from the available evidence. "
                "What the verified data supports is a reading of current conditions, "
                "summarized below — not a probability about the next session."
            )
        return (
            "The available evidence does not support a forward-looking answer to this "
            "question; no directional view can be justified."
        )
    if verified:
        return (
            "Based on the independently verified findings below: " + verified[0].statement
        )
    return (
        "No assertion could be independently verified for this question; see the "
        "limitations for what additional evidence is needed."
    )


# --------------------------------------------------------------------------
# Brief construction (compact — never raw datasets; spec §12)
# --------------------------------------------------------------------------


def _build_brief(
    question: ResearchQuestion,
    verified: tuple[AgentClaim, ...],
    unresolved: tuple[AgentClaim, ...],
    assessment: MarketAssessment | None,
    sanity_flags: tuple[SanityFlag, ...],
    prior_context: str | None = None,
) -> str:
    lines: list[str] = []
    if prior_context:
        lines += [prior_context, ""]
    lines += [
        f"QUESTION: {question.text}",
        f"INTENT: {question.intent.value}; forward_looking={question.is_forward_looking}; "
        f"horizon={question.horizon.value}",
        "",
        "VERIFIED FINDINGS (these are the only facts you may rely on; cite by claim_id):",
    ]
    if verified:
        for c in verified:
            value = (
                f" [computed {c.verification.computed_value} via {c.verification.method}]"
                if c.verification.computed_value is not None
                else ""
            )
            lines.append(f"  - {c.claim_id}: {c.statement}{value}")
    else:
        lines.append("  (none met the verification bar)")

    if assessment is not None:
        lines += [
            "",
            f"DETERMINISTIC MARKET STANCE (do not override): {assessment.stance.value} "
            f"(evidence strength: {assessment.evidence_strength.value})",
            f"MISSING INDICATORS: {', '.join(assessment.missing_indicators) or 'none noted'}",
        ]
    if unresolved:
        lines += ["", f"UNRESOLVED (do NOT state as fact): {len(unresolved)} candidate(s)."]
    if sanity_flags:
        lines += ["", "DATA-QUALITY FLAGS:"]
        lines += [f"  - {f.message}" for f in sanity_flags]
    return "\n".join(lines)


def _synthesis_instructions() -> str:
    return (
        "You are STRIX's analytical synthesis step. Write a conversational, "
        "evidence-grounded answer to the QUESTION using ONLY the VERIFIED FINDINGS "
        "provided. Return a single JSON object with keys: direct_answer (string, "
        "directly answers the question), analysis (string), analytical_inferences "
        "(array of {statement, epistemic_class: 'analytical_inference'|'forecast', "
        "supporting_claim_ids: [claim ids], uncertainty}), conditional_scenarios "
        "(array of {condition, outcome}), invalidation_conditions (array of strings), "
        "monitoring_indicators (array of {label, rationale}). Rules: (1) Do not state "
        "any number that is not present in a verified finding. (2) Never invent a "
        "probability, confidence level, or percentage of certainty. (3) Respect the "
        "DETERMINISTIC MARKET STANCE — explain it, never contradict it. (4) If the "
        "question is forward-looking, distinguish current conditions from a prediction "
        "about the future. (5) Output JSON only, no prose outside the object."
    )


# --------------------------------------------------------------------------
# Numeric support set
# --------------------------------------------------------------------------


def _allowed_numbers(verified: tuple[AgentClaim, ...]) -> set[str]:
    """Numbers the synthesis text is permitted to use (from verified claims)."""
    allowed: set[str] = set()
    for claim in verified:
        allowed.update(_NUMBER_RE.findall(claim.statement))
        value = claim.verification.computed_value
        if value is not None:
            allowed.add(_normalize_number(str(value)))
            allowed.add(_normalize_number(_pct(value)))
    return {_normalize_number(a) for a in allowed}


def _normalize_number(token: str) -> str:
    token = token.strip().rstrip("%")
    try:
        d = Decimal(token)
    except Exception:
        return token
    # Normalize sign/trailing zeros; compare at 4-dp to tolerate rounding in prose.
    return format(d.quantize(Decimal("0.0001")).normalize(), "f")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _subject_of(claim: AgentClaim, collector: EvidenceCollector) -> str:
    if claim.calculation is not None and claim.calculation.input_series_ids:
        series = collector.series(claim.calculation.input_series_ids[0])
        if series is not None:
            return series.subject
    return ""


def _latest_obs_date(claim: AgentClaim, collector: EvidenceCollector) -> str | None:
    if claim.calculation is None:
        return None
    latest: str | None = None
    for sid in claim.calculation.input_series_ids:
        series = collector.series(sid)
        if series is not None and series.observations:
            latest = _max_session(latest, series.observations[-1].at)
    return latest


def _max_session(a: str | None, b: str | None) -> str | None:
    candidates = [x for x in (a, b) if x]
    return max(candidates) if candidates else None


def _horizon_label(question: ResearchQuestion) -> str:
    return question.horizon.value.replace("_", " ")


def _pct(value: Decimal) -> str:
    return f"{value * 100:.2f}%"
