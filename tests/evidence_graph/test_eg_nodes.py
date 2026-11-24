"""Tests for the typed node/edge foundation of the R1 evidence graph.

Covers enum membership, deterministic content-derived identity (stable under
re-construction, changing when a semantic field changes), immutability, the
``float``-rejection discipline on Decimal fields, and the plain-``str``
referential contract on edges and assertions.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.errors import StrixError
from strix.evidence_graph.nodes import (
    AdmissionOutcome,
    Assertion,
    CandidateClaim,
    EvidenceGraphError,
    PredicateName,
    PredicateResult,
    PredicateStatus,
    RelationshipKind,
    SourceObservation,
    TemporalMode,
    VerificationOutcome,
    VerificationPolicy,
    make_candidate_claim,
    make_edge,
    make_source_observation,
    make_verification_policy,
)

AT = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
PUB = datetime(2024, 2, 1, 0, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


def test_relationship_kind_members() -> None:
    assert {m.value for m in RelationshipKind} == {
        "derived_from",
        "extracted_from",
        "calculated_from",
        "supported_by",
        "contradicted_by",
        "attributed_to",
        "verified_by",
        "supersedes",
        "depends_on",
        "satisfies_requirement",
        "authorized_by",
        "resulted_in",
        "reconciled_with",
    }
    assert len(RelationshipKind) == 13


def test_predicate_name_members() -> None:
    assert {m.value for m in PredicateName} == {
        "integrity",
        "type_temporal",
        "provenance",
        "derivation",
        "support",
    }
    assert len(PredicateName) == 5


def test_predicate_status_members() -> None:
    assert {m.value for m in PredicateStatus} == {
        "pass",
        "fail",
        "unknown",
        "not_applicable",
    }
    assert len(PredicateStatus) == 4


def test_admission_outcome_members() -> None:
    assert {m.value for m in AdmissionOutcome} == {"admitted", "rejected", "abstained"}
    assert len(AdmissionOutcome) == 3


def test_verification_outcome_members() -> None:
    assert {m.value for m in VerificationOutcome} == {
        "verified",
        "contradicted",
        "insufficient_evidence",
        "unverifiable",
        "stale",
        "invalid_evidence",
        "integrity_failure",
        "unresolved_conflict",
    }
    assert len(VerificationOutcome) == 8


def test_temporal_mode_members() -> None:
    assert {m.value for m in TemporalMode} == {"point_in_time", "retrospective"}
    assert len(TemporalMode) == 2


# --------------------------------------------------------------------------
# Exception
# --------------------------------------------------------------------------


def test_evidence_graph_error_is_strix_error() -> None:
    assert issubclass(EvidenceGraphError, StrixError)


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def _observation(**overrides: object) -> SourceObservation:
    kwargs: dict[str, object] = {
        "subject_id": "SUBJ-1",
        "concept": "revenue",
        "value": Decimal("84000000"),
        "unit": "USD",
        "observation_period": "FY2023",
        "observed_at": AT,
        "source_artifact_id": "ART-abc",
        "source_locator": "/facts/0",
    }
    kwargs.update(overrides)
    return make_source_observation(**kwargs)  # type: ignore[arg-type]


def _candidate(**overrides: object) -> CandidateClaim:
    assertion = Assertion(
        metric="operating_margin",
        asserted_value=Decimal("0.25"),
        unit="ratio",
        evidence_id="EV-1",
    )
    kwargs: dict[str, object] = {
        "subject_id": "SUBJ-1",
        "claim_type": "profitability_change",
        "statement": "Operating margin increased.",
        "evidence_ids": ("EV-1",),
        "assertions": (assertion,),
    }
    kwargs.update(overrides)
    return make_candidate_claim(**kwargs)  # type: ignore[arg-type]


def _policy(**overrides: object) -> VerificationPolicy:
    kwargs: dict[str, object] = {
        "version": "1.0.0",
        "mandatory_predicates": (PredicateName.INTEGRITY, PredicateName.PROVENANCE),
        "temporal_mode": TemporalMode.POINT_IN_TIME,
        "absolute_tolerance": Decimal("0.01"),
        "relative_tolerance": Decimal("0.001"),
    }
    kwargs.update(overrides)
    return make_verification_policy(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Identity: prefixes + determinism
# --------------------------------------------------------------------------


def test_factory_id_prefixes() -> None:
    assert _observation().observation_id.startswith("OBS-")
    assert _candidate().candidate_claim_id.startswith("CC-")
    assert make_edge(RelationshipKind.DERIVED_FROM, "A", "B").edge_id.startswith("EDGE-")
    assert _policy().policy_id.startswith("VPOL-")


def test_identity_is_deterministic() -> None:
    assert _observation().observation_id == _observation().observation_id
    assert _candidate().candidate_claim_id == _candidate().candidate_claim_id
    assert (
        make_edge(RelationshipKind.DERIVED_FROM, "A", "B").edge_id
        == make_edge(RelationshipKind.DERIVED_FROM, "A", "B").edge_id
    )
    assert _policy().policy_id == _policy().policy_id


def test_observation_identity_changes_with_semantic_fields() -> None:
    base = _observation().observation_id
    assert _observation(value=Decimal("84000001")).observation_id != base
    assert _observation(concept="operating_income").observation_id != base
    assert _observation(subject_id="SUBJ-2").observation_id != base
    assert _observation(observation_period="FY2022").observation_id != base
    assert _observation(source_locator="/facts/1").observation_id != base


def test_observation_timestamps_are_part_of_identity() -> None:
    base = _observation().observation_id
    assert _observation(observed_at=PUB).observation_id != base
    assert _observation(publication_at=PUB).observation_id != base
    assert _observation(available_at=PUB).observation_id != base


def test_decimal_normalization_is_identity_stable() -> None:
    # 84000000 == 8.4E+7 == 84000000.00 under canonical Decimal encoding.
    a = _observation(value=Decimal("84000000")).observation_id
    b = _observation(value=Decimal("8.4E+7")).observation_id
    c = _observation(value=Decimal("84000000.00")).observation_id
    assert a == b == c


def test_candidate_identity_changes_with_semantic_fields() -> None:
    base = _candidate().candidate_claim_id
    assert _candidate(statement="Operating margin decreased.").candidate_claim_id != base
    assert _candidate(claim_type="other").candidate_claim_id != base
    assert _candidate(subject_id="SUBJ-2").candidate_claim_id != base
    assert _candidate(evidence_ids=("EV-2",)).candidate_claim_id != base
    assert _candidate(knowledge_cutoff=date(2023, 12, 31)).candidate_claim_id != base
    other = Assertion(
        metric="operating_margin",
        asserted_value=Decimal("0.26"),
        unit="ratio",
        evidence_id="EV-1",
    )
    assert _candidate(assertions=(other,)).candidate_claim_id != base


def test_edge_identity_changes_with_semantic_fields() -> None:
    base = make_edge(RelationshipKind.DERIVED_FROM, "A", "B").edge_id
    assert make_edge(RelationshipKind.SUPPORTED_BY, "A", "B").edge_id != base
    assert make_edge(RelationshipKind.DERIVED_FROM, "X", "B").edge_id != base
    assert make_edge(RelationshipKind.DERIVED_FROM, "A", "Y").edge_id != base
    assert make_edge(RelationshipKind.DERIVED_FROM, "A", "B", ("EV-1",)).edge_id != base


def test_policy_identity_changes_with_semantic_fields() -> None:
    base = _policy().policy_id
    assert _policy(version="2.0.0").policy_id != base
    assert _policy(temporal_mode=TemporalMode.RETROSPECTIVE).policy_id != base
    assert _policy(absolute_tolerance=Decimal("0.02")).policy_id != base
    assert _policy(relative_tolerance=Decimal("0.002")).policy_id != base
    assert _policy(mandatory_predicates=(PredicateName.SUPPORT,)).policy_id != base
    assert _policy(freshness_max_age_seconds=3600).policy_id != base
    assert _policy(require_source_independence=True).policy_id != base


# --------------------------------------------------------------------------
# Immutability + float rejection
# --------------------------------------------------------------------------


def test_models_are_frozen() -> None:
    obs = _observation()
    with pytest.raises(ValidationError):
        obs.subject_id = "SUBJ-9"  # type: ignore[misc]
    edge = make_edge(RelationshipKind.DERIVED_FROM, "A", "B")
    with pytest.raises(ValidationError):
        edge.source_id = "X"  # type: ignore[misc]


def test_decimal_fields_reject_float() -> None:
    with pytest.raises(ValidationError):
        _observation(value=84000000.0)
    with pytest.raises(ValidationError):
        Assertion(
            metric="m",
            asserted_value=0.25,  # type: ignore[arg-type]
            unit="ratio",
            evidence_id="EV-1",
        )
    with pytest.raises(ValidationError):
        _policy(absolute_tolerance=0.01)


# --------------------------------------------------------------------------
# Referential contracts: plain str ids
# --------------------------------------------------------------------------


def test_edge_referential_fields_are_plain_str() -> None:
    edge = make_edge(RelationshipKind.DEPENDS_ON, "SRC-1", "TGT-1", ("EV-1", "EV-2"))
    assert isinstance(edge.source_id, str)
    assert isinstance(edge.target_id, str)
    assert edge.source_id == "SRC-1"
    assert edge.target_id == "TGT-1"
    assert edge.evidence_ids == ("EV-1", "EV-2")
    assert edge.note is None


def test_assertion_referential_field_is_plain_str() -> None:
    assertion = Assertion(
        metric="operating_margin",
        asserted_value=Decimal("0.25"),
        unit="ratio",
        evidence_id="EV-1",
    )
    assert isinstance(assertion.evidence_id, str)
    assert assertion.evidence_id == "EV-1"


# --------------------------------------------------------------------------
# PredicateResult + defaults
# --------------------------------------------------------------------------


def test_predicate_result_defaults() -> None:
    result = PredicateResult(predicate=PredicateName.INTEGRITY, status=PredicateStatus.PASS)
    assert result.reason_codes == ()
    assert result.detail == ""


def test_candidate_claim_optional_cutoff_default() -> None:
    assert _candidate().knowledge_cutoff is None


def test_verification_policy_optional_defaults() -> None:
    policy = _policy()
    assert policy.freshness_max_age_seconds is None
    assert policy.require_source_independence is False


def test_observation_optional_timestamp_defaults() -> None:
    obs = _observation()
    assert obs.publication_at is None
    assert obs.available_at is None
