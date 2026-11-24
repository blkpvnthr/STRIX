"""Tests for the answer-first synthesis loop (R1 §16, §17.5).

These exercise :func:`strix.answering.pipeline.answer_question` end to end: it must
synthesize a substantive natural-language answer from admitted findings, validate
that every factual assertion binds to an admitted claim, strip anything that does
not, and re-derive coverage/status on the corrected set — never returning an
unsupported factual assertion and never degrading into an evidence dump
(R1 §17.4, §16). :func:`strix.answering.pipeline.render_markdown` renders the
answer-first CLI/API surface.
"""

from __future__ import annotations

from decimal import Decimal

from strix.answering.models import (
    AnswerStatus,
    make_answer_requirement,
)
from strix.answering.pipeline import answer_question, render_markdown
from strix.answering.synthesize import AdmittedFinding
from strix.evidence_graph.certificates import (
    ClaimCertificate,
    build_claim_certificate,
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
    evidence_id: str = "EV-1",
) -> AdmittedFinding:
    claim = _claim(
        subject_id=subject_id,
        metric=metric,
        value=value,
        unit=unit,
        evidence_id=evidence_id,
    )
    return AdmittedFinding(
        claim=claim,
        decision=_decision(claim, outcome),
        certificate=_certificate(claim),
    )


def _tampered_finding(**kwargs: object) -> AdmittedFinding:
    """An ADMITTED finding whose certificate content was altered after issuance.

    ``verified_value`` is part of certificate identity, so changing it leaves a
    stale ``certificate_id`` that fails integrity validation. ``synthesize`` still
    emits a factual assertion for it (its decision is ADMITTED), so this models an
    injected unsupported assertion the pipeline must strip.
    """
    finding = _finding(**kwargs)  # type: ignore[arg-type]
    tampered_cert = finding.certificate.model_copy(
        update={"verified_value": Decimal("99")}
    )
    return finding.model_copy(update={"certificate": tampered_cert})


# --------------------------------------------------------------------------
# End to end: admitted-only content, ok validation, readable answer
# --------------------------------------------------------------------------


def test_end_to_end_admitted_finding_is_answered_and_valid() -> None:
    finding = _finding()
    req = make_answer_requirement(
        text="What was the operating margin?",
        weight=Decimal("1"),
        subject_id="ACME",
        metric="operating_margin",
    )
    response = answer_question(
        question="What was ACME's operating margin?",
        requirements=(req,),
        findings=(finding,),
    )

    # It actually answers: magnitude is stated in prose, not as an id dump.
    assert "18.4%" in response.answer_text
    assert finding.claim.candidate_claim_id not in response.answer_text
    assert "EV-1" not in response.answer_text
    # One certificate-backed factual assertion, and validation passes.
    assert len(response.factual_assertions) == 1
    assert response.validation.ok is True
    assert response.validation.unsupported_assertions == ()
    assert response.answer_status is AnswerStatus.COMPLETE_ANSWER
    assert response.coverage.score == Decimal("1")


# --------------------------------------------------------------------------
# Injected unsupported assertion is stripped; the final response still answers
# --------------------------------------------------------------------------


def test_injected_unsupported_is_stripped_and_answer_survives() -> None:
    good = _finding(subject_id="ACME", metric="operating_margin", evidence_id="EV-1")
    tampered = _tampered_finding(
        subject_id="BETA", metric="revenue", value=Decimal("1000"), unit="USD",
        evidence_id="EV-2",
    )
    good_req = make_answer_requirement(
        text="Operating margin?",
        weight=Decimal("1"),
        subject_id="ACME",
        metric="operating_margin",
    )
    beta_req = make_answer_requirement(
        text="Revenue?",
        weight=Decimal("1"),
        subject_id="BETA",
        metric="revenue",
    )
    response = answer_question(
        question="How did ACME and BETA do?",
        requirements=(good_req, beta_req),
        findings=(good, tampered),
    )

    # The final response is fully valid: nothing unsupported remains.
    assert response.validation.ok is True
    assert response.validation.unsupported_assertions == ()
    texts = tuple(a.text for a in response.factual_assertions)
    # The good assertion survived; the tampered one is gone.
    assert any("18.4%" in t for t in texts)
    assert not any("BETA" in t for t in texts)
    assert "18.4%" in response.answer_text
    # Coverage was re-derived on the corrected set: the tampered requirement is now
    # unresolved, so the answer is partial and says so.
    assert response.answer_status is AnswerStatus.PARTIAL_ANSWER
    assert beta_req.requirement_id in response.unresolved_requirements
    assert len(response.limitations) >= 1


