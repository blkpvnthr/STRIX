"""Deterministic financial calculators for the research agent.

Every function is exact :class:`~decimal.Decimal` arithmetic inside a local
context (the global decimal context is never mutated), mirroring
:mod:`strix.analytics.profitability`. These are the *only* place agent numbers
are computed, and the independent verifier recomputes claims by calling the very
same functions on the preserved observation series — so a claim's number is
accepted only if it reproduces here, never because the model asserted it.

All results are ratios/correlations quantized to six decimal places unless noted.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from itertools import pairwise

from strix.agent.models import CalculationMethod
from strix.errors import CalculationError

#: Version stamped on every AgentCalculation; bump when any formula changes.
CALC_VERSION = "1.0.0"

#: Six-decimal quantum for ratios, volatilities, and correlations.
RATIO_QUANTUM = Decimal("0.000001")

#: Default annualization factor (US equity trading days per year).
DEFAULT_PERIODS_PER_YEAR = 252

_PRECISION = 50
_ONE = Decimal(1)


def _q(value: Decimal) -> Decimal:
    """Quantize to the ratio quantum, collapsing negative zero."""
    out = value.quantize(RATIO_QUANTUM, rounding=ROUND_HALF_EVEN)
    return out.copy_abs() if out == 0 else out


def _check_levels(values: Sequence[Decimal], *, minimum: int) -> None:
    if len(values) < minimum:
        raise CalculationError(f"need at least {minimum} observations, got {len(values)}")
    for value in values:
        if not isinstance(value, Decimal):
            raise CalculationError("observation values must be Decimal")
        if not value.is_finite():
            raise CalculationError("observation values must be finite")


def period_return(values: Sequence[Decimal]) -> Decimal:
    """Simple return over the window: ``last / first - 1`` (ratio)."""
    _check_levels(values, minimum=2)
    first, last = values[0], values[-1]
    if first <= 0:
        raise CalculationError("period return requires a positive starting value")
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return _q(last / first - _ONE)


def cumulative_return(values: Sequence[Decimal]) -> Decimal:
    """Cumulative return of a level series — equivalent to ``last / first - 1``."""
    return period_return(values)


def max_drawdown(values: Sequence[Decimal]) -> Decimal:
    """Largest peak-to-trough decline as a non-positive ratio (e.g. -0.20)."""
    _check_levels(values, minimum=2)
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        peak = values[0]
        worst = Decimal(0)
        for value in values:
            if value > peak:
                peak = value
            if peak > 0:
                drawdown = value / peak - _ONE
                if drawdown < worst:
                    worst = drawdown
        return _q(worst)


def realized_volatility(
    values: Sequence[Decimal], *, periods_per_year: int = DEFAULT_PERIODS_PER_YEAR
) -> Decimal:
    """Annualized realized volatility: sample stdev of log returns * sqrt(ppy)."""
    _check_levels(values, minimum=3)
    if periods_per_year <= 0:
        raise CalculationError("periods_per_year must be positive")
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        log_returns: list[Decimal] = []
        for prev, curr in pairwise(values):
            if prev <= 0 or curr <= 0:
                raise CalculationError("volatility requires positive prices for log returns")
            try:
                log_returns.append((curr / prev).ln())
            except InvalidOperation as exc:
                raise CalculationError("log return is undefined for the given prices") from exc
        n = len(log_returns)
        mean = sum(log_returns, Decimal(0)) / n
        variance = sum(((r - mean) ** 2 for r in log_returns), Decimal(0)) / (n - 1)
        stdev = variance.sqrt()
        annualized = stdev * Decimal(periods_per_year).sqrt()
        return _q(annualized)


def moving_average(values: Sequence[Decimal], *, window: int) -> Decimal:
    """Simple moving average of the last ``window`` observations."""
    if window <= 0:
        raise CalculationError("moving-average window must be positive")
    _check_levels(values, minimum=window)
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        tail = values[-window:]
        return _q(sum(tail, Decimal(0)) / window)


def relative_performance(a: Sequence[Decimal], b: Sequence[Decimal]) -> Decimal:
    """Difference in period return: ``return(a) - return(b)`` (ratio)."""
    return _q(period_return(a) - period_return(b))


def correlation(a: Sequence[Decimal], b: Sequence[Decimal]) -> Decimal:
    """Pearson correlation of the two series' simple returns, in [-1, 1]."""
    _check_levels(a, minimum=3)
    _check_levels(b, minimum=3)
    if len(a) != len(b):
        raise CalculationError("correlation requires two equal-length series")
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        ra = _simple_returns(a)
        rb = _simple_returns(b)
        n = len(ra)
        mean_a = sum(ra, Decimal(0)) / n
        mean_b = sum(rb, Decimal(0)) / n
        cov = sum(((x - mean_a) * (y - mean_b) for x, y in zip(ra, rb, strict=True)), Decimal(0))
        var_a = sum(((x - mean_a) ** 2 for x in ra), Decimal(0))
        var_b = sum(((y - mean_b) ** 2 for y in rb), Decimal(0))
        if var_a <= 0 or var_b <= 0:
            raise CalculationError("correlation is undefined for a constant series")
        r = cov / (var_a.sqrt() * var_b.sqrt())
        # Clamp tiny numeric overshoot into the valid range.
        r = max(Decimal(-1), min(Decimal(1), r))
        return _q(r)


def _simple_returns(values: Sequence[Decimal]) -> list[Decimal]:
    out: list[Decimal] = []
    for prev, curr in pairwise(values):
        if prev == 0:
            raise CalculationError("simple return is undefined when a prior value is zero")
        out.append(curr / prev - _ONE)
    return out


#: Methods that consume two series (role-ordered: [primary, benchmark]).
_TWO_SERIES = frozenset({CalculationMethod.RELATIVE_PERFORMANCE, CalculationMethod.CORRELATION})


def recompute(
    method: CalculationMethod,
    series_values: Sequence[Sequence[Decimal]],
    parameters: dict[str, str],
) -> Decimal:
    """Recompute one calculation from preserved series values (verifier entry).

    ``series_values`` is role-ordered: one series for single-series methods, two
    for relative performance and correlation.
    """
    expected = 2 if method in _TWO_SERIES else 1
    if len(series_values) != expected:
        raise CalculationError(
            f"{method.value} expects {expected} series, got {len(series_values)}"
        )
    if method is CalculationMethod.PERIOD_RETURN:
        return period_return(series_values[0])
    if method is CalculationMethod.CUMULATIVE_RETURN:
        return cumulative_return(series_values[0])
    if method is CalculationMethod.MAX_DRAWDOWN:
        return max_drawdown(series_values[0])
    if method is CalculationMethod.REALIZED_VOLATILITY:
        ppy = _int_param(parameters, "periods_per_year", DEFAULT_PERIODS_PER_YEAR)
        return realized_volatility(series_values[0], periods_per_year=ppy)
    if method is CalculationMethod.MOVING_AVERAGE:
        window = _int_param(parameters, "window", 0)
        return moving_average(series_values[0], window=window)
    if method is CalculationMethod.RELATIVE_PERFORMANCE:
        return relative_performance(series_values[0], series_values[1])
    if method is CalculationMethod.CORRELATION:
        return correlation(series_values[0], series_values[1])
    raise CalculationError(f"unsupported calculation method {method!r}")


def _int_param(parameters: dict[str, str], name: str, default: int) -> int:
    raw = parameters.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise CalculationError(f"parameter {name} must be an integer, got {raw!r}") from exc
