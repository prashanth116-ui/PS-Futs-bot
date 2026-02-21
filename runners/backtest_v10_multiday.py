"""
V10 Multi-Day Backtest - Validate strategy across multiple trading days.
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10


def backtest_v10_multiday(symbol='ES', days=30, contracts=3, t1_r=3, trail_r=6):
    """Run V10 backtest across multiple days."""

    tick_size = 0.25
    # Tick values: ES=$12.50, NQ=$5.00, MES=$1.25 (1/10 ES), MNQ=$0.50 (1/10 NQ)
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25 if symbol == 'MES' else 0.50 if symbol == 'MNQ' else 1.25
    # Min risk in points (same for micro and mini)
    min_risk_pts = 1.5 if symbol in ['ES', 'MES'] else 6.0 if symbol in ['NQ', 'MNQ'] else 1.5
    # V10.4: Cap BOS entry risk to avoid oversized losses (same for micro and mini)
    max_bos_risk_pts = 8.0 if symbol in ['ES', 'MES'] else 20.0 if symbol in ['NQ', 'MNQ'] else 8.0
    # V10.11: Reduce retrace contracts when risk exceeds threshold (ES/MES only — NQ retraces win big)
    max_retrace_risk_pts = 8.0 if symbol in ['ES', 'MES'] else None

    print(f'Fetching {symbol} 3m data for {days}-day backtest...')
    # Fetch enough bars for 30+ trading days
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=10000)

    if not all_bars:
        print('No data available')
        return

    # Get unique trading dates
    all_dates = sorted(set(b.timestamp.date() for b in all_bars), reverse=True)

    # Filter to trading days only (has RTH bars)
    trading_dates = []
    for d in all_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == d]
        rth_bars = [b for b in day_bars if dt_time(9, 30) <= b.timestamp.time() <= dt_time(16, 0)]
        if len(rth_bars) >= 50:  # Has enough RTH bars
            trading_dates.append(d)
        if len(trading_dates) >= days:
            break

    trading_dates = sorted(trading_dates)  # Oldest first

    print(f'Found {len(trading_dates)} trading days')
    print(f'Date range: {trading_dates[0]} to {trading_dates[-1]}')
    print()
    print('='*80)
    print(f'{symbol} V10 MULTI-DAY BACKTEST - {len(trading_dates)} Days - {contracts} Contracts')
    print('='*80)
    print(f'Strategy: V10.7 Quad Entry (Hybrid Exit - T1 at {t1_r}R, Trail at {trail_r}R)')
    print('  - Entry Types: Creation, Overnight Retrace, Intraday Retrace, BOS')
    print('  - Morning only filter: YES')
    print(f'  - Min risk: {min_risk_pts} pts')
    print(f'  - Max BOS risk: {max_bos_risk_pts} pts')
    print(f'  - Max retrace risk (1-ct cap): {max_retrace_risk_pts} pts')
    print(f'  - T1 Exit: {t1_r}R | Trail Activation: {trail_r}R | Trail Floor: {t1_r}R')
    print('='*80)
    print()

    # Track results
    daily_results = []
    total_trades = 0
    total_wins = 0
    total_losses = 0
    total_pnl = 0

    entry_type_counts = {'CREATION': 0, 'RETRACEMENT': 0, 'INTRADAY_RETRACE': 0, 'BOS_RETRACE': 0}

    max_drawdown = 0
    peak_pnl = 0
    losing_streak = 0
    max_losing_streak = 0

    print(f'{"Date":<12} {"Trades":>7} {"Wins":>5} {"Losses":>7} {"Win%":>6} {"P/L":>12} {"Cumulative":>12}')
    print('-'*80)

    for target_date in trading_dates:
        # Get bars for this date
        day_bars = [b for b in all_bars if b.timestamp.date() == target_date]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # V10.6: Per-symbol BOS control
        disable_bos = symbol in ['ES', 'MES']

        # Run V10 strategy with all filters
        results = run_session_v10(
            session_bars,
            all_bars,
            tick_size=tick_size,
            tick_value=tick_value,
            contracts=contracts,
            min_risk_pts=min_risk_pts,
            enable_creation_entry=True,
            enable_retracement_entry=True,
            enable_bos_entry=True,
            retracement_morning_only=True,
            t1_fixed_4r=True,
            midday_cutoff=True,       # V10.2: No entries 12:00-14:00
            pm_cutoff_nq=True,        # V10.2: No NQ entries after 14:00
            max_bos_risk_pts=max_bos_risk_pts,  # V10.4: Cap BOS risk
            symbol=symbol,
            t1_r_target=t1_r,
            trail_r_trigger=trail_r,
            disable_bos_retrace=disable_bos,      # V10.6: ES/MES BOS off
            bos_daily_loss_limit=1,                # V10.6: 1 loss/day limit
            high_displacement_override=3.0,        # V10.5: 3x skip ADX
            max_retrace_risk_pts=max_retrace_risk_pts,  # V10.11: Reduce retrace cts if high risk
        )

        # Tally results
        day_trades = len(results)
        day_wins = sum(1 for r in results if r['total_dollars'] > 0)
        day_losses = sum(1 for r in results if r['total_dollars'] < 0)
        day_pnl = sum(r['total_dollars'] for r in results)

        total_trades += day_trades
        total_wins += day_wins
        total_losses += day_losses
        total_pnl += day_pnl

        # Track entry types
        for r in results:
            et = r['entry_type']
            if et in entry_type_counts:
                entry_type_counts[et] += 1

        # Track drawdown
        if total_pnl > peak_pnl:
            peak_pnl = total_pnl
        drawdown = peak_pnl - total_pnl
        if drawdown > max_drawdown:
            max_drawdown = drawdown

        # Track losing streak
        if day_pnl < 0:
            losing_streak += 1
            if losing_streak > max_losing_streak:
                max_losing_streak = losing_streak
        else:
            losing_streak = 0

        win_rate = (day_wins / day_trades * 100) if day_trades > 0 else 0

        daily_results.append({
            'date': target_date,
            'trades': day_trades,
            'wins': day_wins,
            'losses': day_losses,
            'pnl': day_pnl,
            'cumulative': total_pnl,
        })

        print(f'{target_date} {day_trades:>7} {day_wins:>5} {day_losses:>7} {win_rate:>5.1f}% ${day_pnl:>+10,.0f} ${total_pnl:>+10,.0f}')

    print('-'*80)
    print()

    # Summary statistics
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

    winning_days = sum(1 for r in daily_results if r['pnl'] > 0)
    losing_days = sum(1 for r in daily_results if r['pnl'] < 0)
    breakeven_days = sum(1 for r in daily_results if r['pnl'] == 0)

    best_day = max(daily_results, key=lambda x: x['pnl'])
    worst_day = min(daily_results, key=lambda x: x['pnl'])

    avg_daily_pnl = total_pnl / len(daily_results) if daily_results else 0

    # Profit factor
    gross_profit = sum(r['pnl'] for r in daily_results if r['pnl'] > 0)
    gross_loss = abs(sum(r['pnl'] for r in daily_results if r['pnl'] < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    print('='*80)
    print('SUMMARY')
    print('='*80)
    print(f'Trading Days:      {len(daily_results)}')
    print(f'Total Trades:      {total_trades}')
    print(f'Total Wins:        {total_wins}')
    print(f'Total Losses:      {total_losses}')
    print(f'Win Rate:          {win_rate:.1f}%')
    print()
    print(f'Winning Days:      {winning_days}')
    print(f'Losing Days:       {losing_days}')
    print(f'Breakeven Days:    {breakeven_days}')
    print(f'Day Win Rate:      {winning_days/len(daily_results)*100:.1f}%')
    print()
    print(f'Total P/L:         ${total_pnl:+,.2f}')
    print(f'Avg Daily P/L:     ${avg_daily_pnl:+,.2f}')
    print(f'Best Day:          {best_day["date"]} ${best_day["pnl"]:+,.2f}')
    print(f'Worst Day:         {worst_day["date"]} ${worst_day["pnl"]:+,.2f}')
    print()
    print(f'Gross Profit:      ${gross_profit:+,.2f}')
    print(f'Gross Loss:        ${gross_loss:+,.2f}')
    print(f'Profit Factor:     {profit_factor:.2f}')
    print()
    print(f'Max Drawdown:      ${max_drawdown:,.2f}')
    print(f'Max Losing Streak: {max_losing_streak} days')
    print()
    print('Entry Type Breakdown:')
    for et, count in entry_type_counts.items():
        pct = count / total_trades * 100 if total_trades > 0 else 0
        print(f'  {et}: {count} ({pct:.1f}%)')
    print('='*80)

    return daily_results


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    contracts = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    # Parse optional R-target flags
    t1_r = 3
    trail_r = 6
    for arg in sys.argv[4:]:
        if arg.startswith('--t1-r='):
            t1_r = int(arg.split('=')[1])
        elif arg.startswith('--trail-r='):
            trail_r = int(arg.split('=')[1])

    backtest_v10_multiday(symbol=symbol, days=days, contracts=contracts, t1_r=t1_r, trail_r=trail_r)
