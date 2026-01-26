"""
ICT_Sweep_OTE_MSS_FVG_Long_v1 - Detection Functions

Implements:
- Swing detection (fractal pivots)
- SSL (Sell-Side Liquidity) sweep detection
- MSS (Market Structure Shift) detection
- Displacement + FVG detection
- OTE zone calculation
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional
from enum import Enum

from core.types import Bar
from strategies.ict_sweep_ote.config import (
    SwingConfig,
    SweepConfig,
    MSSConfig,
    DisplacementConfig,
    FVGConfig,
    OTEConfig,
)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class SwingType(Enum):
    HIGH = "HIGH"
    LOW = "LOW"


@dataclass
class SwingPoint:
    """A detected swing high or low."""
    bar_index: int
    timestamp: datetime
    price: float
    swing_type: SwingType
    confirmed: bool = True  # Becomes True after right_bars elapse


@dataclass
class SSLSweep:
    """Sell-Side Liquidity sweep event."""
    swept_swing: SwingPoint  # The swing low that was swept
    sweep_bar_index: int
    sweep_bar_timestamp: datetime
    sweep_low: float  # Lowest point during sweep
    penetration: float  # How far below swing low
    confirmed: bool = False  # True if price closed back above
    confirmation_bar_index: Optional[int] = None


@dataclass
class BSLSweep:
    """Buy-Side Liquidity sweep event (for shorts)."""
    swept_swing: SwingPoint  # The swing high that was swept
    sweep_bar_index: int
    sweep_bar_timestamp: datetime
    sweep_high: float  # Highest point during sweep
    penetration: float  # How far above swing high
    confirmed: bool = False  # True if price closed back below
    confirmation_bar_index: Optional[int] = None


@dataclass
class LowerHigh:
    """A lower-high pivot used for bullish MSS detection."""
    bar_index: int
    timestamp: datetime
    price: float


@dataclass
class HigherLow:
    """A higher-low pivot used for bearish MSS detection."""
    bar_index: int
    timestamp: datetime
    price: float


@dataclass
class MSSEvent:
    """Market Structure Shift event."""
    lh_pivot: LowerHigh  # The lower-high that was broken
    break_bar_index: int
    break_bar_timestamp: datetime
    break_price: float  # Price where LH was broken
    confirmed_by_close: bool  # True if closed above LH


@dataclass
class DisplacementCandle:
    """A displacement (impulsive) candle."""
    bar_index: int
    timestamp: datetime
    open_price: float
    close_price: float
    high: float
    low: float
    body_size: float
    atr_multiple: float  # body_size / ATR
    direction: Literal["BULLISH", "BEARISH"]


@dataclass
class FVGZone:
    """Fair Value Gap zone."""
    bar_index: int  # Bar that created the FVG (middle of 3-bar pattern)
    timestamp: datetime
    top: float  # Upper edge of gap
    bottom: float  # Lower edge of gap
    direction: Literal["BULLISH", "BEARISH"]
    size: float  # Gap size in price
    displacement: Optional[DisplacementCandle] = None
    mitigated: bool = False
    mitigation_bar_index: Optional[int] = None


@dataclass
class OTEZone:
    """Optimal Trade Entry zone (Fibonacci retracement)."""
    swing_low: float  # Sweep low (anchor)
    swing_high: float  # Recent high after sweep
    fib_62: float  # 62% retracement level
    fib_79: float  # 79% retracement level
    discount_50: float  # 50% level (discount boundary)

    def price_in_ote(self, price: float) -> bool:
        """Check if price is within OTE zone (62-79% retrace)."""
        return self.fib_79 <= price <= self.fib_62

    def price_in_discount(self, price: float) -> bool:
        """Check if price is in discount zone (<= 50% retrace)."""
        return price <= self.discount_50


# =============================================================================
# ATR CALCULATION
# =============================================================================

def calculate_atr(bars: list[Bar], period: int = 14) -> float:
    """
    Calculate Average True Range.

    ATR = SMA of True Range over `period` bars.
    True Range = max(high - low, |high - prev_close|, |low - prev_close|)
    """
    if len(bars) < period + 1:
        # Not enough bars, return simple high-low average
        if not bars:
            return 0.0
        return sum(b.high - b.low for b in bars) / len(bars)

    true_ranges = []
    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        prev_close = bars[i - 1].close

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        true_ranges.append(tr)

    # Return SMA of last `period` TRs
    if len(true_ranges) >= period:
        return sum(true_ranges[-period:]) / period
    return sum(true_ranges) / len(true_ranges)


def calculate_median_body(bars: list[Bar], period: int = 20) -> float:
    """Calculate median candle body size over `period` bars."""
    if not bars:
        return 0.0

    recent = bars[-period:] if len(bars) >= period else bars
    bodies = sorted([abs(b.close - b.open) for b in recent])

    n = len(bodies)
    if n % 2 == 0:
        return (bodies[n // 2 - 1] + bodies[n // 2]) / 2
    return bodies[n // 2]


# =============================================================================
# SWING DETECTION
# =============================================================================

def detect_swings(
    bars: list[Bar],
    config: SwingConfig,
    existing_swings: list[SwingPoint] | None = None
) -> list[SwingPoint]:
    """
    Detect swing highs and lows using fractal pivot method.

    A swing low at bar[i] requires:
    - low[i] is the MINIMUM of lows in [i - left_bars, i + right_bars]
    - At least min_swing_distance bars since last swing

    A swing high at bar[i] requires:
    - high[i] is the MAXIMUM of highs in [i - left_bars, i + right_bars]

    Args:
        bars: List of Bar objects
        config: SwingConfig with parameters
        existing_swings: Previously detected swings (for incremental detection)

    Returns:
        List of SwingPoint objects
    """
    swings = list(existing_swings) if existing_swings else []

    L = config.left_bars
    R = config.right_bars
    min_dist = config.min_swing_distance

    # Need at least L + R + 1 bars
    if len(bars) < L + R + 1:
        return swings

    # Find last confirmed swing index to avoid re-processing
    last_swing_idx = -min_dist
    if swings:
        last_swing_idx = max(s.bar_index for s in swings)

    # Iterate through bars that can form complete pivots
    for i in range(L, len(bars) - R):
        # Skip if too close to last swing
        if i - last_swing_idx < min_dist:
            continue

        # Skip if already processed
        if any(s.bar_index == i for s in swings):
            continue

        bar = bars[i]

        # Check for swing low
        window_lows = [bars[j].low for j in range(i - L, i + R + 1)]
        if bar.low == min(window_lows):
            # Confirm it's a proper swing low (not just flat)
            left_lows = [bars[j].low for j in range(i - L, i)]
            right_lows = [bars[j].low for j in range(i + 1, i + R + 1)]

            if all(bar.low < l for l in left_lows) or all(bar.low < l for l in right_lows):
                swing = SwingPoint(
                    bar_index=i,
                    timestamp=bar.timestamp,
                    price=bar.low,
                    swing_type=SwingType.LOW,
                    confirmed=True
                )
                swings.append(swing)
                last_swing_idx = i
                continue  # A bar can only be one type of swing

        # Check for swing high
        window_highs = [bars[j].high for j in range(i - L, i + R + 1)]
        if bar.high == max(window_highs):
            left_highs = [bars[j].high for j in range(i - L, i)]
            right_highs = [bars[j].high for j in range(i + 1, i + R + 1)]

            if all(bar.high > h for h in left_highs) or all(bar.high > h for h in right_highs):
                swing = SwingPoint(
                    bar_index=i,
                    timestamp=bar.timestamp,
                    price=bar.high,
                    swing_type=SwingType.HIGH,
                    confirmed=True
                )
                swings.append(swing)
                last_swing_idx = i

    return swings


def get_recent_swing_lows(swings: list[SwingPoint], max_count: int = 5) -> list[SwingPoint]:
    """Get the most recent swing lows."""
    lows = [s for s in swings if s.swing_type == SwingType.LOW]
    return sorted(lows, key=lambda s: s.bar_index, reverse=True)[:max_count]


def get_recent_swing_highs(swings: list[SwingPoint], max_count: int = 5) -> list[SwingPoint]:
    """Get the most recent swing highs."""
    highs = [s for s in swings if s.swing_type == SwingType.HIGH]
    return sorted(highs, key=lambda s: s.bar_index, reverse=True)[:max_count]


# =============================================================================
# SSL SWEEP DETECTION
# =============================================================================

def detect_ssl_sweep(
    bars: list[Bar],
    swings: list[SwingPoint],
    current_bar_index: int,
    config: SweepConfig,
    atr: float,
) -> Optional[SSLSweep]:
    """
    Detect sell-side liquidity sweep (price dips below swing low then recovers).

    Sweep conditions:
    1. Price goes below a swing low by at least sweep_buffer
    2. If require_close_above: candle closes back above the swept level
    3. Sweep must be confirmed within max_bars_for_confirm

    Args:
        bars: List of Bar objects
        swings: List of detected swing points
        current_bar_index: Index of current bar being processed
        config: SweepConfig parameters
        atr: Current ATR value

    Returns:
        SSLSweep if detected, None otherwise
    """
    if current_bar_index >= len(bars):
        return None

    current_bar = bars[current_bar_index]

    # Get recent swing lows to check for sweeps
    swing_lows = get_recent_swing_lows(swings, max_count=10)

    # Calculate sweep buffer
    if config.use_atr_buffer:
        sweep_buffer = atr * config.sweep_buffer_atr_mult
    else:
        sweep_buffer = current_bar.close * config.sweep_buffer_pct

    for swing_low in swing_lows:
        # Skip if swing is too recent (still forming)
        if current_bar_index - swing_low.bar_index < 3:
            continue

        # Check if current bar sweeps below this swing low
        if current_bar.low < swing_low.price - sweep_buffer:
            penetration = swing_low.price - current_bar.low

            # Check for immediate confirmation (close above)
            confirmed = False
            confirmation_idx = None

            if config.require_close_above:
                # Check if this bar closes above
                if current_bar.close > swing_low.price:
                    confirmed = True
                    confirmation_idx = current_bar_index
                # Or check next bar if allowed
                elif config.allow_next_bar_confirm:
                    # We can't know about future bars, so return unconfirmed
                    # Caller should check next bar
                    pass
            else:
                confirmed = True
                confirmation_idx = current_bar_index

            return SSLSweep(
                swept_swing=swing_low,
                sweep_bar_index=current_bar_index,
                sweep_bar_timestamp=current_bar.timestamp,
                sweep_low=current_bar.low,
                penetration=penetration,
                confirmed=confirmed,
                confirmation_bar_index=confirmation_idx
            )

    return None


def confirm_ssl_sweep(
    sweep: SSLSweep,
    bars: list[Bar],
    current_bar_index: int,
    config: SweepConfig,
) -> bool:
    """
    Confirm a pending SSL sweep with subsequent bar action.

    Returns True if sweep is now confirmed.
    """
    if sweep.confirmed:
        return True

    # Check if too many bars have passed
    bars_since_sweep = current_bar_index - sweep.sweep_bar_index
    if bars_since_sweep > config.max_bars_for_confirm:
        return False

    current_bar = bars[current_bar_index]

    # Check if current bar closes above swept level
    if current_bar.close > sweep.swept_swing.price:
        sweep.confirmed = True
        sweep.confirmation_bar_index = current_bar_index
        return True

    return False


# =============================================================================
# BSL SWEEP DETECTION (FOR SHORTS)
# =============================================================================

def detect_bsl_sweep(
    bars: list[Bar],
    swings: list[SwingPoint],
    current_bar_index: int,
    config: SweepConfig,
    atr: float,
) -> Optional[BSLSweep]:
    """
    Detect buy-side liquidity sweep (price spikes above swing high then reverses).

    Sweep conditions:
    1. Price goes above a swing high by at least sweep_buffer
    2. If require_close_above: candle closes back below the swept level
    3. Sweep must be confirmed within max_bars_for_confirm

    Args:
        bars: List of Bar objects
        swings: List of detected swing points
        current_bar_index: Index of current bar being processed
        config: SweepConfig parameters
        atr: Current ATR value

    Returns:
        BSLSweep if detected, None otherwise
    """
    if current_bar_index >= len(bars):
        return None

    current_bar = bars[current_bar_index]

    # Get recent swing highs to check for sweeps
    swing_highs = get_recent_swing_highs(swings, max_count=10)

    # Calculate sweep buffer
    if config.use_atr_buffer:
        sweep_buffer = atr * config.sweep_buffer_atr_mult
    else:
        sweep_buffer = current_bar.close * config.sweep_buffer_pct

    for swing_high in swing_highs:
        # Skip if swing is too recent (still forming)
        if current_bar_index - swing_high.bar_index < 3:
            continue

        # Check if current bar sweeps above this swing high
        if current_bar.high > swing_high.price + sweep_buffer:
            penetration = current_bar.high - swing_high.price

            # Check for immediate confirmation (close below)
            confirmed = False
            confirmation_idx = None

            if config.require_close_above:  # For BSL, this means require_close_below
                # Check if this bar closes below
                if current_bar.close < swing_high.price:
                    confirmed = True
                    confirmation_idx = current_bar_index
                elif config.allow_next_bar_confirm:
                    pass
            else:
                confirmed = True
                confirmation_idx = current_bar_index

            return BSLSweep(
                swept_swing=swing_high,
                sweep_bar_index=current_bar_index,
                sweep_bar_timestamp=current_bar.timestamp,
                sweep_high=current_bar.high,
                penetration=penetration,
                confirmed=confirmed,
                confirmation_bar_index=confirmation_idx
            )

    return None


def confirm_bsl_sweep(
    sweep: BSLSweep,
    bars: list[Bar],
    current_bar_index: int,
    config: SweepConfig,
) -> bool:
    """
    Confirm a pending BSL sweep with subsequent bar action.

    Returns True if sweep is now confirmed.
    """
    if sweep.confirmed:
        return True

    # Check if too many bars have passed
    bars_since_sweep = current_bar_index - sweep.sweep_bar_index
    if bars_since_sweep > config.max_bars_for_confirm:
        return False

    current_bar = bars[current_bar_index]

    # Check if current bar closes below swept level
    if current_bar.close < sweep.swept_swing.price:
        sweep.confirmed = True
        sweep.confirmation_bar_index = current_bar_index
        return True

    return False


# =============================================================================
# MSS DETECTION
# =============================================================================

def find_lower_high(
    bars: list[Bar],
    swings: list[SwingPoint],
    after_bar_index: int,
    lookback_bars: int = 20,
) -> Optional[LowerHigh]:
    """
    Find the lower-high pivot before a sweep point.

    A lower-high is a swing high that is lower than the previous swing high.
    This forms the resistance level that MSS will break.

    Args:
        bars: List of Bar objects
        swings: All detected swings
        after_bar_index: Index after which to look (typically sweep bar)
        lookback_bars: How far back to search

    Returns:
        LowerHigh if found, None otherwise
    """
    # Get swing highs before the reference point
    swing_highs = [
        s for s in swings
        if s.swing_type == SwingType.HIGH
        and s.bar_index < after_bar_index
        and s.bar_index >= after_bar_index - lookback_bars
    ]

    if len(swing_highs) < 2:
        return None

    # Sort by index (oldest first)
    swing_highs = sorted(swing_highs, key=lambda s: s.bar_index)

    # Find a lower-high (swing high lower than previous swing high)
    for i in range(1, len(swing_highs)):
        if swing_highs[i].price < swing_highs[i - 1].price:
            return LowerHigh(
                bar_index=swing_highs[i].bar_index,
                timestamp=swing_highs[i].timestamp,
                price=swing_highs[i].price
            )

    # If no lower-high found, use the most recent swing high
    most_recent = swing_highs[-1]
    return LowerHigh(
        bar_index=most_recent.bar_index,
        timestamp=most_recent.timestamp,
        price=most_recent.price
    )


def detect_mss(
    bars: list[Bar],
    sweep: SSLSweep,
    swings: list[SwingPoint],
    current_bar_index: int,
    config: MSSConfig,
) -> Optional[MSSEvent]:
    """
    Detect Market Structure Shift after SSL sweep.

    MSS occurs when price breaks above the lower-high pivot,
    signaling a shift from bearish to bullish structure.

    Args:
        bars: List of Bar objects
        sweep: Confirmed SSL sweep
        swings: All detected swings
        current_bar_index: Current bar index
        config: MSSConfig parameters

    Returns:
        MSSEvent if detected, None otherwise
    """
    if not sweep.confirmed:
        return None

    # Check if we're within the window for MSS
    bars_since_sweep = current_bar_index - sweep.sweep_bar_index
    if bars_since_sweep > config.max_bars_after_sweep:
        return None

    if current_bar_index >= len(bars):
        return None

    # Find the lower-high to break
    lh = find_lower_high(
        bars=bars,
        swings=swings,
        after_bar_index=sweep.sweep_bar_index,
        lookback_bars=config.lh_lookback_bars
    )

    if lh is None:
        return None

    current_bar = bars[current_bar_index]

    # Check for break above LH
    if config.require_close_above:
        if current_bar.close > lh.price:
            return MSSEvent(
                lh_pivot=lh,
                break_bar_index=current_bar_index,
                break_bar_timestamp=current_bar.timestamp,
                break_price=current_bar.close,
                confirmed_by_close=True
            )
    else:
        if current_bar.high > lh.price:
            return MSSEvent(
                lh_pivot=lh,
                break_bar_index=current_bar_index,
                break_bar_timestamp=current_bar.timestamp,
                break_price=current_bar.high,
                confirmed_by_close=False
            )

    return None


def find_higher_low(
    bars: list[Bar],
    swings: list[SwingPoint],
    after_bar_index: int,
    lookback_bars: int = 20,
) -> Optional[HigherLow]:
    """
    Find the higher-low pivot before a BSL sweep point (for shorts).

    A higher-low is a swing low that is higher than the previous swing low.
    This forms the support level that bearish MSS will break.

    Args:
        bars: List of Bar objects
        swings: All detected swings
        after_bar_index: Index after which to look (typically sweep bar)
        lookback_bars: How far back to search

    Returns:
        HigherLow if found, None otherwise
    """
    # Get swing lows before the reference point
    swing_lows = [
        s for s in swings
        if s.swing_type == SwingType.LOW
        and s.bar_index < after_bar_index
        and s.bar_index >= after_bar_index - lookback_bars
    ]

    if len(swing_lows) < 2:
        return None

    # Sort by index (oldest first)
    swing_lows = sorted(swing_lows, key=lambda s: s.bar_index)

    # Find a higher-low (swing low higher than previous swing low)
    for i in range(1, len(swing_lows)):
        if swing_lows[i].price > swing_lows[i - 1].price:
            return HigherLow(
                bar_index=swing_lows[i].bar_index,
                timestamp=swing_lows[i].timestamp,
                price=swing_lows[i].price
            )

    # If no higher-low found, use the most recent swing low
    most_recent = swing_lows[-1]
    return HigherLow(
        bar_index=most_recent.bar_index,
        timestamp=most_recent.timestamp,
        price=most_recent.price
    )


def detect_bearish_mss(
    bars: list[Bar],
    sweep: BSLSweep,
    swings: list[SwingPoint],
    current_bar_index: int,
    config: MSSConfig,
) -> Optional[MSSEvent]:
    """
    Detect bearish Market Structure Shift after BSL sweep.

    MSS occurs when price breaks below the higher-low pivot,
    signaling a shift from bullish to bearish structure.

    Args:
        bars: List of Bar objects
        sweep: Confirmed BSL sweep
        swings: All detected swings
        current_bar_index: Current bar index
        config: MSSConfig parameters

    Returns:
        MSSEvent if detected, None otherwise
    """
    if not sweep.confirmed:
        return None

    # Check if we're within the window for MSS
    bars_since_sweep = current_bar_index - sweep.sweep_bar_index
    if bars_since_sweep > config.max_bars_after_sweep:
        return None

    if current_bar_index >= len(bars):
        return None

    # Find the higher-low to break
    hl = find_higher_low(
        bars=bars,
        swings=swings,
        after_bar_index=sweep.sweep_bar_index,
        lookback_bars=config.lh_lookback_bars
    )

    if hl is None:
        return None

    current_bar = bars[current_bar_index]

    # Check for break below HL
    if config.require_close_above:  # For bearish, this means require_close_below
        if current_bar.close < hl.price:
            return MSSEvent(
                lh_pivot=hl,  # Using lh_pivot field for HL as well
                break_bar_index=current_bar_index,
                break_bar_timestamp=current_bar.timestamp,
                break_price=current_bar.close,
                confirmed_by_close=True
            )
    else:
        if current_bar.low < hl.price:
            return MSSEvent(
                lh_pivot=hl,
                break_bar_index=current_bar_index,
                break_bar_timestamp=current_bar.timestamp,
                break_price=current_bar.low,
                confirmed_by_close=False
            )

    return None


# =============================================================================
# DISPLACEMENT + FVG DETECTION
# =============================================================================

def detect_displacement(
    bars: list[Bar],
    current_bar_index: int,
    config: DisplacementConfig,
    atr: float,
) -> Optional[DisplacementCandle]:
    """
    Detect a displacement (impulsive) candle.

    Displacement = large body candle that shows strong momentum.

    Criteria:
    - Body size >= min_body_atr_mult * ATR, OR
    - Body size >= min_body_median_mult * median_body

    Args:
        bars: List of Bar objects
        current_bar_index: Index of bar to check
        config: DisplacementConfig parameters
        atr: Current ATR value

    Returns:
        DisplacementCandle if current bar qualifies, None otherwise
    """
    if current_bar_index >= len(bars):
        return None

    bar = bars[current_bar_index]
    body_size = abs(bar.close - bar.open)

    # Determine threshold
    if config.use_atr_method:
        threshold = atr * config.min_body_atr_mult
    else:
        median_body = calculate_median_body(bars[:current_bar_index], config.median_body_period)
        threshold = median_body * config.min_body_median_mult

    if body_size < threshold:
        return None

    direction = "BULLISH" if bar.close > bar.open else "BEARISH"

    return DisplacementCandle(
        bar_index=current_bar_index,
        timestamp=bar.timestamp,
        open_price=bar.open,
        close_price=bar.close,
        high=bar.high,
        low=bar.low,
        body_size=body_size,
        atr_multiple=body_size / atr if atr > 0 else 0,
        direction=direction
    )


def detect_fvg(
    bars: list[Bar],
    current_bar_index: int,
    config: FVGConfig,
    atr: float,
) -> Optional[FVGZone]:
    """
    Detect Fair Value Gap in 3-bar pattern.

    Bullish FVG:
    - Gap between bar[i-2].high and bar[i].low
    - FVG top = bar[i].low
    - FVG bottom = bar[i-2].high

    Bearish FVG:
    - Gap between bar[i].high and bar[i-2].low
    - FVG top = bar[i-2].low
    - FVG bottom = bar[i].high

    Args:
        bars: List of Bar objects
        current_bar_index: Index of third bar in pattern (bar[i])
        config: FVGConfig parameters
        atr: Current ATR value

    Returns:
        FVGZone if detected, None otherwise
    """
    if current_bar_index < 2 or current_bar_index >= len(bars):
        return None

    bar_0 = bars[current_bar_index - 2]  # First bar
    bar_1 = bars[current_bar_index - 1]  # Middle bar (usually displacement)
    bar_2 = bars[current_bar_index]      # Third bar

    # Minimum FVG size
    min_size = max(config.min_fvg_price, atr * config.min_fvg_atr_mult)

    # Check for bullish FVG: gap between bar_0.high and bar_2.low
    if bar_2.low > bar_0.high:
        gap_size = bar_2.low - bar_0.high
        if gap_size >= min_size:
            return FVGZone(
                bar_index=current_bar_index - 1,  # Middle bar created it
                timestamp=bar_1.timestamp,
                top=bar_2.low,
                bottom=bar_0.high,
                direction="BULLISH",
                size=gap_size
            )

    # Check for bearish FVG: gap between bar_2.high and bar_0.low
    if bar_0.low > bar_2.high:
        gap_size = bar_0.low - bar_2.high
        if gap_size >= min_size:
            return FVGZone(
                bar_index=current_bar_index - 1,
                timestamp=bar_1.timestamp,
                top=bar_0.low,
                bottom=bar_2.high,
                direction="BEARISH",
                size=gap_size
            )

    return None


def detect_displacement_fvg(
    bars: list[Bar],
    current_bar_index: int,
    displacement_config: DisplacementConfig,
    fvg_config: FVGConfig,
    atr: float,
) -> tuple[Optional[DisplacementCandle], Optional[FVGZone]]:
    """
    Detect both displacement and FVG together.

    Looks for a displacement candle (bar[i-1]) that creates an FVG.

    Returns:
        Tuple of (DisplacementCandle, FVGZone) or (None, None)
    """
    if current_bar_index < 2:
        return None, None

    # Check if middle bar was displacement
    displacement = detect_displacement(
        bars=bars,
        current_bar_index=current_bar_index - 1,
        config=displacement_config,
        atr=atr
    )

    if displacement is None:
        return None, None

    # Check for FVG created by this pattern
    fvg = detect_fvg(
        bars=bars,
        current_bar_index=current_bar_index,
        config=fvg_config,
        atr=atr
    )

    if fvg is None:
        return None, None

    # Verify directions match
    if displacement.direction == "BULLISH" and fvg.direction == "BULLISH":
        fvg.displacement = displacement
        return displacement, fvg
    elif displacement.direction == "BEARISH" and fvg.direction == "BEARISH":
        fvg.displacement = displacement
        return displacement, fvg

    return None, None


# =============================================================================
# OTE ZONE CALCULATION
# =============================================================================

def calculate_ote_zone(
    sweep_low: float,
    swing_high: float,
    config: OTEConfig,
) -> OTEZone:
    """
    Calculate Optimal Trade Entry zone using Fibonacci retracement.

    For long entries after SSL sweep:
    - 0% = sweep_low (anchor)
    - 100% = swing_high (recent high after sweep)
    - OTE zone = 62-79% retracement from high toward low

    Args:
        sweep_low: The sweep low (0% fib)
        swing_high: Recent high after sweep (100% fib)
        config: OTEConfig parameters

    Returns:
        OTEZone with calculated levels
    """
    range_size = swing_high - sweep_low

    # Fib retracement levels (from high, retracing toward low)
    fib_62 = swing_high - (range_size * config.ote_fib_lower)  # 62% retrace
    fib_79 = swing_high - (range_size * config.ote_fib_upper)  # 79% retrace
    discount_50 = swing_high - (range_size * config.discount_fib_max)  # 50% level

    return OTEZone(
        swing_low=sweep_low,
        swing_high=swing_high,
        fib_62=fib_62,
        fib_79=fib_79,
        discount_50=discount_50
    )


def check_fvg_ote_overlap(fvg: FVGZone, ote: OTEZone) -> bool:
    """
    Check if FVG overlaps with OTE zone.

    Returns True if any part of FVG is within OTE zone.
    """
    if fvg.direction == "BULLISH":
        # Bullish FVG: check if FVG range overlaps OTE
        fvg_top = fvg.top
        fvg_bottom = fvg.bottom
        ote_top = ote.fib_62
        ote_bottom = ote.fib_79

        # Overlap if ranges intersect
        return fvg_bottom <= ote_top and fvg_top >= ote_bottom

    return False


# =============================================================================
# FVG MITIGATION CHECK
# =============================================================================

def check_fvg_mitigation(
    fvg: FVGZone,
    bars: list[Bar],
    start_index: int,
    current_index: int,
) -> bool:
    """
    Check if FVG has been mitigated (filled) by price action.

    Bullish FVG is mitigated when price trades through the entire gap.
    """
    if fvg.mitigated:
        return True

    for i in range(start_index, min(current_index + 1, len(bars))):
        bar = bars[i]

        if fvg.direction == "BULLISH":
            # Bullish FVG mitigated when price drops through it
            if bar.low <= fvg.bottom:
                fvg.mitigated = True
                fvg.mitigation_bar_index = i
                return True
        else:
            # Bearish FVG mitigated when price rises through it
            if bar.high >= fvg.top:
                fvg.mitigated = True
                fvg.mitigation_bar_index = i
                return True

    return False


def check_fvg_entry(
    fvg: FVGZone,
    current_bar: Bar,
    config: FVGConfig,
) -> Optional[float]:
    """
    Check if current bar provides FVG entry opportunity.

    Args:
        fvg: FVGZone to check
        current_bar: Current price bar
        config: FVGConfig parameters

    Returns:
        Entry price if conditions met, None otherwise
    """
    if fvg.mitigated:
        return None

    if fvg.direction == "BULLISH":
        # Entry on retrace into bullish FVG
        if current_bar.low <= fvg.top:  # Price entered FVG
            if config.entry_mode == "FIRST_TOUCH":
                return fvg.top
            elif config.entry_mode == "MIDPOINT":
                return (fvg.top + fvg.bottom) / 2
            elif config.entry_mode == "LOWER_EDGE":
                return fvg.bottom

    elif fvg.direction == "BEARISH":
        # Entry on retrace into bearish FVG (for shorts)
        if current_bar.high >= fvg.bottom:
            if config.entry_mode == "FIRST_TOUCH":
                return fvg.bottom
            elif config.entry_mode == "MIDPOINT":
                return (fvg.top + fvg.bottom) / 2
            elif config.entry_mode == "LOWER_EDGE":
                return fvg.top

    return None
