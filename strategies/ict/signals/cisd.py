"""
Change in State of Delivery (CISD) Detection Module

CISD is a key ICT concept that identifies when the market shifts from one
directional state to another. It's a more stringent confirmation than BOS.

What is CISD?
-------------
CISD occurs when:
1. Price takes out a key level (sweep/liquidity grab)
2. Price then breaks structure in the OPPOSITE direction (BOS)
3. Price shows displacement (strong momentum candle)
4. The market "state" has changed from bullish to bearish or vice versa

CISD vs BOS:
- BOS = any structure break
- CISD = structure break with displacement that confirms directional change

Visual example of BULLISH CISD:

    Swing High ─────────────────────────
                              ▲
                             /│\\  CISD candle (displacement)
                            / │ \\
    Prior Low  ────────────/──┼──\\─────
                          /   │
                    Sweep ▼   │
                              │
    ─────────────────────────────────────

    Sequence: Sweep low → Displacement up through structure → CISD confirmed

Usage:
    from strategies.ict.signals.cisd import detect_cisd, CISDEvent

    cisd = detect_cisd(bars, config, sweep_event)
    if cisd and cisd.confirmed:
        # Look for FVG entry in direction of CISD
        pass
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from core.types import Bar
from strategies.ict.signals.sweep import SwingPoint, find_swing_highs, find_swing_lows

if TYPE_CHECKING:
    from strategies.ict.signals.sweep import SweepEvent


@dataclass
class CISDEvent:
    """
    Represents a confirmed Change in State of Delivery.

    Attributes:
        direction: "BULLISH" or "BEARISH" - the new market state
        displacement_bar: The bar that caused the displacement
        displacement_bar_index: Index of the displacement bar
        broken_level: The structure level that was broken
        timestamp: When CISD occurred
        displacement_size: Size of the displacement candle body in ticks
        confirmed: Whether all CISD criteria are met
        fvg_zone: Optional tuple (low, high) of FVG created by displacement
    """
    direction: Literal["BULLISH", "BEARISH"]
    displacement_bar: Bar
    displacement_bar_index: int
    broken_level: float
    timestamp: datetime
    displacement_size: float = 0.0
    confirmed: bool = False
    fvg_zone: tuple[float, float] | None = None
    metadata: dict = field(default_factory=dict)


def check_displacement(
    bar: Bar,
    min_displacement_ticks: float,
    tick_size: float,
) -> tuple[bool, float]:
    """
    Check if a bar qualifies as a displacement candle.

    Displacement = strong momentum candle with large body relative to wicks.

    Args:
        bar: The bar to check
        min_displacement_ticks: Minimum body size in ticks
        tick_size: Tick size for the instrument

    Returns:
        Tuple of (is_displacement, body_size_ticks)
    """
    body_size = bar.body_size
    body_ticks = body_size / tick_size

    # Check minimum body size
    if body_ticks < min_displacement_ticks:
        return False, body_ticks

    # Check body-to-range ratio (body should be >60% of total range)
    if bar.range > 0:
        body_ratio = body_size / bar.range
        if body_ratio < 0.6:
            return False, body_ticks

    return True, body_ticks


def detect_cisd(
    bars: list[Bar],
    config: dict,
    sweep_event: "SweepEvent | None" = None,
) -> CISDEvent | None:
    """
    Detect Change in State of Delivery.

    CISD requires:
    1. A sweep event (liquidity grab)
    2. A displacement candle breaking structure in opposite direction
    3. Displacement candle meets minimum size requirement

    Args:
        bars: List of Bar objects
        config: Configuration with:
            - tick_size: Tick size for instrument
            - min_displacement_ticks: Minimum displacement body size (default: 4)
            - swing_left_bars: Left bars for swing detection
            - swing_right_bars: Right bars for swing detection
            - lookback_bars: Lookback window for structure
        sweep_event: The sweep event to confirm with CISD

    Returns:
        CISDEvent if CISD detected, None otherwise
    """
    if len(bars) < 5:
        return None

    tick_size = config.get("tick_size", 0.25)
    min_displacement_ticks = config.get("min_displacement_ticks", 4)
    swing_left = config.get("swing_left_bars", 3)
    swing_right = config.get("swing_right_bars", 1)
    lookback = config.get("lookback_bars", 20)

    current_bar = bars[-1]
    current_bar_index = len(bars) - 1

    # Check if current bar is a displacement candle
    is_displacement, disp_ticks = check_displacement(
        current_bar, min_displacement_ticks, tick_size
    )

    if not is_displacement:
        return None

    # Determine displacement direction
    bar_direction = "BULLISH" if current_bar.close > current_bar.open else "BEARISH"

    # If we have a sweep, CISD must be in opposite direction
    if sweep_event:
        expected_direction = "BULLISH" if sweep_event.direction == "DOWN" else "BEARISH"
        if bar_direction != expected_direction:
            return None

    # Find swing points for structure reference
    lookback_start = max(0, len(bars) - lookback)
    lookback_bars = bars[lookback_start:-1]

    swing_highs = find_swing_highs(lookback_bars, swing_left, swing_right)
    swing_lows = find_swing_lows(lookback_bars, swing_left, swing_right)

    # Check for structure break with displacement
    broken_level = None

    if bar_direction == "BULLISH":
        # Bullish CISD: displacement candle closes above a swing high
        for sh in sorted(swing_highs, key=lambda s: s.price, reverse=True):
            if current_bar.close > sh.price and current_bar.open < sh.price:
                # Candle opened below and closed above the swing high
                broken_level = sh.price
                break

        if broken_level is None and swing_highs:
            # Check if close is above the most recent swing high
            recent_sh = max(swing_highs, key=lambda s: s.bar_index)
            if current_bar.close > recent_sh.price:
                broken_level = recent_sh.price

    else:  # BEARISH
        # Bearish CISD: displacement candle closes below a swing low
        for sl in sorted(swing_lows, key=lambda s: s.price):
            if current_bar.close < sl.price and current_bar.open > sl.price:
                # Candle opened above and closed below the swing low
                broken_level = sl.price
                break

        if broken_level is None and swing_lows:
            # Check if close is below the most recent swing low
            recent_sl = max(swing_lows, key=lambda s: s.bar_index)
            if current_bar.close < recent_sl.price:
                broken_level = recent_sl.price

    if broken_level is None:
        return None

    # Check if displacement creates an FVG
    fvg_zone = None
    if len(bars) >= 3:
        bar_minus_2 = bars[-3]
        if bar_direction == "BULLISH":
            # Bullish FVG: gap between bar[-3].high and bar[-1].low
            if current_bar.low > bar_minus_2.high:
                fvg_zone = (bar_minus_2.high, current_bar.low)
        else:
            # Bearish FVG: gap between bar[-1].high and bar[-3].low
            if current_bar.high < bar_minus_2.low:
                fvg_zone = (current_bar.high, bar_minus_2.low)

    # CISD is confirmed if we have sweep + displacement + structure break
    confirmed = (
        sweep_event is not None and
        is_displacement and
        broken_level is not None
    )

    return CISDEvent(
        direction=bar_direction,
        displacement_bar=current_bar,
        displacement_bar_index=current_bar_index,
        broken_level=broken_level,
        timestamp=current_bar.timestamp,
        displacement_size=disp_ticks,
        confirmed=confirmed,
        fvg_zone=fvg_zone,
        metadata={
            "sweep_direction": sweep_event.direction if sweep_event else None,
            "sweep_level": sweep_event.swept_level if sweep_event else None,
            "body_ratio": current_bar.body_size / current_bar.range if current_bar.range > 0 else 0,
        }
    )


def detect_cisd_on_bar(
    current_bar: Bar,
    bar_index: int,
    bars_history: list[Bar],
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    sweep_event: "SweepEvent | None",
    config: dict,
) -> CISDEvent | None:
    """
    Check a single bar for CISD against pre-computed swing points.

    Optimized version for real-time processing.

    Args:
        current_bar: The bar to check
        bar_index: Index of this bar
        bars_history: Recent bar history (for FVG detection)
        swing_highs: Pre-computed swing highs
        swing_lows: Pre-computed swing lows
        sweep_event: Optional sweep event to confirm
        config: Configuration dictionary

    Returns:
        CISDEvent if CISD detected, None otherwise
    """
    tick_size = config.get("tick_size", 0.25)
    min_displacement_ticks = config.get("min_displacement_ticks", 4)

    # Check displacement
    is_displacement, disp_ticks = check_displacement(
        current_bar, min_displacement_ticks, tick_size
    )

    if not is_displacement:
        return None

    # Determine direction
    bar_direction = "BULLISH" if current_bar.close > current_bar.open else "BEARISH"

    # Validate against sweep direction
    if sweep_event:
        expected_direction = "BULLISH" if sweep_event.direction == "DOWN" else "BEARISH"
        if bar_direction != expected_direction:
            return None

    # Check structure break
    broken_level = None

    if bar_direction == "BULLISH" and swing_highs:
        for sh in sorted(swing_highs, key=lambda s: s.price, reverse=True):
            if current_bar.close > sh.price:
                broken_level = sh.price
                break

    elif bar_direction == "BEARISH" and swing_lows:
        for sl in sorted(swing_lows, key=lambda s: s.price):
            if current_bar.close < sl.price:
                broken_level = sl.price
                break

    if broken_level is None:
        return None

    # Check for FVG
    fvg_zone = None
    if len(bars_history) >= 3:
        bar_minus_2 = bars_history[-3]
        if bar_direction == "BULLISH" and current_bar.low > bar_minus_2.high:
            fvg_zone = (bar_minus_2.high, current_bar.low)
        elif bar_direction == "BEARISH" and current_bar.high < bar_minus_2.low:
            fvg_zone = (current_bar.high, bar_minus_2.low)

    confirmed = sweep_event is not None and broken_level is not None

    return CISDEvent(
        direction=bar_direction,
        displacement_bar=current_bar,
        displacement_bar_index=bar_index,
        broken_level=broken_level,
        timestamp=current_bar.timestamp,
        displacement_size=disp_ticks,
        confirmed=confirmed,
        fvg_zone=fvg_zone,
    )
