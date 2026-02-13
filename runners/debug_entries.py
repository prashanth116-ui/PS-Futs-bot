"""
Debug why no entries occurred in a specific time window.
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_fvg_mitigation


def calculate_ema(bars, period):
    """Calculate EMA for the given bars."""
    if len(bars) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(b.close for b in bars[:period]) / period
    for bar in bars[period:]:
        ema = (bar.close - ema) * multiplier + ema
    return ema


def calculate_adx(bars, period=14):
    """Calculate ADX and DI values."""
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


def debug_entries(symbol='ES', start_time='08:00', end_time='09:40'):
    """Debug why no entries occurred in a time window."""

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
    print()

    # Parse time window
    start_h, start_m = map(int, start_time.split(':'))
    end_h, end_m = map(int, end_time.split(':'))
    window_start = dt_time(start_h, start_m)
    window_end = dt_time(end_h, end_m)

    # Calculate average body size
    body_sizes = [abs(b.close - b.open) for b in session_bars[:50]]
    avg_body_size = sum(body_sizes) / len(body_sizes) if body_sizes else tick_size * 4

    # Detect all FVGs
    fvg_config = {
        'min_fvg_ticks': 5,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)

    print('=' * 80)
    print(f'DEBUGGING ENTRIES: {start_time} - {end_time}')
    print('=' * 80)
    print()

    # Find FVGs created in the time window
    print(f'FVGs CREATED IN WINDOW ({start_time} - {end_time}):')
    print('-' * 80)

    window_fvgs = []
    for fvg in all_fvgs:
        fvg_time = session_bars[fvg.created_bar_index].timestamp.time()
        if window_start <= fvg_time <= window_end:
            window_fvgs.append(fvg)
            size_ticks = (fvg.high - fvg.low) / tick_size
            creating_bar = session_bars[fvg.created_bar_index]
            is_displacement = is_displacement_candle(creating_bar, avg_body_size, 1.2)
            print(f'  {fvg.direction} FVG @ {fvg_time.strftime("%H:%M")}')
            print(f'    Range: {fvg.low:.2f} - {fvg.high:.2f} ({size_ticks:.0f} ticks)')
            print(f'    Displacement: {"YES" if is_displacement else "NO"} (body={abs(creating_bar.close-creating_bar.open):.2f}, avg={avg_body_size:.2f})')
            print()

    if not window_fvgs:
        print('  No FVGs created in this window')
    print()

    # Check for potential entries (price touching FVGs) in the window
    print(f'POTENTIAL ENTRY ANALYSIS:')
    print('-' * 80)

    # Get all FVGs that could have been entered in the window
    for fvg in all_fvgs:
        fvg.mitigated = False
        fvg.mitigation_bar_index = None

        is_long = fvg.direction == 'BULLISH'
        edge_price = fvg.high if is_long else fvg.low

        # Check displacement
        creating_bar = session_bars[fvg.created_bar_index]
        is_displacement = is_displacement_candle(creating_bar, avg_body_size, 1.2)

        if not is_displacement:
            continue

        # Look for entry touch in the window
        for i in range(fvg.created_bar_index + 1, len(session_bars)):
            bar = session_bars[i]
            bar_time = bar.timestamp.time()

            # Update mitigation
            update_fvg_mitigation(fvg, bar, i, fvg_config)

            if fvg.mitigated:
                break

            # Only check touches in the window
            if not (window_start <= bar_time <= window_end):
                continue

            # Check for edge touch
            if is_long:
                edge_hit = bar.low <= edge_price
            else:
                edge_hit = bar.high >= edge_price

            if edge_hit:
                # Check filters at this bar
                bars_to_entry = session_bars[:i+1]

                # EMA filter
                ema_fast = calculate_ema(bars_to_entry, 20)
                ema_slow = calculate_ema(bars_to_entry, 50)
                ema_ok = True
                ema_reason = ""
                if ema_fast is not None and ema_slow is not None:
                    if is_long and ema_fast < ema_slow:
                        ema_ok = False
                        ema_reason = f"EMA20 ({ema_fast:.2f}) < EMA50 ({ema_slow:.2f})"
                    elif not is_long and ema_fast > ema_slow:
                        ema_ok = False
                        ema_reason = f"EMA20 ({ema_fast:.2f}) > EMA50 ({ema_slow:.2f})"
                    else:
                        ema_reason = f"EMA20 ({ema_fast:.2f}) vs EMA50 ({ema_slow:.2f})"

                # ADX filter
                adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)
                adx_ok = True
                adx_reason = ""
                di_ok = True
                di_reason = ""

                if adx is not None:
                    if adx < 17:
                        adx_ok = False
                        adx_reason = f"ADX ({adx:.1f}) < 17"
                    else:
                        adx_reason = f"ADX ({adx:.1f}) >= 17"

                    if is_long and plus_di <= minus_di:
                        di_ok = False
                        di_reason = f"+DI ({plus_di:.1f}) <= -DI ({minus_di:.1f})"
                    elif not is_long and minus_di <= plus_di:
                        di_ok = False
                        di_reason = f"-DI ({minus_di:.1f}) <= +DI ({plus_di:.1f})"
                    else:
                        di_reason = f"+DI ({plus_di:.1f}) vs -DI ({minus_di:.1f})"

                # Print analysis
                direction = "LONG" if is_long else "SHORT"
                fvg_time = session_bars[fvg.created_bar_index].timestamp.strftime("%H:%M")
                touch_time = bar.timestamp.strftime("%H:%M")

                print(f'{direction} FVG (created {fvg_time}) touched @ {touch_time}')
                print(f'  Edge: {edge_price:.2f}')
                print(f'  Filters:')
                print(f'    EMA 20/50: {"PASS" if ema_ok else "FAIL"} - {ema_reason}')
                print(f'    ADX > 17:  {"PASS" if adx_ok else "FAIL"} - {adx_reason}')
                print(f'    DI Dir:    {"PASS" if di_ok else "FAIL"} - {di_reason}')

                if ema_ok and adx_ok and di_ok:
                    print(f'  >>> ENTRY WOULD BE TAKEN')
                else:
                    failed = []
                    if not ema_ok: failed.append("EMA")
                    if not adx_ok: failed.append("ADX")
                    if not di_ok: failed.append("DI")
                    print(f'  >>> FILTERED OUT by: {", ".join(failed)}')
                print()
                break  # Only check first touch for this FVG

    print()
    print('=' * 80)
    print('MARKET CONDITIONS IN WINDOW:')
    print('=' * 80)

    # Show market conditions at key times
    check_times = ['08:00', '08:30', '09:00', '09:30']
    for check_time in check_times:
        h, m = map(int, check_time.split(':'))
        target_time = dt_time(h, m)

        for i, bar in enumerate(session_bars):
            if bar.timestamp.time() >= target_time:
                bars_to_here = session_bars[:i+1]
                ema_fast = calculate_ema(bars_to_here, 20)
                ema_slow = calculate_ema(bars_to_here, 50)
                adx, plus_di, minus_di = calculate_adx(bars_to_here, 14)

                print(f'\n@ {check_time}:')
                print(f'  Price: {bar.close:.2f}')
                if ema_fast and ema_slow:
                    trend = "BULLISH" if ema_fast > ema_slow else "BEARISH"
                    print(f'  EMA 20/50: {ema_fast:.2f} / {ema_slow:.2f} ({trend})')
                if adx:
                    di_dir = "BULLISH" if plus_di > minus_di else "BEARISH"
                    trending = "YES" if adx >= 17 else "NO"
                    print(f'  ADX: {adx:.1f} (Trending: {trending})')
                    print(f'  +DI/-DI: {plus_di:.1f} / {minus_di:.1f} ({di_dir})')
                break


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    start = sys.argv[2] if len(sys.argv) > 2 else '08:00'
    end = sys.argv[3] if len(sys.argv) > 3 else '09:40'
    debug_entries(symbol, start, end)