def test_all_findings_tampered_yields_insufficient_evidence_not_a_dump() -> None:
    tampered = _tampered_finding()
    req = make_answer_requirement(
        text="Operating margin?",
        weight=Decimal("1"),
        subject_id="ACME",
        metric="operating_margin",
    )
    response = answer_question(
        question="What was ACME's operating margin?",
        requirements=(req,),
        findings=(tampered,),
    )
    assert response.validation.ok is True
    assert response.factual_assertions == ()
    assert response.answer_status is AnswerStatus.INSUFFICIENT_EVIDENCE
    # States what is missing rather than dumping ids.
    assert req.requirement_id in response.unresolved_requirements
    assert len(response.limitations) >= 1


# --------------------------------------------------------------------------
# Partial coverage
# --------------------------------------------------------------------------


def test_partial_coverage_is_partial_answer_with_limitations() -> None:
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
    response = answer_question(
        question="q",
        requirements=(addressed, unaddressed),
        findings=(finding,),
    )
    assert response.answer_status is AnswerStatus.PARTIAL_ANSWER
    assert response.coverage.score == Decimal("0.5")
    assert unaddressed.requirement_id in response.unresolved_requirements
    assert len(response.limitations) >= 1
    assert response.validation.ok is True


# --------------------------------------------------------------------------
# No admitted findings
# --------------------------------------------------------------------------


def test_no_admitted_findings_states_what_is_missing() -> None:
    req = make_answer_requirement(
        text="What was the operating margin?",
        weight=Decimal("1"),
        subject_id="ACME",
        metric="operating_margin",
    )
    response = answer_question(
        question="What was ACME's operating margin?",
        requirements=(req,),
        findings=(),
    )
    assert response.answer_status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert response.factual_assertions == ()
    assert response.validation.ok is True
    # Not an evidence dump: it names the unmet requirement and notes the gap.
    assert req.requirement_id in response.unresolved_requirements
    assert len(response.limitations) >= 1
    assert "could not be answered" in response.answer_text


def test_rejected_findings_are_not_answered() -> None:
    rejected = _finding(AdmissionOutcome.REJECTED)
    req = make_answer_requirement(
        text="Operating margin?",
        weight=Decimal("1"),
        subject_id="ACME",
        metric="operating_margin",
    )
    response = answer_question(question="q", requirements=(req,), findings=(rejected,))
    assert response.factual_assertions == ()
    assert response.answer_status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert response.validation.ok is True


# --------------------------------------------------------------------------
# render_markdown
# --------------------------------------------------------------------------


def test_render_markdown_has_answer_bullets_citations_and_sections() -> None:
    finding = _finding()
    req = make_answer_requirement(
        text="Operating margin?",
        weight=Decimal("1"),
        subject_id="ACME",
        metric="operating_margin",
    )
    response = answer_question(
        question="What was the margin?", requirements=(req,), findings=(finding,)
    )
    md = render_markdown(response)

    # A lead answer with the magnitude.
    assert "18.4%" in md
    # Finding bullet with an inline numbered citation.
    assert "- ACME" in md
    assert "[1]" in md
    # Section headings present.
    assert "Limitations" in md
    assert "Unresolved requirements" in md
    assert "### Citations" in md
    assert "1. EV-1" in md


def test_render_markdown_reports_unresolved_requirements() -> None:
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
    response = answer_question(
        question="q", requirements=(addressed, unaddressed), findings=(finding,)
    )
    md = render_markdown(response)
    assert unaddressed.requirement_id in md
    # A limitations note is rendered.
    assert "Not addressed by admitted evidence" in md
