"""
Liquidity Zone Detection Module

Identifies and tracks liquidity zones where stop orders likely rest.
In ICT methodology, liquidity exists:
- Above swing highs (buy stops)
- Below swing lows (sell stops)

Smart money targets these zones to fill large orders before reversing.

Liquidity Flow:
    swingFound → liquidityDefined → sweepConfirmed
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from core.types import Bar
from strategies.ict.signals.sweep import SwingPoint


@dataclass
class LiquidityZone:
    """
    Represents a defined liquidity zone.

    Attributes:
        zone_type: "BSL" (Buy Side Liquidity - above highs) or
                   "SSL" (Sell Side Liquidity - below lows)
        price: The price level of the liquidity zone
        swing_point: The underlying swing point
        strength: How many times this level has been tested (more = stronger)
        swept: Whether this zone has been swept
        swept_at: Timestamp when swept
        swept_bar_index: Bar index when swept
    """
    zone_type: Literal["BSL", "SSL"]  # Buy Side / Sell Side Liquidity
    price: float
    swing_point: SwingPoint
    strength: int = 1
    swept: bool = False
    swept_at: datetime | None = None
    swept_bar_index: int | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def is_buy_side(self) -> bool:
        """True if this is buy side liquidity (above price)."""
        return self.zone_type == "BSL"

    @property
    def is_sell_side(self) -> bool:
        """True if this is sell side liquidity (below price)."""
        return self.zone_type == "SSL"


def define_liquidity_zones(
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    config: dict,
) -> list[LiquidityZone]:
    """
    Convert swing points into defined liquidity zones.

    Buy Side Liquidity (BSL): Above swing highs - buy stops rest here
    Sell Side Liquidity (SSL): Below swing lows - sell stops rest here

    Args:
        swing_highs: List of identified swing highs
        swing_lows: List of identified swing lows
        config: Configuration dictionary

    Returns:
        List of LiquidityZone objects
    """
    zones: list[LiquidityZone] = []
    tick_size = config.get("tick_size", 0.25)
    cluster_ticks = config.get("liquidity_cluster_ticks", 4)
    cluster_threshold = cluster_ticks * tick_size

    # Create BSL zones from swing highs
    for sh in swing_highs:
        # Check if there's already a zone near this level
        existing = None
        for z in zones:
            if z.zone_type == "BSL" and abs(z.price - sh.price) <= cluster_threshold:
                existing = z
                break

        if existing:
            # Cluster with existing zone - increase strength
            existing.strength += 1
            # Use the higher price as the zone level
            if sh.price > existing.price:
                existing.price = sh.price
                existing.swing_point = sh
        else:
            # Create new zone
            zones.append(LiquidityZone(
                zone_type="BSL",
                price=sh.price,
                swing_point=sh,
                strength=1,
            ))

    # Create SSL zones from swing lows
    for sl in swing_lows:
        existing = None
        for z in zones:
            if z.zone_type == "SSL" and abs(z.price - sl.price) <= cluster_threshold:
                existing = z
                break

        if existing:
            existing.strength += 1
            if sl.price < existing.price:
                existing.price = sl.price
                existing.swing_point = sl
        else:
            zones.append(LiquidityZone(
                zone_type="SSL",
                price=sl.price,
                swing_point=sl,
                strength=1,
            ))

    return zones


def check_liquidity_sweep(
    bar: Bar,
    bar_index: int,
    zone: LiquidityZone,
    config: dict,
) -> bool:
    """
    Check if a bar sweeps a liquidity zone.

    BSL sweep: Price goes ABOVE the zone then reverses (closes below)
    SSL sweep: Price goes BELOW the zone then reverses (closes above)

    Args:
        bar: The bar to check
        bar_index: Index of the bar
        zone: The liquidity zone to check
        config: Configuration dictionary

    Returns:
        True if zone was swept, False otherwise
    """
    if zone.swept:
        return False

    tick_size = config.get("tick_size", 0.25)
    sweep_buffer = config.get("sweep_buffer_ticks", 1) * tick_size

    if zone.zone_type == "BSL":
        # Buy side liquidity sweep:
        # - High goes above the zone (takes out buy stops)
        # - Close is below the zone (reversal)
        if bar.high >= zone.price + sweep_buffer and bar.close < zone.price:
            zone.swept = True
            zone.swept_at = bar.timestamp
            zone.swept_bar_index = bar_index
            return True

    else:  # SSL
        # Sell side liquidity sweep:
        # - Low goes below the zone (takes out sell stops)
        # - Close is above the zone (reversal)
        if bar.low <= zone.price - sweep_buffer and bar.close > zone.price:
            zone.swept = True
            zone.swept_at = bar.timestamp
            zone.swept_bar_index = bar_index
            return True

    return False


def get_nearest_liquidity(
    zones: list[LiquidityZone],
    current_price: float,
    zone_type: Literal["BSL", "SSL"] | None = None,
    unswept_only: bool = True,
) -> LiquidityZone | None:
    """
    Find the nearest liquidity zone to current price.

    Args:
        zones: List of liquidity zones
        current_price: Current market price
        zone_type: Filter by type (BSL/SSL) or None for any
        unswept_only: If True, only return unswept zones

    Returns:
        Nearest LiquidityZone or None
    """
    candidates = zones

    if zone_type:
        candidates = [z for z in candidates if z.zone_type == zone_type]

    if unswept_only:
        candidates = [z for z in candidates if not z.swept]

    if not candidates:
        return None

    return min(candidates, key=lambda z: abs(z.price - current_price))


def get_liquidity_for_bias(
    zones: list[LiquidityZone],
    current_price: float,
    bias: Literal["BULLISH", "BEARISH"],
) -> LiquidityZone | None:
    """
    Get the liquidity zone that would be targeted for the given bias.

    BULLISH bias: Look for SSL below price (sweep lows then go up)
    BEARISH bias: Look for BSL above price (sweep highs then go down)

    Args:
        zones: List of liquidity zones
        current_price: Current price
        bias: Expected direction

    Returns:
        Target liquidity zone or None
    """
    if bias == "BULLISH":
        # Bullish = sweep lows first (SSL below price)
        ssl_zones = [z for z in zones if z.zone_type == "SSL" and z.price < current_price and not z.swept]
        if ssl_zones:
            return max(ssl_zones, key=lambda z: z.price)  # Nearest SSL below
    else:
        # Bearish = sweep highs first (BSL above price)
        bsl_zones = [z for z in zones if z.zone_type == "BSL" and z.price > current_price and not z.swept]
        if bsl_zones:
            return min(bsl_zones, key=lambda z: z.price)  # Nearest BSL above

    return None
