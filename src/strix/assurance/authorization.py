"""Domain-independent independent-execution authorization (R1 §18, §20).

This module generalizes the C-engine deterministic risk-engine pattern — an
*ordered* constraint evaluation producing *typed deterministic* reject reason
codes, with an atomic duplicate-action guard — into a trading-agnostic
authorization kernel.

The authorization predicate is

    Auth(a, G, P) = I_a ∧ V_a ∧ C_a ∧ F_a ∧ B_a ∧ R_a

over an :class:`ActionRequest` ``a``, a set of supporting evidence-graph
:class:`~strix.evidence_graph.certificates.ClaimCertificate` ``G``, and a
trusted versioned :class:`AuthorizationPolicy` ``P``. The six conditions are
evaluated in a fixed order, each yielding a :class:`ConditionResult` with a
typed reason code. **Every** mandatory condition must pass; any failed or
unknown condition denies. Unlike a short-circuiting gauntlet, all six
conditions are always evaluated so the decision carries the complete set of
failing reason codes for audit — but the ordering is deterministic and every
reason code is a pure function of the inputs.

Identity & TOCTOU
-----------------
An :class:`ActionRequest`'s ``action_id`` is content-derived over its exact
parameters. A granted :class:`AuthorizationCertificate` therefore binds the
*exact* parameters: changing any parameter changes the ``action_id`` and the
request digest, so :func:`reauthorize` rejects a stale certificate presented
against a mutated request (bind-to-parameters; addresses time-of-check /
time-of-use).

Fail-closed
-----------
External state-changing execution is disabled by default
(``AuthorizationPolicy.enabled = False``, R1 §18.3); a policy must explicitly
enable it, else every request is denied ``external_execution_disabled``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, Field

from strix.canonical import canonical_hash, make_id
from strix.errors import StrixError
from strix.evidence_graph.certificates import (
    AuthorizationCertificate,
    ClaimCertificate,
    build_authorization_certificate,
    validate_authorization_certificate,
    validate_claim_certificate,
)
from strix.models import StrixModel

__all__ = [
    "ActionRequest",
    "AuthorizationDecision",
    "AuthorizationError",
    "AuthorizationPolicy",
    "AuthorizationReasonCode",
    "ConditionName",
    "ConditionResult",
    "ConditionStatus",
    "Decision",
    "authorize",
    "build_grant_certificate",
    "make_action_request",
    "make_authorization_policy",
    "reauthorize",
]

#: id prefix for content-derived action ids.
_ACTION_PREFIX = "ACTION"
#: id prefix for content-derived policy ids.
_POLICY_PREFIX = "AUTHPOL"


class AuthorizationError(StrixError):
    """An authorization operation could not be performed or trusted.

    Raised for programmer/contract violations (e.g. dispatching without a valid
    certificate). A *denied* authorization is a normal, typed
    :class:`AuthorizationDecision` outcome, never this exception.
    """


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class Decision(StrEnum):
    """Terminal authorization decision."""

    GRANTED = "granted"
    DENIED = "denied"


class ConditionName(StrEnum):
    """The six ordered authorization conditions (R1 §18)."""

    IDENTITY = "I_a"
    SUPPORT = "V_a"
    CONSTRAINTS = "C_a"
    FRESHNESS = "F_a"
    RESOURCE = "B_a"
    EXECUTOR = "R_a"


class ConditionStatus(StrEnum):
    """The outcome of evaluating one authorization condition."""

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class AuthorizationReasonCode(StrEnum):
    """Typed deterministic reject reason codes (domain-neutral registry).

    Replaces the trading-specific ``RiskRejectReason`` of the C-engine with a
    generic authorization vocabulary. Every denial names one or more of these.
    """

    # I_a — identity / integrity
    ACTION_ID_MISMATCH = "action_id_mismatch"
    MISSING_PARAMETERS = "missing_parameters"
    # V_a — supporting evidence
    INSUFFICIENT_SUPPORTING_CERTIFICATES = "insufficient_supporting_certificates"
    INVALID_CLAIM_CERTIFICATE = "invalid_claim_certificate"
    MISSING_DEPENDENCY_CERTIFICATE = "missing_dependency_certificate"
    # C_a — deterministic policy constraints
    ACTION_TYPE_NOT_ALLOWED = "action_type_not_allowed"
    # F_a — freshness / temporal
    SUPPORTING_CERTIFICATE_STALE = "supporting_certificate_stale"
    TIMESTAMP_SKEW_DETECTED = "timestamp_skew_detected"
    AUTHORIZATION_EXPIRED = "authorization_expired"
    # B_a — resource / risk limits
    RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"
    NEGATIVE_RESOURCE_AMOUNT = "negative_resource_amount"
    PARAMETER_NOT_NUMERIC = "parameter_not_numeric"
    # R_a — executor / scope / duplicate / enablement
    EXECUTOR_NOT_ALLOWED = "executor_not_allowed"
    TARGET_OUT_OF_SCOPE = "target_out_of_scope"
    DUPLICATE_IDEMPOTENCY_KEY = "duplicate_idempotency_key"
    EXTERNAL_EXECUTION_DISABLED = "external_execution_disabled"
    # reauthorize-only (re-check of an existing certificate)
    CERTIFICATE_TAMPERED = "certificate_tampered"
    ACTION_PARAMETERS_CHANGED = "action_parameters_changed"
    POLICY_VERSION_MISMATCH = "policy_version_mismatch"
    CERTIFICATE_NOT_GRANTED = "certificate_not_granted"


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------


class ActionRequest(StrixModel):
    """A request to perform one external state-changing action.

    ``action_id`` is content-derived (via :func:`make_action_request`) over the
    exact remaining fields and is excluded from its own hashed payload. Because
    identity binds the exact ``parameters``, any mutation produces a different
    ``action_id`` — a granted certificate cannot be replayed against changed
    parameters.
    """

    action_id: str
    action_type: str
    target: str
    parameters: dict[str, str]
    dependency_claim_certificate_ids: tuple[str, ...] = ()
    idempotency_key: str
    requested_executor: str


class AuthorizationPolicy(StrixModel):
    """The trusted, versioned authorization policy (R1 §18).

    ``enabled`` defaults to ``False``: external state-changing execution is
    disabled unless a policy explicitly turns it on (R1 §18.3).
    """

    policy_id: str
    version: str
    enabled: bool = False
    allowed_action_types: tuple[str, ...] = ()
    allowed_executors: tuple[str, ...] = ()
    min_supporting_claim_certificates: int = 1
    permission_scope: tuple[str, ...] = ()
    resource_limits: dict[str, str] = Field(default_factory=dict)
    freshness_max_age_seconds: int | None = None
    authorization_ttl_seconds: int = 300


class ConditionResult(StrixModel):
    """The outcome of evaluating one of the six authorization conditions."""

    condition: ConditionName
    status: ConditionStatus
    reason_codes: tuple[AuthorizationReasonCode, ...] = ()
    detail: str = ""


class AuthorizationDecision(StrixModel):
    """The terminal, fully-diagnosed authorization decision.

    ``condition_results`` carries exactly one :class:`ConditionResult` per
    condition in evaluation order; ``reason_codes`` aggregates every failing
    condition's codes. On a grant ``certificate_id`` references the built
    :class:`AuthorizationCertificate`; on a denial it is ``None``.
    """

    decision: Decision
    reason_codes: tuple[AuthorizationReasonCode, ...]
    action_id: str
    policy_version: str
    certificate_id: str | None = None
    condition_results: tuple[ConditionResult, ...]


# --------------------------------------------------------------------------
# Factories
# --------------------------------------------------------------------------


def _action_identity_payload(request: ActionRequest) -> dict[str, Any]:
    """Return *request*'s content payload with the self-referential id removed."""
    payload = request.model_dump()
    payload.pop("action_id", None)
    return payload


