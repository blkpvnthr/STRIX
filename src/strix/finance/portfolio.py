"""Offline portfolio analytics for the personal-finance engine.

This module answers *analytical* questions about a set of holdings — how is
capital allocated, how concentrated is the book, what returns were earned, how
volatile were they, and what trades would move the book toward a target weight.
It is strictly read-only: nothing here places, routes, or executes an order.
``rebalancing_trades`` returns a *recommendation* (symbol, delta-value) tuple
and never touches a broker.

Design rules this module upholds (shared with :mod:`strix.finance.ledger`):

* Models are frozen and closed (``strix.models.StrixModel``).
* Monetary and quantity values use ``strix.models.DecimalValue`` — binary
  ``float`` is rejected at the model boundary, and every free function coerces
  its numeric inputs through ``strix.native.arithmetic.as_decimal`` (which also
  rejects ``float``). No value is ever a binary ``float``.
* Exact arithmetic goes through ``strix.native.arithmetic`` and descriptive
  statistics through ``strix.native.statistics`` so results stay exact and
  deterministic regardless of magnitude.
* Portfolio-specific invalid inputs raise :class:`PortfolioError` (a
  ``strix.errors.StrixError``); the native layers raise ``CalculationError``.

No network access and no order execution happen here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from strix.errors import StrixError
from strix.models import DecimalValue, StrixModel
from strix.native.arithmetic import (
    ARITH_PRECISION,
    STAT_QUANTUM,
    as_decimal,
    checked_div,
    checked_sub,
    checked_sum,
    quantize,
    require_finite,
)
from strix.native.statistics import stdev

__all__ = [
    "Holding",
    "PortfolioError",
    "Security",
    "allocation_by",
    "allocation_drift",
    "concentration",
    "correlation",
    "herfindahl_index",
    "max_drawdown",
    "money_weighted_return",
    "rebalancing_trades",
    "time_weighted_return",
    "unrealized_gain",
    "volatility",
]


class PortfolioError(StrixError):
    """A portfolio analytic received invalid input or violated an invariant
    (an empty book, a zero total value, mismatched series lengths, or a cash-flow
    set whose internal rate of return cannot be bracketed)."""


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------


class Security(StrixModel):
    """Static reference data for a tradable instrument.

    ``asset_class`` is a free-form bucket (e.g. ``"equity"``, ``"bond"``,
    ``"cash"``); ``sector`` is an optional finer classification. These labels
    are the grouping keys that :func:`allocation_by` can aggregate over when the
    caller joins holdings to their securities.
    """

    symbol: str
    asset_class: str
    sector: str = ""


class Holding(StrixModel):
    """A position in one account: a quantity of a symbol at a current price.

    ``quantity`` and ``price`` are exact decimals; ``cost_basis`` is the
    *per-unit* acquisition price (``None`` when unknown). :attr:`market_value`
    is the exact product ``quantity * price``.
    """

    account_id: str
    symbol: str
    quantity: DecimalValue
    price: DecimalValue
    cost_basis: DecimalValue | None = None

    @property
    def market_value(self) -> Decimal:
        """Exact current market value: ``quantity * price``."""
        return _exact_mul(self.quantity, self.price)


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------


def _exact_mul(a: Decimal, b: Decimal) -> Decimal:
    """Exact product of two finite Decimals inside a local context.

    The context precision is sized to the sum of the operands' significant
    digits, so the product never silently rounds under the global 28-digit
    context.
    """
    left = require_finite(a)
    right = require_finite(b)
    with localcontext() as ctx:
        ctx.prec = len(left.as_tuple().digits) + len(right.as_tuple().digits) + 4
        ctx.rounding = ROUND_HALF_EVEN
        return +(left * right)


def _coerce_series(values: Sequence[object], *, what: str) -> list[Decimal]:
    """Coerce a non-empty sequence to finite Decimals (``float`` rejected)."""
    items = [as_decimal(v) for v in values]
    if not items:
        raise PortfolioError(f"{what} must contain at least one value")
    return items


def _weights_by_symbol(holdings: Sequence[Holding]) -> dict[str, Decimal]:
    """Market-value weights aggregated by symbol (each in ``[?, 1]``, sum 1)."""
    return allocation_by(holdings, lambda h: h.symbol)


# --------------------------------------------------------------------------
# Allocation and concentration
# --------------------------------------------------------------------------


def allocation_by(
    holdings: Sequence[Holding], key: Callable[[Holding], str]
) -> dict[str, Decimal]:
    """Fraction of total market value falling in each group.

    *key* maps a holding to its grouping label (e.g. ``lambda h: h.symbol`` or a
    lookup into :class:`Security` for ``asset_class``/``sector``). The returned
    weights are exact Decimals; for inputs whose group totals divide the book
    total exactly they sum to ``Decimal("1")``.

    Raises :class:`PortfolioError` for an empty book or a zero total value.
    """
    if not holdings:
        raise PortfolioError("allocation requires at least one holding")
    grouped: dict[str, list[Decimal]] = {}
    for holding in holdings:
        grouped.setdefault(key(holding), []).append(holding.market_value)
    group_totals = {label: checked_sum(parts) for label, parts in grouped.items()}
    total = checked_sum(list(group_totals.values()))
    if total == 0:
        raise PortfolioError("allocation requires a non-zero total market value")
    return {
        label: quantize(checked_div(value, total), STAT_QUANTUM)
        for label, value in group_totals.items()
    }


def concentration(holdings: Sequence[Holding]) -> Decimal:
    """Largest single-symbol weight (the book's top-position concentration)."""
    weights = _weights_by_symbol(holdings)
    return max(weights.values())


def herfindahl_index(holdings: Sequence[Holding]) -> Decimal:
    """Herfindahl-Hirschman index: the sum of squared symbol weights.

    Ranges from ``1/n`` (perfectly diversified across ``n`` symbols) to ``1``
    (a single-symbol book); a higher value means greater concentration.
    """
    weights = _weights_by_symbol(holdings)
    squares = [_exact_mul(w, w) for w in weights.values()]
    return quantize(checked_sum(squares), STAT_QUANTUM)


def unrealized_gain(holding: Holding) -> Decimal | None:
    """Unrealized gain/loss for *holding*, or ``None`` without a cost basis.

    When ``cost_basis`` is present the gain is
    ``market_value - quantity * cost_basis`` (exact); a loss is negative.
    """
    if holding.cost_basis is None:
        return None
    cost = _exact_mul(holding.quantity, holding.cost_basis)
    return checked_sub(holding.market_value, cost)


# --------------------------------------------------------------------------
# Returns
# --------------------------------------------------------------------------


def time_weighted_return(
    period_values: Sequence[Decimal], flows: Sequence[Decimal]
) -> Decimal:
    """Time-weighted return linking per-sub-period growth factors.

    *period_values* are portfolio values at ``k + 1`` sub-period boundaries
    ``[V0, V1, ..., Vk]``; *flows* are the ``k`` net external cash flows, where
    ``flows[i]`` is added at the **start** of sub-period ``i`` (so it is capital
    present for that period's growth but not part of its return). Each
    sub-period growth factor is ``V[i+1] / (V[i] + flows[i])`` and the TWR is
    their product minus one, which removes the distorting effect of the timing
    and size of contributions.

    Raises :class:`PortfolioError` for fewer than two values, a
    length mismatch, or a zero invested base in any sub-period.
    """
    values = _coerce_series(period_values, what="period_values")
    flow_items = [as_decimal(f) for f in flows]
    if len(values) < 2:
        raise PortfolioError("time_weighted_return requires at least two values")
    if len(flow_items) != len(values) - 1:
        raise PortfolioError(
            "flows must have exactly one entry per sub-period "
            f"(expected {len(values) - 1}, got {len(flow_items)})"
        )
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        product = Decimal(1)
        for i, flow in enumerate(flow_items):
            base = values[i] + flow
            if base == 0:
                raise PortfolioError(
                    f"sub-period {i} has a zero invested base; return undefined"
                )
            product *= values[i + 1] / base
        result = product - Decimal(1)
    return quantize(result, STAT_QUANTUM)


def _npv(rate: Decimal, flows: Sequence[tuple[int, Decimal]]) -> Decimal:
    """Net present value of dated *flows* at per-period *rate* (``rate > -1``)."""
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        base = Decimal(1) + rate
        total = Decimal(0)
        for period, amount in flows:
            total += amount / (base**period)
        return +total


def money_weighted_return(cashflows: Sequence[tuple[int, Decimal]]) -> Decimal:
    """Money-weighted return (internal rate of return) of dated cash flows.

    Each entry is ``(period, amount)`` where ``period`` is a non-negative
    integer number of periods from the start and ``amount`` is signed
    (negative = contribution/outflow, positive = withdrawal/inflow). The IRR is
    the per-period rate ``r`` that makes the net present value zero.

    Convergence: the root is found by **bisection**, which is unconditionally
    convergent once bracketed. The bracket starts at ``(-0.999999, 1.0)`` and
    the upper bound is doubled (up to ``1e6``) until the NPV changes sign; the
    interval is then halved up to 300 times until it is narrower than the
    statistical quantum. A cash-flow set with no sign change (and hence no real
    IRR in range) raises :class:`PortfolioError`.
    """
    items: list[tuple[int, Decimal]] = []
    for entry in cashflows:
        period, amount = entry
        if not isinstance(period, int) or isinstance(period, bool):
            raise PortfolioError("cash-flow period must be an int number of periods")
        if period < 0:
            raise PortfolioError("cash-flow period must be non-negative")
        items.append((period, as_decimal(amount)))
    if not items:
        raise PortfolioError("money_weighted_return requires at least one cash flow")

    lo = Decimal("-0.999999")
    hi = Decimal("1")
    f_lo = _npv(lo, items)
    f_hi = _npv(hi, items)
    while f_lo * f_hi > 0 and hi < Decimal("1000000"):
        hi *= 2
        f_hi = _npv(hi, items)
    if f_lo * f_hi > 0:
        raise PortfolioError(
            "cash flows have no sign change; the internal rate of return "
            "cannot be bracketed"
        )

    tolerance = STAT_QUANTUM
    mid = (lo + hi) / 2
    for _ in range(300):
        mid = (lo + hi) / 2
        f_mid = _npv(mid, items)
        if f_mid == 0 or (hi - lo) < tolerance:
            break
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo = mid
            f_lo = f_mid
    return quantize(mid, STAT_QUANTUM)


# --------------------------------------------------------------------------
# Risk statistics
# --------------------------------------------------------------------------


def volatility(returns: Sequence[Decimal]) -> Decimal:
    """Return volatility: the sample standard deviation of *returns*.

    Delegates to :func:`strix.native.statistics.stdev` (``sample=True``), which
    rejects ``float`` and requires at least two observations.
    """
    return stdev(returns, sample=True)


def max_drawdown(values: Sequence[Decimal]) -> Decimal:
    """Maximum peak-to-trough decline of a value series, as a positive fraction.

    Walks the running peak and returns the largest ``(peak - value) / peak``
    observed; a monotonically non-decreasing series yields ``Decimal("0")``.
    Raises :class:`PortfolioError` if the running peak is ever non-positive
    (a drawdown fraction is undefined there).
    """
    items = _coerce_series(values, what="values")
    worst = Decimal(0)
    peak = items[0]
    for value in items:
        if value > peak:
            peak = value
        if peak <= 0:
            raise PortfolioError("max_drawdown requires a positive running peak")
        drop = checked_div(checked_sub(peak, value), peak)
        if drop > worst:
            worst = drop
    return quantize(worst, STAT_QUANTUM)


def correlation(a: Sequence[Decimal], b: Sequence[Decimal]) -> Decimal:
    """Pearson correlation coefficient of two equal-length series.

    Computed as ``cov(a, b) / (||a - mean_a|| * ||b - mean_b||)`` with exact
    Decimal arithmetic. Raises :class:`PortfolioError` for a length mismatch or
    fewer than two observations, and ``CalculationError`` (via the zero-division
    guard) when either series is constant (an undefined correlation).
    """
    xs = _coerce_series(a, what="a")
    ys = _coerce_series(b, what="b")
    if len(xs) != len(ys):
        raise PortfolioError("correlation requires two equal-length series")
    if len(xs) < 2:
        raise PortfolioError("correlation requires at least two observations")
    mean_x = checked_div(checked_sum(xs), Decimal(len(xs)))
    mean_y = checked_div(checked_sum(ys), Decimal(len(ys)))
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        cov = Decimal(0)
        var_x = Decimal(0)
        var_y = Decimal(0)
        for x, y in zip(xs, ys, strict=True):
            dx = x - mean_x
            dy = y - mean_y
            cov += dx * dy
            var_x += dx * dx
            var_y += dy * dy
        denom_sq = var_x * var_y
    denom = _sqrt_exact(denom_sq)
    return quantize(checked_div(cov, denom), STAT_QUANTUM)


def _sqrt_exact(value: Decimal) -> Decimal:
    """Non-negative square root inside a local high-precision context."""
    guarded = require_finite(value)
    if guarded < 0:
        raise PortfolioError("cannot take the square root of a negative value")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        return guarded.sqrt()


# --------------------------------------------------------------------------
# Drift and rebalancing (recommendation only — never executes trades)
# --------------------------------------------------------------------------


def allocation_drift(
    current: Mapping[str, Decimal], target: Mapping[str, Decimal]
) -> dict[str, Decimal]:
    """Per-key weight drift ``current - target`` over the union of keys.

    A key absent from one side is treated as a zero weight there. A positive
    drift means the book is **over**-weight that key relative to target.
    """
    keys = sorted(set(current) | set(target))
    drift: dict[str, Decimal] = {}
    for key in keys:
        cur = as_decimal(current.get(key, Decimal(0)))
        tgt = as_decimal(target.get(key, Decimal(0)))
        drift[key] = checked_sub(cur, tgt)
    return drift


def rebalancing_trades(
    current: Mapping[str, Decimal],
    target: Mapping[str, Decimal],
    total_value: Decimal,
) -> tuple[tuple[str, Decimal], ...]:
    """Recommend per-symbol value changes to move *current* weights to *target*.

    For each symbol the recommended change is
    ``(target_weight - current_weight) * total_value`` — positive means *buy*
    that much notional, negative means *sell*. Because both weight maps sum to
    one over the same key union, the deltas sum to (approximately) zero: the
    recommendation is self-funding.

    This is **advisory only**. It returns a sorted tuple of
    ``(symbol, delta_value)`` pairs and never places or routes an order.
    """
    total = as_decimal(total_value)
    keys = sorted(set(current) | set(target))
    trades: list[tuple[str, Decimal]] = []
    for key in keys:
        cur = as_decimal(current.get(key, Decimal(0)))
        tgt = as_decimal(target.get(key, Decimal(0)))
        delta = _exact_mul(checked_sub(tgt, cur), total)
        trades.append((key, delta))
    return tuple(trades)
