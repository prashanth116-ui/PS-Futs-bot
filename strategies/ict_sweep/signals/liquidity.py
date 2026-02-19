"""
Liquidity Detection Module

Identifies swing highs and swing lows that act as liquidity pools.
Liquidity pools are areas where stop losses cluster (above swing highs, below swing lows).
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SwingPoint:
    """Represents a swing high or swing low."""
    price: float
    bar_index: int
    timestamp: datetime
    swing_type: str  # 'HIGH' or 'LOW'
    strength: int  # Number of bars on each side that confirm the swing


def is_swing_high(bars, index: int, lookback: int = 3) -> bool:
    """
    Check if bar at index is a swing high.

    A swing high has lower highs on both sides for 'lookback' bars.

    Args:
        bars: List of price bars
        index: Bar index to check
        lookback: Number of bars on each side to confirm swing

    Returns:
        True if bar is a swing high
    """
    if index < lookback or index >= len(bars) - lookback:
        return False

    bar_high = bars[index].high

    # Check left side (bars before)
    for i in range(1, lookback + 1):
        if bars[index - i].high >= bar_high:
            return False

    # Check right side (bars after)
    for i in range(1, lookback + 1):
        if bars[index + i].high >= bar_high:
            return False

    return True


def is_swing_low(bars, index: int, lookback: int = 3) -> bool:
    """
    Check if bar at index is a swing low.

    A swing low has higher lows on both sides for 'lookback' bars.

    Args:
        bars: List of price bars
        index: Bar index to check
        lookback: Number of bars on each side to confirm swing

    Returns:
        True if bar is a swing low
    """
    if index < lookback or index >= len(bars) - lookback:
        return False

    bar_low = bars[index].low

    # Check left side (bars before)
    for i in range(1, lookback + 1):
        if bars[index - i].low <= bar_low:
            return False

    # Check right side (bars after)
    for i in range(1, lookback + 1):
        if bars[index + i].low <= bar_low:
            return False

    return True


def find_swing_highs(bars, lookback: int = 3, max_swings: int = 10) -> list[SwingPoint]:
    """
    Find all swing highs in the bar data.

    Args:
        bars: List of price bars
        lookback: Number of bars on each side to confirm swing
        max_swings: Maximum number of recent swings to return

    Returns:
        List of SwingPoint objects (most recent first)
    """
    swings = []

    # Start from lookback, end before lookback from end
    for i in range(lookback, len(bars) - lookback):
        if is_swing_high(bars, i, lookback):
            swings.append(SwingPoint(
                price=bars[i].high,
                bar_index=i,
                timestamp=bars[i].timestamp,
                swing_type='HIGH',
                strength=lookback
            ))

    # Return most recent swings first, limited to max_swings
    return swings[-max_swings:][::-1]


def find_swing_lows(bars, lookback: int = 3, max_swings: int = 10) -> list[SwingPoint]:
    """
    Find all swing lows in the bar data.

    Args:
        bars: List of price bars
        lookback: Number of bars on each side to confirm swing
        max_swings: Maximum number of recent swings to return

    Returns:
        List of SwingPoint objects (most recent first)
    """
    swings = []

    for i in range(lookback, len(bars) - lookback):
        if is_swing_low(bars, i, lookback):
            swings.append(SwingPoint(
                price=bars[i].low,
                bar_index=i,
                timestamp=bars[i].timestamp,
                swing_type='LOW',
                strength=lookback
            ))

    return swings[-max_swings:][::-1]


def find_liquidity_levels(bars, lookback: int = 3, max_levels: int = 5) -> dict:
    """
    Find liquidity levels (swing highs and lows) that represent stop clusters.

    Args:
        bars: List of price bars
        lookback: Swing detection lookback
        max_levels: Maximum levels to track on each side

    Returns:
        Dict with 'highs' and 'lows' lists of SwingPoint objects
    """
    highs = find_swing_highs(bars, lookback, max_levels)
    lows = find_swing_lows(bars, lookback, max_levels)

    return {
        'highs': highs,  # Liquidity above (buy stops)
        'lows': lows,    # Liquidity below (sell stops)
    }


def find_nearest_liquidity(bars, current_price: float, lookback: int = 3) -> dict:
    """
    Find the nearest liquidity level above and below current price.

    Args:
        bars: List of price bars
        current_price: Current market price
        lookback: Swing detection lookback

    Returns:
        Dict with 'above' and 'below' SwingPoint objects (or None)
    """
    levels = find_liquidity_levels(bars, lookback)

    # Find nearest high above current price
    above = None
    for swing in levels['highs']:
        if swing.price > current_price:
            if above is None or swing.price < above.price:
                above = swing

    # Find nearest low below current price
    below = None
    for swing in levels['lows']:
        if swing.price < current_price:
            if below is None or swing.price > below.price:
                below = swing

    return {
        'above': above,  # Nearest liquidity above (for short setup after sweep)
        'below': below,  # Nearest liquidity below (for long setup after sweep)
    }
