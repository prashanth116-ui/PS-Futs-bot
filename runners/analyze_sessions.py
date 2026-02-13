"""
Session Performance Analysis - Break down P/L by time windows.

Sessions:
- Early AM (9:30-10:00): Opening range, high volatility
- Mid AM (10:00-11:00): Trend development
- Late AM (11:00-12:00): Pre-lunch momentum
- Lunch (12:00-14:00): Already filtered by midday_cutoff
- Afternoon (14:00-16:00): End-of-day moves
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time, timedelta
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10


def analyze_sessions(symbol='ES', days=30):
    """Analyze trade performance by session and entry type."""

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25 if symbol == 'MES' else 0.50
    min_risk_pts = 1.5 if symbol in ['ES', 'MES'] else 6.0
    max_bos_risk_pts = 8.0 if symbol in ['ES', 'MES'] else 20.0

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

    # Session definitions
    sessions = {
        'Early AM (9:30-10:00)': (dt_time(9, 30), dt_time(10, 0)),
        'Mid AM (10:00-11:00)': (dt_time(10, 0), dt_time(11, 0)),
        'Late AM (11:00-12:00)': (dt_time(11, 0), dt_time(12, 0)),
        'Afternoon (14:00-16:00)': (dt_time(14, 0), dt_time(16, 0)),
        'Pre-market (4:00-9:30)': (dt_time(4, 0), dt_time(9, 30)),
    }

    # Track results by session and entry type
    results_by_session = {s: {'trades': 0, 'wins': 0, 'pnl': 0.0, 'by_type': {}} for s in sessions}
    entry_types = ['CREATION', 'RETRACEMENT', 'INTRADAY_RETRACE', 'BOS_RETRACE']
    for s in sessions:
        for et in entry_types:
            results_by_session[s]['by_type'][et] = {'trades': 0, 'wins': 0, 'pnl': 0.0, 'risks': []}

    # Run backtests
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
            retracement_morning_only=False,  # Analyze all sessions
            t1_fixed_4r=True,
            midday_cutoff=False,  # Analyze lunch too
            pm_cutoff_nq=False,   # Analyze afternoon too
            max_bos_risk_pts=max_bos_risk_pts,
            symbol=symbol,
        )

        for r in results:
            entry_time = r['entry_time']
            if hasattr(entry_time, 'time'):
                entry_time = entry_time.time()

            entry_type = r['entry_type']
            pnl = r['total_dollars']
            risk = r['risk']
            is_win = pnl > 0

            # Find which session this trade belongs to
            for session_name, (start, end) in sessions.items():
                if start <= entry_time < end:
                    results_by_session[session_name]['trades'] += 1
                    results_by_session[session_name]['pnl'] += pnl
                    if is_win:
                        results_by_session[session_name]['wins'] += 1

                    results_by_session[session_name]['by_type'][entry_type]['trades'] += 1
                    results_by_session[session_name]['by_type'][entry_type]['pnl'] += pnl
                    results_by_session[session_name]['by_type'][entry_type]['risks'].append(risk)
                    if is_win:
                        results_by_session[session_name]['by_type'][entry_type]['wins'] += 1
                    break

    # Print results
    print()
    print('=' * 100)
    print(f'{symbol} SESSION ANALYSIS - {len(trading_dates)} Days')
    print('=' * 100)

    print(f"\n{'Session':<25} {'Trades':>7} {'Wins':>6} {'Win%':>7} {'P/L':>14} {'Avg P/L':>12}")
    print('-' * 80)

    for session_name in ['Pre-market (4:00-9:30)', 'Early AM (9:30-10:00)', 'Mid AM (10:00-11:00)',
                         'Late AM (11:00-12:00)', 'Afternoon (14:00-16:00)']:
        data = results_by_session[session_name]
        trades = data['trades']
        wins = data['wins']
        pnl = data['pnl']
        win_rate = (wins / trades * 100) if trades > 0 else 0
        avg_pnl = pnl / trades if trades > 0 else 0

        print(f"{session_name:<25} {trades:>7} {wins:>6} {win_rate:>6.1f}% ${pnl:>12,.0f} ${avg_pnl:>10,.0f}")

    # Entry type breakdown by session
    print()
    print('-' * 100)
    print('ENTRY TYPE BREAKDOWN BY SESSION')
    print('-' * 100)

    for entry_type in entry_types:
        print(f"\n{entry_type}:")
        print(f"  {'Session':<25} {'Trades':>7} {'Win%':>7} {'P/L':>14} {'Avg Risk':>10}")
        print(f"  {'-'*70}")

        for session_name in ['Pre-market (4:00-9:30)', 'Early AM (9:30-10:00)', 'Mid AM (10:00-11:00)',
                             'Late AM (11:00-12:00)', 'Afternoon (14:00-16:00)']:
            data = results_by_session[session_name]['by_type'][entry_type]
            trades = data['trades']
            if trades == 0:
                continue
            wins = data['wins']
            pnl = data['pnl']
            risks = data['risks']
            win_rate = (wins / trades * 100) if trades > 0 else 0
            avg_risk = sum(risks) / len(risks) if risks else 0

            print(f"  {session_name:<25} {trades:>7} {win_rate:>6.1f}% ${pnl:>12,.0f} {avg_risk:>9.2f}")

    # Overnight retrace specific analysis
    print()
    print('=' * 100)
    print('OVERNIGHT RETRACE (RETRACEMENT) FOCUS')
    print('=' * 100)

    overnight_data = []
    for session_name in ['Early AM (9:30-10:00)', 'Mid AM (10:00-11:00)', 'Late AM (11:00-12:00)']:
        data = results_by_session[session_name]['by_type']['RETRACEMENT']
        if data['trades'] > 0:
            win_rate = (data['wins'] / data['trades'] * 100)
            avg_risk = sum(data['risks']) / len(data['risks']) if data['risks'] else 0
            overnight_data.append({
                'session': session_name,
                'trades': data['trades'],
                'wins': data['wins'],
                'win_rate': win_rate,
                'pnl': data['pnl'],
                'avg_risk': avg_risk,
            })

    print(f"\n{'Session':<25} {'Trades':>7} {'Win%':>7} {'P/L':>14} {'Avg Risk':>10}")
    print('-' * 70)
    for d in overnight_data:
        print(f"{d['session']:<25} {d['trades']:>7} {d['win_rate']:>6.1f}% ${d['pnl']:>12,.0f} {d['avg_risk']:>9.2f}")

    # Recommendation
    print()
    print('=' * 100)
    print('RECOMMENDATION')
    print('=' * 100)

    # Find best and worst sessions for overnight retrace
    if overnight_data:
        best = max(overnight_data, key=lambda x: x['win_rate'])
        worst = min(overnight_data, key=lambda x: x['win_rate'])
        print(f"\nOvernight Retrace Performance:")
        print(f"  Best session: {best['session']} ({best['win_rate']:.1f}% WR, ${best['pnl']:,.0f} P/L)")
        print(f"  Worst session: {worst['session']} ({worst['win_rate']:.1f}% WR, ${worst['pnl']:,.0f} P/L)")

        if worst['win_rate'] < 50:
            print(f"\n  SUGGESTION: Consider delaying overnight retrace to {best['session'].split('(')[1].split('-')[0]}")


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    analyze_sessions(symbol, days)
