"""Statistical analysis for research experiments (R1 §29; CLAUDE.md robustness).

Thin, typed, offline layer over :mod:`strix.native.inference`. It provides the
three analyses an experiment comparison needs:

- :func:`bootstrap_ci` — a seeded percentile-bootstrap confidence interval for
  the mean, returned as ``(point, lower, upper)``. Deterministic given the seed.
- :func:`paired_comparison` — the mean difference between two equal-length arms
  together with a Welch two-sample t-test and a Cohen's *d* effect size, packed
  into a :class:`ComparisonResult`.
- :func:`holm_or_bh_correction` — a Benjamini-Hochberg FDR rejection mask over a
  family of p-values, in input order.

Discipline (CLAUDE.md Principle 1 — falsification first):

- We never claim significance on our own: the rejection decision belongs to the
  caller, who inspects the p-value / mask against a stated ``alpha``. This module
  only computes the test statistics.
- **Assumptions.** The p-value comes from Welch's *unequal-variance two-sample*
  t-test, which treats the two arms as independent samples. It does **not** model
  within-pair correlation; "paired" here means only that the arms are aligned and
  equal length (e.g. per-question scores for two system variants). If strong
  pairing is present, the Welch p-value is conservative/mis-specified and must be
  read as indicative, not decisive.
- **Seeds are recorded.** Bootstrap determinism is anchored to the integer seed
  the caller supplies; the same seed yields byte-identical Decimals.

Numerical note: ``float`` is forbidden at every boundary (money/scores are
``Decimal``). ``float64`` appears only *inside* :mod:`strix.native.inference`
(the documented approximate/stochastic layer); results return as quantized
Decimals.

This is offline experimental infrastructure: it performs no model calls and
fabricates no numbers.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from strix.errors import CalculationError
from strix.models import DecimalValue, StrixModel
from strix.native import inference

__all__ = [
    "ComparisonResult",
    "bootstrap_ci",
    "holm_or_bh_correction",
    "paired_comparison",
]


class ComparisonResult(StrixModel):
    """Two-arm comparison: mean difference, Welch t-test, and effect size.

    Frozen, closed schema. ``mean_difference`` equals ``mean_a - mean_b``; a
    positive value means arm A scored higher. ``p_value`` is the two-sided Welch
    p-value (see the module docstring for the independence assumption).
    """

    mean_a: DecimalValue
    mean_b: DecimalValue
    mean_difference: DecimalValue
    t_statistic: DecimalValue
    degrees_of_freedom: DecimalValue
    p_value: DecimalValue
    effect_size: DecimalValue
    n: int


def bootstrap_ci(
    values: Sequence[Decimal],
    *,
    confidence: str = "0.95",
    n_resamples: int = 2000,
    seed: int,
) -> tuple[Decimal, Decimal, Decimal]:
    """Seeded percentile-bootstrap confidence interval for the mean.

    Delegates to :func:`strix.native.inference.bootstrap_mean_ci`, which resamples
    with replacement using a :class:`random.Random` seeded by ``seed`` — so the
    result is deterministic for a given ``(values, confidence, n_resamples, seed)``.

    Args:
        values: Observations as ``Decimal`` (``float`` is rejected at the boundary).
        confidence: Two-sided confidence level in ``(0, 1)`` as a decimal string.
        n_resamples: Number of bootstrap resamples (recorded for reproducibility).
        seed: Integer seed anchoring determinism; record it alongside results.

    Returns:
        ``(point, lower, upper)`` as quantized Decimals, where ``point`` is the
        sample mean and ``lower``/``upper`` are the percentile interval bounds.

    Raises:
        strix.errors.CalculationError: On fewer than two observations, a float
            input, an out-of-range confidence, or a non-positive ``n_resamples``.
    """
    result = inference.bootstrap_mean_ci(
        values,
        confidence=confidence,
        n_resamples=n_resamples,
        seed=seed,
    )
    return result.point, result.lower, result.upper


def paired_comparison(
    arm_a: Sequence[Decimal],
    arm_b: Sequence[Decimal],
) -> ComparisonResult:
    """Compare two equal-length arms: mean difference, Welch t-test, Cohen's d.

    The arms must be the same length (aligned observations, e.g. per-question
    scores for two system variants). The reported p-value is from Welch's
    unequal-variance two-sample t-test; see the module docstring for why that is
    conservative under genuine pairing and why significance is the caller's call.

    Args:
        arm_a: First arm's observations as ``Decimal`` (float rejected).
        arm_b: Second arm's observations as ``Decimal`` (float rejected).

    Returns:
        A :class:`ComparisonResult`. ``mean_difference`` is ``mean_a - mean_b``;
        ``effect_size`` is Cohen's *d* (pooled SD); ``n`` is the per-arm count.

    Raises:
        strix.errors.CalculationError: If the arms differ in length, have fewer
            than two observations each, or contain float values.
    """
    if len(arm_a) != len(arm_b):
        raise CalculationError(
            f"paired comparison requires equal-length arms, "
            f"got {len(arm_a)} and {len(arm_b)}"
        )
    test = inference.welch_t_test(arm_a, arm_b)
    effect = inference.cohens_d(arm_a, arm_b)
    return ComparisonResult(
        mean_a=test.mean_a,
        mean_b=test.mean_b,
        mean_difference=test.mean_a - test.mean_b,
        t_statistic=test.t_statistic,
        degrees_of_freedom=test.degrees_of_freedom,
        p_value=test.p_value_two_sided,
        effect_size=effect,
        n=test.n_a,
    )


def holm_or_bh_correction(
    pvalues: Sequence[Decimal],
    *,
    alpha: str = "0.05",
) -> tuple[bool, ...]:
    """Benjamini-Hochberg FDR correction; rejection mask in input order.

    Controls the false-discovery rate across a family of tests at level ``alpha``
    via :func:`strix.native.inference.benjamini_hochberg`. ``True`` at position
    *i* means hypothesis *i* is rejected (its p-value survived the step-up
    threshold); the ordering of the input is preserved.

    Args:
        pvalues: Family of two-sided p-values as ``Decimal`` (float rejected).
        alpha: Target FDR level in ``(0, 1)`` as a decimal string.

    Returns:
        A tuple of booleans aligned to ``pvalues``; empty for an empty family.
    """
    return inference.benjamini_hochberg(pvalues, alpha=alpha)
