"""Statistical inference for the native quantitative layer (R1 §6.4).

Confidence intervals, effect sizes, Welch's t-test, percentile bootstrap, and
multiple-comparison correction.

Numerical contract: this is the **approximate / stochastic** class (R1 §7.1).
Inputs are still exact — ``float`` is rejected at the boundary via
:func:`strix.native.arithmetic.as_decimal` — but the internal computation is
IEEE-754 ``float64`` (the natural domain for special functions), and results are
returned as Decimals quantized to :data:`INFER_QUANTUM` with a documented
tolerance. The Student-t distribution is evaluated through the regularized
incomplete beta function (the standard continued-fraction form), not a lookup
table. Bootstrap results are deterministic given a recorded random seed.

Statistical-significance claims require appropriate assumptions, a valid test,
and adequate data; nothing here licenses inferring causation from correlation.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from decimal import Decimal

from strix.errors import CalculationError
from strix.models import DecimalValue, StrixModel
from strix.native import arithmetic as A

#: Quantum for inference outputs (9 decimal places). Reflects the approximate
#: contract: agreement is tolerance-bounded, not bitwise exact.
INFER_QUANTUM = Decimal("0.000000001")


# --------------------------------------------------------------------------
# Typed results
# --------------------------------------------------------------------------


class ConfidenceInterval(StrixModel):
    """A two-sided confidence interval for a point estimate."""

    point: DecimalValue
    lower: DecimalValue
    upper: DecimalValue
    confidence: DecimalValue
    degrees_of_freedom: DecimalValue
    n: int
    method: str


class TTestResult(StrixModel):
    """Result of a two-sample t-test (Welch's by default)."""

    t_statistic: DecimalValue
    degrees_of_freedom: DecimalValue
    p_value_two_sided: DecimalValue
    mean_a: DecimalValue
    mean_b: DecimalValue
    n_a: int
    n_b: int
    method: str


class BootstrapResult(StrixModel):
    """A percentile-bootstrap confidence interval with its recorded seed."""

    point: DecimalValue
    lower: DecimalValue
    upper: DecimalValue
    confidence: DecimalValue
    n_resamples: int
    seed: int
    method: str


# --------------------------------------------------------------------------
# Input coercion
# --------------------------------------------------------------------------


def _floats(values: Sequence[object], *, minimum: int) -> list[float]:
    """Coerce a sequence through the exact boundary, then to float64."""
    out = [float(A.as_decimal(v)) for v in values]
    if len(out) < minimum:
        raise CalculationError(f"need at least {minimum} observations, got {len(out)}")
    return out


def _dec(value: float) -> Decimal:
    if not math.isfinite(value):
        raise CalculationError("non-finite result")
    return A.quantize(Decimal(repr(value)), INFER_QUANTUM)


def _mean(xs: Sequence[float]) -> float:
    return math.fsum(xs) / len(xs)


def _sample_variance(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        raise CalculationError("sample variance needs at least two observations")
    mu = _mean(xs)
    return math.fsum((x - mu) ** 2 for x in xs) / (n - 1)


# --------------------------------------------------------------------------
# Student-t via the regularized incomplete beta function
# --------------------------------------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta (Numerical Recipes form)."""
    max_iter = 300
    eps = 3.0e-16
    fpmin = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _reg_incomplete_beta(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b) for 0 <= x <= 1."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_bt = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    bt = math.exp(ln_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _require_df(df: object) -> float:
    value = float(A.as_decimal(df))
    if value <= 0:
        raise CalculationError("degrees of freedom must be positive")
    return value


def student_t_two_sided_p(t: object, df: object) -> Decimal:
    """Two-sided p-value P(|T| > |t|) for Student's t with ``df`` dof."""
    tf = float(A.as_decimal(t))
    dff = _require_df(df)
    x = dff / (dff + tf * tf)
    return _dec(_reg_incomplete_beta(dff / 2.0, 0.5, x))


def student_t_sf(t: object, df: object) -> Decimal:
    """Survival function P(T > t) for Student's t with ``df`` dof."""
    tf = float(A.as_decimal(t))
    dff = _require_df(df)
    x = dff / (dff + tf * tf)
    ib = _reg_incomplete_beta(dff / 2.0, 0.5, x)
    sf = 0.5 * ib if tf >= 0 else 1.0 - 0.5 * ib
    return _dec(sf)


def _inverse_t_tail(tail: float, df: float) -> float:
    """t > 0 such that the upper-tail survival equals ``tail`` (bisection)."""
    lo, hi = 0.0, 1.0e6
    for _ in range(200):
        mid = (lo + hi) / 2.0
        x = df / (df + mid * mid)
        sf = 0.5 * _reg_incomplete_beta(df / 2.0, 0.5, x)
        if sf > tail:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# --------------------------------------------------------------------------
# Public inference API
# --------------------------------------------------------------------------


def cohens_d(a: Sequence[object], b: Sequence[object]) -> Decimal:
    """Cohen's d effect size using the pooled sample standard deviation."""
    xs = _floats(a, minimum=2)
    ys = _floats(b, minimum=2)
    na, nb = len(xs), len(ys)
    var_a, var_b = _sample_variance(xs), _sample_variance(ys)
    pooled_var = ((na - 1) * var_a + (nb - 1) * var_b) / (na + nb - 2)
    if pooled_var <= 0:
        raise CalculationError("pooled standard deviation is zero; d is undefined")
    return _dec((_mean(xs) - _mean(ys)) / math.sqrt(pooled_var))


def welch_t_test(a: Sequence[object], b: Sequence[object]) -> TTestResult:
    """Welch's unequal-variance two-sample t-test."""
    xs = _floats(a, minimum=2)
    ys = _floats(b, minimum=2)
    na, nb = len(xs), len(ys)
    mean_a, mean_b = _mean(xs), _mean(ys)
    var_a, var_b = _sample_variance(xs), _sample_variance(ys)
    sa, sb = var_a / na, var_b / nb
    se = math.sqrt(sa + sb)
    if se == 0:
        t_stat, df, p = 0.0, float(na + nb - 2), 1.0
    else:
        t_stat = (mean_a - mean_b) / se
        df = (sa + sb) ** 2 / (sa**2 / (na - 1) + sb**2 / (nb - 1))
        x = df / (df + t_stat * t_stat)
        p = _reg_incomplete_beta(df / 2.0, 0.5, x)
    return TTestResult(
        t_statistic=_dec(t_stat),
        degrees_of_freedom=_dec(df),
        p_value_two_sided=_dec(p),
        mean_a=_dec(mean_a),
        mean_b=_dec(mean_b),
        n_a=na,
        n_b=nb,
        method="welch",
    )


def mean_confidence_interval(
    values: Sequence[object], *, confidence: object = "0.95"
) -> ConfidenceInterval:
    """Student-t confidence interval for the population mean."""
    xs = _floats(values, minimum=2)
    conf = float(A.as_decimal(confidence))
    if not 0.0 < conf < 1.0:
        raise CalculationError("confidence must be strictly between 0 and 1")
    n = len(xs)
    df = n - 1
    mean = _mean(xs)
    sem = math.sqrt(_sample_variance(xs) / n)
    t_crit = _inverse_t_tail((1.0 - conf) / 2.0, float(df))
    margin = t_crit * sem
    return ConfidenceInterval(
        point=_dec(mean),
        lower=_dec(mean - margin),
        upper=_dec(mean + margin),
        confidence=A.quantize(A.as_decimal(confidence), INFER_QUANTUM),
        degrees_of_freedom=_dec(float(df)),
        n=n,
        method="student_t",
    )


def _percentile_sorted(sorted_xs: Sequence[float], pct: float) -> float:
    """Linear-interpolation percentile (pct in [0, 100]) of a sorted sequence."""
    if not sorted_xs:
        raise CalculationError("percentile of an empty sequence is undefined")
    if len(sorted_xs) == 1:
        return sorted_xs[0]
    rank = (pct / 100.0) * (len(sorted_xs) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_xs[low]
    frac = rank - low
    return sorted_xs[low] + frac * (sorted_xs[high] - sorted_xs[low])


def bootstrap_mean_ci(
    values: Sequence[object],
    *,
    confidence: object = "0.95",
    n_resamples: int = 2000,
    seed: int,
) -> BootstrapResult:
    """Percentile-bootstrap confidence interval for the mean (seeded)."""
    xs = _floats(values, minimum=2)
    conf = float(A.as_decimal(confidence))
    if not 0.0 < conf < 1.0:
        raise CalculationError("confidence must be strictly between 0 and 1")
    if n_resamples < 1:
        raise CalculationError("n_resamples must be positive")
    rng = random.Random(seed)
    n = len(xs)
    means = [math.fsum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_resamples)]
    means.sort()
    alpha = 1.0 - conf
    lower = _percentile_sorted(means, alpha / 2.0 * 100.0)
    upper = _percentile_sorted(means, (1.0 - alpha / 2.0) * 100.0)
    return BootstrapResult(
        point=_dec(_mean(xs)),
        lower=_dec(lower),
        upper=_dec(upper),
        confidence=A.quantize(A.as_decimal(confidence), INFER_QUANTUM),
        n_resamples=n_resamples,
        seed=seed,
        method="percentile_bootstrap",
    )


def benjamini_hochberg(
    pvalues: Sequence[object], *, alpha: object = "0.05"
) -> tuple[bool, ...]:
    """Benjamini-Hochberg FDR correction; returns a rejection mask in input order."""
    ps = [float(A.as_decimal(p)) for p in pvalues]
    a = float(A.as_decimal(alpha))
    m = len(ps)
    if m == 0:
        return ()
    order = sorted(range(m), key=lambda i: ps[i])
    max_rank = 0
    for rank, idx in enumerate(order, start=1):
        if ps[idx] <= rank / m * a:
            max_rank = rank
    rejected = [False] * m
    for rank, idx in enumerate(order, start=1):
        if rank <= max_rank:
            rejected[idx] = True
    return tuple(rejected)


def bonferroni(pvalues: Sequence[object], *, alpha: object = "0.05") -> tuple[bool, ...]:
    """Bonferroni correction; returns a rejection mask in input order."""
    ps = [float(A.as_decimal(p)) for p in pvalues]
    a = float(A.as_decimal(alpha))
    m = len(ps)
    if m == 0:
        return ()
    threshold = a / m
    return tuple(p <= threshold for p in ps)
