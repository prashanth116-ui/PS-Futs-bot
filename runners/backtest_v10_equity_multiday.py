"""
V10.4 Equity Multi-Day Backtest - SPY/QQQ

Runs the V10 strategy across multiple days for equity instruments.

V10.4 includes:
- ATR-based stop buffer (ATR × 0.5) instead of fixed $0.02
- Improves P/L by +$54k over 30 days
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time, timedelta
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_equity import run_session_v10_equity, EQUITY_CONFIG


def run_multiday_backtest(symbol='SPY', days=30, risk_per_trade=500):
    """Run V10 equity backtest across multiple days."""

    print(f"Fetching {symbol} data...")
    bars = fetch_futures_bars(symbol, interval='3m', n_bars=5000)

    if not bars:
        print(f"No data available for {symbol}")
        return

    # Get unique trading days
    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:] if len(all_dates) >= days else all_dates

    print(f"Backtesting {len(recent_dates)} days: {recent_dates[0]} to {recent_dates[-1]}")
    print(f"Risk per trade: ${risk_per_trade}")
    print()

    # Track results
    all_results = []
    daily_summaries = []

    for target_date in recent_dates:
        day_bars = [b for b in bars if b.timestamp.date() == target_date]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        results = run_session_v10_equity(
            session_bars,
            bars,
            symbol=symbol,
            risk_per_trade=risk_per_trade,
            max_open_trades=2,
            t1_fixed_4r=True,
            overnight_retrace_min_adx=22,
            midday_cutoff=True,       # V10.2: No entries 12:00-14:00
            pm_cutoff_qqq=True,       # V10.2: No QQQ entries after 14:00
            disable_intraday_spy=True,  # V10.4: Disable SPY INTRADAY (24% win rate)
        )

        day_pnl = sum(r['total_dollars'] for r in results)
        day_wins = len([r for r in results if r['total_dollars'] > 0])
        day_losses = len([r for r in results if r['total_dollars'] <= 0])

        daily_summaries.append({
            'date': target_date,
            'trades': len(results),
            'wins': day_wins,
            'losses': day_losses,
            'pnl': day_pnl,
        })

        for r in results:
            r['date'] = target_date
            all_results.append(r)

    # Print daily breakdown
    print("=" * 80)
    print(f"DAILY BREAKDOWN - {symbol}")
    print("=" * 80)
    print(f"{'Date':<12} {'Trades':>7} {'Wins':>6} {'Losses':>7} {'P/L':>14}")
    print("-" * 50)

    for day in daily_summaries:
        print(f"{day['date']} {day['trades']:>7} {day['wins']:>6} {day['losses']:>7} ${day['pnl']:>12,.2f}")

    # Summary statistics
    total_trades = len(all_results)
    total_wins = len([r for r in all_results if r['total_dollars'] > 0])
    total_losses = len([r for r in all_results if r['total_dollars'] <= 0])
    total_pnl = sum(r['total_dollars'] for r in all_results)

    # Entry type breakdown
    entry_types = {}
    for r in all_results:
        et = r['entry_type']
        if et not in entry_types:
            entry_types[et] = {'count': 0, 'wins': 0, 'pnl': 0}
        entry_types[et]['count'] += 1
        entry_types[et]['pnl'] += r['total_dollars']
        if r['total_dollars'] > 0:
            entry_types[et]['wins'] += 1

    print()
    print("=" * 80)
    print(f"ENTRY TYPE BREAKDOWN - {symbol}")
    print("=" * 80)
    print(f"{'Type':<15} {'Count':>7} {'Wins':>6} {'Win%':>7} {'P/L':>14}")
    print("-" * 55)

    for et, data in sorted(entry_types.items()):
        win_rate = (data['wins'] / data['count'] * 100) if data['count'] > 0 else 0
        print(f"{et:<15} {data['count']:>7} {data['wins']:>6} {win_rate:>6.1f}% ${data['pnl']:>12,.2f}")

    # Final summary
    print()
    print("=" * 80)
    print(f"SUMMARY - {symbol} - {len(recent_dates)} Days")
    print("=" * 80)
    print(f"Total Trades:  {total_trades}")
    print(f"Wins:          {total_wins}")
    print(f"Losses:        {total_losses}")
    if total_trades > 0:
        print(f"Win Rate:      {total_wins/total_trades*100:.1f}%")

        # Profit factor
        gross_profit = sum(r['total_dollars'] for r in all_results if r['total_dollars'] > 0)
        gross_loss = abs(sum(r['total_dollars'] for r in all_results if r['total_dollars'] < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        print(f"Profit Factor: {pf:.2f}")

        # Average win/loss
        avg_win = gross_profit / total_wins if total_wins > 0 else 0
        avg_loss = gross_loss / total_losses if total_losses > 0 else 0
        print(f"Avg Win:       ${avg_win:,.2f}")
        print(f"Avg Loss:      ${avg_loss:,.2f}")

    print(f"Total P/L:     ${total_pnl:+,.2f}")

    # Winning vs losing days
    winning_days = len([d for d in daily_summaries if d['pnl'] > 0])
    losing_days = len([d for d in daily_summaries if d['pnl'] < 0])
    flat_days = len([d for d in daily_summaries if d['pnl'] == 0])

    print()
    print(f"Winning Days:  {winning_days}")
    print(f"Losing Days:   {losing_days}")
    print(f"Flat Days:     {flat_days}")

    return all_results, daily_summaries


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'SPY'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    risk = int(sys.argv[3]) if len(sys.argv) > 3 else 500

    run_multiday_backtest(symbol, days, risk)
