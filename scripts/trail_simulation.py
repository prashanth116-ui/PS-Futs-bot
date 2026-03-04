"""
Trail Stop Simulation for ES SHORT CREATION trade on Feb 26, 2026.

Simulates 4 trail stop options bar-by-bar from 6R touch through EOD:
  - Baseline: Current trail logic (check_idx = i-2, swing must improve)
  - Option A: High-water-mark percentage floor (50%, 60%, 70% of max unrealized)
  - Option B: Scan last N bars for swings (3, 5, 7) instead of single bar at i-2
  - Option C: Fix last_swing init (use current_high instead of current_low for SHORT)

Usage:
    python scripts/trail_simulation.py
"""
from __future__ import annotations

import sys
import os
from datetime import time as dt_time, datetime

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.types import Bar
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import is_swing_high

# ─── Trade parameters ────────────────────────────────────────────────
ENTRY_PRICE   = 6956.50
STOP_PRICE    = 6959.75
RISK          = abs(ENTRY_PRICE - STOP_PRICE)      # 3.25 pts
TICK_SIZE     = 0.25
TICK_VALUE    = 12.50
T1_R          = 3       # T1 fixed exit at 3R
TRAIL_R       = 6       # Trail activation at 6R

TARGET_T1     = ENTRY_PRICE - T1_R * RISK           # 3R target
TARGET_6R     = ENTRY_PRICE - TRAIL_R * RISK         # 6R target (trail activation)
PLUS_3R       = ENTRY_PRICE - T1_R * RISK            # 3R floor

DIRECTION     = "SHORT"
ENTRY_TIME_APPROX = dt_time(9, 33)

# ES tick
T2_BUFFER_TICKS    = 4
RUNNER_BUFFER_TICKS = 6


def pts_to_dollars(pts: float, cts: int = 1) -> float:
    """Convert point P/L to dollars."""
    return (pts / TICK_SIZE) * TICK_VALUE * cts


def load_today_bars() -> list[Bar]:
    """Fetch today's ES 3m bars from TradingView."""
    print("Fetching ES 3m bars from TradingView...")
    all_bars = fetch_futures_bars(symbol="ES", interval="3m", n_bars=1000)
    if not all_bars:
        print("ERROR: No bars fetched. Is TradingView session valid?")
        sys.exit(1)

    today = all_bars[-1].timestamp.date()
    today_bars = [b for b in all_bars if b.timestamp.date() == today]

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

    print(f"Date: {today}")
    print(f"Session bars loaded: {len(session_bars)}")
    return session_bars


def find_entry_bar(bars: list[Bar]) -> int:
    """Find the bar index closest to the entry time."""
    for i, b in enumerate(bars):
        if b.timestamp.time() >= ENTRY_TIME_APPROX:
            # Verify price is in the right neighborhood
            if abs(b.close - ENTRY_PRICE) < 10 or abs(b.open - ENTRY_PRICE) < 10:
                return i
            # If price doesn't match, still return time-matched bar
            return i
    print("WARNING: Could not find entry bar by time, using bar 0")
    return 0


def find_6r_touch_bar(bars: list[Bar], entry_idx: int) -> int:
    """Find the first bar where price reaches the 6R target (SHORT: low <= target_6r)."""
    for i in range(entry_idx, len(bars)):
        if bars[i].low <= TARGET_6R:
            return i
    return -1


def find_t1_exit_bar(bars: list[Bar], entry_idx: int) -> int:
    """Find the first bar where T1 target is hit (SHORT: low <= target_t1)."""
    for i in range(entry_idx, len(bars)):
        if bars[i].low <= TARGET_T1:
            return i
    return -1


# ─── Baseline simulation ─────────────────────────────────────────────

