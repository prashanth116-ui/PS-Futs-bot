"""
Elliott Wave Detector — Phase 1 + Phase 2

Ports core logic from Pine Script V2 (tradingview/elliott_wave_detector.pine)
to Python for use in the backtesting/live trading pipeline.

Phase 1: Zigzag construction, impulse detection, enrichment, invalidation.
Phase 2: ABC correction tracking, flat/zigzag classification, Fibonacci targets.

Usage:
    from strategies.ict.signals.elliott_wave import detect_elliott_waves

    result = detect_elliott_waves(bars, scales=[4, 8, 16])
    for p in result.valid_patterns:
        print(f"{p.direction_str} impulse, confidence={p.confidence}%")
        if p.correction:
            print(f"  correction: {p.correction.correction_type}")
    for idx, fib in result.fib_targets.items():
        for lvl in fib.levels:
            print(f"  {lvl.label}: {lvl.price:.2f}")
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
class CorrectionPoints:
    """The 3 wave points (A, B, C) of a correction."""

    a: ZigzagPoint
    b: ZigzagPoint
    c: ZigzagPoint

    def as_list(self) -> list[ZigzagPoint]:
        """Return ordered list A, B, C."""
        return [self.a, self.b, self.c]


@dataclass
class FibTarget:
    """A single Fibonacci retracement level."""

    ratio: float  # e.g. 0.382, 0.5, 0.618
    price: float  # computed target price
    label: str  # e.g. "38.2%"


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

    # Phase 2: correction (set by track_abc)
    correction: CorrectivePattern | None = None

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
class CorrectivePattern:
    """A detected ABC correction after an impulse."""

    impulse: ImpulsePattern
    points: CorrectionPoints
    correction_type: str  # "zigzag" or "flat"
    direction: int  # opposite of impulse direction
    completed_at_bar: int
    b_retrace_ratio: float  # |B-A| / |A-W5|, used for flat/zigzag classification
    c_retrace_ratio: float  # |C-W5| / |W5-W0|, must be < 0.854
    confidence_boost: int = 15  # added to parent impulse on completion
    is_valid: bool = True


@dataclass
class FibTargets:
    """Collection of Fibonacci retracement targets after an impulse."""

    impulse: ImpulsePattern
    levels: list[FibTarget] = field(default_factory=list)
    impulse_range: float = 0.0  # |W5 - W0|

    def get_level(self, ratio: float) -> FibTarget | None:
        """Get a specific Fibonacci level by ratio, or None if not found."""
        for lvl in self.levels:
            if abs(lvl.ratio - ratio) < 1e-6:
                return lvl
        return None


@dataclass
class ElliottWaveResult:
    """Top-level result container from detect_elliott_waves."""

    patterns: list[ImpulsePattern] = field(default_factory=list)
    zigzags: dict[int, list[ZigzagPoint]] = field(default_factory=dict)
    bars_analyzed: int = 0
    scales: list[int] = field(default_factory=list)
    fib_targets: dict[int, FibTargets] = field(default_factory=dict)

    @property
    def valid_patterns(self) -> list[ImpulsePattern]:
        return [p for p in self.patterns if p.is_valid]

    @property
    def latest_pattern(self) -> ImpulsePattern | None:
        valid = self.valid_patterns
        if not valid:
            return None
        return max(valid, key=lambda p: p.detected_at_bar)

    @property
    def corrections(self) -> list[CorrectivePattern]:
        """All completed corrections across all patterns."""
        return [p.correction for p in self.patterns if p.correction is not None]

    @property
    def patterns_with_corrections(self) -> list[ImpulsePattern]:
        """Patterns that have completed ABC corrections."""
        return [p for p in self.patterns if p.correction is not None]

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
# ABC Correction Tracking (Phase 2)
# =============================================================================


def track_abc(
    impulse: ImpulsePattern,
    zigzag: list[ZigzagPoint],
    bars: list[Bar],
) -> CorrectivePattern | None:
    """
    State machine: find A, B, C correction after impulse W5.

    For a bullish impulse (W5 is a high):
      - Wave A: first low pivot after W5
      - Wave B: next high pivot after A (retrace back up)
      - Wave C: next low pivot after B (continue down)

    For a bearish impulse (W5 is a low):
      - Wave A: first high pivot after W5
      - Wave B: next low pivot after A (retrace back down)
      - Wave C: next high pivot after B (continue up)

    Classification:
      - B retrace > 90% of A move → "flat"
      - Otherwise → "zigzag"

    Validation:
      - |C - W5| / |W5 - W0| < 0.854 (max retrace rule)

    Returns CorrectivePattern if complete and valid, else None.
    """
    w5 = impulse.waves.w5
    w0 = impulse.waves.w0

    # Correction direction is opposite to impulse
    corr_dir = -impulse.direction

    # Direction of Wave A pivot: opposite to W5
    # Bullish impulse: W5 is high (+1), A is low (-1)
    # Bearish impulse: W5 is low (-1), A is high (+1)
    a_dir = -w5.direction

    # Scan zigzag points chronologically after W5
    after_w5 = [p for p in zigzag if p.bar_index > w5.bar_index]
    if not after_w5:
        return None

    # Find Wave A: first pivot in a_dir
    wave_a = None
    for p in after_w5:
        if p.direction == a_dir:
            wave_a = p
            break
    if wave_a is None:
        return None

    # Find Wave B: next pivot opposite to A (same as W5 direction)
    wave_b = None
    for p in after_w5:
        if p.bar_index > wave_a.bar_index and p.direction == -a_dir:
            wave_b = p
            break
    if wave_b is None:
        return None

    # Find Wave C: next pivot same direction as A
    wave_c = None
    for p in after_w5:
        if p.bar_index > wave_b.bar_index and p.direction == a_dir:
            wave_c = p
            break
    if wave_c is None:
        return None

    # B retrace ratio: |B - A| / |A - W5|
    a_move = abs(wave_a.price - w5.price)
    b_retrace = abs(wave_b.price - wave_a.price)
    b_retrace_ratio = b_retrace / a_move if a_move > 0 else 0.0

    # Classify: flat if B retraces > 90% of A move
    correction_type = "flat" if b_retrace_ratio > 0.90 else "zigzag"

    # C retrace ratio: |C - W5| / |W5 - W0| (how much of impulse is retraced)
    impulse_range = abs(w5.price - w0.price)
    c_retrace = abs(wave_c.price - w5.price)
    c_retrace_ratio = c_retrace / impulse_range if impulse_range > 0 else 0.0

    # Validate: max retrace rule — correction must not retrace > 85.4%
    if c_retrace_ratio >= 0.854:
        return None

    return CorrectivePattern(
        impulse=impulse,
        points=CorrectionPoints(a=wave_a, b=wave_b, c=wave_c),
        correction_type=correction_type,
        direction=corr_dir,
        completed_at_bar=wave_c.bar_index,
        b_retrace_ratio=b_retrace_ratio,
        c_retrace_ratio=c_retrace_ratio,
    )


# =============================================================================
# Fibonacci Targets (Phase 2)
# =============================================================================


_FIB_RATIOS = [
    (0.236, "23.6%"),
    (0.382, "38.2%"),
    (0.5, "50.0%"),
    (0.618, "61.8%"),
    (0.786, "78.6%"),
]


def compute_fib_targets(impulse: ImpulsePattern) -> FibTargets:
    """
    Compute Fibonacci retracement levels after an impulse.

    Bullish impulse: targets below W5 (retracement = W5 - range * ratio)
    Bearish impulse: targets above W5 (retracement = W5 + range * ratio)
    """
    w5_price = impulse.waves.w5.price
    w0_price = impulse.waves.w0.price
    imp_range = abs(w5_price - w0_price)

    levels = []
    for ratio, label in _FIB_RATIOS:
        if impulse.direction == 1:
            # Bullish: retracement goes down from W5
            price = w5_price - imp_range * ratio
        else:
            # Bearish: retracement goes up from W5
            price = w5_price + imp_range * ratio
        levels.append(FibTarget(ratio=ratio, price=price, label=label))

    return FibTargets(impulse=impulse, levels=levels, impulse_range=imp_range)


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
    4. Phase 2: track ABC corrections and compute Fibonacci targets
    5. Return ElliottWaveResult
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

    # Phase 2: track ABC corrections and compute Fibonacci targets
    for idx, pattern in enumerate(result.patterns):
        if not pattern.is_valid:
            continue

        # Find the zigzag for this pattern's scale
        zigzag = result.zigzags.get(pattern.scale, [])

        # Track ABC correction
        correction = track_abc(pattern, zigzag, bars)
        if correction is not None:
            pattern.correction = correction
            pattern.confidence = min(pattern.confidence + correction.confidence_boost, 100)

        # Compute Fibonacci targets
        result.fib_targets[idx] = compute_fib_targets(pattern)

    return result
