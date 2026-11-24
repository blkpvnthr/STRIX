"""Tests for R2-C uncertainty assessment (honest, non-fabricated).

The assessor derives an ordinal uncertainty :class:`UncertaintyLevel` plus
explicit named :class:`UncertaintyComponents` and typed reason codes from an
admitted-evidence picture. It never fabricates a probability: there is no
numeric confidence field, and the five status dimensions (R1 §2-C) are kept
separate and never collapsed into one score.

Coverage:
- full coverage + fresh + no contradiction -> low;
- partial coverage -> moderate;
- low coverage / contradiction / stale -> high;
- no admitted evidence for required items -> insufficient + abstention;
- the five status dimensions are distinct fields and never collapsed;
- float is rejected on the Decimal evidence_sufficiency field;
- the abstention control cannot be overridden away;
- determinism across repeated calls.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.assurance.uncertainty import (
    StatusDimensions,
    UncertaintyAssessment,
    UncertaintyComponents,
    UncertaintyError,
    UncertaintyLevel,
    UncertaintyReasonCode,
    assess_uncertainty,
)
from strix.errors import StrixError


def _full() -> UncertaintyAssessment:
    return assess_uncertainty(
        total_requirements=3,
        admitted_requirement_ids=frozenset({"R1", "R2", "R3"}),
        required_requirement_ids=frozenset({"R1", "R2", "R3"}),
        contradiction_count=0,
        max_evidence_age_seconds=10,
        freshness_limit_seconds=100,
        has_confidence_interval=False,
        authorization_status="granted",
    )


# --------------------------------------------------------------------------
# Level derivation
# --------------------------------------------------------------------------


def test_full_coverage_fresh_no_contradiction_is_low() -> None:
    assessment = _full()
    assert assessment.level is UncertaintyLevel.LOW
    assert assessment.components.evidence_sufficiency == Decimal(1)
    assert assessment.components.freshness_ok is True
    assert assessment.components.missing_requirements == ()
    assert assessment.components.abstention_recommended is False
    assert UncertaintyReasonCode.FULL_COVERAGE.value in assessment.reason_codes


def test_partial_coverage_is_moderate() -> None:
    assessment = assess_uncertainty(
        total_requirements=4,
        admitted_requirement_ids=frozenset({"R1", "R2", "R3"}),
        required_requirement_ids=frozenset({"R1", "R2", "R3", "R4"}),
        contradiction_count=0,
        max_evidence_age_seconds=10,
        freshness_limit_seconds=100,
        has_confidence_interval=False,
        authorization_status="granted",
    )
    assert assessment.level is UncertaintyLevel.MODERATE
    assert assessment.components.evidence_sufficiency == Decimal(3) / Decimal(4)
    assert assessment.components.missing_requirements == ("R4",)
    assert assessment.components.abstention_recommended is False
    assert UncertaintyReasonCode.PARTIAL_COVERAGE.value in assessment.reason_codes


def test_low_coverage_is_high() -> None:
    assessment = assess_uncertainty(
        total_requirements=4,
        admitted_requirement_ids=frozenset({"R1"}),
        required_requirement_ids=frozenset({"R1", "R2", "R3", "R4"}),
        contradiction_count=0,
        max_evidence_age_seconds=10,
        freshness_limit_seconds=100,
        has_confidence_interval=False,
        authorization_status="granted",
    )
    assert assessment.level is UncertaintyLevel.HIGH
    assert assessment.components.evidence_sufficiency < Decimal("0.5")
    assert UncertaintyReasonCode.LOW_EVIDENCE_SUFFICIENCY.value in assessment.reason_codes


def test_contradiction_forces_high_even_with_full_coverage() -> None:
    assessment = assess_uncertainty(
        total_requirements=3,
        admitted_requirement_ids=frozenset({"R1", "R2", "R3"}),
        required_requirement_ids=frozenset({"R1", "R2", "R3"}),
        contradiction_count=2,
        max_evidence_age_seconds=10,
        freshness_limit_seconds=100,
        has_confidence_interval=False,
        authorization_status="granted",
    )
    assert assessment.level is UncertaintyLevel.HIGH
    assert assessment.components.source_disagreement_count == 2
    assert UncertaintyReasonCode.SOURCE_DISAGREEMENT.value in assessment.reason_codes


def test_stale_evidence_forces_high() -> None:
    assessment = assess_uncertainty(
        total_requirements=3,
        admitted_requirement_ids=frozenset({"R1", "R2", "R3"}),
        required_requirement_ids=frozenset({"R1", "R2", "R3"}),
        contradiction_count=0,
        max_evidence_age_seconds=1000,
        freshness_limit_seconds=100,
        has_confidence_interval=False,
        authorization_status="granted",
    )
    assert assessment.level is UncertaintyLevel.HIGH
    assert assessment.components.freshness_ok is False
    assert UncertaintyReasonCode.STALE_EVIDENCE.value in assessment.reason_codes


def test_no_admitted_evidence_is_insufficient_and_recommends_abstention() -> None:
    assessment = assess_uncertainty(
        total_requirements=3,
        admitted_requirement_ids=frozenset(),
        required_requirement_ids=frozenset({"R1", "R2", "R3"}),
        contradiction_count=0,
        max_evidence_age_seconds=None,
        freshness_limit_seconds=None,
        has_confidence_interval=False,
        authorization_status="granted",
    )
    assert assessment.level is UncertaintyLevel.INSUFFICIENT
    assert assessment.components.abstention_recommended is True
    assert assessment.components.evidence_sufficiency == Decimal(0)
    assert assessment.components.missing_requirements == ("R1", "R2", "R3")
    assert UncertaintyReasonCode.INSUFFICIENT_EVIDENCE.value in assessment.reason_codes
    assert UncertaintyReasonCode.ABSTENTION_RECOMMENDED.value in assessment.reason_codes


def test_admitted_but_none_of_required_is_insufficient() -> None:
    # Admitted evidence exists but none of it covers a required item.
    assessment = assess_uncertainty(
        total_requirements=2,
        admitted_requirement_ids=frozenset({"X1", "X2"}),
        required_requirement_ids=frozenset({"R1", "R2"}),
        contradiction_count=0,
        max_evidence_age_seconds=10,
        freshness_limit_seconds=100,
        has_confidence_interval=False,
        authorization_status="granted",
    )
    assert assessment.level is UncertaintyLevel.INSUFFICIENT
    assert assessment.components.abstention_recommended is True


# --------------------------------------------------------------------------
# Status dimensions (R1 §2-C): five SEPARATE fields, never collapsed
# --------------------------------------------------------------------------


def test_five_status_dimensions_are_distinct_fields() -> None:
    dims = _full().dimensions
    names = set(StatusDimensions.model_fields)
    assert names == {
        "verification_status",
        "evidence_quality",
        "answer_completeness",
        "analytical_uncertainty",
        "authorization_status",
    }
    # Distinct, independently-populated string dimensions (not one score).
    values = [
        dims.verification_status,
        dims.evidence_quality,
        dims.answer_completeness,
        dims.analytical_uncertainty,
        dims.authorization_status,
    ]
    assert all(isinstance(v, str) and v for v in values)
    assert dims.authorization_status == "granted"


def test_authorization_status_is_passed_through_verbatim() -> None:
    assessment = assess_uncertainty(
        total_requirements=1,
        admitted_requirement_ids=frozenset({"R1"}),
        required_requirement_ids=frozenset({"R1"}),
        contradiction_count=0,
        max_evidence_age_seconds=10,
        freshness_limit_seconds=100,
        has_confidence_interval=False,
        authorization_status="denied",
    )
    assert assessment.dimensions.authorization_status == "denied"


def test_statistical_uncertainty_recorded_separately() -> None:
    assessment = assess_uncertainty(
        total_requirements=2,
        admitted_requirement_ids=frozenset({"R1", "R2"}),
        required_requirement_ids=frozenset({"R1", "R2"}),
        contradiction_count=0,
        max_evidence_age_seconds=10,
        freshness_limit_seconds=100,
        has_confidence_interval=True,
        authorization_status="granted",
    )
    assert assessment.components.statistical_uncertainty_present is True
    assert (
        UncertaintyReasonCode.STATISTICAL_UNCERTAINTY.value in assessment.reason_codes
    )
    # Statistical uncertainty surfaces on its own dimension, not folded into level.
    assert "statistical" in assessment.dimensions.analytical_uncertainty


# --------------------------------------------------------------------------
# Honesty mandate: no fabricated probability
# --------------------------------------------------------------------------


def test_assessment_has_no_probability_field() -> None:
    # No numeric confidence/probability anywhere in the closed schema.
    forbidden = {"probability", "confidence", "confidence_probability", "score"}
    for model in (UncertaintyAssessment, UncertaintyComponents, StatusDimensions):
        assert not (set(model.model_fields) & forbidden)


def test_no_calibrated_probability_reason_code_always_present() -> None:
    assert (
        UncertaintyReasonCode.NO_CALIBRATED_PROBABILITY.value in _full().reason_codes
    )


def test_float_rejected_on_evidence_sufficiency() -> None:
    with pytest.raises(ValidationError):
        UncertaintyComponents(
            evidence_sufficiency=0.5,
            freshness_ok=True,
            source_disagreement_count=0,
            missing_requirements=(),
            statistical_uncertainty_present=False,
            abstention_recommended=False,
        )


def test_models_are_frozen_and_closed() -> None:
    components = _full().components
    with pytest.raises(ValidationError):
        UncertaintyComponents(
            evidence_sufficiency=Decimal(1),
            freshness_ok=True,
            source_disagreement_count=0,
            missing_requirements=(),
            statistical_uncertainty_present=False,
            abstention_recommended=False,
            injected_probability=Decimal("0.99"),  # type: ignore[call-arg]
        )
    with pytest.raises(ValidationError):
        components.model_copy(update={"evidence_sufficiency": Decimal(0)}).__setattr__(
            "freshness_ok", False
        )


# --------------------------------------------------------------------------
# Assurance control cannot be overridden
# --------------------------------------------------------------------------


def test_abstention_control_cannot_be_bypassed_by_authorization() -> None:
    # Even an explicit "granted" authorization cannot turn an insufficient
    # evidence picture into a non-abstaining one.
    assessment = assess_uncertainty(
        total_requirements=2,
        admitted_requirement_ids=frozenset(),
        required_requirement_ids=frozenset({"R1", "R2"}),
        contradiction_count=0,
        max_evidence_age_seconds=1,
        freshness_limit_seconds=10_000,
        has_confidence_interval=True,
        authorization_status="granted",
    )
    assert assessment.level is UncertaintyLevel.INSUFFICIENT
    assert assessment.components.abstention_recommended is True


def test_confidence_interval_cannot_downgrade_level_below_high() -> None:
    # Contradictions keep the level at high regardless of other favourable signals.
    assessment = assess_uncertainty(
        total_requirements=2,
        admitted_requirement_ids=frozenset({"R1", "R2"}),
        required_requirement_ids=frozenset({"R1", "R2"}),
        contradiction_count=1,
        max_evidence_age_seconds=1,
        freshness_limit_seconds=10_000,
        has_confidence_interval=True,
        authorization_status="granted",
    )
    assert assessment.level is UncertaintyLevel.HIGH


# --------------------------------------------------------------------------
# Input validation and determinism
# --------------------------------------------------------------------------


def test_negative_total_requirements_rejected() -> None:
    with pytest.raises(UncertaintyError):
        assess_uncertainty(
            total_requirements=-1,
            admitted_requirement_ids=frozenset(),
            required_requirement_ids=frozenset(),
            contradiction_count=0,
            max_evidence_age_seconds=None,
            freshness_limit_seconds=None,
            has_confidence_interval=False,
            authorization_status="granted",
        )


def test_negative_contradiction_count_rejected() -> None:
    with pytest.raises(UncertaintyError):
        assess_uncertainty(
            total_requirements=1,
            admitted_requirement_ids=frozenset({"R1"}),
            required_requirement_ids=frozenset({"R1"}),
            contradiction_count=-1,
            max_evidence_age_seconds=None,
            freshness_limit_seconds=None,
            has_confidence_interval=False,
            authorization_status="granted",
        )


def test_negative_age_rejected() -> None:
    with pytest.raises(UncertaintyError):
        assess_uncertainty(
            total_requirements=1,
            admitted_requirement_ids=frozenset({"R1"}),
            required_requirement_ids=frozenset({"R1"}),
            contradiction_count=0,
            max_evidence_age_seconds=-5,
            freshness_limit_seconds=100,
            has_confidence_interval=False,
            authorization_status="granted",
        )


def test_empty_authorization_status_rejected() -> None:
    with pytest.raises(UncertaintyError):
        assess_uncertainty(
            total_requirements=1,
            admitted_requirement_ids=frozenset({"R1"}),
            required_requirement_ids=frozenset({"R1"}),
            contradiction_count=0,
            max_evidence_age_seconds=10,
            freshness_limit_seconds=100,
            has_confidence_interval=False,
            authorization_status="   ",
        )


def test_uncertainty_error_is_strix_error() -> None:
    assert issubclass(UncertaintyError, StrixError)


def test_determinism() -> None:
    first = _full()
    second = _full()
    assert first == second
    assert first.reason_codes == second.reason_codes
