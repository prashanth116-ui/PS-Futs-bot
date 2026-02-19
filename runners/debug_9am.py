"""
Debug what happened at 9:00 AM specifically.
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
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


def debug_9am(symbol='ES'):
    """Debug what happened at 9:00 AM."""

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

    # Find the 9:00 bar
    bar_9am_idx = None
    for i, bar in enumerate(session_bars):
        if bar.timestamp.time() == dt_time(9, 0):
            bar_9am_idx = i
            break

    if bar_9am_idx is None:
        print('Could not find 9:00 AM bar')
        return

    bar_9am = session_bars[bar_9am_idx]
    print('\n09:00 AM Bar:')
    print(f'  Open: {bar_9am.open:.2f}')
    print(f'  High: {bar_9am.high:.2f}')
    print(f'  Low: {bar_9am.low:.2f}')
    print(f'  Close: {bar_9am.close:.2f}')

    # Calculate average body size
    body_sizes = [abs(b.close - b.open) for b in session_bars[:50]]
    avg_body_size = sum(body_sizes) / len(body_sizes) if body_sizes else tick_size * 4
    disp_threshold = avg_body_size * 1.2

    print(f'\nDisplacement threshold: {disp_threshold:.2f}')

    # Detect all FVGs
    fvg_config = {
        'min_fvg_ticks': 5,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)

    print(f'\n{"="*80}')
    print('ALL BULLISH FVGs THAT EXISTED BEFORE 09:00:')
    print(f'{"="*80}')

    # Find all bullish FVGs created before 9am
    bullish_fvgs_before_9am = []
    for fvg in all_fvgs:
        if fvg.direction != 'BULLISH':
            continue
        fvg_time = session_bars[fvg.created_bar_index].timestamp.time()
        if fvg_time < dt_time(9, 0):
            bullish_fvgs_before_9am.append(fvg)

    bullish_fvgs_before_9am.sort(key=lambda f: f.created_bar_index)

    for fvg in bullish_fvgs_before_9am:
        fvg_time = session_bars[fvg.created_bar_index].timestamp.strftime("%H:%M")
        creating_bar = session_bars[fvg.created_bar_index]
        body = abs(creating_bar.close - creating_bar.open)
        is_disp = body > disp_threshold
        size_ticks = (fvg.high - fvg.low) / tick_size

        # Check if touched by 9am bar
        edge_price = fvg.high  # For bullish FVG, entry is at the high (edge)
        touched_at_9am = bar_9am.low <= edge_price

        # Check mitigation status at 9am
        fvg.mitigated = False
        fvg.mitigation_bar_index = None
        for i in range(fvg.created_bar_index + 1, bar_9am_idx):
            update_fvg_mitigation(fvg, session_bars[i], i, fvg_config)
            if fvg.mitigated:
                break

        mitigated_before = fvg.mitigated

        print(f'\nFVG @ {fvg_time}')
        print(f'  Range: {fvg.low:.2f} - {fvg.high:.2f} ({size_ticks:.0f} ticks)')
        print(f'  Edge (LONG entry): {edge_price:.2f}')
        print(f'  Displacement: {"YES" if is_disp else "NO"} (body={body:.2f}, need={disp_threshold:.2f})')
        print(f'  Mitigated before 9am: {"YES" if mitigated_before else "NO"}')
        print(f'  09:00 bar low ({bar_9am.low:.2f}) touches edge ({edge_price:.2f}): {"YES" if touched_at_9am else "NO"}')

        if touched_at_9am and not mitigated_before:
            if is_disp:
                print('  --> POTENTIAL ENTRY!')
                # Check filters
                bars_to_9am = session_bars[:bar_9am_idx+1]
                ema_fast = calculate_ema(bars_to_9am, 20)
                ema_slow = calculate_ema(bars_to_9am, 50)
                adx, plus_di, minus_di = calculate_adx(bars_to_9am, 14)

                print('\n  FILTER CHECK AT 09:00:')
                if ema_fast and ema_slow:
                    ema_ok = ema_fast > ema_slow
                    print(f'    EMA 20/50: {ema_fast:.2f} / {ema_slow:.2f} -> {"PASS" if ema_ok else "FAIL"}')
                else:
                    ema_ok = True
                    print('    EMA: Not enough data (PASS)')

                if adx:
                    adx_ok = adx >= 17
                    di_ok = plus_di > minus_di
                    print(f'    ADX: {adx:.1f} -> {"PASS" if adx_ok else "FAIL (need >= 17)"}')
                    print(f'    DI: +{plus_di:.1f} / -{minus_di:.1f} -> {"PASS" if di_ok else "FAIL (need +DI > -DI)"}')
                else:
                    adx_ok = True
                    di_ok = True
                    print('    ADX/DI: Not enough data (PASS)')

                all_pass = ema_ok and adx_ok and di_ok
                if all_pass:
                    print('  >>> ALL FILTERS PASS - ENTRY SHOULD HAPPEN!')
                else:
                    failed = []
                    if not ema_ok:
                        failed.append("EMA")
                    if not adx_ok:
                        failed.append("ADX")
                    if not di_ok:
                        failed.append("DI")
                    print(f'  >>> FILTERED OUT by: {", ".join(failed)}')
            else:
                print('  --> No entry (failed displacement)')
        elif mitigated_before:
            print('  --> No entry (FVG already mitigated)')
        else:
            print('  --> No entry (not touched)')

    # Also show bars around 9am for context
    print(f'\n{"="*80}')
    print('BARS AROUND 09:00:')
    print(f'{"="*80}')
    print(f'{"Time":<8} {"Open":<10} {"High":<10} {"Low":<10} {"Close":<10}')
    print('-' * 50)
    for i in range(max(0, bar_9am_idx - 5), min(len(session_bars), bar_9am_idx + 5)):
        bar = session_bars[i]
        marker = " <-- 9:00 AM" if i == bar_9am_idx else ""
        print(f'{bar.timestamp.strftime("%H:%M"):<8} {bar.open:<10.2f} {bar.high:<10.2f} {bar.low:<10.2f} {bar.close:<10.2f}{marker}')


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    debug_9am(symbol)
