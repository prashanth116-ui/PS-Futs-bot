"""
Liquidity Sweep Detection Module

Detects when price sweeps (takes out) a liquidity level and rejects.
A sweep is a stop hunt - price briefly breaks a swing high/low to trigger stops,
then reverses.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from strategies.ict_sweep.signals.liquidity import SwingPoint, find_swing_highs, find_swing_lows


@dataclass
class Sweep:
    """Represents a liquidity sweep event."""
    sweep_type: str  # 'BULLISH' (swept low, expecting up) or 'BEARISH' (swept high, expecting down)
    sweep_price: float  # The extreme price of the sweep (wick tip)
    liquidity_level: float  # The swing high/low that was swept
    bar_index: int
    timestamp: datetime
    sweep_depth_ticks: float  # How far price went beyond the level


def detect_sweep(
    bars,
    tick_size: float = 0.25,
    swing_lookback: int = 3,
    min_sweep_ticks: int = 2,
    check_bars: int = 3
) -> Optional[Sweep]:
    """
    Detect if a liquidity sweep occurred in the recent bars.

    A bullish sweep: Price wicks below a swing low and rejects (closes above).
    A bearish sweep: Price wicks above a swing high and rejects (closes below).

    Args:
        bars: List of price bars
        tick_size: Instrument tick size
        swing_lookback: Bars on each side to confirm swing
        min_sweep_ticks: Minimum ticks price must go beyond level
        check_bars: Number of recent bars to check for sweep

    Returns:
        Sweep object if detected, None otherwise
    """
    if len(bars) < swing_lookback * 2 + check_bars:
        return None

    # Find swing highs and lows (excluding the most recent bars we're checking)
    analysis_bars = bars[:-check_bars] if check_bars > 0 else bars
    swing_highs = find_swing_highs(analysis_bars, swing_lookback, max_swings=5)
    swing_lows = find_swing_lows(analysis_bars, swing_lookback, max_swings=5)

    # Check recent bars for sweep
    recent_bars = bars[-check_bars:] if check_bars > 0 else [bars[-1]]

    for i, bar in enumerate(recent_bars):
        bar_index = len(bars) - check_bars + i

        # Check for BULLISH sweep (swept low, expecting price to go up)
        for swing in swing_lows:
            # Skip if swing is too recent (within check_bars)
            if swing.bar_index >= len(bars) - check_bars:
                continue

            # Check if wick went below swing low
            sweep_depth = swing.price - bar.low
            if sweep_depth >= min_sweep_ticks * tick_size:
                # Check if price rejected (closed above the swing low)
                if bar.close > swing.price:
                    return Sweep(
                        sweep_type='BULLISH',
                        sweep_price=bar.low,
                        liquidity_level=swing.price,
                        bar_index=bar_index,
                        timestamp=bar.timestamp,
                        sweep_depth_ticks=sweep_depth / tick_size
                    )

        # Check for BEARISH sweep (swept high, expecting price to go down)
        for swing in swing_highs:
            # Skip if swing is too recent
            if swing.bar_index >= len(bars) - check_bars:
                continue

            # Check if wick went above swing high
            sweep_depth = bar.high - swing.price
            if sweep_depth >= min_sweep_ticks * tick_size:
                # Check if price rejected (closed below the swing high)
                if bar.close < swing.price:
                    return Sweep(
                        sweep_type='BEARISH',
                        sweep_price=bar.high,
                        liquidity_level=swing.price,
                        bar_index=bar_index,
                        timestamp=bar.timestamp,
                        sweep_depth_ticks=sweep_depth / tick_size
                    )

    return None


def detect_sweep_at_level(
    bars,
    level: float,
    level_type: str,  # 'HIGH' or 'LOW'
    tick_size: float = 0.25,
    min_sweep_ticks: int = 2
) -> Optional[Sweep]:
    """
    Check if the most recent bar swept a specific level.

    Args:
        bars: List of price bars
        level: The price level to check
        level_type: 'HIGH' for resistance, 'LOW' for support
        tick_size: Instrument tick size
        min_sweep_ticks: Minimum ticks beyond level

    Returns:
        Sweep object if detected, None otherwise
    """
    if not bars:
        return None

    bar = bars[-1]
    bar_index = len(bars) - 1

    if level_type == 'LOW':
        # Check for bullish sweep (swept low)
        sweep_depth = level - bar.low
        if sweep_depth >= min_sweep_ticks * tick_size and bar.close > level:
            return Sweep(
                sweep_type='BULLISH',
                sweep_price=bar.low,
                liquidity_level=level,
                bar_index=bar_index,
                timestamp=bar.timestamp,
                sweep_depth_ticks=sweep_depth / tick_size
            )

    elif level_type == 'HIGH':
        # Check for bearish sweep (swept high)
        sweep_depth = bar.high - level
        if sweep_depth >= min_sweep_ticks * tick_size and bar.close < level:
            return Sweep(
                sweep_type='BEARISH',
                sweep_price=bar.high,
                liquidity_level=level,
                bar_index=bar_index,
                timestamp=bar.timestamp,
                sweep_depth_ticks=sweep_depth / tick_size
            )

    return None


def is_valid_sweep(sweep: Sweep, min_depth_ticks: int = 2, max_depth_ticks: int = 20) -> bool:
    """
    Validate a sweep meets quality criteria.

    Args:
        sweep: Sweep object to validate
        min_depth_ticks: Minimum sweep depth
        max_depth_ticks: Maximum sweep depth (too deep might not be a sweep)

    Returns:
        True if sweep is valid
    """
    if sweep is None:
        return False

    return min_depth_ticks <= sweep.sweep_depth_ticks <= max_depth_ticks
