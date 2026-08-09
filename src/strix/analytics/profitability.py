"""Deterministic operating-profitability calculations.

All arithmetic is exact ``Decimal`` inside a local context (the global
decimal context is never mutated). Authoritative values:

- Operating margin: ``operating_income / revenue`` as a *ratio*, quantized
  to six decimal places (e.g. ``0.084000``).
- Operating-margin change: ``(current - previous) * 100`` in *percentage
  points*, quantized to four decimal places (e.g. ``1.7000``).

Percentage points measure the arithmetic difference between two percentages
(10.1% - 8.4% = 1.7 pp). This is distinct from percentage change
((10.1 - 8.4) / 8.4 ≈ 20.2%), which STRIX deliberately does not report here.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext

from strix.canonical import make_id
from strix.errors import CalculationError
from strix.models import CalculationResult, Concept, Metric, SourceFact, Unit

#: Version recorded on every CalculationResult and in the run manifest.
CALCULATION_VERSION = "1.0.0"

#: Authoritative quantum for margin ratios (six decimal places).
RATIO_QUANTUM = Decimal("0.000001")

#: Authoritative quantum for percentage-point changes (four decimal places).
PP_QUANTUM = Decimal("0.0001")

_HUNDRED = Decimal("100")
_ARITH_PRECISION = 34


def operating_margin(*, operating_income: SourceFact, revenue: SourceFact) -> CalculationResult:
    """Compute operating margin (ratio) for one period from two source facts.

    Rejects zero and negative revenue: a margin over non-positive revenue is
    not meaningful for this prototype.
    """
    if operating_income.concept is not Concept.OPERATING_INCOME:
        raise CalculationError(
            f"numerator must be operating_income, got {operating_income.concept}"
        )
    if revenue.concept is not Concept.REVENUE:
        raise CalculationError(f"denominator must be revenue, got {revenue.concept}")
    if operating_income.unit is not Unit.USD or revenue.unit is not Unit.USD:
        raise CalculationError("operating margin requires USD inputs")
    if operating_income.subject_id != revenue.subject_id:
        raise CalculationError("operating margin inputs must share one subject")
    if operating_income.observation_period != revenue.observation_period:
        raise CalculationError("operating margin inputs must share one observation period")
    if revenue.value == 0:
        raise CalculationError("revenue is zero; operating margin is undefined")
    if revenue.value < 0:
        raise CalculationError("revenue is negative; rejected by this prototype")

    try:
        with localcontext() as ctx:
            ctx.prec = _ARITH_PRECISION
            ctx.rounding = ROUND_HALF_EVEN
            value = (operating_income.value / revenue.value).quantize(RATIO_QUANTUM)
    except InvalidOperation as exc:
        raise CalculationError("operating margin is out of the supported numeric range") from exc

    # Role-ordered: [numerator, denominator].
    input_fact_ids = (operating_income.fact_id, revenue.fact_id)
    calculation_id = make_id(
        "CALC",
        {
            "calculation_name": Metric.OPERATING_MARGIN,
            "calculation_version": CALCULATION_VERSION,
            "subject_id": revenue.subject_id,
            "input_fact_ids": list(input_fact_ids),
            "value": value,
            "unit": Unit.RATIO,
            "observation_period": revenue.observation_period,
        },
    )
    return CalculationResult(
        calculation_id=calculation_id,
        calculation_name=Metric.OPERATING_MARGIN,
        calculation_version=CALCULATION_VERSION,
        subject_id=revenue.subject_id,
        value=value,
        unit=Unit.RATIO,
        observation_period=revenue.observation_period,
        input_fact_ids=input_fact_ids,
    )


def operating_margin_change_pp(
    *, current: CalculationResult, previous: CalculationResult
) -> CalculationResult:
    """Compute the margin change between two periods in percentage points."""
    for margin in (current, previous):
        if margin.calculation_name is not Metric.OPERATING_MARGIN:
            raise CalculationError(
                f"change inputs must be operating margins, got {margin.calculation_name}"
            )
        if margin.unit is not Unit.RATIO:
            raise CalculationError(f"change inputs must be ratios, got {margin.unit}")
    if current.subject_id != previous.subject_id:
        raise CalculationError("margin change inputs must share one subject")
    if current.observation_period == previous.observation_period:
        raise CalculationError("margin change requires two distinct observation periods")

    try:
        with localcontext() as ctx:
            ctx.prec = _ARITH_PRECISION
            ctx.rounding = ROUND_HALF_EVEN
            value = ((current.value - previous.value) * _HUNDRED).quantize(PP_QUANTUM)
    except InvalidOperation as exc:
        raise CalculationError(
            "operating margin change is out of the supported numeric range"
        ) from exc

    observation_period = f"{previous.observation_period}..{current.observation_period}"
    # Role-ordered facts: current period's facts first, then previous period's.
    input_fact_ids = current.input_fact_ids + previous.input_fact_ids
    # Role-ordered calculations: [current, previous].
    input_calculation_ids = (current.calculation_id, previous.calculation_id)
    calculation_id = make_id(
        "CALC",
        {
            "calculation_name": Metric.OPERATING_MARGIN_CHANGE_PP,
            "calculation_version": CALCULATION_VERSION,
            "subject_id": current.subject_id,
            "input_fact_ids": list(input_fact_ids),
            "input_calculation_ids": list(input_calculation_ids),
            "value": value,
            "unit": Unit.PERCENTAGE_POINTS,
            "observation_period": observation_period,
        },
    )
    return CalculationResult(
        calculation_id=calculation_id,
        calculation_name=Metric.OPERATING_MARGIN_CHANGE_PP,
        calculation_version=CALCULATION_VERSION,
        subject_id=current.subject_id,
        value=value,
        unit=Unit.PERCENTAGE_POINTS,
        observation_period=observation_period,
        input_fact_ids=input_fact_ids,
        input_calculation_ids=input_calculation_ids,
    )
