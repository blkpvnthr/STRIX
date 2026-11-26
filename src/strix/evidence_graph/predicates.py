"""The five independent admission predicates and their composition (R1 §10).

Admission of a candidate claim ``c`` into the verified graph ``G`` is the
conjunction of five *independent* predicates (R1 §10):

    A(c, G) = I(c, G) AND T(c, G) AND P(c, G) AND D(c, G) AND S(c, G)

* ``I`` :func:`integrity` — the supporting evidence chain resolves and is
  internally hash-consistent.
* ``T`` :func:`type_temporal` — type/unit/entity compatibility plus temporal
  validity (point-in-time cutoff and freshness).
* ``P`` :func:`provenance` — every cited evidence item traces to a preserved
  source artifact, optionally via independent sources.
* ``D`` :func:`derivation` — every numeric assertion backed by a computation is
  independently re-derived and matched within tolerance.
* ``S`` :func:`support` — every assertion cites evidence that actually supports
  it (value/unit match, entity relevance).

Each predicate is a pure function ``(graph, claim, policy) -> PredicateResult``
carrying a :class:`~strix.evidence_graph.nodes.PredicateStatus` and
machine-readable ``reason_codes``. :func:`admit` composes them under the trusted,
versioned :class:`~strix.evidence_graph.nodes.VerificationPolicy`.

Trust boundary (R1 §10.6, §11 invariant 7): the research agent / candidate claim
can neither mark a predicate ``NOT_APPLICABLE`` nor assign the verdict — the
``CandidateClaim`` carries no such field, and only these functions plus the
policy decide. Composition is deterministic given an identical normalized graph,
claim, and policy (R1 §11 invariant 10).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal

from strix.canonical import make_id
from strix.evidence_graph.graph import EvidenceGraph, Node
from strix.evidence_graph.nodes import (
    AdmissionOutcome,
    CandidateClaim,
    PredicateName,
    PredicateResult,
    PredicateStatus,
    SourceObservation,
    TemporalMode,
    VerificationOutcome,
    VerificationPolicy,
)
from strix.models import (
    CalculationResult,
    Evidence,
    SourceArtifact,
    SourceFact,
    StrixModel,
)
from strix.native.results import ComputationResult, ResultKind

__all__ = [
    "AdmissionDecision",
    "admit",
    "derivation",
    "integrity",
    "provenance",
    "support",
    "type_temporal",
]

_SECONDS_PER_DAY = 86_400

# Fixed, deterministic order in which predicates are recorded (R1 §11 inv. 10).
_PREDICATE_ORDER: tuple[PredicateName, ...] = (
    PredicateName.INTEGRITY,
    PredicateName.TYPE_TEMPORAL,
    PredicateName.PROVENANCE,
    PredicateName.DERIVATION,
    PredicateName.SUPPORT,
)

# Content-identity recompute spec for factory-built node types: (prefix, field).
_SELF_ID_SPEC: dict[type[StrixModel], tuple[str, str]] = {
    SourceObservation: ("OBS", "observation_id"),
    CandidateClaim: ("CC", "candidate_claim_id"),
}


# --------------------------------------------------------------------------
# Decision model
# --------------------------------------------------------------------------


class AdmissionDecision(StrixModel):
    """The composed verdict for one candidate claim (R1 §10.6/§10.7).

    ``outcome`` is the admission control-flow result; ``verification_outcome`` is
    the mapped terminal verdict. ``predicate_results`` records all five
    predicates in the fixed :data:`_PREDICATE_ORDER` (not only the mandatory
    ones) so the decision is fully auditable and deterministic.
    """

    outcome: AdmissionOutcome
    verification_outcome: VerificationOutcome
    predicate_results: tuple[PredicateResult, ...]
    policy_version: str
    claim_id: str


# --------------------------------------------------------------------------
# Node accessors (type-dispatched, read-only)
# --------------------------------------------------------------------------


def _value_of(node: Node) -> Decimal | None:
    """Return the scalar numeric value a node carries, if any."""
    if isinstance(node, (SourceObservation, SourceFact, Evidence, CalculationResult)):
        return node.value
    if isinstance(node, ComputationResult):
        return node.scalar
    return None


def _unit_of(node: Node) -> str | None:
    """Return a node's unit as a plain string, if any."""
    if isinstance(node, SourceObservation):
        return node.unit
    if isinstance(node, (SourceFact, Evidence, CalculationResult)):
        return node.unit.value
    if isinstance(node, ComputationResult):
        return node.output_unit
    return None


