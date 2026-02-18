"""
Impulse Leg Detection Module

An impulse leg is a strong directional move (displacement) that creates a
swing high/low. It represents institutional order flow and is the starting
point for an OTE (Optimal Trade Entry) setup.

Bullish impulse: Strong move up creating a swing low -> swing high
Bearish impulse: Strong move down creating a swing high -> swing low
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ImpulseLeg:
    """Represents a strong directional impulse move."""
    direction: str  # 'BULLISH' or 'BEARISH'
    start_price: float  # Swing low (bullish) or swing high (bearish)
    end_price: float  # Swing high (bullish) or swing low (bearish)
    start_index: int  # Bar index of impulse start
    end_index: int  # Bar index of impulse end
    start_timestamp: datetime
    end_timestamp: datetime
    size_ticks: float  # Size of impulse in ticks
    displacement_ratio: float  # Max body / avg body ratio during impulse


def _find_swing_high(bars, index: int, lookback: int = 3) -> bool:
    """Check if bar at index is a swing high."""
    if index < lookback or index >= len(bars) - lookback:
        return False
    bar_high = bars[index].high
    for i in range(1, lookback + 1):
        if bars[index - i].high >= bar_high or bars[index + i].high >= bar_high:
            return False
    return True


def _find_swing_low(bars, index: int, lookback: int = 3) -> bool:
    """Check if bar at index is a swing low."""
    if index < lookback or index >= len(bars) - lookback:
        return False
    bar_low = bars[index].low
    for i in range(1, lookback + 1):
        if bars[index - i].low <= bar_low or bars[index + i].low <= bar_low:
            return False
    return True


def detect_impulse(
    bars,
    tick_size: float = 0.25,
    avg_body: float = 0.0,
    min_body_multiplier: float = 2.0,
    swing_lookback: int = 3,
    min_leg_ticks: int = 10,
    max_bars_back: int = 30,
) -> Optional[ImpulseLeg]:
    """
    Detect the most recent impulse leg in the bar data.

    An impulse leg is identified by:
    1. A displacement candle (body >= min_body_multiplier * avg_body)
    2. A clear directional move from swing point to swing point
    3. Minimum size in ticks

    Scans backwards from recent bars to find the most recent impulse.

    Args:
        bars: List of price bars
        tick_size: Instrument tick size
        avg_body: Average candle body size
        min_body_multiplier: Min body/avg ratio for displacement
        swing_lookback: Bars on each side for swing confirmation
        min_leg_ticks: Minimum impulse size in ticks
        max_bars_back: How far back to search

    Returns:
        ImpulseLeg if found, None otherwise
    """
    if len(bars) < swing_lookback * 2 + 5:
        return None

    if avg_body <= 0:
        return None

    end_idx = len(bars) - 1
    start_search = max(swing_lookback, end_idx - max_bars_back)

    # Find recent displacement candle (strong move)
    displacement_idx = None
    displacement_dir = None
    best_ratio = 0.0

    for i in range(end_idx, start_search, -1):
        bar = bars[i]
        body = abs(bar.close - bar.open)
        ratio = body / avg_body if avg_body > 0 else 0

        if ratio >= min_body_multiplier:
            is_bullish = bar.close > bar.open
            displacement_idx = i
            displacement_dir = 'BULLISH' if is_bullish else 'BEARISH'
            best_ratio = ratio
            break

    if displacement_idx is None:
        return None

    # Find the impulse leg around the displacement
    if displacement_dir == 'BULLISH':
        # Bullish impulse: find swing low before displacement, swing high after
        # Find lowest low in bars leading up to displacement
        search_start = max(0, displacement_idx - max_bars_back)
        swing_low_idx = displacement_idx
        swing_low_price = bars[displacement_idx].low

        for i in range(displacement_idx, search_start, -1):
            if bars[i].low < swing_low_price:
                swing_low_price = bars[i].low
                swing_low_idx = i
            # Stop if we find a swing low (confirmed)
            if _find_swing_low(bars, i, min(swing_lookback, i)):
                swing_low_price = bars[i].low
                swing_low_idx = i
                break

        # Find highest high from displacement onward
        swing_high_idx = displacement_idx
        swing_high_price = bars[displacement_idx].high

        for i in range(displacement_idx, min(end_idx + 1, displacement_idx + max_bars_back)):
            if bars[i].high > swing_high_price:
                swing_high_price = bars[i].high
                swing_high_idx = i

        leg_size = swing_high_price - swing_low_price
        leg_ticks = leg_size / tick_size

        if leg_ticks < min_leg_ticks:
            return None

        return ImpulseLeg(
            direction='BULLISH',
            start_price=swing_low_price,
            end_price=swing_high_price,
            start_index=swing_low_idx,
            end_index=swing_high_idx,
            start_timestamp=bars[swing_low_idx].timestamp,
            end_timestamp=bars[swing_high_idx].timestamp,
            size_ticks=leg_ticks,
            displacement_ratio=best_ratio,
        )

    else:  # BEARISH
        # Bearish impulse: find swing high before displacement, swing low after
        search_start = max(0, displacement_idx - max_bars_back)
        swing_high_idx = displacement_idx
        swing_high_price = bars[displacement_idx].high

        for i in range(displacement_idx, search_start, -1):
            if bars[i].high > swing_high_price:
                swing_high_price = bars[i].high
                swing_high_idx = i
            if _find_swing_high(bars, i, min(swing_lookback, i)):
                swing_high_price = bars[i].high
                swing_high_idx = i
                break

        swing_low_idx = displacement_idx
        swing_low_price = bars[displacement_idx].low

        for i in range(displacement_idx, min(end_idx + 1, displacement_idx + max_bars_back)):
            if bars[i].low < swing_low_price:
                swing_low_price = bars[i].low
                swing_low_idx = i

        leg_size = swing_high_price - swing_low_price
        leg_ticks = leg_size / tick_size

        if leg_ticks < min_leg_ticks:
            return None

        return ImpulseLeg(
            direction='BEARISH',
            start_price=swing_high_price,
            end_price=swing_low_price,
            start_index=swing_high_idx,
            end_index=swing_low_idx,
            start_timestamp=bars[swing_high_idx].timestamp,
            end_timestamp=bars[swing_low_idx].timestamp,
            size_ticks=leg_ticks,
            displacement_ratio=best_ratio,
        )


def detect_all_impulses(
    bars,
    tick_size: float = 0.25,
    avg_body: float = 0.0,
    min_body_multiplier: float = 2.0,
    swing_lookback: int = 3,
    min_leg_ticks: int = 10,
    max_bars_back: int = 50,
) -> list[ImpulseLeg]:
    """
    Detect all impulse legs in the bar data.

    Scans the entire range and returns all valid impulse legs.

    Args:
        bars: List of price bars
        tick_size: Instrument tick size
        avg_body: Average candle body size
        min_body_multiplier: Min body/avg ratio for displacement
        swing_lookback: Bars on each side for swing confirmation
        min_leg_ticks: Minimum impulse size in ticks
        max_bars_back: Window size for each scan

    Returns:
        List of ImpulseLeg objects (most recent last)
    """
    impulses = []
    if len(bars) < swing_lookback * 2 + 5 or avg_body <= 0:
        return impulses

    # Scan through bars looking for displacement candles
    used_indices = set()

    for i in range(swing_lookback + 2, len(bars) - swing_lookback):
        bar = bars[i]
        body = abs(bar.close - bar.open)
        ratio = body / avg_body

        if ratio < min_body_multiplier:
            continue

        if i in used_indices:
            continue

        is_bullish = bar.close > bar.open
        direction = 'BULLISH' if is_bullish else 'BEARISH'

        if direction == 'BULLISH':
            # Find swing low before, swing high after
            search_start = max(0, i - max_bars_back)
            swing_low_idx = i
            swing_low_price = bars[i].low

            for j in range(i, search_start, -1):
                if bars[j].low < swing_low_price:
                    swing_low_price = bars[j].low
                    swing_low_idx = j
                if _find_swing_low(bars, j, min(swing_lookback, j)):
                    swing_low_price = bars[j].low
                    swing_low_idx = j
                    break

            swing_high_idx = i
            swing_high_price = bars[i].high

            search_end = min(len(bars) - swing_lookback, i + max_bars_back)
            for j in range(i, search_end):
                if bars[j].high > swing_high_price:
                    swing_high_price = bars[j].high
                    swing_high_idx = j

            leg_ticks = (swing_high_price - swing_low_price) / tick_size
            if leg_ticks >= min_leg_ticks:
                impulses.append(ImpulseLeg(
                    direction='BULLISH',
                    start_price=swing_low_price,
                    end_price=swing_high_price,
                    start_index=swing_low_idx,
                    end_index=swing_high_idx,
                    start_timestamp=bars[swing_low_idx].timestamp,
                    end_timestamp=bars[swing_high_idx].timestamp,
                    size_ticks=leg_ticks,
                    displacement_ratio=ratio,
                ))
                for k in range(swing_low_idx, swing_high_idx + 1):
                    used_indices.add(k)

        else:  # BEARISH
            search_start = max(0, i - max_bars_back)
            swing_high_idx = i
            swing_high_price = bars[i].high

            for j in range(i, search_start, -1):
                if bars[j].high > swing_high_price:
                    swing_high_price = bars[j].high
                    swing_high_idx = j
                if _find_swing_high(bars, j, min(swing_lookback, j)):
                    swing_high_price = bars[j].high
                    swing_high_idx = j
                    break

            swing_low_idx = i
            swing_low_price = bars[i].low

            search_end = min(len(bars) - swing_lookback, i + max_bars_back)
            for j in range(i, search_end):
                if bars[j].low < swing_low_price:
                    swing_low_price = bars[j].low
                    swing_low_idx = j

            leg_ticks = (swing_high_price - swing_low_price) / tick_size
            if leg_ticks >= min_leg_ticks:
                impulses.append(ImpulseLeg(
                    direction='BEARISH',
                    start_price=swing_high_price,
                    end_price=swing_low_price,
                    start_index=swing_high_idx,
                    end_index=swing_low_idx,
                    start_timestamp=bars[swing_high_idx].timestamp,
                    end_timestamp=bars[swing_low_idx].timestamp,
                    size_ticks=leg_ticks,
                    displacement_ratio=ratio,
                ))
                for k in range(swing_high_idx, swing_low_idx + 1):
                    used_indices.add(k)

    return impulses
