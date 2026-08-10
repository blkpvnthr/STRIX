"""Fact -> evidence construction with explicit knowability.

Evidence known_at = max(source availability date from the manifest, every
record-level availability constraint). It can never precede the availability
of the document that carries the record: an ECN approved after its carrying
document became available is knowable only once approved.
"""

from __future__ import annotations

from datetime import date

from strix.canonical import make_id
from strix.engineering.models import (
    AnchoredFact,
    EngineeringEvidence,
    FactPayload,
    HandlingMarking,
    ManifestSource,
    RevisionChangeFact,
)


def known_at_for(payload: FactPayload, source_known_at: date) -> date:
    """Apply the record-level knowability constraints for one payload."""
    if isinstance(payload, RevisionChangeFact):
        return max(source_known_at, payload.approved_date)
    return source_known_at


def build_evidence(
    facts: tuple[AnchoredFact, ...],
    sources_by_artifact: dict[str, ManifestSource],
) -> tuple[EngineeringEvidence, ...]:
    """One evidence record per anchored fact (typed, dated, marked)."""
    evidence: list[EngineeringEvidence] = []
    for fact in facts:
        source = sources_by_artifact[fact.artifact_id]
        known_at = known_at_for(fact.payload, source.known_at)
        handling: tuple[HandlingMarking, ...] = tuple(sorted(source.handling))
        evidence.append(
            EngineeringEvidence(
                evidence_id=make_id(
                    "EV",
                    {
                        "payload": fact.payload.model_dump(),
                        "known_at": known_at,
                        "handling": list(handling),
                        "source_fact_ids": [fact.fact_id],
                    },
                ),
                payload=fact.payload,
                known_at=known_at,
                handling=handling,
                source_fact_ids=(fact.fact_id,),
            )
        )
    return tuple(evidence)