def _subject_of(node: Node) -> str | None:
    """Return a node's subject/entity id, if it names one."""
    if isinstance(node, (SourceObservation, SourceFact, Evidence, CalculationResult)):
        return node.subject_id
    return None


def _metric_of(node: Node) -> str | None:
    """Return the metric/concept name a node attests, if any.

    This is what an assertion's ``metric`` must match: an assertion claiming
    metric X may only cite evidence that attests metric X (R1 §10.5). A
    :class:`ComputationResult` has no financial metric concept and returns
    ``None`` (metric relevance is then not asserted by that node).
    """
    if isinstance(node, SourceObservation):
        return node.concept
    if isinstance(node, SourceFact):
        return node.concept.value
    if isinstance(node, Evidence):
        return node.metric.value
    if isinstance(node, CalculationResult):
        return node.calculation_name.value
    return None


def _available_time_of(node: Node) -> datetime | None:
    """Return the tz-aware datetime at which a node's content became available.

    For a raw observation this is ``available_at`` (falling back to
    ``publication_at``); for facts, evidence, and artifacts it is ``known_at``.
    Derived calculations carry no own timestamp and return ``None``.
    """
    if isinstance(node, SourceObservation):
        return node.available_at or node.publication_at
    if isinstance(node, (SourceFact, Evidence, SourceArtifact)):
        return node.known_at
    return None


def _upstream_refs(node: Node) -> tuple[str, ...]:
    """Return the ids a node declares it was derived/extracted/computed from."""
    if isinstance(node, Evidence):
        return (node.calculation_id, *node.source_fact_ids)
    if isinstance(node, CalculationResult):
        return (*node.input_fact_ids, *node.input_calculation_ids)
    if isinstance(node, SourceFact):
        return (node.source_artifact_id,)
    if isinstance(node, SourceObservation):
        return (node.source_artifact_id,)
    if isinstance(node, ComputationResult):
        return (*node.input_observation_ids, *node.input_artifact_refs)
    return ()


def _computed_value(node: Node, graph: EvidenceGraph) -> Decimal | None:
    """Return the independently-computed scalar backing a node, if reproducible.

    A backend-produced :class:`CalculationResult`/:class:`ComputationResult` is
    the independent computation; model-asserted numbers are never trusted here.
    """
    if isinstance(node, CalculationResult):
        return node.value
    if isinstance(node, ComputationResult):
        return node.scalar if node.result_kind is ResultKind.SCALAR else None
    if isinstance(node, Evidence) and graph.has_node(node.calculation_id):
        upstream = graph.node(node.calculation_id)
        if isinstance(upstream, CalculationResult):
            return upstream.value
        if isinstance(upstream, ComputationResult):
            return upstream.scalar if upstream.result_kind is ResultKind.SCALAR else None
    return None


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _within_tolerance(asserted: Decimal, computed: Decimal, policy: VerificationPolicy) -> bool:
    """Whether ``asserted`` matches ``computed`` under the policy tolerances."""
    diff = abs(asserted - computed)
    if diff <= policy.absolute_tolerance:
        return True
    magnitude = abs(computed)
    return magnitude != 0 and diff <= policy.relative_tolerance * magnitude


