"""Citation resolution tests (spec §8).

Regression anchor: RUN-20261123-002 produced an unresolved finding that cited
``turn874423news19`` — a raw web-search handle — which surfaced to the user as
"cites unknown evidence: turn874423news19". After the fix, such a handle either
resolves to a preserved source (when aliased) or is stripped and qualified, and
the raw handle never appears in the rendered answer.
"""

from __future__ import annotations

from datetime import UTC, datetime

from strix.agent.citations import resolve_claim_citations
from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import AgentClaim, AgentClaimType, SourceKind
from strix.agent.response_builder import render_answer
from strix.agent.verifier import verify_claims

_NOW = datetime(2026, 11, 23, 1, 5, tzinfo=UTC)
_HANDLE = "turn874423news19"


def _web_evidence(collector: EvidenceCollector, *, excerpt: str | None = None):
    return collector.register(
        source_type=SourceKind.WEB_SEARCH_RESULT,
        provider="Web search",
        source_title="AP: AI-stock sell-off pulls S&P 500 down 3.7%",
        raw=b'{"url": "https://apnews.com/article/markets", "title": "AP markets"}',
        retrieved_at=_NOW,
        source_url="https://apnews.com/article/markets",
        excerpt=excerpt,
    )


def test_alias_resolves_to_canonical_evidence_id() -> None:
    collector = EvidenceCollector()
    ev = _web_evidence(collector)
    collector.register_alias(_HANDLE, ev.evidence_id)
    assert collector.resolve(_HANDLE) == ev.evidence_id
    assert collector.resolve(ev.evidence_id) == ev.evidence_id
    assert collector.resolve("totally-unknown") is None


def test_alias_never_shadows_a_real_evidence_id() -> None:
    collector = EvidenceCollector()
    ev = _web_evidence(collector)
    # Try to alias an existing evidence id to a different target — must no-op.
    other = collector.register(
        source_type=SourceKind.WEB_SEARCH_RESULT,
        provider="Web search",
        source_title="other",
        raw=b"other-bytes",
        retrieved_at=_NOW,
        source_url="https://example.com/other",
    )
    collector.register_alias(ev.evidence_id, other.evidence_id)
    assert collector.resolve(ev.evidence_id) == ev.evidence_id  # unchanged


def test_known_handle_is_rewritten_to_evidence_id() -> None:
    collector = EvidenceCollector()
    ev = _web_evidence(collector)
    collector.register_alias(_HANDLE, ev.evidence_id)
    claim = AgentClaim(
        claim_id="CL-ap",
        claim_type=AgentClaimType.ATTRIBUTED_STATEMENT,
        statement="An AP report described an AI-stock sell-off.",
        evidence_ids=(_HANDLE,),
        attributed_to="Associated Press",
    )
    resolution = resolve_claim_citations((claim,), collector)
    assert resolution.claims[0].evidence_ids == (ev.evidence_id,)
    assert resolution.had_unresolved is False


def test_dangling_handle_is_stripped_and_recorded() -> None:
    collector = EvidenceCollector()
    # No evidence / no alias registered for the handle at all.
    claim = AgentClaim(
        claim_id="CL-ap",
        claim_type=AgentClaimType.ATTRIBUTED_STATEMENT,
        statement="An AP report described an AI-stock sell-off.",
        evidence_ids=(_HANDLE,),
        attributed_to="Associated Press",
    )
    resolution = resolve_claim_citations((claim,), collector)
    assert resolution.claims[0].evidence_ids == ()
    assert resolution.dropped["CL-ap"] == (_HANDLE,)
    assert resolution.had_unresolved is True


def test_dangling_handle_never_reaches_rendered_answer() -> None:
    """The exact RUN-002 failure must not recur: the raw handle must not leak."""
    collector = EvidenceCollector()
    claim = AgentClaim(
        claim_id="CL-ap",
        claim_type=AgentClaimType.ATTRIBUTED_STATEMENT,
        statement="An AP report described an AI-stock sell-off that pulled the S&P 500 down 3.7%.",
        evidence_ids=(_HANDLE,),
        attributed_to="Associated Press",
    )
    resolution = resolve_claim_citations((claim,), collector)
    verified = verify_claims(resolution.claims, collector, now=_NOW)
    # It stays unresolved (no preserved source), but with a clean reason.
    assert len(verified) == 1
    reason = verified[0].verification.reason or ""
    assert _HANDLE not in reason

    from strix.agent.response_builder import build_answer

    answer = build_answer(
        run_id="RUN-TEST",
        question="should i expect bearish or bullish conditions?",
        verified_claims=(),
        unresolved_claims=verified,
        collector=collector,
        limitations=(),
        now=_NOW,
    )
    rendered = render_answer(answer)
    assert _HANDLE not in rendered
    # And the answer.json-equivalent dump likewise carries no raw handle.
    assert _HANDLE not in answer.model_dump_json()


def test_resolved_attribution_can_be_verified_when_excerpt_matches() -> None:
    """A resolved web source whose excerpt contains the attributed text verifies."""
    collector = EvidenceCollector()
    excerpt = "The Associated Press reported an AI-stock sell-off on November 20, 2026."
    ev = _web_evidence(collector, excerpt=excerpt)
    collector.register_alias(_HANDLE, ev.evidence_id)
    claim = AgentClaim(
        claim_id="CL-ap",
        claim_type=AgentClaimType.ATTRIBUTED_STATEMENT,
        statement="AI-stock sell-off",
        evidence_ids=(_HANDLE,),
        attributed_to="The Associated Press reported an AI-stock sell-off",
    )
    resolution = resolve_claim_citations((claim,), collector)
    verified = verify_claims(resolution.claims, collector, now=_NOW)
    from strix.agent.models import AgentVerificationStatus

    assert verified[0].verification.status is AgentVerificationStatus.VERIFIED
