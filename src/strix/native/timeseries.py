"""Deterministic Decimal time-series statistics for the native layer (R1 §6/§7).

Every function in this module obeys a single numerical contract:

- Inputs are coerced through :func:`strix.native.arithmetic.as_decimal`, which
  forbids binary ``float`` and rejects NaN/Inf.
- All reductions, divisions, roots, logs, and exponentials run inside a *local*
  :class:`decimal.Decimal` context (precision :data:`~strix.native.arithmetic.ARITH_PRECISION`,
  rounding ``ROUND_HALF_EVEN``); the global decimal context is never mutated.
- Every scalar result and every tuple element is quantized to
  :data:`~strix.native.arithmetic.STAT_QUANTUM` (12 decimal places) so results
  are reproducible and canonically hashable.
- Invalid inputs (wrong length, too few observations, zero denominators,
  constant series where a statistic is undefined) raise
  :class:`strix.errors.CalculationError`.

Rolling windows use only current-and-past points (no look-ahead bias): the
``k``-th output of a windowed function summarizes ``series[k : k + window]``,
and the first output covers the first ``window`` points.

This module deliberately imports only from :mod:`strix.native.arithmetic` and
:mod:`strix.errors`; the few descriptive helpers it needs (mean, variance) are
implemented locally rather than imported from sibling stat modules.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from pydantic import Field

from strix.errors import CalculationError
from strix.models import StrixModel
from strix.native.arithmetic import (
    ARITH_PRECISION,
    STAT_QUANTUM,
    as_decimal,
    checked_sum,
    quantize,
)

__all__ = [
    "TrendFit",
    "absolute_change",
    "annualized_volatility",
    "autocorrelation",
    "cagr",
    "ewma",
    "growth_rate",
    "linear_trend",
    "moving_average",
    "percentage_change",
    "rolling_stdev",
    "volatility",
]


class TrendFit(StrixModel):
    """Ordinary-least-squares fit of a series against its index 0..n-1.

    Numerical contract: deterministic Decimal; all fields are quantized to
    :data:`~strix.native.arithmetic.STAT_QUANTUM`.
    """

    slope: Decimal = Field(description="OLS slope (change in value per index step).")
    intercept: Decimal = Field(description="OLS intercept (fitted value at index 0).")
    r_squared: Decimal = Field(description="Coefficient of determination in [0, 1].")


# --------------------------------------------------------------------------
# Internal helpers (local to this module by design — see module docstring)
# --------------------------------------------------------------------------


def _coerce_series(series: Sequence[object]) -> list[Decimal]:
    """Coerce every element to a finite Decimal (rejecting float/NaN/Inf)."""
    return [as_decimal(x) for x in series]


def _mean(values: Sequence[Decimal]) -> Decimal:
    """Exact arithmetic mean inside a local context (caller guarantees non-empty)."""
    return checked_sum(values) / Decimal(len(values))


def _variance(values: Sequence[Decimal], *, sample: bool) -> Decimal:
    """Sum-of-squares variance (sample divides by n-1, population by n).

    The caller must guarantee enough observations (>=2 for sample, >=1 for
    population). Runs inside a local context.
    """
    n = len(values)
    mean = _mean(values)
    ss = sum(((x - mean) * (x - mean) for x in values), Decimal(0))
    denom = Decimal(n - 1) if sample else Decimal(n)
    return ss / denom


def _q(value: Decimal) -> Decimal:
    """Quantize a result to the canonical statistical quantum."""
    return quantize(value, STAT_QUANTUM)


# --------------------------------------------------------------------------
# Change / growth
# --------------------------------------------------------------------------


def absolute_change(series: Sequence[object]) -> tuple[Decimal, ...]:
    """Consecutive first differences ``x[i] - x[i-1]`` (length ``n - 1``).

    Requires ``n >= 2``.
    """
    values = _coerce_series(series)
    if len(values) < 2:
        raise CalculationError("absolute_change requires at least 2 observations")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        return tuple(_q(values[i] - values[i - 1]) for i in range(1, len(values)))


def percentage_change(series: Sequence[object]) -> tuple[Decimal, ...]:
    """Consecutive simple returns ``x[i] / x[i-1] - 1`` (length ``n - 1``).

    Requires ``n >= 2``; a zero prior value is rejected (undefined ratio).
    """
    values = _coerce_series(series)
    if len(values) < 2:
        raise CalculationError("percentage_change requires at least 2 observations")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        out: list[Decimal] = []
        for i in range(1, len(values)):
            prior = values[i - 1]
            if prior == 0:
                raise CalculationError(
                    "percentage_change undefined: prior value is zero"
                )
            out.append(_q(values[i] / prior - 1))
        return tuple(out)


def growth_rate(first: object, last: object) -> Decimal:
    """Total growth ratio ``(last - first) / first``. Requires ``first != 0``."""
    f = as_decimal(first)
    last_v = as_decimal(last)
    if f == 0:
        raise CalculationError("growth_rate undefined: first value is zero")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        return _q((last_v - f) / f)


def cagr(begin: object, end: object, periods: object) -> Decimal:
    """Compound annual growth rate ``exp(ln(end/begin) / periods) - 1``.

    Uses Decimal ``ln``/``exp`` inside a local context. Requires ``begin > 0``,
    ``end > 0``, and ``periods > 0`` (``periods`` may be ``int`` or ``Decimal``).
    """
    b = as_decimal(begin)
    e = as_decimal(end)
    p = as_decimal(periods)
    if b <= 0:
        raise CalculationError("cagr requires begin > 0")
    if e <= 0:
        raise CalculationError("cagr requires end > 0")
    if p <= 0:
        raise CalculationError("cagr requires periods > 0")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        ratio = e / b
        rate = (ratio.ln() / p).exp() - 1
        return _q(rate)


# --------------------------------------------------------------------------
# Windowed statistics
# --------------------------------------------------------------------------


def _require_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise CalculationError(f"{name} must be an int")
    return value


def moving_average(series: Sequence[object], window: int) -> tuple[Decimal, ...]:
    """Simple moving average over a trailing window (length ``n - window + 1``).

    Requires ``window >= 1`` and ``n >= window``. No look-ahead: output ``k``
    averages ``series[k : k + window]``.
    """
    win = _require_int(window, "window")
    values = _coerce_series(series)
    if win < 1:
        raise CalculationError("moving_average requires window >= 1")
    if len(values) < win:
        raise CalculationError("moving_average requires n >= window")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        out: list[Decimal] = []
        for k in range(len(values) - win + 1):
            out.append(_q(_mean(values[k : k + win])))
        return tuple(out)


def rolling_stdev(
    series: Sequence[object], window: int, *, sample: bool = True
) -> tuple[Decimal, ...]:
    """Rolling standard deviation over a trailing window (length ``n - window + 1``).

    ``sample=True`` divides by ``window - 1``; ``sample=False`` divides by
    ``window``. Requires ``window >= 2`` and ``n >= window``. No look-ahead.
    """
    win = _require_int(window, "window")
    values = _coerce_series(series)
    if win < 2:
        raise CalculationError("rolling_stdev requires window >= 2")
    if len(values) < win:
        raise CalculationError("rolling_stdev requires n >= window")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        out: list[Decimal] = []
        for k in range(len(values) - win + 1):
            var = _variance(values[k : k + win], sample=sample)
            out.append(_q(var.sqrt()))
        return tuple(out)


def ewma(
    series: Sequence[object],
    *,
    span: object | None = None,
    alpha: object | None = None,
) -> tuple[Decimal, ...]:
    """Exponentially weighted moving average (length ``n``).

    Exactly one of ``span`` or ``alpha`` must be supplied. With a span,
    ``alpha = 2 / (span + 1)``; ``alpha`` must satisfy ``0 < alpha <= 1``. The
    recursion is seeded with ``series[0]`` and advances as
    ``y[i] = alpha * x[i] + (1 - alpha) * y[i-1]``.
    """
    values = _coerce_series(series)
    if not values:
        raise CalculationError("ewma requires at least 1 observation")
    if (span is None) == (alpha is None):
        raise CalculationError("ewma requires exactly one of span or alpha")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        if alpha is not None:
            a = as_decimal(alpha)
        else:
            span_v = as_decimal(span)
            if span_v <= 0:
                raise CalculationError("ewma requires span > 0")
            a = Decimal(2) / (span_v + 1)
        if not (0 < a <= 1):
            raise CalculationError("ewma requires 0 < alpha <= 1")
        one_minus = 1 - a
        y = values[0]
        out: list[Decimal] = [_q(y)]
        for x in values[1:]:
            y = a * x + one_minus * y
            out.append(_q(y))
        return tuple(out)


# --------------------------------------------------------------------------
# Volatility
# --------------------------------------------------------------------------


def volatility(returns: Sequence[object], *, sample: bool = True) -> Decimal:
    """Standard deviation of a return series (scalar).

    ``sample=True`` divides by ``n - 1`` (requires ``n >= 2``); ``sample=False``
    divides by ``n`` (requires ``n >= 1``). Implements its own variance.
    """
    values = _coerce_series(returns)
    if sample and len(values) < 2:
        raise CalculationError("sample volatility requires at least 2 observations")
    if not sample and len(values) < 1:
        raise CalculationError("population volatility requires at least 1 observation")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        return _q(_variance(values, sample=sample).sqrt())


def annualized_volatility(
    returns: Sequence[object], periods_per_year: object, *, sample: bool = True
) -> Decimal:
    """Per-period volatility scaled by ``sqrt(periods_per_year)``.

    Requires ``periods_per_year > 0``.
    """
    ppy = as_decimal(periods_per_year)
    if ppy <= 0:
        raise CalculationError("annualized_volatility requires periods_per_year > 0")
    values = _coerce_series(returns)
    if sample and len(values) < 2:
        raise CalculationError("sample volatility requires at least 2 observations")
    if not sample and len(values) < 1:
        raise CalculationError("population volatility requires at least 1 observation")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        vol = _variance(values, sample=sample).sqrt()
        return _q(vol * ppy.sqrt())


# --------------------------------------------------------------------------
# Autocorrelation / trend
# --------------------------------------------------------------------------


def autocorrelation(series: Sequence[object], lag: int) -> Decimal:
    """Pearson autocorrelation at integer ``lag >= 1``, result in ``[-1, 1]``.

    Correlates ``series[:-lag]`` with ``series[lag:]``. Requires ``n > lag + 1``
    (at least two overlapping pairs); a constant series on either leg is
    rejected (undefined correlation).
    """
    k = _require_int(lag, "lag")
    if k < 1:
        raise CalculationError("autocorrelation requires lag >= 1")
    values = _coerce_series(series)
    n = len(values)
    if n <= k + 1:
        raise CalculationError("autocorrelation requires n > lag + 1")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        xs = values[: n - k]
        ys = values[k:]
        mx = _mean(xs)
        my = _mean(ys)
        cov = sum(((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)), Decimal(0))
        sxx = sum(((x - mx) * (x - mx) for x in xs), Decimal(0))
        syy = sum(((y - my) * (y - my) for y in ys), Decimal(0))
        if sxx == 0 or syy == 0:
            raise CalculationError(
                "autocorrelation undefined: a constant (zero-variance) leg"
            )
        rho = cov / (sxx * syy).sqrt()
        return _q(rho)


def linear_trend(series: Sequence[object]) -> TrendFit:
    """OLS of value on index ``0..n-1``; returns slope, intercept, r_squared.

    Requires ``n >= 2``. The r_squared is undefined when the series has zero
    variance (constant), which is rejected.
    """
    values = _coerce_series(series)
    n = len(values)
    if n < 2:
        raise CalculationError("linear_trend requires at least 2 observations")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        xs = [Decimal(i) for i in range(n)]
        mx = _mean(xs)
        my = _mean(values)
        sxy = sum(((x - mx) * (y - my) for x, y in zip(xs, values, strict=True)), Decimal(0))
        sxx = sum(((x - mx) * (x - mx) for x in xs), Decimal(0))
        syy = sum(((y - my) * (y - my) for y in values), Decimal(0))
        # sxx is never zero for n >= 2 (distinct integer indices).
        slope = sxy / sxx
        intercept = my - slope * mx
        if syy == 0:
            raise CalculationError(
                "linear_trend r_squared undefined: series has zero variance"
            )
        r = sxy / (sxx * syy).sqrt()
        r_squared = r * r
        return TrendFit(
            slope=_q(slope),
            intercept=_q(intercept),
            r_squared=_q(r_squared),
        )
