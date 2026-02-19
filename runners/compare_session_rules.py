"""
Compare Session-Based Rules vs Baseline

Tests:
- Baseline: No session restrictions
- Session Rules: Overnight retrace only 9:30-10:00 with risk caps
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10


def run_comparison(symbol='ES', days=30):
    """Compare baseline vs session-based rules."""

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25 if symbol == 'MES' else 0.50
    min_risk_pts = 1.5 if symbol in ['ES', 'MES'] else 6.0
    max_bos_risk_pts = 8.0 if symbol in ['ES', 'MES'] else 20.0

    # Session-based risk caps
    max_overnight_risk = 10.0 if symbol in ['ES', 'MES'] else 25.0

    print(f'Fetching {symbol} 3m data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=10000)

    if not all_bars:
        print('No data available')
        return

    # Get trading dates
    all_dates = sorted(set(b.timestamp.date() for b in all_bars), reverse=True)
    trading_dates = []
    for d in all_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == d]
        rth_bars = [b for b in day_bars if dt_time(9, 30) <= b.timestamp.time() <= dt_time(16, 0)]
        if len(rth_bars) >= 50:
            trading_dates.append(d)
        if len(trading_dates) >= days:
            break

    trading_dates = sorted(trading_dates)

    # Track all trades for comparison
    baseline_trades = []
    filtered_trades = []  # Trades that would be filtered by session rules

    # Run baseline backtest (no session restrictions on overnight retrace)
    for target_date in trading_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == target_date]
        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        results = run_session_v10(
            session_bars,
            all_bars,
            tick_size=tick_size,
            tick_value=tick_value,
            contracts=3,
            min_risk_pts=min_risk_pts,
            enable_creation_entry=True,
            enable_retracement_entry=True,
            enable_bos_entry=True,
            retracement_morning_only=False,
            t1_fixed_4r=True,
            midday_cutoff=True,
            pm_cutoff_nq=(symbol in ['NQ', 'MNQ']),
            max_bos_risk_pts=max_bos_risk_pts,
            symbol=symbol,
        )

        for r in results:
            r['date'] = target_date
            baseline_trades.append(r)

            # Check if this trade would be filtered by session rules
            entry_time = r['entry_time']
            if hasattr(entry_time, 'time'):
                entry_time_only = entry_time.time()
            else:
                entry_time_only = entry_time

            entry_type = r['entry_type']
            risk = r['risk']

            should_filter = False
            filter_reason = None

            if entry_type == 'RETRACEMENT':
                # Session rule: Only allow overnight retrace 9:30-10:00
                if entry_time_only >= dt_time(10, 0):
                    should_filter = True
                    filter_reason = 'After 10:00'
                # Risk cap for overnight retrace
                elif risk > max_overnight_risk:
                    should_filter = True
                    filter_reason = f'Risk {risk:.1f} > {max_overnight_risk} cap'

            if should_filter:
                r['filter_reason'] = filter_reason
                filtered_trades.append(r)

    # Calculate baseline totals
    baseline_pnl = sum(t['total_dollars'] for t in baseline_trades)
    baseline_wins = sum(1 for t in baseline_trades if t['total_dollars'] > 0)
    baseline_losses = sum(1 for t in baseline_trades if t['total_dollars'] < 0)

    # Calculate session rules totals (baseline minus filtered)
    session_trades = [t for t in baseline_trades if t not in filtered_trades]
    session_pnl = sum(t['total_dollars'] for t in session_trades)
    session_wins = sum(1 for t in session_trades if t['total_dollars'] > 0)
    session_losses = sum(1 for t in session_trades if t['total_dollars'] < 0)

    # Filtered trade analysis
    filtered_pnl = sum(t['total_dollars'] for t in filtered_trades)
    filtered_wins = sum(1 for t in filtered_trades if t['total_dollars'] > 0)
    filtered_losses = sum(1 for t in filtered_trades if t['total_dollars'] < 0)

    print()
    print('=' * 100)
    print(f'{symbol} SESSION RULES COMPARISON - {len(trading_dates)} Days')
    print('=' * 100)

    print(f"\n{'Scenario':<30} {'Trades':>7} {'Wins':>6} {'Losses':>7} {'Win%':>7} {'P/L':>14}")
    print('-' * 80)

    baseline_wr = (baseline_wins / len(baseline_trades) * 100) if baseline_trades else 0
    session_wr = (session_wins / len(session_trades) * 100) if session_trades else 0

    print(f"{'Baseline (no restrictions)':<30} {len(baseline_trades):>7} {baseline_wins:>6} {baseline_losses:>7} {baseline_wr:>6.1f}% ${baseline_pnl:>12,.0f}")
    print(f"{'Session Rules':<30} {len(session_trades):>7} {session_wins:>6} {session_losses:>7} {session_wr:>6.1f}% ${session_pnl:>12,.0f}")
    print('-' * 80)
    print(f"{'Difference':<30} {len(filtered_trades):>7} {filtered_wins:>6} {filtered_losses:>7} {'':>7} ${session_pnl - baseline_pnl:>+12,.0f}")

    # Show filtered trades detail
    print()
    print('=' * 100)
    print('FILTERED TRADES (What we lose)')
    print('=' * 100)
    print(f"\n{'Date':<12} {'Time':<8} {'Dir':<6} {'Risk':>8} {'P/L':>12} {'Result':<6} {'Reason':<25}")
    print('-' * 90)

    # Sort by P/L to show biggest wins/losses first
    filtered_sorted = sorted(filtered_trades, key=lambda x: x['total_dollars'], reverse=True)

    for t in filtered_sorted:
        entry_time = t['entry_time']
        if hasattr(entry_time, 'strftime'):
            time_str = entry_time.strftime('%H:%M')
        else:
            time_str = str(entry_time)

        result = 'WIN' if t['total_dollars'] > 0 else 'LOSS'
        print(f"{t['date']!s:<12} {time_str:<8} {t['direction']:<6} {t['risk']:>7.2f} ${t['total_dollars']:>10,.0f} {result:<6} {t['filter_reason']:<25}")

    # Summary of filtered trades
    print()
    print('-' * 90)
    print(f"Total Filtered: {len(filtered_trades)} trades")
    print(f"  Winners filtered: {filtered_wins} (${sum(t['total_dollars'] for t in filtered_trades if t['total_dollars'] > 0):,.0f})")
    print(f"  Losers filtered: {filtered_losses} (${sum(t['total_dollars'] for t in filtered_trades if t['total_dollars'] < 0):,.0f})")
    print(f"  Net impact: ${filtered_pnl:+,.0f}")

    # By filter reason
    print()
    print('By Filter Reason:')
    reasons = {}
    for t in filtered_trades:
        reason = t['filter_reason']
        if reason not in reasons:
            reasons[reason] = {'count': 0, 'pnl': 0, 'wins': 0, 'losses': 0}
        reasons[reason]['count'] += 1
        reasons[reason]['pnl'] += t['total_dollars']
        if t['total_dollars'] > 0:
            reasons[reason]['wins'] += 1
        else:
            reasons[reason]['losses'] += 1

    for reason, data in reasons.items():
        print(f"  {reason}: {data['count']} trades ({data['wins']}W/{data['losses']}L), P/L: ${data['pnl']:+,.0f}")

    return {
        'baseline_pnl': baseline_pnl,
        'session_pnl': session_pnl,
        'filtered_pnl': filtered_pnl,
        'filtered_trades': filtered_trades,
    }


if __name__ == "__main__":
    print("=" * 100)
    print("COMPARING BASELINE vs SESSION RULES")
    print("Session Rules: Overnight retrace only 9:30-10:00 with risk caps (ES:10, NQ:25)")
    print("=" * 100)

    es_results = run_comparison('ES', 30)
    print("\n" * 2)
    nq_results = run_comparison('NQ', 30)

    # Combined summary
    print("\n" * 2)
    print("=" * 100)
    print("COMBINED SUMMARY")
    print("=" * 100)

    total_baseline = es_results['baseline_pnl'] + nq_results['baseline_pnl']
    total_session = es_results['session_pnl'] + nq_results['session_pnl']
    total_filtered = es_results['filtered_pnl'] + nq_results['filtered_pnl']

    print(f"\nBaseline Total P/L: ${total_baseline:,.0f}")
    print(f"Session Rules P/L:  ${total_session:,.0f}")
    print(f"Difference:         ${total_session - total_baseline:+,.0f}")
    print(f"\nFiltered Trades Impact: ${total_filtered:+,.0f}")

    if total_filtered < 0:
        print(f"\n✓ Session rules IMPROVE P/L by filtering ${abs(total_filtered):,.0f} in losses")
    else:
        print(f"\n✗ Session rules REDUCE P/L by filtering ${total_filtered:,.0f} in profits")
