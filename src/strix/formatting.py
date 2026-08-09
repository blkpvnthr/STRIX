"""Pure, deterministic display formatting and prose rendering.

These functions convert authoritative Decimal values into human-readable
strings and render claim prose from verified structured values. They perform
no financial calculation beyond exact scaling/quantization for display, and
they never touch files, the network, or the terminal.

Consistency contract for the finding sentence: the displayed "from" and "to"
percentages and the displayed percentage-point difference are all derived
from ONE rounding step, so the visible numbers always add up
(to - from == difference at one decimal place). When rounding collapses a
genuine but tiny change to 0.0, the sentence says so explicitly instead of
asserting an increase of "0.0 percentage points".

The sentence is a pure function of structured claim values; the verifier
re-renders it and rejects any claim whose statement differs, so displayed
prose can never silently disagree with the verified numbers.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from strix.models import Direction, Metric, Unit

#: Display quantum: margins and percentage-point changes show one decimal.
DISPLAY_QUANTUM = Decimal("0.1")
_HUNDRED = Decimal("100")
_ARITH_PRECISION = 34


def _no_negative_zero(value: Decimal) -> Decimal:
    """Collapse -0.0 (a rounding artifact) to 0.0 for display."""
    return value.copy_abs() if value == 0 else value


def _percent_decimal(ratio: Decimal) -> Decimal:
    """One-decimal percent value for a ratio: Decimal('0.084') -> Decimal('8.4')."""
    with localcontext() as ctx:
        ctx.prec = _ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        return _no_negative_zero((ratio * _HUNDRED).quantize(DISPLAY_QUANTUM))


def display_percent(ratio: Decimal) -> str:
    """Render a ratio as a one-decimal percentage: Decimal('0.084') -> '8.4%'."""
    return f"{format(_percent_decimal(ratio), 'f')}%"


def display_percentage_points(value: Decimal) -> str:
    """Render a signed pp value: Decimal('1.7') -> '1.7 percentage points'."""
    with localcontext() as ctx:
        ctx.prec = _ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        quantized = _no_negative_zero(value.quantize(DISPLAY_QUANTUM))
    return f"{format(quantized, 'f')} percentage points"


def display_value(metric: Metric, unit: Unit, value: Decimal) -> str:
    """Canonical display string for an evidence value."""
    if unit is Unit.RATIO:
        return display_percent(value)
    if unit is Unit.PERCENTAGE_POINTS:
        return display_percentage_points(value)
    raise ValueError(f"no display rule for unit {unit!r} (metric {metric!r})")


def direction_from_change(change: Decimal) -> Direction:
    """Structured direction implied by a signed change value."""
    if change > 0:
        return Direction.INCREASED
    if change < 0:
        return Direction.DECREASED
    return Direction.UNCHANGED


def render_statement(
    direction: Direction,
    previous_ratio: Decimal,
    current_ratio: Decimal,
) -> str:
    """Render the profitability finding from verified structured values only.

    ``direction`` comes from the sign of the authoritative (unrounded)
    change; the displayed magnitude is the exact difference of the two
    displayed one-decimal percentages, so the sentence is always internally
    consistent. Display rounding is monotone, so the displayed difference can
    shrink to zero but can never contradict the authoritative direction.
    """
    previous_pct = _percent_decimal(previous_ratio)
    current_pct = _percent_decimal(current_ratio)
    delta = _no_negative_zero(current_pct - previous_pct)
    current_display = f"{format(current_pct, 'f')}%"
    previous_display = f"{format(previous_pct, 'f')}%"

    if direction is Direction.UNCHANGED:
        return f"Operating margin was unchanged at {current_display}."
    if delta == 0:
        return (
            f"Operating margin was effectively unchanged at {current_display} "
            f"(a change of less than 0.1 percentage points)."
        )
    magnitude = f"{format(abs(delta), 'f')} percentage points"
    if direction is Direction.INCREASED:
        return (
            f"Operating margin increased from {previous_display} to "
            f"{current_display}, an improvement of {magnitude}."
        )
    return (
        f"Operating margin decreased from {previous_display} to "
        f"{current_display}, a decline of {magnitude}."
    )