def simulate_baseline(bars: list[Bar], entry_idx: int, r6_idx: int) -> dict:
    """
    Baseline trail logic: check only bar at i-2, swing high must be LOWER than
    previous t2_last_swing to tighten trail DOWN (for SHORT).
    """
    # At 6R touch: initialize
    t2_trail_stop = PLUS_3R  # floor at 3R
    t2_last_swing = bars[r6_idx].low   # init to bar LOW (current logic)
    runner_stop = PLUS_3R
    runner_last_swing = bars[r6_idx].low

    t2_exit_price = None
    t2_exit_time = None
    t2_exit_bar = None
    runner_exit_price = None
    runner_exit_time = None
    runner_exit_bar = None
    t2_exited = False

    trail_log = []

    for i in range(r6_idx + 1, len(bars)):
        bar = bars[i]

        # --- T2 trail update (4-tick buffer) ---
        if not t2_exited:
            check_idx = i - 2
            if check_idx > entry_idx and check_idx < len(bars):
                if is_swing_high(bars, check_idx, lookback=2):
                    swing = bars[check_idx].high
                    if swing < t2_last_swing:
                        new_trail = swing + (T2_BUFFER_TICKS * TICK_SIZE)
                        if new_trail < t2_trail_stop:
                            t2_trail_stop = new_trail
                            t2_last_swing = swing

        # --- Runner trail update (6-tick buffer, only after T2 exits) ---
        if t2_exited:
            check_idx = i - 2
            if check_idx > entry_idx and check_idx < len(bars):
                if is_swing_high(bars, check_idx, lookback=2):
                    swing = bars[check_idx].high
                    if swing < runner_last_swing:
                        new_trail = swing + (RUNNER_BUFFER_TICKS * TICK_SIZE)
                        if new_trail < runner_stop:
                            runner_stop = new_trail
                            runner_last_swing = swing

        # --- Check T2 stop hit ---
        if not t2_exited:
            if bar.high >= t2_trail_stop:
                t2_exit_price = t2_trail_stop
                t2_exit_time = bar.timestamp
                t2_exit_bar = i
                t2_exited = True

        # --- Check Runner stop hit ---
        if t2_exited and runner_exit_price is None:
            if bar.high >= runner_stop:
                runner_exit_price = runner_stop
                runner_exit_time = bar.timestamp
                runner_exit_bar = i

        # Log trail state at key bars
        unrealized_t2 = ENTRY_PRICE - bar.low if not t2_exited else None
        unrealized_runner = ENTRY_PRICE - bar.low if runner_exit_price is None else None
        trail_log.append({
            'bar_idx': i,
            'time': bar.timestamp.strftime('%H:%M'),
            'high': bar.high,
            'low': bar.low,
            't2_trail': t2_trail_stop if not t2_exited else None,
            'runner_trail': runner_stop if runner_exit_price is None else None,
            't2_exited': t2_exited,
            'runner_exited': runner_exit_price is not None,
        })

        if t2_exited and runner_exit_price is not None:
            break

    # EOD handling
    last_bar = bars[-1]
    if not t2_exited:
        t2_exit_price = last_bar.close
        t2_exit_time = last_bar.timestamp
        t2_exit_bar = len(bars) - 1
    if runner_exit_price is None:
        runner_exit_price = last_bar.close
        runner_exit_time = last_bar.timestamp
        runner_exit_bar = len(bars) - 1

    t2_pnl_pts = ENTRY_PRICE - t2_exit_price
    runner_pnl_pts = ENTRY_PRICE - runner_exit_price

    return {
        'name': 'Baseline',
        't2_exit_price': t2_exit_price,
        't2_exit_time': t2_exit_time,
        't2_exit_bar': t2_exit_bar,
        't2_pnl_pts': t2_pnl_pts,
        't2_pnl_dollars': pts_to_dollars(t2_pnl_pts),
        'runner_exit_price': runner_exit_price,
        'runner_exit_time': runner_exit_time,
        'runner_exit_bar': runner_exit_bar,
        'runner_pnl_pts': runner_pnl_pts,
        'runner_pnl_dollars': pts_to_dollars(runner_pnl_pts),
        'total_pnl_dollars': pts_to_dollars(t2_pnl_pts) + pts_to_dollars(runner_pnl_pts),
        'trail_log': trail_log,
    }


# ─── Option A: High-water-mark percentage floor ──────────────────────

