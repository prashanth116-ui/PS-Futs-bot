"""
Fair Value Gap (FVG) Detection Module

FVG is a 3-candle pattern where there's a gap between candle 1's wick
and candle 3's wick, with candle 2 being the displacement candle.

Bullish FVG: Gap between candle 1 high and candle 3 low (price should go up to fill)
Bearish FVG: Gap between candle 1 low and candle 3 high (price should go down to fill)
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class FVG:
    """Represents a Fair Value Gap."""
    fvg_type: str  # 'BULLISH' or 'BEARISH'
    top: float  # Upper boundary of the gap
    bottom: float  # Lower boundary of the gap
    midpoint: float  # 50% level of the gap
    bar_index: int  # Index of the middle (displacement) candle
    timestamp: datetime
    size_ticks: float  # Size of gap in ticks
    mitigated: bool = False  # Has price filled the gap?
    mitigation_bar_index: Optional[int] = None


def detect_fvg(
    bars,
    tick_size: float = 0.25,
    min_size_ticks: int = 5,
    direction: Optional[str] = None
) -> Optional[FVG]:
    """
    Detect if a Fair Value Gap formed in the last 3 bars.

    Args:
        bars: List of price bars (need at least 3)
        tick_size: Instrument tick size
        min_size_ticks: Minimum gap size in ticks
        direction: Optional filter - 'BULLISH' or 'BEARISH' only

    Returns:
        FVG object if detected, None otherwise
    """
    if len(bars) < 3:
        return None

    bar1 = bars[-3]  # First candle
    bar2 = bars[-2]  # Middle candle (displacement)
    bar3 = bars[-1]  # Third candle

    # Check for BULLISH FVG (gap below, expecting price to rise)
    # Gap exists between bar1's high and bar3's low
    if bar3.low > bar1.high:
        gap_size = bar3.low - bar1.high
        gap_ticks = gap_size / tick_size

        if gap_ticks >= min_size_ticks:
            if direction is None or direction == 'BULLISH':
                return FVG(
                    fvg_type='BULLISH',
                    top=bar3.low,
                    bottom=bar1.high,
                    midpoint=(bar3.low + bar1.high) / 2,
                    bar_index=len(bars) - 2,
                    timestamp=bar2.timestamp,
                    size_ticks=gap_ticks
                )

    # Check for BEARISH FVG (gap above, expecting price to fall)
    # Gap exists between bar1's low and bar3's high
    if bar3.high < bar1.low:
        gap_size = bar1.low - bar3.high
        gap_ticks = gap_size / tick_size

        if gap_ticks >= min_size_ticks:
            if direction is None or direction == 'BEARISH':
                return FVG(
                    fvg_type='BEARISH',
                    top=bar1.low,
                    bottom=bar3.high,
                    midpoint=(bar1.low + bar3.high) / 2,
                    bar_index=len(bars) - 2,
                    timestamp=bar2.timestamp,
                    size_ticks=gap_ticks
                )

    return None


def detect_fvg_in_range(
    bars,
    start_index: int,
    end_index: int,
    tick_size: float = 0.25,
    min_size_ticks: int = 5,
    direction: Optional[str] = None
) -> list[FVG]:
    """
    Find all FVGs within a range of bars.

    Args:
        bars: List of price bars
        start_index: Start index to search from
        end_index: End index to search to
        tick_size: Instrument tick size
        min_size_ticks: Minimum gap size
        direction: Optional direction filter

    Returns:
        List of FVG objects
    """
    fvgs = []

    for i in range(max(2, start_index), min(len(bars), end_index + 1)):
        # Check the 3-bar window ending at index i
        window = bars[i-2:i+1]
        if len(window) < 3:
            continue

        fvg = detect_fvg(window, tick_size, min_size_ticks, direction)
        if fvg:
            # Adjust bar_index to be relative to full bars list
            fvg.bar_index = i - 1
            fvg.timestamp = bars[i-1].timestamp
            fvgs.append(fvg)

    return fvgs


def check_fvg_mitigation(fvg: FVG, bar, bar_index: int) -> bool:
    """
    Check if a bar mitigates (enters) an FVG.

    Args:
        fvg: The FVG to check
        bar: Current price bar
        bar_index: Index of the current bar

    Returns:
        True if bar enters the FVG zone
    """
    if fvg.mitigated:
        return True

    if fvg.fvg_type == 'BULLISH':
        # Price retraces down into bullish FVG
        if bar.low <= fvg.top:
            fvg.mitigated = True
            fvg.mitigation_bar_index = bar_index
            return True

    elif fvg.fvg_type == 'BEARISH':
        # Price retraces up into bearish FVG
        if bar.high >= fvg.bottom:
            fvg.mitigated = True
            fvg.mitigation_bar_index = bar_index
            return True

    return False


def is_price_in_fvg(fvg: FVG, price: float) -> bool:
    """
    Check if a price is within the FVG zone.

    Args:
        fvg: The FVG to check
        price: Price level to check

    Returns:
        True if price is within the FVG boundaries
    """
    return fvg.bottom <= price <= fvg.top


def get_fvg_entry_price(fvg: FVG, entry_type: str = 'midpoint') -> float:
    """
    Get the entry price for an FVG-based trade.

    Args:
        fvg: The FVG
        entry_type: 'midpoint' (50%), 'aggressive' (edge), or 'conservative' (opposite edge)

    Returns:
        Entry price
    """
    if entry_type == 'midpoint':
        return fvg.midpoint
    elif entry_type == 'aggressive':
        # Enter at the edge closest to current price movement
        return fvg.top if fvg.fvg_type == 'BULLISH' else fvg.bottom
    elif entry_type == 'conservative':
        # Enter at the far edge (deeper into the gap)
        return fvg.bottom if fvg.fvg_type == 'BULLISH' else fvg.top
    else:
        return fvg.midpoint


def update_fvg_list(fvgs: list[FVG], bar, bar_index: int, max_age_bars: int = 50) -> list[FVG]:
    """
    Update a list of FVGs - check mitigation and remove old/fully mitigated ones.

    Args:
        fvgs: List of FVGs to update
        bar: Current price bar
        bar_index: Current bar index
        max_age_bars: Remove FVGs older than this

    Returns:
        Updated list of FVGs
    """
    active_fvgs = []

    for fvg in fvgs:
        # Check mitigation
        check_fvg_mitigation(fvg, bar, bar_index)

        # Keep if not too old
        age = bar_index - fvg.bar_index
        if age <= max_age_bars:
            active_fvgs.append(fvg)

    return active_fvgs
