"""Reproducible technical indicators as exact :class:`~decimal.Decimal` values.

Every indicator in this module is an *independently reproducible* computation:
the methodology, observation window, and minimum-observation requirement travel
with the number inside an :class:`IndicatorResult`, and the arithmetic is exact
``Decimal`` (binary ``float`` is forbidden by the native layer).

Smoothing conventions (chosen explicitly and documented per function):

- **SMA** — simple (equal-weight) moving average over a trailing window.
- **EMA** — exponential moving average seeded with ``prices[0]`` and advanced as
  ``y[i] = alpha * x[i] + (1 - alpha) * y[i-1]`` with ``alpha = 2 / (span + 1)``.
- **Wilder** — Wilder's recursive smoothing (RSI, ATR, ADX): the first value is
  the simple average of the first ``period`` observations, and each subsequent
  value is ``(prev * (period - 1) + current) / period``. Wilder smoothing reacts
  more slowly than an EMA of the same period (it is equivalent to an EMA with
  ``alpha = 1 / period``).

All results are quantized to :data:`strix.native.arithmetic.STAT_QUANTUM`
(12 decimal places) so they are reproducible and canonically hashable. Series
shorter than the methodology's minimum observation requirement are rejected with
:class:`strix.errors.StrixError`.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from pydantic import Field

from strix.errors import StrixError
from strix.models import DecimalValue, StrixModel
from strix.native import timeseries
from strix.native.arithmetic import ARITH_PRECISION, STAT_QUANTUM, as_decimal, quantize
from strix.native.multivariate import correlation as _native_correlation

__all__ = [
    "IndicatorResult",
    "atr",
    "correlation",
    "dmi",
    "ema",
    "macd",
    "max_drawdown",
    "realized_volatility",
    "relative_volume",
    "returns",
    "rsi",
    "sma",
    "trend_strength",
    "wilder_smooth",
]


class IndicatorResult(StrixModel):
    """A single indicator value carrying its own methodology provenance.

    Attributes:
        name: Short indicator identifier (e.g. ``"rsi"``, ``"di_plus"``).
        value: The exact ``Decimal`` indicator value (quantized to 12 dp).
        method: The smoothing/estimation convention used (``"sma"``, ``"ema"``,
            ``"wilder"``, ``"ratio"``, ``"pearson"`` ...).
        window: The observation window / period parameter the value was computed
            with.
        observations: The number of input observations consumed.
        as_of: Optional caller-supplied timestamp/label for the final bar.
    """

    name: str = Field(description="Short indicator identifier.")
    value: DecimalValue = Field(description="Exact Decimal value (quantized).")
    method: str = Field(description="Smoothing/estimation convention used.")
    window: int = Field(ge=1, description="Observation window / period.")
    observations: int = Field(ge=1, description="Input observations consumed.")
    as_of: str = Field(default="", description="Optional label for the final bar.")


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------


def _q(value: Decimal) -> Decimal:
    """Quantize a result to the canonical statistical quantum (12 dp)."""
    return quantize(value, STAT_QUANTUM)


def _coerce(series: Sequence[object], *, what: str) -> list[Decimal]:
    """Coerce every element to a finite ``Decimal`` (rejecting float/NaN/Inf)."""
    if not isinstance(series, Sequence) or isinstance(series, (str, bytes)):
        raise StrixError(f"{what} must be a sequence of numbers")
    return [as_decimal(x) for x in series]


def _require_period(period: int, *, what: str) -> int:
    """Validate a positive integer period."""
    if not isinstance(period, int) or isinstance(period, bool):
        raise StrixError(f"{what} must be an int")
    if period < 1:
        raise StrixError(f"{what} must be >= 1")
    return period


def wilder_smooth(values: Sequence[object], period: int) -> tuple[Decimal, ...]:
    """Wilder's recursive smoothing of ``values`` over ``period``.

    The first output is the simple average of ``values[:period]`` (Wilder's
    seed); each subsequent output is ``(prev * (period - 1) + current) / period``.
    The returned tuple has length ``len(values) - period + 1`` and is aligned so
    that output ``k`` summarizes through ``values[period - 1 + k]``.

    Raises:
        StrixError: if there are fewer than ``period`` observations.
    """
    _require_period(period, what="period")
    vals = _coerce(values, what="values")
    if len(vals) < period:
        raise StrixError(
            f"wilder_smooth requires at least period={period} observations, "
            f"got {len(vals)}"
        )
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        seed = sum(vals[:period], Decimal(0)) / Decimal(period)
        out: list[Decimal] = [_q(seed)]
        prev = out[0]
        divisor = Decimal(period)
        weight = Decimal(period - 1)
        for current in vals[period:]:
            prev = _q((prev * weight + current) / divisor)
            out.append(prev)
        return tuple(out)


# --------------------------------------------------------------------------
# Moving averages
# --------------------------------------------------------------------------


def sma(prices: Sequence[object], window: int) -> IndicatorResult:
    """Latest simple moving average over a trailing ``window``.

    Reuses :func:`strix.native.timeseries.moving_average` and reports its final
    (most recent) value. Requires at least ``window`` observations.
    """
    _require_period(window, what="window")
    vals = _coerce(prices, what="prices")
    if len(vals) < window:
        raise StrixError(
            f"sma requires at least window={window} observations, got {len(vals)}"
        )
    series = timeseries.moving_average(vals, window)
    return IndicatorResult(
        name="sma",
        value=series[-1],
        method="sma",
        window=window,
        observations=len(vals),
    )


def ema(prices: Sequence[object], span: int) -> IndicatorResult:
    """Latest exponential moving average for ``span`` (``alpha = 2/(span+1)``).

    Reuses :func:`strix.native.timeseries.ewma`, seeded with ``prices[0]``, and
    reports its final value. Requires at least ``span`` observations so the
    smoothing is meaningful rather than dominated by the seed.
    """
    _require_period(span, what="span")
    vals = _coerce(prices, what="prices")
    if len(vals) < span:
        raise StrixError(
            f"ema requires at least span={span} observations, got {len(vals)}"
        )
    series = timeseries.ewma(vals, span=span)
    return IndicatorResult(
        name="ema",
        value=series[-1],
        method="ema",
        window=span,
        observations=len(vals),
    )


# --------------------------------------------------------------------------
# RSI (Wilder)
# --------------------------------------------------------------------------


def rsi(prices: Sequence[object], *, period: int = 14) -> IndicatorResult:
    """Wilder-smoothed Relative Strength Index in ``[0, 100]``.

    Price changes are split into gains (``max(delta, 0)``) and losses
    (``max(-delta, 0)``); the average gain and loss are Wilder-smoothed over
    ``period`` and combined as ``RSI = 100 - 100 / (1 + avg_gain/avg_loss)``.
    A zero average loss yields ``100`` and a zero average gain yields ``0``.

    Requires at least ``period + 1`` prices (``period`` price changes).
    """
    _require_period(period, what="period")
    vals = _coerce(prices, what="prices")
    if len(vals) < period + 1:
        raise StrixError(
            f"rsi requires at least period+1={period + 1} prices, got {len(vals)}"
        )
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        gains: list[Decimal] = []
        losses: list[Decimal] = []
        for i in range(1, len(vals)):
            delta = vals[i] - vals[i - 1]
            gains.append(delta if delta > 0 else Decimal(0))
            losses.append(-delta if delta < 0 else Decimal(0))
        avg_gain = wilder_smooth(gains, period)[-1]
        avg_loss = wilder_smooth(losses, period)[-1]
        if avg_loss == 0:
            value = Decimal(0) if avg_gain == 0 else Decimal(100)
        else:
            rs = avg_gain / avg_loss
            value = Decimal(100) - Decimal(100) / (Decimal(1) + rs)
        value = _q(value)
    return IndicatorResult(
        name="rsi",
        value=value,
        method="wilder",
        window=period,
        observations=len(vals),
    )


# --------------------------------------------------------------------------
# True range / ATR / DMI (Wilder)
# --------------------------------------------------------------------------


def _true_ranges(
    highs: list[Decimal], lows: list[Decimal], closes: list[Decimal]
) -> list[Decimal]:
    """True range per bar; the first bar is ``high - low`` (no prior close)."""
    tr: list[Decimal] = [highs[0] - lows[0]]
    for i in range(1, len(highs)):
        prev_close = closes[i - 1]
        tr.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - prev_close),
                abs(lows[i] - prev_close),
            )
        )
    return tr


def _coerce_hlc(
    highs: Sequence[object], lows: Sequence[object], closes: Sequence[object]
) -> tuple[list[Decimal], list[Decimal], list[Decimal]]:
    """Coerce and length-check three aligned OHLC columns."""
    h = _coerce(highs, what="highs")
    low = _coerce(lows, what="lows")
    c = _coerce(closes, what="closes")
    if not (len(h) == len(low) == len(c)):
        raise StrixError(
            f"highs/lows/closes must be equal length, got "
            f"{len(h)}/{len(low)}/{len(c)}"
        )
    return h, low, c


def atr(
    highs: Sequence[object],
    lows: Sequence[object],
    closes: Sequence[object],
    *,
    period: int = 14,
) -> IndicatorResult:
    """Wilder's Average True Range (volatility, in price units).

    True range is Wilder-smoothed over ``period``. Requires at least
    ``period + 1`` bars (``period`` true ranges to seed plus one to smooth).
    """
    _require_period(period, what="period")
    h, low, c = _coerce_hlc(highs, lows, closes)
    if len(h) < period + 1:
        raise StrixError(
            f"atr requires at least period+1={period + 1} bars, got {len(h)}"
        )
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        tr = _true_ranges(h, low, c)
        value = wilder_smooth(tr, period)[-1]
    return IndicatorResult(
        name="atr",
        value=value,
        method="wilder",
        window=period,
        observations=len(h),
    )


def _directional_movement(
    highs: list[Decimal], lows: list[Decimal]
) -> tuple[list[Decimal], list[Decimal]]:
    """Wilder's +DM / -DM series (length ``n - 1``)."""
    plus: list[Decimal] = []
    minus: list[Decimal] = []
    for i in range(1, len(highs)):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus.append(up_move if up_move > down_move and up_move > 0 else Decimal(0))
        minus.append(down_move if down_move > up_move and down_move > 0 else Decimal(0))
    return plus, minus


