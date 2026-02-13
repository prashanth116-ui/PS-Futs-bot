"""
HTF Key Level Detection Module

Detects support/resistance levels from higher timeframe analysis.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from core.types import Bar


@dataclass
class SwingPoint:
    """Swing high or low point."""
    price: float
    swing_type: str  # "HIGH" or "LOW"
    bar_index: int
    timestamp: datetime
    strength: int = 1  # How many bars confirm it


@dataclass
class KeyLevel:
    """Support or resistance level."""
    price: float
    level_type: str  # "SUPPORT", "RESISTANCE"
    touches: int = 1
    created_at: Optional[datetime] = None
    last_test: Optional[datetime] = None
    broken: bool = False


def find_swing_points(bars: list[Bar], lookback: int = 5) -> list[SwingPoint]:
    """
    Find swing highs and lows.

    Args:
        bars: Price bars
        lookback: Bars to look left/right for confirmation

    Returns:
        List of swing points
    """
    swings = []

    if len(bars) < lookback * 2 + 1:
        return swings

    for i in range(lookback, len(bars) - lookback):
        bar = bars[i]

        # Swing high: highest high in lookback window
        is_swing_high = all(
            bar.high >= bars[i + j].high
            for j in range(-lookback, lookback + 1) if j != 0
        )

        # Swing low: lowest low in lookback window
        is_swing_low = all(
            bar.low <= bars[i + j].low
            for j in range(-lookback, lookback + 1) if j != 0
        )

        if is_swing_high:
            swings.append(SwingPoint(
                price=bar.high,
                swing_type="HIGH",
                bar_index=i,
                timestamp=bar.timestamp,
                strength=lookback
            ))

        if is_swing_low:
            swings.append(SwingPoint(
                price=bar.low,
                swing_type="LOW",
                bar_index=i,
                timestamp=bar.timestamp,
                strength=lookback
            ))

    return swings


def find_key_levels(bars: list[Bar], config: dict) -> list[KeyLevel]:
    """
    Find key support/resistance levels from swing points.

    Args:
        bars: HTF price bars
        config: Configuration with tolerance settings

    Returns:
        List of key levels sorted by price
    """
    lookback = config.get('swing_lookback', 5)
    tolerance_pct = config.get('level_tolerance_pct', 0.1)  # 0.1% tolerance

    swings = find_swing_points(bars, lookback)

    if not swings:
        return []

    # Convert swings to levels
    levels = []
    for swing in swings:
        level_type = "RESISTANCE" if swing.swing_type == "HIGH" else "SUPPORT"
        levels.append(KeyLevel(
            price=swing.price,
            level_type=level_type,
            touches=1,
            created_at=swing.timestamp
        ))

    # Merge nearby levels
    merged = merge_nearby_levels(levels, tolerance_pct)

    # Sort by price
    return sorted(merged, key=lambda x: x.price)


def merge_nearby_levels(levels: list[KeyLevel], tolerance_pct: float) -> list[KeyLevel]:
    """
    Merge levels within tolerance percentage.

    Args:
        levels: List of key levels
        tolerance_pct: Percentage tolerance for merging

    Returns:
        Merged list of levels
    """
    if not levels:
        return []

    sorted_levels = sorted(levels, key=lambda x: x.price)
    merged = []

    for level in sorted_levels:
        # Check if near existing merged level
        found = False
        for m in merged:
            pct_diff = abs(m.price - level.price) / m.price * 100
            if pct_diff <= tolerance_pct:
                # Merge: average price, add touches
                m.price = (m.price + level.price) / 2
                m.touches += 1
                if level.created_at and (not m.last_test or level.created_at > m.last_test):
                    m.last_test = level.created_at
                found = True
                break

        if not found:
            merged.append(KeyLevel(
                price=level.price,
                level_type=level.level_type,
                touches=level.touches,
                created_at=level.created_at
            ))

    return merged


def find_nearest_levels(
    levels: list[KeyLevel],
    current_price: float
) -> tuple[Optional[KeyLevel], Optional[KeyLevel]]:
    """
    Find nearest support and resistance to current price.

    Args:
        levels: List of key levels
        current_price: Current market price

    Returns:
        Tuple of (nearest_support, nearest_resistance)
    """
    supports = [l for l in levels if l.price < current_price and not l.broken]
    resistances = [l for l in levels if l.price > current_price and not l.broken]

    nearest_support = max(supports, key=lambda x: x.price) if supports else None
    nearest_resistance = min(resistances, key=lambda x: x.price) if resistances else None

    return nearest_support, nearest_resistance


def check_level_test(
    bar: Bar,
    level: KeyLevel,
    tolerance_ticks: int,
    tick_size: float
) -> bool:
    """
    Check if price is testing a level.

    Args:
        bar: Current bar
        level: Key level to test
        tolerance_ticks: Ticks tolerance for "testing"
        tick_size: Instrument tick size

    Returns:
        True if price is testing the level
    """
    tolerance = tolerance_ticks * tick_size

    # Price is within tolerance of level
    if level.level_type == "SUPPORT":
        return bar.low <= level.price + tolerance and bar.low >= level.price - tolerance
    else:  # RESISTANCE
        return bar.high >= level.price - tolerance and bar.high <= level.price + tolerance
