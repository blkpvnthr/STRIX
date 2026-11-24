"""The four R1 §13 certificate classes.

A STRIX certificate is a frozen, content-addressed record that attests that a
specific policy was satisfied against preserved inputs — nothing more. The four
kinds mirror the four stages of the autonomy pipeline (R1 §13):

- :class:`ComputationCertificate` (§13.1) — a numerical operation met its
  numerical contract against an independent reference.
- :class:`ClaimCertificate` (§13.2) — a candidate claim passed the mandatory
  verification predicates under a named policy, over a preserved evidence-graph
  snapshot.
- :class:`AuthorizationCertificate` (§13.3) — an action was authorized (or
  denied) under a named authorization policy, bounded by a time window.
- :class:`OutcomeCertificate` (§13.4) — a dispatched action's reported results
  were reconciled against independently observed post-execution state.

What a certificate is NOT
-------------------------
A content digest or certificate signature establishes *satisfaction of a policy
against the inputs that were preserved* — it does **not** establish factual
truth. A :class:`ComputationCertificate` says a division reproduced its
reference to tolerance; it says nothing about whether the dividend was the right
number. A :class:`ClaimCertificate` says the claim survived the policy's
predicates over the recorded evidence; it is not an unconditional guarantee the
claim is true of the world. Certificates are falsifiable, auditable receipts,
not oracles (R1 §13).

Identity contract
-----------------
Every certificate has a content-derived ``certificate_id`` computed by
:func:`strix.canonical.make_id` over its *deterministic* content only. The
process wall-clock of issuance, ``issued_at``, is recorded for audit but is
**excluded** from the id, from :func:`certificate_hash`, and from the
``validate_*`` comparison — reissuing the same logical certificate at a
different time yields the same id. ``validate_*`` recomputes the id from content
and returns ``False`` if it no longer matches the stored id, detecting
tampering with any deterministic field.

For :class:`AuthorizationCertificate` the authorization and expiration
timestamps *are* part of identity (they bound the authorization), distinct from
the issuance wall-clock which is not.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, TypeVar

from pydantic import AwareDatetime

from strix.canonical import canonical_hash, make_id
from strix.evidence_graph.nodes import PredicateResult
from strix.models import DecimalValue, StrixModel
from strix.native.contracts import NumericalContract

__all__ = [
    "AuthorizationCertificate",
    "ClaimCertificate",
    "ComputationCertificate",
    "OutcomeCertificate",
    "build_authorization_certificate",
    "build_claim_certificate",
    "build_computation_certificate",
    "build_outcome_certificate",
    "certificate_hash",
    "validate_authorization_certificate",
    "validate_claim_certificate",
    "validate_computation_certificate",
    "validate_outcome_certificate",
]

#: JSON-serializable mapping payload (Decimal/str/int/bool/None values, nested
#: dicts/lists). ``float`` is rejected downstream by the canonical serializer.
JsonDict = dict[str, Any]


# --------------------------------------------------------------------------
# Certificate models (frozen; content-derived certificate_id)
# --------------------------------------------------------------------------


class ComputationCertificate(StrixModel):
    """A numerical operation met its numerical contract (R1 §13.1).

    Attests that ``algorithm_id``@``algorithm_version`` run on
    ``backend_version`` produced ``output_digest`` from ``input_digest`` and
    agreed with ``reference_results`` within ``applicable_tolerances`` under
    ``numerical_contract``. Establishes contract satisfaction over the preserved
    inputs — **not** that the inputs or the result are factually correct.
    """

    certificate_id: str
    algorithm_id: str
    algorithm_version: str
    input_digest: str
    input_artifact_refs: tuple[str, ...]
    input_observation_ids: tuple[str, ...]
    output_digest: str
    backend_version: str
    numerical_contract: NumericalContract | JsonDict
    reference_results: tuple[Any, ...] | None = None
    error_measurements: JsonDict | None = None
    applicable_tolerances: JsonDict
    random_seed: int | None = None
    validation_status: str
    #: Process wall-clock of issuance; excluded from identity (R1 §13).
    issued_at: AwareDatetime


class ClaimCertificate(StrixModel):
    """A claim passed the mandatory verification predicates (R1 §13.2).

    Attests that ``claim_id`` (digest ``canonical_claim_digest``) survived
    ``predicate_results`` under ``verification_policy_version`` /
    ``verifier_version`` over the evidence-graph snapshot
    ``evidence_graph_snapshot_digest`` and its ``dependency_closure``.
    Establishes policy satisfaction over preserved evidence — **not** that the
    claim is unconditionally true.
    """

    certificate_id: str
    claim_id: str
    canonical_claim_digest: str
    evidence_graph_snapshot_digest: str
    supporting_evidence_ids: tuple[str, ...]
    dependency_closure: tuple[str, ...]
    predicate_results: tuple[PredicateResult, ...]
    verification_policy_version: str
    verifier_version: str
    computation_certificate_refs: tuple[str, ...]
    applicable_temporal_cutoff: date | None = None
    verified_value: DecimalValue | None = None
    measurement_unit: str | None = None
    numerical_tolerance: DecimalValue | None = None
    #: Process wall-clock of issuance; excluded from identity (R1 §13).
    issued_at: AwareDatetime


class AuthorizationCertificate(StrixModel):
    """An action was authorized or denied under a policy (R1 §13.3).

    Attests the ``decision`` for ``action_request_digest`` under
    ``authorization_policy_version``, bounded by the
    ``authorization_timestamp`` / ``expiration_timestamp`` window and scoped to
    ``permission_scope`` / ``resource_limits``. The authorization/expiration
    timestamps bound the grant and so are part of identity; the issuance
    wall-clock (``issued_at``) is not. Establishes that policy granted the
    action over the preserved supporting claims — **not** that executing it is
    guaranteed safe or profitable.
    """

    certificate_id: str
    action_request_digest: str
    action_parameters: JsonDict
    evidence_graph_snapshot_digest: str
    supporting_claim_certificate_ids: tuple[str, ...]
    authorization_policy_version: str
    authorized_executor: str
    resource_limits: JsonDict
    permission_scope: tuple[str, ...]
    authorization_timestamp: AwareDatetime
    expiration_timestamp: AwareDatetime
    idempotency_key: str
    decision: str
    rejection_reason_codes: tuple[str, ...] = ()
    #: Process wall-clock of issuance; excluded from identity (R1 §13).
    issued_at: AwareDatetime


class OutcomeCertificate(StrixModel):
    """A dispatched action's results were reconciled (R1 §13.4).

    Attests that ``executor_reported_results`` for ``authorized_action_id``
    (authorized by ``authorization_certificate_id``) were compared against
    ``independently_observed_state``, yielding ``reconciliation_residuals``
    within ``numerical_tolerances`` and the terminal ``outcome_classification``.
    Establishes the reconciliation outcome over the preserved pre/post evidence
    — **not** that the reported results are themselves truthful.
    """

    certificate_id: str
    authorized_action_id: str
    authorization_certificate_id: str
    dispatched_action_digest: str
    pre_execution_evidence_digest: str
    post_execution_evidence_digest: str
    executor_reported_results: JsonDict
    independently_observed_state: JsonDict
    expected_outcome: JsonDict
    actual_outcome: JsonDict
    reconciliation_residuals: JsonDict
    numerical_tolerances: JsonDict
    outcome_classification: str
    #: Process wall-clock of issuance; excluded from identity (R1 §13).
    issued_at: AwareDatetime


# --------------------------------------------------------------------------
# Content-identity helpers
# --------------------------------------------------------------------------

# ``_CertT`` binds to the concrete certificate types so ``_finalize`` preserves
# the exact type of the certificate it stamps.
_CertT = TypeVar(
    "_CertT",
    ComputationCertificate,
    ClaimCertificate,
    AuthorizationCertificate,
    OutcomeCertificate,
)

#: Fields excluded from every certificate's deterministic identity payload:
#: the self-referential id and the nondeterministic issuance wall-clock.
_EXCLUDED_FROM_IDENTITY = ("certificate_id", "issued_at")

#: id prefix per certificate type.
_PREFIXES: dict[type[StrixModel], str] = {
    ComputationCertificate: "COMPCERT",
    ClaimCertificate: "CLAIMCERT",
    AuthorizationCertificate: "AUTHCERT",
    OutcomeCertificate: "OUTCOMECERT",
}


def _deterministic_payload(cert: StrixModel) -> JsonDict:
    """Return *cert*'s content payload with nondeterministic fields removed.

    Dumps in python mode (Decimals stay ``Decimal``, datetimes stay aware,
    nested models become dicts) and drops ``certificate_id`` and ``issued_at``
    so neither the self-id nor the issuance wall-clock enters the hash.
    """
    payload = cert.model_dump()
    for field in _EXCLUDED_FROM_IDENTITY:
        payload.pop(field, None)
    return payload


def _recompute_id(cert: StrixModel) -> str:
    """Recompute the content-derived id for *cert* from its deterministic content."""
    prefix = _PREFIXES[type(cert)]
    return make_id(prefix, _deterministic_payload(cert))


def _finalize(cert: _CertT) -> _CertT:
    """Stamp *cert* (built with an empty id) with its content-derived id."""
    return cert.model_copy(update={"certificate_id": _recompute_id(cert)})


def certificate_hash(cert: StrixModel) -> str:
    """Return the full SHA-256 of *cert*'s deterministic content.

    Independent of ``issued_at`` and of the stored ``certificate_id`` — the same
    logical certificate hashes identically regardless of when it was issued. A
    hash attests content identity, never factual truth (R1 §13).
    """
    return canonical_hash(_deterministic_payload(cert))


def _resolve_issued_at(issued_at: AwareDatetime | None) -> datetime:
    """Return *issued_at* or the current UTC wall-clock if unspecified."""
    return issued_at if issued_at is not None else datetime.now(UTC)


# --------------------------------------------------------------------------
# Factories
# --------------------------------------------------------------------------


def build_computation_certificate(
    *,
    algorithm_id: str,
    algorithm_version: str,
    input_digest: str,
    input_artifact_refs: tuple[str, ...],
    input_observation_ids: tuple[str, ...],
    output_digest: str,
    backend_version: str,
    numerical_contract: NumericalContract | JsonDict,
    applicable_tolerances: JsonDict,
    validation_status: str,
    reference_results: tuple[Any, ...] | None = None,
    error_measurements: JsonDict | None = None,
    random_seed: int | None = None,
    issued_at: AwareDatetime | None = None,
) -> ComputationCertificate:
    """Build a :class:`ComputationCertificate` with a content-derived id.

    ``issued_at`` defaults to the current UTC time and is excluded from the id.
    """
    draft = ComputationCertificate(
        certificate_id="",
        algorithm_id=algorithm_id,
        algorithm_version=algorithm_version,
        input_digest=input_digest,
        input_artifact_refs=input_artifact_refs,
        input_observation_ids=input_observation_ids,
        output_digest=output_digest,
        backend_version=backend_version,
        numerical_contract=numerical_contract,
        reference_results=reference_results,
        error_measurements=error_measurements,
        applicable_tolerances=applicable_tolerances,
        random_seed=random_seed,
        validation_status=validation_status,
        issued_at=_resolve_issued_at(issued_at),
    )
    return _finalize(draft)


def build_claim_certificate(
    *,
    claim_id: str,
    canonical_claim_digest: str,
    evidence_graph_snapshot_digest: str,
    supporting_evidence_ids: tuple[str, ...],
    dependency_closure: tuple[str, ...],
    predicate_results: tuple[PredicateResult, ...],
    verification_policy_version: str,
    verifier_version: str,
    computation_certificate_refs: tuple[str, ...],
    applicable_temporal_cutoff: date | None = None,
    verified_value: DecimalValue | None = None,
    measurement_unit: str | None = None,
    numerical_tolerance: DecimalValue | None = None,
    issued_at: AwareDatetime | None = None,
) -> ClaimCertificate:
    """Build a :class:`ClaimCertificate` with a content-derived id.

    ``issued_at`` defaults to the current UTC time and is excluded from the id.
    """
    draft = ClaimCertificate(
        certificate_id="",
        claim_id=claim_id,
        canonical_claim_digest=canonical_claim_digest,
        evidence_graph_snapshot_digest=evidence_graph_snapshot_digest,
        supporting_evidence_ids=supporting_evidence_ids,
        dependency_closure=dependency_closure,
        predicate_results=predicate_results,
        verification_policy_version=verification_policy_version,
        verifier_version=verifier_version,
        computation_certificate_refs=computation_certificate_refs,
        applicable_temporal_cutoff=applicable_temporal_cutoff,
        verified_value=verified_value,
        measurement_unit=measurement_unit,
        numerical_tolerance=numerical_tolerance,
        issued_at=_resolve_issued_at(issued_at),
    )
    return _finalize(draft)


def build_authorization_certificate(
    *,
    action_request_digest: str,
    action_parameters: JsonDict,
    evidence_graph_snapshot_digest: str,
    supporting_claim_certificate_ids: tuple[str, ...],
    authorization_policy_version: str,
    authorized_executor: str,
    resource_limits: JsonDict,
    permission_scope: tuple[str, ...],
    authorization_timestamp: AwareDatetime,
    expiration_timestamp: AwareDatetime,
    idempotency_key: str,
    decision: str,
    rejection_reason_codes: tuple[str, ...] = (),
    issued_at: AwareDatetime | None = None,
) -> AuthorizationCertificate:
    """Build an :class:`AuthorizationCertificate` with a content-derived id.

    The authorization/expiration window *is* part of identity; only the
    issuance wall-clock ``issued_at`` (defaulting to now) is excluded.
    """
    draft = AuthorizationCertificate(
        certificate_id="",
        action_request_digest=action_request_digest,
        action_parameters=action_parameters,
        evidence_graph_snapshot_digest=evidence_graph_snapshot_digest,
        supporting_claim_certificate_ids=supporting_claim_certificate_ids,
        authorization_policy_version=authorization_policy_version,
        authorized_executor=authorized_executor,
        resource_limits=resource_limits,
        permission_scope=permission_scope,
        authorization_timestamp=authorization_timestamp,
        expiration_timestamp=expiration_timestamp,
        idempotency_key=idempotency_key,
        decision=decision,
        rejection_reason_codes=rejection_reason_codes,
        issued_at=_resolve_issued_at(issued_at),
    )
    return _finalize(draft)


def build_outcome_certificate(
    *,
    authorized_action_id: str,
    authorization_certificate_id: str,
    dispatched_action_digest: str,
    pre_execution_evidence_digest: str,
    post_execution_evidence_digest: str,
    executor_reported_results: JsonDict,
    independently_observed_state: JsonDict,
    expected_outcome: JsonDict,
    actual_outcome: JsonDict,
    reconciliation_residuals: JsonDict,
    numerical_tolerances: JsonDict,
    outcome_classification: str,
    issued_at: AwareDatetime | None = None,
) -> OutcomeCertificate:
    """Build an :class:`OutcomeCertificate` with a content-derived id.

    ``issued_at`` defaults to the current UTC time and is excluded from the id.
    """
    draft = OutcomeCertificate(
        certificate_id="",
        authorized_action_id=authorized_action_id,
        authorization_certificate_id=authorization_certificate_id,
        dispatched_action_digest=dispatched_action_digest,
        pre_execution_evidence_digest=pre_execution_evidence_digest,
        post_execution_evidence_digest=post_execution_evidence_digest,
        executor_reported_results=executor_reported_results,
        independently_observed_state=independently_observed_state,
        expected_outcome=expected_outcome,
        actual_outcome=actual_outcome,
        reconciliation_residuals=reconciliation_residuals,
        numerical_tolerances=numerical_tolerances,
        outcome_classification=outcome_classification,
        issued_at=_resolve_issued_at(issued_at),
    )
    return _finalize(draft)


# --------------------------------------------------------------------------
# Validators (recompute id from content; detect tampering)
# --------------------------------------------------------------------------


def _validate(cert: StrixModel) -> bool:
    """True iff *cert*'s stored id matches the id recomputed from its content.

    A content/signature match attests integrity against the preserved inputs; it
    is not a claim of factual truth (R1 §13).
    """
    stored = cert.certificate_id  # type: ignore[attr-defined]
    return bool(stored) and stored == _recompute_id(cert)


def validate_computation_certificate(cert: ComputationCertificate) -> bool:
    """True iff *cert* is untampered (recomputed id matches stored id)."""
    return _validate(cert)


def validate_claim_certificate(cert: ClaimCertificate) -> bool:
    """True iff *cert* is untampered (recomputed id matches stored id)."""
    return _validate(cert)


def validate_authorization_certificate(cert: AuthorizationCertificate) -> bool:
    """True iff *cert* is untampered (recomputed id matches stored id)."""
    return _validate(cert)


def validate_outcome_certificate(cert: OutcomeCertificate) -> bool:
    """True iff *cert* is untampered (recomputed id matches stored id)."""
    return _validate(cert)