def simulate_option_a(bars: list[Bar], entry_idx: int, r6_idx: int, pct: float) -> dict:
    """
    After 6R touch, track max unrealized profit. When unrealized > threshold,
    set a trailing floor at pct% of max unrealized profit.
    This acts as a backup alongside the structure trail.
    """
    # At 6R touch: initialize (same as baseline)
    t2_trail_stop = PLUS_3R
    t2_last_swing = bars[r6_idx].low
    runner_stop = PLUS_3R
    runner_last_swing = bars[r6_idx].low

    # Option A: high-water-mark tracking
    max_unrealized_t2 = ENTRY_PRICE - bars[r6_idx].low
    max_unrealized_runner = max_unrealized_t2
    hwm_t2_floor = PLUS_3R
    hwm_runner_floor = PLUS_3R

    t2_exit_price = None
    t2_exit_time = None
    t2_exit_bar = None
    runner_exit_price = None
    runner_exit_time = None
    runner_exit_bar = None
    t2_exited = False

    trail_log = []

    for i in range(r6_idx + 1, len(bars)):
        bar = bars[i]

        # Update max unrealized (SHORT: profit = entry - low)
        current_unrealized = ENTRY_PRICE - bar.low
        if not t2_exited:
            if current_unrealized > max_unrealized_t2:
                max_unrealized_t2 = current_unrealized
            # Set HWM floor: entry - pct * max_profit  (for SHORT, floor is ABOVE current price)
            hwm_floor_price = ENTRY_PRICE - (pct * max_unrealized_t2)
            if hwm_floor_price < hwm_t2_floor:
                hwm_t2_floor = hwm_floor_price

        if runner_exit_price is None:
            if current_unrealized > max_unrealized_runner:
                max_unrealized_runner = current_unrealized
            hwm_runner_price = ENTRY_PRICE - (pct * max_unrealized_runner)
            if hwm_runner_price < hwm_runner_floor:
                hwm_runner_floor = hwm_runner_price

        # --- Baseline T2 trail update ---
        if not t2_exited:
            check_idx = i - 2
            if check_idx > entry_idx and check_idx < len(bars):
                if is_swing_high(bars, check_idx, lookback=2):
                    swing = bars[check_idx].high
                    if swing < t2_last_swing:
                        new_trail = swing + (T2_BUFFER_TICKS * TICK_SIZE)
                        if new_trail < t2_trail_stop:
                            t2_trail_stop = new_trail
                            t2_last_swing = swing

        # --- Baseline Runner trail update ---
        if t2_exited:
            check_idx = i - 2
            if check_idx > entry_idx and check_idx < len(bars):
                if is_swing_high(bars, check_idx, lookback=2):
                    swing = bars[check_idx].high
                    if swing < runner_last_swing:
                        new_trail = swing + (RUNNER_BUFFER_TICKS * TICK_SIZE)
                        if new_trail < runner_stop:
                            runner_stop = new_trail
                            runner_last_swing = swing

        # Use the TIGHTER (lower for SHORT) of structure trail and HWM floor
        effective_t2_stop = min(t2_trail_stop, hwm_t2_floor) if not t2_exited else None
        effective_runner_stop = min(runner_stop, hwm_runner_floor) if runner_exit_price is None else None

        # --- Check T2 stop hit (using effective stop) ---
        if not t2_exited:
            if bar.high >= effective_t2_stop:
                t2_exit_price = effective_t2_stop
                t2_exit_time = bar.timestamp
                t2_exit_bar = i
                t2_exited = True

        # --- Check Runner stop hit ---
        if t2_exited and runner_exit_price is None:
            if bar.high >= effective_runner_stop:
                runner_exit_price = effective_runner_stop
                runner_exit_time = bar.timestamp
                runner_exit_bar = i

        trail_log.append({
            'bar_idx': i,
            'time': bar.timestamp.strftime('%H:%M'),
            'high': bar.high,
            'low': bar.low,
            't2_trail': effective_t2_stop if not t2_exited else None,
            'runner_trail': effective_runner_stop,
            't2_exited': t2_exited,
            'runner_exited': runner_exit_price is not None,
            'max_unreal_t2': max_unrealized_t2,
            'max_unreal_runner': max_unrealized_runner,
            'hwm_t2_floor': hwm_t2_floor,
            'hwm_runner_floor': hwm_runner_floor,
        })

        if t2_exited and runner_exit_price is not None:
            break

    # EOD handling
    last_bar = bars[-1]
    if not t2_exited:
        t2_exit_price = last_bar.close
        t2_exit_time = last_bar.timestamp
        t2_exit_bar = len(bars) - 1
    if runner_exit_price is None:
        runner_exit_price = last_bar.close
        runner_exit_time = last_bar.timestamp
        runner_exit_bar = len(bars) - 1

    t2_pnl_pts = ENTRY_PRICE - t2_exit_price
    runner_pnl_pts = ENTRY_PRICE - runner_exit_price

    return {
        'name': f'Option A ({int(pct*100)}% HWM)',
        't2_exit_price': t2_exit_price,
        't2_exit_time': t2_exit_time,
        't2_exit_bar': t2_exit_bar,
        't2_pnl_pts': t2_pnl_pts,
        't2_pnl_dollars': pts_to_dollars(t2_pnl_pts),
        'runner_exit_price': runner_exit_price,
        'runner_exit_time': runner_exit_time,
        'runner_exit_bar': runner_exit_bar,
        'runner_pnl_pts': runner_pnl_pts,
        'runner_pnl_dollars': pts_to_dollars(runner_pnl_pts),
        'total_pnl_dollars': pts_to_dollars(t2_pnl_pts) + pts_to_dollars(runner_pnl_pts),
        'trail_log': trail_log,
    }


# ─── Option B: Scan more bars for swing detection ────────────────────

