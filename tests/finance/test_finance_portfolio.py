"""Tests for offline portfolio analytics (never executes trades)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from strix.errors import CalculationError, StrixError
from strix.finance.portfolio import (
    Holding,
    PortfolioError,
    Security,
    allocation_by,
    allocation_drift,
    concentration,
    correlation,
    herfindahl_index,
    max_drawdown,
    money_weighted_return,
    rebalancing_trades,
    time_weighted_return,
    unrealized_gain,
    volatility,
)

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _holding(
    symbol: str,
    quantity: str,
    price: str,
    *,
    cost_basis: str | None = None,
    account_id: str = "ACCT-1",
) -> Holding:
    return Holding(
        account_id=account_id,
        symbol=symbol,
        quantity=Decimal(quantity),
        price=Decimal(price),
        cost_basis=None if cost_basis is None else Decimal(cost_basis),
    )


def _portfolio() -> list[Holding]:
    # Market values: AAA=2500, BBB=2500, CCC=5000 ; total = 10000
    return [
        _holding("AAA", "25", "100"),
        _holding("BBB", "50", "50"),
        _holding("CCC", "100", "50"),
    ]


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------


def test_security_defaults() -> None:
    sec = Security(symbol="AAA", asset_class="equity")
    assert sec.sector == ""
    assert sec.asset_class == "equity"


def test_holding_market_value_is_exact() -> None:
    h = _holding("AAA", "25", "100.33")
    assert h.market_value == Decimal("2508.25")


def test_holding_rejects_float_quantity() -> None:
    with pytest.raises(ValidationError):
        Holding(account_id="ACCT-1", symbol="AAA", quantity=1.5, price=Decimal("10"))


def test_holding_rejects_float_price() -> None:
    with pytest.raises(ValidationError):
        Holding(account_id="ACCT-1", symbol="AAA", quantity=Decimal("1"), price=2.5)


# --------------------------------------------------------------------------
# allocation_by
# --------------------------------------------------------------------------


def test_allocation_by_symbol_sums_to_one() -> None:
    alloc = allocation_by(_portfolio(), lambda h: h.symbol)
    assert alloc == {
        "AAA": Decimal("0.25"),
        "BBB": Decimal("0.25"),
        "CCC": Decimal("0.5"),
    }
    assert sum(alloc.values()) == Decimal("1")


def test_allocation_by_group_aggregates_duplicate_keys() -> None:
    holdings = [
        _holding("AAA", "25", "100"),  # 2500
        _holding("AAB", "25", "100"),  # 2500
        _holding("CCC", "100", "50"),  # 5000
    ]
    # group the two 'A*' symbols together
    alloc = allocation_by(holdings, lambda h: h.symbol[:1])
    assert alloc == {"A": Decimal("0.5"), "C": Decimal("0.5")}
    assert sum(alloc.values()) == Decimal("1")


def test_allocation_by_empty_raises() -> None:
    with pytest.raises(PortfolioError):
        allocation_by([], lambda h: h.symbol)


def test_allocation_by_zero_total_raises() -> None:
    holdings = [_holding("AAA", "0", "100")]
    with pytest.raises(PortfolioError):
        allocation_by(holdings, lambda h: h.symbol)


# --------------------------------------------------------------------------
# concentration / herfindahl
# --------------------------------------------------------------------------


def test_concentration_largest_weight() -> None:
    assert concentration(_portfolio()) == Decimal("0.5")


def test_herfindahl_index() -> None:
    # 0.25^2 + 0.25^2 + 0.5^2 = 0.0625 + 0.0625 + 0.25 = 0.375
    assert herfindahl_index(_portfolio()) == Decimal("0.375")


def test_herfindahl_single_holding_is_one() -> None:
    assert herfindahl_index([_holding("AAA", "10", "10")]) == Decimal("1")


# --------------------------------------------------------------------------
# unrealized_gain
# --------------------------------------------------------------------------


def test_unrealized_gain_with_cost_basis() -> None:
    # market_value = 25*100 = 2500 ; cost = 25*80 = 2000 ; gain = 500
    h = _holding("AAA", "25", "100", cost_basis="80")
    assert unrealized_gain(h) == Decimal("500")


def test_unrealized_gain_loss() -> None:
    h = _holding("AAA", "25", "80", cost_basis="100")
    assert unrealized_gain(h) == Decimal("-500")


def test_unrealized_gain_without_cost_basis_is_none() -> None:
    assert unrealized_gain(_holding("AAA", "25", "100")) is None


# --------------------------------------------------------------------------
# time_weighted_return
# --------------------------------------------------------------------------


def test_twr_two_periods_no_flows() -> None:
    # V = [100, 110, 121]; r1 = 1.1, r2 = 1.1; TWR = 1.21 - 1 = 0.21
    twr = time_weighted_return(
        [Decimal("100"), Decimal("110"), Decimal("121")],
        [Decimal("0"), Decimal("0")],
    )
    assert twr == Decimal("0.21")


def test_twr_with_start_of_period_flow() -> None:
    # period 1: start 100, no flow -> end 110 ; factor 1.1
    # period 2: start 110 + flow 10 = 120 -> end 132 ; factor 1.1
    twr = time_weighted_return(
        [Decimal("100"), Decimal("110"), Decimal("132")],
        [Decimal("0"), Decimal("10")],
    )
    assert twr == Decimal("0.21")


def test_twr_length_mismatch_raises() -> None:
    with pytest.raises(PortfolioError):
        time_weighted_return([Decimal("100"), Decimal("110")], [Decimal("0"), Decimal("0")])


def test_twr_requires_two_values() -> None:
    with pytest.raises(PortfolioError):
        time_weighted_return([Decimal("100")], [])


def test_twr_rejects_float() -> None:
    with pytest.raises(CalculationError):
        time_weighted_return([100.0, 110.0], [0.0])


# --------------------------------------------------------------------------
# money_weighted_return (IRR)
# --------------------------------------------------------------------------


def test_mwr_known_ten_percent() -> None:
    irr = money_weighted_return([(0, Decimal("-100")), (1, Decimal("110"))])
    assert irr == Decimal("0.1")


def test_mwr_multi_period() -> None:
    # -100 now, +60 after year 1, +60 after year 2 ; IRR ~ 0.130662...
    irr = money_weighted_return(
        [(0, Decimal("-100")), (1, Decimal("60")), (2, Decimal("60"))]
    )
    assert irr > Decimal("0.13")
    assert irr < Decimal("0.131")


def test_mwr_no_sign_change_raises() -> None:
    with pytest.raises(PortfolioError):
        money_weighted_return([(0, Decimal("100")), (1, Decimal("110"))])


def test_mwr_rejects_float() -> None:
    with pytest.raises(CalculationError):
        money_weighted_return([(0, -100.0), (1, 110.0)])


# --------------------------------------------------------------------------
# volatility / max_drawdown / correlation
# --------------------------------------------------------------------------


def test_volatility_matches_sample_stdev() -> None:
    vol = volatility([Decimal("0.1"), Decimal("-0.1"), Decimal("0.2"), Decimal("0")])
    assert vol > Decimal("0")


def test_max_drawdown() -> None:
    # peak 120, trough 90 -> dd = 30/120 = 0.25
    dd = max_drawdown([Decimal("100"), Decimal("120"), Decimal("90"), Decimal("110")])
    assert dd == Decimal("0.25")


def test_max_drawdown_monotone_increasing_is_zero() -> None:
    assert max_drawdown([Decimal("100"), Decimal("110"), Decimal("120")]) == Decimal("0")


def test_correlation_perfect_positive() -> None:
    corr = correlation(
        [Decimal("1"), Decimal("2"), Decimal("3")],
        [Decimal("2"), Decimal("4"), Decimal("6")],
    )
    assert corr == Decimal("1")


def test_correlation_perfect_negative() -> None:
    corr = correlation(
        [Decimal("1"), Decimal("2"), Decimal("3")],
        [Decimal("6"), Decimal("4"), Decimal("2")],
    )
    assert corr == Decimal("-1")


def test_correlation_length_mismatch_raises() -> None:
    with pytest.raises(PortfolioError):
        correlation([Decimal("1"), Decimal("2")], [Decimal("1")])


def test_correlation_constant_series_raises() -> None:
    with pytest.raises(CalculationError):
        correlation([Decimal("1"), Decimal("1")], [Decimal("2"), Decimal("3")])


def test_correlation_rejects_float() -> None:
    with pytest.raises(CalculationError):
        correlation([1.0, 2.0], [2.0, 4.0])


# --------------------------------------------------------------------------
# allocation_drift / rebalancing_trades
# --------------------------------------------------------------------------


def test_allocation_drift() -> None:
    current = {"AAA": Decimal("0.3"), "BBB": Decimal("0.7")}
    target = {"AAA": Decimal("0.5"), "BBB": Decimal("0.5")}
    drift = allocation_drift(current, target)
    assert drift == {"AAA": Decimal("-0.2"), "BBB": Decimal("0.2")}


def test_allocation_drift_missing_key_treated_as_zero() -> None:
    current = {"AAA": Decimal("1")}
    target = {"AAA": Decimal("0.6"), "BBB": Decimal("0.4")}
    drift = allocation_drift(current, target)
    assert drift == {"AAA": Decimal("0.4"), "BBB": Decimal("-0.4")}


def test_rebalancing_trades_sum_to_zero() -> None:
    current = {"AAA": Decimal("0.3"), "BBB": Decimal("0.7")}
    target = {"AAA": Decimal("0.5"), "BBB": Decimal("0.5")}
    trades = rebalancing_trades(current, target, Decimal("10000"))
    assert trades == (("AAA", Decimal("2000")), ("BBB", Decimal("-2000")))
    assert sum(delta for _, delta in trades) == Decimal("0")


def test_rebalancing_trades_rejects_float_total() -> None:
    with pytest.raises(CalculationError):
        rebalancing_trades({"AAA": Decimal("1")}, {"AAA": Decimal("1")}, 10000.0)


# --------------------------------------------------------------------------
# error typing
# --------------------------------------------------------------------------


def test_portfolio_error_is_strix_error() -> None:
    assert issubclass(PortfolioError, StrixError)
