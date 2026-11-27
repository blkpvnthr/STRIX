"""Institutional noninterference + computation-backed entity binding (R-N6, part 4).

Two concerns from the institutional engine (confidential companion §9):

1. **Noninterference.** For two states differing only in information inaccessible to
   institution ``j`` (``S1 ==_j S2``), the ``j``-observable output must be identical:
   ``Obs_j(F(S1,q)) == Obs_j(F(S2,q))``. This provides the deterministic test harness; full
   noninterference (incl. timing / cache / metadata / composed channels) is an EMPIRICAL
   question — experimental absence of leakage is not a proof.

2. **Entity binding for computation-backed assertions (DTEC-R-N6-BIND).** An additive
   predicate that closes the documented base-core limitation (TBF-INFRA-1): a bare
   ``ComputationResult`` attests a value but no entity/metric, so a material assertion citing
   one must bind its claimed *entity* to the computation's input-observation provenance.
   This never weakens the base ``support`` predicate — it is an extra mandatory check in the
   DTEC path. (Metric binding for computed values remains a documented residual: a computation
   carries no financial-metric concept; a metric-attesting node is required, future work.)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from strix.evidence_graph.calculus import compose_statuses
from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.nodes import (
    CandidateClaim,
    PredicateName,
    PredicateResult,
    PredicateStatus,
    SourceObservation,
)
from strix.native.results import ComputationResult

__all__ = [
    "assess_entity_binding",
    "noninterference_holds",
    "project_observable",
    "states_equivalent_for",
]


# --------------------------------------------------------------------------
# Noninterference
# --------------------------------------------------------------------------


def project_observable(
    output: Mapping[str, object], accessible_keys: frozenset[str]
) -> dict[str, object]:
    """``Obs_j`` — the projection of an output onto what institution ``j`` may observe."""
    return {k: v for k, v in output.items() if k in accessible_keys}


def states_equivalent_for(
    state_a: Mapping[str, object], state_b: Mapping[str, object], accessible_keys: frozenset[str]
) -> bool:
    """Whether two states are ``==_j`` — agree on every ``j``-accessible key (they may differ
    only in ``j``-inaccessible information)."""
    return all(state_a.get(k) == state_b.get(k) for k in accessible_keys)


def noninterference_holds(
    state_a: Mapping[str, object],
    state_b: Mapping[str, object],
    accessible_keys: frozenset[str],
    response_fn: Callable[[Mapping[str, object]], Mapping[str, object]],
) -> bool:
    """Deterministic noninterference check: for ``j``-equivalent states, the ``j``-observable
    responses must be identical. Returns ``True`` if the property holds for this pair.

    If the two states are not ``==_j`` to begin with, the property is vacuously inapplicable
    and returns ``True`` (the caller supplies genuinely ``j``-equivalent states to test).
    """
    if not states_equivalent_for(state_a, state_b, accessible_keys):
        return True
    obs_a = project_observable(response_fn(state_a), accessible_keys)
    obs_b = project_observable(response_fn(state_b), accessible_keys)
    return obs_a == obs_b


# --------------------------------------------------------------------------
# Entity binding for computation-backed assertions (DTEC-R-N6-BIND)
# --------------------------------------------------------------------------


def assess_entity_binding(claim: CandidateClaim, graph: EvidenceGraph) -> PredicateResult:
    """Entity binding for computation-backed assertions — **refute, never falsely confirm**.

    A bare :class:`ComputationResult` attests a *value* but no entity; its
    ``input_observation_ids`` are untrusted provenance metadata that are **not value-bound**
    to the computed result (the value derives from the raw input series; the observation ids
    do not affect it and can be set freely). Binding therefore cannot *confirm* the claimed
    entity — doing so (an any-match PASS) is bypassable by listing a decoy observation whose
    subject equals the claimed entity. This predicate is accordingly **sound-by-refutation**:

    Per computation-backed assertion:
    - ``claim.subject_id`` **not** among the resolved input-observation subjects ⇒ **FAIL**
      (a definite relabel — the claimed entity is not even in the computation's provenance);
    - subject present, or no resolvable input observations ⇒ **UNKNOWN** (abstain) — a
      necessary condition at best; soundly confirming the entity requires *value-bound*
      computation provenance (an ``input_digest`` covering the input observations' values),
      a native-layer change registered as ``DTEC-NATIVE-PROV``. It **never returns PASS**.

    Non-computation citations are NOT_APPLICABLE (base ``support``/``T`` attest their
    entity/metric). No computation-backed assertions ⇒ NOT_APPLICABLE overall. Net effect:
    this predicate can *reject* a relabel but a computation-backed entity is never *admitted*
    on untrusted provenance alone — fail-safe, never fail-open.
    """
    statuses: list[PredicateStatus] = []
    codes: set[str] = set()
    for assertion in claim.assertions:
        eid = assertion.evidence_id
        if not eid or not graph.has_node(eid):
            continue
        node = graph.node(eid)
        if not isinstance(node, ComputationResult):
            continue  # base predicates attest entity/metric for non-computation nodes
        input_subjects: set[str] = set()
        for oid in node.input_observation_ids:
            if graph.has_node(oid):
                input_node = graph.node(oid)
                if isinstance(input_node, SourceObservation):
                    input_subjects.add(input_node.subject_id)
        if input_subjects and claim.subject_id not in input_subjects:
            statuses.append(PredicateStatus.FAIL)
            codes.add("computation_entity_mismatch")
        else:
            # Subject present among (untrusted) inputs, or no resolvable inputs: a necessary
            # condition at most. Untrusted, non-value-bound provenance cannot *confirm* the
            # entity, so abstain — never a PASS (would be a spoofable any-match).
            statuses.append(PredicateStatus.UNKNOWN)
            codes.add(
                "computation_entity_unestablished"
                if not input_subjects
                else "computation_entity_unverified_provenance"
            )

    if not statuses:
        return PredicateResult(
            predicate=PredicateName.INSTITUTIONAL,
            status=PredicateStatus.NOT_APPLICABLE,
            reason_codes=("no_computation_backed_assertions",),
            detail="no bare-computation citations require entity binding",
        )
    overall = compose_statuses(tuple(statuses))
    return PredicateResult(
        predicate=PredicateName.INSTITUTIONAL,
        status=overall,
        reason_codes=tuple(sorted(codes)),
        detail=f"entity binding over {len(statuses)} computation-backed assertion(s)",
    )
