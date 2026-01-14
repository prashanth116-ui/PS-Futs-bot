"""
Unit Tests for ICT Strategy Pipeline

Tests the full signal flow: Sweep -> BOS -> FVG -> Signal

Run with: python -m pytest tests/test_ict_strategy.py -v
Or directly: python tests/test_ict_strategy.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.types import Bar, Direction, Signal
from strategies.ict.ict_strategy import ICTStrategy


# =============================================================================
# Test Fixtures - Synthetic Bar Data
# =============================================================================

ET = ZoneInfo("America/New_York")


def make_bar(
    timestamp: datetime,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: int = 1000,
    symbol: str = "ES",
) -> Bar:
    """Helper to create a Bar object."""
    return Bar(
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        symbol=symbol,
        timeframe="5m",
    )


def create_bullish_setup_bars() -> list[Bar]:
    """
    Create bars that form a BULLISH ICT setup:
    1. Establish swing high/low structure
    2. Sweep below the swing low (liquidity grab)
    3. BOS above swing high (bullish confirmation)
    4. FVG forms during the move up
    5. Price retraces into FVG (entry)

    Price action visualization:

        Bar 15:     ████  <- Price retraces into FVG (entry trigger)
        Bar 14:   ████████ <- Top of move
        Bar 13:     ████   <- FVG forms here (bar[11].high < bar[13].low)
        Bar 12:   ████████ <- Displacement candle (big body)
        Bar 11:     ████   <- Start of BOS move
        ----- BOS Level (swing high from bar 6) -----
        Bar 6-10:  ranging
        ----- Swing High ~4502 -----
        Bar 5:      ████
        Bar 4:    ████████ <- Swing high bar
        Bar 3:      ████
        ----- Swing Low ~4495 -----
        Bar 2:      ████   <- Sweep bar (wick below, close inside)
        Bar 1:    ████     <- Swing low bar
        Bar 0:      ████
    """
    bars: list[Bar] = []

    # Start time: 9:30 AM ET (NY Open killzone)
    base_time = datetime(2024, 1, 15, 9, 30, tzinfo=ET)

    # -----------------------------------------------------------------
    # Bars 0-5: Establish initial structure with swing low and swing high
    # -----------------------------------------------------------------

    # Bar 0: Setup bar
    bars.append(make_bar(base_time, 4498.00, 4499.00, 4497.00, 4498.50))

    # Bar 1: Swing LOW forms here (low = 4495.00)
    bars.append(make_bar(base_time + timedelta(minutes=5), 4498.50, 4499.00, 4495.00, 4496.00))

    # Bar 2: Recovery bar
    bars.append(make_bar(base_time + timedelta(minutes=10), 4496.00, 4498.00, 4495.50, 4497.50))

    # Bar 3: Move up
    bars.append(make_bar(base_time + timedelta(minutes=15), 4497.50, 4500.00, 4497.00, 4499.50))

    # Bar 4: Swing HIGH forms here (high = 4502.00)
    bars.append(make_bar(base_time + timedelta(minutes=20), 4499.50, 4502.00, 4499.00, 4501.00))

    # Bar 5: Pullback from high
    bars.append(make_bar(base_time + timedelta(minutes=25), 4501.00, 4501.50, 4499.50, 4500.00))

    # -----------------------------------------------------------------
    # Bars 6-9: Ranging / consolidation (confirms swing structure)
    # -----------------------------------------------------------------

    # Bar 6
    bars.append(make_bar(base_time + timedelta(minutes=30), 4500.00, 4501.00, 4498.50, 4499.00))

    # Bar 7
    bars.append(make_bar(base_time + timedelta(minutes=35), 4499.00, 4500.00, 4497.50, 4498.00))

    # Bar 8
    bars.append(make_bar(base_time + timedelta(minutes=40), 4498.00, 4499.50, 4497.00, 4498.50))

    # Bar 9
    bars.append(make_bar(base_time + timedelta(minutes=45), 4498.50, 4499.00, 4496.50, 4497.00))

    # -----------------------------------------------------------------
    # Bar 10: SWEEP - Price sweeps below swing low (4495) then closes back inside
    # This is the liquidity grab that triggers our setup
    # -----------------------------------------------------------------

    # Sweep bar: low = 4494.00 (below swing low 4495), close = 4496.50 (back inside)
    bars.append(make_bar(base_time + timedelta(minutes=50), 4497.00, 4497.50, 4494.00, 4496.50))

    # -----------------------------------------------------------------
    # Bars 11-13: BOS + FVG formation
    # Price breaks above swing high (4502) with displacement
    # -----------------------------------------------------------------

    # Bar 11: Start of bullish move
    bars.append(make_bar(base_time + timedelta(minutes=55), 4496.50, 4500.00, 4496.00, 4499.50))

    # Bar 12: Displacement candle (big bullish body) - creates FVG
    # This bar's body should be large to show conviction
    bars.append(make_bar(base_time + timedelta(minutes=60), 4499.50, 4505.00, 4499.00, 4504.50))

    # Bar 13: Continuation - completes FVG and BOS
    # FVG: bar[11].high (4500.00) < bar[13].low (4503.00) = gap of 3 points
    # BOS: close (4507) > swing high (4502)
    bars.append(make_bar(base_time + timedelta(minutes=65), 4504.50, 4508.00, 4503.00, 4507.00))

    # -----------------------------------------------------------------
    # Bars 14-15: Retracement into FVG (entry trigger)
    # -----------------------------------------------------------------

    # Bar 14: Slight pullback begins
    bars.append(make_bar(base_time + timedelta(minutes=70), 4507.00, 4508.50, 4504.00, 4505.00))

    # Bar 15: Price retraces into FVG zone (4500-4503)
    # Entry should trigger here
    bars.append(make_bar(base_time + timedelta(minutes=75), 4505.00, 4506.00, 4501.00, 4502.50))

    return bars


def create_bearish_setup_bars() -> list[Bar]:
    """
    Create bars that form a BEARISH ICT setup:
    1. Establish swing structure
    2. Sweep above swing high (liquidity grab)
    3. BOS below swing low (bearish confirmation)
    4. FVG forms during the move down
    5. Price retraces into FVG (entry)
    """
    bars: list[Bar] = []

    # Start time: 9:30 AM ET (NY Open killzone)
    base_time = datetime(2024, 1, 16, 9, 30, tzinfo=ET)

    # -----------------------------------------------------------------
    # Bars 0-5: Establish initial structure
    # -----------------------------------------------------------------

    # Bar 0: Setup
    bars.append(make_bar(base_time, 4502.00, 4503.00, 4501.00, 4502.50))

    # Bar 1: Swing HIGH forms (high = 4505.00)
    bars.append(make_bar(base_time + timedelta(minutes=5), 4502.50, 4505.00, 4502.00, 4504.00))

    # Bar 2: Pullback
    bars.append(make_bar(base_time + timedelta(minutes=10), 4504.00, 4504.50, 4501.00, 4501.50))

    # Bar 3: Move down
    bars.append(make_bar(base_time + timedelta(minutes=15), 4501.50, 4502.00, 4498.00, 4498.50))

    # Bar 4: Swing LOW forms (low = 4497.00)
    bars.append(make_bar(base_time + timedelta(minutes=20), 4498.50, 4500.00, 4497.00, 4499.00))

    # Bar 5: Recovery
    bars.append(make_bar(base_time + timedelta(minutes=25), 4499.00, 4501.00, 4498.50, 4500.50))

    # -----------------------------------------------------------------
    # Bars 6-9: Consolidation
    # -----------------------------------------------------------------

    bars.append(make_bar(base_time + timedelta(minutes=30), 4500.50, 4502.00, 4499.50, 4501.00))
    bars.append(make_bar(base_time + timedelta(minutes=35), 4501.00, 4503.00, 4500.50, 4502.50))
    bars.append(make_bar(base_time + timedelta(minutes=40), 4502.50, 4504.00, 4501.50, 4503.00))
    bars.append(make_bar(base_time + timedelta(minutes=45), 4503.00, 4504.50, 4502.00, 4504.00))

    # -----------------------------------------------------------------
    # Bar 10: SWEEP - Price sweeps above swing high (4505) then closes back inside
    # -----------------------------------------------------------------

    bars.append(make_bar(base_time + timedelta(minutes=50), 4504.00, 4506.50, 4503.50, 4504.00))

    # -----------------------------------------------------------------
    # Bars 11-13: BOS + FVG formation (bearish)
    # -----------------------------------------------------------------

    # Bar 11: Start of bearish move
    bars.append(make_bar(base_time + timedelta(minutes=55), 4504.00, 4504.50, 4500.00, 4500.50))

    # Bar 12: Displacement candle (big bearish body)
    bars.append(make_bar(base_time + timedelta(minutes=60), 4500.50, 4501.00, 4494.00, 4494.50))

    # Bar 13: Continuation - completes FVG and BOS
    # FVG: bar[11].low (4500.00) > bar[13].high (4496.00) = bearish gap
    # BOS: close (4493) < swing low (4497)
    bars.append(make_bar(base_time + timedelta(minutes=65), 4494.50, 4496.00, 4492.00, 4493.00))

    # -----------------------------------------------------------------
    # Bars 14-15: Retracement into FVG (entry trigger)
    # -----------------------------------------------------------------

    bars.append(make_bar(base_time + timedelta(minutes=70), 4493.00, 4497.00, 4492.50, 4496.00))

    # Bar 15: Price retraces into FVG zone
    bars.append(make_bar(base_time + timedelta(minutes=75), 4496.00, 4499.00, 4495.50, 4498.00))

    return bars


# =============================================================================
# Test Configuration
# =============================================================================

def get_test_config() -> dict:
    """Get test configuration for ICT Strategy."""
    return {
        "name": "ICT_Test",
        # Session config - NY Open killzone
        "killzones": {
            "NY_OPEN": {
                "start": "09:30",
                "end": "11:30",
                "enabled": True,
            },
            "LONDON": {
                "start": "03:00",
                "end": "05:00",
                "enabled": False,  # Disable for testing
            },
        },
        # Swing detection
        "swing_left_bars": 2,
        "swing_right_bars": 1,
        "lookback_bars": 15,
        # Sweep detection
        "min_sweep_ticks": 2,
        "require_close_back_inside": True,
        # BOS detection
        "min_displacement_ticks": 0,
        # FVG detection
        "min_fvg_ticks": 2,
        "max_fvg_age_bars": 20,
        "fvg_entry_mode": "FIRST_TOUCH",
        "invalidate_on_close_through": True,
        # Stop/Target
        "stop_buffer_ticks": 2,
        "rr_targets": [1.0, 2.0, 3.0],
        # Timeouts
        "max_bars_sweep_to_bos": 10,
        "max_trades_per_session": 1,
    }


def get_test_instrument() -> dict:
    """Get test instrument config for ES (E-mini S&P)."""
    return {
        "symbol": "ES",
        "tick_size": 0.25,
        "tick_value": 12.50,
        "point_value": 50.0,
    }


# =============================================================================
# Tests
# =============================================================================

def test_bullish_setup():
    """
    Test that a bullish ICT setup generates a LONG signal.

    Setup: Sweep low -> Bullish BOS -> Bullish FVG -> Entry
    Expected: LONG signal with entry in FVG, stop below FVG
    """
    print("\n" + "=" * 70)
    print("TEST: Bullish ICT Setup")
    print("=" * 70)

    # Create strategy
    config = get_test_config()
    instrument = get_test_instrument()
    strategy = ICTStrategy(config, instrument)

    # Get test bars
    bars = create_bullish_setup_bars()

    print(f"\nFeeding {len(bars)} bars to strategy...")
    print(f"Swing low target: 4495.00")
    print(f"Swing high target: 4502.00")
    print(f"Sweep bar (#10): low=4494.00 (below 4495)")
    print(f"BOS bar (#13): close=4507.00 (above 4502)")
    print(f"FVG zone: ~4500.00 - 4503.00")
    print(f"Entry bar (#15): low=4501.00 (enters FVG)")

    # Process bars
    signals: list[Signal] = []
    for i, bar in enumerate(bars):
        result = strategy.on_bar(bar)
        if result:
            signals.extend(result)
            print(f"\n>>> Signal emitted on bar {i}!")

        # Print state periodically
        if i in [10, 13, 15]:
            state = strategy.get_state_summary()
            print(f"\nBar {i} state:")
            print(f"  Session: {state['session']}")
            print(f"  Pending sweep: {state['pending_sweep']}")
            print(f"  Pending BOS: {state['pending_bos']}")
            print(f"  Bias: {state['current_bias']}")
            print(f"  Active FVGs: {state['active_fvgs']}")

    # Validate results
    print("\n" + "-" * 40)
    print("RESULTS:")
    print("-" * 40)

    if not signals:
        print("FAIL: No signals generated!")
        return False

    signal = signals[0]
    print(f"Signal count: {len(signals)}")
    print(f"Direction: {signal.direction}")
    print(f"Entry price: {signal.entry_price}")
    print(f"Stop price: {signal.stop_price}")
    print(f"Targets: {signal.targets}")
    print(f"Reason: {signal.reason}")

    # Assertions
    passed = True

    if signal.direction != Direction.LONG:
        print(f"FAIL: Expected LONG, got {signal.direction}")
        passed = False
    else:
        print("PASS: Direction is LONG")

    if signal.stop_price >= signal.entry_price:
        print(f"FAIL: Stop ({signal.stop_price}) should be below entry ({signal.entry_price})")
        passed = False
    else:
        print(f"PASS: Stop ({signal.stop_price}) is below entry ({signal.entry_price})")

    if not signal.targets or signal.targets[0] <= signal.entry_price:
        print(f"FAIL: Targets should be above entry")
        passed = False
    else:
        print(f"PASS: Targets are above entry")

    if "sweep" not in signal.reason or "bos" not in signal.reason or "fvg" not in signal.reason:
        print("FAIL: Reason dict missing required keys")
        passed = False
    else:
        print("PASS: Reason dict has sweep, bos, fvg")

    return passed


def test_bearish_setup():
    """
    Test that a bearish ICT setup generates a SHORT signal.

    Setup: Sweep high -> Bearish BOS -> Bearish FVG -> Entry
    Expected: SHORT signal with entry in FVG, stop above FVG
    """
    print("\n" + "=" * 70)
    print("TEST: Bearish ICT Setup")
    print("=" * 70)

    # Create strategy
    config = get_test_config()
    instrument = get_test_instrument()
    strategy = ICTStrategy(config, instrument)

    # Get test bars
    bars = create_bearish_setup_bars()

    print(f"\nFeeding {len(bars)} bars to strategy...")
    print(f"Swing high target: 4505.00")
    print(f"Swing low target: 4497.00")
    print(f"Sweep bar (#10): high=4506.50 (above 4505)")
    print(f"BOS bar (#13): close=4493.00 (below 4497)")
    print(f"FVG zone: ~4496.00 - 4500.00")
    print(f"Entry bar (#15): high=4499.00 (enters FVG)")

    # Process bars
    signals: list[Signal] = []
    for i, bar in enumerate(bars):
        result = strategy.on_bar(bar)
        if result:
            signals.extend(result)
            print(f"\n>>> Signal emitted on bar {i}!")

        # Print state periodically
        if i in [10, 13, 15]:
            state = strategy.get_state_summary()
            print(f"\nBar {i} state:")
            print(f"  Session: {state['session']}")
            print(f"  Pending sweep: {state['pending_sweep']}")
            print(f"  Pending BOS: {state['pending_bos']}")
            print(f"  Bias: {state['current_bias']}")
            print(f"  Active FVGs: {state['active_fvgs']}")

    # Validate results
    print("\n" + "-" * 40)
    print("RESULTS:")
    print("-" * 40)

    if not signals:
        print("FAIL: No signals generated!")
        return False

    signal = signals[0]
    print(f"Signal count: {len(signals)}")
    print(f"Direction: {signal.direction}")
    print(f"Entry price: {signal.entry_price}")
    print(f"Stop price: {signal.stop_price}")
    print(f"Targets: {signal.targets}")
    print(f"Reason: {signal.reason}")

    # Assertions
    passed = True

    if signal.direction != Direction.SHORT:
        print(f"FAIL: Expected SHORT, got {signal.direction}")
        passed = False
    else:
        print("PASS: Direction is SHORT")

    if signal.stop_price <= signal.entry_price:
        print(f"FAIL: Stop ({signal.stop_price}) should be above entry ({signal.entry_price})")
        passed = False
    else:
        print(f"PASS: Stop ({signal.stop_price}) is above entry ({signal.entry_price})")

    if not signal.targets or signal.targets[0] >= signal.entry_price:
        print(f"FAIL: Targets should be below entry")
        passed = False
    else:
        print(f"PASS: Targets are below entry")

    return passed


def test_no_signal_outside_killzone():
    """
    Test that no signals are generated outside killzone hours.
    """
    print("\n" + "=" * 70)
    print("TEST: No Signal Outside Killzone")
    print("=" * 70)

    config = get_test_config()
    instrument = get_test_instrument()
    strategy = ICTStrategy(config, instrument)

    # Create bars at 2:00 PM ET (outside killzone)
    base_time = datetime(2024, 1, 15, 14, 0, tzinfo=ET)
    bars = [
        make_bar(base_time + timedelta(minutes=i*5), 4500.0, 4501.0, 4499.0, 4500.0)
        for i in range(10)
    ]

    signals = []
    for bar in bars:
        result = strategy.on_bar(bar)
        if result:
            signals.extend(result)

    print(f"Bars processed: {len(bars)}")
    print(f"Session: {strategy.current_session}")
    print(f"Signals generated: {len(signals)}")

    if signals:
        print("FAIL: Should not generate signals outside killzone")
        return False

    print("PASS: No signals outside killzone")
    return True


def test_state_reset():
    """
    Test that state is properly reset after signal emission.
    """
    print("\n" + "=" * 70)
    print("TEST: State Reset After Signal")
    print("=" * 70)

    config = get_test_config()
    instrument = get_test_instrument()
    strategy = ICTStrategy(config, instrument)

    # Run bullish setup
    bars = create_bullish_setup_bars()

    for bar in bars:
        strategy.on_bar(bar)

    state = strategy.get_state_summary()
    print(f"After signal emission:")
    print(f"  Pending sweep: {state['pending_sweep']}")
    print(f"  Pending BOS: {state['pending_bos']}")
    print(f"  Has traded session: {state['has_traded_session']}")
    print(f"  Trades today: {state['trades_today']}")

    passed = True

    if state['pending_sweep'] is not None:
        print("FAIL: pending_sweep should be None after signal")
        passed = False

    if state['pending_bos'] is not None:
        print("FAIL: pending_bos should be None after signal")
        passed = False

    if not state['has_traded_session']:
        print("FAIL: has_traded_session should be True")
        passed = False

    if state['trades_today'] != 1:
        print(f"FAIL: trades_today should be 1, got {state['trades_today']}")
        passed = False

    if passed:
        print("PASS: State properly reset")

    return passed


def test_daily_reset():
    """
    Test that daily reset clears all state.
    """
    print("\n" + "=" * 70)
    print("TEST: Daily Reset")
    print("=" * 70)

    config = get_test_config()
    instrument = get_test_instrument()
    strategy = ICTStrategy(config, instrument)

    # Run some bars to build state
    bars = create_bullish_setup_bars()[:10]
    for bar in bars:
        strategy.on_bar(bar)

    print("Before reset:")
    state_before = strategy.get_state_summary()
    print(f"  Bars in history: {state_before['bars_in_history']}")

    # Reset
    strategy.reset_daily()

    print("After reset:")
    state_after = strategy.get_state_summary()
    print(f"  Bars in history: {state_after['bars_in_history']}")
    print(f"  Pending sweep: {state_after['pending_sweep']}")
    print(f"  Trades today: {state_after['trades_today']}")

    passed = True

    if state_after['bars_in_history'] != 0:
        print("FAIL: bars should be cleared")
        passed = False

    if state_after['trades_today'] != 0:
        print("FAIL: trades_today should be 0")
        passed = False

    if passed:
        print("PASS: Daily reset works correctly")

    return passed


# =============================================================================
# Main
# =============================================================================

def run_all_tests():
    """Run all tests and report results."""
    print("\n" + "=" * 70)
    print("ICT STRATEGY TEST SUITE")
    print("=" * 70)

    tests = [
        ("Bullish Setup", test_bullish_setup),
        ("Bearish Setup", test_bearish_setup),
        ("No Signal Outside Killzone", test_no_signal_outside_killzone),
        ("State Reset After Signal", test_state_reset),
        ("Daily Reset", test_daily_reset),
    ]

    results = []
    for name, test_fn in tests:
        try:
            passed = test_fn()
            results.append((name, passed, None))
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"\nEXCEPTION: {e}")
            import traceback
            traceback.print_exc()

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed_count = 0
    for name, passed, error in results:
        status = "PASS" if passed else "FAIL"
        if error:
            print(f"  [{status}] {name}: {error}")
        else:
            print(f"  [{status}] {name}")
        if passed:
            passed_count += 1

    print(f"\nTotal: {passed_count}/{len(results)} passed")

    return passed_count == len(results)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
