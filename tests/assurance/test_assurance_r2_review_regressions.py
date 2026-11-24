"""Regressions for the R2 adversarial review (workflow wf_8f4daeac-3d3):

- MAJOR monitoring: a negative-cost event could pull the running total back under
  the budget and evade the cost circuit-breaker. Fix: cost must be non-negative.
- MINOR signing: verify_signature computed the payload digest outside its
  try/except, so a non-serializable certificate raised instead of returning False.
- MINOR gateway: AUTHORIZED used a partial-coverage blacklist; any other/unknown
  completeness label slipped to AUTHORIZED. Fix: whitelist 'complete'.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.assurance.gateway import GatewayOutcome, evaluate_gateway
from strix.assurance.monitoring import (
    BehaviorMonitor,
    Intervention,
    MonitoredEvent,
    MonitoredEventType,
    MonitorPolicy,
)
from strix.assurance.signing import generate_keypair, sign_certificate, verify_signature
from strix.assurance.uncertainty import (
    StatusDimensions,
    UncertaintyAssessment,
    UncertaintyComponents,
    UncertaintyLevel,
)
from strix.evidence_graph.nodes import AdmissionOutcome, VerificationOutcome
from strix.evidence_graph.predicates import AdmissionDecision
from strix.models import StrixModel

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


class TestMonitorCostCannotBeSuppressed:
    def test_negative_cost_event_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MonitoredEvent(
                event_type=MonitoredEventType.COST_INCURRED,
                label="refund-trick", cost=Decimal("-100"), timestamp=NOW,
            )

    def test_cost_breaker_holds(self) -> None:
        policy = MonitorPolicy(
            max_tool_calls=100, max_identical_calls=5, max_cost=Decimal("1.0"),
            max_verification_failures=3,
        )
        monitor = BehaviorMonitor(policy)
        monitor.record(MonitoredEvent(
            event_type=MonitoredEventType.COST_INCURRED, label="a",
            cost=Decimal("2.0"), timestamp=NOW,
        ))
        assert monitor.assess().intervention is Intervention.TERMINATE


class _BadCert(StrixModel):
    data: bytes  # bytes is not canonically serializable -> digest raises


class TestVerifySignatureFailClosed:
    def test_non_serializable_certificate_returns_false_not_raise(self) -> None:
        priv, key_record = generate_keypair(created_at=NOW)
        good = StatusDimensions(
            verification_status="x", evidence_quality="x", answer_completeness="x",
            analytical_uncertainty="x", authorization_status="x",
        )  # any serializable StrixModel works as the "good" signed certificate
        sig = sign_certificate(good, priv, key_record, domain="d", signed_at=NOW)
        from strix.assurance.signing import Keyring

        keyring = Keyring()
        keyring.register(key_record)
        # Must return False (fail-closed), never raise, on a non-serializable cert.
        assert verify_signature(_BadCert(data=b"x"), sig, keyring, expected_domain="d") is False


def _assessment(*, completeness: str) -> UncertaintyAssessment:
    return UncertaintyAssessment(
        level=UncertaintyLevel.LOW,
        components=UncertaintyComponents(
            evidence_sufficiency=Decimal("1"), freshness_ok=True,
            source_disagreement_count=0, missing_requirements=(),
            statistical_uncertainty_present=False, abstention_recommended=False,
        ),
        dimensions=StatusDimensions(
            verification_status="verified", evidence_quality="high",
            answer_completeness=completeness, analytical_uncertainty="low",
            authorization_status="n/a",
        ),
        reason_codes=(),
    )


def _admitted() -> AdmissionDecision:
    return AdmissionDecision(
        outcome=AdmissionOutcome.ADMITTED, verification_outcome=VerificationOutcome.VERIFIED,
        predicate_results=(), policy_version="p", claim_id="c",
    )


class TestGatewayAuthorizesOnlyCompleteCoverage:
    def test_unknown_completeness_label_not_authorized(self) -> None:
        monitor = BehaviorMonitor(MonitorPolicy(
            max_tool_calls=100, max_identical_calls=5, max_cost=Decimal("1"),
            max_verification_failures=3,
        ))
        finding = monitor.assess()  # continue
        decision = evaluate_gateway(
            admission=_admitted(), uncertainty=_assessment(completeness="no_coverage"),
            monitor_finding=finding,
        )
        assert decision.outcome is not GatewayOutcome.AUTHORIZED

    def test_complete_coverage_is_authorized(self) -> None:
        monitor = BehaviorMonitor(MonitorPolicy(
            max_tool_calls=100, max_identical_calls=5, max_cost=Decimal("1"),
            max_verification_failures=3,
        ))
        decision = evaluate_gateway(
            admission=_admitted(), uncertainty=_assessment(completeness="complete"),
            monitor_finding=monitor.assess(),
        )
        assert decision.outcome is GatewayOutcome.AUTHORIZED