def _referenced_ids(claim: CandidateClaim) -> tuple[str, ...]:
    """Return all evidence ids a claim references, de-duplicated, order-stable."""
    ordered: list[str] = list(claim.evidence_ids)
    ordered.extend(a.evidence_id for a in claim.assertions if a.evidence_id)
    seen: set[str] = set()
    out: list[str] = []
    for identifier in ordered:
        if identifier not in seen:
            seen.add(identifier)
            out.append(identifier)
    return tuple(out)


def _content_hash_consistent(node: Node) -> bool:
    """Whether a factory-built node's stored id matches its recomputed content id.

    Only :class:`SourceObservation`/:class:`CandidateClaim` ids are recomputable
    here (their exclusion rules are known); any other node type is treated as
    not-checkable and returns ``True``.
    """
    spec = _SELF_ID_SPEC.get(type(node))
    if spec is None:
        return True
    prefix, field = spec
    payload = node.model_dump()
    payload.pop(field, None)
    return bool(getattr(node, field) == make_id(prefix, payload))


def _reachable_artifacts(graph: EvidenceGraph, start: str) -> frozenset[str]:
    """Return the preserved :class:`SourceArtifact` ids reachable from ``start``.

    Walks declared upstream references; a missing reference simply dead-ends
    that branch (incompleteness is surfaced by the absence of any artifact).
    """
    artifacts: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = [start]
    while stack:
        current = stack.pop()
        if current in visited or not graph.has_node(current):
            continue
        visited.add(current)
        node = graph.node(current)
        if isinstance(node, SourceArtifact):
            artifacts.add(current)
            continue
        stack.extend(_upstream_refs(node))
    return frozenset(artifacts)


def _effective_cutoff(policy_cutoff: date | None, claim_cutoff: date | None) -> date | None:
    """The trusted point-in-time cutoff (R1 §10.2).

    The policy's ``as_of_cutoff`` is authoritative; a claim's own
    ``knowledge_cutoff`` may only *tighten* it. Taking the earliest of the two
    (ignoring ``None``) means an untrusted claim can never *relax* a policy
    cutoff (omitting it or setting a far-future date does not widen the window);
    it can only make admission stricter. ``None`` only when neither declares a
    cutoff — i.e. no as-of is enforced at all.
    """
    candidates = [c for c in (policy_cutoff, claim_cutoff) if c is not None]
    return min(candidates) if candidates else None


def _max_available_upstream(graph: EvidenceGraph, start: str) -> datetime | None:
    """Latest availability time among the nodes *upstream* of ``start``.

    Defends point-in-time validity against future source data hidden behind a
    back-dated evidence node (R1 §10.2): the direct node may be pre-cutoff while
    a :class:`SourceFact`/:class:`SourceArtifact` it derives from is post-cutoff.
    """
    latest: datetime | None = None
    visited: set[str] = {start}
    stack: list[str] = []
    if graph.has_node(start):
        stack.extend(_upstream_refs(graph.node(start)))
    while stack:
        current = stack.pop()
        if current in visited or not graph.has_node(current):
            continue
        visited.add(current)
        node = graph.node(current)
        available = _available_time_of(node)
        if available is not None and (latest is None or available > latest):
            latest = available
        stack.extend(_upstream_refs(node))
    return latest


# --------------------------------------------------------------------------
# Predicates
# --------------------------------------------------------------------------


def integrity(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> PredicateResult:
    """Artifact/content-hash integrity of the claim's supporting chain (R1 §10.1).

    Every referenced evidence id and every declared upstream link must resolve
    to a present node, and factory-built nodes must be hash-consistent. Returns
    ``UNKNOWN`` when the claim references no evidence to assess.
    """
    referenced = _referenced_ids(claim)
    if not referenced:
        return PredicateResult(
            predicate=PredicateName.INTEGRITY,
            status=PredicateStatus.UNKNOWN,
            reason_codes=("integrity_indeterminate",),
            detail="claim references no evidence",
        )
    direct = set(referenced)
    codes: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = list(referenced)
    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)
        if not graph.has_node(current):
            codes.add("evidence_node_missing" if current in direct else "broken_upstream_link")
            continue
        node = graph.node(current)
        if not _content_hash_consistent(node):
            codes.add("content_hash_mismatch")
        stack.extend(_upstream_refs(node))
    if codes:
        return PredicateResult(
            predicate=PredicateName.INTEGRITY,
            status=PredicateStatus.FAIL,
            reason_codes=tuple(sorted(codes)),
        )
    return PredicateResult(predicate=PredicateName.INTEGRITY, status=PredicateStatus.PASS)


