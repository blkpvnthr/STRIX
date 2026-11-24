"""Exact-Decimal multivariate statistics for the native layer (R1 §6/§7).

This module provides pairwise and matrix second-moment statistics —
covariance, Pearson correlation, their matrices, weighted and
exponentially-weighted covariance — and simple ordinary-least-squares
regression.

Numerical contract (shared by every function here)
--------------------------------------------------
- **Representation:** exact :class:`decimal.Decimal`. Binary ``float`` is
  forbidden at every input boundary; NaN/Inf are rejected (via
  :func:`strix.native.arithmetic.as_decimal`).
- **Precision/rounding:** all reductions run inside a *local* decimal context
  at :data:`~strix.native.arithmetic.ARITH_PRECISION` with ``ROUND_HALF_EVEN``;
  the global decimal context is never mutated.
- **Output:** every scalar and every matrix cell is quantized to
  :data:`~strix.native.arithmetic.STAT_QUANTUM` so results are deterministic
  and reproducible across certified backends. Returns are :class:`Decimal`,
  ``tuple[Decimal, ...]``, ``tuple[tuple[Decimal, ...], ...]`` (matrices), or
  the frozen :class:`RegressionFit` model.
- **Determinism:** no backend may assign an authoritative factual verdict;
  this layer only produces reproducible numeric values.

Invalid inputs (wrong/unequal length, too few observations, zero denominators,
constant series where a quantity is undefined) raise
:class:`strix.errors.CalculationError`.

Out of scope (deferred to the native CPU/Metal backends): multiple/multivariate
regression, eigen-decomposition, and matrix condition number. Only the simple
two-variable and symmetric-matrix cases live here.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

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
    "RegressionFit",
    "correlation",
    "correlation_matrix",
    "covariance",
    "covariance_matrix",
    "ewma_covariance",
    "linear_regression",
    "weighted_covariance",
]


# ---------------------------------------------------------------------------
# local helpers (sibling native stat modules are intentionally NOT imported)
# ---------------------------------------------------------------------------


def _coerce_series(values: Sequence[object], *, name: str) -> tuple[Decimal, ...]:
    """Coerce an input sequence to finite Decimals (float/NaN/Inf rejected)."""
    if isinstance(values, (str, bytes)):
        raise CalculationError(f"{name} must be a sequence of numbers, not a string")
    items = tuple(as_decimal(v) for v in values)
    if not items:
        raise CalculationError(f"{name} must contain at least one observation")
    return items


def _require_equal_length(*series: tuple[Decimal, ...]) -> int:
    lengths = {len(s) for s in series}
    if len(lengths) != 1:
        raise CalculationError(
            f"all series must have equal length, got lengths {sorted(lengths)}"
        )
    return lengths.pop()


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    """Arithmetic mean inside the active local context."""
    return checked_sum(values) / Decimal(len(values))


def _sum_products(
    xs: tuple[Decimal, ...], ys: tuple[Decimal, ...], mx: Decimal, my: Decimal
) -> Decimal:
    """Sum of mean-centered cross products inside the active local context."""
    total = Decimal(0)
    for xi, yi in zip(xs, ys, strict=True):
        total += (xi - mx) * (yi - my)
    return total


def _q(value: Decimal) -> Decimal:
    """Quantize to the statistical quantum inside the active local context."""
    return quantize(value, STAT_QUANTUM)


# ---------------------------------------------------------------------------
# covariance / correlation
# ---------------------------------------------------------------------------


def covariance(
    x: Sequence[object], y: Sequence[object], *, sample: bool = True
) -> Decimal:
    """Covariance of two equal-length series.

    ``cov = sum((xi - x̄)(yi - ȳ)) / d`` where ``d = n - 1`` for the sample
    estimator (default; matches :func:`statistics.covariance`) and ``d = n``
    for the population estimator. Requires ``n >= 2``.
    """
    xs = _coerce_series(x, name="x")
    ys = _coerce_series(y, name="y")
    n = _require_equal_length(xs, ys)
    if n < 2:
        raise CalculationError("covariance requires at least two observations")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        sp = _sum_products(xs, ys, _mean(xs), _mean(ys))
        denom = Decimal(n - 1 if sample else n)
        return _q(sp / denom)


def correlation(x: Sequence[object], y: Sequence[object]) -> Decimal:
    """Pearson product-moment correlation on levels, in ``[-1, 1]``.

    ``r = Sxy / sqrt(Sxx * Syy)`` with mean-centered sums of squares. A
    constant series (zero variance) makes correlation undefined and is
    rejected. Cross-checks :func:`statistics.correlation`.
    """
    xs = _coerce_series(x, name="x")
    ys = _coerce_series(y, name="y")
    n = _require_equal_length(xs, ys)
    if n < 2:
        raise CalculationError("correlation requires at least two observations")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        mx, my = _mean(xs), _mean(ys)
        sxy = _sum_products(xs, ys, mx, my)
        sxx = _sum_products(xs, xs, mx, mx)
        syy = _sum_products(ys, ys, my, my)
        if sxx == 0 or syy == 0:
            raise CalculationError(
                "correlation is undefined for a constant (zero-variance) series"
            )
        r = sxy / (sxx * syy).sqrt()
        # Clamp tiny rounding excursions just outside the valid range.
        if r > 1:
            r = Decimal(1)
        elif r < -1:
            r = Decimal(-1)
        return _q(r)


def covariance_matrix(
    columns: Sequence[Sequence[object]],
) -> tuple[tuple[Decimal, ...], ...]:
    """Symmetric sample-covariance matrix of equal-length columns.

    Cell ``[i][j]`` is the sample covariance of column ``i`` and column ``j``;
    the diagonal is each column's sample variance. Requires ``n >= 2``.
    """
    cols = _coerce_columns(columns)
    k = len(cols)
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        n = len(cols[0])
        if n < 2:
            raise CalculationError(
                "covariance_matrix requires at least two observations"
            )
        means = [_mean(c) for c in cols]
        denom = Decimal(n - 1)
        rows: list[tuple[Decimal, ...]] = []
        for i in range(k):
            row: list[Decimal] = []
            for j in range(k):
                sp = _sum_products(cols[i], cols[j], means[i], means[j])
                row.append(_q(sp / denom))
            rows.append(tuple(row))
        return tuple(rows)


def correlation_matrix(
    columns: Sequence[Sequence[object]],
) -> tuple[tuple[Decimal, ...], ...]:
    """Symmetric Pearson correlation matrix; the diagonal is exactly ``1``.

    Off-diagonal cell ``[i][j]`` is the correlation of columns ``i`` and ``j``.
    A constant (zero-variance) column makes correlation undefined and is
    rejected. Requires ``n >= 2``.
    """
    cols = _coerce_columns(columns)
    k = len(cols)
    one = _one()
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        n = len(cols[0])
        if n < 2:
            raise CalculationError(
                "correlation_matrix requires at least two observations"
            )
        means = [_mean(c) for c in cols]
        ss = [_sum_products(c, c, m, m) for c, m in zip(cols, means, strict=True)]
        for s in ss:
            if s == 0:
                raise CalculationError(
                    "correlation_matrix is undefined for a constant column"
                )
        rows: list[tuple[Decimal, ...]] = []
        for i in range(k):
            row: list[Decimal] = []
            for j in range(k):
                if i == j:
                    row.append(one)
                    continue
                sxy = _sum_products(cols[i], cols[j], means[i], means[j])
                r = sxy / (ss[i] * ss[j]).sqrt()
                if r > 1:
                    r = Decimal(1)
                elif r < -1:
                    r = Decimal(-1)
                row.append(_q(r))
            rows.append(tuple(row))
        return tuple(rows)


def _coerce_columns(
    columns: Sequence[Sequence[object]],
) -> tuple[tuple[Decimal, ...], ...]:
    if isinstance(columns, (str, bytes)):
        raise CalculationError("columns must be a sequence of series")
    cols = tuple(
        _coerce_series(col, name=f"column[{i}]") for i, col in enumerate(columns)
    )
    if not cols:
        raise CalculationError("columns must contain at least one series")
    _require_equal_length(*cols)
    return cols


def _one() -> Decimal:
    """The quantized constant ``1`` (``1.000000000000``)."""
    return quantize(Decimal(1), STAT_QUANTUM)


# ---------------------------------------------------------------------------
# weighted / exponentially-weighted covariance
# ---------------------------------------------------------------------------


def weighted_covariance(
    x: Sequence[object],
    y: Sequence[object],
    weights: Sequence[object],
    *,
    sample: bool = True,
) -> Decimal:
    """Weighted covariance with weighted means.

    Let ``W = Σwᵢ``, ``x̄w = Σwᵢxᵢ / W`` (likewise ``ȳw``) and
    ``Sw = Σ wᵢ (xᵢ - x̄w)(yᵢ - ȳw)``. Then:

    - population: ``cov = Sw / W``
    - sample (unbiased reliability weights): ``cov = Sw / (W - Σwᵢ² / W)``

    With equal weights this reduces to the ordinary covariance. Requires
    equal lengths and ``W != 0`` (and a non-zero sample denominator).
    """
    xs = _coerce_series(x, name="x")
    ys = _coerce_series(y, name="y")
    ws = _coerce_series(weights, name="weights")
    n = _require_equal_length(xs, ys, ws)
    if n < 2:
        raise CalculationError("weighted_covariance requires at least two observations")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        w_sum = checked_sum(ws)
        if w_sum == 0:
            raise CalculationError("weighted_covariance requires non-zero total weight")
        mx = checked_sum(tuple(wi * xi for wi, xi in zip(ws, xs, strict=True))) / w_sum
        my = checked_sum(tuple(wi * yi for wi, yi in zip(ws, ys, strict=True))) / w_sum
        sw = Decimal(0)
        for wi, xi, yi in zip(ws, xs, ys, strict=True):
            sw += wi * (xi - mx) * (yi - my)
        if sample:
            w_sq_sum = checked_sum(tuple(wi * wi for wi in ws))
            denom = w_sum - (w_sq_sum / w_sum)
            if denom == 0:
                raise CalculationError(
                    "weighted_covariance sample denominator is zero "
                    "(weights concentrated on a single observation)"
                )
        else:
            denom = w_sum
        return _q(sw / denom)


def ewma_covariance(
    x: Sequence[object],
    y: Sequence[object],
    *,
    span: object | None = None,
    alpha: object | None = None,
) -> Decimal:
    """Final exponentially-weighted (mean-adjusted) covariance scalar.

    Exactly one of ``span`` or ``alpha`` must be given; ``alpha = 2/(span+1)``.
    With decay ``λ = 1 - alpha`` the observation of age ``k`` (newest = 0) carries
    weight ``wₖ = λᵏ``. With weighted means ``x̄w``/``ȳw`` the result is the
    weighted (bias-not-corrected) covariance
    ``Σ wₖ (xₖ - x̄w)(yₖ - ȳw) / Σ wₖ``. Requires ``n >= 2`` and
    ``0 < alpha <= 1``.
    """
    xs = _coerce_series(x, name="x")
    ys = _coerce_series(y, name="y")
    n = _require_equal_length(xs, ys)
    if n < 2:
        raise CalculationError("ewma_covariance requires at least two observations")
    if (span is None) == (alpha is None):
        raise CalculationError(
            "ewma_covariance requires exactly one of span or alpha"
        )
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        if alpha is not None:
            a = as_decimal(alpha)
        else:
            s = as_decimal(span)
            if s <= 0:
                raise CalculationError("ewma_covariance span must be positive")
            a = Decimal(2) / (s + Decimal(1))
        if not (Decimal(0) < a <= Decimal(1)):
            raise CalculationError("ewma_covariance alpha must be in (0, 1]")
        decay = Decimal(1) - a
        # Oldest observation (index 0) has the greatest age (n-1). The newest
        # observation always carries weight 1 (age 0); defining it explicitly
        # avoids Decimal's invalid ``0 ** 0`` when alpha == 1 (decay == 0).
        weights = tuple(
            Decimal(1) if (n - 1 - i) == 0 else decay ** (n - 1 - i) for i in range(n)
        )
        w_sum = checked_sum(weights)
        if w_sum == 0:
            raise CalculationError("ewma_covariance produced zero total weight")
        mx = checked_sum(tuple(wi * xi for wi, xi in zip(weights, xs, strict=True))) / w_sum
        my = checked_sum(tuple(wi * yi for wi, yi in zip(weights, ys, strict=True))) / w_sum
        sw = Decimal(0)
        for wi, xi, yi in zip(weights, xs, ys, strict=True):
            sw += wi * (xi - mx) * (yi - my)
        return _q(sw / w_sum)


# ---------------------------------------------------------------------------
# simple OLS regression
# ---------------------------------------------------------------------------


class RegressionFit(StrixModel):
    """Result of a simple (two-variable) ordinary-least-squares fit.

    Deterministic Decimal numerical contract: every value is quantized to
    :data:`~strix.native.arithmetic.STAT_QUANTUM`.
    """

    slope: Decimal
    intercept: Decimal
    r_squared: Decimal
    residuals: tuple[Decimal, ...]
    std_error_slope: Decimal
    n: int


def linear_regression(x: Sequence[object], y: Sequence[object]) -> RegressionFit:
    """Simple ordinary-least-squares regression of ``y`` on ``x``.

    ``slope = Sxy / Sxx``, ``intercept = ȳ - slope·x̄``,
    ``residualᵢ = yᵢ - (slope·xᵢ + intercept)``,
    ``r² = 1 - SSres / SStot`` (equivalently ``corr²``), and
    ``std_error_slope = sqrt((SSres / (n-2)) / Sxx)``.

    Requires ``n >= 3`` (so the slope's standard error is defined), a
    non-constant ``x`` (``Sxx != 0``) and a non-constant ``y`` (``SStot != 0``,
    needed for ``r²``). Cross-checks slope/intercept against
    :func:`statistics.linear_regression`.
    """
    xs = _coerce_series(x, name="x")
    ys = _coerce_series(y, name="y")
    n = _require_equal_length(xs, ys)
    if n < 3:
        raise CalculationError(
            "linear_regression requires at least three observations "
            "(the slope standard error needs n - 2 >= 1)"
        )
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        mx, my = _mean(xs), _mean(ys)
        sxx = _sum_products(xs, xs, mx, mx)
        if sxx == 0:
            raise CalculationError(
                "linear_regression is undefined for a constant x series"
            )
        syy = _sum_products(ys, ys, my, my)
        if syy == 0:
            raise CalculationError(
                "linear_regression r_squared is undefined for a constant y series"
            )
        sxy = _sum_products(xs, ys, mx, my)
        slope = sxy / sxx
        intercept = my - slope * mx
        residuals = tuple(yi - (slope * xi + intercept) for xi, yi in zip(xs, ys, strict=True))
        ss_res = Decimal(0)
        for res in residuals:
            ss_res += res * res
        r_squared = Decimal(1) - (ss_res / syy)
        std_error_slope = ((ss_res / Decimal(n - 2)) / sxx).sqrt()
        return RegressionFit(
            slope=_q(slope),
            intercept=_q(intercept),
            r_squared=_q(r_squared),
            residuals=tuple(_q(res) for res in residuals),
            std_error_slope=_q(std_error_slope),
            n=n,
        )
