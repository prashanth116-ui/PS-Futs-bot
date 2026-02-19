"""
Debug why V6-Aggressive didn't take trades in a specific window.
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


def debug_v6_window(symbol='ES', start_time='08:50', end_time='09:40'):
    """Debug V6-Aggressive entries in a window."""

    tick_size = 0.25
    displacement_threshold = 1.0  # V6-Aggressive

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

    # Parse time window
    start_h, start_m = map(int, start_time.split(':'))
    end_h, end_m = map(int, end_time.split(':'))
    window_start = dt_time(start_h, start_m)
    window_end = dt_time(end_h, end_m)

    # Calculate average body size
    body_sizes = [abs(b.close - b.open) for b in session_bars[:50]]
    avg_body_size = sum(body_sizes) / len(body_sizes) if body_sizes else tick_size * 4
    disp_threshold_value = avg_body_size * displacement_threshold

    print('\nV6-Aggressive Settings:')
    print(f'  Displacement threshold: {displacement_threshold}x')
    print(f'  Avg body size: {avg_body_size:.2f}')
    print(f'  Min displacement needed: {disp_threshold_value:.2f}')
    print()

    # Detect all FVGs
    fvg_config = {
        'min_fvg_ticks': 5,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)

    print('=' * 90)
    print(f'BULLISH FVGs CREATED IN WINDOW ({start_time} - {end_time}):')
    print('=' * 90)

    bullish_fvgs_in_window = []
    for fvg in all_fvgs:
        if fvg.direction != 'BULLISH':
            continue
        fvg_time = session_bars[fvg.created_bar_index].timestamp.time()
        if window_start <= fvg_time <= window_end:
            bullish_fvgs_in_window.append(fvg)

    if not bullish_fvgs_in_window:
        print('No BULLISH FVGs created in this window')
    else:
        for fvg in bullish_fvgs_in_window:
            fvg_time = session_bars[fvg.created_bar_index].timestamp
            creating_bar = session_bars[fvg.created_bar_index]
            body = abs(creating_bar.close - creating_bar.open)
            is_disp = body > disp_threshold_value
            size_ticks = (fvg.high - fvg.low) / tick_size

            print(f'\nFVG @ {fvg_time.strftime("%H:%M")}')
            print(f'  Range: {fvg.low:.2f} - {fvg.high:.2f} ({size_ticks:.0f} ticks)')
            print(f'  Creating bar: O={creating_bar.open:.2f} H={creating_bar.high:.2f} L={creating_bar.low:.2f} C={creating_bar.close:.2f}')
            print(f'  Body size: {body:.2f} (need > {disp_threshold_value:.2f})')
            print(f'  Displacement: {"PASS" if is_disp else "FAIL"}')

            if is_disp:
                # Check filters at FVG creation time
                bars_to_entry = session_bars[:fvg.created_bar_index + 1]

                ema_fast = calculate_ema(bars_to_entry, 20)
                ema_slow = calculate_ema(bars_to_entry, 50)
                adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)

                print('\n  FILTER CHECK (V6-Aggressive enters at creation):')

                ema_ok = True
                if ema_fast and ema_slow:
                    ema_ok = ema_fast > ema_slow  # For LONG
                    print(f'    EMA 20/50: {ema_fast:.2f} / {ema_slow:.2f} -> {"PASS" if ema_ok else "FAIL (need EMA20 > EMA50)"}')
                else:
                    print('    EMA: Not enough data (PASS)')

                adx_ok = True
                di_ok = True
                if adx:
                    adx_ok = adx >= 17
                    di_ok = plus_di > minus_di  # For LONG
                    print(f'    ADX: {adx:.1f} -> {"PASS" if adx_ok else "FAIL (need >= 17)"}')
                    print(f'    DI: +{plus_di:.1f} / -{minus_di:.1f} -> {"PASS" if di_ok else "FAIL (need +DI > -DI)"}')
                else:
                    print('    ADX/DI: Not enough data (PASS)')

                if ema_ok and adx_ok and di_ok:
                    print('\n  >>> V6-AGGRESSIVE WOULD ENTER HERE!')
                else:
                    failed = []
                    if not ema_ok: failed.append("EMA")
                    if not adx_ok: failed.append("ADX")
                    if not di_ok: failed.append("DI")
                    print(f'\n  >>> FILTERED OUT by: {", ".join(failed)}')
            else:
                print('  >>> SKIPPED (displacement too small)')

    # Also check why V6-Aggressive might have already traded
    print()
    print('=' * 90)
    print('V6-AGGRESSIVE ALREADY IN TRADE?')
    print('=' * 90)

    # Find the first valid V6-Aggressive entry
    first_entry = None
    for fvg in all_fvgs:
        if fvg.direction != 'BULLISH':
            continue

        creating_bar = session_bars[fvg.created_bar_index]
        body = abs(creating_bar.close - creating_bar.open)
        if body <= disp_threshold_value:
            continue

        bars_to_entry = session_bars[:fvg.created_bar_index + 1]
        ema_fast = calculate_ema(bars_to_entry, 20)
        ema_slow = calculate_ema(bars_to_entry, 50)
        adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)

        ema_ok = ema_fast is None or ema_slow is None or ema_fast > ema_slow
        adx_ok = adx is None or adx >= 17
        di_ok = adx is None or plus_di > minus_di

        if ema_ok and adx_ok and di_ok:
            first_entry = fvg
            break

    if first_entry:
        entry_time = session_bars[first_entry.created_bar_index].timestamp
        print(f'\nFirst V6-Aggressive LONG entry: {entry_time.strftime("%H:%M")}')
        print(f'FVG: {first_entry.low:.2f} - {first_entry.high:.2f}')

        if entry_time.time() < window_start:
            print(f'\n>>> V6-Aggressive entered BEFORE the {start_time}-{end_time} window!')
            print('>>> Strategy only takes 1 trade per direction (no re-entry unless stopped)')
            print('>>> This is why no new entry was taken in the window.')
    else:
        print('\nNo valid V6-Aggressive LONG entry found')


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    start = sys.argv[2] if len(sys.argv) > 2 else '08:50'
    end = sys.argv[3] if len(sys.argv) > 3 else '09:40'
    debug_v6_window(symbol, start, end)
