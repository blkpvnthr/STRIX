"""Conclusion-level verification of the COMPLETE final answer (DTEC ``A_C``).

The per-claim verifier (:mod:`strix.agent.verifier`) checks isolated candidate claims. This
module adds the conclusion-level gate the integration mandate requires: the *complete*
synthesized answer is independently evaluated as a single
:class:`~strix.evidence_graph.calculus.Conclusion` whose premises are the independently
verified claims, via :func:`~strix.evidence_graph.calculus.admit_conclusion`
(``A_C = (⋀ A(c_i)) ∧ R ∧ K ∧ F``).

**Honest live-path scope (what is actually operative here, not what A_C can do in general).**
For a natural-language research answer with no formal encoding and no declared contextual
assumptions beyond temporal applicability, the operative checks are:

1. an explicit **recompute-contradiction gate** — any recompute-CONTRADICTED claim in the run
   ⇒ ``rejected`` (refuted evidence means the conclusion is not cleanly verified), applied
   regardless of how many other claims verified; and
2. **F (completeness)** — the answer must rest on ≥1 independently-verified premise; with none,
   the answer asserts no verified conclusion ⇒ ``abstained`` (honest abstention, not rejection).

``R`` (formal entailment) is NOT_APPLICABLE for a natural-language conclusion (no formal
encoding is fabricated) and the premise conjunction / ``K`` are trivially satisfied given these
inputs — they become genuinely active only when a formal encoding or declared assumptions are
supplied. This is the honest, additive integration; it never weakens per-claim verification and
does not claim to enforce the full eleven-predicate ``A_DTEC`` per claim (see the ledger for the
scoped-remaining per-claim bridge).
"""

from __future__ import annotations

from strix.agent.models import (
    AgentClaim,
    AgentVerificationStatus,
    ConclusionVerification,
)
from strix.evidence_graph.calculus import Conclusion, SupportBalance, admit_conclusion
from strix.evidence_graph.nodes import AdmissionOutcome, PredicateStatus

__all__ = ["verify_final_answer"]

#: Contextual-applicability assumption (K): the answer is scoped to its as-of knowledge state.
_TEMPORAL_ASSUMPTION = "temporal_applicability"


def verify_final_answer(
    *,
    proposition: str,
    verified: tuple[AgentClaim, ...],
    unresolved: tuple[AgentClaim, ...],
) -> ConclusionVerification:
    """Evaluate the complete final answer at conclusion level and return the verdict."""
    verified_ids = tuple(c.claim_id for c in verified)
    contradicted = tuple(
        c.claim_id
        for c in unresolved
        if c.verification.status is AgentVerificationStatus.CONTRADICTED
    )

    # A recompute-CONTRADICTED claim is refuted evidence in the run. The final answer cannot be
    # presented as cleanly verified when STRIX's own recompute refuted an asserted fact —
    # regardless of how many *other* claims verified (or whether any did). Fail closed FIRST so
    # the empty-premise and contradiction cases are consistent.
    if contradicted:
        return ConclusionVerification(
            outcome=AdmissionOutcome.REJECTED.value,
            reason_codes=("recompute_contradicted_evidence",),
            opposing_claim_ids=contradicted,
            detail=f"{len(contradicted)} claim(s) independently contradicted in this run",
        )

    if not verified_ids:
        return ConclusionVerification(
            outcome=AdmissionOutcome.ABSTAINED.value,
            reason_codes=("no_verified_premises",),
            opposing_claim_ids=(),
            detail="no independently verified premise supports a conclusion",
        )

    # No contradiction and ≥1 verified premise: the operative compositional check on the live
    # path is F (completeness — the answer must rest on admitted premises). R (formal
    # entailment) is NOT_APPLICABLE for a natural-language conclusion and K (declared
    # assumptions) is satisfied here; both become active when a formal encoding / declared
    # assumptions are supplied. See the module docstring for this honest scoping.
    premise_admissions = dict.fromkeys(verified_ids, AdmissionOutcome.ADMITTED)
    conclusion = Conclusion(
        conclusion_id="final-answer",
        proposition=proposition or "research conclusion",
        premise_claim_ids=verified_ids,
        assumptions=(_TEMPORAL_ASSUMPTION,),
        balance=SupportBalance(supporting=verified_ids),
    )
    decision = admit_conclusion(
        conclusion,
        premise_admissions,
        satisfied_context=frozenset({_TEMPORAL_ASSUMPTION}),
    )
    # Surface only genuine problems (FAIL / UNKNOWN); NOT_APPLICABLE and PASS are not defects.
    reason_codes = tuple(
        code
        for result in decision.predicate_results
        if result.status in (PredicateStatus.FAIL, PredicateStatus.UNKNOWN)
        for code in result.reason_codes
    )
    return ConclusionVerification(
        outcome=decision.outcome.value,
        reason_codes=reason_codes,
        opposing_claim_ids=(),
        detail=decision.detail,
    )
