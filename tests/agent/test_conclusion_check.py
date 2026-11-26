"""Conclusion-level verification of the complete final answer (DTEC A_C — R∧K∧F).

The per-claim verifier checks isolated candidate claims; this gate evaluates the COMPLETE
synthesized answer as a Conclusion whose premises are the independently-verified claims,
using the compositional calculus. It is additive — it never weakens per-claim verification.
"""

from __future__ import annotations

from strix.agent.conclusion_check import verify_final_answer
from strix.agent.models import (
    AgentClaim,
    AgentClaimType,
    AgentVerificationStatus,
    ClaimVerification,
    ConclusionVerification,
)


def _claim(cid: str, status: AgentVerificationStatus) -> AgentClaim:
    return AgentClaim(
        claim_id=cid,
        claim_type=AgentClaimType.OBSERVATION,
        statement=f"statement {cid}",
        evidence_ids=(f"E-{cid}",),
        verification=ClaimVerification(status=status),
    )


def test_admits_conclusion_backed_by_verified_premises() -> None:
    verified = (
        _claim("c1", AgentVerificationStatus.VERIFIED),
        _claim("c2", AgentVerificationStatus.VERIFIED),
    )
    result = verify_final_answer(proposition="margins expanded", verified=verified, unresolved=())
    assert isinstance(result, ConclusionVerification)
    assert result.outcome == "admitted"
    assert result.opposing_claim_ids == ()


def test_abstains_when_no_verified_premise_supports_the_answer() -> None:
    # An answer with no independently verified premise asserts no verified conclusion:
    # an honest abstention, NOT a false conclusion (and NOT a hard rejection).
    unresolved = (_claim("u1", AgentVerificationStatus.UNVERIFIABLE),)
    result = verify_final_answer(
        proposition="the market will rise", verified=(), unresolved=unresolved
    )
    assert result.outcome == "abstained"
    assert "no_verified_premises" in result.reason_codes


def test_rejects_conclusion_when_a_claim_was_recompute_contradicted() -> None:
    # A recompute-CONTRADICTED claim is genuine refuted evidence in the run; the final
    # conclusion must not be presented as cleanly verified — fail closed (REJECTED verdict).
    verified = (_claim("c1", AgentVerificationStatus.VERIFIED),)
    unresolved = (_claim("bad", AgentVerificationStatus.CONTRADICTED),)
    result = verify_final_answer(
        proposition="revenue grew 10%", verified=verified, unresolved=unresolved
    )
    assert result.outcome == "rejected"
    assert "bad" in result.opposing_claim_ids


def test_unrelated_non_contradicted_unresolved_claims_do_not_reject() -> None:
    # INSUFFICIENT_EVIDENCE / STALE are not refutations, so they are not treated as
    # substantive opposition to the conclusion.
    verified = (_claim("c1", AgentVerificationStatus.VERIFIED),)
    unresolved = (
        _claim("u1", AgentVerificationStatus.INSUFFICIENT_EVIDENCE),
        _claim("u2", AgentVerificationStatus.STALE),
    )
    result = verify_final_answer(proposition="x", verified=verified, unresolved=unresolved)
    assert result.outcome == "admitted"
    assert result.opposing_claim_ids == ()


def test_result_is_a_serializable_model() -> None:
    result = verify_final_answer(
        proposition="x", verified=(_claim("c1", AgentVerificationStatus.VERIFIED),), unresolved=()
    )
    assert result.model_dump()["outcome"] == "admitted"
