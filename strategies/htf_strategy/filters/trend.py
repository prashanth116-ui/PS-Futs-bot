"""
Trend Filter Module

Filters to ensure trades align with the trend.
"""
from core.types import Bar


def calculate_ema(prices: list[float], period: int) -> list[float]:
    """Calculate Exponential Moving Average."""
    if len(prices) < period:
        return []

    multiplier = 2 / (period + 1)
    ema = [sum(prices[:period]) / period]

    for price in prices[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])

    return ema


def check_ema_trend(bars: list[Bar], fast_period: int = 20, slow_period: int = 50) -> str:
    """
    Check trend using EMA crossover.

    Args:
        bars: Price bars
        fast_period: Fast EMA period
        slow_period: Slow EMA period

    Returns:
        "BULLISH", "BEARISH", or "NEUTRAL"
    """
    if len(bars) < slow_period:
        return "NEUTRAL"

    closes = [b.close for b in bars]

    fast_ema = calculate_ema(closes, fast_period)
    slow_ema = calculate_ema(closes, slow_period)

    if not fast_ema or not slow_ema:
        return "NEUTRAL"

    # Align lengths
    min_len = min(len(fast_ema), len(slow_ema))
    fast_ema = fast_ema[-min_len:]
    slow_ema = slow_ema[-min_len:]

    if fast_ema[-1] > slow_ema[-1]:
        return "BULLISH"
    elif fast_ema[-1] < slow_ema[-1]:
        return "BEARISH"

    return "NEUTRAL"


def calculate_adx(bars: list[Bar], period: int = 14) -> tuple[float, float, float]:
    """
    Calculate ADX (Average Directional Index) with +DI/-DI using Wilder's smoothing.

    Args:
        bars: Price bars
        period: ADX period

    Returns:
        Tuple of (adx, plus_di, minus_di)
    """
    if len(bars) < period * 2 + 1:
        return 0.0, 0.0, 0.0

    plus_dm = []
    minus_dm = []
    tr = []

    for i in range(1, len(bars)):
        high_diff = bars[i].high - bars[i-1].high
        low_diff = bars[i-1].low - bars[i].low

        plus_dm.append(high_diff if high_diff > low_diff and high_diff > 0 else 0)
        minus_dm.append(low_diff if low_diff > high_diff and low_diff > 0 else 0)

        tr.append(max(
            bars[i].high - bars[i].low,
            abs(bars[i].high - bars[i-1].close),
            abs(bars[i].low - bars[i-1].close)
        ))

    # Wilder's smoothing method
    def wilder_smooth(values, period):
        if len(values) < period:
            return []
        smoothed = [sum(values[:period])]
        for v in values[period:]:
            smoothed.append(smoothed[-1] - smoothed[-1]/period + v)
        return smoothed

    smoothed_plus_dm = wilder_smooth(plus_dm, period)
    smoothed_minus_dm = wilder_smooth(minus_dm, period)
    smoothed_tr = wilder_smooth(tr, period)

    if not smoothed_tr or smoothed_tr[-1] == 0:
        return 0.0, 0.0, 0.0

    plus_di = 100 * smoothed_plus_dm[-1] / smoothed_tr[-1]
    minus_di = 100 * smoothed_minus_dm[-1] / smoothed_tr[-1]

    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 0.0, plus_di, minus_di

    # Calculate DX values for ADX smoothing
    dx_values = []
    for i in range(len(smoothed_plus_dm)):
        if smoothed_tr[i] == 0:
            dx_values.append(0)
            continue
        pdi = 100 * smoothed_plus_dm[i] / smoothed_tr[i]
        mdi = 100 * smoothed_minus_dm[i] / smoothed_tr[i]
        di_sum_i = pdi + mdi
        if di_sum_i == 0:
            dx_values.append(0)
        else:
            dx_values.append(100 * abs(pdi - mdi) / di_sum_i)

    # Smooth DX to get ADX
    if len(dx_values) < period:
        return dx_values[-1] if dx_values else 0.0, plus_di, minus_di

    adx_smoothed = wilder_smooth(dx_values, period)
    adx = adx_smoothed[-1] / period if adx_smoothed else 0.0

    return adx, plus_di, minus_di


def calculate_displacement(bar: Bar, avg_body_size: float, threshold: float = 1.0) -> bool:
    """
    Check if bar body exceeds threshold * average body (displacement).

    Args:
        bar: Current price bar
        avg_body_size: Average body size from recent bars
        threshold: Multiplier for average body (e.g., 1.0, 3.0)

    Returns:
        True if bar body >= threshold * avg_body_size
    """
    if avg_body_size <= 0:
        return False
    body = abs(bar.close - bar.open)
    return body >= avg_body_size * threshold


def calculate_avg_body_size(bars: list[Bar], lookback: int = 50) -> float:
    """
    Calculate average body size from recent bars.

    Args:
        bars: Price bars
        lookback: Number of bars to average

    Returns:
        Average body size
    """
    if not bars:
        return 0.0
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    bodies = [abs(b.close - b.open) for b in recent]
    return sum(bodies) / len(bodies) if bodies else 0.0


def check_adx_trend(bars: list[Bar], min_adx: float = 17, period: int = 14) -> tuple[bool, str]:
    """
    Check if market is trending using ADX.

    Args:
        bars: Price bars
        min_adx: Minimum ADX value for trending market
        period: ADX period

    Returns:
        Tuple of (is_trending, direction)
        direction: "BULLISH" if +DI > -DI, "BEARISH" if -DI > +DI
    """
    adx, plus_di, minus_di = calculate_adx(bars, period)

    is_trending = adx >= min_adx

    if plus_di > minus_di:
        direction = "BULLISH"
    elif minus_di > plus_di:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    return is_trending, direction
