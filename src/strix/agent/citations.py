"""Citation resolution: map a claim's cited references to preserved evidence.

The hosted web-search tool gives the model provider-native citation handles
(e.g. ``turn874423news19``). When the model echoes one of those as a claim's
``evidence_id``, it is not a STRIX evidence id, so verification would reject it
as "cites unknown evidence: turn874423news19" and that raw handle would leak
into the user-facing answer (spec §8, observed in RUN-20261123-002).

This module runs *before* verification. For each claim it rewrites
``evidence_ids`` so that:

- a real evidence id is kept;
- a known alias (a web handle or URL the evidence collector preserved) is
  mapped to its canonical evidence id;
- an unresolvable handle is dropped, never surfaced.

It returns the rewritten claims plus a per-claim record of dropped handles so
the orchestrator can qualify the attribution in the limitations rather than
present an unresolved reference as evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.models import AgentClaim


@dataclass(frozen=True)
class CitationResolution:
    """Outcome of resolving one run's claim citations."""

    claims: tuple[AgentClaim, ...]
    #: claim_id -> the unresolvable handles that were stripped from it.
    dropped: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def had_unresolved(self) -> bool:
        return any(self.dropped.values())


def resolve_claim_citations(
    claims: tuple[AgentClaim, ...], collector: EvidenceCollector
) -> CitationResolution:
    """Rewrite each claim's ``evidence_ids`` to canonical, resolvable ids.

    Order within a claim is preserved and duplicates (after mapping) collapse to
    the first occurrence. A dangling handle is removed and recorded, never kept.
    """
    out: list[AgentClaim] = []
    dropped: dict[str, tuple[str, ...]] = {}
    for claim in claims:
        resolved: list[str] = []
        missing: list[str] = []
        for ref in claim.evidence_ids:
            canonical = collector.resolve(ref)
            if canonical is None:
                missing.append(ref)
            elif canonical not in resolved:
                resolved.append(canonical)
        if tuple(resolved) != claim.evidence_ids:
            claim = claim.model_copy(update={"evidence_ids": tuple(resolved)})
        if missing:
            dropped[claim.claim_id] = tuple(missing)
        out.append(claim)
    return CitationResolution(claims=tuple(out), dropped=dropped)
