"""Hand-verified tests for reproducible technical indicators.

Every numeric expectation in this module is hand-computed in the test
docstrings/comments so the indicator implementation is checked against an
independent calculation rather than against itself. Money/ratio values are
exact :class:`~decimal.Decimal` quantized to the native statistical quantum
(12 decimal places).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from strix.errors import StrixError
from strix.market.indicators import (
    IndicatorResult,
    atr,
    correlation,
    dmi,
    ema,
    macd,
    max_drawdown,
    realized_volatility,
    relative_volume,
    returns,
    rsi,
    sma,
    trend_strength,
)

# --------------------------------------------------------------------------
# sma / ema (hand-computed)
# --------------------------------------------------------------------------


def test_sma_known_value() -> None:
    """prices=[1,2,3,4], window=2 -> MAs [1.5,2.5,3.5]; latest = 3.5."""
    result = sma([1, 2, 3, 4], 2)
    assert isinstance(result, IndicatorResult)
    assert result.value == Decimal("3.5")
    assert result.window == 2
    assert result.observations == 4
    assert result.method == "sma"
    assert result.name == "sma"


def test_ema_known_value() -> None:
    """span=2 -> alpha=2/3, seed=1.

    y0=1
    y1=(2/3)*2+(1/3)*1 = 5/3
    y2=(2/3)*3+(1/3)*(5/3) = 2 + 5/9 = 23/9 = 2.555555555556
    """
    result = ema([1, 2, 3], 2)
    assert result.value == Decimal("2.555555555556")
    assert result.window == 2
    assert result.observations == 3
    assert result.method == "ema"


def test_sma_rejects_short_series() -> None:
    with pytest.raises(StrixError):
        sma([1, 2], 3)


def test_ema_rejects_short_series() -> None:
    with pytest.raises(StrixError):
        ema([1], 2)


# --------------------------------------------------------------------------
# rsi (Wilder, hand-computed)
# --------------------------------------------------------------------------


def test_rsi_hand_computed() -> None:
    """period=2, prices=[10,11,10,11,12].

    deltas  : +1,-1,+1,+1
    gains   :  1, 0, 1, 1
    losses  :  0, 1, 0, 0
    seed avg_gain=(1+0)/2=0.5 ; seed avg_loss=(0+1)/2=0.5
    step3: avg_gain=(0.5*1+1)/2=0.75 ; avg_loss=(0.5*1+0)/2=0.25
    step4: avg_gain=(0.75*1+1)/2=0.875 ; avg_loss=(0.25*1+0)/2=0.125
    RS=0.875/0.125=7 ; RSI=100-100/(1+7)=87.5
    """
    result = rsi([10, 11, 10, 11, 12], period=2)
    assert result.value == Decimal("87.5")
    assert result.method == "wilder"
    assert result.window == 2
    assert result.observations == 5


def test_rsi_all_gains_is_100() -> None:
    result = rsi([1, 2, 3, 4, 5], period=2)
    assert result.value == Decimal("100")


def test_rsi_all_losses_is_zero() -> None:
    result = rsi([5, 4, 3, 2, 1], period=2)
    assert result.value == Decimal("0")


def test_rsi_rejects_short_series() -> None:
    # Needs period + 1 prices.
    with pytest.raises(StrixError):
        rsi([10, 11], period=2)


# --------------------------------------------------------------------------
# atr (Wilder, hand-computed)
# --------------------------------------------------------------------------


def test_atr_hand_computed() -> None:
    """period=3.

    bars (high, low, close):
      0: 10, 8, 9        TR0 = 10-8 = 2
      1: 12, 9, 11       TR1 = max(12-9, |12-9|, |9-9|) = 3   (prev close 9)
      2: 13, 11, 12      TR2 = max(13-11, |13-11|, |11-11|) = 2 (prev close 11)
      3: 12, 10, 10      TR3 = max(12-10, |12-12|, |10-12|) = 2 (prev close 12)
    seed=(2+3+2)/3=7/3=2.333333333333
    ATR=(seed*2 + TR3)/3 = (14/3 + 2)/3 = 20/9 = 2.222222222222
    """
    result = atr(
        [10, 12, 13, 12],
        [8, 9, 11, 10],
        [9, 11, 12, 10],
        period=3,
    )
    assert result.value == Decimal("2.222222222222")
    assert result.method == "wilder"
    assert result.window == 3
    assert result.observations == 4


def test_atr_rejects_short_series() -> None:
    with pytest.raises(StrixError):
        atr([10, 12, 13], [8, 9, 11], [9, 11, 12], period=3)


def test_atr_rejects_mismatched_lengths() -> None:
    with pytest.raises(StrixError):
        atr([10, 12, 13, 12], [8, 9, 11], [9, 11, 12, 10], period=3)


# --------------------------------------------------------------------------
# dmi / adx (Wilder, hand-computed pure uptrend)
# --------------------------------------------------------------------------


def test_dmi_pure_uptrend() -> None:
    """period=2; a trend with every -DM == 0.

    bars (high, low, close):
      0: 10,  8,  9
      1: 12,  9, 11   +DM=2 -DM=0  TR=3
      2: 14, 11, 13   +DM=2 -DM=0  TR=3
      3: 13, 11, 12   +DM=0 -DM=0  TR=2
      4: 15, 12, 14   +DM=2 -DM=0  TR=3
      5: 16, 14, 15   +DM=1 -DM=0  TR=2
    wilder(+DM,2): 2 -> 1 -> 1.5 -> 1.25
    wilder(TR,2) : 3 -> 2.5 -> 2.75 -> 2.375
    +DI=100*1.25/2.375=52.631578947368 ; -DI=0
    every DX=100 so ADX=100
    """
    di_plus, di_minus, adx = dmi(
        [10, 12, 14, 13, 15, 16],
        [8, 9, 11, 11, 12, 14],
        [9, 11, 13, 12, 14, 15],
        period=2,
    )
    assert di_minus.value == Decimal("0")
    assert di_plus.value == Decimal("52.631578947368")
    assert adx.value == Decimal("100")
    assert di_plus.name == "di_plus"
    assert di_minus.name == "di_minus"
    assert adx.name == "adx"
    assert adx.method == "wilder"


def test_trend_strength_matches_adx() -> None:
    highs = [10, 12, 14, 13, 15, 16]
    lows = [8, 9, 11, 11, 12, 14]
    closes = [9, 11, 13, 12, 14, 15]
    ts = trend_strength(highs, lows, closes, period=2)
    _, _, adx = dmi(highs, lows, closes, period=2)
    assert ts.value == adx.value
    assert ts.name == "trend_strength"


def test_dmi_rejects_short_series() -> None:
    # Needs 2 * period bars.
    with pytest.raises(StrixError):
        dmi([10, 12, 14], [8, 9, 11], [9, 11, 13], period=2)


# --------------------------------------------------------------------------
# macd (structure / sign)
# --------------------------------------------------------------------------


def test_macd_structure_uptrend() -> None:
    prices = [1, 2, 3, 4, 5, 6]
    macd_line, signal_line, histogram = macd(prices, fast=2, slow=3, signal=2)
    # Fast EMA leads a rising series, so MACD line is positive.
    assert macd_line.value > 0
    # Histogram is exactly MACD - signal at the latest point.
    assert histogram.value == macd_line.value - signal_line.value
    assert macd_line.name == "macd_line"
    assert signal_line.name == "signal_line"
    assert histogram.name == "macd_histogram"


def test_macd_rejects_short_series() -> None:
    with pytest.raises(StrixError):
        macd([1, 2], fast=2, slow=3, signal=2)


# --------------------------------------------------------------------------
# returns / volatility / drawdown / relative volume / correlation
# --------------------------------------------------------------------------


def test_returns_hand_computed() -> None:
    """prices=[10,11,12] -> [(11-10)/10, (12-11)/11] = [0.1, 1/11]."""
    result = returns([10, 11, 12])
    assert result == (Decimal("0.1"), Decimal("0.090909090909"))


def test_returns_rejects_short_series() -> None:
    with pytest.raises(StrixError):
        returns([10])


def test_realized_volatility_hand_computed() -> None:
    """prices=[100,110,99] -> returns [0.1, -0.1].

    mean 0 ; sample variance=(0.01+0.01)/1=0.02 ; stdev=sqrt(0.02).
    periods_per_year=1 -> annualized = stdev = 0.141421356237.
    """
    result = realized_volatility([100, 110, 99], periods_per_year=1)
    assert result.value == Decimal("0.141421356237")
    assert result.window == 1


def test_max_drawdown_hand_computed() -> None:
    """prices=[10,12,9,11,8]; running peak hits 12, trough 8 -> 4/12."""
    result = max_drawdown([10, 12, 9, 11, 8])
    assert result.value == Decimal("0.333333333333")
    assert result.name == "max_drawdown"


def test_max_drawdown_monotonic_is_zero() -> None:
    result = max_drawdown([1, 2, 3, 4])
    assert result.value == Decimal("0")


def test_relative_volume_hand_computed() -> None:
    """volumes=[100,200,300,400], window=3.

    baseline = mean(last 3) = (200+300+400)/3 = 300 ; latest = 400.
    relative volume = 400/300 = 1.333333333333.
    """
    result = relative_volume([100, 200, 300, 400], window=3)
    assert result.value == Decimal("1.333333333333")
    assert result.window == 3


def test_relative_volume_rejects_short_series() -> None:
    with pytest.raises(StrixError):
        relative_volume([100, 200], window=3)


def test_correlation_identical_returns_is_one() -> None:
    result = correlation([1, 2, 3, 4], [2, 4, 6, 8])
    assert result.value == Decimal("1")
    assert result.name == "correlation"


def test_correlation_rejects_short_series() -> None:
    with pytest.raises(StrixError):
        correlation([1, 2], [2, 4])


# --------------------------------------------------------------------------
# cross-cutting: exact Decimal + determinism
# --------------------------------------------------------------------------


def test_all_values_are_decimal() -> None:
    assert isinstance(sma([1, 2, 3], 2).value, Decimal)
    assert isinstance(rsi([10, 11, 10, 11, 12], period=2).value, Decimal)
    atr_result = atr([10, 12, 13, 12], [8, 9, 11, 10], [9, 11, 12, 10], period=3)
    assert isinstance(atr_result.value, Decimal)


def test_determinism() -> None:
    args = ([10, 11, 10, 11, 12],)
    first = rsi(*args, period=2)
    second = rsi(*args, period=2)
    assert first == second
    assert first.value == second.value