def make_action_request(
    *,
    action_type: str,
    target: str,
    parameters: dict[str, str],
    idempotency_key: str,
    requested_executor: str,
    dependency_claim_certificate_ids: tuple[str, ...] = (),
) -> ActionRequest:
    """Build an :class:`ActionRequest` with a content-derived ``ACTION-`` id."""
    draft = ActionRequest(
        action_id="",
        action_type=action_type,
        target=target,
        parameters=parameters,
        dependency_claim_certificate_ids=dependency_claim_certificate_ids,
        idempotency_key=idempotency_key,
        requested_executor=requested_executor,
    )
    return draft.model_copy(
        update={"action_id": make_id(_ACTION_PREFIX, _action_identity_payload(draft))}
    )


def make_authorization_policy(
    *,
    version: str,
    enabled: bool = False,
    allowed_action_types: tuple[str, ...] = (),
    allowed_executors: tuple[str, ...] = (),
    min_supporting_claim_certificates: int = 1,
    permission_scope: tuple[str, ...] = (),
    resource_limits: dict[str, str] | None = None,
    freshness_max_age_seconds: int | None = None,
    authorization_ttl_seconds: int = 300,
) -> AuthorizationPolicy:
    """Build an :class:`AuthorizationPolicy` with a content-derived ``AUTHPOL-`` id."""
    draft = AuthorizationPolicy(
        policy_id="",
        version=version,
        enabled=enabled,
        allowed_action_types=allowed_action_types,
        allowed_executors=allowed_executors,
        min_supporting_claim_certificates=min_supporting_claim_certificates,
        permission_scope=permission_scope,
        resource_limits=resource_limits if resource_limits is not None else {},
        freshness_max_age_seconds=freshness_max_age_seconds,
        authorization_ttl_seconds=authorization_ttl_seconds,
    )
    payload = draft.model_dump()
    payload.pop("policy_id", None)
    return draft.model_copy(update={"policy_id": make_id(_POLICY_PREFIX, payload)})


