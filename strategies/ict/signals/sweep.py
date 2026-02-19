"""
Liquidity Sweep Signal Module

Detects liquidity sweeps where price moves beyond key highs/lows
to trigger stop losses before reversing. Identifies when smart money
is accumulating or distributing positions.

What is a Liquidity Sweep?
--------------------------
A liquidity sweep occurs when price temporarily moves beyond a key
level (swing high/low, session high/low) to trigger stop losses,
then reverses back inside the range. This is often referred to as
a "stop hunt" or "liquidity grab".

Visual example of a BULLISH sweep (sweep below, then reverse up):

    Prior Low ──────────────────────
                        │
                        ▼ Price wicks below (triggers stops)
                        │
                        ▲ Price closes back above (no acceptance)
                        │
    ────────────────────────────────

Why it matters:
- Retail traders place stops below obvious lows
- Smart money sweeps these levels to fill large orders
- The sweep + reversal indicates the "real" direction

Sweep Types:
    PRIOR_SESSION: Sweep of previous day's high or low
    SWING: Sweep of a recent swing high or swing low

Sweep Direction:
    UP: Price swept above a high (bearish - look for shorts)
    DOWN: Price swept below a low (bullish - look for longs)

Usage:
    from strategies.ict.signals.sweep import detect_sweeps, SweepEvent

    config = {"lookback_bars": 20, "min_sweep_ticks": 2, "tick_size": 0.25}
    sweeps = detect_sweeps(bars, config)

    for sweep in sweeps:
        if sweep.direction == "DOWN":
            # Bullish setup - look for longs
            pass
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from core.types import Bar


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class SwingPoint:
    """
    Represents a swing high or swing low in price action.

    A swing high is a bar whose high is higher than the bars on either side.
    A swing low is a bar whose low is lower than the bars on either side.

    Attributes:
        price: The price level of the swing (high or low of the bar).
        timestamp: When this swing occurred.
        bar_index: Index of this bar in the original bar list.
        swing_type: "HIGH" for swing high, "LOW" for swing low.
    """

    price: float
    timestamp: datetime
    bar_index: int
    swing_type: Literal["HIGH", "LOW"]


@dataclass
class SessionLevels:
    """
    High and low prices from a prior trading session.

    Used to identify prior session high/low for sweep detection.
    These are key liquidity levels where stops accumulate.

    Attributes:
        high: The session high price.
        low: The session low price.
        date: The date of the session (for identification).
    """

    high: float
    low: float
    date: datetime | None = None


@dataclass
class KeyLiquidityLevels:
    """
    Pre-identified key liquidity levels for proactive sweep detection.

    These levels are marked at session start and watched for sweeps.
    Much more effective than reactive swing detection.

    Attributes:
        pdh: Previous Day High
        pdl: Previous Day Low
        overnight_high: Overnight/Globex session high (after RTH close)
        overnight_low: Overnight/Globex session low
        opening_range_high: First N minutes of RTH high
        opening_range_low: First N minutes of RTH low
        asia_high: Asia session high (optional)
        asia_low: Asia session low (optional)
        current_session_high: Developing session high
        current_session_low: Developing session low
    """
    pdh: float | None = None
    pdl: float | None = None
    overnight_high: float | None = None
    overnight_low: float | None = None
    opening_range_high: float | None = None
    opening_range_low: float | None = None
    asia_high: float | None = None
    asia_low: float | None = None
    current_session_high: float | None = None
    current_session_low: float | None = None

    def get_all_levels(self) -> list[tuple[str, float, Literal["HIGH", "LOW"]]]:
        """Get all defined levels as (name, price, type) tuples."""
        levels = []
        if self.pdh is not None:
            levels.append(("PDH", self.pdh, "HIGH"))
        if self.pdl is not None:
            levels.append(("PDL", self.pdl, "LOW"))
        if self.overnight_high is not None:
            levels.append(("ON_HIGH", self.overnight_high, "HIGH"))
        if self.overnight_low is not None:
            levels.append(("ON_LOW", self.overnight_low, "LOW"))
        if self.opening_range_high is not None:
            levels.append(("OR_HIGH", self.opening_range_high, "HIGH"))
        if self.opening_range_low is not None:
            levels.append(("OR_LOW", self.opening_range_low, "LOW"))
        if self.asia_high is not None:
            levels.append(("ASIA_HIGH", self.asia_high, "HIGH"))
        if self.asia_low is not None:
            levels.append(("ASIA_LOW", self.asia_low, "LOW"))
        return levels


@dataclass
class SweepEvent:
    """
    Represents a detected liquidity sweep.

    A sweep event is generated when price wicks beyond a key level
    and closes back inside, indicating a potential reversal.

    Attributes:
        direction: "UP" (swept above high, bearish) or "DOWN" (swept below low, bullish).
                   - "UP" means price went UP through resistance, triggering buy stops
                   - "DOWN" means price went DOWN through support, triggering sell stops

        swept_level: The price level that was swept (the high/low that was taken).

        timestamp: When the sweep occurred (timestamp of the sweeping bar).

        sweep_type: What kind of level was swept.
                    - "PRIOR_SESSION": Previous session's high or low
                    - "SWING": A recent swing high or swing low

        sweep_size_ticks: How far price exceeded the level (in ticks).
                          Larger sweeps may indicate stronger setups.

        close_price: Where price closed after the sweep.
                     Used to confirm price closed back inside.

        bar_index: Index of the sweeping bar in the bar list.
                   Useful for referencing the specific bar.

        strength: Optional strength score (0.0 to 1.0).
                  Based on factors like sweep size, volume, etc.
                  Higher = stronger sweep signal.

    Example:
        sweep = SweepEvent(
            direction="DOWN",           # Swept below a low (bullish)
            swept_level=4495.00,        # The low that was taken
            timestamp=bar.timestamp,
            sweep_type="SWING",
            sweep_size_ticks=3,         # Exceeded by 3 ticks
            close_price=4497.50,        # Closed back above
            bar_index=42,
        )
    """

    # Core sweep information
    direction: Literal["UP", "DOWN"]
    swept_level: float
    timestamp: datetime
    sweep_type: Literal["PRIOR_SESSION", "SWING"]

    # Sweep details
    sweep_size_ticks: float = 0.0
    close_price: float = 0.0
    bar_index: int = 0

    # Optional strength metrics
    strength: float = field(default=0.0)

    # Additional metadata for debugging/analysis
    metadata: dict = field(default_factory=dict)


# =============================================================================
# Swing Point Detection
# =============================================================================


def find_swing_highs(
    bars: list[Bar],
    left_bars: int = 2,
    right_bars: int = 2,
) -> list[SwingPoint]:
    """
    Find swing highs in a list of bars.

    A swing high is a bar whose high is HIGHER than the highs of
    `left_bars` bars to its left AND `right_bars` bars to its right.

    Visual example (left_bars=2, right_bars=2):

        Swing High
            ▲
           /|\\
          / | \\
         /  |  \\
        L2 L1  R1 R2
        ↑  ↑   ↑  ↑
        Must all be lower than the swing high

    Args:
        bars: List of Bar objects in chronological order.
        left_bars: Number of bars to the left that must be lower.
        right_bars: Number of bars to the right that must be lower.

    Returns:
        List of SwingPoint objects for each swing high found.

    Note:
        - Requires at least (left_bars + 1 + right_bars) bars
        - Bars at the edges cannot be swing points (not enough context)

    Example:
        swing_highs = find_swing_highs(bars, left_bars=3, right_bars=2)
        for sh in swing_highs:
            print(f"Swing high at {sh.price} on {sh.timestamp}")
    """
    swing_highs: list[SwingPoint] = []

    # Need enough bars for comparison
    min_bars_needed = left_bars + 1 + right_bars
    if len(bars) < min_bars_needed:
        return swing_highs

    # Check each potential swing high
    # Start at left_bars, end at len - right_bars
    for i in range(left_bars, len(bars) - right_bars):
        candidate_high = bars[i].high
        is_swing_high = True

        # Check left side - all must be lower
        for j in range(i - left_bars, i):
            if bars[j].high >= candidate_high:
                is_swing_high = False
                break

        if not is_swing_high:
            continue

        # Check right side - all must be lower
        for j in range(i + 1, i + right_bars + 1):
            if bars[j].high >= candidate_high:
                is_swing_high = False
                break

        if is_swing_high:
            swing_highs.append(
                SwingPoint(
                    price=candidate_high,
                    timestamp=bars[i].timestamp,
                    bar_index=i,
                    swing_type="HIGH",
                )
            )

    return swing_highs


def find_swing_lows(
    bars: list[Bar],
    left_bars: int = 2,
    right_bars: int = 2,
) -> list[SwingPoint]:
    """
    Find swing lows in a list of bars.

    A swing low is a bar whose low is LOWER than the lows of
    `left_bars` bars to its left AND `right_bars` bars to its right.

    Visual example (left_bars=2, right_bars=2):

        L2 L1  R1 R2
        ↓  ↓   ↓  ↓
        Must all be higher than the swing low
         \\  |  /
          \\ | /
           \\|/
            ▼
        Swing Low

    Args:
        bars: List of Bar objects in chronological order.
        left_bars: Number of bars to the left that must be higher.
        right_bars: Number of bars to the right that must be higher.

    Returns:
        List of SwingPoint objects for each swing low found.

    Example:
        swing_lows = find_swing_lows(bars, left_bars=3, right_bars=2)
        for sl in swing_lows:
            print(f"Swing low at {sl.price} on {sl.timestamp}")
    """
    swing_lows: list[SwingPoint] = []

    # Need enough bars for comparison
    min_bars_needed = left_bars + 1 + right_bars
    if len(bars) < min_bars_needed:
        return swing_lows

    # Check each potential swing low
    for i in range(left_bars, len(bars) - right_bars):
        candidate_low = bars[i].low
        is_swing_low = True

        # Check left side - all must be higher
        for j in range(i - left_bars, i):
            if bars[j].low <= candidate_low:
                is_swing_low = False
                break

        if not is_swing_low:
            continue

        # Check right side - all must be higher
        for j in range(i + 1, i + right_bars + 1):
            if bars[j].low <= candidate_low:
                is_swing_low = False
                break

        if is_swing_low:
            swing_lows.append(
                SwingPoint(
                    price=candidate_low,
                    timestamp=bars[i].timestamp,
                    bar_index=i,
                    swing_type="LOW",
                )
            )

    return swing_lows


def find_swing_points(
    bars: list[Bar],
    left_bars: int = 2,
    right_bars: int = 2,
) -> tuple[list[SwingPoint], list[SwingPoint]]:
    """
    Find both swing highs and swing lows in a list of bars.

    Convenience function that calls both find_swing_highs and
    find_swing_lows with the same parameters.

    Args:
        bars: List of Bar objects in chronological order.
        left_bars: Number of bars to check on the left.
        right_bars: Number of bars to check on the right.

    Returns:
        Tuple of (swing_highs, swing_lows).

    Example:
        highs, lows = find_swing_points(bars, left_bars=3, right_bars=2)
        print(f"Found {len(highs)} swing highs and {len(lows)} swing lows")
    """
    swing_highs = find_swing_highs(bars, left_bars, right_bars)
    swing_lows = find_swing_lows(bars, left_bars, right_bars)
    return swing_highs, swing_lows


# =============================================================================
# Key Liquidity Level Detection (Proactive)
# =============================================================================


def calculate_key_levels(
    bars: list[Bar],
    current_bar: Bar,
    rth_start_hour: int = 9,
    rth_start_minute: int = 30,
    rth_end_hour: int = 16,
    rth_end_minute: int = 0,
    opening_range_minutes: int = 15,
) -> KeyLiquidityLevels:
    """
    Calculate key liquidity levels for proactive sweep detection.

    This function identifies levels at the START of the session that
    smart money is likely to target:
    - Previous Day High/Low (PDH/PDL)
    - Overnight High/Low (Globex session)
    - Opening Range High/Low (first N minutes of RTH)

    Args:
        bars: Historical bars including previous sessions.
        current_bar: The current bar being processed.
        rth_start_hour: RTH start hour (default 9 for 9:30 AM ET).
        rth_start_minute: RTH start minute (default 30).
        rth_end_hour: RTH end hour (default 16 for 4:00 PM ET).
        rth_end_minute: RTH end minute (default 0).
        opening_range_minutes: Minutes for opening range (default 15).

    Returns:
        KeyLiquidityLevels with all calculated levels.
    """
    from datetime import time as dt_time

    levels = KeyLiquidityLevels()

    if len(bars) < 10:
        return levels

    current_date = current_bar.timestamp.date()
    current_bar.timestamp.time()
    rth_start = dt_time(rth_start_hour, rth_start_minute)
    rth_end = dt_time(rth_end_hour, rth_end_minute)

    # Separate bars by session
    prior_rth_bars: list[Bar] = []  # Previous day RTH
    overnight_bars: list[Bar] = []  # After prior RTH close to current RTH open
    current_rth_bars: list[Bar] = []  # Current day RTH

    for bar in bars:
        bar_date = bar.timestamp.date()
        bar_time = bar.timestamp.time()

        if bar_date < current_date:
            # Previous day
            if rth_start <= bar_time <= rth_end:
                prior_rth_bars.append(bar)
            elif bar_time > rth_end:
                # After RTH close = overnight
                overnight_bars.append(bar)
        elif bar_date == current_date:
            if bar_time < rth_start:
                # Pre-market (part of overnight)
                overnight_bars.append(bar)
            elif rth_start <= bar_time <= rth_end:
                current_rth_bars.append(bar)

    # Calculate PDH/PDL from prior RTH
    if prior_rth_bars:
        levels.pdh = max(b.high for b in prior_rth_bars)
        levels.pdl = min(b.low for b in prior_rth_bars)

    # Calculate Overnight High/Low
    if overnight_bars:
        levels.overnight_high = max(b.high for b in overnight_bars)
        levels.overnight_low = min(b.low for b in overnight_bars)

    # Calculate Opening Range (first N minutes of current RTH)
    if current_rth_bars:
        # Find bars within opening range
        or_end_time = dt_time(
            rth_start_hour + (rth_start_minute + opening_range_minutes) // 60,
            (rth_start_minute + opening_range_minutes) % 60
        )
        or_bars = [b for b in current_rth_bars if b.timestamp.time() <= or_end_time]

        if or_bars:
            levels.opening_range_high = max(b.high for b in or_bars)
            levels.opening_range_low = min(b.low for b in or_bars)

        # Current session high/low (developing)
        levels.current_session_high = max(b.high for b in current_rth_bars)
        levels.current_session_low = min(b.low for b in current_rth_bars)

    return levels


def detect_sweep_at_key_level(
    bar: Bar,
    bar_index: int,
    level_name: str,
    level_price: float,
    level_type: Literal["HIGH", "LOW"],
    config: dict,
) -> SweepEvent | None:
    """
    Check if a bar sweeps a pre-identified key level.

    This is used for proactive sweep detection at known liquidity levels
    (PDH, PDL, overnight levels, etc.) rather than reactive swing detection.

    Args:
        bar: The bar to check.
        bar_index: Index of this bar.
        level_name: Name of the level (e.g., "PDH", "ON_LOW").
        level_price: The price level.
        level_type: "HIGH" or "LOW".
        config: Configuration dictionary.

    Returns:
        SweepEvent if sweep detected, None otherwise.
    """
    tick_size = config.get("tick_size", 0.25)
    min_sweep_ticks = config.get("min_sweep_ticks", 2)
    require_close_back = config.get("require_close_back_inside", True)

    sweep = check_sweep_at_level(
        bar=bar,
        level=level_price,
        level_type=level_type,
        min_sweep_ticks=min_sweep_ticks,
        tick_size=tick_size,
        require_close_back_inside=require_close_back,
    )

    if sweep:
        sweep.sweep_type = "PRIOR_SESSION"  # Key levels are treated as prior session
        sweep.bar_index = bar_index
        sweep.metadata["level_name"] = level_name
        sweep.metadata["level_source"] = "KEY_LEVEL"
        # Increase strength for key levels (more significant than random swings)
        sweep.strength = min(1.0, sweep.strength + 0.2)

    return sweep


def detect_sweep_at_key_levels(
    bar: Bar,
    bar_index: int,
    key_levels: KeyLiquidityLevels,
    config: dict,
) -> list[SweepEvent]:
    """
    Check for sweeps at all pre-identified key levels.

    This is the main function for proactive sweep detection.

    Args:
        bar: The bar to check.
        bar_index: Index of this bar.
        key_levels: Pre-calculated key liquidity levels.
        config: Configuration dictionary.

    Returns:
        List of SweepEvent objects for any sweeps detected.
    """
    sweeps: list[SweepEvent] = []

    for level_name, level_price, level_type in key_levels.get_all_levels():
        sweep = detect_sweep_at_key_level(
            bar=bar,
            bar_index=bar_index,
            level_name=level_name,
            level_price=level_price,
            level_type=level_type,
            config=config,
        )
        if sweep:
            sweeps.append(sweep)

    return sweeps


# =============================================================================
# Prior Session Detection
# =============================================================================


def get_prior_session_levels(
    bars: list[Bar],
    current_bar: Bar,
) -> SessionLevels | None:
    """
    Get the high and low from the prior trading session.

    Looks back through bars to find bars from a different date
    than the current bar, then calculates that session's high/low.

    TODO: This is a simplified implementation that assumes:
        - All bars are from the same session if same date
        - "Prior session" means "yesterday" in simple terms
        - Does not handle weekends, holidays, or overnight sessions
        - For production, consider using actual session times

    Args:
        bars: List of historical Bar objects.
        current_bar: The current bar (to determine current session).

    Returns:
        SessionLevels with prior session high/low, or None if not enough data.

    Example:
        prior = get_prior_session_levels(bars, current_bar)
        if prior:
            print(f"Prior session: High={prior.high}, Low={prior.low}")
    """
    if len(bars) < 2:
        return None

    # Get the current bar's date
    current_date = current_bar.timestamp.date()

    # Find bars from the prior session (different date)
    prior_session_bars: list[Bar] = []
    prior_date = None

    for bar in reversed(bars):
        bar_date = bar.timestamp.date()

        # Skip bars from current session
        if bar_date == current_date:
            continue

        # First bar from a prior date - this is our prior session
        if prior_date is None:
            prior_date = bar_date

        # Collect all bars from this prior session
        if bar_date == prior_date:
            prior_session_bars.append(bar)
        elif bar_date < prior_date:
            # We've gone past the prior session, stop
            break

    if not prior_session_bars:
        return None

    # Calculate high and low of prior session
    prior_high = max(bar.high for bar in prior_session_bars)
    prior_low = min(bar.low for bar in prior_session_bars)

    return SessionLevels(
        high=prior_high,
        low=prior_low,
        date=datetime.combine(prior_date, datetime.min.time()) if prior_date else None,
    )


# =============================================================================
# Sweep Detection
# =============================================================================


def check_sweep_at_level(
    bar: Bar,
    level: float,
    level_type: Literal["HIGH", "LOW"],
    min_sweep_ticks: float,
    tick_size: float,
    require_close_back_inside: bool = True,
) -> SweepEvent | None:
    """
    Check if a bar sweeps a specific price level.

    A sweep occurs when:
    1. Price wicks beyond the level by at least min_sweep_ticks
    2. Price closes back inside (if require_close_back_inside is True)

    For sweeping a HIGH (bearish sweep):
        - Bar's high must exceed the level
        - Bar's close should be below the level

    For sweeping a LOW (bullish sweep):
        - Bar's low must go below the level
        - Bar's close should be above the level

    Args:
        bar: The bar to check for a sweep.
        level: The price level to check against.
        level_type: "HIGH" if checking a resistance level, "LOW" if support.
        min_sweep_ticks: Minimum ticks beyond level to qualify as sweep.
        tick_size: Tick size for the instrument (e.g., 0.25 for ES).
        require_close_back_inside: If True, close must be back inside.

    Returns:
        SweepEvent if a sweep is detected, None otherwise.

    Example:
        sweep = check_sweep_at_level(
            bar=current_bar,
            level=4500.00,
            level_type="LOW",
            min_sweep_ticks=2,
            tick_size=0.25,
        )
        if sweep:
            print(f"Bullish sweep detected at {sweep.swept_level}")
    """
    min_sweep_distance = min_sweep_ticks * tick_size

    if level_type == "HIGH":
        # Checking for sweep ABOVE a high (bearish)
        # Bar's high must exceed the level
        sweep_distance = bar.high - level

        if sweep_distance < min_sweep_distance:
            return None  # Didn't sweep far enough

        # Check if close is back below the level
        if require_close_back_inside and bar.close >= level:
            return None  # Accepted above - not a sweep

        # Calculate sweep size in ticks
        sweep_ticks = sweep_distance / tick_size

        return SweepEvent(
            direction="UP",  # Swept upward (bearish context)
            swept_level=level,
            timestamp=bar.timestamp,
            sweep_type="SWING",  # Will be overridden by caller if needed
            sweep_size_ticks=sweep_ticks,
            close_price=bar.close,
            bar_index=0,  # Will be set by caller
            strength=_calculate_sweep_strength(sweep_ticks, bar),
        )

    else:  # level_type == "LOW"
        # Checking for sweep BELOW a low (bullish)
        # Bar's low must go below the level
        sweep_distance = level - bar.low

        if sweep_distance < min_sweep_distance:
            return None  # Didn't sweep far enough

        # Check if close is back above the level
        if require_close_back_inside and bar.close <= level:
            return None  # Accepted below - not a sweep

        # Calculate sweep size in ticks
        sweep_ticks = sweep_distance / tick_size

        return SweepEvent(
            direction="DOWN",  # Swept downward (bullish context)
            swept_level=level,
            timestamp=bar.timestamp,
            sweep_type="SWING",  # Will be overridden by caller if needed
            sweep_size_ticks=sweep_ticks,
            close_price=bar.close,
            bar_index=0,  # Will be set by caller
            strength=_calculate_sweep_strength(sweep_ticks, bar),
        )


def _calculate_sweep_strength(sweep_ticks: float, bar: Bar) -> float:
    """
    Calculate a strength score for a sweep.

    Factors considered:
    - Sweep size (more ticks = stronger)
    - Wick size relative to body (larger wick = stronger rejection)

    TODO: Consider adding:
        - Volume (higher volume = stronger)
        - Time of day (killzone sweeps may be stronger)
        - Multiple level sweeps (sweeping 2 levels = stronger)

    Args:
        sweep_ticks: How many ticks the sweep extended.
        bar: The sweeping bar (for wick analysis).

    Returns:
        Strength score from 0.0 to 1.0.
    """
    # Base strength from sweep size
    # 2 ticks = 0.3, 4 ticks = 0.5, 8+ ticks = 0.8
    size_strength = min(0.8, 0.2 + (sweep_ticks * 0.075))

    # Wick strength - larger wick relative to body = stronger rejection
    bar_range = bar.range
    if bar_range > 0:
        wick_ratio = max(bar.upper_wick, bar.lower_wick) / bar_range
        wick_strength = min(0.2, wick_ratio * 0.3)
    else:
        wick_strength = 0.0

    # Combined strength (capped at 1.0)
    return min(1.0, size_strength + wick_strength)


def detect_sweeps(
    bars: list[Bar],
    config: dict,
    prior_session: SessionLevels | None = None,
) -> list[SweepEvent]:
    """
    Detect all liquidity sweeps in a list of bars.

    This is the main entry point for sweep detection. It checks
    for sweeps at both swing points and prior session levels.

    The function scans the LAST bar in the list for sweeps, using
    the prior bars to identify swing levels.

    Args:
        bars: List of Bar objects in chronological order.
              Must have at least `lookback_bars` bars.

        config: Configuration dictionary with:
            - lookback_bars (int): How many bars to look back for swings (default: 20)
            - min_sweep_ticks (float): Minimum ticks to qualify as sweep (default: 2)
            - tick_size (float): Tick size for the instrument (default: 0.25)
            - require_close_back_inside (bool): Require close inside (default: True)
            - swing_left_bars (int): Left bars for swing detection (default: 3)
            - swing_right_bars (int): Right bars for swing detection (default: 1)

        prior_session: Optional SessionLevels from the prior trading session.
                       If provided, will check for sweeps of session high/low.

    Returns:
        List of SweepEvent objects for each sweep detected.
        May be empty if no sweeps found.

    Example:
        config = {
            "lookback_bars": 20,
            "min_sweep_ticks": 2,
            "tick_size": 0.25,
            "require_close_back_inside": True,
        }

        # Get prior session levels
        prior = get_prior_session_levels(bars[:-1], bars[-1])

        # Detect sweeps
        sweeps = detect_sweeps(bars, config, prior_session=prior)

        for sweep in sweeps:
            if sweep.direction == "DOWN":
                print(f"Bullish sweep at {sweep.swept_level}")
    """
    sweeps: list[SweepEvent] = []

    # Extract config with defaults
    lookback_bars = config.get("lookback_bars", 20)
    min_sweep_ticks = config.get("min_sweep_ticks", 2)
    tick_size = config.get("tick_size", 0.25)
    require_close_back = config.get("require_close_back_inside", True)
    swing_left = config.get("swing_left_bars", 3)
    swing_right = config.get("swing_right_bars", 1)

    # Need enough bars
    if len(bars) < lookback_bars:
        return sweeps

    # Get the current (last) bar to check for sweeps
    current_bar = bars[-1]
    current_bar_index = len(bars) - 1

    # Get lookback window for swing detection
    # We need extra bars for swing detection (left + right confirmation)
    lookback_start = max(0, len(bars) - lookback_bars - swing_right)
    lookback_bars_list = bars[lookback_start:-1]  # Exclude current bar

    # -------------------------------------------------------------------------
    # Check sweeps at PRIOR SESSION levels
    # -------------------------------------------------------------------------
    if prior_session is not None:
        # Check sweep of prior session HIGH
        sweep = check_sweep_at_level(
            bar=current_bar,
            level=prior_session.high,
            level_type="HIGH",
            min_sweep_ticks=min_sweep_ticks,
            tick_size=tick_size,
            require_close_back_inside=require_close_back,
        )
        if sweep:
            sweep.sweep_type = "PRIOR_SESSION"
            sweep.bar_index = current_bar_index
            sweep.metadata["level_source"] = "prior_session_high"
            sweeps.append(sweep)

        # Check sweep of prior session LOW
        sweep = check_sweep_at_level(
            bar=current_bar,
            level=prior_session.low,
            level_type="LOW",
            min_sweep_ticks=min_sweep_ticks,
            tick_size=tick_size,
            require_close_back_inside=require_close_back,
        )
        if sweep:
            sweep.sweep_type = "PRIOR_SESSION"
            sweep.bar_index = current_bar_index
            sweep.metadata["level_source"] = "prior_session_low"
            sweeps.append(sweep)

    # -------------------------------------------------------------------------
    # Check sweeps at SWING levels
    # -------------------------------------------------------------------------
    swing_highs, swing_lows = find_swing_points(
        bars=lookback_bars_list,
        left_bars=swing_left,
        right_bars=swing_right,
    )

    # Check sweep of each swing HIGH
    for sh in swing_highs:
        sweep = check_sweep_at_level(
            bar=current_bar,
            level=sh.price,
            level_type="HIGH",
            min_sweep_ticks=min_sweep_ticks,
            tick_size=tick_size,
            require_close_back_inside=require_close_back,
        )
        if sweep:
            sweep.sweep_type = "SWING"
            sweep.bar_index = current_bar_index
            sweep.metadata["swing_bar_index"] = sh.bar_index
            sweep.metadata["swing_timestamp"] = str(sh.timestamp)
            sweeps.append(sweep)

    # Check sweep of each swing LOW
    for sl in swing_lows:
        sweep = check_sweep_at_level(
            bar=current_bar,
            level=sl.price,
            level_type="LOW",
            min_sweep_ticks=min_sweep_ticks,
            tick_size=tick_size,
            require_close_back_inside=require_close_back,
        )
        if sweep:
            sweep.sweep_type = "SWING"
            sweep.bar_index = current_bar_index
            sweep.metadata["swing_bar_index"] = sl.bar_index
            sweep.metadata["swing_timestamp"] = str(sl.timestamp)
            sweeps.append(sweep)

    return sweeps


def detect_sweep_on_bar(
    current_bar: Bar,
    current_bar_index: int,
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    prior_session: SessionLevels | None,
    config: dict,
) -> list[SweepEvent]:
    """
    Check a single bar for sweeps against pre-computed levels.

    This is an optimized version for use in real-time processing
    where swing points are calculated once and reused.

    Unlike detect_sweeps(), this function:
    - Does NOT compute swing points (you provide them)
    - Checks a SINGLE bar (not a list)
    - Is more efficient for bar-by-bar processing

    Args:
        current_bar: The bar to check for sweeps.
        current_bar_index: Index of this bar in the bar list.
        swing_highs: Pre-computed swing highs to check.
        swing_lows: Pre-computed swing lows to check.
        prior_session: Prior session levels (optional).
        config: Configuration dictionary (same as detect_sweeps).

    Returns:
        List of SweepEvent objects for sweeps on this bar.

    Example:
        # Pre-compute swings once
        swing_highs, swing_lows = find_swing_points(historical_bars)
        prior = get_prior_session_levels(historical_bars, current_bar)

        # Check each new bar as it arrives
        for i, bar in enumerate(new_bars):
            sweeps = detect_sweep_on_bar(
                bar, i, swing_highs, swing_lows, prior, config
            )
    """
    sweeps: list[SweepEvent] = []

    # Extract config
    min_sweep_ticks = config.get("min_sweep_ticks", 2)
    tick_size = config.get("tick_size", 0.25)
    require_close_back = config.get("require_close_back_inside", True)

    # Check prior session levels
    if prior_session is not None:
        # Prior session high
        sweep = check_sweep_at_level(
            bar=current_bar,
            level=prior_session.high,
            level_type="HIGH",
            min_sweep_ticks=min_sweep_ticks,
            tick_size=tick_size,
            require_close_back_inside=require_close_back,
        )
        if sweep:
            sweep.sweep_type = "PRIOR_SESSION"
            sweep.bar_index = current_bar_index
            sweeps.append(sweep)

        # Prior session low
        sweep = check_sweep_at_level(
            bar=current_bar,
            level=prior_session.low,
            level_type="LOW",
            min_sweep_ticks=min_sweep_ticks,
            tick_size=tick_size,
            require_close_back_inside=require_close_back,
        )
        if sweep:
            sweep.sweep_type = "PRIOR_SESSION"
            sweep.bar_index = current_bar_index
            sweeps.append(sweep)

    # Check swing highs
    for sh in swing_highs:
        sweep = check_sweep_at_level(
            bar=current_bar,
            level=sh.price,
            level_type="HIGH",
            min_sweep_ticks=min_sweep_ticks,
            tick_size=tick_size,
            require_close_back_inside=require_close_back,
        )
        if sweep:
            sweep.sweep_type = "SWING"
            sweep.bar_index = current_bar_index
            sweeps.append(sweep)

    # Check swing lows
    for sl in swing_lows:
        sweep = check_sweep_at_level(
            bar=current_bar,
            level=sl.price,
            level_type="LOW",
            min_sweep_ticks=min_sweep_ticks,
            tick_size=tick_size,
            require_close_back_inside=require_close_back,
        )
        if sweep:
            sweep.sweep_type = "SWING"
            sweep.bar_index = current_bar_index
            sweeps.append(sweep)

    return sweeps


# =============================================================================
# Utility Functions
# =============================================================================


def get_most_significant_sweep(sweeps: list[SweepEvent]) -> SweepEvent | None:
    """
    Get the most significant sweep from a list.

    "Significant" is determined by:
    1. Prior session sweeps are more significant than swing sweeps
    2. Among same type, larger sweep_size_ticks wins
    3. Among same size, higher strength wins

    Args:
        sweeps: List of SweepEvent objects.

    Returns:
        The most significant sweep, or None if list is empty.

    Example:
        sweeps = detect_sweeps(bars, config)
        best = get_most_significant_sweep(sweeps)
        if best:
            print(f"Most significant: {best.sweep_type} at {best.swept_level}")
    """
    if not sweeps:
        return None

    def sweep_score(s: SweepEvent) -> tuple:
        """Higher score = more significant."""
        type_score = 1 if s.sweep_type == "PRIOR_SESSION" else 0
        return (type_score, s.sweep_size_ticks, s.strength)

    return max(sweeps, key=sweep_score)


def filter_sweeps_by_direction(
    sweeps: list[SweepEvent],
    direction: Literal["UP", "DOWN"],
) -> list[SweepEvent]:
    """
    Filter sweeps to only those matching a specific direction.

    Args:
        sweeps: List of SweepEvent objects.
        direction: "UP" for bearish sweeps, "DOWN" for bullish sweeps.

    Returns:
        Filtered list of sweeps.

    Example:
        bullish_sweeps = filter_sweeps_by_direction(sweeps, "DOWN")
    """
    return [s for s in sweeps if s.direction == direction]
