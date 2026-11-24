"""Adversarial tests for the simulation-only SandboxExecutor (R1 §18, §20).

Covers idempotent dispatch (same key -> same result, no double effect) and the
refusal to dispatch without a valid, request-binding grant certificate.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from strix.assurance.authorization import (
    ActionRequest,
    AuthorizationError,
    AuthorizationPolicy,
    build_grant_certificate,
    make_action_request,
    make_authorization_policy,
)
from strix.assurance.executor import SandboxExecutor
from strix.evidence_graph.certificates import ClaimCertificate, build_claim_certificate
from strix.evidence_graph.nodes import PredicateName, PredicateResult, PredicateStatus

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


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
        resource_limits={"amount": "1000"},
    )


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


def test_dispatch_simulates_and_acknowledges() -> None:
    cert = _claim_cert()
    req = _request(cert=cert)
    authcert = build_grant_certificate(req, (cert,), _policy(), now=NOW)
    result = SandboxExecutor().dispatch(authcert, req)
    assert result.acknowledged is True
    assert result.action_id == req.action_id
    assert result.authorization_certificate_id == authcert.certificate_id
    assert result.simulated_state == {"amount": "500"}
    assert result.executor == "sandbox"


def test_dispatch_is_idempotent_no_double_effect() -> None:
    cert = _claim_cert()
    req = _request(cert=cert)
    authcert = build_grant_certificate(req, (cert,), _policy(), now=NOW)
    executor = SandboxExecutor()
    first = executor.dispatch(authcert, req)
    second = executor.dispatch(authcert, req)
    assert first == second
    # The duplicate-action guard short-circuits on the idempotency key before any
    # re-simulation: a later call under the same key returns the original result
    # even against a tampered certificate, proving no second effect occurs.
    tampered = authcert.model_copy(update={"action_parameters": {"amount": "1"}})
    assert executor.dispatch(tampered, req) == first


def test_refuses_dispatch_with_tampered_certificate() -> None:
    cert = _claim_cert()
    req = _request(cert=cert)
    authcert = build_grant_certificate(req, (cert,), _policy(), now=NOW)
    tampered = authcert.model_copy(update={"action_parameters": {"amount": "999999"}})
    with pytest.raises(AuthorizationError):
        SandboxExecutor().dispatch(tampered, req)


def test_refuses_dispatch_when_certificate_does_not_bind_request() -> None:
    cert = _claim_cert()
    req = _request(cert=cert)
    authcert = build_grant_certificate(req, (cert,), _policy(), now=NOW)
    other = _request(cert=cert, parameters={"amount": "700"}, idempotency_key="idem-2")
    with pytest.raises(AuthorizationError):
        SandboxExecutor().dispatch(authcert, other)


def test_refuses_dispatch_for_different_executor() -> None:
    cert = _claim_cert()
    req = _request(cert=cert)
    authcert = build_grant_certificate(req, (cert,), _policy(), now=NOW)
    with pytest.raises(AuthorizationError):
        SandboxExecutor(name="other").dispatch(authcert, req)
