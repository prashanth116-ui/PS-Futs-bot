"""
Fractal swing point detection for TTFM.

A swing high has a higher high than `left` bars to its left AND `right` bars
to its right. A swing low has a lower low. This is the C2 identification step.
"""

from ttfm.core import Bar
from ttfm.types import SwingPoint


def find_swings(
    bars: list[Bar],
    left: int = 2,
    right: int = 2,
    timeframe: str = "",
) -> list[SwingPoint]:
    """Find all fractal swing highs and lows in a bar series.

    Args:
        bars: Chronologically ordered bars.
        left: Number of bars to the left that must confirm.
        right: Number of bars to the right that must confirm.
        timeframe: Label for the timeframe (e.g. "15m", "1h").

    Returns:
        Combined list of swing highs and lows, sorted by bar_index.
    """
    swings: list[SwingPoint] = []
    n = len(bars)
    if n < left + 1 + right:
        return swings

    for i in range(left, n - right):
        # Check swing high
        is_high = True
        for j in range(i - left, i):
            if bars[j].high >= bars[i].high:
                is_high = False
                break
        if is_high:
            for j in range(i + 1, i + right + 1):
                if bars[j].high >= bars[i].high:
                    is_high = False
                    break
        if is_high:
            swings.append(SwingPoint(
                price=bars[i].high,
                timestamp=bars[i].timestamp,
                bar_index=i,
                swing_type="HIGH",
                timeframe=timeframe,
            ))

        # Check swing low
        is_low = True
        for j in range(i - left, i):
            if bars[j].low <= bars[i].low:
                is_low = False
                break
        if is_low:
            for j in range(i + 1, i + right + 1):
                if bars[j].low <= bars[i].low:
                    is_low = False
                    break
        if is_low:
            swings.append(SwingPoint(
                price=bars[i].low,
                timestamp=bars[i].timestamp,
                bar_index=i,
                swing_type="LOW",
                timeframe=timeframe,
            ))

    swings.sort(key=lambda s: s.bar_index)
    return swings
