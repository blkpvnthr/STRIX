"""Deterministic assembly and rendering of the final research answer.

The answer is built from structured, already-verified claims — not from free
model prose — so it cannot introduce an unsupported assertion. Verified claims
render their statements with a bracketed citation index; unresolved claims are
disclosed separately with their verdicts, never as facts.
"""

from __future__ import annotations

from datetime import datetime

from strix.agent.documentation import build_supporting_documentation
from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import (
    AgentClaim,
    AgentClaimType,
    AgentEvidence,
    AgentVerificationStatus,
    ConclusionVerification,
    EpistemicClass,
    ResearchAnswer,
    ResearchResponse,
    SupportingFact,
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
    conclusion_verification: ConclusionVerification | None = None,
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
        conclusion_verification=conclusion_verification,
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
# Conversational response assembly (spec §9)
# --------------------------------------------------------------------------


def build_response(
    *,
    run_id: str,
    question: object,  # ResearchQuestion (imported lazily to avoid a cycle)
    answer: ResearchAnswer,
    draft: object,  # SynthesisDraft
    diagnostics: dict[str, str],
) -> ResearchResponse:
    """Assemble the structured conversational response from the verified answer
    and the synthesis draft, keeping epistemic classes separate from verdicts."""
    from strix.agent.question import ResearchQuestion
    from strix.agent.synthesis import SynthesisDraft

    assert isinstance(question, ResearchQuestion)
    assert isinstance(draft, SynthesisDraft)

    supporting = tuple(_to_supporting_fact(c) for c in answer.verified_claims)
    contradictory = tuple(
        _to_unresolved_fact(c)
        for c in answer.unresolved_claims
        if c.verification.status is AgentVerificationStatus.CONTRADICTED
    )
    unresolved = tuple(
        _to_unresolved_fact(c)
        for c in answer.unresolved_claims
        if c.verification.status is not AgentVerificationStatus.CONTRADICTED
    )

    merged_diagnostics = {**draft.diagnostics, **diagnostics}

    return ResearchResponse(
        run_id=run_id,
        question=answer.question,
        question_intent=question.intent.value,
        direct_answer=draft.direct_answer,
        analysis=draft.analysis,
        market_assessment=draft.market_assessment,
        supporting_facts=supporting,
        analytical_inferences=draft.analytical_inferences,
        conditional_scenarios=draft.conditional_scenarios,
        contradictory_evidence=contradictory,
        unresolved_findings=unresolved,
        monitoring_indicators=draft.monitoring_indicators,
        sources=answer.evidence,
        limitations=answer.limitations,
        diagnostics=merged_diagnostics,
        verified_answer=answer,
    )


def _to_supporting_fact(claim: AgentClaim) -> SupportingFact:
    epistemic = (
        EpistemicClass.ATTRIBUTED_REPORT
        if claim.claim_type is AgentClaimType.ATTRIBUTED_STATEMENT
        else EpistemicClass.VERIFIED_FACT
    )
    return SupportingFact(
        claim_id=claim.claim_id,
        statement=claim.statement,
        epistemic_class=epistemic,
        evidence_ids=claim.evidence_ids,
        computed_value=claim.verification.computed_value,
        method=claim.verification.method,
    )


def _to_unresolved_fact(claim: AgentClaim) -> SupportingFact:
    reason = claim.verification.reason
    statement = claim.statement if not reason else f"{claim.statement} ({reason})"
    return SupportingFact(
        claim_id=claim.claim_id,
        statement=statement,
        epistemic_class=EpistemicClass.UNRESOLVED,
        evidence_ids=claim.evidence_ids,
    )


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


def render_response(response: ResearchResponse) -> str:
    """Render a conversational ResearchResponse for the CLI (spec §11 ordering)."""
    answer = response.verified_answer
    # The single §7/§15 supporting-documentation contract the API and frontend
    # also render: numbering and references come from it, never recomputed here.
    documentation = build_supporting_documentation(response)
    citation_index = {r.evidence_id: r.number for r in documentation.references}
    lines: list[str] = []
    lines.append(f"Question:\n{response.question}\n")
    lines.append(f"Answer:\n{response.direct_answer}\n")

    ma = response.market_assessment
    if ma is not None:
        lines.append(
            f"Market assessment: {ma.stance.value.upper()} "
            f"({ma.horizon}; evidence {ma.evidence_strength.value})"
        )
        for ind in ma.supporting_indicators:
            lines.append(f"  + {ind.label}: {ind.detail}")
        for ind in ma.contradictory_indicators:
            lines.append(f"  - {ind.label}: {ind.detail}")
        if ma.missing_indicators:
            lines.append(f"  missing: {', '.join(ma.missing_indicators)}")
        if ma.invalidation_conditions:
            lines.append("  would be invalidated if: " + "; ".join(ma.invalidation_conditions))
        lines.append("")

    if response.analysis:
        lines.append(f"Analysis:\n{response.analysis}\n")

    if response.conditional_scenarios:
        lines.append("Conditional scenarios:")
        for s in response.conditional_scenarios:
            lines.append(f"  - If {s.condition}: {s.outcome}")
        lines.append("")

    if response.analytical_inferences:
        lines.append("Analytical inferences (interpretation, not independently verified):")
        for inf in response.analytical_inferences:
            tag = inf.epistemic_class.value
            unc = f" [{inf.uncertainty}]" if inf.uncertainty else ""
            lines.append(f"  - ({tag}) {inf.statement}{unc}")
        lines.append("")

    if response.supporting_facts:
        lines.append("Independently verified findings:")
        for fact in response.supporting_facts:
            marks = sorted({citation_index[e] for e in fact.evidence_ids if e in citation_index})
            cites = "".join(f"[{m}]" for m in marks)
            value = f"  [recomputed: {fact.computed_value}]" if fact.computed_value else ""
            lines.append(f"  - {fact.statement} {cites}{value}")
        lines.append("")

    if response.contradictory_evidence:
        lines.append("Contradictory / contradicted evidence:")
        for fact in response.contradictory_evidence:
            lines.append(f"  - {fact.statement}")
        lines.append("")

    if response.unresolved_findings:
        lines.append("Unresolved (not independently verified):")
        for fact in response.unresolved_findings:
            lines.append(f"  - {fact.statement}")
        lines.append("")

    if documentation.references:
        lines.append("Sources:")
        for ref in documentation.references:
            header = f"  [{ref.number}] {ref.title} — {ref.provider}"
            if ref.published_date:
                header += f" ({ref.published_date})"
            lines.append(header)
            if ref.authors:
                lines.append(f"      {', '.join(ref.authors)}")
            locator = []
            if ref.pages:
                locator.append(f"pp. {ref.pages}")
            if ref.sections:
                locator.append(ref.sections)
            if locator:
                lines.append(f"      {', '.join(locator)}")
            if ref.doi:
                lines.append(f"      DOI: {ref.doi}")
            lines.append(f"      {ref.url or '(no public URL)'}")
            if ref.pdf_url:
                lines.append(f"      PDF: {ref.pdf_url}")
        lines.append("")

    if response.monitoring_indicators:
        lines.append("What to monitor:")
        for mon in response.monitoring_indicators:
            lines.append(f"  - {mon.label}: {mon.rationale}")
        lines.append("")

    if response.limitations:
        lines.append("Limitations:")
        for item in response.limitations:
            lines.append(f"  - {item}")
        lines.append("")

    if answer.data_as_of is not None:
        lines.append(f"Data as of: {answer.data_as_of.isoformat()}")
    lines.append(f"Research run: {response.run_id}")
    lines.append(f"\n{answer.disclaimer}")
    return "\n".join(lines) + "\n"
