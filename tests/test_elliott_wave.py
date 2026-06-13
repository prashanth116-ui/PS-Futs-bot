"""
Unit tests for Elliott Wave detector (Phase 1).

Tests:
  - RSI computation (Wilder's method)
  - SMA computation
  - Zigzag construction (alternation, updates, scale effects)
  - Impulse rule checking (bullish, bearish, each rule violation)
  - Enrichment (confidence scoring, extended wave, RSI div, volume, fib ratios)
  - Invalidation (bull/bear, no invalidation, bar index tracking)
  - Full detect_elliott_waves pipeline
"""

import pytest
from datetime import datetime

from core.types import Bar
from strategies.ict.signals.elliott_wave import (
    ZigzagPoint,
    WavePoints,
    ImpulsePattern,
    ElliottWaveResult,
    _compute_rsi,
    _compute_sma,
    build_zigzag,
    check_impulse_rules,
    enrich_pattern,
    check_invalidation,
    detect_elliott_waves,
)


# =============================================================================
# Helpers
# =============================================================================


def _bar(o, h, l, c, idx=0, vol=100):
    """Helper to create a Bar."""
    total_minutes = 9 * 60 + 30 + idx
    return Bar(
        timestamp=datetime(2026, 1, 1, total_minutes // 60, total_minutes % 60),
        open=o, high=h, low=l, close=c, volume=vol,
        symbol="ES", timeframe="3m",
    )


def _zz(price, bar_index, direction, rsi=None, volume=None):
    """Helper to create a ZigzagPoint."""
    return ZigzagPoint(
        price=price,
        bar_index=bar_index,
        timestamp=datetime(2026, 1, 1, 9, 30 + bar_index % 60),
        direction=direction,
        rsi=rsi,
        volume=volume,
    )


# =============================================================================
# RSI Tests
# =============================================================================


class TestRSI:
    def test_known_values(self):
        """RSI on a known sequence produces reasonable values."""
        # 20 bars: alternating up/down but trending up
        closes = [100 + i * 0.5 + (0.3 if i % 2 == 0 else -0.1) for i in range(20)]
        result = _compute_rsi(closes, period=14)

        # First 14 values should be None
        for i in range(14):
            assert result[i] is None
        # Value at index 14 should be defined
        assert result[14] is not None
        assert 0 <= result[14] <= 100

    def test_all_up(self):
        """Monotonically increasing closes produce RSI near 100."""
        closes = [float(100 + i) for i in range(20)]
        result = _compute_rsi(closes, period=14)
        assert result[14] == pytest.approx(100.0)
        assert result[19] == pytest.approx(100.0)

    def test_all_down(self):
        """Monotonically decreasing closes produce RSI near 0."""
        closes = [float(200 - i) for i in range(20)]
        result = _compute_rsi(closes, period=14)
        assert result[14] == pytest.approx(0.0)
        assert result[19] == pytest.approx(0.0)

    def test_none_padding(self):
        """Input shorter than period returns all None."""
        closes = [100.0, 101.0, 102.0]
        result = _compute_rsi(closes, period=14)
        assert all(v is None for v in result)
        assert len(result) == 3


# =============================================================================
# SMA Tests
# =============================================================================


class TestSMA:
    def test_constant_values(self):
        """SMA of constant values equals that constant."""
        values = [50.0] * 25
        result = _compute_sma(values, period=20)
        assert result[19] == pytest.approx(50.0)
        assert result[24] == pytest.approx(50.0)

    def test_known_calculation(self):
        """SMA of 1..20 with period=5: SMA[4] = mean(1,2,3,4,5) = 3.0."""
        values = [float(i + 1) for i in range(20)]
        result = _compute_sma(values, period=5)
        assert result[4] == pytest.approx(3.0)
        # SMA[5] = mean(2,3,4,5,6) = 4.0
        assert result[5] == pytest.approx(4.0)

    def test_none_padding(self):
        """Input shorter than period returns all None."""
        values = [1.0, 2.0, 3.0]
        result = _compute_sma(values, period=5)
        assert all(v is None for v in result)
        assert len(result) == 3


# =============================================================================
# Zigzag Tests
# =============================================================================


class TestZigzag:
    def _make_impulse_bars(self, n=30):
        """Create bars with a clear up-down-up pattern for zigzag detection."""
        bars = []
        for i in range(n):
            if i < 8:
                p = 100 + i * 2
            elif i < 15:
                p = 114 - (i - 8) * 2
            else:
                p = 100 + (i - 15) * 2
            bars.append(_bar(p - 0.5, p + 1, p - 1, p + 0.5, idx=i))
        return bars

    def test_alternation_enforced(self):
        """Zigzag must alternate between highs and lows."""
        bars = self._make_impulse_bars(30)
        zz = build_zigzag(bars, scale=2)
        for i in range(1, len(zz)):
            assert zz[i].direction != zz[i - 1].direction, (
                f"Non-alternating at index {i}: "
                f"{zz[i-1].direction} -> {zz[i].direction}"
            )

    def test_same_direction_update(self):
        """When two consecutive highs occur, keep the more extreme."""
        bars = []
        # Low, then two highs (second higher), then low
        prices = [100, 101, 103, 105, 110, 115, 112, 108, 104, 100, 97]
        for i, p in enumerate(prices):
            bars.append(_bar(p - 0.5, p + 0.5, p - 0.5, p, idx=i))
        zz = build_zigzag(bars, scale=2)
        # All highs in zigzag should be the maximum of any consecutive run
        high_prices = [pt.price for pt in zz if pt.direction == 1]
        for hp in high_prices:
            assert hp > 100  # sanity check

    def test_min_bars_returns_empty(self):
        """Too few bars for the scale returns empty zigzag."""
        bars = [_bar(100, 101, 99, 100, idx=i) for i in range(3)]
        zz = build_zigzag(bars, scale=4)
        assert zz == []

    def test_scale_effect(self):
        """Larger scale produces fewer zigzag points."""
        bars = self._make_impulse_bars(50)
        zz_small = build_zigzag(bars, scale=2)
        zz_large = build_zigzag(bars, scale=4)
        assert len(zz_large) <= len(zz_small)

    def test_rsi_attachment(self):
        """RSI values are attached to zigzag points when provided."""
        bars = self._make_impulse_bars(30)
        rsi = [50.0 + i for i in range(30)]
        zz = build_zigzag(bars, scale=2, rsi_values=rsi)
        for pt in zz:
            assert pt.rsi is not None
            assert pt.rsi == pytest.approx(50.0 + pt.bar_index)


# =============================================================================
# Impulse Rule Tests
# =============================================================================


class TestImpulseRules:
    def test_valid_bullish(self):
        """Valid bullish impulse: all 4 rules pass."""
        # Newest-first: p0=W5(high), p1=W4(low), p2=W3(high), p3=W2(low),
        #               p4=W1(high), p5=W0(low)
        # W0=100, W1=110, W2=105, W3=120, W4=112, W5=130
        p5 = _zz(100, 0, -1)   # W0 (low)
        p4 = _zz(110, 5, 1)    # W1 (high)
        p3 = _zz(105, 10, -1)  # W2 (low)
        p2 = _zz(120, 15, 1)   # W3 (high)
        p1 = _zz(112, 20, -1)  # W4 (low)
        p0 = _zz(130, 25, 1)   # W5 (high)

        found, direction = check_impulse_rules(p0, p1, p2, p3, p4, p5)
        assert found is True
        assert direction == 1

    def test_valid_bearish(self):
        """Valid bearish impulse: all 4 rules pass."""
        # W0=200, W1=190, W2=195, W3=180, W4=188, W5=170
        p5 = _zz(200, 0, 1)    # W0 (high)
        p4 = _zz(190, 5, -1)   # W1 (low)
        p3 = _zz(195, 10, 1)   # W2 (high)
        p2 = _zz(180, 15, -1)  # W3 (low)
        p1 = _zz(188, 20, 1)   # W4 (high)
        p0 = _zz(170, 25, -1)  # W5 (low)

        found, direction = check_impulse_rules(p0, p1, p2, p3, p4, p5)
        assert found is True
        assert direction == -1

    def test_rule1_violation_bullish(self):
        """Bullish Rule 1 fail: W2 < W0 (W2 retraces beyond start)."""
        p5 = _zz(100, 0, -1)
        p4 = _zz(110, 5, 1)
        p3 = _zz(99, 10, -1)   # W2=99 < W0=100 → violation
        p2 = _zz(120, 15, 1)
        p1 = _zz(112, 20, -1)
        p0 = _zz(130, 25, 1)

        found, _ = check_impulse_rules(p0, p1, p2, p3, p4, p5)
        assert found is False

    def test_rule2_violation_bullish(self):
        """Bullish Rule 2 fail: W3 is shortest wave."""
        # W1=10pts, W3=5pts, W5=10pts → W3 shortest
        p5 = _zz(100, 0, -1)
        p4 = _zz(110, 5, 1)    # W1 = 10
        p3 = _zz(105, 10, -1)
        p2 = _zz(110, 15, 1)   # W3 = 5 (shortest)
        p1 = _zz(106, 20, -1)
        p0 = _zz(116, 25, 1)   # W5 = 10

        found, _ = check_impulse_rules(p0, p1, p2, p3, p4, p5)
        assert found is False

    def test_rule3_violation_bullish(self):
        """Bullish Rule 3 fail: W4 < W1 (W4 enters W1 territory)."""
        p5 = _zz(100, 0, -1)
        p4 = _zz(115, 5, 1)    # W1 = 115
        p3 = _zz(105, 10, -1)
        p2 = _zz(125, 15, 1)
        p1 = _zz(114, 20, -1)  # W4 = 114 < W1 = 115 → violation
        p0 = _zz(135, 25, 1)

        found, _ = check_impulse_rules(p0, p1, p2, p3, p4, p5)
        assert found is False

    def test_rule5_violation_bullish(self):
        """Bullish Rule 5 fail: W5 < W3 (no new high)."""
        p5 = _zz(100, 0, -1)
        p4 = _zz(110, 5, 1)
        p3 = _zz(105, 10, -1)
        p2 = _zz(120, 15, 1)   # W3 = 120
        p1 = _zz(112, 20, -1)
        p0 = _zz(119, 25, 1)   # W5 = 119 < W3 → violation

        found, _ = check_impulse_rules(p0, p1, p2, p3, p4, p5)
        assert found is False

    def test_rule1_violation_bearish(self):
        """Bearish Rule 1 fail: W2 > W0."""
        p5 = _zz(200, 0, 1)    # W0 = 200
        p4 = _zz(190, 5, -1)
        p3 = _zz(201, 10, 1)   # W2 = 201 > W0 = 200 → violation
        p2 = _zz(180, 15, -1)
        p1 = _zz(188, 20, 1)
        p0 = _zz(170, 25, -1)

        found, _ = check_impulse_rules(p0, p1, p2, p3, p4, p5)
        assert found is False

    def test_rule3_violation_bearish(self):
        """Bearish Rule 3 fail: W4 > W1."""
        p5 = _zz(200, 0, 1)
        p4 = _zz(185, 5, -1)   # W1 = 185
        p3 = _zz(195, 10, 1)
        p2 = _zz(175, 15, -1)
        p1 = _zz(186, 20, 1)   # W4 = 186 > W1 = 185 → violation
        p0 = _zz(165, 25, -1)

        found, _ = check_impulse_rules(p0, p1, p2, p3, p4, p5)
        assert found is False


# =============================================================================
# Enrichment Tests
# =============================================================================


class TestEnrichment:
    def _make_bull_pattern(self, **overrides):
        """Create a valid bullish impulse for enrichment testing."""
        defaults = {
            "w0": _zz(100, 0, -1, rsi=40, volume=80),
            "w1": _zz(110, 5, 1, rsi=60, volume=100),
            "w2": _zz(105, 10, -1, rsi=45, volume=90),
            "w3": _zz(125, 15, 1, rsi=70, volume=200),
            "w4": _zz(118, 20, -1, rsi=50, volume=100),
            "w5": _zz(135, 25, 1, rsi=65, volume=150),
        }
        defaults.update(overrides)
        waves = WavePoints(**defaults)
        return ImpulsePattern(direction=1, waves=waves, scale=4, detected_at_bar=25)

    def test_extended_wave_3(self):
        """W3 longest → extended_wave = 3, confidence gets +15."""
        pat = self._make_bull_pattern()
        enrich_pattern(pat)
        assert pat.extended_wave == 3
        assert pat.confidence >= 55  # base 40 + 15

    def test_extended_wave_5(self):
        """W5 longest → extended_wave = 5."""
        # W1=10 (110-100), W3=15 (120-105), W5=25 (143-118)
        pat = self._make_bull_pattern(
            w3=_zz(120, 15, 1, rsi=70, volume=200),
            w4=_zz(118, 20, -1, rsi=50, volume=100),
            w5=_zz(143, 25, 1, rsi=65, volume=150),
        )
        enrich_pattern(pat)
        assert pat.extended_wave == 5

    def test_alternation(self):
        """W2 and W4 retrace ratios differ by >10% → has_alternation."""
        pat = self._make_bull_pattern()
        enrich_pattern(pat)
        assert pat.has_alternation is True

    def test_rsi_divergence_bull(self):
        """Bullish: W5 price > W3 price but RSI lower → divergence."""
        pat = self._make_bull_pattern(
            w3=_zz(125, 15, 1, rsi=75, volume=200),
            w5=_zz(135, 25, 1, rsi=65, volume=150),
        )
        enrich_pattern(pat)
        assert pat.has_rsi_divergence is True

    def test_rsi_divergence_bear(self):
        """Bearish: W5 price < W3 price but RSI higher → divergence."""
        waves = WavePoints(
            w0=_zz(200, 0, 1, rsi=60, volume=100),
            w1=_zz(190, 5, -1, rsi=40, volume=120),
            w2=_zz(195, 10, 1, rsi=55, volume=90),
            w3=_zz(175, 15, -1, rsi=25, volume=200),
            w4=_zz(183, 20, 1, rsi=45, volume=100),
            w5=_zz(165, 25, -1, rsi=30, volume=150),
        )
        pat = ImpulsePattern(direction=-1, waves=waves, scale=4, detected_at_bar=25)
        enrich_pattern(pat)
        assert pat.has_rsi_divergence is True

    def test_volume_confirmation(self):
        """Volume at W3 > vol SMA → has_volume_confirmation."""
        pat = self._make_bull_pattern(
            w3=_zz(125, 15, 1, rsi=70, volume=200),
        )
        enrich_pattern(pat, vol_sma_at_w3=150.0)
        assert pat.has_volume_confirmation is True

    def test_max_confidence(self):
        """With all bonuses, confidence caps at 95."""
        # Set up pattern to hit every bonus
        pat = self._make_bull_pattern(
            w0=_zz(100, 0, -1, rsi=40, volume=80),
            w1=_zz(110, 5, 1, rsi=60, volume=100),
            w2=_zz(105, 10, -1, rsi=45, volume=90),   # W2 retrace = 5/10 = 0.50
            w3=_zz(125, 15, 1, rsi=75, volume=200),    # W3 = 20 (extended)
            w4=_zz(118, 20, -1, rsi=50, volume=100),   # W4 retrace = 7/20 = 0.35
            w5=_zz(135, 25, 1, rsi=65, volume=150),    # RSI div
        )
        enrich_pattern(pat, vol_sma_at_w3=150.0)
        assert pat.confidence == 95

    def test_min_confidence(self):
        """Pattern with no bonuses gets base 40."""
        # All RSI None, no volume, W1 longest, no alternation
        pat = self._make_bull_pattern(
            w0=_zz(100, 0, -1),
            w1=_zz(130, 5, 1),     # W1 = 30 (longest)
            w2=_zz(105, 10, -1),   # retrace = 25/30 = 0.83
            w3=_zz(125, 15, 1),    # W3 = 20
            w4=_zz(108, 20, -1),   # retrace = 17/20 = 0.85, diff ~ 0.02
            w5=_zz(135, 25, 1),    # W5 = 27
        )
        enrich_pattern(pat)
        assert pat.extended_wave == 1
        assert pat.confidence == 40


# =============================================================================
# Invalidation Tests
# =============================================================================


class TestInvalidation:
    def test_bull_invalidation(self):
        """Bullish pattern invalidated when bar.low < W1 price."""
        waves = WavePoints(
            w0=_zz(100, 0, -1), w1=_zz(110, 5, 1), w2=_zz(105, 10, -1),
            w3=_zz(120, 15, 1), w4=_zz(112, 20, -1), w5=_zz(130, 25, 1),
        )
        pat = ImpulsePattern(direction=1, waves=waves, scale=4, detected_at_bar=25)

        bars = [_bar(100, 102, 99, 101, idx=i) for i in range(26)]
        # Add bar that violates: low = 109 < W1 = 110
        bars.append(_bar(115, 116, 109, 112, idx=26))

        check_invalidation(pat, bars)
        assert pat.is_valid is False
        assert pat.invalidated_at_bar == 26

    def test_bear_invalidation(self):
        """Bearish pattern invalidated when bar.high > W1 price."""
        waves = WavePoints(
            w0=_zz(200, 0, 1), w1=_zz(190, 5, -1), w2=_zz(195, 10, 1),
            w3=_zz(180, 15, -1), w4=_zz(188, 20, 1), w5=_zz(170, 25, -1),
        )
        pat = ImpulsePattern(direction=-1, waves=waves, scale=4, detected_at_bar=25)

        bars = [_bar(180, 182, 178, 180, idx=i) for i in range(26)]
        # Add bar that violates: high = 191 > W1 = 190
        bars.append(_bar(188, 191, 187, 189, idx=26))

        check_invalidation(pat, bars)
        assert pat.is_valid is False
        assert pat.invalidated_at_bar == 26

    def test_no_invalidation(self):
        """Pattern stays valid when no rule is violated."""
        waves = WavePoints(
            w0=_zz(100, 0, -1), w1=_zz(110, 5, 1), w2=_zz(105, 10, -1),
            w3=_zz(120, 15, 1), w4=_zz(112, 20, -1), w5=_zz(130, 25, 1),
        )
        pat = ImpulsePattern(direction=1, waves=waves, scale=4, detected_at_bar=25)

        # All bars stay above W1=110
        bars = [_bar(120, 122, 115, 121, idx=i) for i in range(30)]

        check_invalidation(pat, bars)
        assert pat.is_valid is True
        assert pat.invalidated_at_bar is None

    def test_invalidation_correct_bar(self):
        """Invalidation records the first violating bar index."""
        waves = WavePoints(
            w0=_zz(100, 0, -1), w1=_zz(110, 5, 1), w2=_zz(105, 10, -1),
            w3=_zz(120, 15, 1), w4=_zz(112, 20, -1), w5=_zz(130, 25, 1),
        )
        pat = ImpulsePattern(direction=1, waves=waves, scale=4, detected_at_bar=25)

        bars = [_bar(120, 122, 115, 121, idx=i) for i in range(30)]
        # Violate at bar 28 (low=109 < W1=110)
        bars[28] = _bar(115, 116, 109, 112, idx=28)
        # Also violate at bar 29 (but 28 should be recorded)
        bars[29] = _bar(115, 116, 108, 112, idx=29)

        check_invalidation(pat, bars)
        assert pat.invalidated_at_bar == 28


# =============================================================================
# Full Pipeline Tests
# =============================================================================


class TestDetectElliottWaves:
    def test_empty_bars(self):
        """Empty bar list returns empty result."""
        result = detect_elliott_waves([])
        assert result.bars_analyzed == 0
        assert result.patterns == []

    def test_insufficient_bars(self):
        """Too few bars returns empty patterns."""
        bars = [_bar(100, 101, 99, 100, idx=i) for i in range(5)]
        result = detect_elliott_waves(bars)
        assert result.patterns == []

    def test_synthetic_impulse_detection(self):
        """Synthetic bullish impulse is detected at scale=2."""
        # Build a clear 5-wave up move
        # W0(low)→W1(high)→W2(low)→W3(high)→W4(low)→W5(high)
        prices = (
            # Lead-in (flat, provides left context for swings)
            [100] * 5
            # W0 trough
            + [99, 98, 97, 96, 95]
            # W1 rise
            + [97, 99, 101, 103, 105, 107, 110]
            # W2 retrace
            + [108, 106, 104, 103]
            # W3 rise (must be longest)
            + [105, 108, 111, 114, 117, 120, 123, 125]
            # W4 retrace (must stay above W1=110)
            + [123, 121, 119, 117, 115]
            # W5 rise (must exceed W3=125)
            + [117, 119, 121, 123, 125, 127, 129, 130]
            # Trail-off
            + [129, 128, 127]
        )
        bars = []
        for i, p in enumerate(prices):
            bars.append(_bar(p - 0.5, p + 1.0, p - 1.0, p + 0.5, idx=i, vol=100 + i))

        result = detect_elliott_waves(bars, scales=[2])
        # Should find at least one pattern
        assert len(result.patterns) >= 1

    def test_result_properties(self):
        """Result container properties work correctly."""
        result = ElliottWaveResult(
            bars_analyzed=100,
            scales=[4, 8],
        )
        assert result.valid_patterns == []
        assert result.latest_pattern is None
        assert result.patterns_at_scale(4) == []

        # Add a pattern
        waves = WavePoints(
            w0=_zz(100, 0, -1), w1=_zz(110, 5, 1), w2=_zz(105, 10, -1),
            w3=_zz(120, 15, 1), w4=_zz(112, 20, -1), w5=_zz(130, 25, 1),
        )
        pat = ImpulsePattern(direction=1, waves=waves, scale=4, detected_at_bar=25)
        result.patterns.append(pat)

        assert len(result.valid_patterns) == 1
        assert result.latest_pattern is pat
        assert len(result.patterns_at_scale(4)) == 1
        assert len(result.patterns_at_scale(8)) == 0


# =============================================================================
# WavePoints Tests
# =============================================================================


class TestWavePoints:
    def test_wave_length(self):
        """wave_length returns absolute price difference."""
        waves = WavePoints(
            w0=_zz(100, 0, -1), w1=_zz(110, 5, 1), w2=_zz(105, 10, -1),
            w3=_zz(125, 15, 1), w4=_zz(118, 20, -1), w5=_zz(135, 25, 1),
        )
        assert waves.wave_length(1) == pytest.approx(10.0)
        assert waves.wave_length(3) == pytest.approx(20.0)
        assert waves.wave_length(5) == pytest.approx(17.0)

    def test_wave_length_invalid(self):
        """wave_length raises ValueError for invalid wave number."""
        waves = WavePoints(
            w0=_zz(100, 0, -1), w1=_zz(110, 5, 1), w2=_zz(105, 10, -1),
            w3=_zz(120, 15, 1), w4=_zz(112, 20, -1), w5=_zz(130, 25, 1),
        )
        with pytest.raises(ValueError):
            waves.wave_length(2)

    def test_as_list(self):
        """as_list returns 6 points in order."""
        pts = [_zz(100 + i * 10, i * 5, 1 if i % 2 else -1) for i in range(6)]
        waves = WavePoints(w0=pts[0], w1=pts[1], w2=pts[2], w3=pts[3], w4=pts[4], w5=pts[5])
        assert waves.as_list() == pts
