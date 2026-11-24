"""End-to-end Milestone R1 integration (DoD §36.5): the full pipeline

    native computation -> typed evidence graph -> independent admission
    -> claim certificate -> verified natural-language answer

on a single preserved source, proving STRIX *actually answers* over
independently verified evidence — and that a tampered number is rejected and
never reaches the answer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from strix.answering.models import AnswerStatus, make_answer_requirement
from strix.answering.pipeline import answer_question, render_markdown
from strix.answering.synthesize import AdmittedFinding
from strix.canonical import canonical_hash
from strix.evidence_graph.certificates import build_claim_certificate
from strix.evidence_graph.graph import EvidenceGraph
from strix.evidence_graph.nodes import (
    Assertion,
    PredicateName,
    TemporalMode,
    make_candidate_claim,
    make_verification_policy,
)
from strix.evidence_graph.predicates import AdmissionOutcome, admit
from strix.models import SourceArtifact, SourceType
from strix.native.backends.python_reference import PythonReferenceBackend

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
HEX64 = "a" * 64
_ALL = (
    PredicateName.INTEGRITY,
    PredicateName.TYPE_TEMPORAL,
    PredicateName.PROVENANCE,
    PredicateName.DERIVATION,
    PredicateName.SUPPORT,
)
QUESTION = "What was ACME's revenue growth over the period?"


def _artifact() -> SourceArtifact:
    return SourceArtifact(
        artifact_id="ART-rev",
        source_type=SourceType.SYNTHETIC_FIXTURE,
        source_name="revenue.json",
        source_version="v1",
        content_hash=HEX64,
        known_at=NOW,
        local_path="raw/revenue.json",
        byte_size=100,
    )


def _policy() -> object:
    return make_verification_policy(
        version="r1-policy-1",
        mandatory_predicates=_ALL,
        temporal_mode=TemporalMode.RETROSPECTIVE,
        absolute_tolerance=Decimal("0.0001"),
        relative_tolerance=Decimal("0.0001"),
    )


def _graph_and_computation() -> tuple[EvidenceGraph, object]:
    backend = PythonReferenceBackend()
    artifact = _artifact()
    # Native computation of revenue growth from the preserved figures, with its
    # provenance bound to the source artifact.
    comp = backend.run(
        "growth_rate",
        {"first": Decimal("100000000"), "last": Decimal("125000000")},
        input_artifact_refs=("ART-rev",),
    )
    graph = EvidenceGraph()
    graph.add_node(artifact)
    graph.add_node(comp)
    return graph, comp


def _finding(graph: EvidenceGraph, comp: object, *, asserted_value: Decimal) -> AdmittedFinding:
    assertion = Assertion(
        metric="revenue_growth",
        asserted_value=asserted_value,
        unit="ratio",
        evidence_id=comp.computation_id,  # type: ignore[attr-defined]
    )
    claim = make_candidate_claim(
        subject_id="ACME",
        claim_type="revenue_growth",
        statement="ACME revenue grew over the period.",
        evidence_ids=(comp.computation_id,),  # type: ignore[attr-defined]
        assertions=(assertion,),
    )
    policy = _policy()
    decision = admit(graph, claim, policy)  # type: ignore[arg-type]
    cert = build_claim_certificate(
        claim_id=claim.candidate_claim_id,
        canonical_claim_digest=canonical_hash(claim),
        evidence_graph_snapshot_digest=graph.graph_hash(),
        supporting_evidence_ids=(comp.computation_id,),  # type: ignore[attr-defined]
        dependency_closure=(comp.computation_id, "ART-rev"),  # type: ignore[attr-defined]
        predicate_results=decision.predicate_results,
        verification_policy_version=decision.policy_version,
        verifier_version="r1-verifier-1",
        computation_certificate_refs=(),
        verified_value=asserted_value,
        measurement_unit="ratio",
        numerical_tolerance=Decimal("0.0001"),
        issued_at=NOW,
    )
    return AdmittedFinding(claim=claim, decision=decision, certificate=cert)


def test_verified_answer_end_to_end() -> None:
    graph, comp = _graph_and_computation()
    growth = comp.scalar  # type: ignore[attr-defined]
    assert growth == Decimal("0.25")  # (125M - 100M) / 100M

    finding = _finding(graph, comp, asserted_value=growth)
    assert finding.decision.outcome is AdmissionOutcome.ADMITTED

    requirement = make_answer_requirement(
        text=QUESTION, weight=Decimal("1"), subject_id="ACME", metric="revenue_growth"
    )
    response = answer_question(QUESTION, (requirement,), (finding,))

    # It actually ANSWERS, with validated factual support and full coverage.
    assert response.answer_status is AnswerStatus.COMPLETE_ANSWER
    assert response.validation.ok
    assert not response.validation.unsupported_assertions
    assert response.coverage.score == Decimal("1")
    assert len(response.factual_assertions) == 1
    # The rendered answer states the magnitude (0.25 ratio -> "25%"), not an id dump.
    assert "25" in response.answer_text
    assert "ACME" in response.answer_text
    assert "25" in render_markdown(response)


def test_tampered_value_is_rejected_and_never_answered() -> None:
    graph, comp = _graph_and_computation()
    # An agent asserts a fabricated growth figure that the evidence does not support.
    finding = _finding(graph, comp, asserted_value=Decimal("0.99"))
    assert finding.decision.outcome is AdmissionOutcome.REJECTED

    requirement = make_answer_requirement(
        text=QUESTION, weight=Decimal("1"), subject_id="ACME", metric="revenue_growth"
    )
    response = answer_question(QUESTION, (requirement,), (finding,))

    # The rejected claim contributes no factual assertion; the false "0.99"/"99%"
    # never appears, and the response is honest about the gap.
    assert response.answer_status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert response.factual_assertions == ()
    assert "99" not in response.answer_text
    assert response.validation.ok  # nothing unsupported slipped through
