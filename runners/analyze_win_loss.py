"""Analyze winning vs losing days for V10 strategy."""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10


def analyze_win_loss(symbol='ES'):
    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00

    print(f'Fetching {symbol} 3m data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=10000)

    # Get trading dates
    all_dates = sorted(set(b.timestamp.date() for b in all_bars), reverse=True)
    trading_dates = []
    for d in all_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == d]
        rth_bars = [b for b in day_bars if dt_time(9, 30) <= b.timestamp.time() <= dt_time(16, 0)]
        if len(rth_bars) >= 50:
            trading_dates.append(d)
        if len(trading_dates) >= 12:
            break

    trading_dates = sorted(trading_dates)

    print()
    print('='*110)
    print(f'WINNING vs LOSING DAY ANALYSIS - {symbol}')
    print('='*110)

    winning_days = []
    losing_days = []

    min_risk_pts = 1.5 if symbol == 'ES' else 6.0

    for target_date in trading_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == target_date]
        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Get RTH only for range calculation
        rth_bars = [b for b in session_bars if dt_time(9, 30) <= b.timestamp.time() <= dt_time(16, 0)]

        # Calculate day's range and trend
        day_high = max(b.high for b in rth_bars)
        day_low = min(b.low for b in rth_bars)
        day_range = day_high - day_low
        day_open = rth_bars[0].open
        day_close = rth_bars[-1].close
        day_direction = 'UP' if day_close > day_open else 'DOWN'
        day_change = day_close - day_open

        # Run strategy
        results = run_session_v10(
            session_bars, all_bars,
            tick_size=tick_size, tick_value=tick_value, contracts=3,
            min_risk_pts=min_risk_pts, enable_creation_entry=True,
            enable_retracement_entry=True, enable_bos_entry=True,
            retracement_morning_only=True, t1_fixed_4r=True,
        )

        day_pnl = sum(r['total_dollars'] for r in results)
        day_trades = len(results)
        day_wins = sum(1 for r in results if r['total_dollars'] > 0)

        # Entry type breakdown
        creation = sum(1 for r in results if r['entry_type'] == 'CREATION')
        overnight = sum(1 for r in results if r['entry_type'] == 'RETRACEMENT')
        intraday = sum(1 for r in results if r['entry_type'] == 'INTRADAY_RETRACE')
        bos = sum(1 for r in results if r['entry_type'] == 'BOS_RETRACE')

        # Avg risk per trade
        avg_risk = sum(r['risk'] for r in results) / len(results) if results else 0

        # How many hit 4R, 8R
        hit_4r = sum(1 for r in results if any(e['type'] == '4R_PARTIAL' for e in r['exits']))
        hit_8r = sum(1 for r in results if any(e['type'] in ['T2_STRUCT', 'RUNNER_STOP'] for e in r['exits']))

        # Stopped out trades
        stopped = sum(1 for r in results if any(e['type'] == 'STOP' for e in r['exits']))

        day_data = {
            'date': target_date,
            'pnl': day_pnl,
            'trades': day_trades,
            'wins': day_wins,
            'range': day_range,
            'direction': day_direction,
            'change': day_change,
            'creation': creation,
            'overnight': overnight,
            'intraday': intraday,
            'bos': bos,
            'avg_risk': avg_risk,
            'hit_4r': hit_4r,
            'hit_8r': hit_8r,
            'stopped': stopped,
        }

        if day_pnl > 0:
            winning_days.append(day_data)
        else:
            losing_days.append(day_data)

    print()
    print('WINNING DAYS:')
    print('-'*110)
    header = f"{'Date':<12} {'P/L':>10} {'Range':>8} {'Dir':>5} {'Chg':>8} {'Trades':>7} {'Wins':>5} {'Stop':>5} {'4R':>4} {'8R+':>4} {'Create':>7} {'O/N':>5} {'BOS':>5}"
    print(header)
    print('-'*110)
    for d in sorted(winning_days, key=lambda x: x['pnl'], reverse=True):
        print(f"{d['date']} ${d['pnl']:>+9,.0f} {d['range']:>7.2f} {d['direction']:>5} {d['change']:>+7.2f} {d['trades']:>7} {d['wins']:>5} {d['stopped']:>5} {d['hit_4r']:>4} {d['hit_8r']:>4} {d['creation']:>7} {d['overnight']:>5} {d['bos']:>5}")

    print()
    print('LOSING DAYS:')
    print('-'*110)
    print(header)
    print('-'*110)
    for d in sorted(losing_days, key=lambda x: x['pnl']):
        print(f"{d['date']} ${d['pnl']:>+9,.0f} {d['range']:>7.2f} {d['direction']:>5} {d['change']:>+7.02f} {d['trades']:>7} {d['wins']:>5} {d['stopped']:>5} {d['hit_4r']:>4} {d['hit_8r']:>4} {d['creation']:>7} {d['overnight']:>5} {d['bos']:>5}")

    # Calculate averages
    avg_win_range = sum(d['range'] for d in winning_days) / len(winning_days) if winning_days else 0
    avg_win_trades = sum(d['trades'] for d in winning_days) / len(winning_days) if winning_days else 0
    avg_win_4r = sum(d['hit_4r'] for d in winning_days) / len(winning_days) if winning_days else 0
    avg_win_8r = sum(d['hit_8r'] for d in winning_days) / len(winning_days) if winning_days else 0
    avg_win_stopped = sum(d['stopped'] for d in winning_days) / len(winning_days) if winning_days else 0

    avg_loss_range = sum(d['range'] for d in losing_days) / len(losing_days) if losing_days else 0
    avg_loss_trades = sum(d['trades'] for d in losing_days) / len(losing_days) if losing_days else 0
    avg_loss_4r = sum(d['hit_4r'] for d in losing_days) / len(losing_days) if losing_days else 0
    avg_loss_8r = sum(d['hit_8r'] for d in losing_days) / len(losing_days) if losing_days else 0
    avg_loss_stopped = sum(d['stopped'] for d in losing_days) / len(losing_days) if losing_days else 0

    print()
    print('='*110)
    print('COMPARISON:')
    print('='*110)
    print(f"{'Metric':<30} {'Winning Days':>15} {'Losing Days':>15} {'Difference':>15}")
    print('-'*75)
    print(f"{'Days Count':<30} {len(winning_days):>15} {len(losing_days):>15}")
    print(f"{'Avg Day Range (pts)':<30} {avg_win_range:>15.2f} {avg_loss_range:>15.2f} {avg_win_range - avg_loss_range:>+15.2f}")
    print(f"{'Avg Trades/Day':<30} {avg_win_trades:>15.1f} {avg_loss_trades:>15.1f} {avg_win_trades - avg_loss_trades:>+15.1f}")
    print(f"{'Avg Stopped/Day':<30} {avg_win_stopped:>15.1f} {avg_loss_stopped:>15.1f} {avg_win_stopped - avg_loss_stopped:>+15.1f}")
    print(f"{'Avg 4R Hits/Day':<30} {avg_win_4r:>15.1f} {avg_loss_4r:>15.1f} {avg_win_4r - avg_loss_4r:>+15.1f}")
    print(f"{'Avg 8R+ Hits/Day':<30} {avg_win_8r:>15.1f} {avg_loss_8r:>15.1f} {avg_win_8r - avg_loss_8r:>+15.1f}")

    # Direction analysis
    win_up = sum(1 for d in winning_days if d['direction'] == 'UP')
    win_down = sum(1 for d in winning_days if d['direction'] == 'DOWN')
    loss_up = sum(1 for d in losing_days if d['direction'] == 'UP')
    loss_down = sum(1 for d in losing_days if d['direction'] == 'DOWN')

    print()
    print('='*110)
    print('MARKET DIRECTION:')
    print('='*110)
    print(f"{'Day Type':<20} {'UP Days':>15} {'DOWN Days':>15}")
    print('-'*50)
    print(f"{'Winning Days':<20} {win_up:>15} {win_down:>15}")
    print(f"{'Losing Days':<20} {loss_up:>15} {loss_down:>15}")

    # Entry type analysis
    print()
    print('='*110)
    print('ENTRY TYPE SUCCESS RATE:')
    print('='*110)

    win_creation = sum(d['creation'] for d in winning_days)
    loss_creation = sum(d['creation'] for d in losing_days)
    win_overnight = sum(d['overnight'] for d in winning_days)
    loss_overnight = sum(d['overnight'] for d in losing_days)
    win_bos = sum(d['bos'] for d in winning_days)
    loss_bos = sum(d['bos'] for d in losing_days)

    print(f"{'Entry Type':<20} {'On Win Days':>15} {'On Loss Days':>15} {'Win Day %':>15}")
    print('-'*65)
    total_creation = win_creation + loss_creation
    total_overnight = win_overnight + loss_overnight
    total_bos = win_bos + loss_bos
    print(f"{'Creation':<20} {win_creation:>15} {loss_creation:>15} {win_creation/total_creation*100 if total_creation else 0:>14.1f}%")
    print(f"{'Overnight':<20} {win_overnight:>15} {loss_overnight:>15} {win_overnight/total_overnight*100 if total_overnight else 0:>14.1f}%")
    print(f"{'BOS':<20} {win_bos:>15} {loss_bos:>15} {win_bos/total_bos*100 if total_bos else 0:>14.1f}%")

    print()
    print('='*110)
    print('KEY INSIGHT:')
    print('='*110)
    print(f"Winning days have {avg_win_range - avg_loss_range:+.2f} pts MORE range than losing days")
    print(f"Winning days hit 4R {avg_win_4r - avg_loss_4r:+.1f} MORE times per day")
    print(f"Winning days hit 8R+ {avg_win_8r - avg_loss_8r:+.1f} MORE times per day")
    print(f"Losing days get stopped {avg_loss_stopped - avg_win_stopped:+.1f} MORE times per day")


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    analyze_win_loss(symbol)
