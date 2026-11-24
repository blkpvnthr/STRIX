"""Tests for the five admission predicates and their composition (R1 §10).

Each predicate is exercised on both a PASS and a FAIL path with
hand-constructed graphs; temporal point-in-time vs. retrospective behaviour,
re-derivation tamper detection, the NOT_APPLICABLE branch, and the composition
rules (ADMITTED / REJECTED / ABSTAINED, NOT_APPLICABLE counting as satisfied,
non-mandatory results not blocking) are covered explicitly, plus determinism.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.nodes import (
    AdmissionOutcome,
    Assertion,
    CandidateClaim,
    PredicateName,
    PredicateStatus,
    SourceObservation,
    TemporalMode,
    VerificationOutcome,
    VerificationPolicy,
    make_candidate_claim,
    make_source_observation,
    make_verification_policy,
)
from strix.evidence_graph.predicates import (
    AdmissionDecision,
    admit,
    derivation,
    integrity,
    provenance,
    support,
    type_temporal,
)
from strix.models import (
    CalculationResult,
    Concept,
    Evidence,
    EvidenceStatus,
    EvidenceType,
    Metric,
    SourceArtifact,
    SourceFact,
    SourceType,
    Unit,
    ValidationStatus,
)

KNOWN = datetime(2024, 1, 1, tzinfo=UTC)
CUTOFF = date(2024, 6, 30)
HEX64 = "a" * 64


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def _artifact(artifact_id: str = "ART-1") -> SourceArtifact:
    return SourceArtifact(
        artifact_id=artifact_id,
        source_type=SourceType.SYNTHETIC_FIXTURE,
        source_name="companyfacts.json",
        source_version="v1",
        content_hash=HEX64,
        known_at=KNOWN,
        local_path="raw/companyfacts.json",
        byte_size=100,
    )


def _fact(fact_id: str = "FACT-1", artifact_id: str = "ART-1") -> SourceFact:
    return SourceFact(
        fact_id=fact_id,
        subject_id="SUBJ-1",
        concept=Concept.OPERATING_INCOME,
        value=Decimal("25"),
        unit=Unit.USD,
        observation_period="FY2023",
        known_at=KNOWN,
        source_artifact_id=artifact_id,
        source_locator="/facts/0",
        validation_status=ValidationStatus.VALID,
    )


def _calc(
    calculation_id: str = "CALC-1",
    value: Decimal = Decimal("0.25"),
    input_fact_ids: tuple[str, ...] = ("FACT-1",),
) -> CalculationResult:
    return CalculationResult(
        calculation_id=calculation_id,
        calculation_name=Metric.OPERATING_MARGIN,
        calculation_version="v1",
        subject_id="SUBJ-1",
        value=value,
        unit=Unit.RATIO,
        observation_period="FY2023",
        input_fact_ids=input_fact_ids,
    )


def _evidence(
    evidence_id: str = "EV-1",
    value: Decimal = Decimal("0.25"),
    unit: Unit = Unit.RATIO,
    subject_id: str = "SUBJ-1",
    calculation_id: str = "CALC-1",
    source_fact_ids: tuple[str, ...] = ("FACT-1",),
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        subject_id=subject_id,
        evidence_type=EvidenceType.CALCULATION,
        metric=Metric.OPERATING_MARGIN,
        value=value,
        display_value=str(value),
        unit=unit,
        observation_period="FY2023",
        calculation_id=calculation_id,
        source_fact_ids=source_fact_ids,
        known_at=KNOWN,
        status=EvidenceStatus.UNVERIFIED,
    )


def _observation(
    *,
    unit: str = "ratio",
    subject_id: str = "SUBJ-1",
    value: Decimal = Decimal("0.25"),
    available_at: datetime | None = KNOWN,
    publication_at: datetime | None = None,
    source_artifact_id: str = "ART-1",
) -> SourceObservation:
    return make_source_observation(
        subject_id=subject_id,
        concept="operating_margin",
        value=value,
        unit=unit,
        observation_period="FY2023",
        observed_at=KNOWN,
        available_at=available_at,
        publication_at=publication_at,
        source_artifact_id=source_artifact_id,
        source_locator="/facts/0",
    )


def _assertion(
    evidence_id: str,
    *,
    value: Decimal = Decimal("0.25"),
    unit: str = "ratio",
) -> Assertion:
    return Assertion(
        metric="operating_margin",
        asserted_value=value,
        unit=unit,
        evidence_id=evidence_id,
    )


def _claim(
    *,
    evidence_ids: tuple[str, ...],
    assertions: tuple[Assertion, ...],
    knowledge_cutoff: date | None = None,
) -> CandidateClaim:
    return make_candidate_claim(
        subject_id="SUBJ-1",
        claim_type="profitability_change",
        statement="Operating margin was 25%.",
        evidence_ids=evidence_ids,
        assertions=assertions,
        knowledge_cutoff=knowledge_cutoff,
    )


def _policy(
    *,
    mandatory: tuple[PredicateName, ...] = (),
    temporal_mode: TemporalMode = TemporalMode.POINT_IN_TIME,
    freshness_max_age_seconds: int | None = None,
    require_source_independence: bool = False,
) -> VerificationPolicy:
    return make_verification_policy(
        version="1.0.0",
        mandatory_predicates=mandatory,
        temporal_mode=temporal_mode,
        absolute_tolerance=Decimal("0.0001"),
        relative_tolerance=Decimal("0.0001"),
        freshness_max_age_seconds=freshness_max_age_seconds,
        require_source_independence=require_source_independence,
    )


def _full_evidence_graph(
    *,
    calc_value: Decimal = Decimal("0.25"),
    evidence_value: Decimal = Decimal("0.25"),
) -> EvidenceGraph:
    g = EvidenceGraph()
    g.add_node(_artifact())
    g.add_node(_fact())
    g.add_node(_calc(value=calc_value))
    g.add_node(_evidence(value=evidence_value))
    return g


# --------------------------------------------------------------------------
# integrity
# --------------------------------------------------------------------------


def test_integrity_pass() -> None:
    g = _full_evidence_graph()
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    result = integrity(g, claim, _policy())
    assert result.predicate is PredicateName.INTEGRITY
    assert result.status is PredicateStatus.PASS


def test_integrity_fail_missing_evidence_node() -> None:
    g = _full_evidence_graph()
    claim = _claim(evidence_ids=("EV-missing",), assertions=(_assertion("EV-missing"),))
    result = integrity(g, claim, _policy())
    assert result.status is PredicateStatus.FAIL
    assert "evidence_node_missing" in result.reason_codes


def test_integrity_fail_broken_upstream_link() -> None:
    g = EvidenceGraph()
    g.add_node(_evidence(calculation_id="CALC-missing", source_fact_ids=()))
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    result = integrity(g, claim, _policy())
    assert result.status is PredicateStatus.FAIL
    assert "broken_upstream_link" in result.reason_codes


def test_integrity_fail_tampered_observation() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    obs = _observation()
    tampered = obs.model_copy(update={"value": Decimal("999")})
    g.add_node(tampered)
    claim = _claim(
        evidence_ids=(obs.observation_id,),
        assertions=(_assertion(obs.observation_id, value=Decimal("999")),),
    )
    result = integrity(g, claim, _policy())
    assert result.status is PredicateStatus.FAIL
    assert "content_hash_mismatch" in result.reason_codes


def test_integrity_unknown_when_no_evidence_referenced() -> None:
    g = EvidenceGraph()
    claim = _claim(evidence_ids=(), assertions=())
    result = integrity(g, claim, _policy())
    assert result.status is PredicateStatus.UNKNOWN


# --------------------------------------------------------------------------
# type_temporal
# --------------------------------------------------------------------------


def test_type_temporal_pass() -> None:
    g = _full_evidence_graph()
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    result = type_temporal(g, claim, _policy())
    assert result.status is PredicateStatus.PASS


def test_type_temporal_unit_mismatch_fail() -> None:
    g = _full_evidence_graph()
    claim = _claim(
        evidence_ids=("EV-1",),
        assertions=(_assertion("EV-1", unit="USD"),),
    )
    result = type_temporal(g, claim, _policy())
    assert result.status is PredicateStatus.FAIL
    assert "unit_mismatch" in result.reason_codes


def test_type_temporal_entity_mismatch_fail() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    g.add_node(_fact())
    g.add_node(_calc())
    g.add_node(_evidence(subject_id="SUBJ-2"))
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    result = type_temporal(g, claim, _policy())
    assert result.status is PredicateStatus.FAIL
    assert "entity_mismatch" in result.reason_codes


def test_type_temporal_point_in_time_rejects_post_cutoff() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    obs = _observation(available_at=datetime(2024, 7, 1, tzinfo=UTC))
    g.add_node(obs)
    claim = _claim(
        evidence_ids=(obs.observation_id,),
        assertions=(_assertion(obs.observation_id),),
        knowledge_cutoff=CUTOFF,
    )
    result = type_temporal(g, claim, _policy(temporal_mode=TemporalMode.POINT_IN_TIME))
    assert result.status is PredicateStatus.FAIL
    assert "evidence_after_cutoff" in result.reason_codes


def test_type_temporal_retrospective_admits_post_cutoff() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    obs = _observation(available_at=datetime(2024, 7, 1, tzinfo=UTC))
    g.add_node(obs)
    claim = _claim(
        evidence_ids=(obs.observation_id,),
        assertions=(_assertion(obs.observation_id),),
        knowledge_cutoff=CUTOFF,
    )
    result = type_temporal(g, claim, _policy(temporal_mode=TemporalMode.RETROSPECTIVE))
    assert result.status is PredicateStatus.PASS


def test_type_temporal_unknown_when_timestamp_missing() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    obs = _observation(available_at=None, publication_at=None)
    g.add_node(obs)
    claim = _claim(
        evidence_ids=(obs.observation_id,),
        assertions=(_assertion(obs.observation_id),),
        knowledge_cutoff=CUTOFF,
    )
    result = type_temporal(g, claim, _policy(temporal_mode=TemporalMode.POINT_IN_TIME))
    assert result.status is PredicateStatus.UNKNOWN
    assert "missing_timestamp" in result.reason_codes


def test_type_temporal_stale_fail() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    obs = _observation(available_at=datetime(2020, 1, 1, tzinfo=UTC))
    g.add_node(obs)
    claim = _claim(
        evidence_ids=(obs.observation_id,),
        assertions=(_assertion(obs.observation_id),),
        knowledge_cutoff=CUTOFF,
    )
    result = type_temporal(g, claim, _policy(freshness_max_age_seconds=86400))
    assert result.status is PredicateStatus.FAIL
    assert "evidence_stale" in result.reason_codes


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------


def test_provenance_pass() -> None:
    g = _full_evidence_graph()
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    result = provenance(g, claim, _policy())
    assert result.status is PredicateStatus.PASS


def test_provenance_fail_incomplete_lineage() -> None:
    g = EvidenceGraph()
    # Evidence -> Calc, but calc has no facts and nothing reaches an artifact.
    g.add_node(_calc(input_fact_ids=()))
    g.add_node(_evidence(source_fact_ids=()))
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    result = provenance(g, claim, _policy())
    assert result.status is PredicateStatus.FAIL
    assert "incomplete_lineage" in result.reason_codes


def test_provenance_non_independent_sources_fail() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact("ART-1"))
    g.add_node(_fact("FACT-1", artifact_id="ART-1"))
    g.add_node(_calc("CALC-1", input_fact_ids=("FACT-1",)))
    g.add_node(_calc("CALC-2", input_fact_ids=("FACT-1",)))
    g.add_node(_evidence("EV-1", calculation_id="CALC-1", source_fact_ids=("FACT-1",)))
    g.add_node(_evidence("EV-2", calculation_id="CALC-2", source_fact_ids=("FACT-1",)))
    claim = _claim(
        evidence_ids=("EV-1", "EV-2"),
        assertions=(_assertion("EV-1"), _assertion("EV-2")),
    )
    result = provenance(g, claim, _policy(require_source_independence=True))
    assert result.status is PredicateStatus.FAIL
    assert "non_independent_sources" in result.reason_codes


def test_provenance_independent_sources_pass() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact("ART-1"))
    g.add_node(_artifact("ART-2"))
    g.add_node(_fact("FACT-1", artifact_id="ART-1"))
    g.add_node(_fact("FACT-2", artifact_id="ART-2"))
    g.add_node(_calc("CALC-1", input_fact_ids=("FACT-1",)))
    g.add_node(_calc("CALC-2", input_fact_ids=("FACT-2",)))
    g.add_node(_evidence("EV-1", calculation_id="CALC-1", source_fact_ids=("FACT-1",)))
    g.add_node(_evidence("EV-2", calculation_id="CALC-2", source_fact_ids=("FACT-2",)))
    claim = _claim(
        evidence_ids=("EV-1", "EV-2"),
        assertions=(_assertion("EV-1"), _assertion("EV-2")),
    )
    result = provenance(g, claim, _policy(require_source_independence=True))
    assert result.status is PredicateStatus.PASS


# --------------------------------------------------------------------------
# derivation
# --------------------------------------------------------------------------


def test_derivation_pass() -> None:
    g = _full_evidence_graph(calc_value=Decimal("0.25"))
    claim = _claim(
        evidence_ids=("EV-1",),
        assertions=(_assertion("EV-1", value=Decimal("0.25")),),
    )
    result = derivation(g, claim, _policy())
    assert result.status is PredicateStatus.PASS


def test_derivation_fail_tampered_number() -> None:
    g = _full_evidence_graph(calc_value=Decimal("0.25"))
    claim = _claim(
        evidence_ids=("EV-1",),
        assertions=(_assertion("EV-1", value=Decimal("0.30")),),
    )
    result = derivation(g, claim, _policy())
    assert result.status is PredicateStatus.FAIL
    assert "assertion_value_mismatch" in result.reason_codes


def test_derivation_not_applicable_without_calc() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    obs = _observation()
    g.add_node(obs)
    claim = _claim(
        evidence_ids=(obs.observation_id,),
        assertions=(_assertion(obs.observation_id),),
    )
    result = derivation(g, claim, _policy())
    assert result.status is PredicateStatus.NOT_APPLICABLE


# --------------------------------------------------------------------------
# support
# --------------------------------------------------------------------------


def test_support_pass() -> None:
    g = _full_evidence_graph()
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    result = support(g, claim, _policy())
    assert result.status is PredicateStatus.PASS


def test_support_fail_uncited() -> None:
    g = _full_evidence_graph()
    # Assertion cites EV-1 but the claim does not list it in evidence_ids.
    claim = _claim(evidence_ids=(), assertions=(_assertion("EV-1"),))
    result = support(g, claim, _policy())
    assert result.status is PredicateStatus.FAIL
    assert "assertion_evidence_not_cited" in result.reason_codes


def test_support_fail_irrelevant_evidence() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    g.add_node(_fact())
    g.add_node(_calc())
    g.add_node(_evidence(subject_id="SUBJ-2"))
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    result = support(g, claim, _policy())
    assert result.status is PredicateStatus.FAIL
    assert "assertion_not_supported" in result.reason_codes


# --------------------------------------------------------------------------
# admit (composition)
# --------------------------------------------------------------------------

_ALL = (
    PredicateName.INTEGRITY,
    PredicateName.TYPE_TEMPORAL,
    PredicateName.PROVENANCE,
    PredicateName.DERIVATION,
    PredicateName.SUPPORT,
)


def test_admit_all_pass_admitted() -> None:
    g = _full_evidence_graph()
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    decision = admit(g, claim, _policy(mandatory=_ALL))
    assert isinstance(decision, AdmissionDecision)
    assert decision.outcome is AdmissionOutcome.ADMITTED
    assert decision.verification_outcome is VerificationOutcome.VERIFIED
    assert len(decision.predicate_results) == 5
    assert tuple(r.predicate for r in decision.predicate_results) == _ALL
    assert decision.policy_version == "1.0.0"
    assert decision.claim_id == claim.candidate_claim_id


def test_admit_failed_mandatory_rejected() -> None:
    g = _full_evidence_graph()
    claim = _claim(evidence_ids=("EV-missing",), assertions=(_assertion("EV-missing"),))
    decision = admit(g, claim, _policy(mandatory=(PredicateName.INTEGRITY,)))
    assert decision.outcome is AdmissionOutcome.REJECTED
    assert decision.verification_outcome is VerificationOutcome.INTEGRITY_FAILURE


def test_admit_unknown_mandatory_abstained() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    obs = _observation(available_at=None, publication_at=None)
    g.add_node(obs)
    claim = _claim(
        evidence_ids=(obs.observation_id,),
        assertions=(_assertion(obs.observation_id),),
        knowledge_cutoff=CUTOFF,
    )
    decision = admit(g, claim, _policy(mandatory=(PredicateName.TYPE_TEMPORAL,)))
    assert decision.outcome is AdmissionOutcome.ABSTAINED
    assert decision.verification_outcome is VerificationOutcome.UNVERIFIABLE


def test_admit_not_applicable_mandatory_counts_satisfied() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    obs = _observation()
    g.add_node(obs)
    claim = _claim(
        evidence_ids=(obs.observation_id,),
        assertions=(_assertion(obs.observation_id),),
    )
    # DERIVATION is NOT_APPLICABLE (no calc) yet mandatory -> must not block.
    decision = admit(g, claim, _policy(mandatory=_ALL))
    assert decision.outcome is AdmissionOutcome.ADMITTED


def test_admit_non_mandatory_failure_does_not_block() -> None:
    # Evidence value supports the assertion, but the upstream calc differs,
    # so derivation FAILs. Derivation is not mandatory, so admission stands.
    g = _full_evidence_graph(calc_value=Decimal("0.99"), evidence_value=Decimal("0.25"))
    claim = _claim(
        evidence_ids=("EV-1",),
        assertions=(_assertion("EV-1", value=Decimal("0.25")),),
    )
    policy = _policy(mandatory=(PredicateName.SUPPORT,))
    assert derivation(g, claim, policy).status is PredicateStatus.FAIL
    decision = admit(g, claim, policy)
    assert decision.outcome is AdmissionOutcome.ADMITTED


def test_admit_derivation_failure_maps_to_contradicted() -> None:
    g = _full_evidence_graph(calc_value=Decimal("0.25"))
    claim = _claim(
        evidence_ids=("EV-1",),
        assertions=(_assertion("EV-1", value=Decimal("0.30")),),
    )
    decision = admit(g, claim, _policy(mandatory=(PredicateName.DERIVATION,)))
    assert decision.outcome is AdmissionOutcome.REJECTED
    assert decision.verification_outcome is VerificationOutcome.CONTRADICTED


def test_admit_support_failure_maps_to_insufficient_evidence() -> None:
    g = _full_evidence_graph()
    claim = _claim(evidence_ids=(), assertions=(_assertion("EV-1"),))
    decision = admit(g, claim, _policy(mandatory=(PredicateName.SUPPORT,)))
    assert decision.outcome is AdmissionOutcome.REJECTED
    assert decision.verification_outcome is VerificationOutcome.INSUFFICIENT_EVIDENCE


def test_admit_is_deterministic() -> None:
    g = _full_evidence_graph()
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    policy = _policy(mandatory=_ALL)
    assert admit(g, claim, policy) == admit(g, claim, policy)


def test_admit_decision_is_frozen() -> None:
    g = _full_evidence_graph()
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    decision = admit(g, claim, _policy(mandatory=_ALL))
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        decision.outcome = AdmissionOutcome.REJECTED  # type: ignore[misc]
