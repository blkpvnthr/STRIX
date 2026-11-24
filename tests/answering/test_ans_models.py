"""Tests for the typed answer/response models (R1 §17.3)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.answering.models import (
    AnswerAssertion,
    AnswerCoverage,
    AnsweringError,
    AnswerRequirement,
    AnswerSection,
    AnswerStatus,
    AnswerValidationResult,
    AssertionKind,
    RequirementCoverage,
    RequirementImportance,
    VerifiedResearchResponse,
    make_answer_requirement,
)
from strix.errors import StrixError

# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


def test_assertion_kind_membership() -> None:
    assert {k.value for k in AssertionKind} == {
        "factual",
        "analytical_inference",
        "hypothesis",
    }


def test_answer_status_membership() -> None:
    assert {s.value for s in AnswerStatus} == {
        "complete_answer",
        "partial_answer",
        "insufficient_evidence",
        "unanswerable",
    }


def test_requirement_importance_membership() -> None:
    assert {i.value for i in RequirementImportance} == {
        "critical",
        "high",
        "normal",
        "low",
    }


def test_requirement_importance_weight_is_decimal_and_positive() -> None:
    for importance in RequirementImportance:
        weight = importance.weight
        assert isinstance(weight, Decimal)
        assert weight > 0
    # Monotonic ordering: critical outranks the rest.
    assert (
        RequirementImportance.CRITICAL.weight
        > RequirementImportance.HIGH.weight
        > RequirementImportance.NORMAL.weight
        > RequirementImportance.LOW.weight
    )


# --------------------------------------------------------------------------
# Error
# --------------------------------------------------------------------------


def test_answering_error_is_strix_error() -> None:
    assert issubclass(AnsweringError, StrixError)
    with pytest.raises(StrixError):
        raise AnsweringError("boom")


# --------------------------------------------------------------------------
# AnswerRequirement + factory
# --------------------------------------------------------------------------


def test_make_answer_requirement_content_id() -> None:
    req = make_answer_requirement(
        text="What was the operating margin change?",
        weight=Decimal("0.75"),
        subject_id="SUBJ-1",
        metric="operating_margin_change_pp",
    )
    assert req.requirement_id.startswith("REQ-")
    assert req.text == "What was the operating margin change?"
    assert req.weight == Decimal("0.75")


def test_make_answer_requirement_is_deterministic() -> None:
    assert (
        make_answer_requirement(text="Revenue trend?", weight=Decimal("1")).requirement_id
        == make_answer_requirement(text="Revenue trend?", weight=Decimal("1")).requirement_id
    )


def test_make_answer_requirement_distinct_content_distinct_id() -> None:
    a = make_answer_requirement(text="A", weight=Decimal("1"))
    b = make_answer_requirement(text="B", weight=Decimal("1"))
    assert a.requirement_id != b.requirement_id


def test_requirement_weight_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        AnswerRequirement(requirement_id="REQ-x", text="t", weight=Decimal("0"))
    with pytest.raises(ValidationError):
        AnswerRequirement(requirement_id="REQ-x", text="t", weight=Decimal("-1"))


def test_requirement_weight_rejects_float() -> None:
    with pytest.raises(ValidationError):
        AnswerRequirement(requirement_id="REQ-x", text="t", weight=0.75)  # type: ignore[arg-type,unused-ignore]


def test_requirement_frozen() -> None:
    req = make_answer_requirement(text="t", weight=Decimal("1"))
    with pytest.raises(ValidationError):
        req.text = "changed"  # type: ignore[misc]


# --------------------------------------------------------------------------
# AnswerAssertion
# --------------------------------------------------------------------------


def test_factual_assertion_requires_certificate() -> None:
    with pytest.raises(ValidationError):
        AnswerAssertion(
            text="Operating margin increased by 3.2pp.",
            kind=AssertionKind.FACTUAL,
        )


def test_factual_assertion_with_certificate_ok() -> None:
    assertion = AnswerAssertion(
        text="Operating margin increased by 3.2pp.",
        kind=AssertionKind.FACTUAL,
        claim_certificate_id="CERT-abc",
        value=Decimal("3.2"),
        unit="percentage_points",
        citation_evidence_ids=("EV-1",),
    )
    assert assertion.claim_certificate_id == "CERT-abc"
    assert assertion.value == Decimal("3.2")


def test_analytical_and_hypothesis_need_no_certificate() -> None:
    analytical = AnswerAssertion(
        text="This likely reflects operating leverage.",
        kind=AssertionKind.ANALYTICAL_INFERENCE,
    )
    hypothesis = AnswerAssertion(
        text="Margins may compress if input costs rise.",
        kind=AssertionKind.HYPOTHESIS,
    )
    assert analytical.claim_certificate_id is None
    assert hypothesis.claim_certificate_id is None


def test_assertion_value_rejects_float() -> None:
    with pytest.raises(ValidationError):
        AnswerAssertion(
            text="t",
            kind=AssertionKind.ANALYTICAL_INFERENCE,
            value=3.2,  # type: ignore[arg-type,unused-ignore]
        )


# --------------------------------------------------------------------------
# Coverage / validation
# --------------------------------------------------------------------------


def test_requirement_coverage_satisfaction_bounds() -> None:
    with pytest.raises(ValidationError):
        RequirementCoverage(
            requirement_id="REQ-1", satisfaction=Decimal("1.5"), satisfied=True
        )
    with pytest.raises(ValidationError):
        RequirementCoverage(
            requirement_id="REQ-1", satisfaction=Decimal("-0.1"), satisfied=False
        )


def test_answer_coverage_score_bounds() -> None:
    with pytest.raises(ValidationError):
        AnswerCoverage(
            score=Decimal("2"),
            per_requirement=(),
            status=AnswerStatus.COMPLETE_ANSWER,
        )


# --------------------------------------------------------------------------
# VerifiedResearchResponse (full construction)
# --------------------------------------------------------------------------


def test_full_verified_research_response() -> None:
    factual = AnswerAssertion(
        text="Operating margin rose 3.2pp to 18.4%.",
        kind=AssertionKind.FACTUAL,
        claim_certificate_id="CERT-1",
        subject_id="SUBJ-1",
        metric="operating_margin_change_pp",
        value=Decimal("3.2"),
        unit="percentage_points",
        citation_evidence_ids=("EV-1", "EV-2"),
    )
    analytical = AnswerAssertion(
        text="The expansion appears driven by operating leverage.",
        kind=AssertionKind.ANALYTICAL_INFERENCE,
    )
    hypothesis = AnswerAssertion(
        text="Further gains depend on sustained revenue growth.",
        kind=AssertionKind.HYPOTHESIS,
    )
    section = AnswerSection(heading="Profitability", assertions=(factual, analytical))
    coverage = AnswerCoverage(
        score=Decimal("1"),
        per_requirement=(
            RequirementCoverage(
                requirement_id="REQ-1", satisfaction=Decimal("1"), satisfied=True
            ),
        ),
        status=AnswerStatus.COMPLETE_ANSWER,
    )
    validation = AnswerValidationResult(
        ok=True, unsupported_assertions=(), issues=()
    )
    response = VerifiedResearchResponse(
        question="How did operating margin change?",
        answer_text="Operating margin rose 3.2 percentage points to 18.4%.",
        sections=(section,),
        factual_assertions=(factual,),
        analytical_inferences=(analytical,),
        hypotheses=(hypothesis,),
        citations=("EV-1", "EV-2"),
        coverage=coverage,
        answer_status=AnswerStatus.COMPLETE_ANSWER,
        limitations=("Single fiscal-year comparison.",),
        unresolved_requirements=(),
        validation=validation,
    )
    assert response.answer_status is AnswerStatus.COMPLETE_ANSWER
    assert response.factual_assertions[0].claim_certificate_id == "CERT-1"
    assert response.citations == ("EV-1", "EV-2")


def test_response_frozen() -> None:
    validation = AnswerValidationResult(ok=True, unsupported_assertions=(), issues=())
    coverage = AnswerCoverage(
        score=Decimal("0"), per_requirement=(), status=AnswerStatus.UNANSWERABLE
    )
    response = VerifiedResearchResponse(
        question="q",
        answer_text="a",
        sections=(),
        factual_assertions=(),
        analytical_inferences=(),
        hypotheses=(),
        citations=(),
        coverage=coverage,
        answer_status=AnswerStatus.UNANSWERABLE,
        limitations=(),
        unresolved_requirements=(),
        validation=validation,
    )
    with pytest.raises(ValidationError):
        response.answer_text = "changed"  # type: ignore[misc]
