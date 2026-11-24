"""Security regressions for the GAP adversarial review (workflow wf_4e2cb7c3-6ee):

- Freshness was gated on ``issued_at``, which is excluded from a ClaimCertificate's
  content identity, so advancing it via model_copy revived a stale cert undetected.
  Fix: freshness anchors on the identity-protected ``applicable_temporal_cutoff``.
- reconcile_outcome trusted the executor's self-reported ids and never checked that
  the authorization certificate actually binds the reconciled request. Fix: it now
  compares the certificate's action_request_digest to the request's identity.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from strix.assurance.authorization import (
    AuthorizationReasonCode,
    ConditionStatus,
    _eval_freshness,
    build_grant_certificate,
    make_action_request,
    make_authorization_policy,
)
from strix.assurance.executor import ExecutorResult
from strix.assurance.outcome import OutcomeClassification, reconcile_outcome
from strix.evidence_graph.certificates import ClaimCertificate, build_claim_certificate
from strix.evidence_graph.nodes import PredicateName, PredicateResult, PredicateStatus

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def _claim_cert(*, cutoff: date | None, issued_at: datetime) -> ClaimCertificate:
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
        applicable_temporal_cutoff=cutoff,
        issued_at=issued_at,
    )


class TestFreshnessAnchor:
    def test_old_cutoff_is_stale_despite_fresh_issued_at(self) -> None:
        # issued_at advanced to "now" (the tamper), but the identity-protected
        # as-of cutoff is old, so freshness must still deny.
        cert = _claim_cert(cutoff=date(2020, 1, 1), issued_at=NOW)
        policy = make_authorization_policy(version="1", freshness_max_age_seconds=3600)
        status, codes, _ = _eval_freshness((cert,), policy, NOW)
        assert status is ConditionStatus.FAIL
        assert AuthorizationReasonCode.SUPPORTING_CERTIFICATE_STALE in codes

    def test_recent_cutoff_is_fresh(self) -> None:
        # Two-day window: the as-of cutoff anchors at date midnight, so "today"
        # is up to 24h old; a same-day cutoff is within a 2-day freshness window.
        cert = _claim_cert(cutoff=NOW.date(), issued_at=NOW)
        policy = make_authorization_policy(version="1", freshness_max_age_seconds=172800)
        status, _codes, _ = _eval_freshness((cert,), policy, NOW)
        assert status is ConditionStatus.PASS


def _policy() -> object:
    return make_authorization_policy(
        version="1",
        enabled=True,
        allowed_action_types=("transfer",),
        allowed_executors=("sandbox",),
        permission_scope=("acct-1", "acct-2"),
    )


class TestOutcomeBinding:
    def test_certificate_for_other_request_is_unauthorized(self) -> None:
        certs = (_claim_cert(cutoff=NOW.date(), issued_at=NOW),)
        dep = (certs[0].certificate_id,)
        r1 = make_action_request(
            action_type="transfer", target="acct-1", parameters={"amount": "10"},
            idempotency_key="k1", requested_executor="sandbox",
            dependency_claim_certificate_ids=dep,
        )
        r2 = make_action_request(
            action_type="transfer", target="acct-2", parameters={"amount": "10"},
            idempotency_key="k2", requested_executor="sandbox",
            dependency_claim_certificate_ids=dep,
        )
        cert_for_r1 = build_grant_certificate(r1, certs, _policy(), now=NOW)  # type: ignore[arg-type]
        # Forge an executor result that self-reports R2 under R1's certificate.
        forged = ExecutorResult(
            action_id=r2.action_id,
            authorization_certificate_id=cert_for_r1.certificate_id,
            acknowledged=True,
            simulated_state={"amount": "10"},
            executor="sandbox",
        )
        outcome = reconcile_outcome(
            r2, cert_for_r1, forged, {"amount": "10"}, {"amount": "10"},
            abs_tol=Decimal("0.01"), rel_tol=Decimal("0"),
        )
        assert (
            outcome.outcome_classification
            == OutcomeClassification.UNAUTHORIZED_EXECUTION_DETECTED
        )

    def test_matching_request_confirms(self) -> None:
        certs = (_claim_cert(cutoff=NOW.date(), issued_at=NOW),)
        dep = (certs[0].certificate_id,)
        r1 = make_action_request(
            action_type="transfer", target="acct-1", parameters={"amount": "10"},
            idempotency_key="k1", requested_executor="sandbox",
            dependency_claim_certificate_ids=dep,
        )
        cert = build_grant_certificate(r1, certs, _policy(), now=NOW)  # type: ignore[arg-type]
        result = ExecutorResult(
            action_id=r1.action_id,
            authorization_certificate_id=cert.certificate_id,
            acknowledged=True,
            simulated_state={"amount": "10"},
            executor="sandbox",
        )
        outcome = reconcile_outcome(
            r1, cert, result, {"amount": "10"}, {"amount": "10"},
            abs_tol=Decimal("0.01"), rel_tol=Decimal("0"),
        )
        assert outcome.outcome_classification == OutcomeClassification.OUTCOME_CONFIRMED
