"""
Compare Optimal vs Baseline - Daily Performance Analysis

Baseline: V10.5 (all BOS on)
Optimal: V10.6 (ES BOS off, NQ BOS on, SPY BOS off, QQQ BOS on)
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from collections import defaultdict
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10
from runners.run_v10_equity import run_session_v10_equity

days = 30


def run_day_futures(session_bars, all_bars, symbol, tick_size, tick_value, disable_bos):
    """Run single day futures backtest."""
    if len(session_bars) < 50:
        return []

    min_risk = 1.5 if symbol in ['ES', 'MES'] else 6.0
    max_bos = 8.0 if symbol in ['ES', 'MES'] else 20.0

    results = run_session_v10(
        session_bars, all_bars,
        tick_size=tick_size,
        tick_value=tick_value,
        contracts=3,
        min_risk_pts=min_risk,
        t1_fixed_4r=True,
        overnight_retrace_min_adx=22,
        midday_cutoff=True,
        pm_cutoff_nq=True,
        max_bos_risk_pts=max_bos,
        high_displacement_override=3.0,
        disable_bos_retrace=disable_bos,
        symbol=symbol,
    )
    return results


def run_day_equity(session_bars, all_bars, symbol, disable_bos):
    """Run single day equity backtest."""
    if len(session_bars) < 50:
        return []

    results = run_session_v10_equity(
        session_bars, all_bars,
        symbol=symbol,
        risk_per_trade=500,
        t1_fixed_4r=True,
        overnight_retrace_min_adx=22,
        midday_cutoff=True,
        pm_cutoff_qqq=True,
        disable_intraday_spy=True,
        atr_buffer_multiplier=0.5,
        high_displacement_override=3.0,
        disable_bos_retrace=disable_bos,
    )
    return results


def main():
    print('Fetching data...')
    es_bars = fetch_futures_bars('ES', interval='3m', n_bars=15000)
    nq_bars = fetch_futures_bars('NQ', interval='3m', n_bars=15000)
    spy_bars = fetch_futures_bars('SPY', interval='3m', n_bars=15000)
    qqq_bars = fetch_futures_bars('QQQ', interval='3m', n_bars=15000)

    # Get trading dates
    all_dates = sorted(set(b.timestamp.date() for b in es_bars))
    recent_dates = all_dates[-days:]

    # Store daily results
    baseline_daily = defaultdict(lambda: {'pnl': 0, 'trades': 0, 'wins': 0})
    optimal_daily = defaultdict(lambda: {'pnl': 0, 'trades': 0, 'wins': 0})

    # BOS settings
    # Baseline: all BOS on (disable_bos=False)
    # Optimal: ES off, NQ on, SPY off, QQQ on
    optimal_bos = {'ES': True, 'NQ': False, 'SPY': True, 'QQQ': False}

    print('\nProcessing daily results...')

    for target_date in recent_dates:
        # ES
        es_day = [b for b in es_bars if b.timestamp.date() == target_date]
        es_session = [b for b in es_day if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]

        baseline_es = run_day_futures(es_session, es_bars, 'ES', 0.25, 12.50, False)
        optimal_es = run_day_futures(es_session, es_bars, 'ES', 0.25, 12.50, optimal_bos['ES'])

        for r in baseline_es:
            baseline_daily[target_date]['pnl'] += r['total_dollars']
            baseline_daily[target_date]['trades'] += 1
            if r['total_dollars'] > 0:
                baseline_daily[target_date]['wins'] += 1

        for r in optimal_es:
            optimal_daily[target_date]['pnl'] += r['total_dollars']
            optimal_daily[target_date]['trades'] += 1
            if r['total_dollars'] > 0:
                optimal_daily[target_date]['wins'] += 1

        # NQ
        nq_day = [b for b in nq_bars if b.timestamp.date() == target_date]
        nq_session = [b for b in nq_day if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]

        baseline_nq = run_day_futures(nq_session, nq_bars, 'NQ', 0.25, 5.00, False)
        optimal_nq = run_day_futures(nq_session, nq_bars, 'NQ', 0.25, 5.00, optimal_bos['NQ'])

        for r in baseline_nq:
            baseline_daily[target_date]['pnl'] += r['total_dollars']
            baseline_daily[target_date]['trades'] += 1
            if r['total_dollars'] > 0:
                baseline_daily[target_date]['wins'] += 1

        for r in optimal_nq:
            optimal_daily[target_date]['pnl'] += r['total_dollars']
            optimal_daily[target_date]['trades'] += 1
            if r['total_dollars'] > 0:
                optimal_daily[target_date]['wins'] += 1

        # SPY
        spy_day = [b for b in spy_bars if b.timestamp.date() == target_date]
        spy_session = [b for b in spy_day if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]

        baseline_spy = run_day_equity(spy_session, spy_bars, 'SPY', False)
        optimal_spy = run_day_equity(spy_session, spy_bars, 'SPY', optimal_bos['SPY'])

        for r in baseline_spy:
            baseline_daily[target_date]['pnl'] += r['total_dollars']
            baseline_daily[target_date]['trades'] += 1
            if r['total_dollars'] > 0:
                baseline_daily[target_date]['wins'] += 1

        for r in optimal_spy:
            optimal_daily[target_date]['pnl'] += r['total_dollars']
            optimal_daily[target_date]['trades'] += 1
            if r['total_dollars'] > 0:
                optimal_daily[target_date]['wins'] += 1

        # QQQ
        qqq_day = [b for b in qqq_bars if b.timestamp.date() == target_date]
        qqq_session = [b for b in qqq_day if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]

        baseline_qqq = run_day_equity(qqq_session, qqq_bars, 'QQQ', False)
        optimal_qqq = run_day_equity(qqq_session, qqq_bars, 'QQQ', optimal_bos['QQQ'])

        for r in baseline_qqq:
            baseline_daily[target_date]['pnl'] += r['total_dollars']
            baseline_daily[target_date]['trades'] += 1
            if r['total_dollars'] > 0:
                baseline_daily[target_date]['wins'] += 1

        for r in optimal_qqq:
            optimal_daily[target_date]['pnl'] += r['total_dollars']
            optimal_daily[target_date]['trades'] += 1
            if r['total_dollars'] > 0:
                optimal_daily[target_date]['wins'] += 1

    # Convert to lists for sorting
    baseline_days = [(d, baseline_daily[d]) for d in recent_dates]
    optimal_days = [(d, optimal_daily[d]) for d in recent_dates]

    # Sort by P/L
    baseline_sorted = sorted(baseline_days, key=lambda x: x[1]['pnl'], reverse=True)
    optimal_sorted = sorted(optimal_days, key=lambda x: x[1]['pnl'], reverse=True)

    print('\n' + '=' * 90)
    print('DAILY PERFORMANCE COMPARISON (30 days)')
    print('=' * 90)

    # Summary stats
    baseline_total = sum(d[1]['pnl'] for d in baseline_days)
    optimal_total = sum(d[1]['pnl'] for d in optimal_days)

    baseline_win_days = sum(1 for d in baseline_days if d[1]['pnl'] > 0)
    optimal_win_days = sum(1 for d in optimal_days if d[1]['pnl'] > 0)

    baseline_trades = sum(d[1]['trades'] for d in baseline_days)
    optimal_trades = sum(d[1]['trades'] for d in optimal_days)

    print(f"\n{'Metric':<25} {'Baseline (V10.5)':<20} {'Optimal (V10.6)':<20} {'Change':<15}")
    print('-' * 80)
    print(f"{'Total P/L':<25} ${baseline_total:>17,.0f} ${optimal_total:>17,.0f} ${optimal_total - baseline_total:>+13,.0f}")
    print(f"{'Winning Days':<25} {baseline_win_days:>17} {optimal_win_days:>17} {optimal_win_days - baseline_win_days:>+13}")
    print(f"{'Losing Days':<25} {len(recent_dates) - baseline_win_days:>17} {len(recent_dates) - optimal_win_days:>17} {(len(recent_dates) - optimal_win_days) - (len(recent_dates) - baseline_win_days):>+13}")
    print(f"{'Win Day %':<25} {baseline_win_days/len(recent_dates)*100:>16.1f}% {optimal_win_days/len(recent_dates)*100:>16.1f}% {(optimal_win_days - baseline_win_days)/len(recent_dates)*100:>+12.1f}%")
    print(f"{'Total Trades':<25} {baseline_trades:>17} {optimal_trades:>17} {optimal_trades - baseline_trades:>+13}")

    # Best days
    print('\n' + '=' * 90)
    print('TOP 5 BEST DAYS')
    print('=' * 90)

    print(f"\n{'Rank':<5} {'Date':<12} {'Baseline P/L':>14} {'Optimal P/L':>14} {'Diff':>12} {'Better':>10}")
    print('-' * 70)

    for i in range(5):
        base_date, base_data = baseline_sorted[i]
        opt_data = optimal_daily[base_date]
        diff = opt_data['pnl'] - base_data['pnl']
        better = 'OPTIMAL' if diff > 0 else 'BASELINE' if diff < 0 else 'SAME'
        print(f"{i+1:<5} {str(base_date):<12} ${base_data['pnl']:>12,.0f} ${opt_data['pnl']:>12,.0f} ${diff:>+10,.0f} {better:>10}")

    # Worst days
    print('\n' + '=' * 90)
    print('TOP 5 WORST DAYS')
    print('=' * 90)

    print(f"\n{'Rank':<5} {'Date':<12} {'Baseline P/L':>14} {'Optimal P/L':>14} {'Diff':>12} {'Better':>10}")
    print('-' * 70)

    for i in range(5):
        base_date, base_data = baseline_sorted[-(i+1)]
        opt_data = optimal_daily[base_date]
        diff = opt_data['pnl'] - base_data['pnl']
        better = 'OPTIMAL' if diff > 0 else 'BASELINE' if diff < 0 else 'SAME'
        print(f"{i+1:<5} {str(base_date):<12} ${base_data['pnl']:>12,.0f} ${opt_data['pnl']:>12,.0f} ${diff:>+10,.0f} {better:>10}")

    # Day-by-day comparison
    print('\n' + '=' * 90)
    print('FULL 30-DAY COMPARISON')
    print('=' * 90)

    print(f"\n{'Date':<12} {'Baseline':>12} {'Optimal':>12} {'Diff':>10} {'Winner':>10}")
    print('-' * 60)

    optimal_wins = 0
    baseline_wins = 0
    ties = 0

    for date in recent_dates:
        base_pnl = baseline_daily[date]['pnl']
        opt_pnl = optimal_daily[date]['pnl']
        diff = opt_pnl - base_pnl

        if diff > 0:
            winner = 'OPTIMAL'
            optimal_wins += 1
        elif diff < 0:
            winner = 'BASELINE'
            baseline_wins += 1
        else:
            winner = 'TIE'
            ties += 1

        print(f"{str(date):<12} ${base_pnl:>10,.0f} ${opt_pnl:>10,.0f} ${diff:>+8,.0f} {winner:>10}")

    print('-' * 60)
    print(f"\nOptimal wins: {optimal_wins} days")
    print(f"Baseline wins: {baseline_wins} days")
    print(f"Ties: {ties} days")

    # Drawdown comparison
    print('\n' + '=' * 90)
    print('DRAWDOWN ANALYSIS')
    print('=' * 90)

    baseline_running = 0
    baseline_peak = 0
    baseline_max_dd = 0

    optimal_running = 0
    optimal_peak = 0
    optimal_max_dd = 0

    for date in recent_dates:
        baseline_running += baseline_daily[date]['pnl']
        if baseline_running > baseline_peak:
            baseline_peak = baseline_running
        dd = baseline_peak - baseline_running
        if dd > baseline_max_dd:
            baseline_max_dd = dd

        optimal_running += optimal_daily[date]['pnl']
        if optimal_running > optimal_peak:
            optimal_peak = optimal_running
        dd = optimal_peak - optimal_running
        if dd > optimal_max_dd:
            optimal_max_dd = dd

    print(f"\n{'Metric':<25} {'Baseline':<20} {'Optimal':<20}")
    print('-' * 65)
    print(f"{'Max Drawdown':<25} ${baseline_max_dd:>17,.0f} ${optimal_max_dd:>17,.0f}")
    print(f"{'Peak Equity':<25} ${baseline_peak:>17,.0f} ${optimal_peak:>17,.0f}")
    print(f"{'Final Equity':<25} ${baseline_running:>17,.0f} ${optimal_running:>17,.0f}")

    # Average day stats
    print('\n' + '=' * 90)
    print('AVERAGE DAY STATISTICS')
    print('=' * 90)

    baseline_avg = baseline_total / len(recent_dates)
    optimal_avg = optimal_total / len(recent_dates)

    baseline_win_avg = sum(d[1]['pnl'] for d in baseline_days if d[1]['pnl'] > 0) / max(1, baseline_win_days)
    optimal_win_avg = sum(d[1]['pnl'] for d in optimal_days if d[1]['pnl'] > 0) / max(1, optimal_win_days)

    baseline_loss_avg = sum(d[1]['pnl'] for d in baseline_days if d[1]['pnl'] <= 0) / max(1, len(recent_dates) - baseline_win_days)
    optimal_loss_avg = sum(d[1]['pnl'] for d in optimal_days if d[1]['pnl'] <= 0) / max(1, len(recent_dates) - optimal_win_days)

    print(f"\n{'Metric':<25} {'Baseline':<20} {'Optimal':<20}")
    print('-' * 65)
    print(f"{'Avg Daily P/L':<25} ${baseline_avg:>17,.0f} ${optimal_avg:>17,.0f}")
    print(f"{'Avg Winning Day':<25} ${baseline_win_avg:>17,.0f} ${optimal_win_avg:>17,.0f}")
    print(f"{'Avg Losing Day':<25} ${baseline_loss_avg:>17,.0f} ${optimal_loss_avg:>17,.0f}")

    # Final summary
    print('\n' + '=' * 90)
    print('CONCLUSION')
    print('=' * 90)

    print(f"\nOptimal (V10.6) vs Baseline (V10.5):")
    print(f"  P/L Improvement: ${optimal_total - baseline_total:+,.0f}")
    print(f"  Winning Days: {optimal_win_days} vs {baseline_win_days}")
    print(f"  Days Optimal Won: {optimal_wins}/{len(recent_dates)}")
    print(f"  Max DD: ${optimal_max_dd:,.0f} vs ${baseline_max_dd:,.0f}")


if __name__ == '__main__':
    main()
