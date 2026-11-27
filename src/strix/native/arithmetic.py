"""Checked exact arithmetic for the native quantitative layer (R1 §7).

Every primitive here is exact :class:`~decimal.Decimal` arithmetic inside a
*local* context (the global decimal context is never mutated), ``float`` is
forbidden, and non-finite values (NaN/Inf), division by zero, and integer
overflow/underflow are raised as typed :class:`~strix.errors.CalculationError`
subclasses carrying a human-readable reason.

This generalizes the discipline already used in
:mod:`strix.analytics.profitability` and :mod:`strix.agent.calculations` so the
whole R1 statistics surface can share one safe arithmetic core.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext

from strix.errors import CalculationError

#: Working precision for division and reductions. Matches the precision used by
#: :mod:`strix.agent.calculations`, giving ample headroom before quantization.
ARITH_PRECISION = 50

#: Canonical quantum for statistical summaries (12 decimal places). Chosen so
#: deterministic Decimal results stay reproducible and canonically hashable while
#: remaining well within any floating-point backend's parity tolerance.
STAT_QUANTUM = Decimal("0.000000000001")


class NumericalContractError(CalculationError):
    """An input or result violated a numerical contract: a forbidden ``float``,
    a non-finite value, division by zero, or an integer range overflow."""


def as_decimal(value: object) -> Decimal:
    """Coerce ``int``/``str``/``Decimal`` to a finite :class:`~decimal.Decimal`.

    ``float`` is forbidden (it silently loses exactness); NaN/Inf and
    unparseable strings are rejected.
    """
    if isinstance(value, float):
        raise NumericalContractError(
            "float values are forbidden; supply Decimal, str, or int"
        )
    if isinstance(value, Decimal):
        return require_finite(value)
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise NumericalContractError(f"cannot parse a Decimal from {value!r}") from exc
        return require_finite(parsed)
    raise NumericalContractError(f"unsupported numeric type {type(value).__name__}")


def require_finite(value: object) -> Decimal:
    """Return ``value`` if it is a finite :class:`~decimal.Decimal`; else raise."""
    if not isinstance(value, Decimal):
        raise NumericalContractError(
            f"value must be a Decimal, got {type(value).__name__}"
        )
    if not value.is_finite():
        raise NumericalContractError("value must be a finite Decimal (NaN/Inf forbidden)")
    return value


def exact_context_prec(values: Sequence[Decimal], *, extra: int = 0) -> int:
    """A context precision large enough to represent exact results over ``values``.

    Sized to the full digit span (most-significant digit of the largest value
    down to the least-significant digit of the most precise value) plus headroom,
    so sums/subtractions never silently round under the global 28-digit context.
    """
    finite = [v for v in values if isinstance(v, Decimal) and v.is_finite()]
    if not finite:
        return ARITH_PRECISION
    max_adjusted = max((v.adjusted() for v in finite if v != 0), default=0)
    exponents: list[int] = []
    for value in finite:
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int):
            exponents.append(exponent)
    min_exponent = min(exponents, default=0)
    span = max(0, max_adjusted) - min(0, min_exponent) + 1
    return max(ARITH_PRECISION, span + extra + 10)


def checked_sum(values: Sequence[object]) -> Decimal:
    """Exact sum of a non-empty sequence of finite Decimals (float rejected).

    Accumulates inside a local context sized to the inputs, so the result is
    exact regardless of magnitude or count (the global 28-digit context would
    silently round large sums).
    """
    items = [require_finite(item) for item in values]
    if not items:
        raise NumericalContractError("checked_sum requires at least one value")
    with localcontext() as ctx:
        ctx.prec = exact_context_prec(items, extra=len(items).bit_length())
        total = Decimal(0)
        for item in items:
            total += item
    return total


def checked_sub(a: object, b: object) -> Decimal:
    """Exact subtraction of two finite Decimals (float rejected)."""
    x = require_finite(a)
    y = require_finite(b)
    with localcontext() as ctx:
        ctx.prec = exact_context_prec((x, y), extra=2)
        return +(x - y)


def checked_div(numerator: object, denominator: object) -> Decimal:
    """Exact division at :data:`ARITH_PRECISION`; division by zero is rejected.

    Operates inside a local context, so the global decimal context is untouched.
    """
    num = as_decimal(numerator)
    den = as_decimal(denominator)
    if den == 0:
        raise NumericalContractError("division by zero")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        try:
            return +(num / den)
        except InvalidOperation as exc:
            raise NumericalContractError("division is out of the supported range") from exc


def checked_mul(a: object, b: object) -> Decimal:
    """Exact product of two finite Decimals (float rejected).

    Computes inside a local context sized to the operands' significant-digit counts so the
    product is exact regardless of magnitude — the global 28-digit context would silently
    round a large-magnitude product (e.g. market-cap-scale variance terms). Analogous to
    :func:`checked_sub` / :func:`checked_div`.
    """
    x = as_decimal(a)
    y = as_decimal(b)
    needed = len(x.as_tuple().digits) + len(y.as_tuple().digits) + 2
    with localcontext() as ctx:
        ctx.prec = max(ARITH_PRECISION, needed)
        return +(x * y)


def quantize(value: object, quantum: object) -> Decimal:
    """Quantize to ``quantum`` with banker's rounding, collapsing negative zero.

    Runs inside a *local* context whose precision is sized to the value's
    magnitude, so quantizing large but finite inputs (e.g. a variance of
    market-cap-scale values, wei amounts, or nanosecond timestamps) never
    overflows the global 28-digit context. A genuinely out-of-range value raises
    a typed :class:`NumericalContractError` rather than an untyped
    ``decimal.InvalidOperation``.
    """
    val = require_finite(value)
    quant = require_finite(quantum)
    exponent = quant.as_tuple().exponent
    # require_finite guarantees a finite Decimal, so the exponent is an int
    # (never the 'n'/'N'/'F' special markers).
    assert isinstance(exponent, int)
    fractional_digits = max(0, -exponent)
    # Enough significant digits for the integer part plus the quantum's fraction.
    needed = max(0, val.adjusted()) + 1 + fractional_digits + 6
    with localcontext() as ctx:
        ctx.prec = max(ARITH_PRECISION, needed)
        ctx.rounding = ROUND_HALF_EVEN
        try:
            out = val.quantize(quant, rounding=ROUND_HALF_EVEN)
        except InvalidOperation as exc:
            raise NumericalContractError(
                "value is out of the supported numeric range for quantization"
            ) from exc
    return out.copy_abs() if out == 0 else out


def _require_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise NumericalContractError(f"value must be an int, got {type(value).__name__}")
    return value


def _int_bounds(*, bits: int, signed: bool) -> tuple[int, int]:
    if bits <= 0:
        raise NumericalContractError("bits must be a positive integer")
    if signed:
        return -(2 ** (bits - 1)), 2 ** (bits - 1) - 1
    return 0, 2**bits - 1


def _check_int_range(result: int, *, bits: int, signed: bool) -> int:
    low, high = _int_bounds(bits=bits, signed=signed)
    if result < low or result > high:
        kind = "signed" if signed else "unsigned"
        raise NumericalContractError(
            f"integer result {result} overflows the {kind} {bits}-bit range "
            f"[{low}, {high}]"
        )
    return result


def checked_int_add(a: int, b: int, *, bits: int = 64, signed: bool = True) -> int:
    """Integer addition with explicit overflow/underflow detection."""
    return _check_int_range(_require_int(a) + _require_int(b), bits=bits, signed=signed)


def checked_int_mul(a: int, b: int, *, bits: int = 64, signed: bool = True) -> int:
    """Integer multiplication with explicit overflow detection."""
    return _check_int_range(_require_int(a) * _require_int(b), bits=bits, signed=signed)
