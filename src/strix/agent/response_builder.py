"""Deterministic assembly and rendering of the final research answer.

The answer is built from structured, already-verified claims — not from free
model prose — so it cannot introduce an unsupported assertion. Verified claims
render their statements with a bracketed citation index; unresolved claims are
disclosed separately with their verdicts, never as facts.
"""

from __future__ import annotations

from datetime import datetime

from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import (
    AgentClaim,
    AgentEvidence,
    AgentVerificationStatus,
    ResearchAnswer,
)

_DISCLAIMER = (
    "STRIX research prototype. Evidence-grounded and independently verified where "
    "stated; not investment advice."
)


def build_answer(
    *,
    run_id: str,
    question: str,
    verified_claims: tuple[AgentClaim, ...],
    unresolved_claims: tuple[AgentClaim, ...],
    collector: EvidenceCollector,
    limitations: tuple[str, ...],
    now: datetime,
) -> ResearchAnswer:
    """Assemble a validated-ready ResearchAnswer from verified structured claims."""
    cited_ids = _cited_evidence_ids(verified_claims, unresolved_claims)
    evidence = tuple(e for e in collector.all_evidence() if e.evidence_id in cited_ids)
    data_as_of = _latest_retrieval(evidence)
    summary = _summary(verified_claims, unresolved_claims)
    return ResearchAnswer(
        run_id=run_id,
        question=question,
        data_as_of=data_as_of,
        summary=summary,
        verified_claims=verified_claims,
        unresolved_claims=unresolved_claims,
        evidence=evidence,
        limitations=limitations,
        disclaimer=_DISCLAIMER,
    )


def _summary(
    verified: tuple[AgentClaim, ...], unresolved: tuple[AgentClaim, ...]
) -> str:
    if verified:
        lead = verified[0].statement
        extra = (
            f" ({len(verified)} independently verified findings"
            + (f"; {len(unresolved)} unresolved" if unresolved else "")
            + ".)"
        )
        return lead + extra
    if unresolved:
        return (
            "No assertion could be independently verified for this question. "
            f"{len(unresolved)} candidate finding(s) remain unresolved; see below."
        )
    return "No evidence sufficient to answer this question was obtained."


def _cited_evidence_ids(*claim_groups: tuple[AgentClaim, ...]) -> set[str]:
    ids: set[str] = set()
    for group in claim_groups:
        for claim in group:
            ids.update(claim.evidence_ids)
    return ids


def _latest_retrieval(evidence: tuple[AgentEvidence, ...]) -> datetime | None:
    times = [e.retrieved_at for e in evidence]
    return max(times) if times else None


# --------------------------------------------------------------------------
# Terminal rendering
# --------------------------------------------------------------------------


def render_answer(answer: ResearchAnswer) -> str:
    """Render a ResearchAnswer as plain text for the CLI."""
    citation_index = {e.evidence_id: i + 1 for i, e in enumerate(answer.evidence)}
    lines: list[str] = []
    lines.append(f"Research question:\n{answer.question}\n")
    if answer.data_as_of is not None:
        lines.append(f"Data as of: {answer.data_as_of.isoformat()}\n")
    lines.append(f"Summary:\n{answer.summary}\n")

    if answer.verified_claims:
        lines.append("Verified findings:")
        for claim in answer.verified_claims:
            cites = _cite_marks(claim, citation_index)
            value = ""
            if claim.calculation is not None and claim.verification.computed_value is not None:
                value = f"  [recomputed: {claim.verification.computed_value}]"
            lines.append(f"  - {claim.statement} {cites}{value}")
        lines.append("")

    if answer.unresolved_claims:
        lines.append("Unresolved / not independently verified:")
        for claim in answer.unresolved_claims:
            status = claim.verification.status.value
            reason = claim.verification.reason or ""
            lines.append(f"  - [{status}] {claim.statement} — {reason}")
        lines.append("")

    if answer.evidence:
        lines.append("Sources:")
        for eid, idx in citation_index.items():
            ev = next(e for e in answer.evidence if e.evidence_id == eid)
            url = ev.source_url or "(no public URL)"
            published = f", published {ev.published_at.date()}" if ev.published_at else ""
            lines.append(
                f"  [{idx}] {ev.source_title} — {ev.provider}{published} "
                f"(retrieved {ev.retrieved_at.date()}; {ev.freshness_status.value})"
            )
            lines.append(f"      {url}")
        lines.append("")

    if answer.limitations:
        lines.append("Limitations:")
        for item in answer.limitations:
            lines.append(f"  - {item}")
        lines.append("")

    lines.append(f"Verification: {_verification_tally(answer)}")
    lines.append(f"Research run: {answer.run_id}")
    lines.append(f"\n{answer.disclaimer}")
    return "\n".join(lines) + "\n"


def _cite_marks(claim: AgentClaim, citation_index: dict[str, int]) -> str:
    marks = sorted({citation_index[e] for e in claim.evidence_ids if e in citation_index})
    return "".join(f"[{m}]" for m in marks)


def _verification_tally(answer: ResearchAnswer) -> str:
    counts: dict[str, int] = {}
    for claim in (*answer.verified_claims, *answer.unresolved_claims):
        key = claim.verification.status.value
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "no claims"
    order = [s.value for s in AgentVerificationStatus]
    return ", ".join(f"{counts[k]} {k}" for k in order if k in counts)
