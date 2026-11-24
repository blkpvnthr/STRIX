"""Adversarial tests for independent outcome reconciliation (R1 §20).

An executor acknowledgement alone never establishes success: classification is
driven by comparing the expected outcome against independently observed state.
Covers confirmed, mismatch, partial, unobservable (ack-without-observed-change),
execution-failed, and unauthorized-execution detection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from strix.assurance.authorization import (
    ActionRequest,
    AuthorizationPolicy,
    build_grant_certificate,
    make_action_request,
    make_authorization_policy,
)
from strix.assurance.executor import ExecutorResult, SandboxExecutor
from strix.assurance.outcome import OutcomeClassification, reconcile_outcome
from strix.evidence_graph.certificates import (
    AuthorizationCertificate,
    ClaimCertificate,
    build_claim_certificate,
    validate_outcome_certificate,
)
from strix.evidence_graph.nodes import PredicateName, PredicateResult, PredicateStatus

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
ABS_TOL = Decimal("0.01")
REL_TOL = Decimal("0")


def _claim_cert() -> ClaimCertificate:
    return build_claim_certificate(
        claim_id="CL-aaaaaaaaaaaa",
        canonical_claim_digest="a" * 64,
        evidence_graph_snapshot_digest="b" * 64,
        supporting_evidence_ids=("EV-cccccccccccc",),
        dependency_closure=("EV-cccccccccccc",),
        predicate_results=(
            PredicateResult(predicate=PredicateName.SUPPORT, status=PredicateStatus.PASS),
        ),
        verification_policy_version="vpol-1",
        verifier_version="verifier-1",
        computation_certificate_refs=(),
        issued_at=NOW,
    )


def _policy() -> AuthorizationPolicy:
    return make_authorization_policy(
        version="authpol-1",
        enabled=True,
        allowed_action_types=("place_order",),
        allowed_executors=("sandbox",),
        permission_scope=("ACCOUNT-1",),
        resource_limits={"filled": "1000"},
    )


def _scenario() -> tuple[ActionRequest, AuthorizationCertificate, ExecutorResult]:
    cert = _claim_cert()
    req = make_action_request(
        action_type="place_order",
        target="ACCOUNT-1",
        parameters={"filled": "100"},
        idempotency_key="idem-1",
        requested_executor="sandbox",
        dependency_claim_certificate_ids=(cert.certificate_id,),
    )
    authcert = build_grant_certificate(req, (cert,), _policy(), now=NOW)
    result = SandboxExecutor().dispatch(authcert, req)
    return req, authcert, result


def test_outcome_confirmed_when_observed_matches_expected() -> None:
    req, authcert, result = _scenario()
    outcome = reconcile_outcome(
        req,
        authcert,
        result,
        observed_state={"filled": "100"},
        expected_outcome={"filled": "100"},
        abs_tol=ABS_TOL,
        rel_tol=REL_TOL,
    )
    assert outcome.outcome_classification == OutcomeClassification.OUTCOME_CONFIRMED.value
    assert validate_outcome_certificate(outcome) is True


def test_outcome_confirmed_within_tolerance() -> None:
    req, authcert, result = _scenario()
    outcome = reconcile_outcome(
        req,
        authcert,
        result,
        observed_state={"filled": "100.005"},
        expected_outcome={"filled": "100"},
        abs_tol=ABS_TOL,
        rel_tol=REL_TOL,
    )
    assert outcome.outcome_classification == OutcomeClassification.OUTCOME_CONFIRMED.value


def test_outcome_mismatch_outside_tolerance() -> None:
    req, authcert, result = _scenario()
    outcome = reconcile_outcome(
        req,
        authcert,
        result,
        observed_state={"filled": "40"},
        expected_outcome={"filled": "100"},
        abs_tol=ABS_TOL,
        rel_tol=REL_TOL,
    )
    assert outcome.outcome_classification == OutcomeClassification.OUTCOME_MISMATCH.value
    assert outcome.reconciliation_residuals["filled"] == Decimal("60")


def test_ack_without_observed_change_is_not_confirmed() -> None:
    req, authcert, result = _scenario()
    assert result.acknowledged is True
    outcome = reconcile_outcome(
        req,
        authcert,
        result,
        observed_state={},
        expected_outcome={"filled": "100"},
        abs_tol=ABS_TOL,
        rel_tol=REL_TOL,
    )
    assert (
        outcome.outcome_classification
        == OutcomeClassification.OUTCOME_UNOBSERVABLE.value
    )


def test_partial_completion_some_keys_unobserved() -> None:
    req, authcert, result = _scenario()
    outcome = reconcile_outcome(
        req,
        authcert,
        result,
        observed_state={"filled": "100"},
        expected_outcome={"filled": "100", "settled": "100"},
        abs_tol=ABS_TOL,
        rel_tol=REL_TOL,
    )
    assert (
        outcome.outcome_classification
        == OutcomeClassification.PARTIAL_COMPLETION.value
    )


def test_execution_failed_when_not_acknowledged() -> None:
    req, authcert, result = _scenario()
    unacked = result.model_copy(update={"acknowledged": False})
    outcome = reconcile_outcome(
        req,
        authcert,
        unacked,
        observed_state={"filled": "100"},
        expected_outcome={"filled": "100"},
        abs_tol=ABS_TOL,
        rel_tol=REL_TOL,
    )
    assert outcome.outcome_classification == OutcomeClassification.EXECUTION_FAILED.value


def test_unauthorized_execution_detected_on_certificate_binding_break() -> None:
    req, authcert, result = _scenario()
    forged = result.model_copy(
        update={"authorization_certificate_id": "AUTHCERT-000000000000"}
    )
    outcome = reconcile_outcome(
        req,
        authcert,
        forged,
        observed_state={"filled": "100"},
        expected_outcome={"filled": "100"},
        abs_tol=ABS_TOL,
        rel_tol=REL_TOL,
    )
    assert (
        outcome.outcome_classification
        == OutcomeClassification.UNAUTHORIZED_EXECUTION_DETECTED.value
    )


def test_unauthorized_execution_detected_on_tampered_certificate() -> None:
    req, authcert, result = _scenario()
    tampered = authcert.model_copy(update={"authorized_executor": "live_broker"})
    outcome = reconcile_outcome(
        req,
        tampered,
        result.model_copy(update={"authorization_certificate_id": tampered.certificate_id}),
        observed_state={"filled": "100"},
        expected_outcome={"filled": "100"},
        abs_tol=ABS_TOL,
        rel_tol=REL_TOL,
    )
    assert (
        outcome.outcome_classification
        == OutcomeClassification.UNAUTHORIZED_EXECUTION_DETECTED.value
    )
