"""
Multi-day backtest with corrected FVG mitigation logic.

Shows realistic results including all trades (wins AND losses).
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time, timedelta
from runners.tradingview_loader import fetch_futures_bars
from runners.run_today import run_trade


def backtest_multiday(symbol='ES', days=14, contracts=3):
    """Run backtest over multiple days."""

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25

    print(f'Fetching {symbol} 3m data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=days * 250)

    if not all_bars:
        print('No data available')
        return

    # Group by date
    dates = sorted(set(b.timestamp.date() for b in all_bars))

    print(f"=" * 80)
    print(f"{symbol} MULTI-DAY BACKTEST - {len(dates)} Days - {contracts} Contracts")
    print(f"=" * 80)
    print()

    total_wins = 0
    total_losses = 0
    total_pnl = 0
    all_trades = []

    print(f"{'Date':<12} | {'Dir':<5} | {'Type':<8} | {'Entry':<10} | {'Result':<6} | {'P/L':>12}")
    print("-" * 70)

    for day in dates[-days:]:
        day_bars = [b for b in all_bars if b.timestamp.date() == day]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        for direction in ['LONG', 'SHORT']:
            # Try first FVG
            result = run_trade(session_bars, direction, 1, tick_size=tick_size,
                             tick_value=tick_value, contracts=contracts)

            if result:
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
                all_trades.append(result)

                print(f"{day} | {direction:<5} | {'1st':<8} | {result['entry_price']:<10.2f} | {result_str:<6} | ${result['total_dollars']:>+10,.2f}")

                # Try re-entry if stopped out
                if result['was_stopped']:
                    result2 = run_trade(session_bars, direction, 2, tick_size=tick_size,
                                       tick_value=tick_value, contracts=contracts)

                    if result2:
                        is_win2 = result2['total_pnl'] > 0.01
                        is_loss2 = result2['total_pnl'] < -0.01

                        if is_win2:
                            total_wins += 1
                            result_str2 = 'WIN'
                        elif is_loss2:
                            total_losses += 1
                            result_str2 = 'LOSS'
                        else:
                            result_str2 = 'BE'

                        total_pnl += result2['total_dollars']
                        all_trades.append(result2)

                        print(f"{day} | {direction:<5} | {'Re-entry':<8} | {result2['entry_price']:<10.2f} | {result_str2:<6} | ${result2['total_dollars']:>+10,.2f}")

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

    backtest_multiday(symbol=symbol, days=days)
