"""
Live Signal Runner - TradingView Data

Monitors ES and NQ for trade signals using the FVG strategy with hybrid trailing stops.
Runs continuously and alerts when signals are generated.

Usage:
    python -m runners.run_signals_live
"""
import sys
sys.path.insert(0, '.')

import time
from datetime import datetime, time as dt_time, date
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations


def check_for_signals(symbol='ES', tick_size=0.25, contracts=3):
    """Check for active trade signals on a symbol."""

    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25

    # Fetch latest data
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=500)

    if not all_bars:
        return None

    today = all_bars[-1].timestamp.date()
    today_bars = [b for b in all_bars if b.timestamp.date() == today]

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

    if len(session_bars) < 20:
        return None

    current_bar = session_bars[-1]
    current_price = current_bar.close
    current_time = current_bar.timestamp

    # Detect FVGs
    fvg_config = {
        'min_fvg_ticks': 4,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)
    update_all_fvg_mitigations(all_fvgs, session_bars, fvg_config)

    signals = []

    for direction in ['LONG', 'SHORT']:
        is_long = direction == 'LONG'
        fvg_dir = 'BULLISH' if is_long else 'BEARISH'

        # Get active FVGs
        active_fvgs = [f for f in all_fvgs if f.direction == fvg_dir and not f.mitigated]
        active_fvgs.sort(key=lambda f: f.created_bar_index)

        if not active_fvgs:
            continue

        entry_fvg = active_fvgs[0]

        # Calculate entry levels
        edge_price = entry_fvg.high if is_long else entry_fvg.low
        midpoint_price = entry_fvg.midpoint

        # Calculate average entry for partial fill
        avg_entry = (edge_price * 1 + midpoint_price * 2) / 3

        # Stop and targets
        if is_long:
            stop_price = entry_fvg.low
            risk = avg_entry - stop_price
        else:
            stop_price = entry_fvg.high
            risk = stop_price - avg_entry

        if risk <= 0:
            continue

        target_4r = avg_entry + (4 * risk) if is_long else avg_entry - (4 * risk)
        target_8r = avg_entry + (8 * risk) if is_long else avg_entry - (8 * risk)
        plus_4r = avg_entry + (4 * risk) if is_long else avg_entry - (4 * risk)

        # Check if price is in or approaching entry zone
        # For LONG: price needs to drop into FVG (buy low)
        # For SHORT: price needs to rise into FVG (sell high)
        fvg_range = entry_fvg.high - entry_fvg.low
        proximity_threshold = fvg_range * 2  # Within 2x FVG range

        if is_long:
            # LONG: price should be at or below FVG high (edge)
            in_entry_zone = entry_fvg.low <= current_price <= entry_fvg.high
            approaching = current_price > entry_fvg.high and current_price <= entry_fvg.high + proximity_threshold
        else:
            # SHORT: price should be at or above FVG low (edge)
            in_entry_zone = entry_fvg.low <= current_price <= entry_fvg.high
            approaching = current_price < entry_fvg.low and current_price >= entry_fvg.low - proximity_threshold

        # Calculate R:R
        rr_4r = 4.0
        rr_8r = 8.0

        signal = {
            'symbol': symbol,
            'direction': direction,
            'status': 'IN_ZONE' if in_entry_zone else 'APPROACHING' if approaching else 'WAITING',
            'current_price': current_price,
            'edge_price': edge_price,
            'midpoint_price': midpoint_price,
            'avg_entry': avg_entry,
            'stop_price': stop_price,
            'target_4r': target_4r,
            'target_8r': target_8r,
            'plus_4r_trail': plus_4r,
            'risk': risk,
            'risk_dollars': (risk / tick_size) * tick_value * contracts,
            'fvg_low': entry_fvg.low,
            'fvg_high': entry_fvg.high,
            'fvg_age': len(session_bars) - entry_fvg.created_bar_index,
            'time': current_time,
        }

        signals.append(signal)

    return {
        'symbol': symbol,
        'price': current_price,
        'time': current_time,
        'signals': signals,
        'bars': len(session_bars),
    }


def print_signal(signal):
    """Print a signal in a formatted way."""
    status_icons = {
        'IN_ZONE': '[ACTIVE]',
        'APPROACHING': '[NEAR]',
        'WAITING': '[WAIT]'
    }

    status_icon = status_icons.get(signal['status'], '[--]')

    print(f"\n  {status_icon} {signal['direction']} Signal")
    print(f"     Status: {signal['status']}")
    print(f"     Current: {signal['current_price']:.2f}")
    print(f"     Entry Zone: {signal['edge_price']:.2f} (edge) -> {signal['midpoint_price']:.2f} (mid)")
    print(f"     Avg Entry: {signal['avg_entry']:.2f}")
    print(f"     Stop: {signal['stop_price']:.2f} | Risk: {signal['risk']:.2f} pts (${signal['risk_dollars']:.0f})")
    print(f"     Targets: 4R={signal['target_4r']:.2f} | 8R={signal['target_8r']:.2f}")
    print(f"     Trail: +4R @ {signal['plus_4r_trail']:.2f} (after 8R)")
    print(f"     FVG: {signal['fvg_low']:.2f}-{signal['fvg_high']:.2f} (age: {signal['fvg_age']} bars)")


def run_live_signals(symbols=['ES', 'NQ'], interval_seconds=180, contracts=3):
    """Run continuous signal monitoring."""

    print("=" * 70)
    print("ICT FVG Strategy - Live Signal Monitor")
    print("=" * 70)
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Contracts: {contracts}")
    print(f"Refresh: Every {interval_seconds // 60} minutes")
    print(f"Strategy: Partial Fill Entry + Hybrid Trailing Stop")
    print("=" * 70)
    print("\nStarting live monitoring... (Ctrl+C to stop)")

    cycle = 0

    try:
        while True:
            cycle += 1
            now = datetime.now()

            print(f"\n{'='*70}")
            print(f"SCAN #{cycle} | {now.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*70}")

            active_signals = []

            for symbol in symbols:
                tick_size = 0.25 if symbol in ['ES', 'NQ'] else 0.01

                result = check_for_signals(symbol, tick_size, contracts)

                if result:
                    print(f"\n{symbol} @ {result['price']:.2f} | {result['time'].strftime('%H:%M')} | {result['bars']} bars")

                    for signal in result['signals']:
                        print_signal(signal)

                        if signal['status'] in ['IN_ZONE', 'APPROACHING']:
                            active_signals.append(signal)
                else:
                    print(f"\n{symbol}: No data available")

            # Summary
            print(f"\n{'-'*70}")
            if active_signals:
                print(f"*** ACTIVE SIGNALS: {len(active_signals)} ***")
                for sig in active_signals:
                    print(f"   -> {sig['symbol']} {sig['direction']} ({sig['status']}) @ {sig['current_price']:.2f}")
            else:
                print("No active signals - monitoring...")

            # Wait for next cycle
            print(f"\nNext scan in {interval_seconds // 60} minutes...")
            time.sleep(interval_seconds)

    except KeyboardInterrupt:
        print("\n\nStopped by user.")
        print("=" * 70)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Live Signal Monitor')
    parser.add_argument('--symbols', default='ES,NQ', help='Symbols to monitor (comma-separated)')
    parser.add_argument('--interval', type=int, default=180, help='Refresh interval in seconds')
    parser.add_argument('--contracts', type=int, default=3, help='Number of contracts for risk calculation')

    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(',')]
    run_live_signals(symbols=symbols, interval_seconds=args.interval, contracts=args.contracts)
