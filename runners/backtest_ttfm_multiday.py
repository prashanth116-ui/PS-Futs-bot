"""
TTFM Multi-Day Backtest - Validate TTrades Fractal Model across multiple days.

Usage:
    python -m runners.backtest_ttfm_multiday ES 15
    python -m runners.backtest_ttfm_multiday NQ 30
    python -m runners.backtest_ttfm_multiday ES 15 --t1-r=3 --trail-r=6
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.bar_storage import load_bars_with_history
from runners.run_ttfm import run_session_ttfm, SYMBOL_CONFIG


def backtest_ttfm_multiday(symbol='ES', days=15, contracts=3, t1_r=2, trail_r=4):
    """Run TTFM backtest across multiple days."""

    cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG['ES'])
    tick_size = cfg['tick_size']
    tick_value = cfg['tick_value']
    min_risk = cfg['min_risk']
    max_risk = cfg['max_risk']

    print(f'Loading {symbol} 3m data for {days}-day backtest (local + live)...')
    all_bars = load_bars_with_history(symbol=symbol, interval='3m', n_bars=10000)

    if not all_bars:
        print('No data available')
        return

    # Get unique trading dates
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

    print(f'Found {len(trading_dates)} trading days')
    print(f'Date range: {trading_dates[0]} to {trading_dates[-1]}')
    print()
    print('='*80)
    print(f'{symbol} TTFM MULTI-DAY BACKTEST - {len(trading_dates)} Days - {contracts} Contracts')
    print('='*80)
    print(f'Strategy: TTrades Fractal Model (T1={t1_r}R, Trail={trail_r}R)')
    print(f'  Min risk: {min_risk} pts | Max risk: {max_risk} pts')
    print(f'  Contracts: {contracts} (1st) / {max(2, contracts-1)} (subsequent)')
    print('='*80)
    print()

    # Track results
    daily_results = []
    total_trades = 0
    total_wins = 0
    total_losses = 0
    total_pnl = 0

    max_drawdown = 0
    peak_pnl = 0
    losing_streak = 0
    max_losing_streak = 0

    print(f'{"Date":<12} {"Trades":>7} {"Wins":>5} {"Losses":>7} {"Win%":>6} {"P/L":>12} {"Cumulative":>12}')
    print('-'*80)

    for target_date in trading_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == target_date]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        results = run_session_ttfm(
            session_bars, all_bars,
            tick_size=tick_size, tick_value=tick_value,
            contracts=contracts,
            min_risk_pts=min_risk, max_risk_pts=max_risk,
            t1_r_target=t1_r, trail_r_trigger=trail_r,
            symbol=symbol,
        )

        day_trades = len(results)
        day_wins = sum(1 for r in results if r['total_dollars'] > 0)
        day_losses = sum(1 for r in results if r['total_dollars'] < 0)
        day_pnl = sum(r['total_dollars'] for r in results)

        total_trades += day_trades
        total_wins += day_wins
        total_losses += day_losses
        total_pnl += day_pnl

        if total_pnl > peak_pnl:
            peak_pnl = total_pnl
        drawdown = peak_pnl - total_pnl
        if drawdown > max_drawdown:
            max_drawdown = drawdown

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

    if not daily_results:
        print('No trading days found.')
        return daily_results

    # Summary
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    winning_days = sum(1 for r in daily_results if r['pnl'] > 0)
    losing_days = sum(1 for r in daily_results if r['pnl'] < 0)
    breakeven_days = sum(1 for r in daily_results if r['pnl'] == 0)
    best_day = max(daily_results, key=lambda x: x['pnl'])
    worst_day = min(daily_results, key=lambda x: x['pnl'])
    avg_daily_pnl = total_pnl / len(daily_results) if daily_results else 0
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
    print('='*80)

    return daily_results


if __name__ == '__main__':
    # Parse positional and flag args
    positional = []
    t1_r = 2
    trail_r = 4
    for arg in sys.argv[1:]:
        if arg.startswith('--t1-r='):
            t1_r = int(arg.split('=')[1])
        elif arg.startswith('--trail-r='):
            trail_r = int(arg.split('=')[1])
        else:
            positional.append(arg)

    symbol = positional[0] if len(positional) > 0 else 'ES'
    days = int(positional[1]) if len(positional) > 1 else 15
    contracts = int(positional[2]) if len(positional) > 2 else 3

    backtest_ttfm_multiday(symbol=symbol, days=days, contracts=contracts, t1_r=t1_r, trail_r=trail_r)
