"""
Debug V6-Aggressive full day - why no second entry after first trade closed?
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs


def calculate_ema(bars, period):
    if len(bars) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(b.close for b in bars[:period]) / period
    for bar in bars[period:]:
        ema = (bar.close - ema) * multiplier + ema
    return ema


def calculate_adx(bars, period=14):
    if len(bars) < period * 2:
        return None, None, None

    tr_list = []
    plus_dm_list = []
    minus_dm_list = []

    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        close_prev = bars[i-1].close
        high_prev = bars[i-1].high
        low_prev = bars[i-1].low

        tr = max(high - low, abs(high - close_prev), abs(low - close_prev))
        tr_list.append(tr)

        up_move = high - high_prev
        down_move = low_prev - low

        plus_dm = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0

        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)

    if len(tr_list) < period:
        return None, None, None

    def wilder_smooth(data, period):
        smoothed = [sum(data[:period])]
        for i in range(period, len(data)):
            smoothed.append(smoothed[-1] - (smoothed[-1] / period) + data[i])
        return smoothed

    atr = wilder_smooth(tr_list, period)
    plus_dm_smooth = wilder_smooth(plus_dm_list, period)
    minus_dm_smooth = wilder_smooth(minus_dm_list, period)

    dx_list = []
    plus_di = 0
    minus_di = 0
    for i in range(len(atr)):
        if atr[i] == 0:
            continue
        plus_di = 100 * plus_dm_smooth[i] / atr[i]
        minus_di = 100 * minus_dm_smooth[i] / atr[i]

        di_sum = plus_di + minus_di
        if di_sum == 0:
            continue
        dx = 100 * abs(plus_di - minus_di) / di_sum
        dx_list.append(dx)

    if len(dx_list) < period:
        return None, None, None

    adx = sum(dx_list[-period:]) / period
    return adx, plus_di, minus_di


def is_displacement_candle(bar, avg_body_size, threshold):
    body_size = abs(bar.close - bar.open)
    return body_size > avg_body_size * threshold


def debug_v6_fullday(symbol='ES'):
    """Debug V6-Aggressive full day entries."""

    tick_size = 0.25
    displacement_threshold = 1.0

    print(f'Fetching {symbol} 3m data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=1000)

    if not all_bars:
        print('No data available')
        return

    today = all_bars[-1].timestamp.date()
    today_bars = [b for b in all_bars if b.timestamp.date() == today]

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

    print(f'Date: {today}')
    print(f'Session bars: {len(session_bars)}')

    body_sizes = [abs(b.close - b.open) for b in session_bars[:50]]
    avg_body_size = sum(body_sizes) / len(body_sizes) if body_sizes else tick_size * 4
    disp_threshold_value = avg_body_size * displacement_threshold

    print('\nV6-Aggressive Settings:')
    print(f'  Displacement: {displacement_threshold}x = {disp_threshold_value:.2f}')
    print()

    fvg_config = {
        'min_fvg_ticks': 5,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)

    print('=' * 100)
    print('ALL BULLISH FVGs WITH DISPLACEMENT (potential V6-Aggressive LONG entries):')
    print('=' * 100)

    valid_entries = []

    for fvg in all_fvgs:
        if fvg.direction != 'BULLISH':
            continue

        creating_bar = session_bars[fvg.created_bar_index]
        body = abs(creating_bar.close - creating_bar.open)

        if body <= disp_threshold_value:
            continue  # Skip no displacement

        fvg_time = session_bars[fvg.created_bar_index].timestamp
        bars_to_entry = session_bars[:fvg.created_bar_index + 1]

        ema_fast = calculate_ema(bars_to_entry, 20)
        ema_slow = calculate_ema(bars_to_entry, 50)
        adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)

        ema_ok = ema_fast is None or ema_slow is None or ema_fast > ema_slow
        adx_ok = adx is None or adx >= 17
        di_ok = adx is None or plus_di > minus_di

        all_pass = ema_ok and adx_ok and di_ok

        print(f'\n{fvg_time.strftime("%H:%M")} - FVG {fvg.low:.2f}-{fvg.high:.2f} (body={body:.2f})')
        ema_fast_str = f'{ema_fast:.2f}' if ema_fast else 'N/A'
        ema_slow_str = f'{ema_slow:.2f}' if ema_slow else 'N/A'
        adx_str = f'{adx:.1f}' if adx else 'N/A'
        plus_di_str = f'{plus_di:.1f}' if plus_di else 'N/A'
        minus_di_str = f'{minus_di:.1f}' if minus_di else 'N/A'
        print(f'  EMA 20/50: {ema_fast_str} / {ema_slow_str} -> {"PASS" if ema_ok else "FAIL"}')
        print(f'  ADX: {adx_str} -> {"PASS" if adx_ok else "FAIL"}')
        print(f'  DI: +{plus_di_str} / -{minus_di_str} -> {"PASS" if di_ok else "FAIL"}')
        print(f'  >>> {"VALID ENTRY" if all_pass else "FILTERED"}')

        if all_pass:
            valid_entries.append({
                'time': fvg_time,
                'fvg': fvg,
                'midpoint': fvg.midpoint
            })

    print()
    print('=' * 100)
    print(f'VALID V6-AGGRESSIVE LONG ENTRIES TODAY: {len(valid_entries)}')
    print('=' * 100)

    for i, entry in enumerate(valid_entries, 1):
        print(f'{i}. {entry["time"].strftime("%H:%M")} - Entry @ {entry["midpoint"]:.2f}')

    print()
    print('=' * 100)
    print('ANALYSIS:')
    print('=' * 100)
    print('''
The test_aggressive.py script shows V6-Aggressive took 2 trades today:
  1. LONG @ 04:21 (6915.12) -> WIN +$1,062.50
  2. LONG [RE-ENTRY] @ 09:33 (6950.12) -> WIN +$7,381.25

But the plot only showed the first trade.

This is because plot_v6_aggressive.py only plots the FIRST valid entry.
The backtest script (test_aggressive.py) correctly handles re-entries.

Let me check if the 04:21 trade was stopped (allowing re-entry) or not...
''')

    # Check first trade outcome
    if valid_entries:
        first = valid_entries[0]
        entry_idx = first['fvg'].created_bar_index
        entry_price = first['midpoint']
        stop_price = first['fvg'].low - (2 * tick_size)

        print('First trade:')
        print(f'  Entry: {entry_price:.2f} @ {first["time"].strftime("%H:%M")}')
        print(f'  Stop: {stop_price:.2f}')

        # Check if stopped
        was_stopped = False
        for i in range(entry_idx + 1, len(session_bars)):
            bar = session_bars[i]
            if bar.low <= stop_price:
                was_stopped = True
                print(f'  STOPPED at {bar.timestamp.strftime("%H:%M")}')
                break

        if not was_stopped:
            print('  NOT STOPPED - trade was a winner')

        print('''
CONCLUSION:
The backtest (test_aggressive.py) uses "fvg_num" parameter:
  - fvg_num=1: First valid FVG
  - fvg_num=2: Second valid FVG (re-entry)

If first trade wins (not stopped), it takes fvg_num=2 as re-entry.
This is why V6-Aggressive shows 2 trades in the backtest:
  - Trade 1: 04:21 (fvg_num=1)
  - Trade 2: 09:33 (fvg_num=2) <- This is the "re-entry"

The plot script only shows fvg_num=1. Let me check test_aggressive results...
''')


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    debug_v6_fullday(symbol)
