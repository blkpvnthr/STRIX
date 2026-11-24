"""Contract tests for strix.native.arithmetic — checked exact arithmetic (R1 §7).

The native quantitative layer extends the existing exact-Decimal discipline
(strix.analytics.profitability, strix.agent.calculations): exact Decimal inside
a local context, ROUND_HALF_EVEN, float forbidden, NaN/Inf rejected,
division-by-zero and integer overflow raised as typed CalculationError.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from strix.errors import CalculationError
from strix.native import arithmetic as A


class TestAsDecimal:
    def test_accepts_int(self) -> None:
        assert A.as_decimal(7) == Decimal(7)
        assert isinstance(A.as_decimal(7), Decimal)

    def test_accepts_str(self) -> None:
        assert A.as_decimal("8.4") == Decimal("8.4")

    def test_accepts_decimal_identity(self) -> None:
        d = Decimal("1.5")
        assert A.as_decimal(d) == d

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            A.as_decimal(8.4)

    def test_rejects_nonfinite_decimal(self) -> None:
        for bad in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
            with pytest.raises(CalculationError):
                A.as_decimal(bad)

    def test_rejects_unparseable_str(self) -> None:
        with pytest.raises(CalculationError):
            A.as_decimal("not-a-number")


class TestRequireFinite:
    def test_returns_finite(self) -> None:
        assert A.require_finite(Decimal("3.14")) == Decimal("3.14")

    def test_raises_on_nan(self) -> None:
        with pytest.raises(CalculationError):
            A.require_finite(Decimal("NaN"))

    def test_raises_on_inf(self) -> None:
        with pytest.raises(CalculationError):
            A.require_finite(Decimal("Infinity"))

    def test_raises_on_float(self) -> None:
        with pytest.raises(CalculationError):
            A.require_finite(1.0)  # type: ignore[arg-type]


class TestCheckedSum:
    def test_exact_sum(self) -> None:
        # 0.1 + 0.2 is EXACT in Decimal (not 0.30000000000000004).
        assert A.checked_sum([Decimal("0.1"), Decimal("0.2")]) == Decimal("0.3")

    def test_large_exact_values(self) -> None:
        values = [Decimal("84000000.00"), Decimal("16000000.00")]
        assert A.checked_sum(values) == Decimal("100000000.00")

    def test_rejects_empty(self) -> None:
        with pytest.raises(CalculationError):
            A.checked_sum([])

    def test_rejects_float_member(self) -> None:
        with pytest.raises(CalculationError):
            A.checked_sum([Decimal("1"), 2.0])  # type: ignore[list-item]

    def test_rejects_nonfinite_member(self) -> None:
        with pytest.raises(CalculationError):
            A.checked_sum([Decimal("1"), Decimal("NaN")])


class TestCheckedDiv:
    def test_exact_division(self) -> None:
        assert A.checked_div(Decimal("1"), Decimal("4")) == Decimal("0.25")

    def test_repeating_division_is_high_precision(self) -> None:
        # 1/3 to context precision; deterministic and reproducible.
        result = A.checked_div(Decimal("1"), Decimal("3"))
        assert str(result).startswith("0.3333333333")

    def test_raises_on_zero_denominator(self) -> None:
        with pytest.raises(CalculationError):
            A.checked_div(Decimal("1"), Decimal("0"))

    def test_rejects_float_operand(self) -> None:
        with pytest.raises(CalculationError):
            A.checked_div(1.0, Decimal("2"))  # type: ignore[arg-type]

    def test_does_not_mutate_global_context(self) -> None:
        from decimal import getcontext

        before = getcontext().prec
        A.checked_div(Decimal("1"), Decimal("3"))
        assert getcontext().prec == before


class TestQuantize:
    def test_round_half_even(self) -> None:
        # Banker's rounding: 0.125 -> 0.12, 0.135 -> 0.14 at 2dp.
        assert A.quantize(Decimal("0.125"), Decimal("0.01")) == Decimal("0.12")
        assert A.quantize(Decimal("0.135"), Decimal("0.01")) == Decimal("0.14")

    def test_collapses_negative_zero(self) -> None:
        q = A.quantize(Decimal("-0.0000001"), Decimal("0.01"))
        assert q == Decimal("0.00")
        assert not q.is_signed()

    def test_rejects_float(self) -> None:
        with pytest.raises(CalculationError):
            A.quantize(1.0, Decimal("0.01"))  # type: ignore[arg-type]


class TestCheckedIntAdd:
    def test_normal_addition(self) -> None:
        assert A.checked_int_add(2, 3) == 5

    def test_detects_signed_64bit_overflow(self) -> None:
        max64 = 2**63 - 1
        with pytest.raises(CalculationError):
            A.checked_int_add(max64, 1, bits=64, signed=True)

    def test_detects_signed_underflow(self) -> None:
        min64 = -(2**63)
        with pytest.raises(CalculationError):
            A.checked_int_add(min64, -1, bits=64, signed=True)

    def test_unsigned_rejects_negative_result(self) -> None:
        with pytest.raises(CalculationError):
            A.checked_int_add(0, -1, bits=64, signed=False)


class TestCheckedIntMul:
    def test_normal_multiplication(self) -> None:
        assert A.checked_int_mul(6, 7) == 42

    def test_detects_overflow(self) -> None:
        with pytest.raises(CalculationError):
            A.checked_int_mul(2**62, 4, bits=64, signed=True)