def dmi(
    highs: Sequence[object],
    lows: Sequence[object],
    closes: Sequence[object],
    *,
    period: int = 14,
) -> tuple[IndicatorResult, IndicatorResult, IndicatorResult]:
    """Directional Movement Index: ``(+DI, -DI, ADX)``.

    +DM/-DM and true range are Wilder-smoothed over ``period``; then
    ``+DI = 100 * +DM_s / TR_s``, ``-DI = 100 * -DM_s / TR_s``,
    ``DX = 100 * |+DI - -DI| / (+DI + -DI)``, and ``ADX`` is the Wilder-smoothed
    average of ``DX`` over ``period``.

    Requires at least ``2 * period`` bars so ``ADX`` has ``period`` DX values to
    seed from.
    """
    _require_period(period, what="period")
    h, low, c = _coerce_hlc(highs, lows, closes)
    if len(h) < 2 * period:
        raise StrixError(
            f"dmi requires at least 2*period={2 * period} bars, got {len(h)}"
        )
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        plus_dm, minus_dm = _directional_movement(h, low)
        tr = _true_ranges(h, low, c)[1:]  # align with DM (drop seed-only TR0)
        plus_s = wilder_smooth(plus_dm, period)
        minus_s = wilder_smooth(minus_dm, period)
        tr_s = wilder_smooth(tr, period)
        dx_series: list[Decimal] = []
        plus_di_last = Decimal(0)
        minus_di_last = Decimal(0)
        hundred = Decimal(100)
        for p_s, m_s, t_s in zip(plus_s, minus_s, tr_s, strict=True):
            plus_di = hundred * p_s / t_s if t_s != 0 else Decimal(0)
            minus_di = hundred * m_s / t_s if t_s != 0 else Decimal(0)
            denom = plus_di + minus_di
            dx = hundred * abs(plus_di - minus_di) / denom if denom != 0 else Decimal(0)
            dx_series.append(dx)
            plus_di_last = plus_di
            minus_di_last = minus_di
        adx_value = wilder_smooth(dx_series, period)[-1]
        plus_di_value = _q(plus_di_last)
        minus_di_value = _q(minus_di_last)
        adx_value = _q(adx_value)
    obs = len(h)
    di_plus = IndicatorResult(
        name="di_plus", value=plus_di_value, method="wilder", window=period, observations=obs
    )
    di_minus = IndicatorResult(
        name="di_minus", value=minus_di_value, method="wilder", window=period, observations=obs
    )
    adx = IndicatorResult(
        name="adx", value=adx_value, method="wilder", window=period, observations=obs
    )
    return di_plus, di_minus, adx


