"""
Multi-day backtest with V9 strategy.

V9 Features:
- Min risk filter (ES: 1.5 pts, NQ: 8.0 pts)
- Tiered structure trail exits
- Independent 2nd entry
- Position limit (max 2 open)
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time, timedelta
from runners.tradingview_loader import fetch_futures_bars
from runners.run_today import run_session_with_position_limit


def backtest_multiday(symbol='ES', days=30, contracts=3, interval='3m'):
    """Run V9 backtest over multiple days."""

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25
    min_risk_pts = 1.5 if symbol == 'ES' else 8.0 if symbol == 'NQ' else 1.5

    # Adjust bars per day based on interval
    bars_per_day = {'1m': 780, '3m': 260, '5m': 156, '15m': 52, '30m': 26, '1h': 13, '4h': 4}
    n_bars = days * bars_per_day.get(interval, 250)

    print(f'Fetching {symbol} {interval} data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval=interval, n_bars=n_bars)

    if not all_bars:
        print('No data available')
        return

    # Group by date
    dates = sorted(set(b.timestamp.date() for b in all_bars))

    print(f"=" * 80)
    print(f"{symbol} MULTI-DAY BACKTEST (V9) - {len(dates)} Days - {contracts} Contracts")
    print(f"=" * 80)
    print(f"  Min Risk: {min_risk_pts} pts | Tiered Trail | Independent Entries")
    print()

    total_wins = 0
    total_losses = 0
    total_pnl = 0
    all_trades = []

    print(f"{'Date':<12} | {'Dir':<5} | {'Type':<10} | {'Entry':<10} | {'Result':<6} | {'P/L':>12}")
    print("-" * 75)

    for day in dates[-days:]:
        day_bars = [b for b in all_bars if b.timestamp.date() == day]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Run V9 strategy for this day
        results = run_session_with_position_limit(
            session_bars,
            tick_size=tick_size,
            tick_value=tick_value,
            contracts=contracts,
            min_risk_pts=min_risk_pts,
            use_opposing_fvg_exit=False,
        )

        for result in results:
            is_win = result['total_pnl'] > 0.01
            is_loss = result['total_pnl'] < -0.01

            if is_win:
                total_wins += 1
                result_str = 'WIN'
            elif is_loss:
                total_losses += 1
                result_str = 'LOSS'
            else:
                result_str = 'BE'

            total_pnl += result['total_dollars']
            result['date'] = day
            all_trades.append(result)

            trade_type = '2nd' if result.get('is_reentry') else '1st'
            print(f"{day} | {result['direction']:<5} | {trade_type:<10} | {result['entry_price']:<10.2f} | {result_str:<6} | ${result['total_dollars']:>+10,.2f}")

    print("-" * 70)
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    total_trades = total_wins + total_losses
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    avg_win = sum(t['total_dollars'] for t in all_trades if t['total_pnl'] > 0) / total_wins if total_wins > 0 else 0
    avg_loss = sum(t['total_dollars'] for t in all_trades if t['total_pnl'] < 0) / total_losses if total_losses > 0 else 0

    print(f"  Total Trades:  {total_trades}")
    print(f"  Wins:          {total_wins}")
    print(f"  Losses:        {total_losses}")
    print(f"  Win Rate:      {win_rate:.1f}%")
    print(f"  Avg Win:       ${avg_win:+,.2f}")
    print(f"  Avg Loss:      ${avg_loss:+,.2f}")
    print(f"  Profit Factor: {abs(avg_win * total_wins / (avg_loss * total_losses)):.2f}" if total_losses > 0 and avg_loss != 0 else "  Profit Factor: N/A")
    print()
    print(f"  TOTAL P/L:     ${total_pnl:+,.2f}")
    print("=" * 80)

    return all_trades


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 14
    interval = sys.argv[3] if len(sys.argv) > 3 else '3m'

    backtest_multiday(symbol=symbol, days=days, interval=interval)
