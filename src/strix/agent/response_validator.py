"""Fail-closed validation of the final answer.

The system must never present an unsupported assertion as verified. This guard
runs after assembly and raises :class:`ResponseValidationError` if any invariant
is violated, so a broken answer is withheld rather than displayed.

Invariants:
- Every claim in ``verified_claims`` actually has status VERIFIED.
- No claim appears in both verified and unresolved groups.
- Every verified claim cites at least one evidence id that resolves.
- Every verified *quantitative* claim was independently recomputed (has a
  computed_value and a method).
- Unresolved claims are never VERIFIED.
"""

from __future__ import annotations

from strix.agent.config import AgentConfig
from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import (
    AgentClaimType,
    AgentVerificationStatus,
    ResearchAnswer,
)
from strix.errors import ResponseValidationError

_RECOMPUTED_TYPES = frozenset(
    {AgentClaimType.QUANTITATIVE, AgentClaimType.HISTORICAL_COMPARISON}
)


def validate_answer(
    answer: ResearchAnswer,
    collector: EvidenceCollector,
    config: AgentConfig,
) -> None:
    """Raise :class:`ResponseValidationError` if any fail-closed invariant breaks."""
    problems: list[str] = []

    verified_ids = {c.claim_id for c in answer.verified_claims}
    unresolved_ids = {c.claim_id for c in answer.unresolved_claims}
    overlap = verified_ids & unresolved_ids
    if overlap:
        problems.append(f"claims appear as both verified and unresolved: {sorted(overlap)}")

    for claim in answer.verified_claims:
        if claim.verification.status is not AgentVerificationStatus.VERIFIED:
            problems.append(
                f"claim {claim.claim_id} is in verified_claims but has status "
                f"{claim.verification.status.value}"
            )
        if config.require_citations and not claim.evidence_ids:
            problems.append(f"verified claim {claim.claim_id} cites no evidence")
        for eid in claim.evidence_ids:
            if collector.evidence(eid) is None:
                problems.append(
                    f"verified claim {claim.claim_id} cites unresolved evidence {eid}"
                )
        if claim.claim_type in _RECOMPUTED_TYPES and (
            claim.verification.computed_value is None or claim.verification.method is None
        ):
            problems.append(
                f"verified quantitative claim {claim.claim_id} was not independently "
                f"recomputed"
            )

    for claim in answer.unresolved_claims:
        if claim.verification.status is AgentVerificationStatus.VERIFIED:
            problems.append(f"unresolved claim {claim.claim_id} is marked VERIFIED")

    # Conclusion-level verification must be communicated, not silently dropped: a REJECTED
    # final conclusion has to be surfaced in the answer's limitations (fail-closed on the
    # §3 "communicate unresolved contradictions" requirement).
    cv = answer.conclusion_verification
    if cv is not None and cv.outcome == "rejected":
        communicated = any("conclusion-level" in lim.lower() for lim in answer.limitations)
        if not communicated:
            problems.append(
                "conclusion-level verification REJECTED the answer but no limitation "
                "communicates it"
            )

    if problems:
        raise ResponseValidationError("; ".join(problems))
