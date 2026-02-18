"""
Premium/Discount Zone Filter

Determines whether price is in the premium (upper half) or discount (lower half)
of the current dealing range. Longs should only be taken in discount zones,
shorts should only be taken in premium zones.

Methods:
- 'session': Uses the current session (day) high/low as the dealing range
- 'swing': Uses HTF swing highs/lows for a broader range
"""
from dataclasses import dataclass
from typing import Optional

from strategies.ict_sweep.signals.liquidity import find_swing_highs, find_swing_lows


@dataclass
class DealingRangeZone:
    """Current dealing range and price position within it."""
    range_high: float
    range_low: float
    equilibrium: float        # 50% level
    zone: str                 # 'PREMIUM' or 'DISCOUNT'
    price_position_pct: float  # 0.0=low, 1.0=high


def calculate_dealing_range(bars, method: str = 'session') -> Optional[DealingRangeZone]:
    """
    Calculate the dealing range and determine premium/discount zone.

    Args:
        bars: List of price bars
        method: 'session' (day H/L) or 'swing' (HTF swings)

    Returns:
        DealingRangeZone or None if insufficient data
    """
    if len(bars) < 10:
        return None

    current_price = bars[-1].close

    if method == 'swing':
        highs = find_swing_highs(bars, lookback=3, max_swings=3)
        lows = find_swing_lows(bars, lookback=3, max_swings=3)

        if not highs or not lows:
            return None

        range_high = max(s.price for s in highs)
        range_low = min(s.price for s in lows)
    else:
        # Session method: use all bars as the range
        range_high = max(b.high for b in bars)
        range_low = min(b.low for b in bars)

    if range_high <= range_low:
        return None

    equilibrium = (range_high + range_low) / 2.0
    position_pct = (current_price - range_low) / (range_high - range_low)
    position_pct = max(0.0, min(1.0, position_pct))

    zone = 'PREMIUM' if current_price > equilibrium else 'DISCOUNT'

    return DealingRangeZone(
        range_high=range_high,
        range_low=range_low,
        equilibrium=equilibrium,
        zone=zone,
        price_position_pct=position_pct,
    )


def check_premium_discount_filter(zone: Optional[DealingRangeZone], direction: str) -> bool:
    """
    Check if trade direction is valid for the current zone.

    BULLISH trades only in DISCOUNT zone, BEARISH trades only in PREMIUM zone.

    Args:
        zone: Current DealingRangeZone (None = pass filter)
        direction: 'BULLISH' or 'BEARISH'

    Returns:
        True if trade is allowed
    """
    if zone is None:
        return True

    if direction == 'BULLISH':
        return zone.zone == 'DISCOUNT'
    else:
        return zone.zone == 'PREMIUM'