# --------------------------------------------------------------------------
# Condition evaluators (each pure; returns (status, reason_codes, detail))
# --------------------------------------------------------------------------

_Eval = tuple[ConditionStatus, tuple[AuthorizationReasonCode, ...], str]


def _ok() -> _Eval:
    return (ConditionStatus.PASS, (), "")


def _fail(*codes: AuthorizationReasonCode, detail: str = "") -> _Eval:
    return (ConditionStatus.FAIL, tuple(codes), detail)


def _as_decimal(value: str) -> Decimal | None:
    """Parse *value* as an exact Decimal, or ``None`` if it is not numeric."""
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _eval_identity(request: ActionRequest) -> _Eval:
    """I_a — action identity / integrity: recomputed id matches; parameters present."""
    codes: list[AuthorizationReasonCode] = []
    recomputed = make_id(_ACTION_PREFIX, _action_identity_payload(request))
    if recomputed != request.action_id:
        codes.append(AuthorizationReasonCode.ACTION_ID_MISMATCH)
    if not request.parameters:
        codes.append(AuthorizationReasonCode.MISSING_PARAMETERS)
    return _fail(*codes) if codes else _ok()


def _eval_support(
    request: ActionRequest,
    claim_certificates: tuple[ClaimCertificate, ...],
    policy: AuthorizationPolicy,
) -> _Eval:
    """V_a — supporting ClaimCertificates present, valid, and covering dependencies."""
    codes: list[AuthorizationReasonCode] = []
    if len(claim_certificates) < policy.min_supporting_claim_certificates:
        codes.append(AuthorizationReasonCode.INSUFFICIENT_SUPPORTING_CERTIFICATES)
    if any(not validate_claim_certificate(cert) for cert in claim_certificates):
        codes.append(AuthorizationReasonCode.INVALID_CLAIM_CERTIFICATE)
    supplied = {cert.certificate_id for cert in claim_certificates}
    if any(dep not in supplied for dep in request.dependency_claim_certificate_ids):
        codes.append(AuthorizationReasonCode.MISSING_DEPENDENCY_CERTIFICATE)
    return _fail(*codes) if codes else _ok()


def _eval_constraints(request: ActionRequest, policy: AuthorizationPolicy) -> _Eval:
    """C_a — deterministic policy constraints: action_type is allowed."""
    if request.action_type not in policy.allowed_action_types:
        return _fail(AuthorizationReasonCode.ACTION_TYPE_NOT_ALLOWED)
    return _ok()


def _freshness_anchor(cert: ClaimCertificate) -> datetime:
    """The timestamp freshness is measured from.

    Prefers the identity-protected ``applicable_temporal_cutoff`` (it is part of
    the certificate's content id, so a tampered timestamp changes the id and is
    caught by ``validate_claim_certificate``) over the excluded, non-identity
    ``issued_at``. Without an as-of cutoff, freshness falls back to the
    best-effort ``issued_at`` — a weaker guarantee that only signed certificates
    would fully close (R1 §13.5).
    """
    cutoff = cert.applicable_temporal_cutoff
    if cutoff is not None:
        return datetime(cutoff.year, cutoff.month, cutoff.day, tzinfo=UTC)
    return cert.issued_at


