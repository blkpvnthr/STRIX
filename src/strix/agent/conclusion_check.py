"""Conclusion-level verification of the COMPLETE final answer (DTEC ``A_C`` — R∧K∧F).

The per-claim verifier (:mod:`strix.agent.verifier`) checks isolated candidate claims. This
module adds the conclusion-level gate the integration mandate requires: the *complete*
synthesized answer is independently evaluated as a single
:class:`~strix.evidence_graph.calculus.Conclusion` whose premises are the independently
verified claims, using the compositional calculus
:func:`~strix.evidence_graph.calculus.admit_conclusion` (``A_C = (⋀ A(c_i)) ∧ R ∧ K ∧ F``).

Design (honest, additive — never weakens per-claim verification):

- Premises are the verified claims (mapped to ADMITTED). With ≥1 verified premise and the
  contextual (temporal-applicability) assumption satisfied, ``A_C`` PASSes → ``admitted``.
- With **no** verified premise, the answer asserts no independently-verified conclusion — an
  honest abstention (``abstained``), not a false conclusion and not a hard rejection.
- A recompute-**CONTRADICTED** claim is genuine refuted evidence in the run. It is surfaced as
  *opposing* with a substantive conflict, so ``F`` fails closed → ``rejected``: the final
  conclusion must not be presented as cleanly verified when STRIX's own recompute refuted an
  asserted fact in the same run.
- ``R`` (formal inferential entailment) is NOT_APPLICABLE for a natural-language conclusion —
  this module does not fabricate a formal encoding.
"""

from __future__ import annotations

from strix.agent.models import (
    AgentClaim,
    AgentVerificationStatus,
    ConclusionVerification,
)
from strix.evidence_graph.calculus import Conclusion, SupportBalance, admit_conclusion
from strix.evidence_graph.nodes import AdmissionOutcome

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

    if not verified_ids:
        return ConclusionVerification(
            outcome=AdmissionOutcome.ABSTAINED.value,
            reason_codes=("no_verified_premises",),
            opposing_claim_ids=contradicted,
            detail="no independently verified premise supports a conclusion",
        )

    premise_admissions = dict.fromkeys(verified_ids, AdmissionOutcome.ADMITTED)
    balance = SupportBalance(
        supporting=verified_ids,
        opposing=contradicted,
        substantive_conflict=bool(contradicted),
    )
    conclusion = Conclusion(
        conclusion_id="final-answer",
        proposition=proposition or "research conclusion",
        premise_claim_ids=verified_ids,
        assumptions=(_TEMPORAL_ASSUMPTION,),
        balance=balance,
    )
    decision = admit_conclusion(
        conclusion,
        premise_admissions,
        satisfied_context=frozenset({_TEMPORAL_ASSUMPTION}),
    )
    reason_codes = tuple(
        code
        for result in decision.predicate_results
        for code in result.reason_codes
        if result.status is not result.status.PASS
    )
    return ConclusionVerification(
        outcome=decision.outcome.value,
        reason_codes=reason_codes,
        opposing_claim_ids=contradicted,
        detail=decision.detail,
    )
