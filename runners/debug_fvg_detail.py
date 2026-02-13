"""
Detailed FVG analysis for a specific time window.
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_fvg_mitigation


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


def is_displacement_candle(bar, avg_body_size, threshold=1.2):
    body_size = abs(bar.close - bar.open)
    return body_size > avg_body_size * threshold


def debug_fvg_detail(symbol='ES', start_time='09:00', end_time='09:38'):
    """Detailed FVG analysis for a time window."""

    tick_size = 0.25

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

    print(f'\nAvg body size (first 50 bars): {avg_body_size:.2f}')
    print(f'Displacement threshold: {avg_body_size * 1.2:.2f}')
    print()

    # Detect all FVGs
    fvg_config = {
        'min_fvg_ticks': 5,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)

    print('=' * 80)
    print(f'PRICE ACTION: {start_time} - {end_time}')
    print('=' * 80)

    # Show bars in window
    print(f'\n{"Time":<8} {"Open":<10} {"High":<10} {"Low":<10} {"Close":<10} {"Body":<8}')
    print('-' * 60)
    for i, bar in enumerate(session_bars):
        bar_time = bar.timestamp.time()
        if window_start <= bar_time <= window_end:
            body = abs(bar.close - bar.open)
            disp = "*" if body > avg_body_size * 1.2 else ""
            print(f'{bar_time.strftime("%H:%M"):<8} {bar.open:<10.2f} {bar.high:<10.2f} {bar.low:<10.2f} {bar.close:<10.2f} {body:<7.2f} {disp}')

    print('\n* = Displacement candle')

    print()
    print('=' * 80)
    print(f'ALL BULLISH FVGs (could enter LONG):')
    print('=' * 80)

    bullish_fvgs = [f for f in all_fvgs if f.direction == 'BULLISH']
    bullish_fvgs.sort(key=lambda f: f.created_bar_index)

    for fvg in bullish_fvgs:
        fvg_time = session_bars[fvg.created_bar_index].timestamp
        if fvg_time.time() > window_end:
            continue

        creating_bar = session_bars[fvg.created_bar_index]
        body = abs(creating_bar.close - creating_bar.open)
        is_disp = body > avg_body_size * 1.2
        size_ticks = (fvg.high - fvg.low) / tick_size

        print(f'\nBULLISH FVG @ {fvg_time.strftime("%H:%M")}')
        print(f'  Range: {fvg.low:.2f} - {fvg.high:.2f} ({size_ticks:.0f} ticks)')
        print(f'  Edge (entry): {fvg.high:.2f}')
        print(f'  Midpoint: {fvg.midpoint:.2f}')
        print(f'  Displacement: {"YES" if is_disp else "NO"} (body={body:.2f}, need={avg_body_size*1.2:.2f})')

        if not is_disp:
            print(f'  >>> SKIPPED (no displacement)')
            continue

        # Check if touched in window
        edge_price = fvg.high
        touched = False
        touch_time = None
        touch_bar_idx = None

        for i in range(fvg.created_bar_index + 1, len(session_bars)):
            bar = session_bars[i]
            bar_time = bar.timestamp.time()

            if bar.low <= edge_price:
                touched = True
                touch_time = bar.timestamp
                touch_bar_idx = i
                break

        if touched:
            print(f'  Touched @ {touch_time.strftime("%H:%M")} (bar low {session_bars[touch_bar_idx].low:.2f} <= edge {edge_price:.2f})')

            # Check filters at touch time
            bars_to_entry = session_bars[:touch_bar_idx+1]
            ema_fast = calculate_ema(bars_to_entry, 20)
            ema_slow = calculate_ema(bars_to_entry, 50)
            adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)

            print(f'  Filters at touch:')
            ema_ok = True
            adx_ok = True
            di_ok = True

            if ema_fast and ema_slow:
                ema_ok = ema_fast > ema_slow
                print(f'    EMA 20/50: {ema_fast:.2f} / {ema_slow:.2f} -> {"PASS" if ema_ok else "FAIL (need EMA20 > EMA50 for LONG)"}')
            else:
                print(f'    EMA 20/50: Not enough data')

            if adx:
                adx_ok = adx >= 17
                di_ok = plus_di > minus_di
                print(f'    ADX: {adx:.1f} -> {"PASS" if adx_ok else "FAIL (need >= 17)"}')
                print(f'    DI: +{plus_di:.1f} / -{minus_di:.1f} -> {"PASS" if di_ok else "FAIL (need +DI > -DI for LONG)"}')
            else:
                print(f'    ADX/DI: Not enough data')

            if ema_ok and adx_ok and di_ok:
                print(f'  >>> ENTRY SHOULD BE TAKEN!')
            else:
                failed = []
                if not ema_ok: failed.append("EMA")
                if not adx_ok: failed.append("ADX")
                if not di_ok: failed.append("DI")
                print(f'  >>> FILTERED by: {", ".join(failed)}')

            # Check if in window
            if window_start <= touch_time.time() <= window_end:
                print(f'  Touch is IN window ({start_time} - {end_time})')
            else:
                print(f'  Touch is OUTSIDE window (touch @ {touch_time.strftime("%H:%M")})')
        else:
            print(f'  NOT touched yet (price never reached {edge_price:.2f})')


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    start = sys.argv[2] if len(sys.argv) > 2 else '09:00'
    end = sys.argv[3] if len(sys.argv) > 3 else '09:38'
    debug_fvg_detail(symbol, start, end)
