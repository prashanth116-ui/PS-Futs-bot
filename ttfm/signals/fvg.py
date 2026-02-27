"""
FVG (Fair Value Gap) detection for TTFM POIs.

Simplified from the ICT FVG module — detects zones as Points of Interest
for the multi-timeframe alignment check. No mitigation tracking needed
for entry decisions (CISD handles confirmation).
"""

from ttfm.core import Bar
from ttfm.types import POI, SwingPoint


def detect_fvgs(
    bars: list[Bar],
    min_gap_ticks: int = 5,
    tick_size: float = 0.25,
) -> list[POI]:
    """Detect Fair Value Gaps in a bar series and return as POIs.

    Bullish FVG: bar[i-2].high < bar[i].low (gap up)
    Bearish FVG: bar[i-2].low > bar[i].high (gap down)

    Args:
        bars: Chronologically ordered bars (need at least 3).
        min_gap_ticks: Minimum gap size in ticks.
        tick_size: Tick size for the instrument.

    Returns:
        List of POI objects representing FVG zones.
    """
    pois: list[POI] = []
    min_gap = min_gap_ticks * tick_size

    for i in range(2, len(bars)):
        # Bullish FVG
        gap = bars[i].low - bars[i - 2].high
        if gap >= min_gap:
            pois.append(POI(
                poi_type="FVG",
                high=bars[i].low,
                low=bars[i - 2].high,
                direction="BULLISH",
                bar_index=i,
                timestamp=bars[i].timestamp,
            ))

        # Bearish FVG
        gap = bars[i - 2].low - bars[i].high
        if gap >= min_gap:
            pois.append(POI(
                poi_type="FVG",
                high=bars[i - 2].low,
                low=bars[i].high,
                direction="BEARISH",
                bar_index=i,
                timestamp=bars[i].timestamp,
            ))

    return pois


def swings_as_pois(swings: list, bars: list[Bar]) -> list[POI]:
    """Convert swing points to POIs (swing highs/lows as zones).

    A swing high is a bearish POI (expect price to reject there).
    A swing low is a bullish POI.
    """
    pois: list[POI] = []
    for s in swings:
        if not isinstance(s, SwingPoint):
            continue
        if s.bar_index >= len(bars):
            continue
        bar = bars[s.bar_index]
        if s.swing_type == "HIGH":
            pois.append(POI(
                poi_type="SWING",
                high=bar.high,
                low=max(bar.open, bar.close),
                direction="BEARISH",
                bar_index=s.bar_index,
                timestamp=s.timestamp,
            ))
        else:
            pois.append(POI(
                poi_type="SWING",
                high=min(bar.open, bar.close),
                low=bar.low,
                direction="BULLISH",
                bar_index=s.bar_index,
                timestamp=s.timestamp,
            ))

    return pois