def simulate_option_b(bars: list[Bar], entry_idx: int, r6_idx: int, scan_n: int) -> dict:
    """
    Instead of checking only bar at i-2 for swing highs, scan the last N bars
    (from i-scan_n to i-1) to find any swing highs.
    """
    t2_trail_stop = PLUS_3R
    t2_last_swing = bars[r6_idx].low  # same init as baseline
    runner_stop = PLUS_3R
    runner_last_swing = bars[r6_idx].low

    t2_exit_price = None
    t2_exit_time = None
    t2_exit_bar = None
    runner_exit_price = None
    runner_exit_time = None
    runner_exit_bar = None
    t2_exited = False

    trail_log = []

    for i in range(r6_idx + 1, len(bars)):
        bar = bars[i]

        # --- T2 trail update: scan last N bars ---
        if not t2_exited:
            for offset in range(2, 2 + scan_n):
                check_idx = i - offset
                if check_idx <= entry_idx or check_idx >= len(bars):
                    continue
                if is_swing_high(bars, check_idx, lookback=2):
                    swing = bars[check_idx].high
                    if swing < t2_last_swing:
                        new_trail = swing + (T2_BUFFER_TICKS * TICK_SIZE)
                        if new_trail < t2_trail_stop:
                            t2_trail_stop = new_trail
                            t2_last_swing = swing

        # --- Runner trail update: scan last N bars ---
        if t2_exited:
            for offset in range(2, 2 + scan_n):
                check_idx = i - offset
                if check_idx <= entry_idx or check_idx >= len(bars):
                    continue
                if is_swing_high(bars, check_idx, lookback=2):
                    swing = bars[check_idx].high
                    if swing < runner_last_swing:
                        new_trail = swing + (RUNNER_BUFFER_TICKS * TICK_SIZE)
                        if new_trail < runner_stop:
                            runner_stop = new_trail
                            runner_last_swing = swing

        # --- Check T2 stop hit ---
        if not t2_exited:
            if bar.high >= t2_trail_stop:
                t2_exit_price = t2_trail_stop
                t2_exit_time = bar.timestamp
                t2_exit_bar = i
                t2_exited = True

        # --- Check Runner stop hit ---
        if t2_exited and runner_exit_price is None:
            if bar.high >= runner_stop:
                runner_exit_price = runner_stop
                runner_exit_time = bar.timestamp
                runner_exit_bar = i

        trail_log.append({
            'bar_idx': i,
            'time': bar.timestamp.strftime('%H:%M'),
            'high': bar.high,
            'low': bar.low,
            't2_trail': t2_trail_stop if not t2_exited else None,
            'runner_trail': runner_stop if runner_exit_price is None else None,
            't2_exited': t2_exited,
            'runner_exited': runner_exit_price is not None,
        })

        if t2_exited and runner_exit_price is not None:
            break

    # EOD handling
    last_bar = bars[-1]
    if not t2_exited:
        t2_exit_price = last_bar.close
        t2_exit_time = last_bar.timestamp
        t2_exit_bar = len(bars) - 1
    if runner_exit_price is None:
        runner_exit_price = last_bar.close
        runner_exit_time = last_bar.timestamp
        runner_exit_bar = len(bars) - 1

    t2_pnl_pts = ENTRY_PRICE - t2_exit_price
    runner_pnl_pts = ENTRY_PRICE - runner_exit_price

    return {
        'name': f'Option B (scan {scan_n} bars)',
        't2_exit_price': t2_exit_price,
        't2_exit_time': t2_exit_time,
        't2_exit_bar': t2_exit_bar,
        't2_pnl_pts': t2_pnl_pts,
        't2_pnl_dollars': pts_to_dollars(t2_pnl_pts),
        'runner_exit_price': runner_exit_price,
        'runner_exit_time': runner_exit_time,
        'runner_exit_bar': runner_exit_bar,
        'runner_pnl_pts': runner_pnl_pts,
        'runner_pnl_dollars': pts_to_dollars(runner_pnl_pts),
        'total_pnl_dollars': pts_to_dollars(t2_pnl_pts) + pts_to_dollars(runner_pnl_pts),
        'trail_log': trail_log,
    }


# ─── Option C: Fix last_swing initialization ─────────────────────────

