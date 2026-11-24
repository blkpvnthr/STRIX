"""Independent outcome certification (R1 §20).

An executor acknowledgement alone must **never** establish success (R1 §20):
:func:`reconcile_outcome` classifies a dispatched action by comparing the
*expected* outcome against *independently observed* post-execution state within
numerical tolerance, producing an
:class:`~strix.evidence_graph.certificates.OutcomeCertificate` whose
``outcome_classification`` is one of:

- ``outcome_confirmed`` — every expected key observed and within tolerance;
- ``partial_completion`` — some expected keys confirmed, others unobserved;
- ``outcome_mismatch`` — at least one observed value is outside tolerance;
- ``execution_failed`` — the executor did not acknowledge the action;
- ``outcome_unobservable`` — nothing (relevant) was independently observed;
- ``reconciliation_required`` — the comparison is ambiguous and needs review;
- ``unauthorized_execution_detected`` — the result is not bound to this grant.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from strix.assurance.authorization import ActionRequest, _action_identity_payload
from strix.assurance.executor import ExecutorResult
from strix.canonical import canonical_hash
from strix.evidence_graph.certificates import (
    AuthorizationCertificate,
    OutcomeCertificate,
    build_outcome_certificate,
    validate_authorization_certificate,
)

__all__ = ["OutcomeClassification", "reconcile_outcome"]


class OutcomeClassification(StrEnum):
    """The terminal reconciliation verdict (R1 §20)."""

    OUTCOME_CONFIRMED = "outcome_confirmed"
    PARTIAL_COMPLETION = "partial_completion"
    OUTCOME_MISMATCH = "outcome_mismatch"
    EXECUTION_FAILED = "execution_failed"
    OUTCOME_UNOBSERVABLE = "outcome_unobservable"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    UNAUTHORIZED_EXECUTION_DETECTED = "unauthorized_execution_detected"


def _as_decimal(value: str) -> Decimal | None:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _within_tolerance(
    expected: str, observed: str, abs_tol: Decimal, rel_tol: Decimal
) -> bool:
    """True iff *observed* matches *expected* within tolerance (numeric) or exactly."""
    exp = _as_decimal(expected)
    obs = _as_decimal(observed)
    if exp is None or obs is None:
        return expected == observed
    diff = abs(exp - obs)
    return diff <= abs_tol or diff <= rel_tol * abs(exp)


def _classify(
    request: ActionRequest,
    authorization_certificate: AuthorizationCertificate,
    executor_result: ExecutorResult,
    observed_state: dict[str, str],
    expected_outcome: dict[str, str],
    abs_tol: Decimal,
    rel_tol: Decimal,
) -> OutcomeClassification:
    """Deterministic classification tree over authorization binding then evidence."""
    if (
        not validate_authorization_certificate(authorization_certificate)
        # Independently verify the certificate actually binds THIS request, rather
        # than trusting the executor's self-reported ids (R1 §20).
        or authorization_certificate.action_request_digest
        != canonical_hash(_action_identity_payload(request))
        or executor_result.authorization_certificate_id
        != authorization_certificate.certificate_id
        or executor_result.action_id != request.action_id
    ):
        return OutcomeClassification.UNAUTHORIZED_EXECUTION_DETECTED
    if not executor_result.acknowledged:
        return OutcomeClassification.EXECUTION_FAILED
    if not expected_outcome:
        return OutcomeClassification.RECONCILIATION_REQUIRED
    if not observed_state:
        return OutcomeClassification.OUTCOME_UNOBSERVABLE

    matched: list[str] = []
    missing: list[str] = []
    mismatched: list[str] = []
    for key, exp_value in expected_outcome.items():
        if key not in observed_state:
            missing.append(key)
        elif _within_tolerance(exp_value, observed_state[key], abs_tol, rel_tol):
            matched.append(key)
        else:
            mismatched.append(key)

    if mismatched:
        return OutcomeClassification.OUTCOME_MISMATCH
    if missing and matched:
        return OutcomeClassification.PARTIAL_COMPLETION
    if missing:  # nothing matched, all missing
        return OutcomeClassification.OUTCOME_UNOBSERVABLE
    return OutcomeClassification.OUTCOME_CONFIRMED


def _residuals(
    observed_state: dict[str, str], expected_outcome: dict[str, str]
) -> dict[str, Any]:
    """Per-key reconciliation residuals (exact Decimal diffs where both numeric)."""
    residuals: dict[str, Any] = {}
    for key, exp_value in expected_outcome.items():
        if key not in observed_state:
            continue
        exp = _as_decimal(exp_value)
        obs = _as_decimal(observed_state[key])
        if exp is not None and obs is not None:
            residuals[key] = abs(exp - obs)
    return residuals


def reconcile_outcome(
    request: ActionRequest,
    authorization_certificate: AuthorizationCertificate,
    executor_result: ExecutorResult,
    observed_state: dict[str, str],
    expected_outcome: dict[str, str],
    *,
    abs_tol: Decimal,
    rel_tol: Decimal,
) -> OutcomeCertificate:
    """Reconcile a dispatched action against independently observed state (R1 §20).

    Classifies by comparing *expected_outcome* against *observed_state* within
    (``abs_tol``, ``rel_tol``); an executor acknowledgement alone never yields
    ``outcome_confirmed``. Returns an :class:`OutcomeCertificate` recording the
    reported results, the independent observation, the residuals, and the
    terminal classification.
    """
    classification = _classify(
        request,
        authorization_certificate,
        executor_result,
        observed_state,
        expected_outcome,
        abs_tol,
        rel_tol,
    )
    reported: dict[str, Any] = dict(executor_result.simulated_state)
    observed: dict[str, Any] = dict(observed_state)
    expected: dict[str, Any] = dict(expected_outcome)
    return build_outcome_certificate(
        authorized_action_id=request.action_id,
        authorization_certificate_id=authorization_certificate.certificate_id,
        dispatched_action_digest=authorization_certificate.action_request_digest,
        pre_execution_evidence_digest=canonical_hash(expected),
        post_execution_evidence_digest=canonical_hash(observed),
        executor_reported_results=reported,
        independently_observed_state=observed,
        expected_outcome=expected,
        actual_outcome=observed,
        reconciliation_residuals=_residuals(observed_state, expected_outcome),
        numerical_tolerances={"absolute": abs_tol, "relative": rel_tol},
        outcome_classification=classification.value,
    )
