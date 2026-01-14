"""
Break of Structure (BOS) Signal Module

Identifies break of structure events that indicate shifts in market
direction. Detects when price breaks previous swing highs or lows,
signaling potential trend changes or continuations.

What is Break of Structure (BOS)?
---------------------------------
BOS occurs when price breaks through a significant swing point,
indicating a shift in market structure. In ICT methodology, BOS
is used to CONFIRM the direction suggested by a liquidity sweep.

The sequence is:
    1. Liquidity sweep occurs (e.g., sweep below a low)
    2. Price reverses and breaks structure in the opposite direction
    3. This confirms the sweep was "the move" and we can trade

Visual example of BULLISH BOS (after sweeping lows):

    Swing High ─────────┬───────────────
                        │        ▲
                        │       /│\\ BOS! Price closes above
                        │      / │ \\
                        │     /  │
    Prior Low  ─────────┼────/───┼───
                        │   /    │
                        ▼  /     │
                    Sweep      Confirmation

Why BOS matters:
- Sweep alone is not enough (could be continuation)
- BOS confirms the reversal
- Entry should come AFTER BOS (in FVG ideally)

BOS Types:
    BULLISH: Price closes above a swing high (look for longs)
    BEARISH: Price closes below a swing low (look for shorts)

Displacement:
    Strong BOS often has "displacement" - a large-bodied candle
    that shows conviction. Optional but increases probability.

Usage:
    from strategies.ict.signals.bos import detect_bos, BOSEvent
    from strategies.ict.signals.sweep import SweepEvent

    # After detecting a sweep
    bos = detect_bos(bars, config, sweep_event=sweep)
    if bos and bos.direction == "BULLISH":
        # Look for long entry in FVG
        pass
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from core.types import Bar
from strategies.ict.signals.sweep import SwingPoint, find_swing_highs, find_swing_lows

if TYPE_CHECKING:
    from strategies.ict.signals.sweep import SweepEvent


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class BOSEvent:
    """
    Represents a detected Break of Structure event.

    A BOS event occurs when price breaks through a swing point,
    confirming a potential shift in market direction.

    Attributes:
        direction: "BULLISH" (broke above swing high) or "BEARISH" (broke below swing low).
                   - BULLISH: Price closed above resistance, look for longs
                   - BEARISH: Price closed below support, look for shorts

        broken_level: The price level that was broken (the swing high/low).

        timestamp: When the BOS occurred (timestamp of the breaking bar).

        bar_index: Index of the bar that caused the break.

        reference_swing: The SwingPoint that was broken.
                         Contains the swing's timestamp and bar_index for reference.

        break_size_ticks: How far price closed beyond the level (in ticks).
                          Larger breaks may indicate stronger moves.

        displacement_ok: Whether the breaking bar meets displacement criteria.
                         True if body size >= min_displacement_ticks.
                         Stronger signals have displacement.

        close_price: The close price of the breaking bar.

        confirms_sweep: Whether this BOS confirms a prior sweep.
                        True if sweep direction matches BOS direction.
                        (Sweep DOWN + BOS BULLISH = confirmed bullish setup)

    Example:
        bos = BOSEvent(
            direction="BULLISH",
            broken_level=4502.50,
            timestamp=bar.timestamp,
            bar_index=45,
            reference_swing=swing_high,
            break_size_ticks=3.0,
            displacement_ok=True,
            close_price=4503.25,
            confirms_sweep=True,
        )
    """

    # Core BOS information
    direction: Literal["BULLISH", "BEARISH"]
    broken_level: float
    timestamp: datetime
    bar_index: int

    # Reference to the broken swing point
    reference_swing: SwingPoint | None = None

    # Break details
    break_size_ticks: float = 0.0
    displacement_ok: bool = False
    close_price: float = 0.0

    # Confirmation with sweep
    confirms_sweep: bool = False

    # Additional metadata
    metadata: dict = field(default_factory=dict)

    @property
    def reference_swing_index(self) -> int | None:
        """Get the bar index of the reference swing point."""
        return self.reference_swing.bar_index if self.reference_swing else None

    @property
    def reference_swing_time(self) -> datetime | None:
        """Get the timestamp of the reference swing point."""
        return self.reference_swing.timestamp if self.reference_swing else None


# =============================================================================
# Swing Point Helpers
# =============================================================================


def get_swing_high_before_index(
    swing_highs: list[SwingPoint],
    before_index: int,
) -> SwingPoint | None:
    """
    Get the most recent swing high that formed before a given bar index.

    Used to find the swing high to watch for BOS after a bearish sweep.

    Args:
        swing_highs: List of SwingPoint objects (swing highs).
        before_index: Find swings with bar_index < this value.

    Returns:
        The most recent (highest bar_index) swing high before the index,
        or None if no valid swing found.

    Example:
        # Find swing high before bar 50
        sh = get_swing_high_before_index(swing_highs, 50)
        if sh:
            print(f"Watch for break above {sh.price}")
    """
    valid_swings = [sh for sh in swing_highs if sh.bar_index < before_index]
    if not valid_swings:
        return None
    # Return the most recent (highest bar_index)
    return max(valid_swings, key=lambda s: s.bar_index)


def get_swing_low_before_index(
    swing_lows: list[SwingPoint],
    before_index: int,
) -> SwingPoint | None:
    """
    Get the most recent swing low that formed before a given bar index.

    Used to find the swing low to watch for BOS after a bullish sweep.

    Args:
        swing_lows: List of SwingPoint objects (swing lows).
        before_index: Find swings with bar_index < this value.

    Returns:
        The most recent (highest bar_index) swing low before the index,
        or None if no valid swing found.

    Example:
        # Find swing low before bar 50
        sl = get_swing_low_before_index(swing_lows, 50)
        if sl:
            print(f"Watch for break below {sl.price}")
    """
    valid_swings = [sl for sl in swing_lows if sl.bar_index < before_index]
    if not valid_swings:
        return None
    return max(valid_swings, key=lambda s: s.bar_index)


def get_relevant_swing_for_bos(
    bars: list[Bar],
    sweep_direction: Literal["UP", "DOWN"] | None,
    sweep_bar_index: int | None,
    config: dict,
) -> SwingPoint | None:
    """
    Get the swing point that should be watched for BOS confirmation.

    After a sweep, we look for BOS in the OPPOSITE direction:
    - Sweep DOWN (bullish) -> Watch for break ABOVE swing high -> BULLISH BOS
    - Sweep UP (bearish) -> Watch for break BELOW swing low -> BEARISH BOS

    Args:
        bars: List of Bar objects.
        sweep_direction: "UP" or "DOWN" from the sweep event.
        sweep_bar_index: Bar index where the sweep occurred.
        config: Configuration dictionary with swing detection params.

    Returns:
        The SwingPoint to watch for BOS, or None if not found.

    Example:
        swing = get_relevant_swing_for_bos(bars, "DOWN", 42, config)
        if swing:
            # Watch for price to close above swing.price
            pass
    """
    swing_left = config.get("swing_left_bars", 3)
    swing_right = config.get("swing_right_bars", 1)

    # Use bars up to (but not including) sweep bar for swing detection
    lookback_start = max(0, (sweep_bar_index or len(bars)) - config.get("lookback_bars", 20))
    lookback_end = sweep_bar_index or len(bars)
    lookback_bars = bars[lookback_start:lookback_end]

    if sweep_direction == "DOWN":
        # Bullish sweep (swept lows) -> look for swing HIGH to break above
        swing_highs = find_swing_highs(lookback_bars, swing_left, swing_right)
        if swing_highs:
            # Return the most recent swing high
            return max(swing_highs, key=lambda s: s.bar_index)

    elif sweep_direction == "UP":
        # Bearish sweep (swept highs) -> look for swing LOW to break below
        swing_lows = find_swing_lows(lookback_bars, swing_left, swing_right)
        if swing_lows:
            # Return the most recent swing low
            return max(swing_lows, key=lambda s: s.bar_index)

    return None


# =============================================================================
# BOS Detection
# =============================================================================


def check_bullish_bos(
    bar: Bar,
    bar_index: int,
    swing_high: SwingPoint,
    config: dict,
) -> BOSEvent | None:
    """
    Check if a bar creates a BULLISH Break of Structure.

    Bullish BOS occurs when price CLOSES above a swing high.
    This indicates buyers have taken control and broken resistance.

    Args:
        bar: The bar to check for BOS.
        bar_index: Index of this bar in the bar list.
        swing_high: The swing high level to check against.
        config: Configuration dictionary with:
            - tick_size: Tick size for the instrument
            - allow_wick_break: If True, wick can break (not just close)
            - min_displacement_ticks: Minimum body size for displacement

    Returns:
        BOSEvent if bullish BOS detected, None otherwise.

    Example:
        bos = check_bullish_bos(current_bar, 50, swing_high, config)
        if bos:
            print(f"Bullish BOS! Broke above {bos.broken_level}")
    """
    tick_size = config.get("tick_size", 0.25)
    allow_wick_break = config.get("allow_wick_break", False)
    min_displacement_ticks = config.get("min_displacement_ticks", 0)

    level = swing_high.price

    # Check if bar breaks the level
    if allow_wick_break:
        # Wick break - high must exceed level
        if bar.high <= level:
            return None
        break_distance = bar.high - level
    else:
        # Close break - close must exceed level
        if bar.close <= level:
            return None
        break_distance = bar.close - level

    # Calculate break size in ticks
    break_ticks = break_distance / tick_size

    # Check displacement (body size)
    body_ticks = bar.body_size / tick_size
    displacement_ok = body_ticks >= min_displacement_ticks

    # Additional check: for bullish BOS, bar should ideally be bullish
    # TODO: Consider making this configurable
    # if not bar.is_bullish:
    #     displacement_ok = False

    return BOSEvent(
        direction="BULLISH",
        broken_level=level,
        timestamp=bar.timestamp,
        bar_index=bar_index,
        reference_swing=swing_high,
        break_size_ticks=break_ticks,
        displacement_ok=displacement_ok if min_displacement_ticks > 0 else True,
        close_price=bar.close,
        confirms_sweep=False,  # Will be set by caller if applicable
    )


def check_bearish_bos(
    bar: Bar,
    bar_index: int,
    swing_low: SwingPoint,
    config: dict,
) -> BOSEvent | None:
    """
    Check if a bar creates a BEARISH Break of Structure.

    Bearish BOS occurs when price CLOSES below a swing low.
    This indicates sellers have taken control and broken support.

    Args:
        bar: The bar to check for BOS.
        bar_index: Index of this bar in the bar list.
        swing_low: The swing low level to check against.
        config: Configuration dictionary with:
            - tick_size: Tick size for the instrument
            - allow_wick_break: If True, wick can break (not just close)
            - min_displacement_ticks: Minimum body size for displacement

    Returns:
        BOSEvent if bearish BOS detected, None otherwise.

    Example:
        bos = check_bearish_bos(current_bar, 50, swing_low, config)
        if bos:
            print(f"Bearish BOS! Broke below {bos.broken_level}")
    """
    tick_size = config.get("tick_size", 0.25)
    allow_wick_break = config.get("allow_wick_break", False)
    min_displacement_ticks = config.get("min_displacement_ticks", 0)

    level = swing_low.price

    # Check if bar breaks the level
    if allow_wick_break:
        # Wick break - low must go below level
        if bar.low >= level:
            return None
        break_distance = level - bar.low
    else:
        # Close break - close must be below level
        if bar.close >= level:
            return None
        break_distance = level - bar.close

    # Calculate break size in ticks
    break_ticks = break_distance / tick_size

    # Check displacement (body size)
    body_ticks = bar.body_size / tick_size
    displacement_ok = body_ticks >= min_displacement_ticks

    return BOSEvent(
        direction="BEARISH",
        broken_level=level,
        timestamp=bar.timestamp,
        bar_index=bar_index,
        reference_swing=swing_low,
        break_size_ticks=break_ticks,
        displacement_ok=displacement_ok if min_displacement_ticks > 0 else True,
        close_price=bar.close,
        confirms_sweep=False,  # Will be set by caller if applicable
    )


def detect_bos(
    bars: list[Bar],
    config: dict,
    sweep_event: "SweepEvent | None" = None,
) -> BOSEvent | None:
    """
    Detect Break of Structure in a list of bars.

    This is the main entry point for BOS detection. It checks the
    LAST bar for BOS, using prior bars to identify swing points.

    If a sweep_event is provided, it looks for BOS that CONFIRMS
    the sweep (opposite direction break).

    Args:
        bars: List of Bar objects in chronological order.
              Must have enough bars for swing detection.

        config: Configuration dictionary with:
            - lookback_bars (int): How many bars to look back for swings (default: 20)
            - swing_left_bars (int): Left bars for swing detection (default: 3)
            - swing_right_bars (int): Right bars for swing detection (default: 1)
            - tick_size (float): Tick size for the instrument (default: 0.25)
            - allow_wick_break (bool): Allow wick to break level (default: False)
            - min_displacement_ticks (float): Min body size for displacement (default: 0)

        sweep_event: Optional SweepEvent from sweep.py.
                     If provided, only looks for BOS that confirms the sweep.
                     - Sweep DOWN -> look for BULLISH BOS
                     - Sweep UP -> look for BEARISH BOS

    Returns:
        BOSEvent if BOS detected, None otherwise.

    Example:
        config = {
            "lookback_bars": 20,
            "swing_left_bars": 3,
            "swing_right_bars": 1,
            "tick_size": 0.25,
            "min_displacement_ticks": 4,
        }

        # Detect BOS after a sweep
        bos = detect_bos(bars, config, sweep_event=sweep)
        if bos and bos.confirms_sweep:
            print(f"{bos.direction} BOS confirms the sweep!")
    """
    lookback_bars_count = config.get("lookback_bars", 20)
    swing_left = config.get("swing_left_bars", 3)
    swing_right = config.get("swing_right_bars", 1)

    # Need enough bars
    min_bars = max(lookback_bars_count, swing_left + swing_right + 2)
    if len(bars) < min_bars:
        return None

    # Current bar to check for BOS
    current_bar = bars[-1]
    current_bar_index = len(bars) - 1

    # Get lookback window for swing detection (exclude current bar)
    lookback_start = max(0, len(bars) - lookback_bars_count - swing_right)
    lookback_bars_list = bars[lookback_start:-1]

    # Find all swing points in lookback window
    swing_highs = find_swing_highs(lookback_bars_list, swing_left, swing_right)
    swing_lows = find_swing_lows(lookback_bars_list, swing_left, swing_right)

    # If sweep provided, only look for confirming BOS
    if sweep_event is not None:
        return _detect_bos_after_sweep(
            current_bar=current_bar,
            current_bar_index=current_bar_index,
            sweep_event=sweep_event,
            swing_highs=swing_highs,
            swing_lows=swing_lows,
            config=config,
        )

    # No sweep - check for any BOS
    return _detect_any_bos(
        current_bar=current_bar,
        current_bar_index=current_bar_index,
        swing_highs=swing_highs,
        swing_lows=swing_lows,
        config=config,
    )


def _detect_bos_after_sweep(
    current_bar: Bar,
    current_bar_index: int,
    sweep_event: "SweepEvent",
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    config: dict,
) -> BOSEvent | None:
    """
    Detect BOS that confirms a prior sweep.

    Internal function called by detect_bos when a sweep_event is provided.

    Logic:
    - Sweep DOWN (bullish) -> Look for break ABOVE swing high -> BULLISH BOS
    - Sweep UP (bearish) -> Look for break BELOW swing low -> BEARISH BOS

    Args:
        current_bar: The bar to check for BOS.
        current_bar_index: Index of this bar.
        sweep_event: The sweep event to confirm.
        swing_highs: List of detected swing highs.
        swing_lows: List of detected swing lows.
        config: Configuration dictionary.

    Returns:
        BOSEvent if confirming BOS found, None otherwise.
    """
    sweep_direction = sweep_event.direction
    sweep_bar_index = sweep_event.bar_index

    if sweep_direction == "DOWN":
        # Bullish sweep -> look for BULLISH BOS (break above swing high)
        # Find swing high that formed before or at the sweep
        relevant_swing = get_swing_high_before_index(swing_highs, sweep_bar_index + 1)

        if relevant_swing is None:
            return None

        bos = check_bullish_bos(current_bar, current_bar_index, relevant_swing, config)
        if bos:
            bos.confirms_sweep = True
            bos.metadata["sweep_direction"] = sweep_direction
            bos.metadata["sweep_level"] = sweep_event.swept_level
            bos.metadata["sweep_bar_index"] = sweep_bar_index
        return bos

    elif sweep_direction == "UP":
        # Bearish sweep -> look for BEARISH BOS (break below swing low)
        # Find swing low that formed before or at the sweep
        relevant_swing = get_swing_low_before_index(swing_lows, sweep_bar_index + 1)

        if relevant_swing is None:
            return None

        bos = check_bearish_bos(current_bar, current_bar_index, relevant_swing, config)
        if bos:
            bos.confirms_sweep = True
            bos.metadata["sweep_direction"] = sweep_direction
            bos.metadata["sweep_level"] = sweep_event.swept_level
            bos.metadata["sweep_bar_index"] = sweep_bar_index
        return bos

    return None


def _detect_any_bos(
    current_bar: Bar,
    current_bar_index: int,
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    config: dict,
) -> BOSEvent | None:
    """
    Detect any BOS (not tied to a sweep).

    Internal function called by detect_bos when no sweep_event is provided.
    Checks for both bullish and bearish BOS.

    Returns the first BOS found (bullish checked first).

    TODO: Consider returning the "best" BOS if multiple found,
          or returning a list of all BOS events.

    Args:
        current_bar: The bar to check for BOS.
        current_bar_index: Index of this bar.
        swing_highs: List of detected swing highs.
        swing_lows: List of detected swing lows.
        config: Configuration dictionary.

    Returns:
        BOSEvent if any BOS found, None otherwise.
    """
    # Check for BULLISH BOS (break above any swing high)
    if swing_highs:
        # Check against the most recent swing high
        most_recent_sh = max(swing_highs, key=lambda s: s.bar_index)
        bos = check_bullish_bos(current_bar, current_bar_index, most_recent_sh, config)
        if bos:
            return bos

    # Check for BEARISH BOS (break below any swing low)
    if swing_lows:
        # Check against the most recent swing low
        most_recent_sl = max(swing_lows, key=lambda s: s.bar_index)
        bos = check_bearish_bos(current_bar, current_bar_index, most_recent_sl, config)
        if bos:
            return bos

    return None


def detect_bos_on_bar(
    current_bar: Bar,
    current_bar_index: int,
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    sweep_event: "SweepEvent | None",
    config: dict,
) -> BOSEvent | None:
    """
    Check a single bar for BOS against pre-computed swing points.

    This is an optimized version for real-time processing where
    swing points are calculated once and reused.

    Unlike detect_bos(), this function:
    - Does NOT compute swing points (you provide them)
    - Checks a SINGLE bar
    - Is more efficient for bar-by-bar processing

    Args:
        current_bar: The bar to check for BOS.
        current_bar_index: Index of this bar.
        swing_highs: Pre-computed swing highs.
        swing_lows: Pre-computed swing lows.
        sweep_event: Optional sweep event to confirm.
        config: Configuration dictionary.

    Returns:
        BOSEvent if BOS found, None otherwise.

    Example:
        # Pre-compute swings once
        swing_highs = find_swing_highs(historical_bars, 3, 1)
        swing_lows = find_swing_lows(historical_bars, 3, 1)

        # Check each new bar
        for i, bar in enumerate(new_bars):
            bos = detect_bos_on_bar(
                bar, i, swing_highs, swing_lows, sweep, config
            )
            if bos:
                print(f"BOS detected: {bos.direction}")
    """
    if sweep_event is not None:
        return _detect_bos_after_sweep(
            current_bar=current_bar,
            current_bar_index=current_bar_index,
            sweep_event=sweep_event,
            swing_highs=swing_highs,
            swing_lows=swing_lows,
            config=config,
        )
    else:
        return _detect_any_bos(
            current_bar=current_bar,
            current_bar_index=current_bar_index,
            swing_highs=swing_highs,
            swing_lows=swing_lows,
            config=config,
        )


# =============================================================================
# Utility Functions
# =============================================================================


def bos_confirms_sweep(
    bos: BOSEvent,
    sweep: "SweepEvent",
) -> bool:
    """
    Check if a BOS event confirms a sweep event.

    Confirmation means the BOS direction matches what we'd expect
    after the sweep:
    - Sweep DOWN (took out lows) + BULLISH BOS = Confirmed bullish
    - Sweep UP (took out highs) + BEARISH BOS = Confirmed bearish

    Args:
        bos: The BOSEvent to check.
        sweep: The SweepEvent to check against.

    Returns:
        True if BOS confirms sweep, False otherwise.

    Example:
        if bos_confirms_sweep(bos, sweep):
            print("Setup confirmed! Look for entry.")
    """
    # Sweep DOWN = bullish context -> expect BULLISH BOS
    if sweep.direction == "DOWN" and bos.direction == "BULLISH":
        return True

    # Sweep UP = bearish context -> expect BEARISH BOS
    if sweep.direction == "UP" and bos.direction == "BEARISH":
        return True

    return False


def get_expected_bos_direction(sweep_direction: Literal["UP", "DOWN"]) -> Literal["BULLISH", "BEARISH"]:
    """
    Get the expected BOS direction to confirm a sweep.

    Args:
        sweep_direction: "UP" or "DOWN" from sweep event.

    Returns:
        "BULLISH" or "BEARISH" - the BOS direction that would confirm.

    Example:
        expected = get_expected_bos_direction(sweep.direction)
        if bos.direction == expected:
            print("Confirmed!")
    """
    if sweep_direction == "DOWN":
        return "BULLISH"
    else:
        return "BEARISH"


def calculate_bos_quality(bos: BOSEvent, config: dict) -> float:
    """
    Calculate a quality score for a BOS event.

    Quality is based on:
    - Break size (larger = better)
    - Displacement (if required and met = better)
    - Sweep confirmation (if confirms = better)

    Args:
        bos: The BOSEvent to score.
        config: Configuration dictionary.

    Returns:
        Quality score from 0.0 to 1.0.

    Example:
        quality = calculate_bos_quality(bos, config)
        if quality >= 0.7:
            print("High quality BOS!")
    """
    score = 0.0

    # Break size contribution (0.0 to 0.4)
    # 2 ticks = 0.1, 4 ticks = 0.2, 8+ ticks = 0.4
    break_score = min(0.4, bos.break_size_ticks * 0.05)
    score += break_score

    # Displacement contribution (0.0 to 0.3)
    if bos.displacement_ok:
        score += 0.3

    # Sweep confirmation contribution (0.0 to 0.3)
    if bos.confirms_sweep:
        score += 0.3

    return min(1.0, score)
