"""Tests for offline evaluation metrics (R1 §30).

These exercise :mod:`strix.research_eval.scoring`: deterministic, exact-Decimal
metrics computed over a :class:`VerifiedResearchResponse` against a supplied
:class:`GroundTruth`, plus their micro-average aggregation.
"""

from __future__ import annotations

from decimal import Decimal

from strix.answering.models import (
    AnswerAssertion,
    AnswerCoverage,
    AnswerStatus,
    AnswerValidationResult,
    AssertionKind,
    RequirementCoverage,
    VerifiedResearchResponse,
)
from strix.research_eval.dataset import GroundTruth
from strix.research_eval.scoring import (
    MetricResult,
    aggregate_scores,
    score_response,
)

# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def _factual(text: str, *, cert: str = "CERT-1", cites: tuple[str, ...] = ()) -> AnswerAssertion:
    return AnswerAssertion(
        text=text,
        kind=AssertionKind.FACTUAL,
        claim_certificate_id=cert,
        citation_evidence_ids=cites,
    )


def _response(
    *,
    factual: tuple[AnswerAssertion, ...] = (),
    citations: tuple[str, ...] = (),
    per_requirement: tuple[RequirementCoverage, ...] = (),
    status: AnswerStatus = AnswerStatus.COMPLETE_ANSWER,
    unsupported: tuple[str, ...] = (),
) -> VerifiedResearchResponse:
    return VerifiedResearchResponse(
        question="Q?",
        answer_text="A.",
        sections=(),
        factual_assertions=factual,
        analytical_inferences=(),
        hypotheses=(),
        citations=citations,
        coverage=AnswerCoverage(
            score=Decimal(1) if per_requirement else Decimal(0),
            per_requirement=per_requirement,
            status=status,
        ),
        answer_status=status,
        limitations=(),
        unresolved_requirements=(),
        validation=AnswerValidationResult(
            ok=not unsupported,
            unsupported_assertions=unsupported,
            issues=(),
        ),
    )


def _truth(**overrides: object) -> GroundTruth:
    base: dict[str, object] = {
        "expected_answer_requirements": ("state the direction",),
        "expected_claims": ("revenue increased",),
    }
    base.update(overrides)
    return GroundTruth(**base)


def _metric(results: tuple[MetricResult, ...], name: str) -> MetricResult:
    (match,) = (m for m in results if m.name == name)
    return match


# --------------------------------------------------------------------------
# MetricResult shape
# --------------------------------------------------------------------------


def test_metric_result_reports_denominator() -> None:
    results = score_response(_response(), _truth())
    for m in results:
        assert isinstance(m.value, Decimal)
        assert isinstance(m.numerator, int)
        assert isinstance(m.denominator, int)


def test_score_response_is_deterministic() -> None:
    resp = _response(
        factual=(_factual("revenue increased", cites=("E1",)),),
        citations=("E1",),
        per_requirement=(
            RequirementCoverage(
                requirement_id="REQ-1", satisfaction=Decimal(1), satisfied=True
            ),
        ),
    )
    truth = _truth()
    assert score_response(resp, truth) == score_response(resp, truth)


# --------------------------------------------------------------------------
# verified_factual_precision
# --------------------------------------------------------------------------


def test_all_factual_match_gives_precision_one() -> None:
    resp = _response(
        factual=(
            _factual("Revenue increased"),  # case/space-insensitive
            _factual("  the index declined "),
        ),
    )
    truth = _truth(expected_claims=("revenue increased", "the index declined"))
    precision = _metric(score_response(resp, truth), "verified_factual_precision")
    assert precision.value == Decimal(1)
    assert precision.numerator == 2
    assert precision.denominator == 2


def test_non_matching_factual_lowers_precision() -> None:
    resp = _response(
        factual=(_factual("revenue increased"), _factual("margins collapsed")),
    )
    truth = _truth(expected_claims=("revenue increased",))
    precision = _metric(score_response(resp, truth), "verified_factual_precision")
    assert precision.numerator == 1
    assert precision.denominator == 2
    assert precision.value == Decimal(1) / Decimal(2)


# --------------------------------------------------------------------------
# reference_claim_coverage
# --------------------------------------------------------------------------


def test_reference_claim_coverage_counts_covered_expected() -> None:
    resp = _response(factual=(_factual("revenue increased"),))
    truth = _truth(expected_claims=("revenue increased", "costs fell"))
    cov = _metric(score_response(resp, truth), "reference_claim_coverage")
    assert cov.numerator == 1
    assert cov.denominator == 2


