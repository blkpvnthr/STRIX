"""Authoritative neutral-JSON export (model.json) with completeness guard.

The export is computed exclusively from ANALYSIS inputs; evaluation
(ground-truth) hashes and content never appear here — metrics live in the
separate metrics.json. ``run_id`` and ``created_at`` appear nowhere in the
export dict, so identical compilations export identically across runs.
"""

from __future__ import annotations

from typing import Any

from strix.canonical import canonical_hash
from strix.engineering.models import (
    AnchoredFact,
    CandidateStatus,
    EngineeringArtifact,
    EngineeringEvidence,
    EngineeringProjectManifest,
    EngineeringSpec,
    VerifiedModel,
)
from strix.engineering.verifier import VERIFIER_VERSION
from strix.errors import ExportError

EXPORT_FORMAT = "strix-engineering-model"
EXPORT_FORMAT_VERSION = "1.0.0"

_HANDLING_NOTE = (
    "Handling markings are propagated source metadata only. STRIX implements "
    "no CUI, classification, export-control, or CMMC enforcement."
)


def build_export(
    *,
    spec: EngineeringSpec,
    project: EngineeringProjectManifest,
    model: VerifiedModel,
    evidence: tuple[EngineeringEvidence, ...],
    facts: tuple[AnchoredFact, ...],
    artifacts: tuple[EngineeringArtifact, ...],
    parser_versions: dict[str, str],
    schema_versions: dict[str, str],
    analysis_source_hashes: dict[str, str],
) -> dict[str, Any]:
    """Build the export dict; raises ExportError on any completeness breach."""
    evidence_by_id = {e.evidence_id: e for e in evidence}
    facts_by_id = {f.fact_id: f for f in facts}
    artifacts_by_id = {a.artifact_id: a for a in artifacts}

    candidates: list[Any] = [*model.elements, *model.relationships]
    for candidate in candidates:
        if candidate.status is not CandidateStatus.VERIFIED:
            raise ExportError(
                f"export-completeness violation: unverified candidate "
                f"{getattr(candidate, 'element_id', getattr(candidate, 'relationship_id', '?'))} "
                f"reached export build"
            )

    cited_ids: list[str] = []
    for element in model.elements:
        cited_ids.extend(element.evidence_ids)
    for relationship in model.relationships:
        cited_ids.extend(relationship.evidence_ids)
    for rejected in model.rejected:
        cited_ids.extend(rejected.evidence_ids)

    evidence_index: dict[str, Any] = {}
    for evidence_id in cited_ids:
        if evidence_id in evidence_index:
            continue
        cited_evidence = evidence_by_id.get(evidence_id)
        if cited_evidence is None:
            raise ExportError(
                f"export-completeness violation: cited evidence {evidence_id} does not exist"
            )
        citations: list[dict[str, Any]] = []
        for fact_id in cited_evidence.source_fact_ids:
            fact = facts_by_id.get(fact_id)
            if fact is None:
                raise ExportError(
                    f"export-completeness violation: evidence {evidence_id} "
                    f"cites missing fact {fact_id}"
                )
            artifact = artifacts_by_id.get(fact.artifact_id)
            if artifact is None:
                raise ExportError(
                    f"export-completeness violation: fact {fact_id} references "
                    f"missing artifact {fact.artifact_id}"
                )
            citations.append(
                {
                    "fact_id": fact.fact_id,
                    "file": artifact.source_name,
                    "anchor": fact.anchor.render(artifact.source_name),
                    "artifact_hash": artifact.content_hash,
                }
            )
        evidence_index[evidence_id] = {
            "payload": cited_evidence.payload.model_dump(),
            "known_at": cited_evidence.known_at,
            "handling": list(cited_evidence.handling),
            "citations": citations,
        }

    return {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_FORMAT_VERSION,
        "project_id": spec.project_id,
        "as_of_date": spec.as_of_date,
        "provenance": {
            "pipeline_version": spec.pipeline_version,
            "verifier_version": VERIFIER_VERSION,
            "parser_versions": dict(sorted(parser_versions.items())),
            "schema_versions": dict(sorted(schema_versions.items())),
            "analysis_source_hashes": dict(sorted(analysis_source_hashes.items())),
            "handling_note": _HANDLING_NOTE,
            "synthetic_note": project.notice,
        },
        "verified_model": {
            "elements": [
                {
                    "element_id": e.element_id,
                    "element_type": e.element_type,
                    "identity_key": e.identity_key,
                    "name": e.name,
                    "revision": e.revision,
                    "properties": [p.model_dump() for p in e.properties],
                    "handling": list(e.handling),
                    "evidence_ids": list(e.evidence_ids),
                }
                for e in sorted(model.elements, key=lambda e: e.element_id)
            ],
            "relationships": [
                {
                    "relationship_id": r.relationship_id,
                    "relationship_type": r.relationship_type,
                    "from_ref": r.from_ref,
                    "to_ref": r.to_ref,
                    "attributes": r.attributes.model_dump(),
                    "handling": list(r.handling),
                    "evidence_ids": list(r.evidence_ids),
                }
                for r in sorted(model.relationships, key=lambda r: r.relationship_id)
            ],
        },
        "quarantine": {
            "rejected_candidates": [
                rejected.model_dump()
                for rejected in sorted(model.rejected, key=lambda r: r.candidate_id)
            ]
        },
        "evidence": evidence_index,
    }


def export_hash(export: dict[str, Any]) -> str:
    """Canonical hash of the export dict (never of the pretty file bytes)."""
    return canonical_hash(export)
