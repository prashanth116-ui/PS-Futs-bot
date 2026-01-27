"""
Run MES strategy for today.
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time
from tvDatafeed import TvDatafeed, Interval
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations


class Bar:
    def __init__(self, timestamp, open_, high, low, close, volume):
        self.timestamp = timestamp
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


def calculate_ema(closes, period):
    ema = []
    multiplier = 2 / (period + 1)
    for i, close in enumerate(closes):
        if i < period - 1:
            ema.append(None)
        elif i == period - 1:
            sma = sum(closes[:period]) / period
            ema.append(sma)
        else:
            ema.append((close * multiplier) + (ema[-1] * (1 - multiplier)))
    return ema


def run_trade(session_bars, direction, fvg_num, tick_size=0.25, tick_value=1.25, contracts=3, target1_r=4, target2_r=8):
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'

    fvg_config = {
        'min_fvg_ticks': 4,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)
    update_all_fvg_mitigations(all_fvgs, session_bars, fvg_config)

    active_fvgs = [f for f in all_fvgs if f.direction == fvg_dir and not f.mitigated]
    active_fvgs.sort(key=lambda f: f.created_bar_index)

    if len(active_fvgs) < fvg_num:
        return None

    entry_fvg = active_fvgs[fvg_num - 1]
    entry_price = entry_fvg.midpoint

    if is_long:
        stop_price = entry_fvg.low - (2 * tick_size)
        risk = entry_price - stop_price
    else:
        stop_price = entry_fvg.high + (2 * tick_size)
        risk = stop_price - entry_price

    target_t1 = entry_price + (target1_r * risk) if is_long else entry_price - (target1_r * risk)
    target_t2 = entry_price + (target2_r * risk) if is_long else entry_price - (target2_r * risk)

    closes = [b.close for b in session_bars]
    ema_50 = calculate_ema(closes, 50)

    entry_bar_idx = None
    entry_time = None

    for i in range(entry_fvg.created_bar_index + 1, len(session_bars)):
        bar = session_bars[i]
        price_at_entry = bar.low <= entry_price if is_long else bar.high >= entry_price
        if price_at_entry:
            entry_bar_idx = i
            entry_time = bar.timestamp
            break

    if not entry_bar_idx:
        return None

    cts_t1 = 1
    cts_t2 = 1
    cts_runner = 1

    exits = []
    remaining = contracts
    exited_t1 = False
    exited_t2 = False

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]
        bar_ema50 = ema_50[i] if i < len(ema_50) and ema_50[i] else None

        stop_hit = bar.low <= stop_price if is_long else bar.high >= stop_price
        if stop_hit:
            pnl = (stop_price - entry_price) * remaining if is_long else (entry_price - stop_price) * remaining
            exits.append({'type': 'STOP', 'pnl': pnl, 'price': stop_price, 'time': bar.timestamp, 'cts': remaining})
            remaining = 0
            break

        t1_hit = bar.high >= target_t1 if is_long else bar.low <= target_t1
        if not exited_t1 and t1_hit:
            exit_cts = min(cts_t1, remaining)
            pnl = (target_t1 - entry_price) * exit_cts if is_long else (entry_price - target_t1) * exit_cts
            exits.append({'type': f'T{target1_r}R', 'pnl': pnl, 'price': target_t1, 'time': bar.timestamp, 'cts': exit_cts})
            remaining -= exit_cts
            exited_t1 = True

        t2_hit = bar.high >= target_t2 if is_long else bar.low <= target_t2
        if not exited_t2 and t2_hit and remaining > cts_runner:
            exit_cts = min(cts_t2, remaining - cts_runner)
            pnl = (target_t2 - entry_price) * exit_cts if is_long else (entry_price - target_t2) * exit_cts
            exits.append({'type': f'T{target2_r}R', 'pnl': pnl, 'price': target_t2, 'time': bar.timestamp, 'cts': exit_cts})
            remaining -= exit_cts
            exited_t2 = True

        if remaining > 0 and remaining <= cts_runner and bar_ema50:
            ema_exit = bar.close < bar_ema50 if is_long else bar.close > bar_ema50
            if ema_exit:
                pnl = (bar.close - entry_price) * remaining if is_long else (entry_price - bar.close) * remaining
                exits.append({'type': 'EMA50', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': remaining})
                remaining = 0

    if remaining > 0:
        last_bar = session_bars[-1]
        pnl = (last_bar.close - entry_price) * remaining if is_long else (entry_price - last_bar.close) * remaining
        exits.append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'cts': remaining})

    total_pnl = sum(e['pnl'] for e in exits)
    total_dollars = (total_pnl / tick_size) * tick_value
    was_stopped = any(e['type'] == 'STOP' for e in exits)

    return {
        'direction': direction,
        'entry_time': entry_time,
        'entry_price': entry_price,
        'stop_price': stop_price,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'was_stopped': was_stopped,
        'exits': exits,
    }


def main():
    # Fetch MES data
    print('Fetching MES 3m data for today...')
    tv = TvDatafeed()
    data = tv.get_hist(symbol='MES1!', exchange='CME_MINI', interval=Interval.in_3_minute, n_bars=500)

    if data is None or len(data) == 0:
        print('No data available')
        return

    # Convert to Bar objects
    all_bars = []
    for idx, row in data.iterrows():
        bar = Bar(idx.to_pydatetime(), row['open'], row['high'], row['low'], row['close'], row['volume'])
        all_bars.append(bar)

    today = date(2026, 1, 27)
    today_bars = [b for b in all_bars if b.timestamp.date() == today]

    print(f'Got {len(today_bars)} bars for {today}')

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

    print(f'Session bars: {len(session_bars)}')

    if len(session_bars) < 50:
        print('Not enough bars for analysis')
        return

    tick_size = 0.25
    tick_value = 1.25

    print()
    print('=' * 70)
    print(f'TODAY ({today}) - MES 3m - 3 CONTRACTS - 4R/8R Targets')
    print('=' * 70)
    print('Exit plan: 1 ct @ 4R, 1 ct @ 8R, 1 ct @ EMA50 runner')
    print(f'Tick value: ${tick_value} (micro)')
    print('=' * 70)

    # Try LONG
    result = run_trade(session_bars, 'LONG', 1, tick_size=tick_size, tick_value=tick_value, contracts=3, target1_r=4, target2_r=8)
    if result:
        result_str = 'WIN' if result['total_pnl'] > 0.01 else 'LOSS' if result['total_pnl'] < -0.01 else 'BE'
        print(f"LONG  | Entry: {result['entry_time'].strftime('%H:%M')} | {result_str} | ${result['total_dollars']:+,.2f}")
        print(f"       Entry: {result['entry_price']:.2f} | Stop: {result['stop_price']:.2f}")
        for e in result['exits']:
            print(f"       Exit {e['type']}: {e['cts']} cts @ {e['price']:.2f} = ${(e['pnl']/tick_size)*tick_value:+,.2f}")

        if result['was_stopped']:
            print()
            print('  --> Stopped out, trying re-entry on 2nd FVG...')
            result2 = run_trade(session_bars, 'LONG', 2, tick_size=tick_size, tick_value=tick_value, contracts=3, target1_r=4, target2_r=8)
            if result2:
                result_str2 = 'WIN' if result2['total_pnl'] > 0.01 else 'LOSS'
                print(f"LONG [RE-ENTRY] | Entry: {result2['entry_time'].strftime('%H:%M')} | {result_str2} | ${result2['total_dollars']:+,.2f}")
                print(f"       Entry: {result2['entry_price']:.2f} | Stop: {result2['stop_price']:.2f}")
                for e in result2['exits']:
                    print(f"       Exit {e['type']}: {e['cts']} cts @ {e['price']:.2f} = ${(e['pnl']/tick_size)*tick_value:+,.2f}")

    print()

    # Try SHORT
    result = run_trade(session_bars, 'SHORT', 1, tick_size=tick_size, tick_value=tick_value, contracts=3, target1_r=4, target2_r=8)
    if result:
        result_str = 'WIN' if result['total_pnl'] > 0.01 else 'LOSS' if result['total_pnl'] < -0.01 else 'BE'
        print(f"SHORT | Entry: {result['entry_time'].strftime('%H:%M')} | {result_str} | ${result['total_dollars']:+,.2f}")
        print(f"       Entry: {result['entry_price']:.2f} | Stop: {result['stop_price']:.2f}")
        for e in result['exits']:
            print(f"       Exit {e['type']}: {e['cts']} cts @ {e['price']:.2f} = ${(e['pnl']/tick_size)*tick_value:+,.2f}")

        if result['was_stopped']:
            print()
            print('  --> Stopped out, trying re-entry on 2nd FVG...')
            result2 = run_trade(session_bars, 'SHORT', 2, tick_size=tick_size, tick_value=tick_value, contracts=3, target1_r=4, target2_r=8)
            if result2:
                result_str2 = 'WIN' if result2['total_pnl'] > 0.01 else 'LOSS'
                print(f"SHORT [RE-ENTRY] | Entry: {result2['entry_time'].strftime('%H:%M')} | {result_str2} | ${result2['total_dollars']:+,.2f}")
                print(f"       Entry: {result2['entry_price']:.2f} | Stop: {result2['stop_price']:.2f}")
                for e in result2['exits']:
                    print(f"       Exit {e['type']}: {e['cts']} cts @ {e['price']:.2f} = ${(e['pnl']/tick_size)*tick_value:+,.2f}")

    print('=' * 70)
    print()
    print('Note: MES is 1/10th the value of ES')
    print('      ES equivalent P/L would be 10x these values')


if __name__ == '__main__':
    main()