def simulate_option_c(bars: list[Bar], entry_idx: int, r6_idx: int) -> dict:
    """
    At 6R touch, initialize t2_last_swing = bar.HIGH instead of bar.LOW.
    For SHORT trades this means the very first swing high can be accepted immediately
    because it will always be <= the high of the 6R bar.
    """
    t2_trail_stop = PLUS_3R
    t2_last_swing = bars[r6_idx].high   # CHANGED: use HIGH not LOW
    runner_stop = PLUS_3R
    runner_last_swing = bars[r6_idx].high   # CHANGED: use HIGH not LOW

    t2_exit_price = None
    t2_exit_time = None
    t2_exit_bar = None
    runner_exit_price = None
    runner_exit_time = None
    runner_exit_bar = None
    t2_exited = False

    trail_log = []

    for i in range(r6_idx + 1, len(bars)):
        bar = bars[i]

        # --- T2 trail update (same as baseline, just different init) ---
        if not t2_exited:
            check_idx = i - 2
            if check_idx > entry_idx and check_idx < len(bars):
                if is_swing_high(bars, check_idx, lookback=2):
                    swing = bars[check_idx].high
                    if swing < t2_last_swing:
                        new_trail = swing + (T2_BUFFER_TICKS * TICK_SIZE)
                        if new_trail < t2_trail_stop:
                            t2_trail_stop = new_trail
                            t2_last_swing = swing

        # --- Runner trail update ---
        if t2_exited:
            check_idx = i - 2
            if check_idx > entry_idx and check_idx < len(bars):
                if is_swing_high(bars, check_idx, lookback=2):
                    swing = bars[check_idx].high
                    if swing < runner_last_swing:
                        new_trail = swing + (RUNNER_BUFFER_TICKS * TICK_SIZE)
                        if new_trail < runner_stop:
                            runner_stop = new_trail
                            runner_last_swing = swing

        # --- Check T2 stop hit ---
        if not t2_exited:
            if bar.high >= t2_trail_stop:
                t2_exit_price = t2_trail_stop
                t2_exit_time = bar.timestamp
                t2_exit_bar = i
                t2_exited = True

        # --- Check Runner stop hit ---
        if t2_exited and runner_exit_price is None:
            if bar.high >= runner_stop:
                runner_exit_price = runner_stop
                runner_exit_time = bar.timestamp
                runner_exit_bar = i

        trail_log.append({
            'bar_idx': i,
            'time': bar.timestamp.strftime('%H:%M'),
            'high': bar.high,
            'low': bar.low,
            't2_trail': t2_trail_stop if not t2_exited else None,
            'runner_trail': runner_stop if runner_exit_price is None else None,
            't2_exited': t2_exited,
            'runner_exited': runner_exit_price is not None,
        })

        if t2_exited and runner_exit_price is not None:
            break

    # EOD handling
    last_bar = bars[-1]
    if not t2_exited:
        t2_exit_price = last_bar.close
        t2_exit_time = last_bar.timestamp
        t2_exit_bar = len(bars) - 1
    if runner_exit_price is None:
        runner_exit_price = last_bar.close
        runner_exit_time = last_bar.timestamp
        runner_exit_bar = len(bars) - 1

    t2_pnl_pts = ENTRY_PRICE - t2_exit_price
    runner_pnl_pts = ENTRY_PRICE - runner_exit_price

    return {
        'name': 'Option C (init HIGH)',
        't2_exit_price': t2_exit_price,
        't2_exit_time': t2_exit_time,
        't2_exit_bar': t2_exit_bar,
        't2_pnl_pts': t2_pnl_pts,
        't2_pnl_dollars': pts_to_dollars(t2_pnl_pts),
        'runner_exit_price': runner_exit_price,
        'runner_exit_time': runner_exit_time,
        'runner_exit_bar': runner_exit_bar,
        'runner_pnl_pts': runner_pnl_pts,
        'runner_pnl_dollars': pts_to_dollars(runner_pnl_pts),
        'total_pnl_dollars': pts_to_dollars(t2_pnl_pts) + pts_to_dollars(runner_pnl_pts),
        'trail_log': trail_log,
    }


# ─── Combined Option B+C ─────────────────────────────────────────────

