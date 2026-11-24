"""Tests for independent response validation (R1 §17.4, fail-closed).

These exercise :func:`strix.answering.validate.validate_response` and
:func:`strix.answering.validate.strip_unsupported`: every *factual* assertion in
a response must bind, by certificate id, to an admitted finding whose claim
asserts the same ``(subject, metric, value, unit)``; anything else is treated as
unsupported (fail-closed).
"""

from __future__ import annotations

from decimal import Decimal

from strix.answering.models import (
    AnswerAssertion,
    AnswerCoverage,
    AnswerSection,
    AnswerStatus,
    AnswerValidationResult,
    AssertionKind,
    VerifiedResearchResponse,
)
from strix.answering.validate import (
    AdmittedFinding,
    strip_unsupported,
    validate_response,
)
from strix.evidence_graph.certificates import build_claim_certificate
from strix.evidence_graph.nodes import (
    AdmissionOutcome,
    Assertion,
    CandidateClaim,
    VerificationOutcome,
)
from strix.evidence_graph.predicates import AdmissionDecision

# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def _finding(
    *,
    subject_id: str = "SUBJ-1",
    metric: str = "operating_margin_change_pp",
    value: Decimal = Decimal("3.2"),
    unit: str = "percentage_points",
    evidence_ids: tuple[str, ...] = ("EV-1", "EV-2"),
    outcome: AdmissionOutcome = AdmissionOutcome.ADMITTED,
    tolerance: Decimal | None = None,
) -> AdmittedFinding:
    assertion = Assertion(
        metric=metric,
        asserted_value=value,
        unit=unit,
        evidence_id=evidence_ids[0],
    )
    claim = CandidateClaim(
        candidate_claim_id="CC-1",
        subject_id=subject_id,
        claim_type="metric_change",
        statement="Operating margin changed.",
        evidence_ids=evidence_ids,
        assertions=(assertion,),
    )
    cert = build_claim_certificate(
        claim_id=claim.candidate_claim_id,
        canonical_claim_digest="digest",
        evidence_graph_snapshot_digest="snapshot",
        supporting_evidence_ids=evidence_ids,
        dependency_closure=(),
        predicate_results=(),
        verification_policy_version="policy-v1",
        verifier_version="verifier-v1",
        computation_certificate_refs=(),
        verified_value=value,
        measurement_unit=unit,
        numerical_tolerance=tolerance,
    )
    decision = AdmissionDecision(
        outcome=outcome,
        verification_outcome=VerificationOutcome.VERIFIED,
        predicate_results=(),
        policy_version="policy-v1",
        claim_id=claim.candidate_claim_id,
    )
    return AdmittedFinding(certificate=cert, claim=claim, decision=decision)


def _factual(
    cert_id: str,
    *,
    text: str = "Operating margin rose 3.2pp.",
    subject_id: str = "SUBJ-1",
    metric: str = "operating_margin_change_pp",
    value: Decimal = Decimal("3.2"),
    unit: str = "percentage_points",
    citations: tuple[str, ...] = ("EV-1",),
) -> AnswerAssertion:
    return AnswerAssertion(
        text=text,
        kind=AssertionKind.FACTUAL,
        claim_certificate_id=cert_id,
        subject_id=subject_id,
        metric=metric,
        value=value,
        unit=unit,
        citation_evidence_ids=citations,
    )


def _response(
    *,
    factual: tuple[AnswerAssertion, ...] = (),
    analytical: tuple[AnswerAssertion, ...] = (),
    hypotheses: tuple[AnswerAssertion, ...] = (),
    answer_text: str = "An answer.",
) -> VerifiedResearchResponse:
    section = AnswerSection(
        heading="Findings",
        assertions=factual + analytical,
    ) if (factual or analytical) else AnswerSection(
        heading="Findings", assertions=(AnswerAssertion(
            text="placeholder", kind=AssertionKind.ANALYTICAL_INFERENCE),),
    )
    coverage = AnswerCoverage(
        score=Decimal("1"),
        per_requirement=(),
        status=AnswerStatus.COMPLETE_ANSWER,
    )
    validation = AnswerValidationResult(ok=True, unsupported_assertions=(), issues=())
    return VerifiedResearchResponse(
        question="How did operating margin change?",
        answer_text=answer_text,
        sections=(section,),
        factual_assertions=factual,
        analytical_inferences=analytical,
        hypotheses=hypotheses,
        citations=(),
        coverage=coverage,
        answer_status=AnswerStatus.COMPLETE_ANSWER,
        limitations=(),
        unresolved_requirements=(),
        validation=validation,
    )


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------