def _eval_freshness(
    claim_certificates: tuple[ClaimCertificate, ...],
    policy: AuthorizationPolicy,
    now: datetime,
) -> _Eval:
    """F_a — freshness / temporal: supporting evidence is fresh and not skewed."""
    codes: list[AuthorizationReasonCode] = []
    for cert in claim_certificates:
        age = (now - _freshness_anchor(cert)).total_seconds()
        if age < 0:
            codes.append(AuthorizationReasonCode.TIMESTAMP_SKEW_DETECTED)
        elif (
            policy.freshness_max_age_seconds is not None
            and age > policy.freshness_max_age_seconds
        ):
            codes.append(AuthorizationReasonCode.SUPPORTING_CERTIFICATE_STALE)
    return _fail(*codes) if codes else _ok()


def _eval_resource(request: ActionRequest, policy: AuthorizationPolicy) -> _Eval:
    """B_a — resource / risk limits: numeric parameters within their declared caps."""
    codes: list[AuthorizationReasonCode] = []
    status = ConditionStatus.PASS
    for key, limit_text in policy.resource_limits.items():
        if key not in request.parameters:
            continue
        limit = _as_decimal(limit_text)
        amount = _as_decimal(request.parameters[key])
        if limit is None or amount is None:
            codes.append(AuthorizationReasonCode.PARAMETER_NOT_NUMERIC)
            status = ConditionStatus.UNKNOWN
            continue
        if amount < 0:
            codes.append(AuthorizationReasonCode.NEGATIVE_RESOURCE_AMOUNT)
        elif amount > limit:
            codes.append(AuthorizationReasonCode.RESOURCE_LIMIT_EXCEEDED)
    if not codes:
        return _ok()
    if status is ConditionStatus.UNKNOWN:
        return (ConditionStatus.UNKNOWN, tuple(codes), "")
    return _fail(*codes)


def _eval_executor(
    request: ActionRequest,
    policy: AuthorizationPolicy,
    used_idempotency_keys: frozenset[str],
) -> _Eval:
    """R_a — executor allowed, scope satisfied, no duplicate, execution enabled."""
    codes: list[AuthorizationReasonCode] = []
    if request.requested_executor not in policy.allowed_executors:
        codes.append(AuthorizationReasonCode.EXECUTOR_NOT_ALLOWED)
    if policy.permission_scope and request.target not in policy.permission_scope:
        codes.append(AuthorizationReasonCode.TARGET_OUT_OF_SCOPE)
    if request.idempotency_key in used_idempotency_keys:
        codes.append(AuthorizationReasonCode.DUPLICATE_IDEMPOTENCY_KEY)
    if not policy.enabled:
        codes.append(AuthorizationReasonCode.EXTERNAL_EXECUTION_DISABLED)
    return _fail(*codes) if codes else _ok()


# --------------------------------------------------------------------------
# Authorize
# --------------------------------------------------------------------------


def _snapshot_digest(claim_certificates: tuple[ClaimCertificate, ...]) -> str:
    """Deterministic digest of the supporting evidence-graph snapshot."""
    return canonical_hash(
        {
            "supporting_claim_certificate_ids": [
                cert.certificate_id for cert in claim_certificates
            ],
            "evidence_graph_snapshot_digests": [
                cert.evidence_graph_snapshot_digest for cert in claim_certificates
            ],
        }
    )


def build_grant_certificate(
    request: ActionRequest,
    claim_certificates: tuple[ClaimCertificate, ...],
    policy: AuthorizationPolicy,
    *,
    now: AwareDatetime,
) -> AuthorizationCertificate:
    """Build the :class:`AuthorizationCertificate` a grant issues for *request*.

    Binds the exact parameters, the supporting claim-certificate ids, and a TTL
    expiration ``now + authorization_ttl_seconds``. Separated from
    :func:`authorize` so the certificate can be reconstructed deterministically
    (its id is content-derived) for later :func:`reauthorize` re-checks. This
    does **not** itself authorize — call :func:`authorize` for that.
    """
    parameters: dict[str, Any] = dict(request.parameters)
    resource_limits: dict[str, Any] = dict(policy.resource_limits)
    return build_authorization_certificate(
        action_request_digest=canonical_hash(_action_identity_payload(request)),
        action_parameters=parameters,
        evidence_graph_snapshot_digest=_snapshot_digest(claim_certificates),
        supporting_claim_certificate_ids=tuple(
            cert.certificate_id for cert in claim_certificates
        ),
        authorization_policy_version=policy.version,
        authorized_executor=request.requested_executor,
        resource_limits=resource_limits,
        permission_scope=policy.permission_scope,
        authorization_timestamp=now,
        expiration_timestamp=now + timedelta(seconds=policy.authorization_ttl_seconds),
        idempotency_key=request.idempotency_key,
        decision=Decision.GRANTED.value,
    )


