"""
TTFM Long-Range Backtest - Fetch native 15m/1H/daily bars from TradingView.

Gets 60+ days of history by fetching 15m bars directly (77 days available)
instead of aggregating from 3m bars (only 18 days available).

Usage:
    python -m ttfm.runners.backtest_longrange ES 60
    python -m ttfm.runners.backtest_longrange NQ 60
    python -m ttfm.runners.backtest_longrange ES 60 --t1-r=1 --trail-r=3
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time, date as dt_date
from ttfm.tradingview_loader import fetch_futures_bars
from ttfm.runners.run_ttfm import run_session_ttfm_native, SYMBOL_CONFIG, _build_daily_bars
from ttfm.signals.bias import determine_bias


def backtest_ttfm_longrange(symbol='ES', days=60, contracts=3, t1_r=2, trail_r=4,
                            risk_cap_pts=None, allow_lunch=False,
                            rth_only=False, skip_deadzone=False, t2_r=None):
    """Run TTFM backtest using native TradingView timeframe data."""

    cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG['ES'])
    tick_size = cfg['tick_size']
    tick_value = cfg['tick_value']
    min_risk = cfg['min_risk']
    max_risk = cfg['max_risk']

    # When risk cap is used, raise absolute max to allow oversized trades through
    if risk_cap_pts and risk_cap_pts < max_risk:
        pass
    elif risk_cap_pts:
        max_risk = risk_cap_pts * 2

    # Fetch all timeframes directly from TradingView
    print(f'Fetching {symbol} data from TradingView...')
    print(f'  15m bars...', end=' ', flush=True)
    bars_15m = fetch_futures_bars(symbol=symbol, interval='15m', n_bars=10000)
    print(f'{len(bars_15m)} bars')
    print(f'  1H bars...', end=' ', flush=True)
    bars_1h = fetch_futures_bars(symbol=symbol, interval='1h', n_bars=10000)
    print(f'{len(bars_1h)} bars')
    print(f'  Daily bars...', end=' ', flush=True)
    bars_daily = fetch_futures_bars(symbol=symbol, interval='1d', n_bars=500)
    print(f'{len(bars_daily)} bars')

    if not bars_15m or not bars_1h or not bars_daily:
        print('Failed to fetch data')
        return

    # Get unique trading dates from 15m data
    all_dates = sorted(set(b.timestamp.date() for b in bars_15m), reverse=True)

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)

    trading_dates = []
    for d in all_dates:
        day_15m = [b for b in bars_15m if b.timestamp.date() == d
                   and premarket_start <= b.timestamp.time() <= rth_end]
        if len(day_15m) >= 20:
            trading_dates.append(d)
        if len(trading_dates) >= days:
            break

    trading_dates = sorted(trading_dates)

    if not trading_dates:
        print('No valid trading days found')
        return

    print(f'\nFound {len(trading_dates)} trading days')
    print(f'Date range: {trading_dates[0]} to {trading_dates[-1]}')
    print()
    print('=' * 80)
    print(f'{symbol} TTFM LONG-RANGE BACKTEST - {len(trading_dates)} Days - {contracts} Contracts')
    print('=' * 80)
    print(f'Strategy: TTrades Fractal Model (T1={t1_r}R, Trail={trail_r}R)')
    print(f'  Data: Native 15m/1H/Daily from TradingView (no 3m aggregation)')
    print(f'  Min risk: {min_risk} pts | Max risk: {max_risk} pts')
    if risk_cap_pts:
        print(f'  Risk cap: {risk_cap_pts} pts (oversized -> 1 ct)')
    if skip_deadzone:
        print(f'  Risk dead zone: SKIP 7-12 pts')
    print(f'  Session: {"RTH only (08:00+)" if rth_only else "Pre-market + RTH (04:00+)"}')
    print(f'  Lunch entries: {"YES" if allow_lunch else "NO (12:00-14:00 blocked)"}')
    if t2_r:
        print(f'  Exits: T1={t1_r}R, T2={t2_r}R, Trail={trail_r}R')
    else:
        print(f'  Exits: T1={t1_r}R, Trail={trail_r}R')
    print(f'  Contracts: {contracts} (1st) / {max(2, contracts - 1)} (subsequent)')
    print('=' * 80)
    print()

    # Track results
    daily_results = []
    total_trades = 0
    total_wins = 0
    total_losses = 0
    total_pnl = 0.0

    max_drawdown = 0.0
    peak_pnl = 0.0
    losing_streak = 0
    max_losing_streak = 0

    all_trade_details = []

    print(f'{"Date":<12} {"Bias":<7} {"Trades":>6} {"Wins":>5} {"Losses":>6} {"Win%":>6} {"P/L":>12} {"Cumulative":>12}')
    print('-' * 80)

    for target_date in trading_dates:
        day_15m = [b for b in bars_15m if b.timestamp.date() == target_date
                   and premarket_start <= b.timestamp.time() <= rth_end]
        day_1h = [b for b in bars_1h if b.timestamp.date() == target_date
                  and premarket_start <= b.timestamp.time() <= rth_end]

        if len(day_15m) < 10:
            continue

        history_daily = [b for b in bars_daily if b.timestamp.date() < target_date]
        if len(history_daily) < 2:
            continue

        results = run_session_ttfm_native(
            day_15m, day_1h, history_daily,
            tick_size=tick_size, tick_value=tick_value,
            contracts=contracts,
            min_risk_pts=min_risk, max_risk_pts=max_risk,
            t1_r_target=t1_r, trail_r_trigger=trail_r,
            symbol=symbol,
            risk_cap_pts=risk_cap_pts,
            allow_lunch=allow_lunch,
            rth_only=rth_only,
            skip_risk_deadzone=skip_deadzone,
            t2_r_target=t2_r,
        )

        day_trades = len(results)
        day_wins = sum(1 for r in results if r['total_dollars'] > 0)
        day_losses = sum(1 for r in results if r['total_dollars'] < 0)
        day_pnl = sum(r['total_dollars'] for r in results)

        bias = determine_bias(history_daily)
        bias_short = bias.direction[:4]

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
        elif day_pnl > 0:
            losing_streak = 0

        win_rate = (day_wins / day_trades * 100) if day_trades > 0 else 0

        daily_results.append({
            'date': target_date,
            'trades': day_trades,
            'wins': day_wins,
            'losses': day_losses,
            'pnl': day_pnl,
            'cumulative': total_pnl,
            'bias': bias.direction,
        })

        for r in results:
            all_trade_details.append({**r, 'date': target_date})

        print(f'{target_date} {bias_short:<7} {day_trades:>6} {day_wins:>5} {day_losses:>6} {win_rate:>5.1f}% ${day_pnl:>+10,.0f} ${total_pnl:>+10,.0f}')

    print('-' * 80)
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

    bull_trades = [t for t in all_trade_details if t['direction'] == 'BULLISH']
    bear_trades = [t for t in all_trade_details if t['direction'] == 'BEARISH']
    bull_wins = sum(1 for t in bull_trades if t['total_dollars'] > 0)
    bear_wins = sum(1 for t in bear_trades if t['total_dollars'] > 0)
    bull_pnl = sum(t['total_dollars'] for t in bull_trades)
    bear_pnl = sum(t['total_dollars'] for t in bear_trades)

    print('=' * 80)
    print('SUMMARY')
    print('=' * 80)
    print(f'Trading Days:      {len(daily_results)}')
    print(f'Total Trades:      {total_trades}')
    print(f'Total Wins:        {total_wins}')
    print(f'Total Losses:      {total_losses}')
    print(f'Win Rate:          {win_rate:.1f}%')
    print()
    print(f'Winning Days:      {winning_days}')
    print(f'Losing Days:       {losing_days}')
    print(f'Breakeven Days:    {breakeven_days}')
    print(f'Day Win Rate:      {winning_days / len(daily_results) * 100:.1f}%')
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
    print('-- Direction Breakdown --')
    print(f'BULLISH: {len(bull_trades)} trades, {bull_wins}W/{len(bull_trades)-bull_wins}L, P/L ${bull_pnl:+,.0f}')
    print(f'BEARISH: {len(bear_trades)} trades, {bear_wins}W/{len(bear_trades)-bear_wins}L, P/L ${bear_pnl:+,.0f}')
    print('=' * 80)

    # Trade detail dump
    if all_trade_details:
        print()
        print('-- All Trades --')
        print(f'{"Date":<12} {"Time":<6} {"Dir":<6} {"Entry":>10} {"Stop":>10} {"Risk":>6} {"Cts":>4} {"P/L":>10} {"Exit":<20}')
        print('-' * 90)
        for t in all_trade_details:
            exits_str = ', '.join(e['type'] for e in t['exits'])
            tm = t['entry_time']
            print(f'{t["date"]!s:<12} {tm.strftime("%H:%M"):<6} {t["direction"][:5]:<6} {t["entry_price"]:>10.2f} {t["stop_price"]:>10.2f} {t["risk"]:>6.2f} {t["contracts"]:>4} ${t["total_dollars"]:>+9,.0f} {exits_str}')

    return daily_results


if __name__ == '__main__':
    positional = []
    t1_r = 2
    trail_r = 4
    risk_cap = None
    allow_lunch = False
    rth_only = False
    skip_deadzone = False
    t2_r = None
    for arg in sys.argv[1:]:
        if arg.startswith('--t1-r='):
            t1_r = int(arg.split('=')[1])
        elif arg.startswith('--trail-r='):
            trail_r = int(arg.split('=')[1])
        elif arg.startswith('--t2-r='):
            t2_r = int(arg.split('=')[1])
        elif arg.startswith('--risk-cap='):
            risk_cap = float(arg.split('=')[1])
        elif arg == '--lunch':
            allow_lunch = True
        elif arg == '--rth':
            rth_only = True
        elif arg == '--skip-deadzone':
            skip_deadzone = True
        else:
            positional.append(arg)

    symbol = positional[0] if len(positional) > 0 else 'ES'
    days = int(positional[1]) if len(positional) > 1 else 60
    contracts = int(positional[2]) if len(positional) > 2 else 3

    backtest_ttfm_longrange(symbol=symbol, days=days, contracts=contracts,
                            t1_r=t1_r, trail_r=trail_r,
                            risk_cap_pts=risk_cap, allow_lunch=allow_lunch,
                            rth_only=rth_only, skip_deadzone=skip_deadzone,
                            t2_r=t2_r)
