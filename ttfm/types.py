"""
TTFM-specific data types.

Dataclasses for the TTrades Fractal Model strategy:
- SwingPoint: Fractal swing high/low
- CandleLabel: C1/C2/C3/C4 candle numbering
- CISD: Change in State of Delivery
- Bias: HTF directional bias
- POI: Point of Interest (FVG, swing H/L)
- TTFMSignal: Complete trade signal with all context
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class SwingPoint:
    """Fractal swing high or low detected on any timeframe."""
    price: float
    timestamp: datetime
    bar_index: int
    swing_type: Literal["HIGH", "LOW"]
    timeframe: str = ""


@dataclass
class CandleLabel:
    """Candle label in the C1/C2/C3/C4 numbering system.

    C1 = pre-swing (preceding trend)
    C2 = swing point (reversal bar)
    C3 = continuation (expands in new direction)
    C4 = expansion (further continuation)
    """
    bar_index: int
    label: Literal["C1", "C2", "C3", "C4"]
    direction: Literal["BULLISH", "BEARISH"]
    swing_point: SwingPoint | None = None


@dataclass
class CISD:
    """Change in State of Delivery — confirms trend shift.

    Bearish CISD: price creates higher high then closes below the candles
                  that created that high.
    Bullish CISD: price creates lower low then closes above the candles
                  that created that low.
    """
    direction: Literal["BULLISH", "BEARISH"]
    bar_index: int
    timestamp: datetime
    price: float          # Close that confirmed the shift
    swing_price: float    # The high/low that was created before shift
    ob_high: float        # Order block high
    ob_low: float         # Order block low


@dataclass
class Bias:
    """HTF directional bias from daily candle closure analysis."""
    direction: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    bias_type: Literal["CONTINUATION", "REVERSAL"]
    reason: str


@dataclass
class POI:
    """Point of Interest — zone where reversals are likely.

    Can be an FVG, a swing high/low, or an order block.
    """
    poi_type: Literal["FVG", "SWING", "ORDER_BLOCK"]
    high: float
    low: float
    direction: Literal["BULLISH", "BEARISH"]
    bar_index: int
    timestamp: datetime


@dataclass
class TTFMSignal:
    """Complete TTFM trade signal with multi-timeframe context."""
    htf_bias: Bias
    mtf_swing: SwingPoint
    ltf_cisd: CISD
    candle_label: CandleLabel
    direction: Literal["BULLISH", "BEARISH"]
    entry_price: float
    stop_price: float         # Beyond protected swing (C2 level)
    risk_pts: float
    targets: list[float] = field(default_factory=list)
    entry_bar_index: int = 0
    entry_timestamp: datetime | None = None
    reason: str = ""