def trend_strength(
    highs: Sequence[object],
    lows: Sequence[object],
    closes: Sequence[object],
    *,
    period: int = 14,
) -> IndicatorResult:
    """Trend strength as the ADX value from :func:`dmi` (0 = none, 100 = max)."""
    _, _, adx = dmi(highs, lows, closes, period=period)
    return IndicatorResult(
        name="trend_strength",
        value=adx.value,
        method="wilder",
        window=period,
        observations=adx.observations,
    )


# --------------------------------------------------------------------------
# MACD (EMA-based)
# --------------------------------------------------------------------------


def macd(
    prices: Sequence[object],
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[IndicatorResult, IndicatorResult, IndicatorResult]:
    """Moving Average Convergence/Divergence: ``(macd_line, signal_line, hist)``.

    ``macd_line = EMA(fast) - EMA(slow)`` computed pointwise; ``signal_line`` is
    the EMA of the MACD line over ``signal``; ``histogram = macd_line - signal``.
    Each result reports the latest value. Requires ``fast < slow`` and at least
    ``slow`` observations.
    """
    _require_period(fast, what="fast")
    _require_period(slow, what="slow")
    _require_period(signal, what="signal")
    if fast >= slow:
        raise StrixError(f"macd requires fast < slow, got fast={fast} slow={slow}")
    vals = _coerce(prices, what="prices")
    if len(vals) < slow:
        raise StrixError(
            f"macd requires at least slow={slow} observations, got {len(vals)}"
        )
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        ema_fast = timeseries.ewma(vals, span=fast)
        ema_slow = timeseries.ewma(vals, span=slow)
        macd_series = [_q(f - s) for f, s in zip(ema_fast, ema_slow, strict=True)]
        signal_series = timeseries.ewma(macd_series, span=signal)
        macd_value = macd_series[-1]
        signal_value = signal_series[-1]
        hist_value = _q(macd_value - signal_value)
    obs = len(vals)
    macd_line = IndicatorResult(
        name="macd_line", value=macd_value, method="ema", window=slow, observations=obs
    )
    signal_line = IndicatorResult(
        name="signal_line", value=signal_value, method="ema", window=signal, observations=obs
    )
    histogram = IndicatorResult(
        name="macd_histogram", value=hist_value, method="ema", window=slow, observations=obs
    )
    return macd_line, signal_line, histogram


# --------------------------------------------------------------------------
# Returns / volatility / drawdown / relative volume / correlation
# --------------------------------------------------------------------------


def returns(prices: Sequence[object]) -> tuple[Decimal, ...]:
    """Simple per-step returns ``(p[i] - p[i-1]) / p[i-1]`` (length ``n - 1``).

    Requires at least 2 prices and non-zero denominators.
    """
    vals = _coerce(prices, what="prices")
    if len(vals) < 2:
        raise StrixError(f"returns requires at least 2 prices, got {len(vals)}")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        out: list[Decimal] = []
        for i in range(1, len(vals)):
            prev = vals[i - 1]
            if prev == 0:
                raise StrixError("returns undefined for a zero base price")
            out.append(_q((vals[i] - prev) / prev))
        return tuple(out)


def realized_volatility(
    prices: Sequence[object], *, periods_per_year: object = 252
) -> IndicatorResult:
    """Annualized realized volatility of simple returns.

    Computes per-step simple returns and scales their sample standard deviation
    by ``sqrt(periods_per_year)`` via
    :func:`strix.native.timeseries.annualized_volatility`. Requires at least 3
    prices (2 returns for a sample standard deviation).
    """
    rets = returns(prices)
    vol = timeseries.annualized_volatility(rets, periods_per_year)
    ppy = as_decimal(periods_per_year)
    return IndicatorResult(
        name="realized_volatility",
        value=vol,
        method="sample_annualized",
        window=int(ppy) if ppy == ppy.to_integral_value() else len(rets),
        observations=len(prices) if isinstance(prices, Sequence) else len(rets),
    )


def max_drawdown(prices: Sequence[object]) -> IndicatorResult:
    """Maximum peak-to-trough decline as a non-negative ratio in ``[0, 1]``.

    For a running peak ``m``, the drawdown at each point is ``(m - p) / m``; the
    result is the largest such drawdown over the series (``0`` if monotonic up).
    Requires at least 2 prices and a positive running peak.
    """
    vals = _coerce(prices, what="prices")
    if len(vals) < 2:
        raise StrixError(f"max_drawdown requires at least 2 prices, got {len(vals)}")
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        peak = vals[0]
        worst = Decimal(0)
        for price in vals:
            if price > peak:
                peak = price
            if peak <= 0:
                raise StrixError("max_drawdown undefined for a non-positive peak")
            drawdown = (peak - price) / peak
            if drawdown > worst:
                worst = drawdown
        value = _q(worst)
    return IndicatorResult(
        name="max_drawdown",
        value=value,
        method="ratio",
        window=len(vals),
        observations=len(vals),
    )


def relative_volume(volumes: Sequence[object], *, window: int) -> IndicatorResult:
    """Latest volume divided by the mean of the most recent ``window`` volumes.

    ``relative_volume = volumes[-1] / mean(volumes[-window:])``. A value of 1
    means the latest bar matches its recent baseline. Requires at least
    ``window`` observations and a non-zero baseline.
    """
    _require_period(window, what="window")
    vals = _coerce(volumes, what="volumes")
    if len(vals) < window:
        raise StrixError(
            f"relative_volume requires at least window={window} observations, "
            f"got {len(vals)}"
        )
    with localcontext() as ctx:
        ctx.prec = ARITH_PRECISION
        ctx.rounding = ROUND_HALF_EVEN
        baseline = sum(vals[-window:], Decimal(0)) / Decimal(window)
        if baseline == 0:
            raise StrixError("relative_volume undefined for a zero baseline volume")
        value = _q(vals[-1] / baseline)
    return IndicatorResult(
        name="relative_volume",
        value=value,
        method="ratio",
        window=window,
        observations=len(vals),
    )


def correlation(a: Sequence[object], b: Sequence[object]) -> IndicatorResult:
    """Pearson correlation of the two series' simple returns.

    Both series are converted to per-step simple returns and correlated via
    :func:`strix.native.multivariate.correlation`. Requires enough prices to
    yield at least 2 returns each (at least 3 prices), of equal length, and with
    non-constant returns.
    """
    ra = returns(a)
    rb = returns(b)
    if len(ra) != len(rb):
        raise StrixError(
            f"correlation requires equal-length series, got {len(ra) + 1}/{len(rb) + 1}"
        )
    if len(ra) < 2:
        raise StrixError("correlation requires at least 3 prices per series")
    value = _native_correlation(ra, rb)
    return IndicatorResult(
        name="correlation",
        value=value,
        method="pearson",
        window=len(ra),
        observations=len(ra) + 1,
    )
