"""
Displacement Filter Module

Displacement refers to strong, impulsive price movement - characterized by
large candle bodies relative to average. This indicates institutional
order flow and increases probability of valid setups.
"""
from typing import Optional


def calculate_avg_body(bars, lookback: int = 20) -> float:
    """
    Calculate the average candle body size over recent bars.

    Args:
        bars: List of price bars
        lookback: Number of bars to average

    Returns:
        Average body size
    """
    if not bars:
        return 0.0

    recent = bars[-lookback:] if len(bars) >= lookback else bars
    bodies = [abs(b.close - b.open) for b in recent]

    return sum(bodies) / len(bodies) if bodies else 0.0


def get_body_size(bar) -> float:
    """Get the body size of a single bar."""
    return abs(bar.close - bar.open)


def check_displacement(
    bar,
    avg_body: float,
    min_multiplier: float = 2.0
) -> bool:
    """
    Check if a bar shows displacement (strong move).

    Args:
        bar: Price bar to check
        avg_body: Average body size for comparison
        min_multiplier: Minimum multiplier of average body (e.g., 2.0 = 2x avg)

    Returns:
        True if bar shows displacement
    """
    if avg_body <= 0:
        return False

    body = get_body_size(bar)
    return body >= avg_body * min_multiplier


def get_displacement_ratio(bar, avg_body: float) -> float:
    """
    Get the displacement ratio (body / avg_body).

    Args:
        bar: Price bar
        avg_body: Average body size

    Returns:
        Displacement ratio (e.g., 2.5 means 2.5x average)
    """
    if avg_body <= 0:
        return 0.0

    return get_body_size(bar) / avg_body


def is_bullish_displacement(bar, avg_body: float, min_multiplier: float = 2.0) -> bool:
    """
    Check for bullish displacement (large green candle).

    Args:
        bar: Price bar to check
        avg_body: Average body size
        min_multiplier: Minimum body multiplier

    Returns:
        True if bullish displacement
    """
    if bar.close <= bar.open:
        return False

    return check_displacement(bar, avg_body, min_multiplier)


def is_bearish_displacement(bar, avg_body: float, min_multiplier: float = 2.0) -> bool:
    """
    Check for bearish displacement (large red candle).

    Args:
        bar: Price bar to check
        avg_body: Average body size
        min_multiplier: Minimum body multiplier

    Returns:
        True if bearish displacement
    """
    if bar.close >= bar.open:
        return False

    return check_displacement(bar, avg_body, min_multiplier)


def find_displacement_bar(
    bars,
    direction: str,
    avg_body: float,
    min_multiplier: float = 2.0,
    max_bars_back: int = 3
) -> Optional[int]:
    """
    Find a displacement bar within recent bars.

    Args:
        bars: List of price bars
        direction: 'BULLISH' or 'BEARISH'
        avg_body: Average body size
        min_multiplier: Minimum multiplier
        max_bars_back: How many bars back to search

    Returns:
        Bar index if found, None otherwise
    """
    if not bars:
        return None

    search_range = min(max_bars_back, len(bars))

    for i in range(1, search_range + 1):
        bar = bars[-i]
        bar_index = len(bars) - i

        if direction == 'BULLISH' and is_bullish_displacement(bar, avg_body, min_multiplier):
            return bar_index
        elif direction == 'BEARISH' and is_bearish_displacement(bar, avg_body, min_multiplier):
            return bar_index

    return None
