"""
Backtest ADX Filter for Overnight Retrace Entries

Tests the hypothesis: ADX >= 22 for overnight retrace entries improves results
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10, calculate_adx

def run_backtest(symbol='ES', days=30, adx_threshold=None):
    """
    Run backtest with optional ADX filter for overnight retrace entries.

    Args:
        symbol: ES or NQ
        days: Number of days to backtest
        adx_threshold: If set, only take overnight retrace entries when ADX >= threshold
    """
    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00
    min_risk_pts = 1.5 if symbol == 'ES' else 6.0
    contracts = 3

    print(f"Fetching {symbol} data...")
    bars = fetch_futures_bars(symbol, interval='3m', n_bars=5000)

    if not bars:
        print("No data available")
        return

    # Get unique trading days
    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:] if len(all_dates) >= days else all_dates

    print(f"Backtesting {len(recent_dates)} days: {recent_dates[0]} to {recent_dates[-1]}")
    print()

    # Track results
    all_retrace_trades = []
    all_other_trades = []

    for target_date in recent_dates:
        day_bars = [b for b in bars if b.timestamp.date() == target_date]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Run V10 strategy
        results = run_session_v10(
            session_bars,
            bars,
            tick_size=tick_size,
            tick_value=tick_value,
            contracts=contracts,
            max_open_trades=2,
            min_risk_pts=min_risk_pts,
            t1_fixed_4r=True,
        )

        for r in results:
            # Calculate ADX at entry time
            entry_time = r['entry_time']
            bars_to_entry = [b for b in bars if b.timestamp <= entry_time]
            adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)

            trade_info = {
                'date': target_date,
                'time': entry_time.strftime('%H:%M'),
                'entry_type': r['entry_type'],
                'direction': r['direction'],
                'entry_price': r['entry_price'],
                'risk': r['risk'],
                'pnl': r['total_dollars'],
                'adx': adx if adx else 0,
                'plus_di': plus_di if plus_di else 0,
                'minus_di': minus_di if minus_di else 0,
            }

            if r['entry_type'] == 'RETRACEMENT':
                all_retrace_trades.append(trade_info)
            else:
                all_other_trades.append(trade_info)

    # Analyze results
    print("=" * 80)
    print(f"OVERNIGHT RETRACE ENTRIES - {symbol} - {len(recent_dates)} Days")
    print("=" * 80)

    if not all_retrace_trades:
        print("No overnight retrace trades found")
        return

    # Current results (no filter)
    total_trades = len(all_retrace_trades)
    wins = [t for t in all_retrace_trades if t['pnl'] > 0]
    losses = [t for t in all_retrace_trades if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in all_retrace_trades)

    print("\nCURRENT (No ADX Filter):")
    print(f"  Trades: {total_trades} ({len(wins)} wins, {len(losses)} losses)")
    print(f"  Win Rate: {len(wins)/total_trades*100:.1f}%")
    print(f"  Total P/L: ${total_pnl:+,.2f}")

    # With ADX filter
    print("\nWITH ADX >= 22 FILTER:")
    filtered_trades = [t for t in all_retrace_trades if t['adx'] >= 22]
    skipped_trades = [t for t in all_retrace_trades if t['adx'] < 22]

    if filtered_trades:
        filtered_wins = [t for t in filtered_trades if t['pnl'] > 0]
        filtered_losses = [t for t in filtered_trades if t['pnl'] <= 0]
        filtered_pnl = sum(t['pnl'] for t in filtered_trades)

        print(f"  Trades: {len(filtered_trades)} ({len(filtered_wins)} wins, {len(filtered_losses)} losses)")
        print(f"  Win Rate: {len(filtered_wins)/len(filtered_trades)*100:.1f}%")
        print(f"  Total P/L: ${filtered_pnl:+,.2f}")
    else:
        filtered_pnl = 0
        print("  Trades: 0")
        print("  Total P/L: $0.00")

    # Skipped trades analysis
    if skipped_trades:
        skipped_wins = [t for t in skipped_trades if t['pnl'] > 0]
        skipped_losses = [t for t in skipped_trades if t['pnl'] <= 0]
        skipped_pnl = sum(t['pnl'] for t in skipped_trades)

        print("\nSKIPPED TRADES (ADX < 22):")
        print(f"  Trades: {len(skipped_trades)} ({len(skipped_wins)} wins, {len(skipped_losses)} losses)")
        print(f"  Total P/L: ${skipped_pnl:+,.2f}")

        if skipped_pnl > 0:
            print("  WARNING: Skipped trades were NET PROFITABLE")
        else:
            print("  GOOD: Skipped trades were NET LOSING")

    # Summary comparison
    improvement = filtered_pnl - total_pnl
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"  Current P/L:     ${total_pnl:+,.2f}")
    print(f"  With ADX Filter: ${filtered_pnl:+,.2f}")
    print(f"  Improvement:     ${improvement:+,.2f}")

    # Detailed trade list
    print(f"\n{'='*80}")
    print("DETAILED OVERNIGHT RETRACE TRADES")
    print(f"{'='*80}")
    print(f"{'Date':<12} {'Time':<6} {'Dir':<6} {'ADX':>6} {'Risk':>6} {'P/L':>12} {'Filter':<10}")
    print("-" * 70)

    for t in sorted(all_retrace_trades, key=lambda x: (x['date'], x['time'])):
        filter_status = "TAKE" if t['adx'] >= 22 else "SKIP"
        "WIN" if t['pnl'] > 0 else "LOSS"
        print(f"{t['date']} {t['time']:<6} {t['direction']:<6} {t['adx']:>6.1f} {t['risk']:>6.2f} ${t['pnl']:>10,.2f} {filter_status:<10}")

    # Test different thresholds
    print(f"\n{'='*80}")
    print("ADX THRESHOLD COMPARISON")
    print(f"{'='*80}")
    print(f"{'Threshold':>10} | {'Trades':>7} | {'Wins':>5} | {'Losses':>6} | {'Win%':>6} | {'P/L':>12}")
    print("-" * 65)

    for threshold in [17, 20, 22, 25, 28, 30, 35]:
        taken = [t for t in all_retrace_trades if t['adx'] >= threshold]
        if taken:
            t_wins = len([t for t in taken if t['pnl'] > 0])
            t_losses = len([t for t in taken if t['pnl'] <= 0])
            t_pnl = sum(t['pnl'] for t in taken)
            t_winrate = t_wins / len(taken) * 100
            print(f"ADX >= {threshold:>3} | {len(taken):>7} | {t_wins:>5} | {t_losses:>6} | {t_winrate:>5.1f}% | ${t_pnl:>10,.2f}")
        else:
            print(f"ADX >= {threshold:>3} | {0:>7} | {0:>5} | {0:>6} | {'N/A':>6} | ${0:>10,.2f}")

    # Other entry types for context
    if all_other_trades:
        other_pnl = sum(t['pnl'] for t in all_other_trades)
        print(f"\n{'='*80}")
        print("OTHER ENTRY TYPES (Creation, Intraday, BOS)")
        print(f"{'='*80}")
        print(f"  Trades: {len(all_other_trades)}")
        print(f"  Total P/L: ${other_pnl:+,.2f}")
        print(f"\n  Combined with ADX-filtered retrace: ${filtered_pnl + other_pnl:+,.2f}")


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    run_backtest(symbol, days)
