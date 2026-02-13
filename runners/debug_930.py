"""
Debug 9:30 Entry - Why didn't the strategy enter at 9:30?
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs
from runners.run_v10_dual_entry import calculate_ema, calculate_adx, detect_bos, is_rejection_candle


def debug_930(symbol='ES'):
    """Debug why no entry was taken at 9:30."""

    tick_size = 0.25
    min_risk_pts = 1.5 if symbol in ['ES', 'MES'] else 6.0

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

    # Find 9:30 bar and surrounding bars
    print('\n' + '='*80)
    print('BARS AROUND 9:30')
    print('='*80)

    for i, bar in enumerate(session_bars):
        bar_time = bar.timestamp.time()
        if dt_time(9, 24) <= bar_time <= dt_time(9, 48):
            print(f'{bar.timestamp.strftime("%H:%M")} | O:{bar.open:.2f} H:{bar.high:.2f} L:{bar.low:.2f} C:{bar.close:.2f}')

    # Detect FVGs
    fvg_config = {
        'min_fvg_ticks': 2,
        'tick_size': tick_size,
        'max_fvg_age_bars': 200,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(all_bars, fvg_config)

    # Find FVGs active around 9:30
    print('\n' + '='*80)
    print('FVGs AVAILABLE AT 9:30')
    print('='*80)

    # Find the bar index for 9:30
    bar_930_idx = None
    for i, bar in enumerate(all_bars):
        if bar.timestamp.date() == today and bar.timestamp.time() >= dt_time(9, 30):
            bar_930_idx = i
            break

    if bar_930_idx:
        print(f'Bar index at 9:30: {bar_930_idx}')
        bar_930 = all_bars[bar_930_idx]
        print(f'9:30 bar: O:{bar_930.open:.2f} H:{bar_930.high:.2f} L:{bar_930.low:.2f} C:{bar_930.close:.2f}')

        # Check which FVGs were valid at this point
        valid_fvgs = []
        for fvg in all_fvgs:
            if fvg.created_bar_index < bar_930_idx:
                # Check if FVG is still valid (not mitigated)
                fvg_created_time = all_bars[fvg.created_bar_index].timestamp
                age_bars = bar_930_idx - fvg.created_bar_index

                # Check if price has closed through it
                mitigated = False
                for j in range(fvg.created_bar_index + 1, bar_930_idx):
                    if fvg.direction == 'BULLISH':
                        if all_bars[j].close < fvg.low:
                            mitigated = True
                            break
                    else:
                        if all_bars[j].close > fvg.high:
                            mitigated = True
                            break

                if not mitigated and age_bars < 200:
                    valid_fvgs.append({
                        'fvg': fvg,
                        'created': fvg_created_time,
                        'age': age_bars,
                    })

        print(f'\nValid FVGs at 9:30: {len(valid_fvgs)}')

        # Show overnight FVGs (created before 9:30)
        overnight_fvgs = [f for f in valid_fvgs if f['created'].time() < dt_time(9, 30)]
        print(f'Overnight FVGs: {len(overnight_fvgs)}')

        for f in overnight_fvgs[-10:]:  # Show last 10
            fvg = f['fvg']
            size = (fvg.high - fvg.low) / tick_size
            print(f"  {fvg.direction}: {fvg.low:.2f} - {fvg.high:.2f} (size: {size:.1f} ticks) | Created: {f['created'].strftime('%H:%M')} | Age: {f['age']} bars")

    # Check indicators at 9:30
    print('\n' + '='*80)
    print('INDICATORS AT 9:30')
    print('='*80)

    if bar_930_idx:
        bars_to_930 = all_bars[:bar_930_idx + 1]

        ema_fast = calculate_ema(bars_to_930, 20)
        ema_slow = calculate_ema(bars_to_930, 50)
        adx, plus_di, minus_di = calculate_adx(bars_to_930, 14)

        print(f'EMA 20: {ema_fast:.2f}')
        print(f'EMA 50: {ema_slow:.2f}')
        print(f'EMA Trend: {"BULLISH (EMA20 > EMA50)" if ema_fast > ema_slow else "BEARISH (EMA20 < EMA50)"}')
        print(f'ADX: {adx:.2f}')
        print(f'+DI: {plus_di:.2f}')
        print(f'-DI: {minus_di:.2f}')
        print(f'DI Direction: {"LONG (+DI > -DI)" if plus_di > minus_di else "SHORT (-DI > +DI)"}')

        # Check for BOS at 9:30
        print('\n' + '='*80)
        print('BOS CHECK AT 9:30')
        print('='*80)

        # Map session bars to all_bars
        session_to_all = {}
        for i, sbar in enumerate(session_bars):
            for j, abar in enumerate(all_bars):
                if abar.timestamp == sbar.timestamp:
                    session_to_all[i] = j
                    break

        # Find session bar index for 9:30
        session_930_idx = None
        for i, bar in enumerate(session_bars):
            if bar.timestamp.time() >= dt_time(9, 30):
                session_930_idx = i
                break

        if session_930_idx:
            print(f'Session bar index at 9:30: {session_930_idx}')

            # Check BOS
            bos_dir, bos_level = detect_bos(session_bars, session_930_idx, lookback=10)
            if bos_dir:
                print(f'BOS detected: {bos_dir} at level {bos_level:.2f}')
            else:
                print('No BOS detected at 9:30')

                # Show recent swing points
                print('\nRecent swing points:')
                for i in range(max(0, session_930_idx - 15), session_930_idx + 1):
                    bar = session_bars[i]
                    print(f'  {bar.timestamp.strftime("%H:%M")} | H:{bar.high:.2f} L:{bar.low:.2f}')

        # Check rejection candle at 9:30
        print('\n' + '='*80)
        print('REJECTION CANDLE CHECK AT 9:30')
        print('='*80)

        bar_930 = all_bars[bar_930_idx]

        for f in overnight_fvgs[-5:]:
            fvg = f['fvg']

            # Check for LONG rejection (bullish FVG)
            if fvg.direction == 'BULLISH':
                is_rejection, entry, stop = is_rejection_candle(bar_930, fvg, 'LONG', tick_size)
                if is_rejection:
                    risk = abs(entry - stop)
                    print(f'BULLISH FVG {fvg.low:.2f}-{fvg.high:.2f}: REJECTION FOUND')
                    print(f'  Entry: {entry:.2f}, Stop: {stop:.2f}, Risk: {risk:.2f} pts')
                else:
                    # Check why no rejection
                    wick_into = bar_930.low <= fvg.high and bar_930.low >= fvg.low
                    wick_through = bar_930.low < fvg.low
                    wick_near = bar_930.low <= fvg.high + (5 * tick_size)
                    body = abs(bar_930.close - bar_930.open)
                    wick_bottom = min(bar_930.open, bar_930.close)
                    wick_size = wick_bottom - bar_930.low
                    close_above = bar_930.close >= fvg.high

                    print(f'BULLISH FVG {fvg.low:.2f}-{fvg.high:.2f}: NO REJECTION')
                    print(f'  Bar low: {bar_930.low:.2f}, FVG range: {fvg.low:.2f}-{fvg.high:.2f}')
                    print(f'  Wick into FVG: {wick_into}')
                    print(f'  Wick through FVG: {wick_through}')
                    print(f'  Wick near FVG: {wick_near}')
                    print(f'  Wick size: {wick_size:.2f}, Body: {body:.2f}, Wick > Body: {wick_size > body}')
                    print(f'  Close ({bar_930.close:.2f}) above FVG high ({fvg.high:.2f}): {close_above}')

            # Check for SHORT rejection (bearish FVG)
            elif fvg.direction == 'BEARISH':
                is_rejection, entry, stop = is_rejection_candle(bar_930, fvg, 'SHORT', tick_size)
                if is_rejection:
                    risk = abs(entry - stop)
                    print(f'BEARISH FVG {fvg.low:.2f}-{fvg.high:.2f}: REJECTION FOUND')
                    print(f'  Entry: {entry:.2f}, Stop: {stop:.2f}, Risk: {risk:.2f} pts')
                else:
                    print(f'BEARISH FVG {fvg.low:.2f}-{fvg.high:.2f}: NO REJECTION (checking SHORT)')


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    debug_930(symbol)
    print('\n\n')
    debug_930('NQ')
