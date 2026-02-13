"""
Pattern Detection Module

Template for creating pattern detectors.
Each detector should be self-contained and return dataclass objects.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from core.types import Bar


@dataclass
class PatternSignal:
    """
    Detected pattern signal.

    Customize fields for your specific pattern.
    """
    direction: str  # "BULLISH" or "BEARISH"
    pattern_type: str  # Name of the pattern
    price: float
    created_at: datetime
    strength: float = 1.0  # Pattern strength (0-1)
    bar_index: int = 0

    # Optional: Pattern-specific fields
    pattern_high: Optional[float] = None
    pattern_low: Optional[float] = None


def detect_patterns(bars: list[Bar], config: dict) -> list[PatternSignal]:
    """
    Detect patterns in price data.

    Args:
        bars: List of price bars
        config: Configuration parameters

    Returns:
        List of detected pattern signals
    """
    patterns = []

    if len(bars) < 3:
        return patterns

    # ===== EXAMPLE: Engulfing Pattern =====

    current = bars[-1]
    previous = bars[-2]

    # Bullish engulfing
    if (previous.close < previous.open and  # Previous bearish
        current.close > current.open and     # Current bullish
        current.open <= previous.close and   # Opens at/below prev close
        current.close >= previous.open):     # Closes at/above prev open

        patterns.append(PatternSignal(
            direction="BULLISH",
            pattern_type="engulfing",
            price=current.close,
            created_at=current.timestamp,
            strength=_calculate_strength(current, previous),
            bar_index=len(bars) - 1,
            pattern_high=current.high,
            pattern_low=min(current.low, previous.low)
        ))

    # Bearish engulfing
    if (previous.close > previous.open and  # Previous bullish
        current.close < current.open and     # Current bearish
        current.open >= previous.close and   # Opens at/above prev close
        current.close <= previous.open):     # Closes at/below prev open

        patterns.append(PatternSignal(
            direction="BEARISH",
            pattern_type="engulfing",
            price=current.close,
            created_at=current.timestamp,
            strength=_calculate_strength(current, previous),
            bar_index=len(bars) - 1,
            pattern_high=max(current.high, previous.high),
            pattern_low=current.low
        ))

    # ===== ADD MORE PATTERNS HERE =====
    # - Pin bars
    # - Inside bars
    # - Morning/evening star
    # - Double top/bottom
    # etc.

    return patterns


def _calculate_strength(current: Bar, previous: Bar) -> float:
    """Calculate pattern strength based on relative size."""
    current_body = abs(current.close - current.open)
    previous_body = abs(previous.close - previous.open)

    if previous_body == 0:
        return 0.5

    ratio = current_body / previous_body
    # Normalize to 0-1 range
    return min(1.0, ratio / 2.0)