def test_supported_factual_assertion_is_ok() -> None:
    finding = _finding()
    cert_id = finding.certificate.certificate_id
    response = _response(factual=(_factual(cert_id),))
    result = validate_response(
        response, frozenset({cert_id}), {cert_id: finding}
    )
    assert result.ok is True
    assert result.unsupported_assertions == ()
    assert result.issues == ()


def test_hypothesis_without_certificate_is_allowed() -> None:
    finding = _finding()
    cert_id = finding.certificate.certificate_id
    hypothesis = AnswerAssertion(
        text="Margins may compress if input costs rise.",
        kind=AssertionKind.HYPOTHESIS,
    )
    analytical = AnswerAssertion(
        text="The gain likely reflects operating leverage.",
        kind=AssertionKind.ANALYTICAL_INFERENCE,
    )
    response = _response(
        factual=(_factual(cert_id),),
        analytical=(analytical,),
        hypotheses=(hypothesis,),
    )
    result = validate_response(response, frozenset({cert_id}), {cert_id: finding})
    assert result.ok is True


# --------------------------------------------------------------------------
# Unsupported paths (fail-closed)
# --------------------------------------------------------------------------


def test_forged_certificate_id_is_unsupported() -> None:
    finding = _finding()
    cert_id = finding.certificate.certificate_id
    bad = _factual("CLAIMCERT-forged", text="Forged factual claim.")
    response = _response(factual=(bad,))
    result = validate_response(
        response, frozenset({cert_id}), {cert_id: finding}
    )
    assert result.ok is False
    assert "Forged factual claim." in result.unsupported_assertions
    assert result.issues  # a human-readable reason was recorded


def test_unknown_certificate_id_is_unsupported() -> None:
    # Certificate id is present in the admitted set but no finding backs it.
    finding = _finding()
    cert_id = finding.certificate.certificate_id
    bad = _factual("CLAIMCERT-missing", text="No finding backs this.")
    response = _response(factual=(bad,))
    result = validate_response(
        response,
        frozenset({cert_id, "CLAIMCERT-missing"}),
        {cert_id: finding},
    )
    assert result.ok is False
    assert "No finding backs this." in result.unsupported_assertions


def test_value_mismatch_is_unsupported() -> None:
    finding = _finding(value=Decimal("3.2"))
    cert_id = finding.certificate.certificate_id
    bad = _factual(cert_id, text="Wrong magnitude.", value=Decimal("9.9"))
    response = _response(factual=(bad,))
    result = validate_response(response, frozenset({cert_id}), {cert_id: finding})
    assert result.ok is False
    assert "Wrong magnitude." in result.unsupported_assertions


def test_metric_mismatch_is_unsupported() -> None:
    finding = _finding(metric="operating_margin_change_pp")
    cert_id = finding.certificate.certificate_id
    bad = _factual(cert_id, text="Wrong metric.", metric="revenue_growth_pct")
    response = _response(factual=(bad,))
    result = validate_response(response, frozenset({cert_id}), {cert_id: finding})
    assert result.ok is False
    assert "Wrong metric." in result.unsupported_assertions


def test_unit_mismatch_is_unsupported() -> None:
    finding = _finding(unit="percentage_points")
    cert_id = finding.certificate.certificate_id
    bad = _factual(cert_id, text="Wrong unit.", unit="usd")
    response = _response(factual=(bad,))
    result = validate_response(response, frozenset({cert_id}), {cert_id: finding})
    assert result.ok is False
    assert "Wrong unit." in result.unsupported_assertions


def test_subject_mismatch_is_unsupported() -> None:
    finding = _finding(subject_id="SUBJ-1")
    cert_id = finding.certificate.certificate_id
    bad = _factual(cert_id, text="Wrong subject.", subject_id="SUBJ-OTHER")
    response = _response(factual=(bad,))
    result = validate_response(response, frozenset({cert_id}), {cert_id: finding})
    assert result.ok is False
    assert "Wrong subject." in result.unsupported_assertions


def test_not_admitted_finding_is_unsupported() -> None:
    finding = _finding(outcome=AdmissionOutcome.REJECTED)
    cert_id = finding.certificate.certificate_id
    bad = _factual(cert_id, text="Rejected finding.")
    response = _response(factual=(bad,))
    # Even if the id is handed in as "admitted", the decision says otherwise.
    result = validate_response(response, frozenset({cert_id}), {cert_id: finding})
    assert result.ok is False
    assert "Rejected finding." in result.unsupported_assertions


def test_citation_not_in_backing_evidence_is_unsupported() -> None:
    finding = _finding(evidence_ids=("EV-1", "EV-2"))
    cert_id = finding.certificate.certificate_id
    bad = _factual(cert_id, text="Bad citation.", citations=("EV-999",))
    response = _response(factual=(bad,))
    result = validate_response(response, frozenset({cert_id}), {cert_id: finding})
    assert result.ok is False
    assert "Bad citation." in result.unsupported_assertions