def type_temporal(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> PredicateResult:
    """Type/unit/entity compatibility plus temporal validity (R1 §10.2).

    Unit or entity mismatches between an assertion and its cited evidence fail.
    In :attr:`TemporalMode.POINT_IN_TIME`, evidence available after the claim's
    ``knowledge_cutoff`` is inadmissible; a missing timestamp needed to decide
    yields ``UNKNOWN``. In :attr:`TemporalMode.RETROSPECTIVE` the cutoff is not
    enforced. Freshness staleness (relative to the cutoff) fails.
    """
    fail: set[str] = set()
    unknown: set[str] = set()

    for assertion in claim.assertions:
        if not assertion.evidence_id or not graph.has_node(assertion.evidence_id):
            continue
        node = graph.node(assertion.evidence_id)
        unit = _unit_of(node)
        if unit is not None and unit != assertion.unit:
            fail.add("unit_mismatch")
        subject = _subject_of(node)
        if subject is not None and subject != claim.subject_id:
            fail.add("entity_mismatch")

    # The trusted policy as-of governs; a claim may only tighten it (R1 §10.2).
    effective = _effective_cutoff(policy.as_of_cutoff, claim.knowledge_cutoff)
    for node_id in claim.evidence_ids:
        if not graph.has_node(node_id):
            continue
        available = _available_time_of(graph.node(node_id))
        if policy.temporal_mode is TemporalMode.POINT_IN_TIME and effective is not None:
            if available is None:
                unknown.add("missing_timestamp")
            elif available.date() > effective:
                fail.add("evidence_after_cutoff")
            # Future source data hidden upstream of a back-dated evidence node.
            upstream_latest = _max_available_upstream(graph, node_id)
            if upstream_latest is not None and upstream_latest.date() > effective:
                fail.add("evidence_after_cutoff")
        if (
            policy.freshness_max_age_seconds is not None
            and effective is not None
            and available is not None
        ):
            age_days = (effective - available.date()).days
            if age_days * _SECONDS_PER_DAY > policy.freshness_max_age_seconds:
                fail.add("evidence_stale")

    if fail:
        return PredicateResult(
            predicate=PredicateName.TYPE_TEMPORAL,
            status=PredicateStatus.FAIL,
            reason_codes=tuple(sorted(fail)),
        )
    if unknown:
        return PredicateResult(
            predicate=PredicateName.TYPE_TEMPORAL,
            status=PredicateStatus.UNKNOWN,
            reason_codes=tuple(sorted(unknown)),
        )
    return PredicateResult(predicate=PredicateName.TYPE_TEMPORAL, status=PredicateStatus.PASS)


def provenance(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> PredicateResult:
    """Complete lineage to preserved source artifacts (R1 §10.3).

    Each cited evidence id must trace, via declared upstream links, to at least
    one preserved :class:`SourceArtifact`; otherwise ``incomplete_lineage``.
    When ``policy.require_source_independence`` is set, two distinct cited items
    resolving to the same artifact are not independent corroboration.
    """
    codes: set[str] = set()
    per_evidence: dict[str, frozenset[str]] = {}
    for node_id in claim.evidence_ids:
        artifacts = _reachable_artifacts(graph, node_id)
        per_evidence[node_id] = artifacts
        if not artifacts:
            codes.add("incomplete_lineage")
    if not claim.evidence_ids:
        codes.add("incomplete_lineage")

    if policy.require_source_independence:
        counts: dict[str, int] = {}
        for artifacts in per_evidence.values():
            for artifact_id in artifacts:
                counts[artifact_id] = counts.get(artifact_id, 0) + 1
        if any(count > 1 for count in counts.values()):
            codes.add("non_independent_sources")

    if codes:
        return PredicateResult(
            predicate=PredicateName.PROVENANCE,
            status=PredicateStatus.FAIL,
            reason_codes=tuple(sorted(codes)),
        )
    return PredicateResult(predicate=PredicateName.PROVENANCE, status=PredicateStatus.PASS)


def derivation(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> PredicateResult:
    """Independently re-derive numeric assertions backed by a computation (R1 §10.4).

    For each assertion whose evidence resolves to an upstream
    :class:`CalculationResult`/:class:`ComputationResult`, the backend-computed
    value is compared to the asserted value within policy tolerance; a mismatch
    fails. If no assertion has a reproducible computation attached, the predicate
    is ``NOT_APPLICABLE`` (never ``FAIL``).
    """
    applicable = False
    codes: set[str] = set()
    for assertion in claim.assertions:
        if not assertion.evidence_id or not graph.has_node(assertion.evidence_id):
            continue
        computed = _computed_value(graph.node(assertion.evidence_id), graph)
        if computed is None:
            continue
        applicable = True
        if not _within_tolerance(assertion.asserted_value, computed, policy):
            codes.add("assertion_value_mismatch")

    if not applicable:
        return PredicateResult(
            predicate=PredicateName.DERIVATION,
            status=PredicateStatus.NOT_APPLICABLE,
            reason_codes=("no_reproducible_calculation",),
        )
    if codes:
        return PredicateResult(
            predicate=PredicateName.DERIVATION,
            status=PredicateStatus.FAIL,
            reason_codes=tuple(sorted(codes)),
        )
    return PredicateResult(predicate=PredicateName.DERIVATION, status=PredicateStatus.PASS)


def support(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> PredicateResult:
    """Every assertion must cite evidence that actually supports it (R1 §10.5).

    An assertion whose ``evidence_id`` is absent from the claim's cited evidence
    (or does not resolve) is uncited. Cited evidence must match the asserted
    value within tolerance, share the unit, and name the same entity; otherwise
    it is irrelevant and does not satisfy support.
    """
    codes: set[str] = set()
    for assertion in claim.assertions:
        evidence_id = assertion.evidence_id
        if (
            not evidence_id
            or evidence_id not in claim.evidence_ids
            or not graph.has_node(evidence_id)
        ):
            codes.add("assertion_evidence_not_cited")
            continue
        node = graph.node(evidence_id)
        metric = _metric_of(node)
        if metric is not None and metric != assertion.metric:
            # Citing real evidence under a false metric label is a forgery of the
            # verified graph; the evidence does not attest the asserted metric.
            codes.add("metric_mismatch")
            continue
        unit = _unit_of(node)
        subject = _subject_of(node)
        value = _value_of(node)
        # DOCUMENTED LIMITATION (TBF-INFRA-1): when the cited node is a bare
        # ComputationResult it attests no entity/metric (``subject``/``metric`` are None),
        # so entity/metric relevance here rests on the untrusted claim's declared
        # subject_id/assertion.metric. This base predicate proves the *value* (and
        # derivation re-checks it) but not the entity/metric *labels* for computation-
        # backed assertions. Independent entity/metric binding is enforced additively by
        # the DTEC institutional-admissibility predicate (A_inst, R-N6 / Phase 4), which
        # requires computation-backed material assertions to bind to entity-attesting
        # provenance; see research/dtec/_confidential/trust-boundary-findings.md. The
        # base behavior is preserved here to avoid weakening the existing core.
        supported = (
            unit is not None
            and unit == assertion.unit
            and (subject is None or subject == claim.subject_id)
            and value is not None
            and _within_tolerance(assertion.asserted_value, value, policy)
        )
        if not supported:
            codes.add("assertion_not_supported")

    if codes:
        return PredicateResult(
            predicate=PredicateName.SUPPORT,
            status=PredicateStatus.FAIL,
            reason_codes=tuple(sorted(codes)),
        )
    return PredicateResult(predicate=PredicateName.SUPPORT, status=PredicateStatus.PASS)


_PredicateFunc = Callable[[EvidenceGraph, CandidateClaim, VerificationPolicy], PredicateResult]

_PREDICATE_FUNCS: dict[PredicateName, _PredicateFunc] = {
    PredicateName.INTEGRITY: integrity,
    PredicateName.TYPE_TEMPORAL: type_temporal,
    PredicateName.PROVENANCE: provenance,
    PredicateName.DERIVATION: derivation,
    PredicateName.SUPPORT: support,
}


# --------------------------------------------------------------------------
# Composition
# --------------------------------------------------------------------------


# Lower rank == higher severity when several mandatory predicates fail.
def _outcome_for_failures(failures: tuple[PredicateResult, ...]) -> VerificationOutcome:
    """Map the failing mandatory predicates to a terminal verdict by severity."""
    ranked: list[tuple[int, VerificationOutcome]] = []
    for result in failures:
        if result.predicate is PredicateName.INTEGRITY:
            ranked.append((0, VerificationOutcome.INTEGRITY_FAILURE))
        elif result.predicate is PredicateName.DERIVATION:
            ranked.append((1, VerificationOutcome.CONTRADICTED))
        elif result.predicate is PredicateName.TYPE_TEMPORAL:
            if "evidence_stale" in result.reason_codes:
                ranked.append((2, VerificationOutcome.STALE))
            else:
                ranked.append((3, VerificationOutcome.INVALID_EVIDENCE))
        elif result.predicate is PredicateName.PROVENANCE:
            ranked.append((3, VerificationOutcome.INVALID_EVIDENCE))
        else:  # SUPPORT
            ranked.append((4, VerificationOutcome.INSUFFICIENT_EVIDENCE))
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def admit(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> AdmissionDecision:
    """Compose the five predicates into an :class:`AdmissionDecision` (R1 §10.6/§10.7).

    All five predicates run and are recorded in :data:`_PREDICATE_ORDER`. A
    predicate is *mandatory* iff it is in ``policy.mandatory_predicates``.
    Admission is ``ADMITTED`` only when every mandatory predicate is ``PASS`` or
    ``NOT_APPLICABLE`` (the latter counts as satisfied — applicable-but-not-
    triggered); any mandatory ``FAIL`` yields ``REJECTED``; any mandatory
    ``UNKNOWN`` with no ``FAIL`` yields ``ABSTAINED`` (unknown is never treated
    as pass or as false). Non-mandatory results are recorded but never block.
    The result is deterministic for identical inputs (R1 §11 invariant 10).
    """
    results = tuple(_PREDICATE_FUNCS[name](graph, claim, policy) for name in _PREDICATE_ORDER)
    by_name = {result.predicate: result for result in results}
    mandatory = tuple(by_name[name] for name in policy.mandatory_predicates)
    failures = tuple(r for r in mandatory if r.status is PredicateStatus.FAIL)
    unknowns = tuple(r for r in mandatory if r.status is PredicateStatus.UNKNOWN)

    if failures:
        outcome = AdmissionOutcome.REJECTED
        verification = _outcome_for_failures(failures)
    elif unknowns:
        outcome = AdmissionOutcome.ABSTAINED
        verification = VerificationOutcome.UNVERIFIABLE
    else:
        outcome = AdmissionOutcome.ADMITTED
        verification = VerificationOutcome.VERIFIED

    return AdmissionDecision(
        outcome=outcome,
        verification_outcome=verification,
        predicate_results=results,
        policy_version=policy.version,
        claim_id=claim.candidate_claim_id,
    )