# --------------------------------------------------------------------------
# unsupported_claim_escape
# --------------------------------------------------------------------------


def test_unsupported_assertion_raises_escape_rate() -> None:
    resp = _response(
        factual=(_factual("revenue increased"), _factual("costs fell")),
        unsupported=("costs fell",),
    )
    escape = _metric(score_response(resp, _truth()), "unsupported_claim_escape")
    assert escape.numerator == 1
    assert escape.denominator == 2
    assert escape.value == Decimal(1) / Decimal(2)


def test_no_unsupported_assertion_zero_escape() -> None:
    resp = _response(factual=(_factual("revenue increased"),))
    escape = _metric(score_response(resp, _truth()), "unsupported_claim_escape")
    assert escape.numerator == 0
    assert escape.value == Decimal(0)


# --------------------------------------------------------------------------
# citation_support_accuracy
# --------------------------------------------------------------------------


def test_citation_support_accuracy_requires_grounded_citations() -> None:
    resp = _response(
        factual=(
            _factual("a", cites=("E1",)),  # grounded
            _factual("b", cites=("E9",)),  # cites unknown evidence
            _factual("c", cites=()),  # no citation at all
        ),
        citations=("E1", "E2"),
    )
    acc = _metric(score_response(resp, _truth()), "citation_support_accuracy")
    assert acc.numerator == 1
    assert acc.denominator == 3


# --------------------------------------------------------------------------
# answer_requirement_coverage
# --------------------------------------------------------------------------


def test_answer_requirement_coverage_from_response_coverage() -> None:
    resp = _response(
        per_requirement=(
            RequirementCoverage(
                requirement_id="REQ-1", satisfaction=Decimal(1), satisfied=True
            ),
            RequirementCoverage(
                requirement_id="REQ-2", satisfaction=Decimal(0), satisfied=False
            ),
        ),
    )
    arc = _metric(score_response(resp, _truth()), "answer_requirement_coverage")
    assert arc.numerator == 1
    assert arc.denominator == 2


# --------------------------------------------------------------------------
# appropriate_abstention
# --------------------------------------------------------------------------


def test_must_abstain_with_insufficient_evidence_is_appropriate() -> None:
    resp = _response(status=AnswerStatus.INSUFFICIENT_EVIDENCE)
    ab = _metric(
        score_response(resp, _truth(must_abstain=True, expected_claims=())),
        "appropriate_abstention",
    )
    assert ab.numerator == 1
    assert ab.denominator == 1


def test_must_abstain_but_answered_is_inappropriate() -> None:
    resp = _response(status=AnswerStatus.COMPLETE_ANSWER)
    ab = _metric(
        score_response(resp, _truth(must_abstain=True, expected_claims=())),
        "appropriate_abstention",
    )
    assert ab.numerator == 0
    assert ab.denominator == 1


def test_non_abstain_question_answered_is_appropriate() -> None:
    resp = _response(status=AnswerStatus.COMPLETE_ANSWER)
    ab = _metric(score_response(resp, _truth()), "appropriate_abstention")
    assert ab.numerator == 1


def test_non_abstain_question_that_abstains_is_inappropriate() -> None:
    resp = _response(status=AnswerStatus.INSUFFICIENT_EVIDENCE)
    ab = _metric(score_response(resp, _truth()), "appropriate_abstention")
    assert ab.numerator == 0


# --------------------------------------------------------------------------
# Aggregation (micro-average)
# --------------------------------------------------------------------------


def test_aggregate_micro_averages_numerators_and_denominators() -> None:
    q1 = score_response(
        _response(
            factual=(_factual("revenue increased"), _factual("wrong")),
        ),
        _truth(expected_claims=("revenue increased",)),
    )
    q2 = score_response(
        _response(
            factual=(_factual("costs fell"),),
        ),
        _truth(expected_claims=("costs fell",)),
    )
    agg = aggregate_scores((q1, q2))
    precision = agg["verified_factual_precision"]
    # q1: 1/2, q2: 1/1 -> micro 2/3
    assert precision.numerator == 2
    assert precision.denominator == 3
    assert precision.value == Decimal(2) / Decimal(3)


def test_aggregate_is_deterministic() -> None:
    per = (
        score_response(_response(factual=(_factual("x"),)), _truth()),
        score_response(_response(factual=(_factual("y"),)), _truth()),
    )
    assert aggregate_scores(per) == aggregate_scores(per)
