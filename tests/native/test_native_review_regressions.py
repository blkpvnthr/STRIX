"""Regression tests for bugs surfaced by the independent adversarial review
(workflow wf_765160e4-0dd). Each reproduces a real crash on valid finite input.

1. arithmetic.quantize ran under the global decimal context (prec=28), so
   quantizing any value >= ~1e16 to 1e-12 raised an untyped decimal.InvalidOperation
   instead of returning the value — breaking statistics on market-cap/wei/timestamp
   scale inputs (CRITICAL) and inference at >= 1e19 (MINOR).
2. multivariate.ewma_covariance raised decimal.InvalidOperation (0**0) at alpha=1,
   an input its own docstring documents as valid (MAJOR).
"""

from __future__ import annotations

from decimal import Decimal

from strix.native import arithmetic as A
from strix.native import inference as I
from strix.native import multivariate as M
from strix.native import statistics as S

STAT_Q = Decimal("0.000000000001")


class TestQuantizeLargeMagnitude:
    def test_quantize_1e16(self) -> None:
        assert A.quantize(Decimal("20000000000000000"), STAT_Q) == Decimal("2E16")

    def test_quantize_1e18(self) -> None:
        assert A.quantize(Decimal("1000000000000000000"), STAT_Q) == Decimal("1E18")

    def test_quantize_1e40_does_not_crash(self) -> None:
        # Extremely large but finite: must return a value, never raise untyped.
        assert A.quantize(Decimal("1E40"), STAT_Q) == Decimal("1E40")


class TestStatisticsLargeScale:
    def test_variance_market_cap_scale(self) -> None:
        # mean 2e8; deviations +/-1e8; sample variance = 2e16.
        v = S.variance([Decimal("100000000"), Decimal("300000000")])
        assert v == Decimal("20000000000000000")

    def test_mean_wei_scale(self) -> None:
        m = S.mean([Decimal("1000000000000000000"), Decimal("2000000000000000000")])
        assert m == Decimal("1500000000000000000")

    def test_maximum_timestamp_scale(self) -> None:
        big = Decimal("1760000000000000000")
        assert S.maximum([big, Decimal("2")]) == big


class TestInferenceLargeScale:
    def test_mean_ci_does_not_crash(self) -> None:
        values = [
            Decimal("10000000000000000000"),
            Decimal("10000000000000000020"),
            Decimal("10000000000000000040"),
        ]
        ci = I.mean_confidence_interval(values, confidence="0.95")
        assert float(ci.point) > 1e18


class TestEwmaCovarianceAlphaOne:
    def test_alpha_one_returns_zero(self) -> None:
        # alpha=1 -> only the newest observation carries weight -> covariance 0.
        assert M.ewma_covariance(["1", "2", "3"], ["4", "5", "7"], alpha="1") == Decimal("0")

    def test_span_one_equivalent(self) -> None:
        assert M.ewma_covariance(["1", "2", "3"], ["4", "5", "7"], span="1") == Decimal("0")


class TestCheckedSumExact:
    """checked_sum/checked_sub must be EXACT regardless of magnitude/count — they
    accumulated under the global prec-28 context, silently rounding large exact
    sums (GAP-003 reconciliation review, workflow wf_4e2cb7c3-6ee)."""

    def test_sum_exceeds_global_precision(self) -> None:
        # 30 * 1e27 + 0.01 — the exact total needs 29 integer + 2 fractional digits.
        values = [Decimal("1000000000000000000000000000")] * 30 + [Decimal("0.01")]
        assert A.checked_sum(values) == Decimal("30000000000000000000000000000.01")

    def test_checked_sub_exact(self) -> None:
        # 1e30 - 1 rounds to 1e30 under prec 28; must be exact.
        assert A.checked_sub(Decimal("1E30"), Decimal("1")) == Decimal(
            "999999999999999999999999999999"
        )
