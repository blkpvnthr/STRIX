"""Tests for the four R1 §13 certificate classes.

Each certificate carries a content-derived ``certificate_id`` computed over its
*deterministic* content only. Nondeterministic execution metadata (``issued_at``
wall-clock) is excluded from the id, from ``certificate_hash``, and from
``validate_*`` comparison. The tests cover:

- deterministic, reproducible ids from the ``build_*`` factories;
- ``validate_*`` returning ``True`` for an untampered certificate and ``False``
  after mutating a deterministic field (simulated via ``model_copy``);
- ``issued_at`` changes leaving the id, hash, and validation untouched;
- ``certificate_hash`` determinism and independence from ``issued_at``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from strix.evidence_graph.certificates import (
    AuthorizationCertificate,
    ClaimCertificate,
    ComputationCertificate,
    OutcomeCertificate,
    build_authorization_certificate,
    build_claim_certificate,
    build_computation_certificate,
    build_outcome_certificate,
    certificate_hash,
    validate_authorization_certificate,
    validate_claim_certificate,
    validate_computation_certificate,
    validate_outcome_certificate,
)
from strix.evidence_graph.nodes import (
    PredicateName,
    PredicateResult,
    PredicateStatus,
)
from strix.native.contracts import ContractClass, NumericalContract

ISSUED = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
ISSUED_LATER = datetime(2025, 6, 7, 8, 9, 10, tzinfo=UTC)
AUTH_TS = datetime(2024, 5, 1, 0, 0, 0, tzinfo=UTC)
EXP_TS = datetime(2024, 5, 1, 1, 0, 0, tzinfo=UTC)

CONTRACT = NumericalContract(
    representation="decimal",
    contract_class=ContractClass.EXACT,
    precision="arbitrary",
    rounding="round_half_even",
    reference_method="python_reference_div",
)


# --------------------------------------------------------------------------
# ComputationCertificate
# --------------------------------------------------------------------------


def _computation() -> ComputationCertificate:
    return build_computation_certificate(
        algorithm_id="operating_margin",
        algorithm_version="1.0.0",
        input_digest="a" * 64,
        input_artifact_refs=("ART-aaaaaaaaaaaa",),
        input_observation_ids=("OBS-bbbbbbbbbbbb", "OBS-cccccccccccc"),
        output_digest="d" * 64,
        backend_version="native_cpu-0.1",
        numerical_contract=CONTRACT,
        applicable_tolerances={"absolute": Decimal("0"), "relative": Decimal("0")},
        validation_status="parity_passed",
        reference_results=(Decimal("0.25"),),
        error_measurements={"max_abs_error": Decimal("0")},
        random_seed=None,
        issued_at=ISSUED,
    )


def test_computation_build_is_deterministic() -> None:
    a = _computation()
    b = _computation()
    assert a.certificate_id == b.certificate_id
    assert a.certificate_id.startswith("COMPCERT-")


def test_computation_validate_true_for_untampered() -> None:
    assert validate_computation_certificate(_computation()) is True


def test_computation_validate_false_after_tamper() -> None:
    cert = _computation()
    tampered = cert.model_copy(update={"output_digest": "e" * 64})
    assert tampered.certificate_id == cert.certificate_id  # id not recomputed
    assert validate_computation_certificate(tampered) is False


def test_computation_issued_at_not_in_identity() -> None:
    cert = _computation()
    rescheduled = cert.model_copy(update={"issued_at": ISSUED_LATER})
    assert rescheduled.certificate_id == cert.certificate_id
    assert validate_computation_certificate(rescheduled) is True
    assert certificate_hash(rescheduled) == certificate_hash(cert)


def test_computation_dict_contract_equivalent_to_model() -> None:
    model_cert = _computation()
    dict_cert = build_computation_certificate(
        algorithm_id="operating_margin",
        algorithm_version="1.0.0",
        input_digest="a" * 64,
        input_artifact_refs=("ART-aaaaaaaaaaaa",),
        input_observation_ids=("OBS-bbbbbbbbbbbb", "OBS-cccccccccccc"),
        output_digest="d" * 64,
        backend_version="native_cpu-0.1",
        numerical_contract=CONTRACT.model_dump(),
        applicable_tolerances={"absolute": Decimal("0"), "relative": Decimal("0")},
        validation_status="parity_passed",
        reference_results=(Decimal("0.25"),),
        error_measurements={"max_abs_error": Decimal("0")},
        random_seed=None,
        issued_at=ISSUED_LATER,
    )
    assert dict_cert.certificate_id == model_cert.certificate_id


# --------------------------------------------------------------------------
# ClaimCertificate
# --------------------------------------------------------------------------


def _claim() -> ClaimCertificate:
    results = (
        PredicateResult(predicate=PredicateName.INTEGRITY, status=PredicateStatus.PASS),
        PredicateResult(predicate=PredicateName.SUPPORT, status=PredicateStatus.PASS),
    )
    return build_claim_certificate(
        claim_id="CC-dddddddddddd",
        canonical_claim_digest="1" * 64,
        evidence_graph_snapshot_digest="2" * 64,
        supporting_evidence_ids=("EV-eeeeeeeeeeee",),
        dependency_closure=("OBS-bbbbbbbbbbbb", "CALC-ffffffffffff"),
        predicate_results=results,
        verification_policy_version="vpol-1",
        verifier_version="verifier-1",
        computation_certificate_refs=("COMPCERT-000000000000",),
        applicable_temporal_cutoff=date(2024, 3, 31),
        verified_value=Decimal("0.25"),
        measurement_unit="ratio",
        numerical_tolerance=Decimal("0"),
        issued_at=ISSUED,
    )


def test_claim_build_is_deterministic() -> None:
    assert _claim().certificate_id == _claim().certificate_id
    assert _claim().certificate_id.startswith("CLAIMCERT-")


def test_claim_validate_true_for_untampered() -> None:
    assert validate_claim_certificate(_claim()) is True


def test_claim_validate_false_after_tamper() -> None:
    cert = _claim()
    tampered = cert.model_copy(update={"verified_value": Decimal("0.99")})
    assert validate_claim_certificate(tampered) is False


def test_claim_issued_at_not_in_identity() -> None:
    cert = _claim()
    rescheduled = cert.model_copy(update={"issued_at": ISSUED_LATER})
    assert rescheduled.certificate_id == cert.certificate_id
    assert validate_claim_certificate(rescheduled) is True


# --------------------------------------------------------------------------
# AuthorizationCertificate
# --------------------------------------------------------------------------


def _authorization() -> AuthorizationCertificate:
    return build_authorization_certificate(
        action_request_digest="3" * 64,
        action_parameters={"symbol": "ABC", "quantity": 10},
        evidence_graph_snapshot_digest="2" * 64,
        supporting_claim_certificate_ids=("CLAIMCERT-000000000000",),
        authorization_policy_version="authpol-1",
        authorized_executor="paper-broker-1",
        resource_limits={"max_notional": Decimal("1000")},
        permission_scope=("place_order",),
        authorization_timestamp=AUTH_TS,
        expiration_timestamp=EXP_TS,
        idempotency_key="idem-123",
        decision="granted",
        rejection_reason_codes=(),
        issued_at=ISSUED,
    )


def test_authorization_build_is_deterministic() -> None:
    assert _authorization().certificate_id == _authorization().certificate_id
    assert _authorization().certificate_id.startswith("AUTHCERT-")


def test_authorization_validate_true_for_untampered() -> None:
    assert validate_authorization_certificate(_authorization()) is True


def test_authorization_validate_false_after_tamper() -> None:
    cert = _authorization()
    tampered = cert.model_copy(update={"decision": "denied"})
    assert validate_authorization_certificate(tampered) is False


def test_authorization_timestamp_is_in_identity() -> None:
    cert = _authorization()
    moved = cert.model_copy(update={"authorization_timestamp": ISSUED_LATER})
    # authorization window bounds identity: recomputed id differs from stored.
    assert validate_authorization_certificate(moved) is False


def test_authorization_issued_at_not_in_identity() -> None:
    cert = _authorization()
    rescheduled = cert.model_copy(update={"issued_at": ISSUED_LATER})
    assert rescheduled.certificate_id == cert.certificate_id
    assert validate_authorization_certificate(rescheduled) is True


# --------------------------------------------------------------------------
# OutcomeCertificate
# --------------------------------------------------------------------------


def _outcome() -> OutcomeCertificate:
    return build_outcome_certificate(
        authorized_action_id="ACT-aaaaaaaaaaaa",
        authorization_certificate_id="AUTHCERT-000000000000",
        dispatched_action_digest="4" * 64,
        pre_execution_evidence_digest="5" * 64,
        post_execution_evidence_digest="6" * 64,
        executor_reported_results={"filled_qty": 10, "avg_price": Decimal("12.5")},
        independently_observed_state={"position": 10},
        expected_outcome={"position": 10},
        actual_outcome={"position": 10},
        reconciliation_residuals={"position": Decimal("0")},
        numerical_tolerances={"position": Decimal("0")},
        outcome_classification="reconciled",
        issued_at=ISSUED,
    )


def test_outcome_build_is_deterministic() -> None:
    assert _outcome().certificate_id == _outcome().certificate_id
    assert _outcome().certificate_id.startswith("OUTCOMECERT-")


def test_outcome_validate_true_for_untampered() -> None:
    assert validate_outcome_certificate(_outcome()) is True


def test_outcome_validate_false_after_tamper() -> None:
    cert = _outcome()
    tampered = cert.model_copy(update={"outcome_classification": "diverged"})
    assert validate_outcome_certificate(tampered) is False


def test_outcome_issued_at_not_in_identity() -> None:
    cert = _outcome()
    rescheduled = cert.model_copy(update={"issued_at": ISSUED_LATER})
    assert rescheduled.certificate_id == cert.certificate_id
    assert validate_outcome_certificate(rescheduled) is True


# --------------------------------------------------------------------------
# certificate_hash
# --------------------------------------------------------------------------


def test_certificate_hash_is_deterministic_full_sha256() -> None:
    h = certificate_hash(_computation())
    assert h == certificate_hash(_computation())
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_certificate_hash_differs_across_certificate_types() -> None:
    assert certificate_hash(_computation()) != certificate_hash(_claim())


def test_default_issued_at_does_not_affect_identity() -> None:
    # Two builds without an explicit issued_at still share a certificate_id.
    a = build_computation_certificate(
        algorithm_id="x",
        algorithm_version="1",
        input_digest="0" * 64,
        input_artifact_refs=(),
        input_observation_ids=(),
        output_digest="1" * 64,
        backend_version="b",
        numerical_contract=CONTRACT,
        applicable_tolerances={},
        validation_status="reference",
    )
    b = build_computation_certificate(
        algorithm_id="x",
        algorithm_version="1",
        input_digest="0" * 64,
        input_artifact_refs=(),
        input_observation_ids=(),
        output_digest="1" * 64,
        backend_version="b",
        numerical_contract=CONTRACT,
        applicable_tolerances={},
        validation_status="reference",
    )
    assert a.certificate_id == b.certificate_id
    assert certificate_hash(a) == certificate_hash(b)
