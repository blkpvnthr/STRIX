"""Tests for deterministic answer synthesis from admitted findings (R1 §16, §17)."""

from __future__ import annotations

from decimal import Decimal

from strix.answering.models import (
    AnswerStatus,
    AssertionKind,
    make_answer_requirement,
)
from strix.answering.synthesize import AdmittedFinding, synthesize
from strix.evidence_graph.certificates import (
    ClaimCertificate,
    build_claim_certificate,
    validate_claim_certificate,
)
from strix.evidence_graph.nodes import (
    AdmissionOutcome,
    Assertion,
    CandidateClaim,
    VerificationOutcome,
    make_candidate_claim,
)
from strix.evidence_graph.predicates import AdmissionDecision

# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def _claim(
    *,
    subject_id: str = "ACME",
    metric: str = "operating_margin",
    value: Decimal = Decimal("0.184"),
    unit: str = "ratio",
    evidence_id: str = "EV-1",
) -> CandidateClaim:
    assertion = Assertion(
        metric=metric,
        asserted_value=value,
        unit=unit,
        evidence_id=evidence_id,
    )
    return make_candidate_claim(
        subject_id=subject_id,
        claim_type="metric",
        statement=f"{subject_id} {metric} was {value}{unit}.",
        evidence_ids=(evidence_id,),
        assertions=(assertion,),
    )


def _certificate(claim: CandidateClaim) -> ClaimCertificate:
    return build_claim_certificate(
        claim_id=claim.candidate_claim_id,
        canonical_claim_digest="digest-" + claim.candidate_claim_id,
        evidence_graph_snapshot_digest="snapshot-1",
        supporting_evidence_ids=claim.evidence_ids,
        dependency_closure=(),
        predicate_results=(),
        verification_policy_version="vpol-1",
        verifier_version="verifier-1",
        computation_certificate_refs=(),
    )


def _decision(claim: CandidateClaim, outcome: AdmissionOutcome) -> AdmissionDecision:
    verification = {
        AdmissionOutcome.ADMITTED: VerificationOutcome.VERIFIED,
        AdmissionOutcome.REJECTED: VerificationOutcome.INSUFFICIENT_EVIDENCE,
        AdmissionOutcome.ABSTAINED: VerificationOutcome.UNVERIFIABLE,
    }[outcome]
    return AdmissionDecision(
        outcome=outcome,
        verification_outcome=verification,
        predicate_results=(),
        policy_version="vpol-1",
        claim_id=claim.candidate_claim_id,
    )


def _finding(
    outcome: AdmissionOutcome = AdmissionOutcome.ADMITTED,
    *,
    subject_id: str = "ACME",
    metric: str = "operating_margin",
    value: Decimal = Decimal("0.184"),
    unit: str = "ratio",
) -> AdmittedFinding:
    claim = _claim(subject_id=subject_id, metric=metric, value=value, unit=unit)
    return AdmittedFinding(
        claim=claim,
        decision=_decision(claim, outcome),
        certificate=_certificate(claim),
    )


# --------------------------------------------------------------------------
# AdmittedFinding usability
# --------------------------------------------------------------------------


def test_admitted_finding_usable_only_when_admitted() -> None:
    assert _finding(AdmissionOutcome.ADMITTED).is_usable()
    assert not _finding(AdmissionOutcome.REJECTED).is_usable()
    assert not _finding(AdmissionOutcome.ABSTAINED).is_usable()


# --------------------------------------------------------------------------
# Happy path: one admitted finding -> one certificate-backed factual assertion
# --------------------------------------------------------------------------


def test_single_admitted_finding_produces_factual_assertion() -> None:
    finding = _finding()
    req = make_answer_requirement(
        text="What was the operating margin?",
        weight=Decimal("1"),
        subject_id="ACME",
        metric="operating_margin",
    )
    response = synthesize(
        question="What was ACME's operating margin?",
        requirements=(req,),
        findings=(finding,),
    )

    assert len(response.factual_assertions) == 1
    fa = response.factual_assertions[0]
    assert fa.kind is AssertionKind.FACTUAL
    # Bound to the admitted claim's certificate.
    assert fa.claim_certificate_id == finding.certificate.certificate_id
    assert validate_claim_certificate(finding.certificate)
    # Carries the structured number and citations from the claim.
    assert fa.subject_id == "ACME"
    assert fa.metric == "operating_margin"
    assert fa.value == Decimal("0.184")
    assert fa.unit == "ratio"
    assert fa.citation_evidence_ids == ("EV-1",)
    # Readable sentence that renders the ratio as a percentage.
    assert "18.4%" in fa.text
    assert "ACME" in fa.text
    assert response.citations == ("EV-1",)


# --------------------------------------------------------------------------
# Non-admitted findings contribute no factual assertion (filtered)
# --------------------------------------------------------------------------


