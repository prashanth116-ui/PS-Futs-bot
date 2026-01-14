"""
Fair Value Gap (FVG) Signal Module

Detects ICT-style Fair Value Gaps using a 3-bar pattern.
Tracks active (unmitigated) FVG zones and determines when
price enters or mitigates an FVG.

What is a Fair Value Gap (FVG)?
-------------------------------
An FVG occurs when three consecutive candles create an area
where price has not traded. This represents an "imbalance"
where price moved so quickly that not all orders were filled.

Definitions:
    Bullish FVG:
        - bar[i-2].high < bar[i].low
        - gap zone = (bar[i-2].high, bar[i].low)
        - Price retracing DOWN into this zone = potential long entry

    Bearish FVG:
        - bar[i-2].low > bar[i].high
        - gap zone = (bar[i].high, bar[i-2].low)
        - Price retracing UP into this zone = potential short entry

Visual example of a BULLISH FVG:

    bar[i]      │     │
                │█████│  <- bar[i].low = FVG HIGH
                └──┬──┘
                   │
    ═══════════════╧═══════════  <- FVG HIGH
           GAP (unfilled area)
    ═══════════════╤═══════════  <- FVG LOW
                   │
    bar[i-1]    │█████│  <- Displacement candle
                │  │  │
                └──┼──┘
                   │
    bar[i-2]    ┌──┴──┐
                │█████│  <- bar[i-2].high = FVG LOW
                │  │  │
                └──┴──┘

Mitigation:
    An FVG is "mitigated" when price returns to fill the gap.
    - Bullish FVG: mitigated when bar.low <= fvg.low (or closes through)
    - Bearish FVG: mitigated when bar.high >= fvg.high (or closes through)

Usage:
    from strategies.ict.signals.fvg import detect_fvgs, get_active_fvgs, FVGZone

    config = {
        "min_fvg_ticks": 2,
        "tick_size": 0.25,
        "max_fvg_age_bars": 50,
        "entry_mode": "MIDPOINT",
        "invalidate_on_close_through": True,
    }

    fvgs = detect_fvgs(bars, config)
    active = get_active_fvgs(fvgs, current_bar_index, config)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from core.types import Bar


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class FVGZone:
    """
    Represents a detected Fair Value Gap zone.

    An FVG is an imbalance zone where price moved so quickly that
    a gap was left unfilled. These zones often act as entry points.

    Attributes:
        direction: "BULLISH" (gap below price, look for longs) or
                   "BEARISH" (gap above price, look for shorts).

        low: The lower boundary of the FVG zone.
             - For BULLISH: bar[i-2].high
             - For BEARISH: bar[i].high

        high: The upper boundary of the FVG zone.
              - For BULLISH: bar[i].low
              - For BEARISH: bar[i-2].low

        midpoint: The middle of the FVG zone ((high + low) / 2).
                  Often used as the precise entry point.

        created_at: Timestamp when the FVG formed (bar[i].timestamp).

        created_bar_index: Index of bar[i] (the completing bar) in the bar list.

        mitigated: Whether price has returned to fill/mitigate the gap.
                   Initially False when detected.

        mitigation_bar_index: Bar index where mitigation occurred (None if not mitigated).

    Example:
        fvg = FVGZone(
            direction="BULLISH",
            low=4500.50,          # bar[i-2].high
            high=4502.00,         # bar[i].low
            midpoint=4501.25,
            created_at=bar.timestamp,
            created_bar_index=45,
        )
    """

    # Core FVG information
    direction: Literal["BULLISH", "BEARISH"]
    low: float
    high: float
    midpoint: float
    created_at: datetime
    created_bar_index: int

    # Mitigation status
    mitigated: bool = False
    mitigation_bar_index: int | None = None

    # Additional metadata
    metadata: dict = field(default_factory=dict)

    @property
    def size(self) -> float:
        """Size of the gap in price units (high - low)."""
        return self.high - self.low

    def contains_price(self, price: float) -> bool:
        """Check if a price is within the FVG zone."""
        return self.low <= price <= self.high

    def get_entry_price(self, entry_mode: Literal["FIRST_TOUCH", "MIDPOINT"] = "MIDPOINT") -> float:
        """
        Get the entry price based on entry mode.

        Args:
            entry_mode: How to enter the FVG.
                "FIRST_TOUCH": Enter at edge of FVG (high for bullish, low for bearish)
                "MIDPOINT": Enter at middle of FVG (default)

        Returns:
            The entry price level.
        """
        if entry_mode == "FIRST_TOUCH":
            # For bullish: enter when price touches the top of FVG (retracing down)
            # For bearish: enter when price touches the bottom of FVG (retracing up)
            return self.high if self.direction == "BULLISH" else self.low
        else:
            return self.midpoint


# =============================================================================
# FVG Detection
# =============================================================================


def _check_bullish_fvg(
    bar_i_minus_2: Bar,
    bar_i: Bar,
    bar_index: int,
    config: dict,
) -> FVGZone | None:
    """
    Check if bars form a BULLISH FVG.

    Bullish FVG occurs when:
        bar[i-2].high < bar[i].low

    The gap zone is (bar[i-2].high, bar[i].low).

    Args:
        bar_i_minus_2: The first bar (bar[i-2]).
        bar_i: The third bar (bar[i]).
        bar_index: Index of bar[i] in the bar list.
        config: Configuration dictionary.

    Returns:
        FVGZone if bullish FVG detected, None otherwise.
    """
    min_fvg_ticks = config.get("min_fvg_ticks", 1)
    tick_size = config.get("tick_size", 0.25)
    min_gap_size = min_fvg_ticks * tick_size

    # Bullish FVG: bar[i-2].high < bar[i].low
    fvg_low = bar_i_minus_2.high
    fvg_high = bar_i.low

    # Check if gap exists and meets minimum size
    gap_size = fvg_high - fvg_low
    if gap_size < min_gap_size:
        return None

    midpoint = (fvg_high + fvg_low) / 2

    return FVGZone(
        direction="BULLISH",
        low=fvg_low,
        high=fvg_high,
        midpoint=midpoint,
        created_at=bar_i.timestamp,
        created_bar_index=bar_index,
        metadata={
            "gap_size": gap_size,
            "gap_size_ticks": gap_size / tick_size,
        },
    )


def _check_bearish_fvg(
    bar_i_minus_2: Bar,
    bar_i: Bar,
    bar_index: int,
    config: dict,
) -> FVGZone | None:
    """
    Check if bars form a BEARISH FVG.

    Bearish FVG occurs when:
        bar[i-2].low > bar[i].high

    The gap zone is (bar[i].high, bar[i-2].low).

    Args:
        bar_i_minus_2: The first bar (bar[i-2]).
        bar_i: The third bar (bar[i]).
        bar_index: Index of bar[i] in the bar list.
        config: Configuration dictionary.

    Returns:
        FVGZone if bearish FVG detected, None otherwise.
    """
    min_fvg_ticks = config.get("min_fvg_ticks", 1)
    tick_size = config.get("tick_size", 0.25)
    min_gap_size = min_fvg_ticks * tick_size

    # Bearish FVG: bar[i-2].low > bar[i].high
    fvg_low = bar_i.high
    fvg_high = bar_i_minus_2.low

    # Check if gap exists and meets minimum size
    gap_size = fvg_high - fvg_low
    if gap_size < min_gap_size:
        return None

    midpoint = (fvg_high + fvg_low) / 2

    return FVGZone(
        direction="BEARISH",
        low=fvg_low,
        high=fvg_high,
        midpoint=midpoint,
        created_at=bar_i.timestamp,
        created_bar_index=bar_index,
        metadata={
            "gap_size": gap_size,
            "gap_size_ticks": gap_size / tick_size,
        },
    )


def _detect_fvg_at_index(
    bars: list[Bar],
    index: int,
    config: dict,
) -> FVGZone | None:
    """
    Check for FVG formation at a specific bar index.

    Checks the three bars: bar[index-2], bar[index-1], bar[index]
    for both bullish and bearish FVG patterns.

    Args:
        bars: List of Bar objects.
        index: Index of the third candle (bar[i]).
        config: Configuration dictionary.

    Returns:
        FVGZone if FVG found, None otherwise.
        Note: Only returns one FVG. Bullish is checked first.
    """
    # Need at least 3 bars
    if index < 2 or index >= len(bars):
        return None

    bar_i_minus_2 = bars[index - 2]
    bar_i = bars[index]

    # Check for bullish FVG first
    fvg = _check_bullish_fvg(bar_i_minus_2, bar_i, index, config)
    if fvg:
        return fvg

    # Check for bearish FVG
    fvg = _check_bearish_fvg(bar_i_minus_2, bar_i, index, config)
    if fvg:
        return fvg

    return None


def detect_fvgs(
    bars: list[Bar],
    config: dict,
) -> list[FVGZone]:
    """
    Detect all FVGs in a list of bars.

    This is the main entry point for FVG detection. It scans through
    bars looking for both bullish and bearish FVG patterns.

    Args:
        bars: List of Bar objects in chronological order.
              Must have at least 3 bars.

        config: Configuration dictionary with:
            - min_fvg_ticks (int): Minimum gap size in ticks (default: 1)
            - tick_size (float): Tick size for the instrument (default: 0.25)
            - max_fvg_age_bars (int): Maximum age before FVG expires (default: 50)
            - entry_mode (str): "FIRST_TOUCH" or "MIDPOINT" (default: "MIDPOINT")
            - invalidate_on_close_through (bool): Invalidate if price closes through (default: True)

    Returns:
        List of FVGZone objects for each FVG found.
        Sorted chronologically (oldest first).

    Example:
        config = {
            "min_fvg_ticks": 2,
            "tick_size": 0.25,
            "max_fvg_age_bars": 50,
        }

        fvgs = detect_fvgs(bars, config)

        for fvg in fvgs:
            print(f"{fvg.direction} FVG: {fvg.low} - {fvg.high}")
    """
    fvgs: list[FVGZone] = []

    # Need at least 3 bars
    if len(bars) < 3:
        return fvgs

    # Scan for FVGs starting at index 2 (need bars at i-2, i-1, i)
    for i in range(2, len(bars)):
        fvg = _detect_fvg_at_index(bars, i, config)
        if fvg:
            fvgs.append(fvg)

    return fvgs


def detect_fvg_on_bar(
    bars: list[Bar],
    config: dict,
) -> FVGZone | None:
    """
    Check if the last bar completes an FVG pattern.

    Convenience function for real-time processing. Checks only
    the last 3 bars for an FVG formation.

    Args:
        bars: List of Bar objects (checks last 3 bars).
        config: Configuration dictionary.

    Returns:
        FVGZone if the last bar completes an FVG, None otherwise.

    Example:
        # On each new bar
        fvg = detect_fvg_on_bar(bars, config)
        if fvg:
            print(f"New {fvg.direction} FVG formed!")
    """
    if len(bars) < 3:
        return None

    return _detect_fvg_at_index(bars, len(bars) - 1, config)


# =============================================================================
# FVG Mitigation
# =============================================================================


def update_fvg_mitigation(
    fvg: FVGZone,
    bar: Bar,
    bar_index: int,
    config: dict,
) -> None:
    """
    Update the mitigation status of an FVG based on current bar.

    Modifies the FVG object in place to update mitigated and mitigation_bar_index.

    Mitigation logic:
    - BULLISH FVG: mitigated when price trades down into the gap
        - If invalidate_on_close_through: bar.close <= fvg.low
        - Otherwise: bar.low <= fvg.low
    - BEARISH FVG: mitigated when price trades up into the gap
        - If invalidate_on_close_through: bar.close >= fvg.high
        - Otherwise: bar.high >= fvg.high

    Args:
        fvg: The FVGZone to update.
        bar: The current bar to check against.
        bar_index: Index of the current bar.
        config: Configuration dictionary.

    Example:
        for fvg in active_fvgs:
            update_fvg_mitigation(fvg, current_bar, current_index, config)
            if fvg.mitigated:
                print(f"FVG at {fvg.midpoint} has been mitigated")
    """
    if fvg.mitigated:
        return  # Already mitigated

    invalidate_on_close = config.get("invalidate_on_close_through", True)

    if fvg.direction == "BULLISH":
        # Bullish FVG mitigated when price comes down through it
        if invalidate_on_close:
            # Require close through the low
            if bar.close <= fvg.low:
                fvg.mitigated = True
                fvg.mitigation_bar_index = bar_index
        else:
            # Just wick through is enough
            if bar.low <= fvg.low:
                fvg.mitigated = True
                fvg.mitigation_bar_index = bar_index
    else:
        # Bearish FVG mitigated when price comes up through it
        if invalidate_on_close:
            # Require close through the high
            if bar.close >= fvg.high:
                fvg.mitigated = True
                fvg.mitigation_bar_index = bar_index
        else:
            # Just wick through is enough
            if bar.high >= fvg.high:
                fvg.mitigated = True
                fvg.mitigation_bar_index = bar_index


def update_all_fvg_mitigations(
    fvgs: list[FVGZone],
    bars: list[Bar],
    config: dict,
) -> None:
    """
    Update mitigation status for all FVGs based on price action after formation.

    Scans bars after each FVG's creation to check for mitigation.
    Modifies FVG objects in place.

    Args:
        fvgs: List of FVGZone objects to update.
        bars: Full list of Bar objects.
        config: Configuration dictionary.

    Example:
        fvgs = detect_fvgs(bars, config)
        update_all_fvg_mitigations(fvgs, bars, config)
        active = [f for f in fvgs if not f.mitigated]
    """
    for fvg in fvgs:
        if fvg.mitigated:
            continue

        # Check all bars after FVG creation
        for i in range(fvg.created_bar_index + 1, len(bars)):
            update_fvg_mitigation(fvg, bars[i], i, config)
            if fvg.mitigated:
                break


# =============================================================================
# Active FVG Filtering
# =============================================================================


def get_active_fvgs(
    fvgs: list[FVGZone],
    current_index: int,
    config: dict | None = None,
) -> list[FVGZone]:
    """
    Get FVGs that are still active (unmitigated and not expired).

    An FVG is considered active if:
    1. It is not mitigated
    2. It has not exceeded max_fvg_age_bars (if configured)

    Args:
        fvgs: List of FVGZone objects.
        current_index: Current bar index (for age calculation).
        config: Optional configuration dictionary with:
            - max_fvg_age_bars (int): Maximum age before FVG expires

    Returns:
        List of active FVGZone objects.

    Example:
        active = get_active_fvgs(all_fvgs, len(bars) - 1, config)
        print(f"{len(active)} active FVGs")
    """
    if config is None:
        config = {}

    max_age = config.get("max_fvg_age_bars")

    active: list[FVGZone] = []

    for fvg in fvgs:
        # Skip mitigated FVGs
        if fvg.mitigated:
            continue

        # Skip if FVG hasn't formed yet (shouldn't happen but safety check)
        if fvg.created_bar_index > current_index:
            continue

        # Check age limit if configured
        if max_age is not None:
            age = current_index - fvg.created_bar_index
            if age > max_age:
                continue

        active.append(fvg)

    return active


def filter_fvgs_by_direction(
    fvgs: list[FVGZone],
    direction: Literal["BULLISH", "BEARISH"],
) -> list[FVGZone]:
    """
    Filter FVGs to only those matching a specific direction.

    Args:
        fvgs: List of FVGZone objects.
        direction: "BULLISH" or "BEARISH".

    Returns:
        Filtered list of FVGs.

    Example:
        bullish_fvgs = filter_fvgs_by_direction(fvgs, "BULLISH")
    """
    return [fvg for fvg in fvgs if fvg.direction == direction]


# =============================================================================
# FVG Entry Detection
# =============================================================================


def check_fvg_entry(
    bar: Bar,
    fvg: FVGZone,
    entry_mode: Literal["FIRST_TOUCH", "MIDPOINT"] = "MIDPOINT",
) -> bool:
    """
    Check if a bar triggers an entry condition for an FVG.

    Entry logic based on entry_mode:
        FIRST_TOUCH:
            - Bullish FVG: bar.low <= fvg.high (price touched top of FVG)
            - Bearish FVG: bar.high >= fvg.low (price touched bottom of FVG)

        MIDPOINT:
            - Bullish FVG: bar.low <= fvg.midpoint (price reached midpoint)
            - Bearish FVG: bar.high >= fvg.midpoint (price reached midpoint)

    Args:
        bar: The current bar to check.
        fvg: The FVGZone to check entry against.
        entry_mode: "FIRST_TOUCH" or "MIDPOINT".

    Returns:
        True if entry condition is met, False otherwise.

    Example:
        if check_fvg_entry(current_bar, bullish_fvg, "MIDPOINT"):
            print("Entry triggered at FVG midpoint!")
    """
    if fvg.mitigated:
        return False

    if entry_mode == "FIRST_TOUCH":
        if fvg.direction == "BULLISH":
            # Bullish: price retracing DOWN, touches the top of the FVG
            return bar.low <= fvg.high
        else:
            # Bearish: price retracing UP, touches the bottom of the FVG
            return bar.high >= fvg.low
    else:  # MIDPOINT
        if fvg.direction == "BULLISH":
            # Bullish: price retracing DOWN to midpoint
            return bar.low <= fvg.midpoint
        else:
            # Bearish: price retracing UP to midpoint
            return bar.high >= fvg.midpoint


def check_price_in_fvg(
    price: float,
    fvg: FVGZone,
) -> bool:
    """
    Check if a specific price is within the FVG zone.

    Args:
        price: The price to check.
        fvg: The FVGZone to check against.

    Returns:
        True if price is between fvg.low and fvg.high (inclusive).

    Example:
        if check_price_in_fvg(current_price, bullish_fvg):
            print("Price is in the FVG zone!")
    """
    return fvg.low <= price <= fvg.high


# =============================================================================
# FVG Selection
# =============================================================================


def get_nearest_fvg(
    fvgs: list[FVGZone],
    current_price: float,
    direction: Literal["BULLISH", "BEARISH"] | None = None,
) -> FVGZone | None:
    """
    Get the FVG nearest to the current price.

    Args:
        fvgs: List of FVGZone objects.
        current_price: The current market price.
        direction: Optional filter by direction.

    Returns:
        The nearest FVGZone, or None if list is empty.

    Example:
        fvg = get_nearest_fvg(active_fvgs, current_price, "BULLISH")
        if fvg:
            print(f"Nearest bullish FVG at {fvg.midpoint}")
    """
    if not fvgs:
        return None

    candidates = fvgs
    if direction:
        candidates = filter_fvgs_by_direction(fvgs, direction)

    if not candidates:
        return None

    def distance_to_fvg(fvg: FVGZone) -> float:
        """Distance from current price to nearest edge of FVG."""
        if current_price < fvg.low:
            return fvg.low - current_price
        elif current_price > fvg.high:
            return current_price - fvg.high
        else:
            return 0.0  # Price is inside FVG

    return min(candidates, key=distance_to_fvg)


def get_fvg_for_entry(
    fvgs: list[FVGZone],
    current_price: float,
    direction: Literal["BULLISH", "BEARISH"],
    max_distance_ticks: float | None = None,
    tick_size: float = 0.25,
) -> FVGZone | None:
    """
    Get the best FVG for entry at the current price.

    This function finds an unmitigated FVG that:
    1. Matches the desired direction
    2. Is reachable from current price (price moving toward it)
    3. Optionally within a maximum distance

    For BULLISH entry: Finds FVGs BELOW current price (price will retrace down)
    For BEARISH entry: Finds FVGs ABOVE current price (price will retrace up)

    Args:
        fvgs: List of FVGZone objects.
        current_price: The current market price.
        direction: "BULLISH" (looking for longs) or "BEARISH" (looking for shorts).
        max_distance_ticks: Maximum distance in ticks to consider (optional).
        tick_size: Tick size for distance calculation.

    Returns:
        The best FVGZone for entry, or None if none suitable.

    Example:
        fvg = get_fvg_for_entry(
            active_fvgs,
            current_price=4505.00,
            direction="BULLISH",
            max_distance_ticks=20,
            tick_size=0.25,
        )
        if fvg:
            limit_price = fvg.midpoint
            print(f"Set limit buy at {limit_price}")
    """
    # Filter by direction and unmitigated
    candidates = [
        fvg for fvg in fvgs
        if fvg.direction == direction and not fvg.mitigated
    ]

    if not candidates:
        return None

    # Filter by position relative to current price
    if direction == "BULLISH":
        # For longs, we want FVGs BELOW current price (price retraces to entry)
        candidates = [fvg for fvg in candidates if fvg.high <= current_price]
    else:
        # For shorts, we want FVGs ABOVE current price (price retraces to entry)
        candidates = [fvg for fvg in candidates if fvg.low >= current_price]

    if not candidates:
        return None

    # Apply max distance filter if specified
    if max_distance_ticks is not None:
        max_distance = max_distance_ticks * tick_size
        if direction == "BULLISH":
            candidates = [
                fvg for fvg in candidates
                if (current_price - fvg.midpoint) <= max_distance
            ]
        else:
            candidates = [
                fvg for fvg in candidates
                if (fvg.midpoint - current_price) <= max_distance
            ]

    if not candidates:
        return None

    # Return the nearest FVG
    if direction == "BULLISH":
        # Nearest = highest high (closest to current price from below)
        return max(candidates, key=lambda fvg: fvg.high)
    else:
        # Nearest = lowest low (closest to current price from above)
        return min(candidates, key=lambda fvg: fvg.low)
