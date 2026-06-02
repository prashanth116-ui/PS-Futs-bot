"""Unit tests for runners/rotation_scanner.py."""

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

from runners.rotation_scanner import (
    calc_roc,
    calc_sma,
    calc_cmf,
    normalize_0_100,
    compute_composite,
    filter_interesting_sectors,
    apply_quality_gates,
    classify_stock,
    score_conviction,
    should_alert,
    record_alert,
    clean_state,
    format_sector_alert,
    format_stock_alert,
    SECTOR_ETFS,
    SECTOR_HOLDINGS,
    DEDUP_DAYS,
    DEDUP_EXPIRY_DAYS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sector(**overrides):
    """Create a sector dict with defaults."""
    defaults = {
        "etf": "SMH",
        "name": "Semiconductors",
        "momentum_raw": 5.0,
        "acceleration": 1.5,
        "mansfield_rs": 3.0,
        "rs_ratio": 103.0,
        "rs_momentum": 101.0,
        "cmf": 0.15,
        "cmf_positive_days": 12,
        "breadth_pct": 60.0,
        "smart_money_pct": 55.0,
        "quadrant": "IMPROVING",
        "ret_20d": -1.5,
        "stealth_accumulation": False,
        "stealth_signals": 0,
        "flow_price_div": False,
        "accel_inflection": False,
        "breadth_div": False,
        "composite": 65.0,
        "filter_reasons": [],
    }
    defaults.update(overrides)
    return defaults


def _make_stock(**overrides):
    """Create a stock dict with defaults."""
    defaults = {
        "symbol": "NVDA",
        "etf": "SMH",
        "sector_name": "Semiconductors",
        "price": 120.0,
        "sma50": 115.0,
        "sma200": 100.0,
        "above_50ma": True,
        "pct_from_50ma": 4.3,
        "pct_from_200ma": 20.0,
        "vol_5d": 5_000_000,
        "vol_20d": 4_000_000,
        "vol_ratio": 1.25,
        "ret_20d": 8.5,
        "etf_ret_20d": 5.0,
        "rs_accel": 3.5,
        "market_cap": 80_000_000_000,
        "institutional_pct": 75.0,
        "short_name": "NVIDIA Corporation",
        "sector_quadrant": "IMPROVING",
        "sector_composite": 72.0,
        "sector_stealth": False,
        "sector_acceleration": 1.5,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Technical Indicator Tests
# ---------------------------------------------------------------------------

class TestCalcROC:
    def test_basic(self):
        s = pd.Series([100, 110, 121])
        result = calc_roc(s, 1)
        assert abs(result.iloc[-1] - 10.0) < 0.01

    def test_negative(self):
        s = pd.Series([100, 90, 80])
        result = calc_roc(s, 1)
        assert result.iloc[-1] < 0

    def test_multiperiod(self):
        s = pd.Series([100, 100, 100, 120])
        result = calc_roc(s, 3)
        assert abs(result.iloc[-1] - 20.0) < 0.01


class TestCalcSMA:
    def test_basic(self):
        s = pd.Series([10, 20, 30, 40, 50])
        result = calc_sma(s, 3)
        assert abs(result.iloc[-1] - 40.0) < 0.01

    def test_insufficient_data(self):
        s = pd.Series([10, 20])
        result = calc_sma(s, 3)
        assert pd.isna(result.iloc[-1])


class TestCalcCMF:
    def test_positive_flow(self):
        n = 25
        high = pd.Series([110.0] * n)
        low = pd.Series([90.0] * n)
        # Close near high -> positive CMF
        close = pd.Series([108.0] * n)
        volume = pd.Series([1_000_000] * n)
        result = calc_cmf(high, low, close, volume, 20)
        assert result.iloc[-1] > 0

    def test_negative_flow(self):
        n = 25
        high = pd.Series([110.0] * n)
        low = pd.Series([90.0] * n)
        # Close near low -> negative CMF
        close = pd.Series([92.0] * n)
        volume = pd.Series([1_000_000] * n)
        result = calc_cmf(high, low, close, volume, 20)
        assert result.iloc[-1] < 0


class TestNormalize:
    def test_range(self):
        s = pd.Series([0, 25, 50, 75, 100])
        result = normalize_0_100(s)
        assert abs(result.iloc[0] - 0) < 0.01
        assert abs(result.iloc[-1] - 100) < 0.01

    def test_constant(self):
        s = pd.Series([5, 5, 5])
        result = normalize_0_100(s)
        assert all(abs(v - 50) < 0.01 for v in result)


# ---------------------------------------------------------------------------
# Composite Score Tests
# ---------------------------------------------------------------------------

class TestComposite:
    def test_mid_range(self):
        sector = _make_sector(momentum_raw=0, acceleration=0, mansfield_rs=0,
                              cmf=0, breadth_pct=50, smart_money_pct=50)
        score = compute_composite(sector)
        assert 40 <= score <= 60

    def test_bullish(self):
        sector = _make_sector(momentum_raw=20, acceleration=8, mansfield_rs=15,
                              cmf=0.4, breadth_pct=90, smart_money_pct=80)
        score = compute_composite(sector)
        assert score > 75

    def test_bearish(self):
        sector = _make_sector(momentum_raw=-20, acceleration=-8, mansfield_rs=-15,
                              cmf=-0.4, breadth_pct=10, smart_money_pct=20)
        score = compute_composite(sector)
        assert score < 25


# ---------------------------------------------------------------------------
# Filter Tests
# ---------------------------------------------------------------------------

class TestFilterInteresting:
    def test_improving_quadrant(self):
        sectors = [_make_sector(quadrant="IMPROVING", composite=40)]
        result = filter_interesting_sectors(sectors)
        assert len(result) == 1

    def test_leading_quadrant(self):
        sectors = [_make_sector(quadrant="LEADING", composite=40)]
        result = filter_interesting_sectors(sectors)
        assert len(result) == 1

    def test_lagging_low_composite(self):
        sectors = [_make_sector(quadrant="LAGGING", composite=40,
                                stealth_accumulation=False, acceleration=0.5)]
        result = filter_interesting_sectors(sectors)
        assert len(result) == 0

    def test_high_composite_passes(self):
        sectors = [_make_sector(quadrant="LAGGING", composite=65,
                                stealth_accumulation=False, acceleration=0.5)]
        result = filter_interesting_sectors(sectors)
        assert len(result) == 1

    def test_stealth_accumulation_passes(self):
        sectors = [_make_sector(quadrant="LAGGING", composite=40,
                                stealth_accumulation=True, acceleration=0.5)]
        result = filter_interesting_sectors(sectors)
        assert len(result) == 1

    def test_high_acceleration_passes(self):
        sectors = [_make_sector(quadrant="LAGGING", composite=40,
                                stealth_accumulation=False, acceleration=3.0)]
        result = filter_interesting_sectors(sectors)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Quality Gate Tests
# ---------------------------------------------------------------------------

class TestQualityGates:
    def test_all_pass(self):
        stocks = [_make_stock()]
        passed, rejected = apply_quality_gates(stocks)
        assert len(passed) == 1
        assert len(rejected) == 0

    def test_market_cap_too_low(self):
        stocks = [_make_stock(market_cap=500_000_000)]
        passed, rejected = apply_quality_gates(stocks)
        assert len(passed) == 0
        assert "market_cap" in rejected[0]["rejection_reasons"][0]

    def test_volume_too_low(self):
        stocks = [_make_stock(vol_20d=500_000)]
        passed, rejected = apply_quality_gates(stocks)
        assert len(passed) == 0

    def test_volume_spike(self):
        stocks = [_make_stock(vol_ratio=6.0)]
        passed, rejected = apply_quality_gates(stocks)
        assert len(passed) == 0

    def test_overextended(self):
        stocks = [_make_stock(pct_from_200ma=85)]
        passed, rejected = apply_quality_gates(stocks)
        assert len(passed) == 0

    def test_below_50ma_no_turnaround(self):
        stocks = [_make_stock(above_50ma=False, rs_accel=0.2, vol_ratio=0.8)]
        passed, rejected = apply_quality_gates(stocks)
        assert len(passed) == 0

    def test_below_50ma_with_turnaround(self):
        stocks = [_make_stock(above_50ma=False, rs_accel=1.0, vol_ratio=1.5)]
        passed, rejected = apply_quality_gates(stocks)
        assert len(passed) == 1

    def test_low_institutional(self):
        stocks = [_make_stock(institutional_pct=20)]
        passed, rejected = apply_quality_gates(stocks)
        assert len(passed) == 0

    def test_null_institutional_passes(self):
        stocks = [_make_stock(institutional_pct=None)]
        passed, rejected = apply_quality_gates(stocks)
        assert len(passed) == 1

    def test_uncorrelated_return(self):
        stocks = [_make_stock(ret_20d=45, etf_ret_20d=5)]
        passed, rejected = apply_quality_gates(stocks)
        assert len(passed) == 0

    def test_null_market_cap_passes(self):
        stocks = [_make_stock(market_cap=None)]
        passed, rejected = apply_quality_gates(stocks)
        assert len(passed) == 1


# ---------------------------------------------------------------------------
# Classification Tests
# ---------------------------------------------------------------------------

class TestClassification:
    def test_leader(self):
        s = _make_stock(above_50ma=True, ret_20d=10, etf_ret_20d=5, vol_ratio=1.2)
        result = classify_stock(s)
        assert result["category"] == "LEADER"

    def test_catch_up(self):
        s = _make_stock(above_50ma=True, ret_20d=3, etf_ret_20d=5, vol_ratio=0.8)
        result = classify_stock(s)
        assert result["category"] == "CATCH_UP"

    def test_turnaround(self):
        s = _make_stock(above_50ma=False, rs_accel=1.0, vol_ratio=1.5)
        result = classify_stock(s)
        assert result["category"] == "TURNAROUND"

    def test_avoid(self):
        s = _make_stock(above_50ma=False, rs_accel=0.2, vol_ratio=0.8)
        result = classify_stock(s)
        assert result["category"] == "AVOID"

    def test_p2_turnaround_phase(self):
        s = _make_stock(above_50ma=True, pct_from_50ma=1.5, rs_accel=1.0,
                        vol_ratio=1.3, ret_20d=6, etf_ret_20d=5)
        result = classify_stock(s)
        assert result["phase"] == "P2_TURNAROUND"

    def test_p3_trending_phase(self):
        s = _make_stock(above_50ma=True, pct_from_50ma=8.0, rs_accel=0.5,
                        ret_20d=10, etf_ret_20d=5, vol_ratio=1.2)
        result = classify_stock(s)
        assert result["phase"] == "P3_TRENDING"

    def test_p4_exhausting_phase(self):
        s = _make_stock(above_50ma=True, pct_from_50ma=8.0, rs_accel=-3.0,
                        ret_20d=10, etf_ret_20d=5, vol_ratio=1.2)
        result = classify_stock(s)
        assert result["phase"] == "P4_EXHAUSTING"

    def test_rs_accel_description(self):
        s = _make_stock(rs_accel=4.0, above_50ma=True, ret_20d=10,
                        etf_ret_20d=5, vol_ratio=1.2)
        result = classify_stock(s)
        assert result["rs_accel_desc"] == "strong catch-up"

        s2 = _make_stock(rs_accel=-1.0, above_50ma=True, ret_20d=10,
                         etf_ret_20d=5, vol_ratio=1.2)
        result2 = classify_stock(s2)
        assert result2["rs_accel_desc"] == "decelerating"


# ---------------------------------------------------------------------------
# Conviction Tests
# ---------------------------------------------------------------------------

class TestConviction:
    def test_high_conviction(self):
        s = _make_stock(
            sector_quadrant="IMPROVING",
            sector_composite=75,
            rs_accel=4.0,
            vol_ratio=1.5,
            institutional_pct=60,
            sector_stealth=True,
        )
        s["category"] = "LEADER"
        result = score_conviction(s)
        assert result["conviction"] == "HIGH"

    def test_medium_conviction(self):
        s = _make_stock(
            sector_quadrant="IMPROVING",
            sector_composite=75,
            rs_accel=1.0,
            vol_ratio=0.9,
            institutional_pct=40,
            sector_stealth=False,
        )
        s["category"] = "CATCH_UP"
        result = score_conviction(s)
        assert result["conviction"] == "MEDIUM"

    def test_watch_conviction(self):
        s = _make_stock(
            sector_quadrant="LAGGING",
            sector_composite=40,
            rs_accel=0.5,
            vol_ratio=0.8,
            institutional_pct=30,
            sector_stealth=False,
        )
        s["category"] = "CATCH_UP"
        result = score_conviction(s)
        assert result["conviction"] == "WATCH"


# ---------------------------------------------------------------------------
# Dedup Tests
# ---------------------------------------------------------------------------

class TestDedup:
    def test_new_stock_alerts(self):
        state = {"alerts": {}}
        assert should_alert("NVDA", "HIGH", "LEADER", "P3_TRENDING", state)

    def test_same_within_dedup_window(self):
        state = {"alerts": {"NVDA": {
            "date": date.today().isoformat(),
            "conviction": "HIGH",
            "category": "LEADER",
            "phase": "P3_TRENDING",
        }}}
        assert not should_alert("NVDA", "HIGH", "LEADER", "P3_TRENDING", state)

    def test_conviction_upgrade(self):
        state = {"alerts": {"NVDA": {
            "date": date.today().isoformat(),
            "conviction": "MEDIUM",
            "category": "CATCH_UP",
            "phase": "P3_TRENDING",
        }}}
        assert should_alert("NVDA", "HIGH", "CATCH_UP", "P3_TRENDING", state)

    def test_category_change(self):
        state = {"alerts": {"NVDA": {
            "date": date.today().isoformat(),
            "conviction": "HIGH",
            "category": "CATCH_UP",
            "phase": "P3_TRENDING",
        }}}
        assert should_alert("NVDA", "HIGH", "LEADER", "P3_TRENDING", state)

    def test_phase_transition(self):
        state = {"alerts": {"NVDA": {
            "date": date.today().isoformat(),
            "conviction": "HIGH",
            "category": "LEADER",
            "phase": "P1_BASING",
        }}}
        assert should_alert("NVDA", "HIGH", "LEADER", "P2_TURNAROUND", state)

    def test_expired_entry(self):
        old_date = (date.today() - timedelta(days=DEDUP_EXPIRY_DAYS + 1)).isoformat()
        state = {"alerts": {"NVDA": {
            "date": old_date,
            "conviction": "HIGH",
            "category": "LEADER",
            "phase": "P3_TRENDING",
        }}}
        assert should_alert("NVDA", "HIGH", "LEADER", "P3_TRENDING", state)

    def test_after_dedup_window(self):
        old_date = (date.today() - timedelta(days=DEDUP_DAYS + 1)).isoformat()
        state = {"alerts": {"NVDA": {
            "date": old_date,
            "conviction": "HIGH",
            "category": "LEADER",
            "phase": "P3_TRENDING",
        }}}
        assert should_alert("NVDA", "HIGH", "LEADER", "P3_TRENDING", state)

    def test_record_alert(self):
        state = {"alerts": {}}
        record_alert("NVDA", "HIGH", "LEADER", "P3_TRENDING", state)
        assert "NVDA" in state["alerts"]
        assert state["alerts"]["NVDA"]["conviction"] == "HIGH"

    def test_clean_state(self):
        old_date = (date.today() - timedelta(days=DEDUP_EXPIRY_DAYS + 5)).isoformat()
        state = {"alerts": {
            "OLD": {"date": old_date, "conviction": "HIGH", "category": "LEADER", "phase": "P3"},
            "NEW": {"date": date.today().isoformat(), "conviction": "MEDIUM", "category": "CATCH_UP", "phase": "P2"},
        }}
        clean_state(state)
        assert "OLD" not in state["alerts"]
        assert "NEW" in state["alerts"]


# ---------------------------------------------------------------------------
# Formatting Tests
# ---------------------------------------------------------------------------

class TestFormatting:
    def test_sector_alert(self):
        sector = _make_sector()
        stocks = [
            _make_stock(conviction="HIGH"),
            _make_stock(symbol="AMD", conviction="MEDIUM"),
            _make_stock(symbol="INTC", conviction="WATCH"),
        ]
        msg = format_sector_alert(sector, stocks)
        assert "Semiconductors" in msg
        assert "SMH" in msg
        assert "IMPROVING" in msg
        assert "1 HIGH" in msg
        assert "1 MEDIUM" in msg
        assert "1 WATCH" in msg

    def test_stock_alert(self):
        s = _make_stock()
        s["category"] = "LEADER"
        s["phase"] = "P3_TRENDING"
        s["conviction"] = "HIGH"
        s["rs_accel_desc"] = "strong catch-up"
        msg = format_stock_alert(s)
        assert "NVDA" in msg
        assert "LEADER" in msg
        assert "HIGH" in msg
        assert "$120.00" in msg

    def test_stock_alert_null_institutional(self):
        s = _make_stock(institutional_pct=None, market_cap=None)
        s["category"] = "CATCH_UP"
        s["phase"] = "P3_TRENDING"
        s["conviction"] = "MEDIUM"
        s["rs_accel_desc"] = "moderate"
        msg = format_stock_alert(s)
        assert "N/A" in msg


# ---------------------------------------------------------------------------
# Data Integrity Tests
# ---------------------------------------------------------------------------

class TestDataIntegrity:
    def test_all_etfs_have_holdings(self):
        for etf in SECTOR_ETFS:
            assert etf in SECTOR_HOLDINGS, f"Missing holdings for {etf}"

    def test_holdings_size(self):
        for etf, holdings in SECTOR_HOLDINGS.items():
            assert len(holdings) >= 10, f"{etf} has only {len(holdings)} holdings"
            assert len(holdings) <= 20, f"{etf} has too many holdings: {len(holdings)}"

    def test_no_duplicate_holdings_within_sector(self):
        for etf, holdings in SECTOR_HOLDINGS.items():
            assert len(holdings) == len(set(holdings)), f"Duplicates in {etf}"

    def test_sector_count(self):
        assert len(SECTOR_ETFS) == 14
