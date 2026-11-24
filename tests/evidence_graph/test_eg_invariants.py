"""Tested properties for the compositional verification invariants (R1 §11).

Each invariant is exercised with a hand-constructed scenario demonstrating that
the property HOLDS, plus (where meaningful) a "teeth" scenario proving the
checker actually detects a violation rather than always returning ``True``.

These are *tested* properties, not mathematical proofs: the scenarios establish
the behaviour over concrete inputs, nothing more.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from strix.evidence_graph.certificates import (
    build_computation_certificate,
    validate_computation_certificate,
)
from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.invariants import (
    InvariantResult,
    admission_blockers,
    check_invariant_contradiction_reevaluation,
    check_invariant_evidence_resolution,
    check_invariant_integrity_not_truth,
    check_invariant_invalidation_reevaluation,
    check_invariant_mandatory_dependency,
    check_invariant_model_cannot_assign_verdict,
    check_invariant_no_downgrade_on_exhaustion,
    check_invariant_numerical_contract,
    check_invariant_point_in_time,
    check_invariant_reproducibility,
    check_invariant_unrelated_evidence,
    check_invariants,
    is_effectively_admitted,
)
from strix.evidence_graph.nodes import (
    AdmissionOutcome,
    Assertion,
    CandidateClaim,
    PredicateName,
    RelationshipKind,
    SourceObservation,
    TemporalMode,
    VerificationPolicy,
    make_candidate_claim,
    make_edge,
    make_source_observation,
    make_verification_policy,
)
from strix.evidence_graph.predicates import admit
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
from strix.native.contracts import BackendValidation, ContractClass, NumericalContract
from strix.native.results import make_computation_result

KNOWN = datetime(2024, 1, 1, tzinfo=UTC)
CUTOFF = date(2024, 6, 30)
HEX64 = "a" * 64

_ALL: tuple[PredicateName, ...] = (
    PredicateName.INTEGRITY,
    PredicateName.TYPE_TEMPORAL,
    PredicateName.PROVENANCE,
    PredicateName.DERIVATION,
    PredicateName.SUPPORT,
)


# --------------------------------------------------------------------------
# Builders (mirror tests/evidence_graph/test_eg_predicates.py)
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
    concept: str = "operating_margin",
) -> SourceObservation:
    return make_source_observation(
        subject_id=subject_id,
        concept=concept,
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
    statement: str = "Operating margin was 25%.",
    claim_type: str = "profitability_change",
) -> CandidateClaim:
    return make_candidate_claim(
        subject_id="SUBJ-1",
        claim_type=claim_type,
        statement=statement,
        evidence_ids=evidence_ids,
        assertions=assertions,
        knowledge_cutoff=knowledge_cutoff,
    )


def _policy(
    *,
    mandatory: tuple[PredicateName, ...] = _ALL,
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


def _full_graph(
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


def _admitted_scenario() -> tuple[EvidenceGraph, CandidateClaim, VerificationPolicy]:
    g = _full_graph()
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    return g, claim, _policy()


_CONTRACT = NumericalContract(
    representation="decimal",
    contract_class=ContractClass.EXACT,
    precision="arbitrary",
    rounding="round_half_even",
    reference_method="python_reference_div",
)


def _computation_backed_graph(
    *, status: BackendValidation
) -> tuple[EvidenceGraph, CandidateClaim]:
    """A graph whose Evidence is backed by a ComputationResult of *status*.

    Evidence -> ComputationResult -> artifact. The computation's scalar matches
    the asserted value so the derivation predicate PASSes; only the compositional
    numerical-contract layer may block on a failed parity status.
    """
    g = EvidenceGraph()
    g.add_node(_artifact())
    comp = make_computation_result(
        algorithm_id="operating_margin",
        algorithm_version="1.0.0",
        backend_id="native_cpu",
        inputs={"a": Decimal("25"), "b": Decimal("100")},
        contract=_CONTRACT,
        output_unit="ratio",
        software_version="0.1",
        numerical_validation_status=status,
        scalar=Decimal("0.25"),
        input_artifact_refs=("ART-1",),
    )
    g.add_node(comp)
    ev = _evidence(calculation_id=comp.computation_id, source_fact_ids=())
    g.add_node(ev)
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    return g, claim


# --------------------------------------------------------------------------
# InvariantResult shape
# --------------------------------------------------------------------------


def test_invariant_result_is_frozen() -> None:
    import pytest
    from pydantic import ValidationError

    r = InvariantResult(name="x", holds=True, detail="d")
    with pytest.raises(ValidationError):
        r.holds = False  # type: ignore[misc]


# --------------------------------------------------------------------------
# Invariant 1 — invalid mandatory dependencies prevent admission
# --------------------------------------------------------------------------


def test_invariant_1_holds_when_broken_dependency_rejected() -> None:
    g = _full_graph()
    claim = _claim(evidence_ids=("EV-missing",), assertions=(_assertion("EV-missing"),))
    policy = _policy(mandatory=(PredicateName.INTEGRITY,))
    # The scenario is meaningful: admission is actually prevented.
    assert admit(g, claim, policy).outcome is AdmissionOutcome.REJECTED
    result = check_invariant_mandatory_dependency(g, claim, policy)
    assert result.holds is True


def test_invariant_1_holds_on_clean_admission() -> None:
    g, claim, policy = _admitted_scenario()
    assert check_invariant_mandatory_dependency(g, claim, policy).holds is True


# --------------------------------------------------------------------------
# Invariant 2 — supporting evidence must resolve to preserved artifacts
# --------------------------------------------------------------------------


def test_invariant_2_holds_when_unresolved_lineage_blocked() -> None:
    g = EvidenceGraph()
    g.add_node(_calc(input_fact_ids=()))
    g.add_node(_evidence(source_fact_ids=()))
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    policy = _policy(mandatory=(PredicateName.PROVENANCE,))
    assert admit(g, claim, policy).outcome is AdmissionOutcome.REJECTED
    assert check_invariant_evidence_resolution(g, claim, policy).holds is True


def test_invariant_2_teeth_detects_admission_without_artifact() -> None:
    # provenance NOT mandatory: an unresolved claim is admitted -> violation.
    g = EvidenceGraph()
    g.add_node(_calc(input_fact_ids=()))
    g.add_node(_evidence(source_fact_ids=()))
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    policy = _policy(mandatory=(PredicateName.SUPPORT,))
    assert admit(g, claim, policy).outcome is AdmissionOutcome.ADMITTED
    assert check_invariant_evidence_resolution(g, claim, policy).holds is False


# --------------------------------------------------------------------------
# Invariant 3 — invalidated observations trigger reevaluation
# --------------------------------------------------------------------------


def test_invariant_3_holds_removal_flips_admitted_claim() -> None:
    g, claim, policy = _admitted_scenario()
    assert is_effectively_admitted(g, claim, policy) is True
    assert check_invariant_invalidation_reevaluation(g, claim, policy).holds is True


def test_invariant_3_teeth_no_mandatory_means_no_reevaluation() -> None:
    g, claim, _ = _admitted_scenario()
    policy = _policy(mandatory=())  # nothing mandatory -> removal never blocks
    assert is_effectively_admitted(g, claim, policy) is True
    assert check_invariant_invalidation_reevaluation(g, claim, policy).holds is False


# --------------------------------------------------------------------------
# Invariant 4 — unrelated evidence cannot satisfy support
# --------------------------------------------------------------------------


def test_invariant_4_holds_unrelated_entity_blocked() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    g.add_node(_fact())
    g.add_node(_calc())
    g.add_node(_evidence(subject_id="SUBJ-2"))  # about a different entity
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    policy = _policy(mandatory=(PredicateName.SUPPORT,))
    assert admit(g, claim, policy).outcome is AdmissionOutcome.REJECTED
    assert check_invariant_unrelated_evidence(g, claim, policy).holds is True


def test_invariant_4_teeth_detects_unrelated_admission() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    g.add_node(_fact())
    g.add_node(_calc())
    g.add_node(_evidence(subject_id="SUBJ-2"))
    claim = _claim(evidence_ids=("EV-1",), assertions=(_assertion("EV-1"),))
    # support NOT mandatory -> unrelated evidence slips through.
    policy = _policy(mandatory=(PredicateName.INTEGRITY,))
    assert admit(g, claim, policy).outcome is AdmissionOutcome.ADMITTED
    assert check_invariant_unrelated_evidence(g, claim, policy).holds is False


# --------------------------------------------------------------------------
# Invariant 5 — point-in-time: post-cutoff info cannot establish knowledge
# --------------------------------------------------------------------------


def test_invariant_5_holds_post_cutoff_blocked() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    obs = _observation(available_at=datetime(2024, 7, 1, tzinfo=UTC))
    g.add_node(obs)
    claim = _claim(
        evidence_ids=(obs.observation_id,),
        assertions=(_assertion(obs.observation_id),),
        knowledge_cutoff=CUTOFF,
    )
    policy = _policy(
        mandatory=(PredicateName.TYPE_TEMPORAL,),
        temporal_mode=TemporalMode.POINT_IN_TIME,
    )
    assert admit(g, claim, policy).outcome is AdmissionOutcome.REJECTED
    assert check_invariant_point_in_time(g, claim, policy).holds is True


def test_invariant_5_vacuous_in_retrospective_mode() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    obs = _observation(available_at=datetime(2024, 7, 1, tzinfo=UTC))
    g.add_node(obs)
    claim = _claim(
        evidence_ids=(obs.observation_id,),
        assertions=(_assertion(obs.observation_id),),
        knowledge_cutoff=CUTOFF,
    )
    policy = _policy(temporal_mode=TemporalMode.RETROSPECTIVE)
    # Not point-in-time -> invariant does not apply; it still "holds".
    assert check_invariant_point_in_time(g, claim, policy).holds is True


def test_invariant_5_teeth_detects_post_cutoff_admission() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    obs = _observation(available_at=datetime(2024, 7, 1, tzinfo=UTC))
    g.add_node(obs)
    claim = _claim(
        evidence_ids=(obs.observation_id,),
        assertions=(_assertion(obs.observation_id),),
        knowledge_cutoff=CUTOFF,
    )
    # point-in-time but TYPE_TEMPORAL not mandatory -> post-cutoff evidence admitted.
    policy = _policy(mandatory=(PredicateName.INTEGRITY,), temporal_mode=TemporalMode.POINT_IN_TIME)
    assert admit(g, claim, policy).outcome is AdmissionOutcome.ADMITTED
    assert check_invariant_point_in_time(g, claim, policy).holds is False


# --------------------------------------------------------------------------
# Invariant 6 — integrity cannot establish semantic truth
# --------------------------------------------------------------------------


def test_invariant_6_holds_integrity_pass_support_fail_rejected() -> None:
    # Hashes resolve (integrity PASS) but the asserted number is wrong (support FAIL).
    g = _full_graph(calc_value=Decimal("0.25"), evidence_value=Decimal("0.25"))
    claim = _claim(
        evidence_ids=("EV-1",),
        assertions=(_assertion("EV-1", value=Decimal("0.99")),),
    )
    policy = _policy(mandatory=(PredicateName.INTEGRITY, PredicateName.SUPPORT))
    assert admit(g, claim, policy).outcome is AdmissionOutcome.REJECTED
    assert check_invariant_integrity_not_truth(g, claim, policy).holds is True


def test_invariant_6_teeth_integrity_only_admits_unsupported() -> None:
    g = _full_graph(evidence_value=Decimal("0.25"))
    claim = _claim(
        evidence_ids=("EV-1",),
        assertions=(_assertion("EV-1", value=Decimal("0.99")),),
    )
    policy = _policy(mandatory=(PredicateName.INTEGRITY,))  # integrity alone
    assert admit(g, claim, policy).outcome is AdmissionOutcome.ADMITTED
    assert check_invariant_integrity_not_truth(g, claim, policy).holds is False


# --------------------------------------------------------------------------
# Invariant 7 — the model cannot assign or override verdicts
# --------------------------------------------------------------------------


def test_invariant_7_holds_self_asserted_verdict_ignored() -> None:
    g = _full_graph()
    claim = _claim(evidence_ids=("EV-missing",), assertions=(_assertion("EV-missing"),))
    policy = _policy(mandatory=(PredicateName.INTEGRITY,))
    assert admit(g, claim, policy).outcome is AdmissionOutcome.REJECTED
    assert check_invariant_model_cannot_assign_verdict(g, claim, policy).holds is True


def test_invariant_7_candidate_claim_has_no_verdict_field() -> None:
    forbidden = ("status", "verdict", "verified", "outcome", "decision", "admit")
    for name in CandidateClaim.model_fields:
        assert not any(token in name.lower() for token in forbidden)


# --------------------------------------------------------------------------
# Invariant 8 — new contradictory evidence triggers reevaluation
# --------------------------------------------------------------------------


def test_invariant_8_holds_contradiction_flips_outcome() -> None:
    g, claim, policy = _admitted_scenario()
    assert is_effectively_admitted(g, claim, policy) is True
    assert check_invariant_contradiction_reevaluation(g, claim, policy).holds is True


def test_invariant_8_existing_contradiction_blocks_effective_admission() -> None:
    g, claim, policy = _admitted_scenario()
    contra = _observation(value=Decimal("0.99"), concept="contradiction")
    g.add_node(contra)
    g.add_edge(make_edge(RelationshipKind.CONTRADICTED_BY, "EV-1", contra.observation_id))
    assert admit(g, claim, policy).outcome is AdmissionOutcome.ADMITTED
    assert is_effectively_admitted(g, claim, policy) is False
    assert "unresolved_contradiction" in admission_blockers(g, claim, policy)


# --------------------------------------------------------------------------
# Invariant 9 — resource exhaustion cannot weaken requirements
# --------------------------------------------------------------------------


def test_invariant_9_holds_unknown_abstains_never_admits() -> None:
    g = EvidenceGraph()
    g.add_node(_artifact())
    obs = _observation(available_at=None, publication_at=None)  # cannot decide cutoff
    g.add_node(obs)
    claim = _claim(
        evidence_ids=(obs.observation_id,),
        assertions=(_assertion(obs.observation_id),),
        knowledge_cutoff=CUTOFF,
    )
    policy = _policy(mandatory=(PredicateName.TYPE_TEMPORAL,))
    decision = admit(g, claim, policy)
    assert decision.outcome is AdmissionOutcome.ABSTAINED
    assert check_invariant_no_downgrade_on_exhaustion(g, claim, policy).holds is True


# --------------------------------------------------------------------------
# Invariant 10 — reproducible decision for identical inputs + pinned policy
# --------------------------------------------------------------------------


def test_invariant_10_holds_reproducible() -> None:
    g, claim, policy = _admitted_scenario()
    assert admit(g, claim, policy) == admit(g, claim, policy)
    assert check_invariant_reproducibility(g, claim, policy).holds is True


# --------------------------------------------------------------------------
# Invariant 16 — invalid numerical contracts block dependent findings
# --------------------------------------------------------------------------


def test_invariant_16_holds_failed_parity_blocks_claim() -> None:
    g, claim = _computation_backed_graph(status=BackendValidation.PARITY_FAILED)
    policy = _policy(mandatory=_ALL)
    # Predicate admission alone would ADMIT (derivation only checks the value):
    assert admit(g, claim, policy).outcome is AdmissionOutcome.ADMITTED
    # ...but the compositional contract layer blocks it.
    assert is_effectively_admitted(g, claim, policy) is False
    assert "invalid_numerical_contract" in admission_blockers(g, claim, policy)
    assert check_invariant_numerical_contract(g, claim, policy).holds is True


def test_invariant_16_valid_parity_admits() -> None:
    g, claim = _computation_backed_graph(status=BackendValidation.PARITY_PASSED)
    policy = _policy(mandatory=_ALL)
    assert is_effectively_admitted(g, claim, policy) is True
    assert check_invariant_numerical_contract(g, claim, policy).holds is True


def test_invariant_16_failed_computation_certificate_is_invalid_evidence() -> None:
    # A certificate recording a failed contract cannot be a valid receipt of
    # numerical soundness for a dependent claim.
    cert = build_computation_certificate(
        algorithm_id="operating_margin",
        algorithm_version="1.0.0",
        input_digest=HEX64,
        input_artifact_refs=("ART-1",),
        input_observation_ids=(),
        output_digest="d" * 64,
        backend_version="native_cpu-0.1",
        numerical_contract=_CONTRACT,
        applicable_tolerances={"absolute": Decimal("0")},
        validation_status="parity_failed",
        issued_at=KNOWN,
    )
    # The certificate is content-intact (untampered) yet attests a FAILED contract:
    assert validate_computation_certificate(cert) is True
    assert cert.validation_status == "parity_failed"


# --------------------------------------------------------------------------
# check_invariants aggregate
# --------------------------------------------------------------------------


def test_check_invariants_all_hold_on_admitted_scenario() -> None:
    g, claim, policy = _admitted_scenario()
    results = check_invariants(g, claim, policy)
    assert isinstance(results, tuple)
    assert len(results) == 11
    assert all(isinstance(r, InvariantResult) for r in results)
    assert all(r.holds for r in results), [
        (r.name, r.detail) for r in results if not r.holds
    ]


def test_check_invariants_names_are_unique_and_nonempty() -> None:
    g, claim, policy = _admitted_scenario()
    results = check_invariants(g, claim, policy)
    names = [r.name for r in results]
    assert all(names)
    assert len(set(names)) == len(names)
