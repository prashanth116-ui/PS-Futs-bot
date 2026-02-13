"""
Market Structure Shift (MSS) Detection Module

MSS is a break of market structure that confirms a potential reversal.
- Bullish MSS: Price breaks above a recent swing high (confirms bullish bias)
- Bearish MSS: Price breaks below a recent swing low (confirms bearish bias)

Used on LTF (1m) to confirm entries after HTF setup is complete.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from strategies.ict_sweep.signals.liquidity import is_swing_high, is_swing_low


@dataclass
class MSS:
    """Represents a Market Structure Shift."""
    mss_type: str  # 'BULLISH' or 'BEARISH'
    break_price: float  # Price level that was broken
    confirmation_price: float  # Price that confirmed the break
    bar_index: int
    timestamp: datetime


def find_recent_swing_high(bars, end_index: int, lookback: int = 10, swing_strength: int = 2) -> Optional[tuple]:
    """
    Find the most recent swing high before end_index.

    Args:
        bars: List of price bars
        end_index: Search backwards from this index
        lookback: How many bars back to search
        swing_strength: Bars on each side to confirm swing

    Returns:
        Tuple of (bar_index, price) or None
    """
    start = max(swing_strength, end_index - lookback)

    for i in range(end_index - swing_strength - 1, start - 1, -1):
        if is_swing_high(bars, i, swing_strength):
            return (i, bars[i].high)

    return None


def find_recent_swing_low(bars, end_index: int, lookback: int = 10, swing_strength: int = 2) -> Optional[tuple]:
    """
    Find the most recent swing low before end_index.

    Args:
        bars: List of price bars
        end_index: Search backwards from this index
        lookback: How many bars back to search
        swing_strength: Bars on each side to confirm swing

    Returns:
        Tuple of (bar_index, price) or None
    """
    start = max(swing_strength, end_index - lookback)

    for i in range(end_index - swing_strength - 1, start - 1, -1):
        if is_swing_low(bars, i, swing_strength):
            return (i, bars[i].low)

    return None


def detect_mss(
    bars,
    direction: str,
    lookback: int = 10,
    swing_strength: int = 2,
    debug: bool = False
) -> Optional[MSS]:
    """
    Detect if a Market Structure Shift occurred on the current bar.

    Args:
        bars: List of price bars
        direction: Expected direction - 'BULLISH' or 'BEARISH'
        lookback: How many bars back to find swing
        swing_strength: Bars on each side to confirm swing
        debug: Print debug info

    Returns:
        MSS object if detected, None otherwise
    """
    if len(bars) < lookback + swing_strength:
        if debug:
            print(f"        MSS: Not enough bars ({len(bars)} < {lookback + swing_strength})")
        return None

    current_bar = bars[-1]
    bar_index = len(bars) - 1

    if direction == 'BULLISH':
        # Look for break above recent swing high
        swing = find_recent_swing_high(bars, bar_index, lookback, swing_strength)
        if debug:
            print(f"        MSS BULLISH: swing={swing}, close={current_bar.close:.2f}")
        if swing:
            swing_idx, swing_price = swing
            # Current bar must close above the swing high
            if current_bar.close > swing_price:
                return MSS(
                    mss_type='BULLISH',
                    break_price=swing_price,
                    confirmation_price=current_bar.close,
                    bar_index=bar_index,
                    timestamp=current_bar.timestamp
                )

    elif direction == 'BEARISH':
        # Look for break below recent swing low
        swing = find_recent_swing_low(bars, bar_index, lookback, swing_strength)
        if debug:
            print(f"        MSS BEARISH: swing={swing}, close={current_bar.close:.2f}")
        if swing:
            swing_idx, swing_price = swing
            # Current bar must close below the swing low
            if current_bar.close < swing_price:
                return MSS(
                    mss_type='BEARISH',
                    break_price=swing_price,
                    confirmation_price=current_bar.close,
                    bar_index=bar_index,
                    timestamp=current_bar.timestamp
                )

    return None


def detect_mss_any_direction(
    bars,
    lookback: int = 10,
    swing_strength: int = 2
) -> Optional[MSS]:
    """
    Detect MSS in either direction.

    Args:
        bars: List of price bars
        lookback: How many bars back to find swing
        swing_strength: Bars on each side to confirm swing

    Returns:
        MSS object if detected, None otherwise
    """
    # Try bullish first
    mss = detect_mss(bars, 'BULLISH', lookback, swing_strength)
    if mss:
        return mss

    # Try bearish
    return detect_mss(bars, 'BEARISH', lookback, swing_strength)


def is_mss_valid(mss: MSS, expected_direction: str) -> bool:
    """
    Validate that MSS matches expected direction.

    Args:
        mss: MSS object
        expected_direction: 'BULLISH' or 'BEARISH'

    Returns:
        True if MSS direction matches expected
    """
    if mss is None:
        return False
    return mss.mss_type == expected_direction
