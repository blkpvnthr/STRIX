"""Dependency-aware admission on the live path (R-N1 / ``A_ind`` projection).

The per-claim verifier confirms a claim's value against its cited sources, but it does not ask
whether those sources are *independent*. Duplicated or shared-origin evidence can create the
appearance of corroboration without adding independent support. This module applies the
dependency engine's **content-hash origin canonicalization** (the same principle as
:func:`strix.evidence_graph.dependency.estimate_dependence`, which keys origins by
``content_hash``) to a claim's cited, preserved evidence — faithfully computable from
:class:`~strix.agent.models.AgentEvidence` without the full evidence-graph reconstruction.

It is additive: it classifies a claim's corroboration (independent / single-sourced /
artificially corroborated) and surfaces it so an answer never presents duplicated evidence as
independent confirmation. It does not drop a claim the recompute verifier already confirmed
against its source — a single-sourced claim is verified, just not independently corroborated.
"""

from __future__ import annotations

from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import AgentClaim, IndependenceVerdict

__all__ = ["assess_claim_independence"]


def assess_claim_independence(
    claim: AgentClaim, collector: EvidenceCollector
) -> IndependenceVerdict:
    """Classify the independence of *claim*'s cited evidence by canonical origin."""
    resolved = [
        e for eid in claim.evidence_ids if (e := collector.evidence(eid)) is not None
    ]
    cited = len(resolved)
    # Canonicalize origins by content hash: distinct documents, regardless of how many
    # citations (or providers/mirror sites) reference them.
    origins = {e.content_hash for e in resolved}
    providers = {e.provider for e in resolved}
    distinct_origins = len(origins)
    artificial = cited > 1 and distinct_origins <= 1
    single_sourced = distinct_origins <= 1
    if artificial:
        detail = (
            f"{cited} citations collapse to {distinct_origins} distinct origin "
            "(shared content hash) — not independent corroboration"
        )
    elif single_sourced:
        detail = "single-sourced: verified against one origin, not independently corroborated"
    else:
        detail = f"{distinct_origins} independent origins corroborate the claim"
    return IndependenceVerdict(
        cited_count=cited,
        distinct_origin_count=distinct_origins,
        distinct_provider_count=len(providers),
        artificial_corroboration=artificial,
        single_sourced=single_sourced,
        detail=detail,
    )