def simulate_option_bc(bars: list[Bar], entry_idx: int, r6_idx: int, scan_n: int) -> dict:
    """
    Combine Option B (scan N bars) + Option C (init last_swing to HIGH).
    """
    t2_trail_stop = PLUS_3R
    t2_last_swing = bars[r6_idx].high   # Option C: HIGH
    runner_stop = PLUS_3R
    runner_last_swing = bars[r6_idx].high

    t2_exit_price = None
    t2_exit_time = None
    t2_exit_bar = None
    runner_exit_price = None
    runner_exit_time = None
    runner_exit_bar = None
    t2_exited = False

    trail_log = []

    for i in range(r6_idx + 1, len(bars)):
        bar = bars[i]

        # --- T2 trail update: scan last N bars (Option B) ---
        if not t2_exited:
            for offset in range(2, 2 + scan_n):
                check_idx = i - offset
                if check_idx <= entry_idx or check_idx >= len(bars):
                    continue
                if is_swing_high(bars, check_idx, lookback=2):
                    swing = bars[check_idx].high
                    if swing < t2_last_swing:
                        new_trail = swing + (T2_BUFFER_TICKS * TICK_SIZE)
                        if new_trail < t2_trail_stop:
                            t2_trail_stop = new_trail
                            t2_last_swing = swing

        # --- Runner trail update ---
        if t2_exited:
            for offset in range(2, 2 + scan_n):
                check_idx = i - offset
                if check_idx <= entry_idx or check_idx >= len(bars):
                    continue
                if is_swing_high(bars, check_idx, lookback=2):
                    swing = bars[check_idx].high
                    if swing < runner_last_swing:
                        new_trail = swing + (RUNNER_BUFFER_TICKS * TICK_SIZE)
                        if new_trail < runner_stop:
                            runner_stop = new_trail
                            runner_last_swing = swing

        # --- Check T2 stop hit ---
        if not t2_exited:
            if bar.high >= t2_trail_stop:
                t2_exit_price = t2_trail_stop
                t2_exit_time = bar.timestamp
                t2_exit_bar = i
                t2_exited = True

        # --- Check Runner stop hit ---
        if t2_exited and runner_exit_price is None:
            if bar.high >= runner_stop:
                runner_exit_price = runner_stop
                runner_exit_time = bar.timestamp
                runner_exit_bar = i

        trail_log.append({
            'bar_idx': i,
            'time': bar.timestamp.strftime('%H:%M'),
            'high': bar.high,
            'low': bar.low,
            't2_trail': t2_trail_stop if not t2_exited else None,
            'runner_trail': runner_stop if runner_exit_price is None else None,
            't2_exited': t2_exited,
            'runner_exited': runner_exit_price is not None,
        })

        if t2_exited and runner_exit_price is not None:
            break

    # EOD handling
    last_bar = bars[-1]
    if not t2_exited:
        t2_exit_price = last_bar.close
        t2_exit_time = last_bar.timestamp
        t2_exit_bar = len(bars) - 1
    if runner_exit_price is None:
        runner_exit_price = last_bar.close
        runner_exit_time = last_bar.timestamp
        runner_exit_bar = len(bars) - 1

    t2_pnl_pts = ENTRY_PRICE - t2_exit_price
    runner_pnl_pts = ENTRY_PRICE - runner_exit_price

    return {
        'name': f'Option B+C (scan {scan_n}, init HIGH)',
        't2_exit_price': t2_exit_price,
        't2_exit_time': t2_exit_time,
        't2_exit_bar': t2_exit_bar,
        't2_pnl_pts': t2_pnl_pts,
        't2_pnl_dollars': pts_to_dollars(t2_pnl_pts),
        'runner_exit_price': runner_exit_price,
        'runner_exit_time': runner_exit_time,
        'runner_exit_bar': runner_exit_bar,
        'runner_pnl_pts': runner_pnl_pts,
        'runner_pnl_dollars': pts_to_dollars(runner_pnl_pts),
        'total_pnl_dollars': pts_to_dollars(t2_pnl_pts) + pts_to_dollars(runner_pnl_pts),
        'trail_log': trail_log,
    }


# ─── Printing ─────────────────────────────────────────────────────────

