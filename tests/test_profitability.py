"""Deterministic calculations: exact Decimal margins and pp change."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from strix.analytics.profitability import (
    operating_margin,
    operating_margin_change_pp,
)
from strix.canonical import encode_decimal
from strix.errors import CalculationError
from strix.models import (
    Concept,
    Metric,
    SourceFact,
    Unit,
    ValidationStatus,
)

KNOWN_AT = datetime(2026, 7, 15, tzinfo=UTC)


def fact(concept: Concept, value: str, period: str = "2026-Q2") -> SourceFact:
    return SourceFact(
        fact_id=f"FACT-{concept.value}-{period}",
        subject_id="demo-company-000001",
        concept=concept,
        value=Decimal(value),
        unit=Unit.USD,
        observation_period=period,
        known_at=KNOWN_AT,
        source_artifact_id="ART-000000000000",
        source_locator="/periods/0/facts/0",
        validation_status=ValidationStatus.VALID,
    )


def margin(income: str, revenue: str, period: str = "2026-Q2"):
    return operating_margin(
        operating_income=fact(Concept.OPERATING_INCOME, income, period),
        revenue=fact(Concept.REVENUE, revenue, period),
    )


class TestOperatingMargin:
    def test_previous_period_margin_is_exactly_8_4_percent(self) -> None:
        result = margin("84000000", "1000000000", "2025-Q2")
        assert result.value == Decimal("0.084000")
        assert encode_decimal(result.value) == "0.084"
        assert result.unit is Unit.RATIO

    def test_current_period_margin_is_exactly_10_1_percent(self) -> None:
        result = margin("101000000", "1000000000")
        assert result.value == Decimal("0.101000")
        assert encode_decimal(result.value) == "0.101"

    def test_value_is_decimal_never_float(self) -> None:
        result = margin("101000000", "1000000000")
        assert isinstance(result.value, Decimal)
        assert not isinstance(result.value, float)
        # Exactness: a float division here would give 0.10100000000000000...
        assert str(result.value) == "0.101000"

    def test_zero_revenue_rejected(self) -> None:
        with pytest.raises(CalculationError, match="revenue is zero"):
            margin("84000000", "0")

    def test_negative_revenue_rejected(self) -> None:
        with pytest.raises(CalculationError, match="revenue is negative"):
            margin("84000000", "-1000000000")

    def test_float_input_rejected_by_model(self) -> None:
        with pytest.raises(ValueError, match="float"):
            fact_kwargs = fact(Concept.REVENUE, "1").model_dump()
            fact_kwargs["value"] = 0.084
            SourceFact.model_validate(fact_kwargs)

    def test_mismatched_periods_rejected(self) -> None:
        with pytest.raises(CalculationError, match="observation period"):
            operating_margin(
                operating_income=fact(Concept.OPERATING_INCOME, "84000000", "2025-Q2"),
                revenue=fact(Concept.REVENUE, "1000000000", "2026-Q2"),
            )

    def test_swapped_concepts_rejected(self) -> None:
        with pytest.raises(CalculationError, match="numerator"):
            operating_margin(
                operating_income=fact(Concept.REVENUE, "1000000000"),
                revenue=fact(Concept.OPERATING_INCOME, "84000000"),
            )

    def test_records_role_ordered_input_facts_and_version(self) -> None:
        income = fact(Concept.OPERATING_INCOME, "101000000")
        revenue = fact(Concept.REVENUE, "1000000000")
        result = operating_margin(operating_income=income, revenue=revenue)
        assert result.input_fact_ids == (income.fact_id, revenue.fact_id)
        assert result.calculation_version == "1.0.0"
        assert result.calculation_name is Metric.OPERATING_MARGIN

    def test_calculation_id_is_stable(self) -> None:
        first = margin("101000000", "1000000000")
        second = margin("101000000", "1000000000")
        assert first.calculation_id == second.calculation_id
        different = margin("102000000", "1000000000")
        assert different.calculation_id != first.calculation_id


class TestMarginChange:
    def test_change_is_exactly_1_7_percentage_points(self) -> None:
        previous = margin("84000000", "1000000000", "2025-Q2")
        current = margin("101000000", "1000000000", "2026-Q2")
        change = operating_margin_change_pp(current=current, previous=previous)
        assert change.value == Decimal("1.7000")
        assert encode_decimal(change.value) == "1.7"
        assert change.unit is Unit.PERCENTAGE_POINTS
        assert change.observation_period == "2025-Q2..2026-Q2"

    def test_percentage_points_not_percentage_change(self) -> None:
        # 8.4% -> 10.1% is +1.7 percentage points, NOT the ~20.2% relative
        # percentage change. The unit system enforces the distinction.
        previous = margin("84000000", "1000000000", "2025-Q2")
        current = margin("101000000", "1000000000", "2026-Q2")
        change = operating_margin_change_pp(current=current, previous=previous)
        relative_change_pct = (current.value - previous.value) / previous.value * Decimal("100")
        assert change.value != relative_change_pct.quantize(Decimal("0.0001"))
        assert change.unit is Unit.PERCENTAGE_POINTS

    def test_change_lineage_records_calcs_and_facts(self) -> None:
        previous = margin("84000000", "1000000000", "2025-Q2")
        current = margin("101000000", "1000000000", "2026-Q2")
        change = operating_margin_change_pp(current=current, previous=previous)
        assert change.input_calculation_ids == (
            current.calculation_id,
            previous.calculation_id,
        )
        assert change.input_fact_ids == current.input_fact_ids + previous.input_fact_ids

    def test_same_period_rejected(self) -> None:
        first = margin("84000000", "1000000000")
        second = margin("101000000", "1000000000")
        with pytest.raises(CalculationError, match="distinct observation periods"):
            operating_margin_change_pp(current=second, previous=first)


class TestRangeGuards:
    def test_astronomical_ratio_raises_calculation_error_not_decimal_error(
        self,
    ) -> None:
        # A ratio with more than 28 integer digits cannot be quantized to six
        # decimals within the working precision; that must surface as a typed
        # CalculationError, never a raw decimal.InvalidOperation traceback.
        with pytest.raises(CalculationError, match="out of the supported numeric range"):
            margin("1" + "0" * 40, "1")
