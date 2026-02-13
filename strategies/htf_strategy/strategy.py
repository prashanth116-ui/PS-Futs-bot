"""
HTF (Higher Time Frame) Strategy

Multi-timeframe strategy that uses higher timeframe for bias
and lower timeframe for precise entries.

HTF Analysis (15m/1h):
- Trend direction (EMA/structure)
- Key levels (support/resistance)
- Supply/demand zones

LTF Entry (3m/5m):
- Entry patterns aligned with HTF bias
- Tight stop placement
- Trend continuation setups

V10.8 Hybrid Filter System:
- 2 mandatory filters (DI direction)
- 2/3 optional filters (displacement, ADX, EMA alignment)
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from core.types import Bar
from strategies.htf_strategy.filters.trend import (
    calculate_adx, calculate_displacement, calculate_avg_body_size
)


@dataclass
class KeyLevel:
    """Support/Resistance level from HTF."""
    price: float
    level_type: str  # "SUPPORT", "RESISTANCE", "SUPPLY", "DEMAND"
    strength: int = 1  # Number of touches
    created_at: Optional[datetime] = None
    broken: bool = False


@dataclass
class HTFBias:
    """Higher timeframe bias/context."""
    direction: str  # "BULLISH", "BEARISH", "NEUTRAL"
    trend_strength: float  # 0-1
    key_levels: list[KeyLevel] = field(default_factory=list)
    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None


@dataclass
class TradeSetup:
    """Valid trade setup."""
    direction: str
    entry_price: float
    stop_price: float
    target_price: float
    htf_bias: str
    entry_reason: str
    bar_index: int


class HTFStrategy:
    """
    Higher Time Frame Strategy

    Uses multi-timeframe analysis:
    - HTF (15m/1h) for bias and key levels
    - LTF (3m/5m) for entry timing

    Entry Rules:
    1. HTF bias must be clear (BULLISH or BEARISH)
    2. Price near HTF key level (support for long, resistance for short)
    3. LTF entry pattern (rejection, engulfing, break & retest)
    4. Stop below/above key level
    5. Target at next HTF level or fixed R multiple
    """

    def __init__(self, config: dict):
        self.config = config

        # Instrument
        self.symbol = config.get('symbol', 'ES')
        self.tick_size = config.get('tick_size', 0.25)
        self.tick_value = config.get('tick_value', 12.50)
        self.contracts = config.get('contracts', 3)

        # Timeframes
        self.htf_interval = config.get('htf_interval', '15m')
        self.ltf_interval = config.get('ltf_interval', '3m')

        # HTF Analysis
        self.htf_ema_fast = config.get('htf_ema_fast', 20)
        self.htf_ema_slow = config.get('htf_ema_slow', 50)
        self.swing_lookback = config.get('swing_lookback', 10)
        self.level_tolerance_ticks = config.get('level_tolerance_ticks', 10)

        # Entry
        self.stop_buffer_ticks = config.get('stop_buffer_ticks', 4)
        self.min_rr_ratio = config.get('min_rr_ratio', 2.0)

        # Risk
        self.max_losses_per_day = config.get('max_losses_per_day', 2)

        # V10.8 Hybrid Filter Settings
        self.displacement_threshold = config.get('displacement_threshold', 1.0)
        self.min_adx = config.get('min_adx', 11)
        self.high_displacement_override = config.get('high_displacement_override', 3.0)
        self.high_displacement_min_adx = config.get('high_displacement_min_adx', 10)

        # State
        self.htf_bars: list[Bar] = []
        self.ltf_bars: list[Bar] = []
        self.htf_bias: Optional[HTFBias] = None
        self.daily_losses = 0
        self.avg_body_size: float = 0.0

    def reset_daily(self):
        """Reset for new trading day."""
        self.htf_bars = []
        self.ltf_bars = []
        self.htf_bias = None
        self.daily_losses = 0
        self.avg_body_size = 0.0

    def update_htf(self, bars: list[Bar]):
        """
        Update HTF analysis with new bars.

        Call this with 15m/1h bars to set the bias.
        """
        self.htf_bars = bars
        self.htf_bias = self._analyze_htf_bias()

    def update_ltf(self, bar: Bar) -> Optional[TradeSetup]:
        """
        Process new LTF bar and check for entry.

        Args:
            bar: New 3m/5m bar

        Returns:
            TradeSetup if valid entry found, None otherwise
        """
        self.ltf_bars.append(bar)

        # Check circuit breaker
        if self.daily_losses >= self.max_losses_per_day:
            return None

        # Need HTF bias
        if not self.htf_bias or self.htf_bias.direction == "NEUTRAL":
            return None

        # Need enough LTF bars
        if len(self.ltf_bars) < 20:
            return None

        # Check for entry setup
        return self._check_entry()

    def _analyze_htf_bias(self) -> HTFBias:
        """Analyze HTF bars to determine bias and key levels."""
        if len(self.htf_bars) < self.htf_ema_slow:
            return HTFBias(direction="NEUTRAL", trend_strength=0.0)

        closes = [b.close for b in self.htf_bars]

        # Calculate EMAs
        fast_ema = self._calculate_ema(closes, self.htf_ema_fast)
        slow_ema = self._calculate_ema(closes, self.htf_ema_slow)

        # Determine trend
        if fast_ema[-1] > slow_ema[-1]:
            direction = "BULLISH"
            separation = (fast_ema[-1] - slow_ema[-1]) / slow_ema[-1] * 100
            trend_strength = min(1.0, separation / 0.5)
        elif fast_ema[-1] < slow_ema[-1]:
            direction = "BEARISH"
            separation = (slow_ema[-1] - fast_ema[-1]) / slow_ema[-1] * 100
            trend_strength = min(1.0, separation / 0.5)
        else:
            direction = "NEUTRAL"
            trend_strength = 0.0

        # Find key levels
        key_levels = self._find_key_levels()

        # Find nearest support/resistance
        current_price = self.htf_bars[-1].close
        supports = [l for l in key_levels if l.price < current_price]
        resistances = [l for l in key_levels if l.price > current_price]

        nearest_support = max(l.price for l in supports) if supports else None
        nearest_resistance = min(l.price for l in resistances) if resistances else None

        return HTFBias(
            direction=direction,
            trend_strength=trend_strength,
            key_levels=key_levels,
            nearest_support=nearest_support,
            nearest_resistance=nearest_resistance
        )

    def _find_key_levels(self) -> list[KeyLevel]:
        """Find support/resistance levels from HTF swing points."""
        if len(self.htf_bars) < self.swing_lookback * 2:
            return []

        levels = []
        lookback = self.swing_lookback

        for i in range(lookback, len(self.htf_bars) - lookback):
            bar = self.htf_bars[i]

            # Check for swing high (resistance)
            is_swing_high = all(
                bar.high >= self.htf_bars[i + j].high
                for j in range(-lookback, lookback + 1) if j != 0
            )
            if is_swing_high:
                levels.append(KeyLevel(
                    price=bar.high,
                    level_type="RESISTANCE",
                    created_at=bar.timestamp
                ))

            # Check for swing low (support)
            is_swing_low = all(
                bar.low <= self.htf_bars[i + j].low
                for j in range(-lookback, lookback + 1) if j != 0
            )
            if is_swing_low:
                levels.append(KeyLevel(
                    price=bar.low,
                    level_type="SUPPORT",
                    created_at=bar.timestamp
                ))

        # Merge nearby levels and count touches
        merged = self._merge_levels(levels)
        return merged

    def _merge_levels(self, levels: list[KeyLevel]) -> list[KeyLevel]:
        """Merge levels within tolerance and count touches."""
        if not levels:
            return []

        tolerance = self.level_tolerance_ticks * self.tick_size
        merged = []

        for level in sorted(levels, key=lambda x: x.price):
            found = False
            for m in merged:
                if abs(m.price - level.price) <= tolerance:
                    m.price = (m.price + level.price) / 2
                    m.strength += 1
                    found = True
                    break

            if not found:
                merged.append(KeyLevel(
                    price=level.price,
                    level_type=level.level_type,
                    strength=1,
                    created_at=level.created_at
                ))

        return merged

    def _check_entry(self) -> Optional[TradeSetup]:
        """Check for valid entry setup on LTF."""
        current_bar = self.ltf_bars[-1]
        current_price = current_bar.close

        tolerance = self.level_tolerance_ticks * self.tick_size

        # LONG: Price near support in bullish bias
        if self.htf_bias.direction == "BULLISH" and self.htf_bias.nearest_support:
            support = self.htf_bias.nearest_support

            if abs(current_price - support) <= tolerance:
                pattern = self._check_bullish_pattern()
                if pattern:
                    # V10.8 Hybrid Filter Check
                    filter_pass, filter_details = self._check_hybrid_filters("LONG")
                    if not filter_pass:
                        return None

                    stop = support - (self.stop_buffer_ticks * self.tick_size)
                    risk = current_price - stop

                    if self.htf_bias.nearest_resistance:
                        target = self.htf_bias.nearest_resistance
                    else:
                        target = current_price + (risk * self.min_rr_ratio)

                    reward = target - current_price
                    if reward / risk >= self.min_rr_ratio:
                        return TradeSetup(
                            direction="LONG",
                            entry_price=current_price,
                            stop_price=stop,
                            target_price=target,
                            htf_bias="BULLISH",
                            entry_reason=pattern,
                            bar_index=len(self.ltf_bars) - 1
                        )

        # SHORT: Price near resistance in bearish bias
        if self.htf_bias.direction == "BEARISH" and self.htf_bias.nearest_resistance:
            resistance = self.htf_bias.nearest_resistance

            if abs(current_price - resistance) <= tolerance:
                pattern = self._check_bearish_pattern()
                if pattern:
                    # V10.8 Hybrid Filter Check
                    filter_pass, filter_details = self._check_hybrid_filters("SHORT")
                    if not filter_pass:
                        return None

                    stop = resistance + (self.stop_buffer_ticks * self.tick_size)
                    risk = stop - current_price

                    if self.htf_bias.nearest_support:
                        target = self.htf_bias.nearest_support
                    else:
                        target = current_price - (risk * self.min_rr_ratio)

                    reward = current_price - target
                    if reward / risk >= self.min_rr_ratio:
                        return TradeSetup(
                            direction="SHORT",
                            entry_price=current_price,
                            stop_price=stop,
                            target_price=target,
                            htf_bias="BEARISH",
                            entry_reason=pattern,
                            bar_index=len(self.ltf_bars) - 1
                        )

        return None

    def _check_bullish_pattern(self) -> Optional[str]:
        """Check for bullish entry pattern on LTF."""
        if len(self.ltf_bars) < 3:
            return None

        current = self.ltf_bars[-1]
        prev = self.ltf_bars[-2]

        # Bullish engulfing
        if (prev.close < prev.open and
            current.close > current.open and
            current.close > prev.open and
            current.open <= prev.close):
            return "bullish_engulfing"

        # Hammer/pin bar
        body = abs(current.close - current.open)
        lower_wick = min(current.open, current.close) - current.low
        upper_wick = current.high - max(current.open, current.close)

        if lower_wick > body * 2 and upper_wick < body:
            return "hammer"

        if lower_wick > body * 1.5:
            return "bullish_rejection"

        return None

    def _check_bearish_pattern(self) -> Optional[str]:
        """Check for bearish entry pattern on LTF."""
        if len(self.ltf_bars) < 3:
            return None

        current = self.ltf_bars[-1]
        prev = self.ltf_bars[-2]

        # Bearish engulfing
        if (prev.close > prev.open and
            current.close < current.open and
            current.close < prev.open and
            current.open >= prev.close):
            return "bearish_engulfing"

        # Shooting star
        body = abs(current.close - current.open)
        lower_wick = min(current.open, current.close) - current.low
        upper_wick = current.high - max(current.open, current.close)

        if upper_wick > body * 2 and lower_wick < body:
            return "shooting_star"

        if upper_wick > body * 1.5:
            return "bearish_rejection"

        return None

    def _calculate_ema(self, prices: list[float], period: int) -> list[float]:
        """Calculate EMA."""
        if len(prices) < period:
            return []
        multiplier = 2 / (period + 1)
        ema = [sum(prices[:period]) / period]
        for price in prices[period:]:
            ema.append((price - ema[-1]) * multiplier + ema[-1])
        return ema

    def on_trade_result(self, pnl: float):
        """Track trade result."""
        if pnl < 0:
            self.daily_losses += 1

    def _check_hybrid_filters(self, direction: str) -> tuple[bool, dict]:
        """
        V10.8 Hybrid Filter System.

        MANDATORY (must pass):
        - DI Direction: +DI > -DI for LONG, -DI > +DI for SHORT

        OPTIONAL (2 of 3 must pass):
        - Displacement: >= threshold * average body
        - ADX: >= min_adx (or high_displacement_min_adx if 3x displacement)
        - EMA Alignment: EMA20 vs EMA50

        Returns:
            Tuple of (passes, details_dict)
        """
        is_long = direction == "LONG"
        current_bar = self.ltf_bars[-1]

        # Update avg body size if not set
        if self.avg_body_size <= 0 and len(self.ltf_bars) >= 20:
            self.avg_body_size = calculate_avg_body_size(self.ltf_bars[:50])

        # Calculate ADX/DI
        adx, plus_di, minus_di = calculate_adx(self.ltf_bars)

        # Calculate EMAs
        closes = [b.close for b in self.ltf_bars]
        ema_fast = self._calculate_ema(closes, self.htf_ema_fast)
        ema_slow = self._calculate_ema(closes, self.htf_ema_slow)

        # === MANDATORY: DI Direction ===
        if adx > 0:
            di_ok = (plus_di > minus_di) if is_long else (minus_di > plus_di)
            if not di_ok:
                return False, {'reason': 'DI_DIRECTION_FAIL'}
        else:
            di_ok = True

        # === OPTIONAL FILTERS (2 of 3 must pass) ===
        body = abs(current_bar.close - current_bar.open)

        # 1. Displacement check
        disp_ok = body >= self.avg_body_size * self.displacement_threshold if self.avg_body_size > 0 else True

        # 2. ADX check (with high displacement override)
        high_disp = body >= self.avg_body_size * self.high_displacement_override if self.avg_body_size > 0 else False
        min_adx = self.high_displacement_min_adx if high_disp else self.min_adx
        adx_ok = adx >= min_adx if adx > 0 else True

        # 3. EMA Alignment check
        if ema_fast and ema_slow:
            ema_ok = (ema_fast[-1] > ema_slow[-1]) if is_long else (ema_fast[-1] < ema_slow[-1])
        else:
            ema_ok = True

        # Count optional filters passed
        optional_passed = sum([disp_ok, adx_ok, ema_ok])

        details = {
            'adx': round(adx, 1),
            'plus_di': round(plus_di, 1),
            'minus_di': round(minus_di, 1),
            'disp_ok': disp_ok,
            'adx_ok': adx_ok,
            'ema_ok': ema_ok,
            'optional_passed': optional_passed,
        }

        if optional_passed < 2:
            details['reason'] = f'OPTIONAL_FAIL ({optional_passed}/3)'
            return False, details

        details['reason'] = 'PASS'
        return True, details
