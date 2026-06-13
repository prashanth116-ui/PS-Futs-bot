"""
Elliott Wave Detector — Phase 1 (Foundation)

Ports core logic from Pine Script V2 (tradingview/elliott_wave_detector.pine)
to Python for use in the backtesting/live trading pipeline.

Phase 1 scope:
  - Zigzag construction (build_zigzag)
  - Impulse pattern detection via 3 cardinal rules + W5 rule (check_impulse_rules)
  - Enrichment with confidence scoring (enrich_pattern)
  - Invalidation checking (check_invalidation)

NOT in Phase 1: ABC correction, Fibonacci targets, multi-timeframe, trading signals.

Usage:
    from strategies.ict.signals.elliott_wave import detect_elliott_waves

    result = detect_elliott_waves(bars, scales=[4, 8, 16])
    for p in result.valid_patterns:
        print(f"{p.direction_str} impulse, confidence={p.confidence}%")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from core.types import Bar
from strategies.ict.signals.sweep import find_swing_highs, find_swing_lows


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class ZigzagPoint:
    """A single pivot in the alternating zigzag."""

    price: float
    bar_index: int
    timestamp: datetime
    direction: int  # +1 = high, -1 = low
    rsi: float | None = None
    volume: float | None = None


@dataclass
class WavePoints:
    """The 6 wave points (W0-W5) of a detected impulse."""

    w0: ZigzagPoint
    w1: ZigzagPoint
    w2: ZigzagPoint
    w3: ZigzagPoint
    w4: ZigzagPoint
    w5: ZigzagPoint

    def wave_length(self, n: int) -> float:
        """Absolute price length of wave 1, 3, or 5."""
        if n == 1:
            return abs(self.w1.price - self.w0.price)
        elif n == 3:
            return abs(self.w3.price - self.w2.price)
        elif n == 5:
            return abs(self.w5.price - self.w4.price)
        raise ValueError(f"wave_length only supports 1, 3, 5; got {n}")

    def as_list(self) -> list[ZigzagPoint]:
        """Return ordered list W0 through W5."""
        return [self.w0, self.w1, self.w2, self.w3, self.w4, self.w5]


@dataclass
class ImpulsePattern:
    """A detected 5-wave impulse with enrichment data."""

    direction: int  # 1 = bull, -1 = bear
    waves: WavePoints
    scale: int
    detected_at_bar: int

    # Enrichment (set by enrich_pattern)
    confidence: int = 0
    extended_wave: int = 0  # 1, 3, or 5
    has_alternation: bool = False
    has_rsi_divergence: bool = False
    has_volume_confirmation: bool = False
    w2_retrace_ratio: float = 0.0
    w4_retrace_ratio: float = 0.0

    # Validity
    is_valid: bool = True
    invalidated_at_bar: int | None = None

    @property
    def is_bullish(self) -> bool:
        return self.direction == 1

    @property
    def is_bearish(self) -> bool:
        return self.direction == -1

    @property
    def direction_str(self) -> str:
        return "BULL" if self.direction == 1 else "BEAR"


@dataclass
class ElliottWaveResult:
    """Top-level result container from detect_elliott_waves."""

    patterns: list[ImpulsePattern] = field(default_factory=list)
    zigzags: dict[int, list[ZigzagPoint]] = field(default_factory=dict)
    bars_analyzed: int = 0
    scales: list[int] = field(default_factory=list)

    @property
    def valid_patterns(self) -> list[ImpulsePattern]:
        return [p for p in self.patterns if p.is_valid]

    @property
    def latest_pattern(self) -> ImpulsePattern | None:
        valid = self.valid_patterns
        if not valid:
            return None
        return max(valid, key=lambda p: p.detected_at_bar)

    def patterns_at_scale(self, scale: int) -> list[ImpulsePattern]:
        return [p for p in self.patterns if p.scale == scale]


# =============================================================================
# Indicator Helpers
# =============================================================================


def _compute_rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """
    Wilder's RSI, pure Python. Returns list aligned to input.

    First `period` values are None (insufficient data).
    """
    n = len(closes)
    result: list[float | None] = [None] * n

    if n <= period:
        return result

    # Seed averages from first `period` changes
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains += change
        else:
            losses += abs(change)

    avg_gain = gains / period
    avg_loss = losses / period

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    # Wilder smoothing for remaining bars
    for i in range(period + 1, n):
        change = closes[i] - closes[i - 1]
        gain = change if change > 0 else 0.0
        loss = abs(change) if change < 0 else 0.0

        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - (100.0 / (1.0 + rs))

    return result


def _compute_sma(values: list[float], period: int = 20) -> list[float | None]:
    """
    Simple moving average. Returns list aligned to input.

    First `period - 1` values are None (insufficient data).
    """
    n = len(values)
    result: list[float | None] = [None] * n

    if n < period:
        return result

    window_sum = sum(values[:period])
    result[period - 1] = window_sum / period

    for i in range(period, n):
        window_sum += values[i] - values[i - period]
        result[i] = window_sum / period

    return result


# =============================================================================
# Zigzag Construction
# =============================================================================


def build_zigzag(
    bars: list[Bar],
    scale: int,
    rsi_values: list[float | None] | None = None,
) -> list[ZigzagPoint]:
    """
    Build alternating zigzag at given scale.

    Uses find_swing_highs/lows with left_bars=scale, right_bars=1,
    merges chronologically, then enforces strict alternation (matching
    Pine's f_zzUpdate high-first logic).
    """
    if len(bars) < scale + 2:
        return []

    highs = find_swing_highs(bars, left_bars=scale, right_bars=1)
    lows = find_swing_lows(bars, left_bars=scale, right_bars=1)

    # Merge into candidate list sorted by (bar_index, -direction)
    # so highs (+1) come before lows (-1) at the same bar index
    candidates: list[ZigzagPoint] = []
    for sp in highs:
        candidates.append(ZigzagPoint(
            price=sp.price,
            bar_index=sp.bar_index,
            timestamp=sp.timestamp,
            direction=1,
            rsi=rsi_values[sp.bar_index] if rsi_values and sp.bar_index < len(rsi_values) else None,
            volume=bars[sp.bar_index].volume if sp.bar_index < len(bars) else None,
        ))
    for sp in lows:
        candidates.append(ZigzagPoint(
            price=sp.price,
            bar_index=sp.bar_index,
            timestamp=sp.timestamp,
            direction=-1,
            rsi=rsi_values[sp.bar_index] if rsi_values and sp.bar_index < len(rsi_values) else None,
            volume=bars[sp.bar_index].volume if sp.bar_index < len(bars) else None,
        ))

    # Sort: by bar_index ascending, then highs before lows at same bar
    candidates.sort(key=lambda p: (p.bar_index, -p.direction))

    # Enforce alternation (matches Pine's f_zzUpdate logic)
    zigzag: list[ZigzagPoint] = []
    for c in candidates:
        if not zigzag:
            zigzag.append(c)
            continue

        last = zigzag[-1]
        if c.direction != last.direction:
            # Alternating — accept
            zigzag.append(c)
        elif c.direction == 1 and c.price > last.price:
            # Same direction (high), more extreme — replace
            zigzag[-1] = c
        elif c.direction == -1 and c.price < last.price:
            # Same direction (low), more extreme — replace
            zigzag[-1] = c
        # else: skip (same direction, not more extreme)

    return zigzag


# =============================================================================
# Impulse Rule Checking
# =============================================================================


def check_impulse_rules(
    p0: ZigzagPoint,
    p1: ZigzagPoint,
    p2: ZigzagPoint,
    p3: ZigzagPoint,
    p4: ZigzagPoint,
    p5: ZigzagPoint,
) -> tuple[bool, int]:
    """
    Check Elliott impulse rules on 6 zigzag points (newest-first: p0..p5).

    Bullish (p0.direction == +1): W0=p5, W1=p4, W2=p3, W3=p2, W4=p1, W5=p0
    Bearish (p0.direction == -1): same mapping, mirrored comparisons.

    Rules checked:
      Rule 1: W2 doesn't retrace beyond W0
      Rule 2: W3 is not the shortest of W1/W3/W5
      Rule 3: W4 doesn't enter W1 territory
      Rule 5: W5 makes a new extreme beyond W3

    Returns (found, direction) where direction is 1 (bull) or -1 (bear).
    """
    # Map newest-first to wave points
    w0y, w1y, w2y, w3y, w4y, w5y = (
        p5.price, p4.price, p3.price, p2.price, p1.price, p0.price,
    )

    l1 = abs(w1y - w0y)
    l3 = abs(w3y - w2y)
    l5 = abs(w5y - w4y)

    # Rule 2: W3 not shortest (same for bull and bear)
    r2 = not (l3 <= l1 and l3 <= l5)

    if p0.direction == 1:
        # Bullish
        r1 = w2y > w0y
        r3 = w4y > w1y
        r5 = w5y > w3y
        if r1 and r2 and r3 and r5:
            return True, 1

    if p0.direction == -1:
        # Bearish
        r1 = w2y < w0y
        r3 = w4y < w1y
        r5 = w5y < w3y
        if r1 and r2 and r3 and r5:
            return True, -1

    return False, 0


# =============================================================================
# Enrichment
# =============================================================================


def enrich_pattern(
    pattern: ImpulsePattern,
    vol_sma_at_w3: float | None = None,
) -> None:
    """
    Add confidence scoring to an impulse pattern (mutates in-place).

    Scoring (matches Pine's f_enrich):
      Base:                         40
      Extended wave is W3:         +15
      Alternation (>10% diff):    +10
      RSI divergence at W5 vs W3: +10
      Volume at W3 > SMA:         +10
      W2 retrace 38-62%:           +5
      W4 retrace 23-50%:           +5
      Max:                         95
    """
    w = pattern.waves

    # Extended wave
    l1 = w.wave_length(1)
    l3 = w.wave_length(3)
    l5 = w.wave_length(5)

    if l3 >= l1 and l3 >= l5:
        pattern.extended_wave = 3
    elif l5 >= l1:
        pattern.extended_wave = 5
    else:
        pattern.extended_wave = 1

    # W2 retrace ratio: how much W2 retraces W1
    w1_len = l1
    w2_retrace = abs(w.w2.price - w.w1.price)
    pattern.w2_retrace_ratio = w2_retrace / w1_len if w1_len > 0 else 0.0

    # W4 retrace ratio: how much W4 retraces W3
    w3_len = l3
    w4_retrace = abs(w.w4.price - w.w3.price)
    pattern.w4_retrace_ratio = w4_retrace / w3_len if w3_len > 0 else 0.0

    # Alternation
    pattern.has_alternation = abs(pattern.w2_retrace_ratio - pattern.w4_retrace_ratio) > 0.10

    # RSI divergence at W5 vs W3
    rsi3 = w.w3.rsi
    rsi5 = w.w5.rsi
    if rsi3 is not None and rsi5 is not None:
        if pattern.direction == 1 and w.w5.price > w.w3.price and rsi5 < rsi3:
            pattern.has_rsi_divergence = True
        elif pattern.direction == -1 and w.w5.price < w.w3.price and rsi5 > rsi3:
            pattern.has_rsi_divergence = True

    # Volume confirmation at W3
    vol3 = w.w3.volume
    if vol3 is not None and vol_sma_at_w3 is not None and vol3 > vol_sma_at_w3:
        pattern.has_volume_confirmation = True

    # Confidence scoring
    conf = 40
    if pattern.extended_wave == 3:
        conf += 15
    if pattern.has_alternation:
        conf += 10
    if pattern.has_rsi_divergence:
        conf += 10
    if pattern.has_volume_confirmation:
        conf += 10
    if 0.38 <= pattern.w2_retrace_ratio <= 0.62:
        conf += 5
    if 0.23 <= pattern.w4_retrace_ratio <= 0.50:
        conf += 5

    pattern.confidence = min(conf, 95)


# =============================================================================
# Invalidation
# =============================================================================


def check_invalidation(pattern: ImpulsePattern, bars: list[Bar]) -> None:
    """
    Scan bars after detection for Rule 3 violation (W4 enters W1 territory).

    For bullish: invalidated if any bar's low < W1 price.
    For bearish: invalidated if any bar's high > W1 price.

    Mutates the pattern in-place.
    """
    w1_price = pattern.waves.w1.price
    start = pattern.detected_at_bar + 1

    for i in range(start, len(bars)):
        bar = bars[i]
        if pattern.direction == 1 and bar.low < w1_price:
            pattern.is_valid = False
            pattern.invalidated_at_bar = i
            return
        elif pattern.direction == -1 and bar.high > w1_price:
            pattern.is_valid = False
            pattern.invalidated_at_bar = i
            return


# =============================================================================
# Main Entry Point
# =============================================================================


def detect_elliott_waves(
    bars: list[Bar],
    scales: list[int] | None = None,
    rsi_period: int = 14,
    vol_sma_period: int = 20,
) -> ElliottWaveResult:
    """
    Detect Elliott Wave impulse patterns at multiple scales.

    1. Pre-compute RSI and volume SMA for all bars
    2. For each scale: build zigzag, check impulse rules at each 6-point
       window, enrich matches, check invalidation
    3. Deduplicate by (scale, w0.bar_index, w5.bar_index)
    4. Return ElliottWaveResult
    """
    if scales is None:
        scales = [4, 8, 16]

    result = ElliottWaveResult(
        bars_analyzed=len(bars),
        scales=list(scales),
    )

    if len(bars) < 10:
        return result

    # Pre-compute indicators
    closes = [b.close for b in bars]
    volumes = [float(b.volume) for b in bars]
    rsi_values = _compute_rsi(closes, rsi_period)
    vol_sma_values = _compute_sma(volumes, vol_sma_period)

    seen: set[tuple[int, int, int]] = set()

    for scale in scales:
        zigzag = build_zigzag(bars, scale, rsi_values)
        result.zigzags[scale] = zigzag

        if len(zigzag) < 6:
            continue

        # Walk through zigzag checking 6-point windows (newest-first)
        for i in range(len(zigzag) - 1, 4, -1):
            p0 = zigzag[i]
            p1 = zigzag[i - 1]
            p2 = zigzag[i - 2]
            p3 = zigzag[i - 3]
            p4 = zigzag[i - 4]
            p5 = zigzag[i - 5]

            found, direction = check_impulse_rules(p0, p1, p2, p3, p4, p5)
            if not found:
                continue

            # Map to wave points (p0 newest, p5 oldest)
            w0, w1, w2, w3, w4, w5 = p5, p4, p3, p2, p1, p0

            # Deduplicate
            key = (scale, w0.bar_index, w5.bar_index)
            if key in seen:
                continue
            seen.add(key)

            waves = WavePoints(w0=w0, w1=w1, w2=w2, w3=w3, w4=w4, w5=w5)
            pattern = ImpulsePattern(
                direction=direction,
                waves=waves,
                scale=scale,
                detected_at_bar=w5.bar_index,
            )

            # Enrich
            vol_sma_at_w3 = (
                vol_sma_values[w3.bar_index]
                if w3.bar_index < len(vol_sma_values)
                else None
            )
            enrich_pattern(pattern, vol_sma_at_w3)

            # Check invalidation
            check_invalidation(pattern, bars)

            result.patterns.append(pattern)

    return result