def test_missing_certificate_id_is_unsupported_fail_closed() -> None:
    # A factual assertion whose cert id is absent must be rejected even though the
    # model normally forbids constructing one (build it bypassing validation).
    finding = _finding()
    cert_id = finding.certificate.certificate_id
    bad = AnswerAssertion.model_construct(
        text="Factual without a certificate.",
        kind=AssertionKind.FACTUAL,
        claim_certificate_id=None,
        subject_id="SUBJ-1",
        metric="operating_margin_change_pp",
        value=Decimal("3.2"),
        unit="percentage_points",
        citation_evidence_ids=(),
    )
    # Containers re-validate nested assertions, so bypass validation there too.
    section = AnswerSection.model_construct(heading="Findings", assertions=(bad,))
    coverage = AnswerCoverage(
        score=Decimal("1"), per_requirement=(), status=AnswerStatus.COMPLETE_ANSWER
    )
    base_validation = AnswerValidationResult(
        ok=True, unsupported_assertions=(), issues=()
    )
    response = VerifiedResearchResponse.model_construct(
        question="q",
        answer_text="Factual without a certificate.",
        sections=(section,),
        factual_assertions=(bad,),
        analytical_inferences=(),
        hypotheses=(),
        citations=(),
        coverage=coverage,
        answer_status=AnswerStatus.COMPLETE_ANSWER,
        limitations=(),
        unresolved_requirements=(),
        validation=base_validation,
    )
    result = validate_response(response, frozenset({cert_id}), {cert_id: finding})
    assert result.ok is False
    assert "Factual without a certificate." in result.unsupported_assertions


def test_tampered_certificate_is_unsupported() -> None:
    finding = _finding()
    # Corrupt the stored certificate id so validate_claim_certificate fails.
    tampered_cert = finding.certificate.model_copy(
        update={"verified_value": Decimal("99")}
    )
    tampered = finding.model_copy(update={"certificate": tampered_cert})
    cert_id = tampered.certificate.certificate_id  # stale id, no longer matches content
    bad = _factual(cert_id, text="Tampered cert.")
    response = _response(factual=(bad,))
    result = validate_response(response, frozenset({cert_id}), {cert_id: tampered})
    assert result.ok is False
    assert "Tampered cert." in result.unsupported_assertions


# --------------------------------------------------------------------------
# Tolerance
# --------------------------------------------------------------------------


def test_value_within_tolerance_is_supported() -> None:
    finding = _finding(value=Decimal("3.2"), tolerance=Decimal("0.05"))
    cert_id = finding.certificate.certificate_id
    good = _factual(cert_id, value=Decimal("3.23"))
    response = _response(factual=(good,))
    result = validate_response(response, frozenset({cert_id}), {cert_id: finding})
    assert result.ok is True


# --------------------------------------------------------------------------
# strip_unsupported
# --------------------------------------------------------------------------


def test_strip_unsupported_removes_bad_keeps_good() -> None:
    finding = _finding()
    cert_id = finding.certificate.certificate_id
    good = _factual(
        cert_id, text="Operating margin rose 3.2pp.", citations=("EV-1",)
    )
    bad = _factual("CLAIMCERT-forged", text="Revenue tripled overnight.")
    response = _response(
        factual=(good, bad),
        answer_text="Operating margin rose 3.2pp. Revenue tripled overnight.",
    )
    validation = validate_response(
        response, frozenset({cert_id}), {cert_id: finding}
    )
    assert validation.ok is False

    corrected = strip_unsupported(response, validation)
    texts = tuple(a.text for a in corrected.factual_assertions)
    assert "Operating margin rose 3.2pp." in texts
    assert "Revenue tripled overnight." not in texts
    # The bad sentence is scrubbed from the prose answer; the good one remains.
    assert "Revenue tripled overnight." not in corrected.answer_text
    assert "Operating margin rose 3.2pp." in corrected.answer_text
    # And the corrected response re-validates clean.
    assert corrected.validation.ok is True
    # Sections no longer carry the stripped assertion either.
    section_texts = {
        a.text for s in corrected.sections for a in s.assertions
    }
    assert "Revenue tripled overnight." not in section_texts


def test_strip_unsupported_noop_when_all_supported() -> None:
    finding = _finding()
    cert_id = finding.certificate.certificate_id
    good = _factual(cert_id)
    response = _response(factual=(good,))
    validation = validate_response(
        response, frozenset({cert_id}), {cert_id: finding}
    )
    corrected = strip_unsupported(response, validation)
    assert corrected.factual_assertions == response.factual_assertions
    assert corrected.validation.ok is True
