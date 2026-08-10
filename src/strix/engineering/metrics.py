"""Deterministic compile metrics — the ONLY consumer of evaluation inputs.

Ground truth (expected-model.json) is preserved and hashed like any input,
but it is read exclusively here, AFTER the model and export are fully built.
It never influences fact extraction, candidate construction, verification,
rejection, IDs, model.json, or export_hash.

Fixture precision/recall of 1.0 validates the measurement machinery on
synthetic data; it is NOT evidence of any research precision/recall target.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from pydantic import ValidationError

from strix.engineering.models import (
    CandidateElement,
    CandidateRelationship,
    CandidateStatus,
    CompileMetrics,
    ElementType,
    EngineeringFailureCode,
    EngineeringVerification,
    ExpectedModel,
    GroundTruthMetrics,
    RelationshipType,
    VerifiedModel,
)
from strix.errors import EngineeringSourceError

_QUANTUM = Decimal("0.0001")
_CONFLICT_CODES = frozenset(
    {
        EngineeringFailureCode.REVISION_CONFLICT,
        EngineeringFailureCode.CONFIGURATION_AMBIGUITY,
    }
)


def _ratio(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0.0000"
    value = (Decimal(numerator) / Decimal(denominator)).quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
    return str(value)


def load_expected_model(raw: bytes) -> ExpectedModel:
    """Strictly parse evaluation ground truth (metrics use only)."""
    try:
        payload: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EngineeringSourceError(f"ground truth is unreadable: {exc}") from exc
    try:
        return ExpectedModel.model_validate(payload)
    except ValidationError as exc:
        raise EngineeringSourceError(f"ground truth failed schema validation: {exc}") from exc


def compute_metrics(
    *,
    model: VerifiedModel,
    elements: tuple[CandidateElement, ...],
    relationships: tuple[CandidateRelationship, ...],
    verification: EngineeringVerification,
    resolvable_verified: int,
    expected: ExpectedModel | None,
) -> CompileMetrics:
    """Counts, coverage, and (when ground truth exists) precision/recall."""
    elements_accepted = len(verification.verified_element_ids)
    elements_rejected = len(verification.rejected_element_ids)
    relationships_accepted = len(verification.verified_relationship_ids)
    relationships_rejected = len(verification.rejected_relationship_ids)
    verified_total = elements_accepted + relationships_accepted

    requirement_keys = {
        e.identity_key for e in elements if e.element_type is ElementType.REQUIREMENT
    }
    allocated = {
        r.from_ref
        for r in relationships
        if r.relationship_type is RelationshipType.ALLOCATED_TO
        and r.status is CandidateStatus.VERIFIED
    }
    conflict_count = sum(1 for failure in verification.failures if failure.code in _CONFLICT_CODES)

    ground_truth: GroundTruthMetrics | None = None
    if expected is not None:
        verified_element_keys = {e.identity_key for e in model.elements}
        expected_element_keys = set(expected.elements)
        verified_triples = {
            (r.relationship_type.value, r.from_ref, r.to_ref) for r in model.relationships
        }
        expected_triples = {
            (kind, from_ref, to_ref) for kind, from_ref, to_ref in expected.relationships
        }
        ground_truth = GroundTruthMetrics(
            element_precision=_ratio(
                len(verified_element_keys & expected_element_keys),
                len(verified_element_keys),
            ),
            element_recall=_ratio(
                len(verified_element_keys & expected_element_keys),
                len(expected_element_keys),
            ),
            relationship_precision=_ratio(
                len(verified_triples & expected_triples), len(verified_triples)
            ),
            relationship_recall=_ratio(
                len(verified_triples & expected_triples), len(expected_triples)
            ),
            note=(
                "Synthetic-fixture evaluation validates the measurement "
                "machinery only; it is not evidence of research "
                "precision/recall targets."
            ),
        )

    return CompileMetrics(
        elements_accepted=elements_accepted,
        elements_rejected=elements_rejected,
        relationships_accepted=relationships_accepted,
        relationships_rejected=relationships_rejected,
        conflict_count=conflict_count,
        traceability_coverage=_ratio(resolvable_verified, verified_total),
        allocation_coverage=_ratio(len(requirement_keys & allocated), len(requirement_keys)),
        unsupported_export_count=verified_total - resolvable_verified,
        ground_truth=ground_truth,
    )
