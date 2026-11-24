"""Adversarial tests for the independent-execution authorization kernel (GAP-001).

Covers the ordered I_a∧V_a∧C_a∧F_a∧B_a∧R_a gauntlet: a grant on a fully
satisfied request, the fail-closed default (external execution disabled), and a
denial for every individual condition. Also covers the bind-to-parameters /
TOCTOU property: mutating a parameter changes the ``action_id`` and request
digest so a prior certificate no longer authorizes via :func:`reauthorize`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from strix.assurance.authorization import (
    ActionRequest,
    AuthorizationPolicy,
    AuthorizationReasonCode,
    ConditionName,
    ConditionStatus,
    Decision,
    authorize,
    build_grant_certificate,
    make_action_request,
    make_authorization_policy,
    reauthorize,
)
from strix.evidence_graph.certificates import (
    ClaimCertificate,
    build_claim_certificate,
)
from strix.evidence_graph.nodes import (
    PredicateName,
    PredicateResult,
    PredicateStatus,
)

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FRESH = datetime(2026, 1, 1, 11, 59, 0, tzinfo=UTC)


def _claim_cert(*, issued_at: datetime = FRESH) -> ClaimCertificate:
    return build_claim_certificate(
        claim_id="CL-aaaaaaaaaaaa",
        canonical_claim_digest="a" * 64,
        evidence_graph_snapshot_digest="b" * 64,
        supporting_evidence_ids=("EV-cccccccccccc",),
        dependency_closure=("EV-cccccccccccc",),
        predicate_results=(
            PredicateResult(
                predicate=PredicateName.SUPPORT, status=PredicateStatus.PASS
            ),
        ),
        verification_policy_version="vpol-1",
        verifier_version="verifier-1",
        computation_certificate_refs=(),
        issued_at=issued_at,
    )


def _policy(**overrides: object) -> AuthorizationPolicy:
    defaults: dict[str, object] = {
        "version": "authpol-1",
        "enabled": True,
        "allowed_action_types": ("place_order",),
        "allowed_executors": ("sandbox",),
        "min_supporting_claim_certificates": 1,
        "permission_scope": ("ACCOUNT-1",),
        "resource_limits": {"amount": "1000"},
        "freshness_max_age_seconds": 3600,
        "authorization_ttl_seconds": 300,
    }
    defaults.update(overrides)
    return make_authorization_policy(**defaults)  # type: ignore[arg-type]


def _request(*, cert: ClaimCertificate, **overrides: object) -> ActionRequest:
    defaults: dict[str, object] = {
        "action_type": "place_order",
        "target": "ACCOUNT-1",
        "parameters": {"amount": "500"},
        "idempotency_key": "idem-1",
        "requested_executor": "sandbox",
        "dependency_claim_certificate_ids": (cert.certificate_id,),
    }
    defaults.update(overrides)
    return make_action_request(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Factories / identity
# --------------------------------------------------------------------------


def test_make_action_request_is_content_derived_and_deterministic() -> None:
    cert = _claim_cert()
    a = _request(cert=cert)
    b = _request(cert=cert)
    assert a.action_id == b.action_id
    assert a.action_id.startswith("ACTION-")


def test_make_authorization_policy_disabled_by_default() -> None:
    policy = make_authorization_policy(version="p", allowed_action_types=("x",))
    assert policy.enabled is False
    assert policy.policy_id.startswith("AUTHPOL-")


# --------------------------------------------------------------------------
# Grant
# --------------------------------------------------------------------------


def test_authorize_grants_fully_satisfied_request() -> None:
    cert = _claim_cert()
    decision = authorize(_request(cert=cert), (cert,), _policy(), now=NOW)
    assert decision.decision is Decision.GRANTED
    assert decision.reason_codes == ()
    assert decision.certificate_id is not None
    assert len(decision.condition_results) == 6
    assert all(c.status is ConditionStatus.PASS for c in decision.condition_results)


def test_grant_condition_results_are_in_canonical_order() -> None:
    cert = _claim_cert()
    decision = authorize(_request(cert=cert), (cert,), _policy(), now=NOW)
    assert tuple(c.condition for c in decision.condition_results) == (
        ConditionName.IDENTITY,
        ConditionName.SUPPORT,
        ConditionName.CONSTRAINTS,
        ConditionName.FRESHNESS,
        ConditionName.RESOURCE,
        ConditionName.EXECUTOR,
    )


# --------------------------------------------------------------------------
# Fail-closed default + each condition denial
# --------------------------------------------------------------------------


def test_denies_when_external_execution_disabled_by_default() -> None:
    cert = _claim_cert()
    policy = _policy(enabled=False)
    decision = authorize(_request(cert=cert), (cert,), policy, now=NOW)
    assert decision.decision is Decision.DENIED
    assert decision.certificate_id is None
    assert AuthorizationReasonCode.EXTERNAL_EXECUTION_DISABLED in decision.reason_codes


def test_denies_missing_supporting_certificate() -> None:
    cert = _claim_cert()
    decision = authorize(_request(cert=cert), (), _policy(), now=NOW)
    assert decision.decision is Decision.DENIED
    assert (
        AuthorizationReasonCode.INSUFFICIENT_SUPPORTING_CERTIFICATES
        in decision.reason_codes
    )
    assert (
        AuthorizationReasonCode.MISSING_DEPENDENCY_CERTIFICATE in decision.reason_codes
    )


def test_denies_invalid_claim_certificate() -> None:
    cert = _claim_cert()
    tampered = cert.model_copy(update={"canonical_claim_digest": "f" * 64})
    req = _request(cert=cert, dependency_claim_certificate_ids=(tampered.certificate_id,))
    decision = authorize(req, (tampered,), _policy(), now=NOW)
    assert decision.decision is Decision.DENIED
    assert AuthorizationReasonCode.INVALID_CLAIM_CERTIFICATE in decision.reason_codes


def test_denies_disallowed_action_type() -> None:
    cert = _claim_cert()
    req = _request(cert=cert, action_type="wire_transfer")
    decision = authorize(req, (cert,), _policy(), now=NOW)
    assert decision.decision is Decision.DENIED
    assert AuthorizationReasonCode.ACTION_TYPE_NOT_ALLOWED in decision.reason_codes


def test_denies_disallowed_executor() -> None:
    cert = _claim_cert()
    req = _request(cert=cert, requested_executor="live_broker")
    decision = authorize(req, (cert,), _policy(), now=NOW)
    assert decision.decision is Decision.DENIED
    assert AuthorizationReasonCode.EXECUTOR_NOT_ALLOWED in decision.reason_codes


def test_denies_target_out_of_scope() -> None:
    cert = _claim_cert()
    req = _request(cert=cert, target="ACCOUNT-OTHER")
    decision = authorize(req, (cert,), _policy(), now=NOW)
    assert decision.decision is Decision.DENIED
    assert AuthorizationReasonCode.TARGET_OUT_OF_SCOPE in decision.reason_codes


def test_denies_parameter_over_resource_limit() -> None:
    cert = _claim_cert()
    req = _request(cert=cert, parameters={"amount": "5000"})
    decision = authorize(req, (cert,), _policy(), now=NOW)
    assert decision.decision is Decision.DENIED
    assert AuthorizationReasonCode.RESOURCE_LIMIT_EXCEEDED in decision.reason_codes
    resource = next(
        c for c in decision.condition_results if c.condition is ConditionName.RESOURCE
    )
    assert resource.status is ConditionStatus.FAIL


def test_denies_negative_resource_amount() -> None:
    cert = _claim_cert()
    req = _request(cert=cert, parameters={"amount": "-1"})
    decision = authorize(req, (cert,), _policy(), now=NOW)
    assert decision.decision is Decision.DENIED
    assert AuthorizationReasonCode.NEGATIVE_RESOURCE_AMOUNT in decision.reason_codes


def test_non_numeric_limited_parameter_is_unknown_and_denies() -> None:
    cert = _claim_cert()
    req = _request(cert=cert, parameters={"amount": "lots"})
    decision = authorize(req, (cert,), _policy(), now=NOW)
    assert decision.decision is Decision.DENIED
    resource = next(
        c for c in decision.condition_results if c.condition is ConditionName.RESOURCE
    )
    assert resource.status is ConditionStatus.UNKNOWN
    assert AuthorizationReasonCode.PARAMETER_NOT_NUMERIC in decision.reason_codes


def test_denies_stale_supporting_certificate() -> None:
    stale = _claim_cert(issued_at=NOW - timedelta(seconds=7200))
    req = _request(cert=stale)
    decision = authorize(req, (stale,), _policy(), now=NOW)
    assert decision.decision is Decision.DENIED
    assert AuthorizationReasonCode.SUPPORTING_CERTIFICATE_STALE in decision.reason_codes


def test_denies_future_dated_certificate_as_skew() -> None:
    future = _claim_cert(issued_at=NOW + timedelta(seconds=120))
    req = _request(cert=future)
    decision = authorize(req, (future,), _policy(), now=NOW)
    assert decision.decision is Decision.DENIED
    assert AuthorizationReasonCode.TIMESTAMP_SKEW_DETECTED in decision.reason_codes


def test_denies_duplicate_idempotency_key() -> None:
    cert = _claim_cert()
    req = _request(cert=cert)
    decision = authorize(
        req, (cert,), _policy(), now=NOW, used_idempotency_keys=frozenset({"idem-1"})
    )
    assert decision.decision is Decision.DENIED
    assert AuthorizationReasonCode.DUPLICATE_IDEMPOTENCY_KEY in decision.reason_codes


def test_tampered_action_id_fails_identity() -> None:
    cert = _claim_cert()
    req = _request(cert=cert)
    tampered = req.model_copy(update={"action_id": "ACTION-000000000000"})
    decision = authorize(tampered, (cert,), _policy(), now=NOW)
    assert decision.decision is Decision.DENIED
    assert AuthorizationReasonCode.ACTION_ID_MISMATCH in decision.reason_codes


def test_empty_parameters_fail_identity() -> None:
    cert = _claim_cert()
    req = _request(cert=cert, parameters={})
    decision = authorize(req, (cert,), _policy(), now=NOW)
    assert decision.decision is Decision.DENIED
    assert AuthorizationReasonCode.MISSING_PARAMETERS in decision.reason_codes


# --------------------------------------------------------------------------
# reauthorize — bind-to-parameters / TOCTOU + TTL expiry
# --------------------------------------------------------------------------


def test_reauthorize_accepts_unchanged_request_in_window() -> None:
    cert = _claim_cert()
    req = _request(cert=cert)
    policy = _policy()
    granted = authorize(req, (cert,), policy, now=NOW)
    assert granted.certificate_id is not None
    authcert = build_grant_certificate(req, (cert,), policy, now=NOW)
    # The grant decision's certificate_id matches the reconstructable certificate.
    assert authcert.certificate_id == granted.certificate_id
    decision = reauthorize(authcert, req, policy, now=NOW + timedelta(seconds=60))
    assert decision.decision is Decision.GRANTED


def test_reauthorize_rejects_parameter_tampering() -> None:
    cert = _claim_cert()
    req = _request(cert=cert)
    policy = _policy()
    authcert = build_grant_certificate(req, (cert,), policy, now=NOW)
    mutated = _request(cert=cert, parameters={"amount": "999"})
    assert mutated.action_id != req.action_id
    decision = reauthorize(authcert, mutated, policy, now=NOW + timedelta(seconds=60))
    assert decision.decision is Decision.DENIED
    assert AuthorizationReasonCode.ACTION_PARAMETERS_CHANGED in decision.reason_codes


def test_reauthorize_rejects_expired_ttl() -> None:
    cert = _claim_cert()
    req = _request(cert=cert)
    policy = _policy()
    authcert = build_grant_certificate(req, (cert,), policy, now=NOW)
    decision = reauthorize(authcert, req, policy, now=NOW + timedelta(seconds=9999))
    assert decision.decision is Decision.DENIED
    assert AuthorizationReasonCode.AUTHORIZATION_EXPIRED in decision.reason_codes


def test_reauthorize_rejects_tampered_certificate() -> None:
    cert = _claim_cert()
    req = _request(cert=cert)
    policy = _policy()
    authcert = build_grant_certificate(req, (cert,), policy, now=NOW)
    tampered = authcert.model_copy(update={"authorized_executor": "live_broker"})
    decision = reauthorize(tampered, req, policy, now=NOW + timedelta(seconds=60))
    assert decision.decision is Decision.DENIED
    assert AuthorizationReasonCode.CERTIFICATE_TAMPERED in decision.reason_codes
