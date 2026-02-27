"""
HTF (daily) bias determination for TTFM.

Analyzes daily candle closures to determine directional bias:
- Continuation: close beyond previous day's high/low
- Reversal: sweep previous day's extreme then close back inside
"""

from ttfm.core import Bar
from ttfm.types import Bias


def determine_bias(daily_bars: list[Bar]) -> Bias:
    """Determine HTF bias from the last two daily candles.

    Rules:
        Bullish continuation: Close above previous day's high
        Bearish continuation: Close below previous day's low
        Bullish reversal: Sweep prev low (wick below) then close above prev low
        Bearish reversal: Sweep prev high (wick above) then close below prev high

    Args:
        daily_bars: Daily bars sorted chronologically (need at least 2).

    Returns:
        Bias with direction, type, and reason.
    """
    if len(daily_bars) < 2:
        return Bias(direction="NEUTRAL", bias_type="CONTINUATION", reason="Insufficient daily data")

    prev = daily_bars[-2]
    curr = daily_bars[-1]

    # Continuation checks (stronger signal)
    if curr.close > prev.high:
        return Bias(
            direction="BULLISH",
            bias_type="CONTINUATION",
            reason=f"Close {curr.close:.2f} > prev high {prev.high:.2f}",
        )
    if curr.close < prev.low:
        return Bias(
            direction="BEARISH",
            bias_type="CONTINUATION",
            reason=f"Close {curr.close:.2f} < prev low {prev.low:.2f}",
        )

    # Reversal checks (sweep + close back inside)
    if curr.low < prev.low and curr.close > prev.low:
        return Bias(
            direction="BULLISH",
            bias_type="REVERSAL",
            reason=f"Swept prev low {prev.low:.2f} (wick {curr.low:.2f}), closed back above",
        )
    if curr.high > prev.high and curr.close < prev.high:
        return Bias(
            direction="BEARISH",
            bias_type="REVERSAL",
            reason=f"Swept prev high {prev.high:.2f} (wick {curr.high:.2f}), closed back below",
        )

    # Neutral — inside day or no clear signal
    if curr.close >= prev.close:
        return Bias(
            direction="BULLISH",
            bias_type="CONTINUATION",
            reason=f"Inside day, leaning bullish (close {curr.close:.2f} >= prev close {prev.close:.2f})",
        )
    return Bias(
        direction="BEARISH",
        bias_type="CONTINUATION",
        reason=f"Inside day, leaning bearish (close {curr.close:.2f} < prev close {prev.close:.2f})",
    )
