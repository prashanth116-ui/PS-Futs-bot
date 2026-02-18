"""
Fibonacci OTE Zone Calculation Module

The Optimal Trade Entry (OTE) zone is the 62-79% Fibonacci retracement
of an impulse leg. This zone represents the highest probability area
for price to reverse and continue in the impulse direction.

Key levels:
- 61.8% (0.618) - Golden ratio, start of OTE zone
- 70.5% (0.705) - Midpoint of OTE zone (optimal entry)
- 78.6% (0.786) - Deep retracement, end of OTE zone
"""
from dataclasses import dataclass
from typing import Optional

from strategies.ict_ote.signals.impulse import ImpulseLeg


@dataclass
class OTEZone:
    """Represents a Fibonacci OTE (62-79%) retracement zone."""
    direction: str  # 'BULLISH' or 'BEARISH' (same as impulse)
    top: float  # Upper boundary (62% for bullish, 79% for bearish)
    bottom: float  # Lower boundary (79% for bullish, 62% for bearish)
    midpoint: float  # 70.5% level (optimal entry)
    fib_62: float  # 61.8% retracement level
    fib_705: float  # 70.5% retracement level
    fib_79: float  # 78.6% retracement level
    impulse: ImpulseLeg  # Reference to the source impulse leg
    tapped: bool = False  # Has price entered the zone?
    tap_bar_index: Optional[int] = None


def calculate_ote_zone(impulse: ImpulseLeg) -> OTEZone:
    """
    Calculate the OTE zone from an impulse leg.

    For a bullish impulse (low -> high):
    - 62% retracement = high - 0.618 * (high - low) [top of zone]
    - 70.5% retracement = high - 0.705 * (high - low) [midpoint]
    - 79% retracement = high - 0.786 * (high - low) [bottom of zone]

    For a bearish impulse (high -> low):
    - 62% retracement = low + 0.618 * (high - low) [bottom of zone]
    - 70.5% retracement = low + 0.705 * (high - low) [midpoint]
    - 79% retracement = low + 0.786 * (high - low) [top of zone]

    Args:
        impulse: ImpulseLeg to calculate retracement from

    Returns:
        OTEZone with calculated levels
    """
    if impulse.direction == 'BULLISH':
        high = impulse.end_price
        low = impulse.start_price
        leg_size = high - low

        fib_62 = high - 0.618 * leg_size
        fib_705 = high - 0.705 * leg_size
        fib_79 = high - 0.786 * leg_size

        return OTEZone(
            direction='BULLISH',
            top=fib_62,
            bottom=fib_79,
            midpoint=fib_705,
            fib_62=fib_62,
            fib_705=fib_705,
            fib_79=fib_79,
            impulse=impulse,
        )
    else:  # BEARISH
        high = impulse.start_price
        low = impulse.end_price
        leg_size = high - low

        fib_62 = low + 0.618 * leg_size
        fib_705 = low + 0.705 * leg_size
        fib_79 = low + 0.786 * leg_size

        return OTEZone(
            direction='BEARISH',
            top=fib_79,
            bottom=fib_62,
            midpoint=fib_705,
            fib_62=fib_62,
            fib_705=fib_705,
            fib_79=fib_79,
            impulse=impulse,
        )


def is_price_in_ote(zone: OTEZone, price: float) -> bool:
    """
    Check if a price is within the OTE zone.

    Args:
        zone: OTE zone to check
        price: Price level

    Returns:
        True if price is within the zone boundaries
    """
    return zone.bottom <= price <= zone.top


def check_ote_tap(zone: OTEZone, bar, bar_index: int) -> bool:
    """
    Check if a bar taps into the OTE zone.

    For bullish OTE (buying the dip): bar.low enters the zone
    For bearish OTE (selling the rally): bar.high enters the zone

    Args:
        zone: OTE zone to check
        bar: Current price bar
        bar_index: Index of the current bar

    Returns:
        True if bar enters the OTE zone
    """
    if zone.tapped:
        return True

    if zone.direction == 'BULLISH':
        # Price retraces down into bullish OTE zone
        if bar.low <= zone.top and bar.low >= zone.bottom:
            zone.tapped = True
            zone.tap_bar_index = bar_index
            return True
        # Price dips through the zone
        if bar.low <= zone.bottom and bar.high >= zone.bottom:
            zone.tapped = True
            zone.tap_bar_index = bar_index
            return True
    else:  # BEARISH
        # Price retraces up into bearish OTE zone
        if bar.high >= zone.bottom and bar.high <= zone.top:
            zone.tapped = True
            zone.tap_bar_index = bar_index
            return True
        # Price pushes through the zone
        if bar.high >= zone.top and bar.low <= zone.top:
            zone.tapped = True
            zone.tap_bar_index = bar_index
            return True

    return False


def check_rejection(zone: OTEZone, bar, min_wick_body_ratio: float = 0.0) -> bool:
    """
    Check if a bar shows rejection from the OTE zone.

    Rejection criteria:
    - Bar must interact with the zone (wick enters zone)
    - Bar must be in the entry direction (bullish close > open, bearish close < open)
    - Rejection wick must exist (> 0)
    - Close must be on the rejection side of the zone

    Args:
        zone: OTE zone
        bar: Current price bar
        min_wick_body_ratio: Minimum wick/body ratio for rejection quality

    Returns:
        True if bar shows rejection
    """
    zone_height = zone.top - zone.bottom
    if zone_height <= 0:
        return False

    if zone.direction == 'BULLISH':
        # Bar must wick into the zone
        if bar.low > zone.top:
            return False

        # Must be a bullish candle (close > open)
        if bar.close <= bar.open:
            return False

        # Must have a lower wick (rejection)
        lower_wick = min(bar.open, bar.close) - bar.low
        if lower_wick <= 0:
            return False

        # Wick must be >= min_wick_body_ratio of body (filter junk rejections)
        body = abs(bar.close - bar.open)
        if body > 0 and lower_wick < min_wick_body_ratio * body:
            return False

        # Close must be above zone bottom (price rejected from zone)
        if bar.close >= zone.bottom:
            return True

    else:  # BEARISH
        # Bar must wick into the zone
        if bar.high < zone.bottom:
            return False

        # Must be a bearish candle (close < open)
        if bar.close >= bar.open:
            return False

        # Must have an upper wick (rejection)
        upper_wick = bar.high - max(bar.open, bar.close)
        if upper_wick <= 0:
            return False

        # Wick must be >= min_wick_body_ratio of body (filter junk rejections)
        body = abs(bar.close - bar.open)
        if body > 0 and upper_wick < min_wick_body_ratio * body:
            return False

        # Close must be below zone top (price rejected from zone)
        if bar.close <= zone.top:
            return True

    return False


def fvg_overlaps_ote(fvg_top: float, fvg_bottom: float, zone: OTEZone) -> bool:
    """
    Check if an FVG overlaps with the OTE zone (confluence).

    Args:
        fvg_top: FVG upper boundary
        fvg_bottom: FVG lower boundary
        zone: OTE zone

    Returns:
        True if FVG and OTE zone overlap
    """
    return fvg_bottom <= zone.top and fvg_top >= zone.bottom