def print_comparison(results: list[dict], bars: list[Bar], entry_idx: int, r6_idx: int):
    """Print a comparison table and key moment trail levels."""
    # Include T1 fixed exit in total P/L
    t1_pnl_pts = ENTRY_PRICE - TARGET_T1
    t1_dollars = pts_to_dollars(t1_pnl_pts)

    print()
    print("=" * 110)
    print("TRAIL STOP SIMULATION RESULTS")
    print(f"Trade: SHORT ES @ {ENTRY_PRICE:.2f}  |  Stop: {STOP_PRICE:.2f}  |  Risk: {RISK:.2f} pts")
    print(f"T1 target (3R): {TARGET_T1:.2f}  |  6R target: {TARGET_6R:.2f}  |  3R floor: {PLUS_3R:.2f}")
    print(f"T1 fixed exit: 1ct @ {TARGET_T1:.2f} = ${t1_dollars:+,.2f}")
    print("=" * 110)
    print()

    # Find key bars for reference
    session_low = min(b.low for b in bars[entry_idx:])
    session_low_bar = None
    for i in range(entry_idx, len(bars)):
        if bars[i].low == session_low:
            session_low_bar = i
            break

    print(f"Key reference: Session low = {session_low:.2f} @ bar {session_low_bar}"
          f" ({bars[session_low_bar].timestamp.strftime('%H:%M')})")
    print(f"               6R touched at bar {r6_idx} ({bars[r6_idx].timestamp.strftime('%H:%M')})")
    print()

    # Comparison table
    hdr = f"{'Option':<30} | {'T2 Exit':>10} {'T2 Time':>8} {'T2 P/L':>12} | {'Runner Exit':>11} {'Run Time':>8} {'Run P/L':>12} | {'T2+Run $':>12} | {'Total(+T1)':>12}"
    print(hdr)
    print("-" * len(hdr))

    for r in results:
        t2_time_str = r['t2_exit_time'].strftime('%H:%M') if r['t2_exit_time'] else 'EOD'
        run_time_str = r['runner_exit_time'].strftime('%H:%M') if r['runner_exit_time'] else 'EOD'
        total_with_t1 = r['total_pnl_dollars'] + t1_dollars

        print(f"{r['name']:<30} | "
              f"{r['t2_exit_price']:>10.2f} {t2_time_str:>8} {r['t2_pnl_dollars']:>+12,.2f} | "
              f"{r['runner_exit_price']:>11.2f} {run_time_str:>8} {r['runner_pnl_dollars']:>+12,.2f} | "
              f"{r['total_pnl_dollars']:>+12,.2f} | "
              f"{total_with_t1:>+12,.2f}")

    print()

    # --- Trail level at key moments ---
    print("=" * 110)
    print("TRAIL LEVELS AT KEY MOMENTS")
    print("=" * 110)

    # Key moments: 6R bar, session low bar, start of reversal, a few snapshots
    # We'll show trail levels from the baseline and all options at specific times
    key_times = set()

    # Add 6R touch
    key_times.add(r6_idx + 1)

    # Add session low bar
    if session_low_bar:
        key_times.add(session_low_bar)

    # Add bars at rough 15-min intervals after 6R for the interesting period
    for i in range(r6_idx, min(len(bars), r6_idx + 80), 5):
        key_times.add(i)

    # Add exit bars from all results
    for r in results:
        if r['t2_exit_bar'] is not None:
            key_times.add(r['t2_exit_bar'])
        if r['runner_exit_bar'] is not None:
            key_times.add(r['runner_exit_bar'])

    key_times = sorted(key_times)

    # Header for trail levels
    print(f"\n{'Bar':>4} {'Time':>6} {'High':>9} {'Low':>9} | ", end="")
    for r in results:
        short_name = r['name'][:18]
        print(f"{short_name:>18} ", end="")
    print()
    print("-" * (36 + 19 * len(results)))

    for ki in key_times:
        if ki >= len(bars) or ki < r6_idx:
            continue
        b = bars[ki]
        offset = ki - r6_idx

        # Collect trail levels from each result's log
        print(f"{ki:>4} {b.timestamp.strftime('%H:%M'):>6} {b.high:>9.2f} {b.low:>9.2f} | ", end="")

        for r in results:
            # Find this bar in the trail log
            log_entry = None
            for le in r['trail_log']:
                if le['bar_idx'] == ki:
                    log_entry = le
                    break

            if log_entry is None:
                # Before trail started or after both exited
                if ki <= r6_idx:
                    print(f"{'(pre-6R)':>18} ", end="")
                else:
                    print(f"{'(done)':>18} ", end="")
            else:
                t2_str = f"T2={log_entry['t2_trail']:.2f}" if log_entry['t2_trail'] is not None else "T2=EXIT"
                run_str = f"R={log_entry['runner_trail']:.2f}" if log_entry['runner_trail'] is not None else "R=EXIT"
                combined = f"{t2_str} {run_str}"
                print(f"{combined:>18} ", end="")
        print()

    print()

    # ---- Swing high detection log for baseline ----
    print("=" * 110)
    print("SWING HIGHS DETECTED (baseline check_idx = i-2)")
    print("=" * 110)
    swings_found = []
    for i in range(r6_idx + 1, len(bars)):
        check_idx = i - 2
        if check_idx > entry_idx and check_idx < len(bars):
            if is_swing_high(bars, check_idx, lookback=2):
                swings_found.append((check_idx, bars[check_idx].high, bars[i].timestamp.strftime('%H:%M')))

    if swings_found:
        print(f"{'Check Bar':>10} {'Swing High':>12} {'Detected At':>12}")
        print("-" * 36)
        for idx, sh, detected_at in swings_found:
            print(f"{idx:>10} {sh:>12.2f} {detected_at:>12}")
    else:
        print("  No swing highs detected in the post-6R range!")

    print()

    # ---- Trail update trace for baseline ----
    print("=" * 110)
    print("BASELINE TRAIL UPDATE TRACE (showing when trail actually moves)")
    print("=" * 110)
    baseline = results[0]
    prev_t2 = PLUS_3R
    prev_runner = PLUS_3R
    t2_done = False
    for le in baseline['trail_log']:
        t2_val = le.get('t2_trail')
        run_val = le.get('runner_trail')
        # Detect T2 trail tightening
        if t2_val is not None and t2_val != prev_t2:
            print(f"  Bar {le['bar_idx']:>4} ({le['time']}): T2 trail tightened {prev_t2:.2f} -> {t2_val:.2f}"
                  f"  (bar H={le['high']:.2f} L={le['low']:.2f})")
            prev_t2 = t2_val
        # Detect T2 exit
        if t2_val is None and not t2_done:
            print(f"  Bar {le['bar_idx']:>4} ({le['time']}): T2 EXITED (trail was {prev_t2:.2f}, bar H={le['high']:.2f})")
            t2_done = True
        # Detect runner trail tightening
        if run_val is not None and run_val != prev_runner:
            print(f"  Bar {le['bar_idx']:>4} ({le['time']}): Runner trail tightened {prev_runner:.2f} -> {run_val:.2f}"
                  f"  (bar H={le['high']:.2f} L={le['low']:.2f})")
            prev_runner = run_val
        # Detect runner exit
        if run_val is None and le.get('runner_exited'):
            if le['bar_idx'] == baseline['runner_exit_bar']:
                print(f"  Bar {le['bar_idx']:>4} ({le['time']}): Runner EXITED (trail was {prev_runner:.2f}, bar H={le['high']:.2f})")

    print()


