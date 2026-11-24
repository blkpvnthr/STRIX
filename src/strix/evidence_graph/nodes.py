"""Typed node/edge foundation for the R1 evidence graph G=(V,E,tau,pi).

The graph's vertices are raw :class:`SourceObservation` records and
pre-verification :class:`CandidateClaim` nodes; its edges are typed
:class:`Edge` relationships (R1 §9). Verification is governed by a trusted,
versioned :class:`VerificationPolicy` that decides predicate applicability
(R1 §10.6), producing :class:`PredicateResult` outcomes.

These types are deliberately distinct from the validated lineage models in
:mod:`strix.models`: a :class:`SourceObservation` is a *raw*, pre-validation
observation (vs. the validated ``SourceFact``); a :class:`CandidateClaim` is
a *pre-verification* claim (vs. the verified ``Claim``); an
:class:`Assertion` is metric-generic (vs. the ``Metric``-enum-bound
``NumericAssertion``).

Every identity-bearing node has a content-derived id built by a module-level
``make_*`` factory that calls :func:`strix.canonical.make_id` and excludes
the id itself (and any process wall-clock) from the hashed payload. Edge and
assertion referential fields are plain ``str`` ids — never embedded objects.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import AwareDatetime

from strix.canonical import make_id
from strix.errors import StrixError
from strix.models import DecimalValue, StrixModel

__all__ = [
    "AdmissionOutcome",
    "Assertion",
    "CandidateClaim",
    "Edge",
    "EvidenceGraphError",
    "PredicateName",
    "PredicateResult",
    "PredicateStatus",
    "RelationshipKind",
    "SourceObservation",
    "TemporalMode",
    "VerificationOutcome",
    "VerificationPolicy",
    "make_candidate_claim",
    "make_edge",
    "make_source_observation",
    "make_verification_policy",
]


# --------------------------------------------------------------------------
# Exception
# --------------------------------------------------------------------------


class EvidenceGraphError(StrixError):
    """A node, edge, or policy in the evidence graph could not be trusted,
    constructed, or interpreted."""


# --------------------------------------------------------------------------
# Enums (R1 §9, §10)
# --------------------------------------------------------------------------


class RelationshipKind(StrEnum):
    """The typed relationship an :class:`Edge` records between two nodes."""

    DERIVED_FROM = "derived_from"
    EXTRACTED_FROM = "extracted_from"
    CALCULATED_FROM = "calculated_from"
    SUPPORTED_BY = "supported_by"
    CONTRADICTED_BY = "contradicted_by"
    ATTRIBUTED_TO = "attributed_to"
    VERIFIED_BY = "verified_by"
    SUPERSEDES = "supersedes"
    DEPENDS_ON = "depends_on"
    SATISFIES_REQUIREMENT = "satisfies_requirement"
    AUTHORIZED_BY = "authorized_by"
    RESULTED_IN = "resulted_in"
    RECONCILED_WITH = "reconciled_with"


class PredicateName(StrEnum):
    """The verification predicates a policy may deem mandatory (R1 §10.6)."""

    INTEGRITY = "integrity"
    TYPE_TEMPORAL = "type_temporal"
    PROVENANCE = "provenance"
    DERIVATION = "derivation"
    SUPPORT = "support"


class PredicateStatus(StrEnum):
    """The outcome of evaluating one predicate."""

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class AdmissionOutcome(StrEnum):
    """Whether a node was admitted into the verified graph."""

    ADMITTED = "admitted"
    REJECTED = "rejected"
    ABSTAINED = "abstained"


class VerificationOutcome(StrEnum):
    """The terminal verification verdict for a claim (R1 §10.7)."""

    VERIFIED = "verified"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNVERIFIABLE = "unverifiable"
    STALE = "stale"
    INVALID_EVIDENCE = "invalid_evidence"
    INTEGRITY_FAILURE = "integrity_failure"
    UNRESOLVED_CONFLICT = "unresolved_conflict"


class TemporalMode(StrEnum):
    """As-of vs. historical interpretation of evidence (R1 §10.2)."""

    POINT_IN_TIME = "point_in_time"
    RETROSPECTIVE = "retrospective"


# --------------------------------------------------------------------------
# Models (frozen; content-derived ids via module-level factories)
# --------------------------------------------------------------------------


class SourceObservation(StrixModel):
    """A raw, pre-validation observation extracted from a source artifact.

    Distinct from the validated :class:`strix.models.SourceFact`: no
    validation status, concept/unit are free-form strings, and the
    observation's own temporal metadata (``observed_at``, ``publication_at``,
    ``available_at``) is part of its content identity — these describe *when
    the observed fact was known in the world*, not the wall-clock of this
    process.
    """

    observation_id: str
    subject_id: str
    concept: str
    value: DecimalValue
    unit: str
    observation_period: str
    observed_at: AwareDatetime
    publication_at: AwareDatetime | None = None
    available_at: AwareDatetime | None = None
    source_artifact_id: str
    source_locator: str


class Assertion(StrixModel):
    """A number a candidate claim asserts, bound to supporting evidence.

    Metric-generic replacement for :class:`strix.models.NumericAssertion`:
    ``metric`` is a free-form string, not the ``Metric`` enum. ``evidence_id``
    is a plain ``str`` reference, never an embedded object.
    """

    metric: str
    asserted_value: DecimalValue
    unit: str
    evidence_id: str


class CandidateClaim(StrixModel):
    """A pre-verification claim about a subject.

    Distinct from the verified :class:`strix.models.Claim`: it carries no
    verification status or direction, ``claim_type`` is free-form, and it may
    record the ``knowledge_cutoff`` under which it was proposed.
    """

    candidate_claim_id: str
    subject_id: str
    claim_type: str
    statement: str
    evidence_ids: tuple[str, ...]
    assertions: tuple[Assertion, ...]
    knowledge_cutoff: date | None = None


class Edge(StrixModel):
    """A typed, directed relationship between two graph nodes.

    ``source_id`` and ``target_id`` are plain ``str`` node ids; ``note`` is a
    non-identifying annotation and does not participate in the edge's content
    identity.
    """

    edge_id: str
    kind: RelationshipKind
    source_id: str
    target_id: str
    evidence_ids: tuple[str, ...] = ()
    note: str | None = None


class VerificationPolicy(StrixModel):
    """The trusted, versioned policy deciding predicate applicability (R1 §10.6).

    Tolerances are exact :class:`~decimal.Decimal` values. The policy is the
    authority on which predicates are mandatory and how numeric comparisons
    are judged — provider/agent output can never substitute for it.
    """

    policy_id: str
    version: str
    mandatory_predicates: tuple[PredicateName, ...]
    temporal_mode: TemporalMode
    absolute_tolerance: DecimalValue
    relative_tolerance: DecimalValue
    freshness_max_age_seconds: int | None = None
    require_source_independence: bool = False
    #: Trusted point-in-time as-of date (R1 §10.2). In POINT_IN_TIME mode this is
    #: the authoritative cutoff; a claim's own ``knowledge_cutoff`` may only
    #: *tighten* it (make it earlier), never relax it. ``None`` means the policy
    #: declares no as-of, so only a claim-supplied cutoff (which can only be
    #: stricter than no enforcement) applies.
    as_of_cutoff: date | None = None


class PredicateResult(StrixModel):
    """The outcome of evaluating one verification predicate."""

    predicate: PredicateName
    status: PredicateStatus
    reason_codes: tuple[str, ...] = ()
    detail: str = ""


# --------------------------------------------------------------------------
# Content-derived identity factories
# --------------------------------------------------------------------------


def _content_id(prefix: str, model: StrixModel, *exclude: str) -> str:
    """Content-derived id for *model*, excluding its own id field(s).

    Dumps in python mode (Decimals stay Decimal, datetimes stay aware), drops
    the self-referential id field(s), and hashes the remainder. The model is
    already validated, so the payload contains no ``float``.
    """
    payload = model.model_dump()
    for field in exclude:
        payload.pop(field, None)
    return make_id(prefix, payload)


def make_source_observation(
    *,
    subject_id: str,
    concept: str,
    value: Decimal,
    unit: str,
    observation_period: str,
    observed_at: AwareDatetime,
    source_artifact_id: str,
    source_locator: str,
    publication_at: AwareDatetime | None = None,
    available_at: AwareDatetime | None = None,
) -> SourceObservation:
    """Build a :class:`SourceObservation` with a content-derived ``OBS-`` id.

    The observation's temporal metadata is part of identity (R1 §10.2); the
    id excludes only ``observation_id`` itself. Constructing the model first
    lets pydantic reject a ``float`` ``value`` before it can reach the hasher.
    """
    draft = SourceObservation(
        observation_id="",
        subject_id=subject_id,
        concept=concept,
        value=value,
        unit=unit,
        observation_period=observation_period,
        observed_at=observed_at,
        publication_at=publication_at,
        available_at=available_at,
        source_artifact_id=source_artifact_id,
        source_locator=source_locator,
    )
    return draft.model_copy(update={"observation_id": _content_id("OBS", draft, "observation_id")})


def make_candidate_claim(
    *,
    subject_id: str,
    claim_type: str,
    statement: str,
    evidence_ids: tuple[str, ...],
    assertions: tuple[Assertion, ...],
    knowledge_cutoff: date | None = None,
) -> CandidateClaim:
    """Build a :class:`CandidateClaim` with a content-derived ``CC-`` id."""
    draft = CandidateClaim(
        candidate_claim_id="",
        subject_id=subject_id,
        claim_type=claim_type,
        statement=statement,
        evidence_ids=evidence_ids,
        assertions=assertions,
        knowledge_cutoff=knowledge_cutoff,
    )
    return draft.model_copy(
        update={"candidate_claim_id": _content_id("CC", draft, "candidate_claim_id")}
    )


def make_edge(
    kind: RelationshipKind,
    source_id: str,
    target_id: str,
    evidence_ids: tuple[str, ...] = (),
    note: str | None = None,
) -> Edge:
    """Build an :class:`Edge` with a content-derived ``EDGE-`` id.

    Identity rests on ``kind``, ``source_id``, ``target_id``, and
    ``evidence_ids``; ``note`` is a non-identifying annotation, excluded.
    """
    draft = Edge(
        edge_id="",
        kind=kind,
        source_id=source_id,
        target_id=target_id,
        evidence_ids=evidence_ids,
        note=note,
    )
    return draft.model_copy(update={"edge_id": _content_id("EDGE", draft, "edge_id", "note")})


def make_verification_policy(
    *,
    version: str,
    mandatory_predicates: tuple[PredicateName, ...],
    temporal_mode: TemporalMode,
    absolute_tolerance: Decimal,
    relative_tolerance: Decimal,
    freshness_max_age_seconds: int | None = None,
    require_source_independence: bool = False,
    as_of_cutoff: date | None = None,
) -> VerificationPolicy:
    """Build a :class:`VerificationPolicy` with a content-derived ``VPOL-`` id."""
    draft = VerificationPolicy(
        policy_id="",
        version=version,
        mandatory_predicates=mandatory_predicates,
        temporal_mode=temporal_mode,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
        freshness_max_age_seconds=freshness_max_age_seconds,
        require_source_independence=require_source_independence,
        as_of_cutoff=as_of_cutoff,
    )
    return draft.model_copy(update={"policy_id": _content_id("VPOL", draft, "policy_id")})
