"""
Smart Money Technique (SMT) Divergence Detection

Detects divergence between correlated instruments:
- Bearish SMT: Primary makes new high, correlated fails to
- Bullish SMT: Primary makes new low, correlated fails to

SMT divergence confirms institutional activity — when correlated markets
diverge at key levels, it signals smart money is positioning.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


SMT_PAIRS = {
    'ES': 'NQ', 'NQ': 'ES',
    'MES': 'MNQ', 'MNQ': 'MES',
    'SPY': 'QQQ', 'QQQ': 'SPY',
}


@dataclass
class SMTDivergence:
    """Represents a detected SMT divergence event."""
    divergence_type: str         # 'BULLISH' or 'BEARISH'
    primary_symbol: str
    correlated_symbol: str
    primary_price: float
    correlated_price: float
    bar_index: int
    timestamp: datetime


def get_correlated_symbol(symbol: str) -> Optional[str]:
    """Get the correlated symbol for SMT analysis."""
    return SMT_PAIRS.get(symbol.upper())


def align_bars_by_timestamp(
    primary_bars,
    correlated_bars,
    tolerance_seconds: int = 60,
) -> tuple[list, list]:
    """
    Align two bar lists by timestamp within a tolerance window.

    Returns two lists of equal length containing only bars that have
    matching timestamps in both series.

    Args:
        primary_bars: Primary instrument bars
        correlated_bars: Correlated instrument bars
        tolerance_seconds: Maximum time difference for a match

    Returns:
        Tuple of (aligned_primary, aligned_correlated)
    """
    if not primary_bars or not correlated_bars:
        return [], []

    aligned_primary = []
    aligned_correlated = []

    corr_idx = 0
    for p_bar in primary_bars:
        p_ts = p_bar.timestamp.timestamp() if hasattr(p_bar.timestamp, 'timestamp') else 0

        # Advance correlated index to find closest match
        while corr_idx < len(correlated_bars) - 1:
            c_ts = correlated_bars[corr_idx].timestamp.timestamp() \
                if hasattr(correlated_bars[corr_idx].timestamp, 'timestamp') else 0
            c_ts_next = correlated_bars[corr_idx + 1].timestamp.timestamp() \
                if hasattr(correlated_bars[corr_idx + 1].timestamp, 'timestamp') else 0

            if abs(c_ts_next - p_ts) < abs(c_ts - p_ts):
                corr_idx += 1
            else:
                break

        if corr_idx < len(correlated_bars):
            c_ts = correlated_bars[corr_idx].timestamp.timestamp() \
                if hasattr(correlated_bars[corr_idx].timestamp, 'timestamp') else 0
            if abs(c_ts - p_ts) <= tolerance_seconds:
                aligned_primary.append(p_bar)
                aligned_correlated.append(correlated_bars[corr_idx])

    return aligned_primary, aligned_correlated


def detect_smt_divergence(
    primary_bars,
    correlated_bars,
    primary_symbol: str = '',
    correlated_symbol: str = '',
    lookback: int = 20,
) -> Optional[SMTDivergence]:
    """
    Detect SMT divergence between two correlated instruments.

    Bearish SMT: Primary makes new high within lookback, correlated does NOT.
    Bullish SMT: Primary makes new low within lookback, correlated does NOT.

    Args:
        primary_bars: Aligned primary instrument bars
        correlated_bars: Aligned correlated instrument bars
        primary_symbol: Primary symbol name
        correlated_symbol: Correlated symbol name
        lookback: Number of bars to check for new highs/lows

    Returns:
        SMTDivergence if detected, None otherwise
    """
    if len(primary_bars) < lookback + 1 or len(correlated_bars) < lookback + 1:
        return None

    # Align bars by timestamp
    p_aligned, c_aligned = align_bars_by_timestamp(primary_bars, correlated_bars)

    if len(p_aligned) < lookback + 1:
        return None

    # Check recent bars for divergence
    recent_p = p_aligned[-lookback:]
    recent_c = c_aligned[-lookback:]

    # Previous highs/lows (excluding last bar)
    prev_p_high = max(b.high for b in recent_p[:-1])
    prev_p_low = min(b.low for b in recent_p[:-1])
    prev_c_high = max(b.high for b in recent_c[:-1])
    prev_c_low = min(b.low for b in recent_c[:-1])

    current_p = recent_p[-1]
    current_c = recent_c[-1]

    # Bearish SMT: primary new high, correlated fails
    if current_p.high > prev_p_high and current_c.high <= prev_c_high:
        return SMTDivergence(
            divergence_type='BEARISH',
            primary_symbol=primary_symbol,
            correlated_symbol=correlated_symbol,
            primary_price=current_p.high,
            correlated_price=current_c.high,
            bar_index=len(primary_bars) - 1,
            timestamp=current_p.timestamp,
        )

    # Bullish SMT: primary new low, correlated fails
    if current_p.low < prev_p_low and current_c.low >= prev_c_low:
        return SMTDivergence(
            divergence_type='BULLISH',
            primary_symbol=primary_symbol,
            correlated_symbol=correlated_symbol,
            primary_price=current_p.low,
            correlated_price=current_c.low,
            bar_index=len(primary_bars) - 1,
            timestamp=current_p.timestamp,
        )

    return None