def main():
    bars = load_today_bars()

    # Find entry bar
    entry_idx = find_entry_bar(bars)
    entry_bar = bars[entry_idx]
    print(f"\nEntry bar: idx={entry_idx}, time={entry_bar.timestamp.strftime('%H:%M')}, "
          f"O={entry_bar.open:.2f} H={entry_bar.high:.2f} L={entry_bar.low:.2f} C={entry_bar.close:.2f}")

    # Find T1 exit bar
    t1_idx = find_t1_exit_bar(bars, entry_idx)
    if t1_idx >= 0:
        print(f"T1 (3R={TARGET_T1:.2f}) hit at bar {t1_idx} ({bars[t1_idx].timestamp.strftime('%H:%M')})")
    else:
        print(f"T1 (3R={TARGET_T1:.2f}) never hit!")

    # Find 6R touch bar
    r6_idx = find_6r_touch_bar(bars, entry_idx)
    if r6_idx < 0:
        print(f"\n6R target ({TARGET_6R:.2f}) never reached! Cannot simulate trail options.")
        print("Check if the entry price parameters match today's actual trade.")

        # Show price range context
        post_entry = bars[entry_idx:]
        if post_entry:
            low_bar = min(post_entry, key=lambda b: b.low)
            print(f"Lowest price after entry: {low_bar.low:.2f} at {low_bar.timestamp.strftime('%H:%M')}")
            print(f"Needed price to reach: {TARGET_6R:.2f}")
            print(f"Gap: {low_bar.low - TARGET_6R:.2f} pts")
        sys.exit(1)

    print(f"6R ({TARGET_6R:.2f}) touched at bar {r6_idx} ({bars[r6_idx].timestamp.strftime('%H:%M')})")
    print(f"  Bar OHLC: O={bars[r6_idx].open:.2f} H={bars[r6_idx].high:.2f} L={bars[r6_idx].low:.2f} C={bars[r6_idx].close:.2f}")

    # Show price context
    post_entry = bars[entry_idx:]
    session_low = min(b.low for b in post_entry)
    low_bar = min(post_entry, key=lambda b: b.low)
    print(f"Session low after entry: {session_low:.2f} at {low_bar.timestamp.strftime('%H:%M')}")
    print(f"Max unrealized profit: {ENTRY_PRICE - session_low:.2f} pts = ${pts_to_dollars(ENTRY_PRICE - session_low):,.2f}")

    last_bar = bars[-1]
    print(f"\nLast bar: {last_bar.timestamp.strftime('%H:%M')} (close={last_bar.close:.2f})")
    if last_bar.timestamp.time() < dt_time(16, 0):
        print("NOTE: Session is still in progress. Runner may show mid-session exit instead of EOD.")
        print("      Re-run after 16:00 ET for final EOD results.")

    # --- Run all simulations ---
    results = []

    # Baseline
    results.append(simulate_baseline(bars, entry_idx, r6_idx))

    # Option A: HWM percentage floors
    for pct in [0.50, 0.60, 0.70]:
        results.append(simulate_option_a(bars, entry_idx, r6_idx, pct))

    # Option B: Scan more bars
    for scan_n in [3, 5, 7]:
        results.append(simulate_option_b(bars, entry_idx, r6_idx, scan_n))

    # Option C: Fix last_swing init
    results.append(simulate_option_c(bars, entry_idx, r6_idx))

    # Bonus: Combined B+C (scan 5 + init HIGH)
    results.append(simulate_option_bc(bars, entry_idx, r6_idx, 5))

    # Print comparison
    print_comparison(results, bars, entry_idx, r6_idx)

    # --- Best option summary ---
    print("=" * 110)
    print("RANKING BY TOTAL P/L (T2 + Runner, excluding T1)")
    print("=" * 110)
    ranked = sorted(results, key=lambda r: r['total_pnl_dollars'], reverse=True)
    for i, r in enumerate(ranked, 1):
        t1_dollars = pts_to_dollars(ENTRY_PRICE - TARGET_T1)
        total_with_t1 = r['total_pnl_dollars'] + t1_dollars
        baseline_diff = r['total_pnl_dollars'] - results[0]['total_pnl_dollars']
        diff_str = f"({'+' if baseline_diff >= 0 else ''}{baseline_diff:,.2f} vs baseline)" if i > 1 or r['name'] != 'Baseline' else "(baseline)"
        print(f"  {i}. {r['name']:<30} T2+Runner: ${r['total_pnl_dollars']:>+10,.2f}  "
              f"Total(+T1): ${total_with_t1:>+10,.2f}  {diff_str}")

    print()


if __name__ == "__main__":
    main()
