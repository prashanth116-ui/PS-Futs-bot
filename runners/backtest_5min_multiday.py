"""
V10 Multi-Day Backtest - 5-Minute Bars
Compare 5-min vs 3-min performance
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time, timedelta
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10


def backtest_5min_multiday(symbol='ES', days=30, contracts=3):
    """Run V10 backtest on 5-minute bars across multiple days."""

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25 if symbol == 'MES' else 0.50
    min_risk_pts = 1.5 if symbol in ['ES', 'MES'] else 6.0
    max_bos_risk_pts = 8.0 if symbol in ['ES', 'MES'] else 20.0

    print(f'Fetching {symbol} 5m data for {days}-day backtest...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='5m', n_bars=10000)

    if not all_bars:
        print('No data available')
        return None

    # Get unique trading dates
    all_dates = sorted(set(b.timestamp.date() for b in all_bars), reverse=True)

    # Filter to trading days only
    trading_dates = []
    for d in all_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == d]
        rth_bars = [b for b in day_bars if dt_time(9, 30) <= b.timestamp.time() <= dt_time(16, 0)]
        if len(rth_bars) >= 30:  # 5-min has fewer bars
            trading_dates.append(d)
        if len(trading_dates) >= days:
            break

    trading_dates = sorted(trading_dates)

    print(f'Found {len(trading_dates)} trading days')
    print(f'Date range: {trading_dates[0]} to {trading_dates[-1]}')
    print()
    print('='*80)
    print(f'{symbol} V10 5-MIN BACKTEST - {len(trading_dates)} Days - {contracts} Contracts')
    print('='*80)
    print('Strategy: V10.7 Quad Entry (5-Minute Bars)')
    print(f'  - Min risk: {min_risk_pts} pts')
    print(f'  - Max BOS risk: {max_bos_risk_pts} pts')
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

    print(f'{"Date":<12} {"Trades":>7} {"Wins":>5} {"Losses":>7} {"Win%":>6} {"P/L":>12} {"Cumulative":>12}')
    print('-'*80)

    for target_date in trading_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == target_date]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 30:
            continue

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
            midday_cutoff=True,
            pm_cutoff_nq=(symbol in ['NQ', 'MNQ']),
            max_bos_risk_pts=max_bos_risk_pts,
            symbol=symbol,
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
        dd = peak_pnl - total_pnl
        if dd > max_drawdown:
            max_drawdown = dd

        win_rate = (day_wins / day_trades * 100) if day_trades > 0 else 0
        print(f'{target_date!s:<12} {day_trades:>7} {day_wins:>5} {day_losses:>7} {win_rate:>5.1f}% ${day_pnl:>+10,.0f} ${total_pnl:>+10,.0f}')

        daily_results.append({
            'date': target_date,
            'trades': day_trades,
            'wins': day_wins,
            'losses': day_losses,
            'pnl': day_pnl,
        })

    print('-'*80)
    print()
    print('='*80)
    print('SUMMARY')
    print('='*80)

    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    winning_days = sum(1 for d in daily_results if d['pnl'] > 0)
    losing_days = sum(1 for d in daily_results if d['pnl'] < 0)

    print(f'Trading Days:      {len(trading_dates)}')
    print(f'Total Trades:      {total_trades}')
    print(f'Total Wins:        {total_wins}')
    print(f'Total Losses:      {total_losses}')
    print(f'Win Rate:          {win_rate:.1f}%')
    print()
    print(f'Winning Days:      {winning_days}')
    print(f'Losing Days:       {losing_days}')
    print(f'Day Win Rate:      {winning_days/len(trading_dates)*100:.1f}%')
    print()
    print(f'Total P/L:         ${total_pnl:+,.2f}')
    print(f'Avg Daily P/L:     ${total_pnl/len(trading_dates):+,.2f}')
    print(f'Max Drawdown:      ${max_drawdown:,.2f}')
    print()
    print('Entry Type Breakdown:')
    for et, count in entry_type_counts.items():
        pct = (count / total_trades * 100) if total_trades > 0 else 0
        print(f'  {et}: {count} ({pct:.1f}%)')
    print('='*80)

    return {
        'symbol': symbol,
        'days': len(trading_dates),
        'trades': total_trades,
        'wins': total_wins,
        'losses': total_losses,
        'win_rate': win_rate,
        'pnl': total_pnl,
        'max_dd': max_drawdown,
        'entry_types': entry_type_counts,
    }


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    backtest_5min_multiday(symbol, days)
