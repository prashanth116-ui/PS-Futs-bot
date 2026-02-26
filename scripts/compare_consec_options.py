"""Compare consecutive loss stop options across all available ES trading days."""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.bar_storage import load_bars_with_history
from runners.run_v10_dual_entry import run_session_v10


def run_option(label, all_bars, trading_dates, max_consec):
    """Run backtest with given consecutive loss settings."""
    tick_size = 0.25
    tick_value = 12.50
    min_risk_pts = 1.5
    max_bos_risk_pts = 8.0
    max_retrace_risk_pts = 8.0
    contracts = 3

    daily = []
    total_pnl = 0
    total_trades = 0
    total_wins = 0
    total_losses = 0

    for target_date in trading_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == target_date]
        session_bars = [b for b in day_bars
                        if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]
        if len(session_bars) < 50:
            continue

        results = run_session_v10(
            session_bars, all_bars,
            tick_size=tick_size, tick_value=tick_value, contracts=contracts,
            min_risk_pts=min_risk_pts,
            enable_creation_entry=True, enable_retracement_entry=True,
            enable_bos_entry=True, retracement_morning_only=False,
            t1_fixed_4r=True, midday_cutoff=True, pm_cutoff_nq=True,
            symbol='ES', max_bos_risk_pts=max_bos_risk_pts,
            high_displacement_override=3.0,
            disable_bos_retrace=True, bos_daily_loss_limit=1,
            max_retrace_risk_pts=max_retrace_risk_pts,
            max_consec_losses=max_consec,
            t1_r_target=3, trail_r_trigger=6,
        )

        day_pnl = sum(r['total_dollars'] for r in results)
        day_trades = len(results)
        day_wins = sum(1 for r in results if r['total_dollars'] > 0)
        day_losses = sum(1 for r in results if r['total_dollars'] < 0)

        total_pnl += day_pnl
        total_trades += day_trades
        total_wins += day_wins
        total_losses += day_losses

        daily.append({
            'date': target_date,
            'trades': day_trades,
            'wins': day_wins,
            'losses': day_losses,
            'pnl': day_pnl,
            'cumulative': total_pnl,
        })

    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    winning_days = sum(1 for d in daily if d['pnl'] > 0)
    losing_days = sum(1 for d in daily if d['pnl'] < 0)
    worst_day = min(daily, key=lambda x: x['pnl']) if daily else None
    best_day = max(daily, key=lambda x: x['pnl']) if daily else None

    # Max drawdown
    peak = 0
    max_dd = 0
    for d in daily:
        if d['cumulative'] > peak:
            peak = d['cumulative']
        dd = peak - d['cumulative']
        if dd > max_dd:
            max_dd = dd

    return {
        'label': label,
        'daily': daily,
        'total_trades': total_trades,
        'total_wins': total_wins,
        'total_losses': total_losses,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'winning_days': winning_days,
        'losing_days': losing_days,
        'worst_day': worst_day,
        'best_day': best_day,
        'max_dd': max_dd,
    }


def main():
    # Parse optional --days=N argument
    n_days = 14
    for arg in sys.argv[1:]:
        if arg.startswith('--days='):
            n_days = int(arg.split('=')[1])

    print("Loading ES 3m data...")
    all_bars = load_bars_with_history(symbol='ES', interval='3m', n_bars=10000)
    if not all_bars:
        print("No data")
        return

    # Get trading dates
    all_dates = sorted(set(b.timestamp.date() for b in all_bars), reverse=True)
    trading_dates = []
    for d in all_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == d]
        rth = [b for b in day_bars if dt_time(9, 30) <= b.timestamp.time() <= dt_time(16, 0)]
        if len(rth) >= 50:
            trading_dates.append(d)
        if len(trading_dates) >= n_days:
            break
    trading_dates = sorted(trading_dates)

    print(f"Trading days: {len(trading_dates)}")
    print(f"Range: {trading_dates[0]} to {trading_dates[-1]}")
    print()

    # Run options: baseline vs V10.13 (full stop after 2) vs full stop after 3
    options = [
        ("Baseline (no consec stop)", 0),
        ("V10.13: Stop after 2 consec", 2),
        ("Stop after 3 consec", 3),
    ]

    results = []
    for label, max_consec in options:
        print(f"Running: {label}...")
        r = run_option(label, all_bars, trading_dates, max_consec)
        results.append(r)
        print(f"  => {r['total_trades']} trades, {r['win_rate']:.1f}% WR, ${r['total_pnl']:+,.0f}")

    print()
    print("=" * 100)
    print(f"COMPARISON: ES CONSECUTIVE LOSS STOP OPTIONS ({len(trading_dates)} days)")
    print("=" * 100)
    print()

    # Summary table
    header = f"{'Option':<35} {'Trades':>7} {'Wins':>5} {'Loss':>5} {'WR':>6} {'Total P/L':>12} {'Max DD':>10} {'W Days':>7} {'L Days':>7} {'Worst Day':>22}"
    print(header)
    print("-" * 120)

    for r in results:
        wd = r['worst_day']
        worst_str = f"{wd['date']} ${wd['pnl']:+,.0f}" if wd else "N/A"
        print(f"{r['label']:<35} {r['total_trades']:>7} {r['total_wins']:>5} {r['total_losses']:>5} "
              f"{r['win_rate']:>5.1f}% ${r['total_pnl']:>+10,.0f} ${r['max_dd']:>8,.0f} "
              f"{r['winning_days']:>7} {r['losing_days']:>7} {worst_str:>22}")

    print()
    print("=" * 100)
    print("PER-DAY COMPARISON")
    print("=" * 100)

    baseline = results[0]
    print()
    print(f"{'Date':<12}", end="")
    for r in results:
        short = r['label'][:12]
        print(f" {short:>12}", end="")
    # Delta columns
    for r in results[1:]:
        short = r['label'][:8]
        print(f" {short + ' vs BL':>12}", end="")
    print()
    print("-" * (12 + 13 * len(results) + 13 * (len(results) - 1)))

    for i, day in enumerate(baseline['daily']):
        d = day['date']
        print(f"{d}", end="")
        pnls = []
        for r in results:
            rd = r['daily'][i]
            print(f" ${rd['pnl']:>+10,.0f}", end="")
            pnls.append(rd['pnl'])
        # Deltas vs baseline
        for j in range(1, len(pnls)):
            print(f" ${pnls[j]-pnls[0]:>+10,.0f}", end="")
        print()

    print("-" * (12 + 13 * len(results) + 13 * (len(results) - 1)))
    print(f"{'TOTAL':<12}", end="")
    for r in results:
        print(f" ${r['total_pnl']:>+10,.0f}", end="")
    b_pnl = results[0]['total_pnl']
    for r in results[1:]:
        print(f" ${r['total_pnl']-b_pnl:>+10,.0f}", end="")
    print()

    print()
    print("=" * 100)
    print("KEY TAKEAWAYS")
    print("=" * 100)
    for r in results[1:]:
        delta = r['total_pnl'] - baseline['total_pnl']
        dd_delta = r['max_dd'] - baseline['max_dd']
        print(f"  {r['label']}: {'+' if delta >= 0 else ''}{delta:,.0f} P/L vs baseline, "
              f"{'+' if dd_delta >= 0 else ''}{dd_delta:,.0f} max DD change")


if __name__ == '__main__':
    main()
