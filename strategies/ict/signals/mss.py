"""
Market Structure Shift (MSS) Detection Module

MSS occurs when price breaks a significant swing point, indicating
a potential change in market direction. It's the first sign that
the prevailing trend may be reversing.

MSS vs BOS:
- MSS = First break of structure (initial shift signal)
- BOS = Confirmation break (validates the MSS)

Flow: displacement → MSS → BOS → CISD

Visual example of BULLISH MSS after sweeping lows:

         ▲ MSS Level (swing high)
    ─────┼─────────────────────────
         │           ╱
         │          ╱ MSS Break
         │         ╱
    ─────┼────────╱─────────────────
         │       ╱
         ▼      ╱ Displacement
         └────╱
          Sweep

MSS confirms the sweep was "the move" and structure has shifted.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from core.types import Bar
from strategies.ict.signals.sweep import SwingPoint, find_swing_highs, find_swing_lows

if TYPE_CHECKING:
    from strategies.ict.signals.displacement import DisplacementEvent
    from strategies.ict.signals.liquidity import LiquidityZone


@dataclass
class MSSEvent:
    """
    Represents a Market Structure Shift event.

    Attributes:
        direction: "BULLISH" (broke above swing high) or
                   "BEARISH" (broke below swing low)
        broken_level: The swing level that was broken
        timestamp: When MSS occurred
        bar_index: Bar index where MSS occurred
        reference_swing: The swing point that was broken
        break_size_ticks: How far beyond the level price went
        has_displacement: Whether MSS was preceded by displacement
    """
    direction: Literal["BULLISH", "BEARISH"]
    broken_level: float
    timestamp: datetime
    bar_index: int
    reference_swing: SwingPoint | None = None
    break_size_ticks: float = 0.0
    has_displacement: bool = False
    close_price: float = 0.0
    metadata: dict = field(default_factory=dict)


def detect_mss(
    bar: Bar,
    bar_index: int,
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    config: dict,
    expected_direction: Literal["BULLISH", "BEARISH"] | None = None,
    displacement_event: "DisplacementEvent | None" = None,
) -> MSSEvent | None:
    """
    Detect Market Structure Shift on the current bar.

    MSS occurs when:
    - BULLISH MSS: Bar closes above a swing high
    - BEARISH MSS: Bar closes below a swing low

    Args:
        bar: Current bar to check
        bar_index: Index of the bar
        swing_highs: List of swing highs to check against
        swing_lows: List of swing lows to check against
        config: Configuration with tick_size
        expected_direction: If set, only detect MSS in this direction
        displacement_event: Optional displacement event for validation

    Returns:
        MSSEvent if MSS detected, None otherwise
    """
    tick_size = config.get("tick_size", 0.25)

    # Check for BULLISH MSS (break above swing high)
    if expected_direction in (None, "BULLISH"):
        for sh in sorted(swing_highs, key=lambda s: s.bar_index, reverse=True):
            # Only check recent swings
            if bar_index - sh.bar_index > config.get("mss_lookback_bars", 20):
                continue

            # Check if bar closes above swing high
            if bar.close > sh.price:
                break_distance = bar.close - sh.price
                break_ticks = break_distance / tick_size

                return MSSEvent(
                    direction="BULLISH",
                    broken_level=sh.price,
                    timestamp=bar.timestamp,
                    bar_index=bar_index,
                    reference_swing=sh,
                    break_size_ticks=break_ticks,
                    has_displacement=displacement_event is not None,
                    close_price=bar.close,
                    metadata={
                        "swing_bar_index": sh.bar_index,
                        "bars_since_swing": bar_index - sh.bar_index,
                    }
                )

    # Check for BEARISH MSS (break below swing low)
    if expected_direction in (None, "BEARISH"):
        for sl in sorted(swing_lows, key=lambda s: s.bar_index, reverse=True):
            # Only check recent swings
            if bar_index - sl.bar_index > config.get("mss_lookback_bars", 20):
                continue

            # Check if bar closes below swing low
            if bar.close < sl.price:
                break_distance = sl.price - bar.close
                break_ticks = break_distance / tick_size

                return MSSEvent(
                    direction="BEARISH",
                    broken_level=sl.price,
                    timestamp=bar.timestamp,
                    bar_index=bar_index,
                    reference_swing=sl,
                    break_size_ticks=break_ticks,
                    has_displacement=displacement_event is not None,
                    close_price=bar.close,
                    metadata={
                        "swing_bar_index": sl.bar_index,
                        "bars_since_swing": bar_index - sl.bar_index,
                    }
                )

    return None


def detect_mss_after_sweep(
    bar: Bar,
    bar_index: int,
    bars: list[Bar],
    swept_zone: "LiquidityZone",
    config: dict,
) -> MSSEvent | None:
    """
    Detect MSS that confirms a liquidity sweep.

    After sweeping SSL (lows) → Look for BULLISH MSS
    After sweeping BSL (highs) → Look for BEARISH MSS

    Args:
        bar: Current bar
        bar_index: Bar index
        bars: Bar history for swing detection
        swept_zone: The liquidity zone that was swept
        config: Configuration dictionary

    Returns:
        MSSEvent if confirming MSS found, None otherwise
    """
    swing_left = config.get("swing_left_bars", 3)
    swing_right = config.get("swing_right_bars", 1)
    lookback = config.get("lookback_bars", 20)

    # Get lookback bars for swing detection
    lookback_start = max(0, len(bars) - lookback)
    lookback_bars = bars[lookback_start:-1]

    # Determine expected direction based on sweep
    if swept_zone.zone_type == "SSL":
        # Swept sell side → expect bullish MSS
        expected = "BULLISH"
        swing_highs = find_swing_highs(lookback_bars, swing_left, swing_right)
        swing_lows = []
    else:
        # Swept buy side → expect bearish MSS
        expected = "BEARISH"
        swing_highs = []
        swing_lows = find_swing_lows(lookback_bars, swing_left, swing_right)

    return detect_mss(
        bar=bar,
        bar_index=bar_index,
        swing_highs=swing_highs,
        swing_lows=swing_lows,
        config=config,
        expected_direction=expected,
    )


def mss_confirms_displacement(
    mss: MSSEvent,
    displacement: "DisplacementEvent",
) -> bool:
    """
    Check if MSS confirms a displacement event.

    The MSS direction should match the displacement direction.

    Args:
        mss: The MSS event
        displacement: The displacement event

    Returns:
        True if MSS confirms displacement
    """
    return mss.direction == displacement.direction


def get_expected_mss_direction(
    sweep_direction: Literal["UP", "DOWN"] | None = None,
    liquidity_type: Literal["BSL", "SSL"] | None = None,
) -> Literal["BULLISH", "BEARISH"] | None:
    """
    Get expected MSS direction based on sweep/liquidity context.

    - Sweep DOWN (SSL) → BULLISH MSS
    - Sweep UP (BSL) → BEARISH MSS

    Args:
        sweep_direction: Direction of sweep
        liquidity_type: Type of liquidity swept

    Returns:
        Expected MSS direction
    """
    if sweep_direction:
        return "BULLISH" if sweep_direction == "DOWN" else "BEARISH"

    if liquidity_type:
        return "BULLISH" if liquidity_type == "SSL" else "BEARISH"

    return None