def test_rejected_finding_contributes_no_factual_assertion() -> None:
    req = make_answer_requirement(
        text="What was the operating margin?",
        weight=Decimal("1"),
        subject_id="ACME",
        metric="operating_margin",
    )
    response = synthesize(
        question="What was ACME's operating margin?",
        requirements=(req,),
        findings=(_finding(AdmissionOutcome.REJECTED),),
    )
    assert response.factual_assertions == ()
    assert response.answer_status is AnswerStatus.INSUFFICIENT_EVIDENCE


def test_abstained_finding_is_filtered_out() -> None:
    admitted = _finding(AdmissionOutcome.ADMITTED)
    abstained = _finding(
        AdmissionOutcome.ABSTAINED, subject_id="BETA", metric="revenue_growth"
    )
    req = make_answer_requirement(
        text="Operating margin?",
        weight=Decimal("1"),
        subject_id="ACME",
        metric="operating_margin",
    )
    response = synthesize(
        question="q", requirements=(req,), findings=(admitted, abstained)
    )
    # Only the admitted finding yields a factual assertion.
    assert len(response.factual_assertions) == 1
    assert response.factual_assertions[0].subject_id == "ACME"


# --------------------------------------------------------------------------
# Coverage -> status
# --------------------------------------------------------------------------


def test_full_coverage_is_complete_answer() -> None:
    finding = _finding()
    req = make_answer_requirement(
        text="Operating margin?",
        weight=Decimal("1"),
        subject_id="ACME",
        metric="operating_margin",
    )
    response = synthesize(question="q", requirements=(req,), findings=(finding,))
    assert response.coverage.score == Decimal("1")
    assert response.answer_status is AnswerStatus.COMPLETE_ANSWER
    assert response.coverage.status is AnswerStatus.COMPLETE_ANSWER
    assert response.unresolved_requirements == ()


def test_partial_coverage_is_partial_answer_with_unresolved() -> None:
    finding = _finding()
    addressed = make_answer_requirement(
        text="Operating margin?",
        weight=Decimal("1"),
        subject_id="ACME",
        metric="operating_margin",
    )
    unaddressed = make_answer_requirement(
        text="Revenue growth?",
        weight=Decimal("1"),
        subject_id="ACME",
        metric="revenue_growth",
    )
    response = synthesize(
        question="q",
        requirements=(addressed, unaddressed),
        findings=(finding,),
    )
    assert response.coverage.score == Decimal("0.5")
    assert response.answer_status is AnswerStatus.PARTIAL_ANSWER
    assert response.unresolved_requirements == (unaddressed.requirement_id,)
    assert len(response.limitations) >= 1


def test_requirements_but_no_admitted_findings_is_insufficient_evidence() -> None:
    req = make_answer_requirement(text="Operating margin?", weight=Decimal("1"))
    response = synthesize(question="q", requirements=(req,), findings=())
    assert response.factual_assertions == ()
    assert response.answer_status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert response.unresolved_requirements == (req.requirement_id,)


def test_no_requirements_is_unanswerable() -> None:
    response = synthesize(question="q", requirements=(), findings=())
    assert response.answer_status is AnswerStatus.UNANSWERABLE
    assert response.coverage.per_requirement == ()


# --------------------------------------------------------------------------
# Keyword-based coverage matching (requirement names neither subject nor metric)
# --------------------------------------------------------------------------


def test_keyword_coverage_matches_metric_text() -> None:
    finding = _finding()
    req = make_answer_requirement(
        text="Tell me about the operating margin.", weight=Decimal("1")
    )
    response = synthesize(question="q", requirements=(req,), findings=(finding,))
    assert response.coverage.score == Decimal("1")
    assert response.answer_status is AnswerStatus.COMPLETE_ANSWER


# --------------------------------------------------------------------------
# answer_text reads as an answer, not an id dump
# --------------------------------------------------------------------------


def test_answer_text_contains_value_and_is_not_an_id_list() -> None:
    finding = _finding()
    req = make_answer_requirement(
        text="Operating margin?",
        weight=Decimal("1"),
        subject_id="ACME",
        metric="operating_margin",
    )
    response = synthesize(question="What was the margin?", requirements=(req,), findings=(finding,))
    text = response.answer_text
    assert "18.4%" in text
    # Not merely a list of ids: the claim/evidence ids must not dominate the prose.
    assert finding.claim.candidate_claim_id not in text
    assert "EV-1" not in text
    assert len(text.split()) >= 5


def test_percentage_points_rendered_with_sign() -> None:
    finding = _finding(
        metric="operating_margin_change",
        value=Decimal("3.2"),
        unit="percentage_points",
    )
    req = make_answer_requirement(
        text="Margin change?",
        weight=Decimal("1"),
        subject_id="ACME",
        metric="operating_margin_change",
    )
    response = synthesize(question="q", requirements=(req,), findings=(finding,))
    assert "+3.2 percentage points" in response.factual_assertions[0].text


def test_validation_is_placeholder_ok() -> None:
    response = synthesize(question="q", requirements=(), findings=())
    assert response.validation.ok is True
    assert response.validation.unsupported_assertions == ()
    assert response.validation.issues == ()
