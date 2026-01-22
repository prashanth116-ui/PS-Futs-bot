"""
Displacement Detection Module

Displacement is a strong momentum candle that shows conviction and
intent in the market. It typically:
- Has a large body relative to its range
- Shows clear directional intent
- Often creates Fair Value Gaps

In ICT methodology, displacement after a sweep confirms the reversal.

Flow: sweepConfirmed → displacement → MSS/BOS
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from core.types import Bar


@dataclass
class DisplacementEvent:
    """
    Represents a confirmed displacement candle.

    Attributes:
        direction: "BULLISH" or "BEARISH"
        bar: The displacement bar
        bar_index: Index of the displacement bar
        body_size_ticks: Size of the candle body in ticks
        body_ratio: Body size / total range (0-1)
        timestamp: When displacement occurred
        created_fvg: Whether this displacement likely created an FVG
    """
    direction: Literal["BULLISH", "BEARISH"]
    bar: Bar
    bar_index: int
    body_size_ticks: float
    body_ratio: float
    timestamp: datetime
    created_fvg: bool = False
    metadata: dict = field(default_factory=dict)


def detect_displacement(
    bar: Bar,
    bar_index: int,
    config: dict,
    expected_direction: Literal["BULLISH", "BEARISH"] | None = None,
) -> DisplacementEvent | None:
    """
    Check if a bar qualifies as a displacement candle.

    Displacement criteria:
    1. Body size >= min_displacement_ticks
    2. Body ratio >= min_body_ratio (body/range)
    3. If expected_direction provided, must match

    Args:
        bar: The bar to check
        bar_index: Index of the bar
        config: Configuration with:
            - tick_size: Tick size for instrument
            - min_displacement_ticks: Minimum body size (default: 4)
            - min_body_ratio: Minimum body/range ratio (default: 0.6)
        expected_direction: If provided, only return if direction matches

    Returns:
        DisplacementEvent if displacement detected, None otherwise
    """
    tick_size = config.get("tick_size", 0.25)
    min_ticks = config.get("min_displacement_ticks", 4)
    min_ratio = config.get("min_body_ratio", 0.6)

    # Calculate body size
    body_size = bar.body_size
    body_ticks = body_size / tick_size

    # Check minimum body size
    if body_ticks < min_ticks:
        return None

    # Calculate body ratio
    if bar.range <= 0:
        return None

    body_ratio = body_size / bar.range

    # Check minimum ratio
    if body_ratio < min_ratio:
        return None

    # Determine direction
    direction: Literal["BULLISH", "BEARISH"] = "BULLISH" if bar.close > bar.open else "BEARISH"

    # Check expected direction
    if expected_direction and direction != expected_direction:
        return None

    return DisplacementEvent(
        direction=direction,
        bar=bar,
        bar_index=bar_index,
        body_size_ticks=body_ticks,
        body_ratio=body_ratio,
        timestamp=bar.timestamp,
        created_fvg=False,  # Will be set by caller if FVG detected
    )


def detect_displacement_with_fvg(
    bars: list[Bar],
    bar_index: int,
    config: dict,
    expected_direction: Literal["BULLISH", "BEARISH"] | None = None,
) -> DisplacementEvent | None:
    """
    Detect displacement and check if it created an FVG.

    Checks the last 3 bars for FVG formation during displacement.

    Args:
        bars: List of bars (needs at least 3)
        bar_index: Index of the current bar
        config: Configuration dictionary
        expected_direction: Expected direction filter

    Returns:
        DisplacementEvent with created_fvg flag set if applicable
    """
    if len(bars) < 3:
        return None

    current_bar = bars[-1]
    bar_minus_2 = bars[-3]

    # Check for displacement
    event = detect_displacement(current_bar, bar_index, config, expected_direction)

    if event is None:
        return None

    # Check if displacement created an FVG
    if event.direction == "BULLISH":
        # Bullish FVG: gap between bar[-3].high and bar[-1].low
        if current_bar.low > bar_minus_2.high:
            event.created_fvg = True
            event.metadata["fvg_low"] = bar_minus_2.high
            event.metadata["fvg_high"] = current_bar.low
    else:
        # Bearish FVG: gap between bar[-1].high and bar[-3].low
        if current_bar.high < bar_minus_2.low:
            event.created_fvg = True
            event.metadata["fvg_low"] = current_bar.high
            event.metadata["fvg_high"] = bar_minus_2.low

    return event


def get_expected_displacement_direction(
    sweep_direction: Literal["UP", "DOWN"] | None = None,
    liquidity_type: Literal["BSL", "SSL"] | None = None,
) -> Literal["BULLISH", "BEARISH"] | None:
    """
    Get expected displacement direction based on sweep/liquidity.

    - Sweep DOWN (took SSL) → Expect BULLISH displacement
    - Sweep UP (took BSL) → Expect BEARISH displacement

    Args:
        sweep_direction: Direction of the sweep
        liquidity_type: Type of liquidity that was swept

    Returns:
        Expected displacement direction or None
    """
    if sweep_direction:
        return "BULLISH" if sweep_direction == "DOWN" else "BEARISH"

    if liquidity_type:
        return "BULLISH" if liquidity_type == "SSL" else "BEARISH"

    return None
