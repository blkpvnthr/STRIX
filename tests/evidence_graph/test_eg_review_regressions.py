"""Security regressions for verification bypasses found by adversarial review
(workflow wf_f7c8fe10-269). Each reproduces a real admission bypass:

- CRITICAL metric-relabeling: an agent cites real evidence under a FALSE metric
  label and the claim is ADMITTED/VERIFIED.
- CRITICAL point-in-time cutoff controlled by the untrusted claim: omitting (or
  far-future-ing) knowledge_cutoff bypasses the as-of check. Fix: the TRUSTED
  VerificationPolicy.as_of_cutoff governs; the claim may only tighten it.
- temporal provenance-closure gap: post-cutoff data upstream of a backdated
  Evidence node leaks in undetected.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.invariants import is_effectively_admitted
from strix.evidence_graph.nodes import (
    AdmissionOutcome,
    Assertion,
    CandidateClaim,
    EvidenceGraphError,
    PredicateName,
    PredicateStatus,
    RelationshipKind,
    TemporalMode,
    VerificationPolicy,
    make_candidate_claim,
    make_edge,
    make_verification_policy,
)
from strix.evidence_graph.predicates import admit, support, type_temporal
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
POST = datetime(2024, 7, 1, tzinfo=UTC)
CUTOFF = date(2024, 6, 30)
FAR_FUTURE = date(2099, 1, 1)
HEX64 = "a" * 64
_ALL = (
    PredicateName.INTEGRITY,
    PredicateName.TYPE_TEMPORAL,
    PredicateName.PROVENANCE,
    PredicateName.DERIVATION,
    PredicateName.SUPPORT,
)


def _artifact(known_at: datetime = KNOWN) -> SourceArtifact:
    return SourceArtifact(
        artifact_id="ART-1", source_type=SourceType.SYNTHETIC_FIXTURE,
        source_name="companyfacts.json", source_version="v1", content_hash=HEX64,
        known_at=known_at, local_path="raw/companyfacts.json", byte_size=100,
    )


def _fact(known_at: datetime = KNOWN) -> SourceFact:
    return SourceFact(
        fact_id="FACT-1", subject_id="SUBJ-1", concept=Concept.OPERATING_INCOME,
        value=Decimal("25"), unit=Unit.USD, observation_period="FY2023",
        known_at=known_at, source_artifact_id="ART-1", source_locator="/facts/0",
        validation_status=ValidationStatus.VALID,
    )


def _calc() -> CalculationResult:
    return CalculationResult(
        calculation_id="CALC-1", calculation_name=Metric.OPERATING_MARGIN,
        calculation_version="v1", subject_id="SUBJ-1", value=Decimal("0.25"),
        unit=Unit.RATIO, observation_period="FY2023", input_fact_ids=("FACT-1",),
    )


def _evidence(known_at: datetime = KNOWN) -> Evidence:
    return Evidence(
        evidence_id="EV-1", subject_id="SUBJ-1", evidence_type=EvidenceType.CALCULATION,
        metric=Metric.OPERATING_MARGIN, value=Decimal("0.25"), display_value="0.25",
        unit=Unit.RATIO, observation_period="FY2023", calculation_id="CALC-1",
        source_fact_ids=("FACT-1",), known_at=known_at, status=EvidenceStatus.UNVERIFIED,
    )


def _graph(*, ev_known: datetime = KNOWN, fact_known: datetime = KNOWN) -> EvidenceGraph:
    g = EvidenceGraph()
    g.add_node(_artifact())
    g.add_node(_fact(known_at=fact_known))
    g.add_node(_calc())
    g.add_node(_evidence(known_at=ev_known))
    return g


def _assertion(metric: str = "operating_margin") -> Assertion:
    return Assertion(
        metric=metric, asserted_value=Decimal("0.25"), unit="ratio", evidence_id="EV-1"
    )


def _claim(
    *, metric: str = "operating_margin", knowledge_cutoff: date | None = None
) -> CandidateClaim:
    return make_candidate_claim(
        subject_id="SUBJ-1", claim_type="profitability", statement="margin 25%",
        evidence_ids=("EV-1",), assertions=(_assertion(metric),),
        knowledge_cutoff=knowledge_cutoff,
    )


def _policy(
    *,
    temporal_mode: TemporalMode = TemporalMode.POINT_IN_TIME,
    as_of_cutoff: date | None = None,
    mandatory: tuple[PredicateName, ...] = _ALL,
) -> VerificationPolicy:
    return make_verification_policy(
        version="1.0.0", mandatory_predicates=mandatory, temporal_mode=temporal_mode,
        absolute_tolerance=Decimal("0.0001"), relative_tolerance=Decimal("0.0001"),
        as_of_cutoff=as_of_cutoff,
    )


class TestMetricRelabelForgery:
    def test_support_rejects_metric_mismatch(self) -> None:
        g = _graph()
        claim = _claim(metric="net_profit_margin")  # evidence attests operating_margin
        result = support(g, claim, _policy())
        assert result.status is PredicateStatus.FAIL
        assert "metric_mismatch" in result.reason_codes

    def test_admit_rejects_relabeled_claim(self) -> None:
        g = _graph()
        claim = _claim(metric="net_profit_margin")
        decision = admit(g, claim, _policy())
        assert decision.outcome is AdmissionOutcome.REJECTED

    def test_matching_metric_still_admitted(self) -> None:
        g = _graph()
        claim = _claim(metric="operating_margin")
        decision = admit(g, claim, _policy(as_of_cutoff=FAR_FUTURE))
        assert decision.outcome is AdmissionOutcome.ADMITTED


class TestTrustedPointInTimeCutoff:
    def test_policy_cutoff_enforced_when_claim_omits(self) -> None:
        g = _graph(ev_known=POST)  # evidence available after the as-of
        claim = _claim(knowledge_cutoff=None)  # agent omits the cutoff
        result = type_temporal(g, claim, _policy(as_of_cutoff=CUTOFF))
        assert result.status is PredicateStatus.FAIL
        assert "evidence_after_cutoff" in result.reason_codes

    def test_claim_cannot_relax_policy_cutoff(self) -> None:
        g = _graph(ev_known=POST)
        claim = _claim(knowledge_cutoff=FAR_FUTURE)  # agent tries to widen the window
        result = type_temporal(g, claim, _policy(as_of_cutoff=CUTOFF))
        assert result.status is PredicateStatus.FAIL
        assert "evidence_after_cutoff" in result.reason_codes

    def test_admit_rejects_lookahead_under_policy_cutoff(self) -> None:
        g = _graph(ev_known=POST)
        claim = _claim(knowledge_cutoff=None)
        decision = admit(g, claim, _policy(as_of_cutoff=CUTOFF))
        assert decision.outcome is AdmissionOutcome.REJECTED


class TestTemporalUpstreamClosure:
    def test_future_source_upstream_of_backdated_evidence_rejected(self) -> None:
        # Evidence itself is pre-cutoff, but its upstream SourceFact is post-cutoff.
        g = _graph(ev_known=KNOWN, fact_known=POST)
        claim = _claim(knowledge_cutoff=None)
        result = type_temporal(g, claim, _policy(as_of_cutoff=CUTOFF))
        assert result.status is PredicateStatus.FAIL
        assert "evidence_after_cutoff" in result.reason_codes


def _contract() -> NumericalContract:
    return NumericalContract(
        representation="decimal", contract_class=ContractClass.TOLERANCE,
        precision="50", rounding="round_half_even",
        absolute_tolerance=Decimal("0"), relative_tolerance=Decimal("0.000000001"),
        reference_method="python stdlib statistics",
    )


def _comp(status: BackendValidation):  # type: ignore[no-untyped-def]
    return make_computation_result(
        algorithm_id="native.mean", algorithm_version="1.0.0",
        backend_id="python_reference@0.1.0", inputs={"x": [Decimal("1")]},
        contract=_contract(), scalar=Decimal("0.25"), output_unit="ratio",
        software_version="strix@test", numerical_validation_status=status,
    )


def _graph_with_backing_comp(status: BackendValidation) -> tuple[EvidenceGraph, CandidateClaim]:
    comp = _comp(status)
    g = EvidenceGraph()
    g.add_node(_artifact())
    g.add_node(_fact())
    g.add_node(comp)
    g.add_node(
        CalculationResult(
            calculation_id="CALC-1", calculation_name=Metric.OPERATING_MARGIN,
            calculation_version="v1", subject_id="SUBJ-1", value=Decimal("0.25"),
            unit=Unit.RATIO, observation_period="FY2023",
            input_fact_ids=("FACT-1",), input_calculation_ids=(comp.computation_id,),
        )
    )
    g.add_node(_evidence())
    return g, _claim(knowledge_cutoff=None)


class TestNumericalContractClosureBlocker:
    def test_unsound_computation_two_hops_blocks_admission(self) -> None:
        g, claim = _graph_with_backing_comp(BackendValidation.PARITY_FAILED)
        policy = _policy(as_of_cutoff=FAR_FUTURE)
        # The claim passes the five predicates...
        assert admit(g, claim, policy).outcome is AdmissionOutcome.ADMITTED
        # ...but a PARITY_FAILED computation two hops upstream blocks it (§11.16).
        assert is_effectively_admitted(g, claim, policy) is False

    def test_sound_computation_does_not_block(self) -> None:
        g, claim = _graph_with_backing_comp(BackendValidation.REFERENCE)
        assert is_effectively_admitted(g, claim, _policy(as_of_cutoff=FAR_FUTURE)) is True


def _chain_graph(n: int, *, cycle: bool) -> EvidenceGraph:
    g = EvidenceGraph()
    for i in range(n):
        g.add_node(
            SourceArtifact(
                artifact_id=f"ART-{i}", source_type=SourceType.SYNTHETIC_FIXTURE,
                source_name="f.json", source_version="v1", content_hash=HEX64,
                known_at=KNOWN, local_path="raw/f.json", byte_size=100,
            )
        )
    for i in range(n - 1):
        g.add_edge(make_edge(RelationshipKind.DERIVED_FROM, f"ART-{i + 1}", f"ART-{i}"))
    if cycle:
        g.add_edge(make_edge(RelationshipKind.DERIVED_FROM, "ART-0", f"ART-{n - 1}"))
    return g


class TestDeepChainAcyclicity:
    def test_deep_chain_no_recursion_error(self) -> None:
        # 1500 > Python's default recursion limit: the old recursive DFS raised
        # RecursionError; the iterative implementation must return normally.
        _chain_graph(1500, cycle=False).assert_acyclic_derivation()

    def test_deep_cycle_detected(self) -> None:
        with pytest.raises(EvidenceGraphError):
            _chain_graph(1200, cycle=True).assert_acyclic_derivation()
