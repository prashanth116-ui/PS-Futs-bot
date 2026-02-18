"""
Time-of-Day Analysis — Break down trade performance by entry hour.

Runs multi-day backtest and groups results by entry time to find
optimal trading windows and underperforming hours.
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time, timedelta
from collections import defaultdict
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10


def analyze_time_of_day(symbol='ES', days=15, contracts=3, t1_r=3, trail_r=6):
    """Analyze trade performance by time of day."""

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25 if symbol == 'MES' else 0.50 if symbol == 'MNQ' else 1.25
    min_risk_pts = 1.5 if symbol in ['ES', 'MES'] else 6.0 if symbol in ['NQ', 'MNQ'] else 1.5
    max_bos_risk_pts = 8.0 if symbol in ['ES', 'MES'] else 20.0 if symbol in ['NQ', 'MNQ'] else 8.0
    disable_bos = symbol in ['ES', 'MES']

    print(f'Fetching {symbol} 3m data for {days}-day analysis...')
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
    print(f'Found {len(trading_dates)} trading days ({trading_dates[0]} to {trading_dates[-1]})')

    # Collect all trades with time info
    all_trades = []

    for target_date in trading_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == target_date]
        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        results = run_session_v10(
            session_bars, all_bars,
            tick_size=tick_size, tick_value=tick_value,
            contracts=contracts, min_risk_pts=min_risk_pts,
            enable_creation_entry=True, enable_retracement_entry=True,
            enable_bos_entry=True, retracement_morning_only=True,
            t1_fixed_4r=True, midday_cutoff=True, pm_cutoff_nq=True,
            max_bos_risk_pts=max_bos_risk_pts, symbol=symbol,
            t1_r_target=t1_r, trail_r_trigger=trail_r,
            disable_bos_retrace=disable_bos, bos_daily_loss_limit=1,
            high_displacement_override=3.0,
        )

        for r in results:
            all_trades.append({
                'date': target_date,
                'entry_time': r['entry_time'],
                'hour': r['entry_time'].hour,
                'minute': r['entry_time'].minute,
                'half_hour': f"{r['entry_time'].hour}:{0 if r['entry_time'].minute < 30 else 30:02d}",
                'direction': r['direction'],
                'entry_type': r['entry_type'],
                'pnl': r['total_dollars'],
                'risk': r.get('risk', 0),
                'is_win': r['total_dollars'] > 0,
                'is_loss': r['total_dollars'] < 0,
            })

    print(f'\nTotal trades collected: {len(all_trades)}')

    # === Analysis by Hour ===
    print('\n' + '=' * 90)
    print(f'{symbol} TIME-OF-DAY ANALYSIS — {len(trading_dates)} Days')
    print('=' * 90)

    # Group by hour
    by_hour = defaultdict(list)
    for t in all_trades:
        by_hour[t['hour']].append(t)

    print(f'\n{"Hour":<8} {"Trades":>7} {"Wins":>5} {"Losses":>7} {"Win%":>7} {"Total P/L":>12} {"Avg P/L":>10} {"Best":>10} {"Worst":>10}')
    print('-' * 90)

    hour_summary = []
    for hour in sorted(by_hour.keys()):
        trades = by_hour[hour]
        wins = sum(1 for t in trades if t['is_win'])
        losses = sum(1 for t in trades if t['is_loss'])
        total_pnl = sum(t['pnl'] for t in trades)
        avg_pnl = total_pnl / len(trades) if trades else 0
        best = max(t['pnl'] for t in trades)
        worst = min(t['pnl'] for t in trades)
        win_rate = wins / len(trades) * 100 if trades else 0

        label = f"{hour:02d}:00"
        print(f'{label:<8} {len(trades):>7} {wins:>5} {losses:>7} {win_rate:>6.1f}% ${total_pnl:>+10,.0f} ${avg_pnl:>+8,.0f} ${best:>+8,.0f} ${worst:>+8,.0f}')

        hour_summary.append({
            'hour': hour, 'label': label, 'trades': len(trades),
            'wins': wins, 'losses': losses, 'win_rate': win_rate,
            'total_pnl': total_pnl, 'avg_pnl': avg_pnl,
        })

    print('-' * 90)
    total_pnl = sum(t['pnl'] for t in all_trades)
    total_wins = sum(1 for t in all_trades if t['is_win'])
    total_losses = sum(1 for t in all_trades if t['is_loss'])
    print(f'{"TOTAL":<8} {len(all_trades):>7} {total_wins:>5} {total_losses:>7} {total_wins/len(all_trades)*100:>6.1f}% ${total_pnl:>+10,.0f}')

    # === Analysis by 30-min block ===
    print(f'\n{"Block":<8} {"Trades":>7} {"Wins":>5} {"Losses":>7} {"Win%":>7} {"Total P/L":>12} {"Avg P/L":>10}')
    print('-' * 70)

    by_half = defaultdict(list)
    for t in all_trades:
        by_half[t['half_hour']].append(t)

    for block in sorted(by_half.keys()):
        trades = by_half[block]
        wins = sum(1 for t in trades if t['is_win'])
        losses = sum(1 for t in trades if t['is_loss'])
        total = sum(t['pnl'] for t in trades)
        avg = total / len(trades) if trades else 0
        wr = wins / len(trades) * 100 if trades else 0
        flag = ' <<<' if wr < 60 or total < 0 else ''
        print(f'{block:<8} {len(trades):>7} {wins:>5} {losses:>7} {wr:>6.1f}% ${total:>+10,.0f} ${avg:>+8,.0f}{flag}')

    # === Analysis by Direction + Hour ===
    print(f'\n{"Hour":<8} {"L Trades":>8} {"L Win%":>7} {"L P/L":>12} {"S Trades":>8} {"S Win%":>7} {"S P/L":>12}')
    print('-' * 70)

    for hour in sorted(by_hour.keys()):
        trades = by_hour[hour]
        longs = [t for t in trades if t['direction'] == 'LONG']
        shorts = [t for t in trades if t['direction'] == 'SHORT']

        l_wins = sum(1 for t in longs if t['is_win'])
        l_wr = l_wins / len(longs) * 100 if longs else 0
        l_pnl = sum(t['pnl'] for t in longs)

        s_wins = sum(1 for t in shorts if t['is_win'])
        s_wr = s_wins / len(shorts) * 100 if shorts else 0
        s_pnl = sum(t['pnl'] for t in shorts)

        label = f"{hour:02d}:00"
        l_str = f"{len(longs):>8} {l_wr:>6.1f}% ${l_pnl:>+10,.0f}" if longs else f"{'—':>8} {'—':>7} {'—':>12}"
        s_str = f"{len(shorts):>8} {s_wr:>6.1f}% ${s_pnl:>+10,.0f}" if shorts else f"{'—':>8} {'—':>7} {'—':>12}"
        print(f'{label:<8} {l_str} {s_str}')

    # === Analysis by Entry Type + Hour ===
    print(f'\n{"Hour":<8} {"Creation":>10} {"Cr Win%":>8} {"Cr P/L":>12} {"Other":>7} {"Oth Win%":>9} {"Oth P/L":>12}')
    print('-' * 75)

    for hour in sorted(by_hour.keys()):
        trades = by_hour[hour]
        creation = [t for t in trades if t['entry_type'] == 'CREATION']
        other = [t for t in trades if t['entry_type'] != 'CREATION']

        c_wins = sum(1 for t in creation if t['is_win'])
        c_wr = c_wins / len(creation) * 100 if creation else 0
        c_pnl = sum(t['pnl'] for t in creation)

        o_wins = sum(1 for t in other if t['is_win'])
        o_wr = o_wins / len(other) * 100 if other else 0
        o_pnl = sum(t['pnl'] for t in other)

        label = f"{hour:02d}:00"
        c_str = f"{len(creation):>10} {c_wr:>7.1f}% ${c_pnl:>+10,.0f}" if creation else f"{'—':>10} {'—':>8} {'—':>12}"
        o_str = f"{len(other):>7} {o_wr:>8.1f}% ${o_pnl:>+10,.0f}" if other else f"{'—':>7} {'—':>9} {'—':>12}"
        print(f'{label:<8} {c_str} {o_str}')

    # === Recommendations ===
    print('\n' + '=' * 90)
    print('RECOMMENDATIONS')
    print('=' * 90)

    # Find best and worst hours
    profitable_hours = [h for h in hour_summary if h['total_pnl'] > 0]
    unprofitable_hours = [h for h in hour_summary if h['total_pnl'] <= 0]
    low_wr_hours = [h for h in hour_summary if h['win_rate'] < 60 and h['trades'] >= 3]

    if profitable_hours:
        best = max(profitable_hours, key=lambda h: h['total_pnl'])
        print(f'Best hour:  {best["label"]} — {best["trades"]} trades, {best["win_rate"]:.1f}% WR, ${best["total_pnl"]:+,.0f}')

    if unprofitable_hours:
        print(f'\nUnprofitable hours:')
        for h in sorted(unprofitable_hours, key=lambda x: x['total_pnl']):
            print(f'  {h["label"]} — {h["trades"]} trades, {h["win_rate"]:.1f}% WR, ${h["total_pnl"]:+,.0f}')

    if low_wr_hours:
        print(f'\nLow win rate hours (<60%):')
        for h in sorted(low_wr_hours, key=lambda x: x['win_rate']):
            print(f'  {h["label"]} — {h["trades"]} trades, {h["win_rate"]:.1f}% WR, ${h["total_pnl"]:+,.0f}')

    # Calculate what-if: removing worst hours
    if unprofitable_hours:
        bad_hours = set(h['hour'] for h in unprofitable_hours)
        filtered_trades = [t for t in all_trades if t['hour'] not in bad_hours]
        filtered_pnl = sum(t['pnl'] for t in filtered_trades)
        filtered_wins = sum(1 for t in filtered_trades if t['is_win'])
        filtered_wr = filtered_wins / len(filtered_trades) * 100 if filtered_trades else 0
        removed_pnl = sum(h['total_pnl'] for h in unprofitable_hours)

        print(f'\nWhat-if: Remove unprofitable hours ({", ".join(h["label"] for h in unprofitable_hours)}):')
        print(f'  Current:  {len(all_trades)} trades, {total_wins/len(all_trades)*100:.1f}% WR, ${total_pnl:+,.0f}')
        print(f'  Filtered: {len(filtered_trades)} trades, {filtered_wr:.1f}% WR, ${filtered_pnl:+,.0f}')
        print(f'  Improvement: ${filtered_pnl - total_pnl:+,.0f} ({(filtered_pnl - total_pnl) / abs(total_pnl) * 100:+.1f}%)')

    print('=' * 90)

    return all_trades


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    analyze_time_of_day(symbol=symbol, days=days)
