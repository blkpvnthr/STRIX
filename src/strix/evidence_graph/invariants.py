"""Compositional verification invariants (R1 §11) as *tested* properties.

The five admission predicates (:mod:`strix.evidence_graph.predicates`) decide a
single claim against preserved evidence. Several R1 §11 invariants, however, are
*compositional*: they concern graph-level relationships the per-claim predicates
do not inspect (unresolved contradictions, §11.8) and certificate/contract
validity of the backing computations (§11.16). This module layers those checks on
top of :func:`~strix.evidence_graph.predicates.admit` to produce an *effective*
admission decision, and exposes one ``check_invariant_*`` function per invariant
plus an aggregate :func:`check_invariants`.

Effective admission
-------------------
A claim is *effectively admitted* iff:

1. :func:`~strix.evidence_graph.predicates.admit` returns
   :attr:`~strix.evidence_graph.nodes.AdmissionOutcome.ADMITTED`, **and**
2. no node in its evidence closure participates in an unresolved
   ``CONTRADICTED_BY`` relationship (R1 §11.8), **and**
3. every :class:`~strix.native.results.ComputationResult` backing one of its
   assertions carries a sound numerical-validation status (R1 §11.16).

What these checks are and are NOT
---------------------------------
Each ``check_invariant_*`` function returns an :class:`InvariantResult` recording
whether the invariant *held for the supplied inputs* — it is a property observed
over a concrete graph/claim/policy, **not** a proof that the invariant holds for
all inputs. The checks are deliberately total (they never raise on well-formed
graphs) and deterministic. Several invariants are conditional on the policy making
the relevant predicate mandatory; where the policy does not, the invariant is not
enforced and the checker reports ``holds=False`` (it has teeth) — the docstring of
each function states its assumptions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from strix.canonical import make_id
from strix.evidence_graph.graph import EvidenceGraph, Node, node_identity
from strix.evidence_graph.nodes import (
    AdmissionOutcome,
    CandidateClaim,
    EvidenceGraphError,
    PredicateName,
    PredicateStatus,
    RelationshipKind,
    SourceObservation,
    TemporalMode,
    VerificationPolicy,
    make_edge,
    make_source_observation,
)
from strix.evidence_graph.predicates import (
    AdmissionDecision,
    admit,
    integrity,
    support,
    type_temporal,
)
from strix.models import (
    CalculationResult,
    Evidence,
    SourceArtifact,
    SourceFact,
    StrixModel,
)
from strix.native.contracts import BackendValidation
from strix.native.results import ComputationResult

__all__ = [
    "InvariantResult",
    "admission_blockers",
    "check_invariant_contradiction_reevaluation",
    "check_invariant_evidence_resolution",
    "check_invariant_integrity_not_truth",
    "check_invariant_invalidation_reevaluation",
    "check_invariant_mandatory_dependency",
    "check_invariant_model_cannot_assign_verdict",
    "check_invariant_no_downgrade_on_exhaustion",
    "check_invariant_numerical_contract",
    "check_invariant_point_in_time",
    "check_invariant_reproducibility",
    "check_invariant_unrelated_evidence",
    "check_invariants",
    "is_effectively_admitted",
]

#: Numerical-validation statuses that make a ComputationResult sound evidence for
#: a dependent claim. Everything else (PARITY_FAILED, UNVALIDATED) is unsound.
_SOUND_BACKEND_STATUS: frozenset[BackendValidation] = frozenset(
    {BackendValidation.REFERENCE, BackendValidation.PARITY_PASSED}
)

#: Field-name tokens that would let a model author smuggle in a verdict (R1 §11.7).
_VERDICT_TOKENS: tuple[str, ...] = (
    "status",
    "verdict",
    "verified",
    "outcome",
    "decision",
    "admit",
)


# --------------------------------------------------------------------------
# Result model
# --------------------------------------------------------------------------


class InvariantResult(StrixModel):
    """The outcome of checking one R1 §11 invariant over concrete inputs.

    ``holds`` is ``True`` iff the invariant's property was observed to hold for
    the supplied graph/claim/policy. It is a tested observation, never a proof.
    """

    name: str
    holds: bool
    detail: str


# --------------------------------------------------------------------------
# Closure / reference walking (declared upstream refs, mirroring predicates)
# --------------------------------------------------------------------------


def _upstream_refs(node: Node) -> tuple[str, ...]:
    """Return the ids a node declares it was derived/extracted/computed from.

    Mirrors the provenance walk used by the admission predicates so the
    invariants observe the same lineage the predicates do.
    """
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


def _closure_ids(graph: EvidenceGraph, starts: tuple[str, ...]) -> frozenset[str]:
    """Return *starts* plus every present node reachable via declared upstream refs."""
    seen: set[str] = set()
    stack: list[str] = list(starts)
    while stack:
        current = stack.pop()
        if current in seen or not graph.has_node(current):
            continue
        seen.add(current)
        stack.extend(_upstream_refs(graph.node(current)))
    return frozenset(seen)


def _reachable_artifact_ids(graph: EvidenceGraph, start: str) -> frozenset[str]:
    """Return the preserved :class:`SourceArtifact` ids reachable from *start*."""
    return frozenset(
        nid
        for nid in _closure_ids(graph, (start,))
        if isinstance(graph.node(nid), SourceArtifact)
    )


def _backing_computation(graph: EvidenceGraph, evidence_id: str) -> ComputationResult | None:
    """Return the :class:`ComputationResult` backing *evidence_id*, if any.

    Resolves either a direct ComputationResult node or an :class:`Evidence` node
    whose ``calculation_id`` points at one.
    """
    if not graph.has_node(evidence_id):
        return None
    node = graph.node(evidence_id)
    if isinstance(node, ComputationResult):
        return node
    if isinstance(node, Evidence) and graph.has_node(node.calculation_id):
        upstream = graph.node(node.calculation_id)
        if isinstance(upstream, ComputationResult):
            return upstream
    return None


def _backing_computations(
    graph: EvidenceGraph, claim: CandidateClaim
) -> tuple[ComputationResult, ...]:
    """Return every ComputationResult anywhere in the claim's evidence closure.

    A failed numerical contract backing the claim via ANY derivation path — not
    only one hop from an assertion — must block admission (R1 §11.16), so the
    entire upstream closure is scanned, not just the directly-cited evidence.
    """
    starts = (*claim.evidence_ids, *(a.evidence_id for a in claim.assertions if a.evidence_id))
    out: dict[str, ComputationResult] = {}
    for node_id in _closure_ids(graph, starts):
        node = graph.node(node_id)
        if isinstance(node, ComputationResult):
            out[node.computation_id] = node
        elif isinstance(node, Evidence) and graph.has_node(node.calculation_id):
            upstream = graph.node(node.calculation_id)
            if isinstance(upstream, ComputationResult):
                out[upstream.computation_id] = upstream
    return tuple(out[cid] for cid in sorted(out))


# --------------------------------------------------------------------------
# Compositional blockers (contradictions, numerical contracts)
# --------------------------------------------------------------------------


def _claim_is_contradicted(graph: EvidenceGraph, claim: CandidateClaim) -> bool:
    """Whether the claim or any node in its evidence closure is contradicted.

    An unresolved ``CONTRADICTED_BY`` edge touching the claim's closure (both
    endpoints still present) means the claim cannot be cleanly verified (R1
    §11.8).
    """
    relevant = _closure_ids(graph, claim.evidence_ids) | {claim.candidate_claim_id}
    relevant |= set(claim.evidence_ids)
    for source_id, target_id in graph.find_contradictions():
        if not (graph.has_node(source_id) and graph.has_node(target_id)):
            continue
        if source_id in relevant or target_id in relevant:
            return True
    return False


def _has_unsound_backing_computation(graph: EvidenceGraph, claim: CandidateClaim) -> bool:
    """Whether any ComputationResult backing an assertion has an unsound status (§11.16)."""
    return any(
        comp.numerical_validation_status not in _SOUND_BACKEND_STATUS
        for comp in _backing_computations(graph, claim)
    )


def admission_blockers(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> tuple[str, ...]:
    """Return compositional blockers beyond the per-claim predicates.

    These are the R1 §11 concerns :func:`~strix.evidence_graph.predicates.admit`
    does not inspect: an unresolved contradiction (§11.8) and an unsound backing
    numerical contract (§11.16). An empty tuple means no compositional blocker.
    """
    codes: list[str] = []
    if _claim_is_contradicted(graph, claim):
        codes.append("unresolved_contradiction")
    if _has_unsound_backing_computation(graph, claim):
        codes.append("invalid_numerical_contract")
    return tuple(codes)


def is_effectively_admitted(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> bool:
    """Whether the claim is admitted by the predicates *and* clears all blockers.

    Combines :func:`~strix.evidence_graph.predicates.admit` with
    :func:`admission_blockers` to form the compositional verdict used by the
    contradiction (§11.8) and numerical-contract (§11.16) invariants.
    """
    decision = admit(graph, claim, policy)
    return (
        decision.outcome is AdmissionOutcome.ADMITTED
        and not admission_blockers(graph, claim, policy)
    )


# --------------------------------------------------------------------------
# Graph perturbation helpers
# --------------------------------------------------------------------------


def _clone(graph: EvidenceGraph) -> EvidenceGraph:
    """Return a shallow structural copy of *graph* (same frozen nodes/edges)."""
    clone = EvidenceGraph()
    for node in graph:
        clone.add_node(node)
    for edge in graph.edges():
        clone.add_edge(edge)
    return clone


def _clone_without(graph: EvidenceGraph, node_id: str) -> EvidenceGraph:
    """Return a copy of *graph* with *node_id* and its dangling edges removed."""
    clone = EvidenceGraph()
    for node in graph:
        if node_identity(node) != node_id:
            clone.add_node(node)
    for edge in graph.edges():
        if clone.has_node(edge.source_id) and clone.has_node(edge.target_id):
            clone.add_edge(edge)
    return clone


def _load_bearing_node(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> str | None:
    """Return a node whose removal must break a mandatory structural predicate.

    Picks a directly cited evidence node (breaks INTEGRITY/SUPPORT) or a reachable
    artifact (breaks PROVENANCE), guided by which predicates the policy makes
    mandatory. Returns ``None`` when no such node exists — meaning the policy pins
    no structural predicate and invalidation has nothing to trigger against.
    """
    mandatory = set(policy.mandatory_predicates)
    cited = tuple(e for e in claim.evidence_ids if graph.has_node(e))
    if PredicateName.INTEGRITY in mandatory and cited:
        return cited[0]
    if PredicateName.PROVENANCE in mandatory:
        for evidence_id in claim.evidence_ids:
            artifacts = _reachable_artifact_ids(graph, evidence_id)
            if artifacts:
                return sorted(artifacts)[0]
    if PredicateName.SUPPORT in mandatory and cited:
        return cited[0]
    return None


_CONTRADICTION_COUNTER = "__invariant_contradiction__"


def _with_contradiction(graph: EvidenceGraph, claim: CandidateClaim) -> EvidenceGraph:
    """Return a copy of *graph* with a ``CONTRADICTED_BY`` edge on a cited node.

    Adds a synthetic contradicting observation and links the first cited evidence
    node to it. Raises :class:`EvidenceGraphError` if the claim cites no present
    node to contradict.
    """
    cited = tuple(e for e in claim.evidence_ids if graph.has_node(e))
    if not cited:
        raise EvidenceGraphError("claim cites no present evidence to contradict")
    clone = _clone(graph)
    contradiction = make_source_observation(
        subject_id=claim.subject_id,
        concept=_CONTRADICTION_COUNTER,
        value=claim.assertions[0].asserted_value if claim.assertions else _one_off_value(),
        unit="ratio",
        observation_period="FY2023",
        observed_at=_fixed_time(),
        source_artifact_id="ART-contradiction",
        source_locator="/contradiction/0",
    )
    clone.add_node(contradiction)
    clone.add_edge(
        make_edge(RelationshipKind.CONTRADICTED_BY, cited[0], contradiction.observation_id)
    )
    return clone


def _fixed_time() -> datetime:
    """A fixed tz-aware timestamp for synthetic perturbation nodes."""
    return datetime(2000, 1, 1, tzinfo=UTC)


def _one_off_value() -> Decimal:
    """A fixed Decimal for a synthetic contradiction with no assertion to mirror."""
    return Decimal("-1")


# --------------------------------------------------------------------------
# Individual invariant checks
# --------------------------------------------------------------------------


def _mandatory_results(
    decision: AdmissionDecision, policy: VerificationPolicy
) -> tuple[PredicateStatus, ...]:
    """Return the statuses of the mandatory predicates in *decision*."""
    mandatory = set(policy.mandatory_predicates)
    return tuple(r.status for r in decision.predicate_results if r.predicate in mandatory)


def check_invariant_mandatory_dependency(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> InvariantResult:
    """§11.1 — invalid mandatory dependencies prevent admission.

    Holds iff whenever a mandatory predicate FAILs, the claim is not admitted.
    This is the defining contract of :func:`~strix.evidence_graph.predicates.admit`;
    the check verifies it over the supplied inputs. Assumes the policy lists the
    predicates whose failure should block.
    """
    decision = admit(graph, claim, policy)
    mandatory = set(policy.mandatory_predicates)
    failing = tuple(
        r.predicate.value
        for r in decision.predicate_results
        if r.predicate in mandatory and r.status is PredicateStatus.FAIL
    )
    admitted = decision.outcome is AdmissionOutcome.ADMITTED
    holds = not (failing and admitted)
    detail = f"mandatory failures={failing or '()'}; outcome={decision.outcome.value}"
    return InvariantResult(
        name="R1.11.1 invalid-mandatory-dependency-blocks", holds=holds, detail=detail
    )


def check_invariant_evidence_resolution(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> InvariantResult:
    """§11.2 — supporting evidence must resolve to preserved artifacts.

    Holds iff an admitted claim's every cited evidence id traces to at least one
    preserved :class:`~strix.models.SourceArtifact`. Enforced by the PROVENANCE
    predicate; a policy that omits PROVENANCE does not enforce it and the checker
    reports a violation (teeth).
    """
    decision = admit(graph, claim, policy)
    unresolved = tuple(
        eid for eid in claim.evidence_ids if not _reachable_artifact_ids(graph, eid)
    )
    admitted = decision.outcome is AdmissionOutcome.ADMITTED
    holds = not (admitted and unresolved)
    detail = f"unresolved_evidence={unresolved or '()'}; outcome={decision.outcome.value}"
    return InvariantResult(
        name="R1.11.2 evidence-resolves-to-artifacts", holds=holds, detail=detail
    )


def check_invariant_invalidation_reevaluation(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> InvariantResult:
    """§11.3 — invalidating an upstream node flips a previously-admitted claim.

    If the claim is effectively admitted and the policy pins a structural
    predicate, removing a load-bearing upstream node must flip it to non-admitted.
    Holds vacuously when the baseline was not admitted. Reports a violation when a
    baseline-admitted claim pins no structural predicate (removal changes nothing).
    """
    baseline = is_effectively_admitted(graph, claim, policy)
    if not baseline:
        return InvariantResult(
            name="R1.11.3 invalidation-triggers-reevaluation",
            holds=True,
            detail="baseline not admitted; invariant vacuous",
        )
    target = _load_bearing_node(graph, claim, policy)
    if target is None:
        return InvariantResult(
            name="R1.11.3 invalidation-triggers-reevaluation",
            holds=False,
            detail="baseline admitted but no mandatory structural predicate to invalidate",
        )
    perturbed = _clone_without(graph, target)
    flipped = not is_effectively_admitted(perturbed, claim, policy)
    detail = f"removed={target!r}; flipped={flipped}"
    return InvariantResult(
        name="R1.11.3 invalidation-triggers-reevaluation", holds=flipped, detail=detail
    )


def check_invariant_unrelated_evidence(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> InvariantResult:
    """§11.4 — unrelated evidence cannot satisfy claim support.

    Holds iff an admitted claim's SUPPORT predicate passed (every assertion cites
    evidence that genuinely matches value/unit/entity). Enforced by a mandatory
    SUPPORT predicate; without it the checker reports a violation (teeth).
    """
    decision = admit(graph, claim, policy)
    support_result = support(graph, claim, policy)
    admitted = decision.outcome is AdmissionOutcome.ADMITTED
    holds = not (admitted and support_result.status is not PredicateStatus.PASS)
    detail = f"support={support_result.status.value}; outcome={decision.outcome.value}"
    return InvariantResult(
        name="R1.11.4 unrelated-evidence-insufficient", holds=holds, detail=detail
    )


def check_invariant_point_in_time(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> InvariantResult:
    """§11.5 — post-cutoff information cannot establish point-in-time knowledge.

    In :attr:`~strix.evidence_graph.nodes.TemporalMode.POINT_IN_TIME`, an admitted
    claim must cite no evidence whose TYPE_TEMPORAL check flags
    ``evidence_after_cutoff``. Vacuous in retrospective mode. Enforced by a
    mandatory TYPE_TEMPORAL predicate; without it the checker has teeth.
    """
    if policy.temporal_mode is not TemporalMode.POINT_IN_TIME:
        return InvariantResult(
            name="R1.11.5 point-in-time-cutoff",
            holds=True,
            detail="retrospective mode; invariant vacuous",
        )
    decision = admit(graph, claim, policy)
    tt_result = type_temporal(graph, claim, policy)
    after_cutoff = "evidence_after_cutoff" in tt_result.reason_codes
    admitted = decision.outcome is AdmissionOutcome.ADMITTED
    holds = not (admitted and after_cutoff)
    detail = (
        f"type_temporal={tt_result.status.value}; after_cutoff={after_cutoff}; "
        f"outcome={decision.outcome.value}"
    )
    return InvariantResult(name="R1.11.5 point-in-time-cutoff", holds=holds, detail=detail)


def check_invariant_integrity_not_truth(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> InvariantResult:
    """§11.6 — content integrity cannot independently establish semantic truth.

    A claim whose hashes resolve (INTEGRITY PASS) but whose assertions are not
    supported (SUPPORT FAIL) must not be admitted. Holds iff that combination is
    never admitted. Requires SUPPORT to be mandatory; otherwise integrity alone
    could admit an unsupported claim and the checker reports a violation (teeth).
    """
    decision = admit(graph, claim, policy)
    integ = integrity(graph, claim, policy)
    supp = support(graph, claim, policy)
    admitted = decision.outcome is AdmissionOutcome.ADMITTED
    integrity_ok = integ.status is PredicateStatus.PASS
    support_fail = supp.status is PredicateStatus.FAIL
    holds = not (admitted and integrity_ok and support_fail)
    detail = (
        f"integrity={integ.status.value}; support={supp.status.value}; "
        f"outcome={decision.outcome.value}"
    )
    return InvariantResult(name="R1.11.6 integrity-not-truth", holds=holds, detail=detail)


def check_invariant_model_cannot_assign_verdict(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> InvariantResult:
    """§11.7 — the language model cannot assign or override verified verdicts.

    Two properties: (a) :class:`~strix.evidence_graph.nodes.CandidateClaim` carries
    no field through which a verdict could be injected, and (b) rewriting the
    claim's free-text ``statement``/``claim_type`` to self-assert a verdict does
    not change the computed outcome — only the predicates and policy decide. Holds
    iff both properties are observed.
    """
    offending = tuple(
        name
        for name in CandidateClaim.model_fields
        if any(token in name.lower() for token in _VERDICT_TOKENS)
    )
    baseline = admit(graph, claim, policy).outcome
    self_asserted = claim.model_copy(
        update={
            "statement": f"{claim.statement} [SELF-ASSERTED STATUS: VERIFIED]",
            "claim_type": f"{claim.claim_type}__verified",
        }
    )
    overridden = admit(graph, self_asserted, policy).outcome
    holds = not offending and baseline is overridden
    detail = (
        f"verdict_fields={offending or '()'}; baseline={baseline.value}; "
        f"after_self_assertion={overridden.value}"
    )
    return InvariantResult(name="R1.11.7 model-cannot-assign-verdict", holds=holds, detail=detail)


def check_invariant_contradiction_reevaluation(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> InvariantResult:
    """§11.8 — new contradictory evidence triggers reevaluation.

    If the claim is effectively admitted, introducing a ``CONTRADICTED_BY`` edge on
    a cited node must flip it to non-admitted (via :func:`admission_blockers`).
    Vacuous when the baseline was not admitted or the claim cites no present node.
    """
    baseline = is_effectively_admitted(graph, claim, policy)
    if not baseline:
        return InvariantResult(
            name="R1.11.8 contradiction-triggers-reevaluation",
            holds=True,
            detail="baseline not admitted; invariant vacuous",
        )
    try:
        perturbed = _with_contradiction(graph, claim)
    except EvidenceGraphError as exc:
        return InvariantResult(
            name="R1.11.8 contradiction-triggers-reevaluation",
            holds=True,
            detail=f"no contradiction target: {exc}",
        )
    flipped = not is_effectively_admitted(perturbed, claim, policy)
    detail = f"contradiction_added=True; flipped={flipped}"
    return InvariantResult(
        name="R1.11.8 contradiction-triggers-reevaluation", holds=flipped, detail=detail
    )


def check_invariant_no_downgrade_on_exhaustion(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> InvariantResult:
    """§11.9 — resource exhaustion cannot weaken verification requirements.

    An undetermined (abstain/termination) state surfaces as a mandatory predicate
    with status ``UNKNOWN``; such a state must never be treated as PASS, i.e. it
    must never yield admission. Holds iff no mandatory ``UNKNOWN`` coincides with
    an ADMITTED outcome.
    """
    decision = admit(graph, claim, policy)
    statuses = _mandatory_results(decision, policy)
    has_unknown = PredicateStatus.UNKNOWN in statuses
    admitted = decision.outcome is AdmissionOutcome.ADMITTED
    holds = not (has_unknown and admitted)
    detail = f"mandatory_unknown={has_unknown}; outcome={decision.outcome.value}"
    return InvariantResult(name="R1.11.9 no-downgrade-on-exhaustion", holds=holds, detail=detail)


def check_invariant_reproducibility(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> InvariantResult:
    """§11.10 — identical normalized inputs + pinned policy → reproducible decision.

    Holds iff two independent evaluations over the same inputs produce an equal
    :class:`~strix.evidence_graph.predicates.AdmissionDecision` and an identical
    normalized digest. Assumes the policy is pinned (its ``version`` is fixed).
    """
    first = admit(graph, claim, policy)
    second = admit(graph, claim, policy)
    equal = first == second
    digest_first = make_id("INVDEC", first.model_dump())
    digest_second = make_id("INVDEC", second.model_dump())
    holds = equal and digest_first == digest_second
    detail = f"decisions_equal={equal}; digest={digest_first}"
    return InvariantResult(name="R1.11.10 reproducible-decision", holds=holds, detail=detail)


def check_invariant_numerical_contract(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> InvariantResult:
    """§11.16 — invalid numerical contracts block dependent findings.

    If any :class:`~strix.native.results.ComputationResult` backing an assertion
    carries an unsound numerical-validation status (e.g. ``PARITY_FAILED``), the
    dependent claim must not be effectively admitted — even if the per-claim
    predicates would admit it (the derivation predicate checks only the value, not
    the backend's parity status). Holds iff that blocking occurs.
    """
    unsound = tuple(
        comp.computation_id
        for comp in _backing_computations(graph, claim)
        if comp.numerical_validation_status not in _SOUND_BACKEND_STATUS
    )
    effectively_admitted = is_effectively_admitted(graph, claim, policy)
    holds = not (unsound and effectively_admitted)
    detail = f"unsound_computations={unsound or '()'}; effectively_admitted={effectively_admitted}"
    return InvariantResult(name="R1.11.16 numerical-contract-blocks", holds=holds, detail=detail)


# --------------------------------------------------------------------------
# Aggregate
# --------------------------------------------------------------------------

_INVARIANT_CHECKS = (
    check_invariant_mandatory_dependency,
    check_invariant_evidence_resolution,
    check_invariant_invalidation_reevaluation,
    check_invariant_unrelated_evidence,
    check_invariant_point_in_time,
    check_invariant_integrity_not_truth,
    check_invariant_model_cannot_assign_verdict,
    check_invariant_contradiction_reevaluation,
    check_invariant_no_downgrade_on_exhaustion,
    check_invariant_reproducibility,
    check_invariant_numerical_contract,
)


def check_invariants(
    graph: EvidenceGraph, claim: CandidateClaim, policy: VerificationPolicy
) -> tuple[InvariantResult, ...]:
    """Run every compositional invariant check over the supplied inputs (R1 §11).

    Returns one :class:`InvariantResult` per invariant, in a fixed order. The
    results are *tested observations* over these concrete inputs — not a proof the
    invariants hold universally. Each result's ``holds`` reflects whether the
    property was satisfied; several invariants are conditional on the policy making
    the relevant predicate mandatory (see the individual checks).
    """
    return tuple(check(graph, claim, policy) for check in _INVARIANT_CHECKS)
