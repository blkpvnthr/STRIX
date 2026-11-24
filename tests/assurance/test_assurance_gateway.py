"""Adversarial tests for the six-pillar independent assurance gateway (R1 §2).

The gateway is the *independent authorization gateway* that composes the six
assurance pillars — evidence verification, policy enforcement, behavior
monitoring, uncertainty scoring, adversarial testing (regression-tested), and
decision traceability — into one deterministic :class:`GatewayDecision`. The
autonomous agent must never be able to force an ``authorized`` outcome while any
pillar objects (R1 §2). These tests confirm the documented precedence and that
agent-influenced inputs cannot override a pillar's objection.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.assurance.authorization import AuthorizationDecision, Decision
from strix.assurance.gateway import (
    GatewayDecision,
    GatewayOutcome,
    GatewayReasonCode,
    evaluate_gateway,
)
from strix.assurance.monitoring import Intervention, MonitorFinding
from strix.assurance.uncertainty import (
    StatusDimensions,
    UncertaintyAssessment,
    UncertaintyComponents,
    UncertaintyLevel,
)
from strix.evidence_graph.nodes import AdmissionOutcome, VerificationOutcome
from strix.evidence_graph.predicates import AdmissionDecision

# --------------------------------------------------------------------------
# Builders — construct the pillar inputs directly so the gateway composition
# is tested in isolation from the upstream pipelines.
# --------------------------------------------------------------------------


def _admission(
    outcome: AdmissionOutcome = AdmissionOutcome.ADMITTED,
    verification: VerificationOutcome = VerificationOutcome.VERIFIED,
) -> AdmissionDecision:
    return AdmissionDecision(
        outcome=outcome,
        verification_outcome=verification,
        predicate_results=(),
        policy_version="VP-1",
        claim_id="CC-1",
    )


def _uncertainty(
    level: UncertaintyLevel = UncertaintyLevel.LOW,
    *,
    abstention_recommended: bool = False,
    answer_completeness: str = "complete",
    evidence_sufficiency: Decimal = Decimal(1),
) -> UncertaintyAssessment:
    components = UncertaintyComponents(
        evidence_sufficiency=evidence_sufficiency,
        freshness_ok=True,
        source_disagreement_count=0,
        missing_requirements=(),
        statistical_uncertainty_present=False,
        abstention_recommended=abstention_recommended,
    )
    dimensions = StatusDimensions(
        verification_status="no_contradictions_detected",
        evidence_quality="fresh",
        answer_completeness=answer_completeness,
        analytical_uncertainty="no_statistical_uncertainty_flagged",
        authorization_status="granted",
    )
    return UncertaintyAssessment(
        level=level,
        components=components,
        dimensions=dimensions,
        reason_codes=("no_calibrated_probability_available",),
    )


def _monitor(intervention: Intervention = Intervention.CONTINUE) -> MonitorFinding:
    return MonitorFinding(
        intervention=intervention,
        reason_codes=() if intervention is Intervention.CONTINUE else ("x",),
        tool_calls=0,
        identical_call_runs=0,
        total_cost=Decimal(0),
        verification_failures=0,
    )


def _authorization(decision: Decision = Decision.GRANTED) -> AuthorizationDecision:
    return AuthorizationDecision(
        decision=decision,
        reason_codes=(),
        action_id="ACTION-1",
        policy_version="AP-1",
        certificate_id="AUTHCERT-1" if decision is Decision.GRANTED else None,
        condition_results=(),
    )


# --------------------------------------------------------------------------
# Taxonomy / model discipline
# --------------------------------------------------------------------------


def test_gateway_outcome_values() -> None:
    assert {o.value for o in GatewayOutcome} == {
        "authorized",
        "qualified",
        "review_required",
        "abstain",
        "rejected",
    }


def test_gateway_decision_is_frozen_and_closed() -> None:
    decision = evaluate_gateway(
        admission=_admission(),
        uncertainty=_uncertainty(),
        monitor_finding=_monitor(),
    )
    assert isinstance(decision, GatewayDecision)
    # Frozen: fields cannot be reassigned.
    with pytest.raises(ValidationError):
        decision.outcome = GatewayOutcome.REJECTED  # type: ignore[misc]
    # Closed schema: extra fields are rejected at construction.
    with pytest.raises(ValidationError):
        GatewayDecision(  # type: ignore[call-arg]
            outcome=GatewayOutcome.AUTHORIZED,
            reason_codes=(),
            verification_outcome="verified",
            authorization_decision=None,
            uncertainty_level="low",
            intervention="continue",
            unknown_field=1,
        )


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------


def test_all_clear_without_authorization_is_authorized() -> None:
    decision = evaluate_gateway(
        admission=_admission(),
        uncertainty=_uncertainty(),
        monitor_finding=_monitor(),
    )
    assert decision.outcome is GatewayOutcome.AUTHORIZED
    assert decision.authorization_decision is None
    assert decision.verification_outcome == VerificationOutcome.VERIFIED.value
    assert decision.uncertainty_level == UncertaintyLevel.LOW.value
    assert decision.intervention == Intervention.CONTINUE.value
    assert GatewayReasonCode.ALL_PILLARS_CLEARED.value in decision.reason_codes


def test_all_clear_with_granted_authorization_is_authorized() -> None:
    decision = evaluate_gateway(
        admission=_admission(),
        uncertainty=_uncertainty(),
        monitor_finding=_monitor(),
        authorization=_authorization(Decision.GRANTED),
    )
    assert decision.outcome is GatewayOutcome.AUTHORIZED
    assert decision.authorization_decision == Decision.GRANTED.value


# --------------------------------------------------------------------------
# Qualified — admitted but elevated/partial uncertainty
# --------------------------------------------------------------------------


@pytest.mark.parametrize("level", [UncertaintyLevel.MODERATE, UncertaintyLevel.HIGH])
def test_admitted_with_elevated_uncertainty_is_qualified(
    level: UncertaintyLevel,
) -> None:
    decision = evaluate_gateway(
        admission=_admission(),
        uncertainty=_uncertainty(level),
        monitor_finding=_monitor(),
    )
    assert decision.outcome is GatewayOutcome.QUALIFIED
    assert GatewayReasonCode.UNCERTAINTY_ELEVATED.value in decision.reason_codes


def test_admitted_with_partial_coverage_is_qualified_not_authorized() -> None:
    # Even if the (agent-influenced) level reads "low", partial coverage must
    # still prevent a full authorization.
    decision = evaluate_gateway(
        admission=_admission(),
        uncertainty=_uncertainty(
            UncertaintyLevel.LOW, answer_completeness="partial"
        ),
        monitor_finding=_monitor(),
    )
    assert decision.outcome is GatewayOutcome.QUALIFIED
    assert GatewayReasonCode.PARTIAL_COVERAGE.value in decision.reason_codes


# --------------------------------------------------------------------------
# Abstain
# --------------------------------------------------------------------------


def test_admission_abstained_is_abstain() -> None:
    decision = evaluate_gateway(
        admission=_admission(
            AdmissionOutcome.ABSTAINED, VerificationOutcome.UNVERIFIABLE
        ),
        uncertainty=_uncertainty(),
        monitor_finding=_monitor(),
    )
    assert decision.outcome is GatewayOutcome.ABSTAIN
    assert GatewayReasonCode.ADMISSION_ABSTAINED.value in decision.reason_codes


def test_insufficient_uncertainty_is_abstain() -> None:
    decision = evaluate_gateway(
        admission=_admission(),
        uncertainty=_uncertainty(UncertaintyLevel.INSUFFICIENT),
        monitor_finding=_monitor(),
    )
    assert decision.outcome is GatewayOutcome.ABSTAIN
    assert GatewayReasonCode.UNCERTAINTY_INSUFFICIENT.value in decision.reason_codes


def test_abstention_recommended_overrides_admitted_low() -> None:
    # Admitted + low level would be AUTHORIZED, but a recommended abstention is a
    # pillar objection and must win over authorization.
    decision = evaluate_gateway(
        admission=_admission(),
        uncertainty=_uncertainty(
            UncertaintyLevel.LOW, abstention_recommended=True
        ),
        monitor_finding=_monitor(),
        authorization=_authorization(Decision.GRANTED),
    )
    assert decision.outcome is GatewayOutcome.ABSTAIN
    assert GatewayReasonCode.ABSTENTION_RECOMMENDED.value in decision.reason_codes


def test_monitor_abstain_is_abstain() -> None:
    decision = evaluate_gateway(
        admission=_admission(),
        uncertainty=_uncertainty(),
        monitor_finding=_monitor(Intervention.ABSTAIN),
    )
    assert decision.outcome is GatewayOutcome.ABSTAIN
    assert GatewayReasonCode.MONITOR_ABSTAIN.value in decision.reason_codes


# --------------------------------------------------------------------------
# Review required
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("intervention", "code"),
    [
        (Intervention.ESCALATE_HUMAN, GatewayReasonCode.MONITOR_ESCALATE_HUMAN),
        (Intervention.RESTRICT, GatewayReasonCode.MONITOR_RESTRICT),
    ],
)
def test_monitor_escalate_or_restrict_is_review_required(
    intervention: Intervention, code: GatewayReasonCode
) -> None:
    decision = evaluate_gateway(
        admission=_admission(),
        uncertainty=_uncertainty(),
        monitor_finding=_monitor(intervention),
        authorization=_authorization(Decision.GRANTED),
    )
    assert decision.outcome is GatewayOutcome.REVIEW_REQUIRED
    assert code.value in decision.reason_codes


# --------------------------------------------------------------------------
# Rejected
# --------------------------------------------------------------------------


def test_monitor_terminate_is_rejected() -> None:
    decision = evaluate_gateway(
        admission=_admission(),
        uncertainty=_uncertainty(),
        monitor_finding=_monitor(Intervention.TERMINATE),
    )
    assert decision.outcome is GatewayOutcome.REJECTED
    assert GatewayReasonCode.MONITOR_TERMINATE.value in decision.reason_codes


def test_verification_rejected_is_rejected() -> None:
    decision = evaluate_gateway(
        admission=_admission(
            AdmissionOutcome.REJECTED, VerificationOutcome.INTEGRITY_FAILURE
        ),
        uncertainty=_uncertainty(),
        monitor_finding=_monitor(),
    )
    assert decision.outcome is GatewayOutcome.REJECTED
    assert GatewayReasonCode.ADMISSION_REJECTED.value in decision.reason_codes


def test_authorization_denied_is_rejected() -> None:
    decision = evaluate_gateway(
        admission=_admission(),
        uncertainty=_uncertainty(),
        monitor_finding=_monitor(),
        authorization=_authorization(Decision.DENIED),
    )
    assert decision.outcome is GatewayOutcome.REJECTED
    assert GatewayReasonCode.AUTHORIZATION_DENIED.value in decision.reason_codes
    assert decision.authorization_decision == Decision.DENIED.value


# --------------------------------------------------------------------------
# Precedence — terminate beats everything; pillars cannot be overridden
# --------------------------------------------------------------------------


def test_terminate_beats_everything() -> None:
    # Every other pillar is maximally favourable; terminate still wins.
    decision = evaluate_gateway(
        admission=_admission(),
        uncertainty=_uncertainty(),
        monitor_finding=_monitor(Intervention.TERMINATE),
        authorization=_authorization(Decision.GRANTED),
    )
    assert decision.outcome is GatewayOutcome.REJECTED


def test_rejection_beats_review_and_abstain() -> None:
    # Admission rejected AND monitor restrict AND uncertainty insufficient: the
    # most severe (rejected) is selected.
    decision = evaluate_gateway(
        admission=_admission(
            AdmissionOutcome.REJECTED, VerificationOutcome.INVALID_EVIDENCE
        ),
        uncertainty=_uncertainty(UncertaintyLevel.INSUFFICIENT),
        monitor_finding=_monitor(Intervention.RESTRICT),
    )
    assert decision.outcome is GatewayOutcome.REJECTED


def test_review_required_beats_abstain() -> None:
    decision = evaluate_gateway(
        admission=_admission(
            AdmissionOutcome.ABSTAINED, VerificationOutcome.UNVERIFIABLE
        ),
        uncertainty=_uncertainty(UncertaintyLevel.INSUFFICIENT),
        monitor_finding=_monitor(Intervention.ESCALATE_HUMAN),
    )
    assert decision.outcome is GatewayOutcome.REVIEW_REQUIRED


# --------------------------------------------------------------------------
# The core assurance invariant: the agent cannot force AUTHORIZED when any
# pillar objects (R1 §2).
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "objecting_kwargs",
    [
        # evidence pillar objects
        {"admission": _admission(AdmissionOutcome.REJECTED, VerificationOutcome.CONTRADICTED)},
        {"admission": _admission(AdmissionOutcome.ABSTAINED, VerificationOutcome.UNVERIFIABLE)},
        # monitor pillar objects
        {"monitor_finding": _monitor(Intervention.TERMINATE)},
        {"monitor_finding": _monitor(Intervention.RESTRICT)},
        {"monitor_finding": _monitor(Intervention.ESCALATE_HUMAN)},
        {"monitor_finding": _monitor(Intervention.ABSTAIN)},
        # uncertainty pillar objects
        {"uncertainty": _uncertainty(UncertaintyLevel.HIGH)},
        {"uncertainty": _uncertainty(UncertaintyLevel.INSUFFICIENT)},
        {"uncertainty": _uncertainty(UncertaintyLevel.LOW, abstention_recommended=True)},
        # authorization pillar objects
        {"authorization": _authorization(Decision.DENIED)},
    ],
)
def test_no_pillar_objection_can_yield_authorized(
    objecting_kwargs: dict[str, object],
) -> None:
    # Start from an all-green baseline, then let exactly one pillar object.
    kwargs: dict[str, object] = {
        "admission": _admission(),
        "uncertainty": _uncertainty(),
        "monitor_finding": _monitor(),
        "authorization": _authorization(Decision.GRANTED),
    }
    kwargs.update(objecting_kwargs)
    decision = evaluate_gateway(**kwargs)  # type: ignore[arg-type]
    assert decision.outcome is not GatewayOutcome.AUTHORIZED


# --------------------------------------------------------------------------
# Determinism & field population
# --------------------------------------------------------------------------


def test_evaluation_is_deterministic() -> None:
    args = {
        "admission": _admission(),
        "uncertainty": _uncertainty(UncertaintyLevel.MODERATE),
        "monitor_finding": _monitor(),
        "authorization": _authorization(Decision.GRANTED),
    }
    first = evaluate_gateway(**args)  # type: ignore[arg-type]
    second = evaluate_gateway(**args)  # type: ignore[arg-type]
    assert first == second


def test_reason_codes_are_sorted_and_unique() -> None:
    decision = evaluate_gateway(
        admission=_admission(
            AdmissionOutcome.REJECTED, VerificationOutcome.INTEGRITY_FAILURE
        ),
        uncertainty=_uncertainty(),
        monitor_finding=_monitor(Intervention.TERMINATE),
        authorization=_authorization(Decision.DENIED),
    )
    codes = decision.reason_codes
    assert list(codes) == sorted(codes)
    assert len(codes) == len(set(codes))
    # All three rejection signals aggregate.
    assert GatewayReasonCode.MONITOR_TERMINATE.value in codes
    assert GatewayReasonCode.ADMISSION_REJECTED.value in codes
    assert GatewayReasonCode.AUTHORIZATION_DENIED.value in codes