def authorize(
    request: ActionRequest,
    claim_certificates: tuple[ClaimCertificate, ...],
    policy: AuthorizationPolicy,
    *,
    now: AwareDatetime,
    used_idempotency_keys: frozenset[str] = frozenset(),
) -> AuthorizationDecision:
    """Decide ``Auth(a, G, P)`` over an ordered, fully-diagnosed condition gauntlet.

    Evaluates I_a, V_a, C_a, F_a, B_a, R_a in order. Every mandatory condition
    must pass; any failed or unknown condition denies and contributes its typed
    reason codes. On a grant an :class:`AuthorizationCertificate` is built
    binding the exact parameters, supporting claim-certificate ids, and a TTL
    expiration ``now + authorization_ttl_seconds``.
    """
    ordered: list[tuple[ConditionName, _Eval]] = [
        (ConditionName.IDENTITY, _eval_identity(request)),
        (ConditionName.SUPPORT, _eval_support(request, claim_certificates, policy)),
        (ConditionName.CONSTRAINTS, _eval_constraints(request, policy)),
        (ConditionName.FRESHNESS, _eval_freshness(claim_certificates, policy, now)),
        (ConditionName.RESOURCE, _eval_resource(request, policy)),
        (
            ConditionName.EXECUTOR,
            _eval_executor(request, policy, used_idempotency_keys),
        ),
    ]

    condition_results: list[ConditionResult] = []
    all_codes: list[AuthorizationReasonCode] = []
    granted = True
    for name, (status, codes, detail) in ordered:
        condition_results.append(
            ConditionResult(
                condition=name, status=status, reason_codes=codes, detail=detail
            )
        )
        if status is not ConditionStatus.PASS:
            granted = False
            all_codes.extend(codes)

    if not granted:
        return AuthorizationDecision(
            decision=Decision.DENIED,
            reason_codes=tuple(all_codes),
            action_id=request.action_id,
            policy_version=policy.version,
            certificate_id=None,
            condition_results=tuple(condition_results),
        )

    certificate = build_grant_certificate(request, claim_certificates, policy, now=now)
    return AuthorizationDecision(
        decision=Decision.GRANTED,
        reason_codes=(),
        action_id=request.action_id,
        policy_version=policy.version,
        certificate_id=certificate.certificate_id,
        condition_results=tuple(condition_results),
    )


def reauthorize(
    certificate: AuthorizationCertificate,
    request: ActionRequest,
    policy: AuthorizationPolicy,
    *,
    now: AwareDatetime,
) -> AuthorizationDecision:
    """Re-check an existing certificate against the live request, policy, and clock.

    Authorization binds the *exact* parameters: a prior grant no longer applies
    once the request's parameters (hence its ``action_id`` and request digest)
    change. This helper re-validates the certificate's integrity, its binding to
    the current request, its grant decision, policy version, and TTL window —
    addressing time-of-check / time-of-use drift between ``authorize`` and
    dispatch. Returns a typed :class:`AuthorizationDecision` (never raises for a
    normal denial).
    """
    codes: list[AuthorizationReasonCode] = []
    if not validate_authorization_certificate(certificate):
        codes.append(AuthorizationReasonCode.CERTIFICATE_TAMPERED)
    if certificate.decision != Decision.GRANTED.value:
        codes.append(AuthorizationReasonCode.CERTIFICATE_NOT_GRANTED)
    live_digest = canonical_hash(_action_identity_payload(request))
    if certificate.action_request_digest != live_digest:
        codes.append(AuthorizationReasonCode.ACTION_PARAMETERS_CHANGED)
    if certificate.authorization_policy_version != policy.version:
        codes.append(AuthorizationReasonCode.POLICY_VERSION_MISMATCH)
    if now > certificate.expiration_timestamp:
        codes.append(AuthorizationReasonCode.AUTHORIZATION_EXPIRED)
    if now < certificate.authorization_timestamp:
        codes.append(AuthorizationReasonCode.TIMESTAMP_SKEW_DETECTED)
    if not policy.enabled:
        codes.append(AuthorizationReasonCode.EXTERNAL_EXECUTION_DISABLED)

    decision = Decision.GRANTED if not codes else Decision.DENIED
    return AuthorizationDecision(
        decision=decision,
        reason_codes=tuple(codes),
        action_id=request.action_id,
        policy_version=policy.version,
        certificate_id=certificate.certificate_id if not codes else None,
        condition_results=(),
    )
