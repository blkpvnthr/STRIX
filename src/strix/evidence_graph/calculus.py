"""Compositional evidence calculus — conclusion-level admission ``A_C`` (R-N3).

This is the principal mathematical research initiative (confidential companion §6).
Individually verified premises do **not** establish conclusion validity; a conclusion is
admitted only when

    A_C(C) = ( ⋀_i A(c_i) ) ∧ R(C) ∧ K(C) ∧ F(C)                    (manuscript eq 9)

holds, where ``R`` is inferential validity (formal entailment for the formally
representable fragment; :mod:`strix.evidence_graph.inference`), ``K`` is contextual
applicability, ``F`` is completeness & conclusion faithfulness, and ``⋀_i A(c_i)`` ranges
over the required **derivation closure** ``Cl(C)`` (cyclic justification without
independent grounding is insufficient).

All components compose under the four-valued admission algebra (FAIL dominates; then
UNKNOWN; PASS only if all pass; NOT_APPLICABLE is satisfied). By the fail-closed
extension property (Proposition 3 / INV-ALG-3) adding ``R``/``K``/``F`` to the preserved
claim-level core can only make admission *stricter*, never weaker.

Support and opposition are represented separately as ``(s⁺, s⁻)``; a substantive
contradiction is never cleared by subtracting the two (CE-N3-3).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.inference import (
    EntailmentStatus,
    Formula,
    ReferenceChecker,
    decide_entailment,
    z3_available,
    z3_checker,
)
from strix.evidence_graph.nodes import (
    AdmissionOutcome,
    PredicateName,
    PredicateResult,
    PredicateStatus,
)
from strix.models import SourceArtifact, StrixModel

__all__ = [
    "Conclusion",
    "ConclusionDecision",
    "FormalEncoding",
    "SupportBalance",
    "admit_conclusion",
    "assess_contextual",
    "assess_faithfulness",
    "assess_inferential",
    "compose_statuses",
]


# --------------------------------------------------------------------------
# Conclusion representation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FormalEncoding:
    """A propositional encoding of a conclusion for the formal fragment.

    ``context`` is ``Γ`` (assumptions/constraints), ``premises`` is ``Φ = ⋀ c_i``, and
    ``conclusion`` is ``φ_C``. Entailment is decided over ``Γ ∧ Φ ⊨ φ_C``. The encoding
    is validity *relative to itself*; it does not assert that the natural-language
    translation is faithful (that is a separate empirical check).
    """

    context: Formula
    premises: Formula
    conclusion: Formula


@dataclass(frozen=True)
class SupportBalance:
    """Separately tracked supporting and opposing evidence ``(s⁺, s⁻)``.

    A genuine opposition (``opposing`` non-empty with a substantive conflict) is a
    contradiction that must not be admitted; it is never cancelled by subtraction.
    """

    supporting: tuple[str, ...] = ()
    opposing: tuple[str, ...] = ()
    substantive_conflict: bool = False


@dataclass(frozen=True)
class Conclusion:
    """A candidate conclusion ``C = (φ_C, Φ, Γ, r)``.

    ``premise_claim_ids`` are the material premises ``Φ``; ``assumptions`` are context
    requirement keys checked by ``K``; ``formal`` (optional) enables the ``R`` entailment
    check for the formally representable fragment.
    """

    conclusion_id: str
    proposition: str
    premise_claim_ids: tuple[str, ...]
    assumptions: tuple[str, ...] = ()
    inference_rule: str = "unspecified"
    formal: FormalEncoding | None = None
    balance: SupportBalance = field(default_factory=SupportBalance)


class ConclusionDecision(StrixModel):
    """The outcome of ``A_C`` for one conclusion, with every component result."""

    conclusion_id: str
    outcome: AdmissionOutcome
    predicate_results: tuple[PredicateResult, ...]
    entailment_status: str | None = None
    counterexample: str | None = None
    detail: str = ""


# --------------------------------------------------------------------------
# Admission-algebra composition
# --------------------------------------------------------------------------


def compose_statuses(statuses: tuple[PredicateStatus, ...]) -> PredicateStatus:
    """Four-valued conjunction (INV-ALG-1): FAIL ⊐ UNKNOWN ⊐ PASS; NA is satisfied.

    Raises :class:`ValueError` on an empty applicable set (no vacuous PASS; RC-3): the
    caller must guarantee at least one applicable predicate.
    """
    applicable = [s for s in statuses if s is not PredicateStatus.NOT_APPLICABLE]
    if not applicable:
        raise ValueError("no applicable predicate: refusing a vacuous admission (RC-3)")
    if any(s is PredicateStatus.FAIL for s in applicable):
        return PredicateStatus.FAIL
    if any(s is PredicateStatus.UNKNOWN for s in applicable):
        return PredicateStatus.UNKNOWN
    return PredicateStatus.PASS


def _outcome_of(status: PredicateStatus) -> AdmissionOutcome:
    if status is PredicateStatus.FAIL:
        return AdmissionOutcome.REJECTED
    if status is PredicateStatus.UNKNOWN:
        return AdmissionOutcome.ABSTAINED
    return AdmissionOutcome.ADMITTED


# --------------------------------------------------------------------------
# R — inferential validity
# --------------------------------------------------------------------------


def assess_inferential(
    conclusion: Conclusion, *, checker: ReferenceChecker | None = None, use_z3: bool = False
) -> PredicateResult:
    """Evaluate ``R``: does ``Γ ∧ Φ`` formally entail ``φ_C``?

    NOT_APPLICABLE when the conclusion carries no formal encoding (an empirical
    conclusion whose validity rests on premise admission + ``F``). The trusted exact
    reference checker decides; the optional SMT backend is consulted **only** when the
    reference checker returns UNKNOWN (too many atoms), and a solver UNKNOWN still yields
    UNKNOWN — never a proof.
    """
    if conclusion.formal is None:
        return PredicateResult(
            predicate=PredicateName.INFERENTIAL,
            status=PredicateStatus.NOT_APPLICABLE,
            reason_codes=("not_formally_representable",),
            detail="no formal encoding; validity rests on premise admission and faithfulness",
        )
    enc = conclusion.formal
    from strix.evidence_graph.inference import And  # local import to avoid top clutter

    combined: Formula = And((enc.context, enc.premises))
    result = decide_entailment(combined, enc.conclusion, checker=checker)
    if result.status is EntailmentStatus.UNKNOWN and use_z3 and z3_available():
        result = z3_checker(combined, enc.conclusion)

    status_map = {
        EntailmentStatus.ENTAILED: (PredicateStatus.PASS, "formally_entailed"),
        EntailmentStatus.NOT_ENTAILED: (PredicateStatus.FAIL, "counterexample_exists"),
        EntailmentStatus.INCONSISTENT_PREMISES: (PredicateStatus.FAIL, "inconsistent_premises"),
        EntailmentStatus.UNKNOWN: (PredicateStatus.UNKNOWN, "entailment_undecided"),
    }
    status, code = status_map[result.status]
    return PredicateResult(
        predicate=PredicateName.INFERENTIAL,
        status=status,
        reason_codes=(code,),
        detail=f"{result.backend}: {result.detail}"
        + (f"; counterexample={result.counterexample}" if result.counterexample else ""),
    )


# --------------------------------------------------------------------------
# K — contextual applicability
# --------------------------------------------------------------------------


def assess_contextual(
    conclusion: Conclusion, satisfied_context: frozenset[str]
) -> PredicateResult:
    """Evaluate ``K``: are the conclusion's declared contextual assumptions satisfied?

    NOT_APPLICABLE when the conclusion declares no assumptions. Otherwise PASS iff every
    declared assumption key is in *satisfied_context*; else FAIL naming the unmet ones.
    """
    required = set(conclusion.assumptions)
    if not required:
        return PredicateResult(
            predicate=PredicateName.CONTEXTUAL,
            status=PredicateStatus.NOT_APPLICABLE,
            reason_codes=("no_contextual_assumptions",),
            detail="conclusion declares no contextual assumptions",
        )
    unmet = sorted(required - satisfied_context)
    if unmet:
        return PredicateResult(
            predicate=PredicateName.CONTEXTUAL,
            status=PredicateStatus.FAIL,
            reason_codes=("unmet_contextual_assumptions",),
            detail=f"unmet assumptions: {', '.join(unmet)}",
        )
    return PredicateResult(
        predicate=PredicateName.CONTEXTUAL,
        status=PredicateStatus.PASS,
        reason_codes=("context_applicable",),
        detail=f"all {len(required)} contextual assumption(s) satisfied",
    )


# --------------------------------------------------------------------------
# F — completeness & conclusion faithfulness (incl. derivation closure)
# --------------------------------------------------------------------------


def _closure_grounded(conclusion: Conclusion, graph: EvidenceGraph) -> tuple[bool, bool, str]:
    """Return ``(acyclic, grounded, detail)`` for the premises' derivation closure.

    Grounded = the closure reaches at least one :class:`SourceArtifact` ground. A cyclic
    derivation subgraph, or a closure with no independent grounding, is insufficient.
    """
    try:
        graph.assert_acyclic_derivation()
    except Exception as exc:  # EvidenceGraphError names the cycle
        return False, False, str(exc)
    grounded = False
    for premise_id in conclusion.premise_claim_ids:
        if not graph.has_node(premise_id):
            continue
        closure = graph.evidence_closure(premise_id)
        for node_id in closure:
            if isinstance(graph.node(node_id), SourceArtifact):
                grounded = True
                break
        if grounded:
            break
    return True, grounded, "closure acyclic; " + ("grounded" if grounded else "no ground source")


def assess_faithfulness(
    conclusion: Conclusion,
    premise_admissions: Mapping[str, AdmissionOutcome],
    *,
    graph: EvidenceGraph | None = None,
) -> PredicateResult:
    """Evaluate ``F``: is the conclusion complete and faithful to its admitted premises?

    FAIL when there are no premises (an unsupported leap), when a required premise is
    rejected, or (with a graph) when the derivation closure is cyclic or ungrounded.
    UNKNOWN when a premise's admission is unknown/abstained. Also rejects an unresolved
    substantive contradiction in the support balance (CE-N3-3).
    """
    if not conclusion.premise_claim_ids:
        return PredicateResult(
            predicate=PredicateName.FAITHFULNESS,
            status=PredicateStatus.FAIL,
            reason_codes=("no_supporting_premises",),
            detail="conclusion asserts more than its (empty) premise set supports",
        )
    if conclusion.balance.opposing and conclusion.balance.substantive_conflict:
        return PredicateResult(
            predicate=PredicateName.FAITHFULNESS,
            status=PredicateStatus.FAIL,
            reason_codes=("unresolved_substantive_contradiction",),
            detail="opposing evidence presents a substantive contradiction (not subtractable)",
        )

    statuses: list[PredicateStatus] = []
    for pid in conclusion.premise_claim_ids:
        outcome = premise_admissions.get(pid)
        if outcome is AdmissionOutcome.REJECTED:
            return PredicateResult(
                predicate=PredicateName.FAITHFULNESS,
                status=PredicateStatus.FAIL,
                reason_codes=("rejected_premise",),
                detail=f"premise {pid} is not admitted (rejected)",
            )
        statuses.append(
            PredicateStatus.PASS
            if outcome is AdmissionOutcome.ADMITTED
            else PredicateStatus.UNKNOWN
        )

    if graph is not None:
        acyclic, grounded, detail = _closure_grounded(conclusion, graph)
        if not acyclic:
            return PredicateResult(
                predicate=PredicateName.FAITHFULNESS,
                status=PredicateStatus.FAIL,
                reason_codes=("cyclic_derivation_closure",),
                detail=detail,
            )
        if not grounded:
            return PredicateResult(
                predicate=PredicateName.FAITHFULNESS,
                status=PredicateStatus.UNKNOWN,
                reason_codes=("ungrounded_closure",),
                detail=detail,
            )

    if any(s is PredicateStatus.UNKNOWN for s in statuses):
        return PredicateResult(
            predicate=PredicateName.FAITHFULNESS,
            status=PredicateStatus.UNKNOWN,
            reason_codes=("premise_admission_unresolved",),
            detail="one or more premises are not yet admitted",
        )
    return PredicateResult(
        predicate=PredicateName.FAITHFULNESS,
        status=PredicateStatus.PASS,
        reason_codes=("complete_and_faithful",),
        detail=f"all {len(conclusion.premise_claim_ids)} premise(s) admitted; closure grounded",
    )


# --------------------------------------------------------------------------
# A_C — compositional conclusion admission
# --------------------------------------------------------------------------


def _premise_conjunction(
    conclusion: Conclusion, premise_admissions: Mapping[str, AdmissionOutcome]
) -> PredicateResult:
    """``⋀_i A(c_i)`` as a single result (premise-admission conjunction)."""
    statuses: list[PredicateStatus] = []
    for pid in conclusion.premise_claim_ids:
        outcome = premise_admissions.get(pid)
        if outcome is AdmissionOutcome.REJECTED:
            statuses.append(PredicateStatus.FAIL)
        elif outcome is AdmissionOutcome.ADMITTED:
            statuses.append(PredicateStatus.PASS)
        else:  # ABSTAINED or unknown-to-us
            statuses.append(PredicateStatus.UNKNOWN)
    status = (
        compose_statuses(tuple(statuses)) if statuses else PredicateStatus.FAIL
    )
    code = {
        PredicateStatus.PASS: "all_premises_admitted",
        PredicateStatus.FAIL: "a_premise_is_rejected",
        PredicateStatus.UNKNOWN: "a_premise_is_unresolved",
    }[status]
    return PredicateResult(
        predicate=PredicateName.FAITHFULNESS,  # premise-level conjunction reported under F-family
        status=status,
        reason_codes=(code,),
        detail=f"premise conjunction over {len(conclusion.premise_claim_ids)} premise(s)",
    )


def admit_conclusion(
    conclusion: Conclusion,
    premise_admissions: Mapping[str, AdmissionOutcome],
    *,
    graph: EvidenceGraph | None = None,
    satisfied_context: frozenset[str] = frozenset(),
    checker: ReferenceChecker | None = None,
    use_z3: bool = False,
) -> ConclusionDecision:
    """Evaluate ``A_C(C) = (⋀A(c_i)) ∧ R ∧ K ∧ F`` and return the decision.

    ``premise_admissions`` maps each premise claim id to its *already-computed*
    claim-level :class:`AdmissionOutcome` (the engine does not re-run the five core
    predicates — it composes their verdicts). Composition is fail-closed: any component
    FAIL rejects; any UNKNOWN (no FAIL) abstains; PASS only if every applicable component
    passes.
    """
    premise = _premise_conjunction(conclusion, premise_admissions)
    inferential = assess_inferential(conclusion, checker=checker, use_z3=use_z3)
    contextual = assess_contextual(conclusion, satisfied_context)
    faithfulness = assess_faithfulness(conclusion, premise_admissions, graph=graph)

    results = (premise, inferential, contextual, faithfulness)
    status = compose_statuses(tuple(r.status for r in results))

    entailment_status = None
    counterexample = None
    if conclusion.formal is not None:
        # Surface the entailment detail for the certificate/audit trace.
        if "counterexample=" in inferential.detail:
            counterexample = inferential.detail.split("counterexample=", 1)[1]
        entailment_status = inferential.reason_codes[0]

    return ConclusionDecision(
        conclusion_id=conclusion.conclusion_id,
        outcome=_outcome_of(status),
        predicate_results=results,
        entailment_status=entailment_status,
        counterexample=counterexample,
        detail=f"A_C={status.value} over premise∧R∧K∧F",
    )
