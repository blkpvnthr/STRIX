"""Descriptive statistics for the native quantitative layer (R1).

Numerical contract: every public function is **deterministic exact Decimal**.
All inputs are coerced through :func:`strix.native.arithmetic.as_decimal`
(``float`` is forbidden, NaN/Inf rejected); heavy arithmetic runs inside a
*local* decimal context at :data:`~strix.native.arithmetic.ARITH_PRECISION` with
``ROUND_HALF_EVEN`` (the global context is never mutated); every scalar and
matrix-cell result is quantized to
:data:`~strix.native.arithmetic.STAT_QUANTUM`. Invalid inputs — wrong length,
too few observations, zero denominators, constant series where a statistic is
undefined — raise :class:`strix.errors.CalculationError`.

Structured results are returned as frozen :class:`strix.models.StrixModel`
subclasses (see :class:`DescriptiveSummary`).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from strix.errors import CalculationError
from strix.models import DecimalValue, StrixModel
from strix.native.arithmetic import (
    ARITH_PRECISION,
    STAT_QUANTUM,
    as_decimal,
    checked_div,
    checked_sum,
    quantize,
)

__all__ = [
    "DescriptiveSummary",
    "coverage",
    "data_range",
    "describe",
    "iqr",
    "kurtosis",
    "mad",
    "maximum",
    "mean",
    "median",
    "minimum",
    "percentile",
    "quantile",
    "skewness",
    "stdev",
    "variance",
    "weighted_mean",
]


# --------------------------------------------------------------------------
# Internal helpers (duplicated locally per module-isolation discipline)
# --------------------------------------------------------------------------


def _coerce(values: Sequence[object], *, what: str = "values") -> list[Decimal]:
    """Coerce a non-empty sequence to finite Decimals; reject empties/floats."""
    items = [as_decimal(v) for v in values]
    if not items:
        raise CalculationError(f"{what} must contain at least one observation")
    return items


def _q(value: Decimal) -> Decimal:
    """Quantize a scalar result to the canonical statistical quantum."""
    return quantize(value, STAT_QUANTUM)


def _sorted(values: Sequence[Decimal]) -> list[Decimal]:
    return sorted(values)


def _mean_exact(values: Sequence[Decimal]) -> Decimal:
    """Unquantized arithmetic mean (for internal composition)."""
    return checked_div(checked_sum(values), Decimal(len(values)))


def _median_exact(values: Sequence[Decimal]) -> Decimal:
    """Unquantized median of a non-empty sequence (sorted internally)."""
    ordered = _sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return checked_div(ordered[mid - 1] + ordered[mid], Decimal(2))


def _quantile_exact(values: Sequence[Decimal], q: Decimal) -> Decimal:
    """Unquantized R-7 (linear-interpolation) quantile. ``q`` in [0, 1]."""
    if q < 0 or q > 1:
        raise CalculationError(f"quantile q must lie in [0, 1], got {q}")
    ordered = _sorted(values)
    n = len(ordered)
    if n == 1:
        return ordered[0]
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        h = (Decimal(n) - 1) * q
        lo = int(h)  # floor for non-negative h
        if lo >= n - 1:
            return ordered[-1]
        frac = h - Decimal(lo)
        return +(ordered[lo] + frac * (ordered[lo + 1] - ordered[lo]))


def _pop_variance_exact(values: Sequence[Decimal], mu: Decimal) -> Decimal:
    """Unquantized population variance about a precomputed mean ``mu``."""
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        sq = sum(((v - mu) ** 2 for v in values), Decimal(0))
    return checked_div(sq, Decimal(len(values)))


def _sqrt_exact(value: Decimal) -> Decimal:
    """Unquantized square root inside the local high-precision context."""
    if value < 0:
        raise CalculationError("cannot take the square root of a negative value")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        return +value.sqrt()


# --------------------------------------------------------------------------
# Central tendency
# --------------------------------------------------------------------------


def mean(values: Sequence[object]) -> Decimal:
    """Arithmetic mean ``sum(x) / n``. Requires ``n >= 1``."""
    items = _coerce(values)
    return _q(_mean_exact(items))


def weighted_mean(values: Sequence[object], weights: Sequence[object]) -> Decimal:
    """Weighted mean ``sum(w*x) / sum(w)``.

    ``values`` and ``weights`` must be equal length and ``sum(weights) != 0``.
    """
    xs = _coerce(values)
    ws = _coerce(weights, what="weights")
    if len(xs) != len(ws):
        raise CalculationError(
            f"values and weights must have equal length ({len(xs)} != {len(ws)})"
        )
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        numerator = sum((w * x for w, x in zip(ws, xs, strict=True)), Decimal(0))
    denominator = checked_sum(ws)
    if denominator == 0:
        raise CalculationError("sum of weights must be non-zero")
    return _q(checked_div(numerator, denominator))


def median(values: Sequence[object]) -> Decimal:
    """Median: the middle value, or the mean of the two middle values."""
    items = _coerce(values)
    return _q(_median_exact(items))


# --------------------------------------------------------------------------
# Order statistics
# --------------------------------------------------------------------------


def quantile(values: Sequence[object], q: object) -> Decimal:
    """R-7 (linear-interpolation) quantile at ``q`` in [0, 1].

    Uses ``h = (N - 1) * q`` and interpolates between the bracketing order
    statistics, matching ``statistics.quantiles(..., method="inclusive")``.
    """
    items = _coerce(values)
    q_dec = as_decimal(q)
    return _q(_quantile_exact(items, q_dec))


def percentile(values: Sequence[object], p: object) -> Decimal:
    """Percentile at ``p`` in [0, 100]; equal to ``quantile(values, p/100)``."""
    p_dec = as_decimal(p)
    if p_dec < 0 or p_dec > 100:
        raise CalculationError(f"percentile p must lie in [0, 100], got {p_dec}")
    items = _coerce(values)
    q_dec = checked_div(p_dec, Decimal(100))
    return _q(_quantile_exact(items, q_dec))


def iqr(values: Sequence[object]) -> Decimal:
    """Interquartile range: ``quantile(0.75) - quantile(0.25)``."""
    items = _coerce(values)
    hi = _quantile_exact(items, Decimal("0.75"))
    lo = _quantile_exact(items, Decimal("0.25"))
    return _q(hi - lo)


def mad(values: Sequence[object]) -> Decimal:
    """Median absolute deviation: ``median(|x - median(x)|)``."""
    items = _coerce(values)
    center = _median_exact(items)
    deviations = [abs(v - center) for v in items]
    return _q(_median_exact(deviations))


# --------------------------------------------------------------------------
# Dispersion
# --------------------------------------------------------------------------


def variance(values: Sequence[object], *, sample: bool = True) -> Decimal:
    """Variance about the mean.

    ``sample=True`` divides by ``n - 1`` (unbiased; requires ``n >= 2``);
    ``sample=False`` divides by ``n`` (population; requires ``n >= 1``).
    """
    items = _coerce(values)
    n = len(items)
    if sample and n < 2:
        raise CalculationError("sample variance requires at least two observations")
    mu = _mean_exact(items)
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        ss = sum(((v - mu) ** 2 for v in items), Decimal(0))
    denominator = Decimal(n - 1) if sample else Decimal(n)
    return _q(checked_div(ss, denominator))


def stdev(values: Sequence[object], *, sample: bool = True) -> Decimal:
    """Standard deviation: ``sqrt(variance(values, sample=sample))``."""
    items = _coerce(values)
    n = len(items)
    if sample and n < 2:
        raise CalculationError("sample stdev requires at least two observations")
    mu = _mean_exact(items)
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        ss = sum(((v - mu) ** 2 for v in items), Decimal(0))
    denominator = Decimal(n - 1) if sample else Decimal(n)
    var = checked_div(ss, denominator)
    return _q(_sqrt_exact(var))


def minimum(values: Sequence[object]) -> Decimal:
    """Smallest value."""
    return _q(min(_coerce(values)))


def maximum(values: Sequence[object]) -> Decimal:
    """Largest value."""
    return _q(max(_coerce(values)))


def data_range(values: Sequence[object]) -> Decimal:
    """Range: ``max(values) - min(values)``."""
    items = _coerce(values)
    return _q(max(items) - min(items))


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------


def skewness(values: Sequence[object]) -> Decimal:
    """Fisher-Pearson sample skewness.

    ``g1 = ((1/n) * sum((x - mean)^3)) / stdev_pop^3`` where ``stdev_pop`` is
    the population standard deviation. Requires ``n >= 3`` and a non-constant
    series (``stdev_pop > 0``).
    """
    items = _coerce(values)
    n = len(items)
    if n < 3:
        raise CalculationError("skewness requires at least three observations")
    mu = _mean_exact(items)
    var_pop = _pop_variance_exact(items, mu)
    if var_pop == 0:
        raise CalculationError("skewness is undefined for a constant series")
    sd_pop = _sqrt_exact(var_pop)
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        m3 = checked_div(sum(((v - mu) ** 3 for v in items), Decimal(0)), Decimal(n))
        g1 = checked_div(m3, sd_pop**3)
    return _q(g1)


def kurtosis(values: Sequence[object], *, excess: bool = True) -> Decimal:
    """Sample kurtosis.

    ``((1/n) * sum((x - mean)^4)) / stdev_pop^4``; when ``excess=True`` the
    value ``3`` is subtracted (excess kurtosis). Requires ``n >= 4`` and a
    non-constant series (``stdev_pop > 0``).
    """
    items = _coerce(values)
    n = len(items)
    if n < 4:
        raise CalculationError("kurtosis requires at least four observations")
    mu = _mean_exact(items)
    var_pop = _pop_variance_exact(items, mu)
    if var_pop == 0:
        raise CalculationError("kurtosis is undefined for a constant series")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        m4 = checked_div(sum(((v - mu) ** 4 for v in items), Decimal(0)), Decimal(n))
        k = checked_div(m4, var_pop**2)
        if excess:
            k = k - Decimal(3)
    return _q(k)


# --------------------------------------------------------------------------
# Completeness
# --------------------------------------------------------------------------


def coverage(values: Sequence[object]) -> Decimal:
    """Fraction of non-``None`` observations: ``count_non_none / len``.

    ``values`` may contain ``None`` gaps; every present value is validated via
    :func:`strix.native.arithmetic.as_decimal` (``float`` rejected). Requires
    ``len >= 1``.
    """
    items = list(values)
    if not items:
        raise CalculationError("coverage requires at least one slot")
    present = 0
    for v in items:
        if v is None:
            continue
        as_decimal(v)  # validate present values (rejects float/NaN/Inf)
        present += 1
    return _q(checked_div(Decimal(present), Decimal(len(items))))


# --------------------------------------------------------------------------
# Structured summary
# --------------------------------------------------------------------------


class DescriptiveSummary(StrixModel):
    """Frozen descriptive summary of a numeric sample (deterministic Decimal).

    All Decimal fields are quantized to
    :data:`~strix.native.arithmetic.STAT_QUANTUM`.
    """

    n: int
    mean: DecimalValue
    median: DecimalValue
    stdev: DecimalValue
    minimum: DecimalValue
    maximum: DecimalValue
    q1: DecimalValue
    q3: DecimalValue


def describe(values: Sequence[object]) -> DescriptiveSummary:
    """Build a :class:`DescriptiveSummary` from the sample.

    Uses sample standard deviation, so it requires ``n >= 2``.
    """
    items = _coerce(values)
    n = len(items)
    if n < 2:
        raise CalculationError("describe requires at least two observations")
    return DescriptiveSummary(
        n=n,
        mean=_q(_mean_exact(items)),
        median=_q(_median_exact(items)),
        stdev=stdev(items),
        minimum=_q(min(items)),
        maximum=_q(max(items)),
        q1=_q(_quantile_exact(items, Decimal("0.25"))),
        q3=_q(_quantile_exact(items, Decimal("0.75"))),
    )
