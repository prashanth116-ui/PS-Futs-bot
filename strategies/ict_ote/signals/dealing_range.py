"""
Dealing Range and Liquidity Targets Module

Identifies the current dealing range (swing high to swing low) and
maps out liquidity targets above and below price. Used to set
runner targets at the nearest opposing liquidity level.
"""
from dataclasses import dataclass
from typing import Optional

from strategies.ict_sweep.signals.liquidity import (
    SwingPoint, find_swing_highs, find_swing_lows
)


@dataclass
class DealingRange:
    """The current swing-based dealing range."""
    high: float
    low: float
    high_index: int
    low_index: int
    equilibrium: float


@dataclass
class LiquidityTargets:
    """Liquidity levels above and below current price."""
    buy_side: list  # list[SwingPoint] — swing highs above (long targets)
    sell_side: list  # list[SwingPoint] — swing lows below (short targets)
    nearest_buy_side: Optional[SwingPoint]
    nearest_sell_side: Optional[SwingPoint]
    dealing_range: DealingRange


def find_dealing_range(bars, swing_lookback: int = 3, max_bars_back: int = 100) -> Optional[DealingRange]:
    """
    Find the current dealing range using swing highs and lows.

    Args:
        bars: List of price bars
        swing_lookback: Bars on each side for swing confirmation
        max_bars_back: Maximum bars to look back

    Returns:
        DealingRange or None if insufficient swings
    """
    if len(bars) < swing_lookback * 2 + 5:
        return None

    # Limit to max_bars_back
    analysis_bars = bars[-max_bars_back:] if len(bars) > max_bars_back else bars
    offset = len(bars) - len(analysis_bars)

    highs = find_swing_highs(analysis_bars, swing_lookback, max_swings=5)
    lows = find_swing_lows(analysis_bars, swing_lookback, max_swings=5)

    if not highs or not lows:
        return None

    # Use the most extreme swing points to define the range
    range_high_swing = max(highs, key=lambda s: s.price)
    range_low_swing = min(lows, key=lambda s: s.price)

    if range_high_swing.price <= range_low_swing.price:
        return None

    return DealingRange(
        high=range_high_swing.price,
        low=range_low_swing.price,
        high_index=range_high_swing.bar_index + offset,
        low_index=range_low_swing.bar_index + offset,
        equilibrium=(range_high_swing.price + range_low_swing.price) / 2.0,
    )


def find_liquidity_targets(
    bars,
    current_price: float,
    swing_lookback: int = 3,
    max_bars_back: int = 100,
) -> Optional[LiquidityTargets]:
    """
    Find liquidity targets above and below current price.

    Args:
        bars: List of price bars
        current_price: Current market price
        swing_lookback: Bars on each side for swing confirmation
        max_bars_back: Maximum bars to look back

    Returns:
        LiquidityTargets or None
    """
    dr = find_dealing_range(bars, swing_lookback, max_bars_back)
    if dr is None:
        return None

    analysis_bars = bars[-max_bars_back:] if len(bars) > max_bars_back else bars

    highs = find_swing_highs(analysis_bars, swing_lookback, max_swings=10)
    lows = find_swing_lows(analysis_bars, swing_lookback, max_swings=10)

    # Buy-side liquidity: swing highs above current price
    buy_side = sorted(
        [s for s in highs if s.price > current_price],
        key=lambda s: s.price
    )

    # Sell-side liquidity: swing lows below current price
    sell_side = sorted(
        [s for s in lows if s.price < current_price],
        key=lambda s: s.price,
        reverse=True
    )

    return LiquidityTargets(
        buy_side=buy_side,
        sell_side=sell_side,
        nearest_buy_side=buy_side[0] if buy_side else None,
        nearest_sell_side=sell_side[0] if sell_side else None,
        dealing_range=dr,
    )


def get_runner_target(targets: Optional[LiquidityTargets], direction: str) -> Optional[float]:
    """
    Get the runner target price from liquidity targets.

    BULLISH -> nearest buy-side liquidity (swing high above)
    BEARISH -> nearest sell-side liquidity (swing low below)

    Args:
        targets: LiquidityTargets object
        direction: 'BULLISH' or 'BEARISH'

    Returns:
        Target price or None
    """
    if targets is None:
        return None

    if direction == 'BULLISH' and targets.nearest_buy_side:
        return targets.nearest_buy_side.price
    elif direction == 'BEARISH' and targets.nearest_sell_side:
        return targets.nearest_sell_side.price

    return None
