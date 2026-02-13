"""
Test loosening BOS parameters to improve win rate.

Parameters to test:
1. swing_lookback: 1 vs 2 (default)
2. bos_lookback: 10 (default) vs 15 vs 20
3. bos_fvg_window: 5 (default) vs 8 vs 10
4. skip_adx_for_bos: True vs False (default)
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs

days = 30


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
    tr_list, plus_dm_list, minus_dm_list = [], [], []
    for i in range(1, len(bars)):
        high, low = bars[i].high, bars[i].low
        close_prev, high_prev, low_prev = bars[i-1].close, bars[i-1].high, bars[i-1].low
        tr = max(high - low, abs(high - close_prev), abs(low - close_prev))
        tr_list.append(tr)
        up_move, down_move = high - high_prev, low_prev - low
        plus_dm_list.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm_list.append(down_move if down_move > up_move and down_move > 0 else 0)
    if len(tr_list) < period:
        return None, None, None
    def wilder_smooth(data, p):
        smoothed = [sum(data[:p])]
        for i in range(p, len(data)):
            smoothed.append(smoothed[-1] - (smoothed[-1] / p) + data[i])
        return smoothed
    atr = wilder_smooth(tr_list, period)
    plus_dm_smooth = wilder_smooth(plus_dm_list, period)
    minus_dm_smooth = wilder_smooth(minus_dm_list, period)
    dx_list, plus_di, minus_di = [], 0, 0
    for i in range(len(atr)):
        if atr[i] == 0:
            continue
        plus_di = 100 * plus_dm_smooth[i] / atr[i]
        minus_di = 100 * minus_dm_smooth[i] / atr[i]
        di_sum = plus_di + minus_di
        if di_sum == 0:
            continue
        dx_list.append(100 * abs(plus_di - minus_di) / di_sum)
    if len(dx_list) < period:
        return None, None, None
    return sum(dx_list[-period:]) / period, plus_di, minus_di


def is_swing_high(bars, idx, lookback=2):
    if idx < lookback or idx >= len(bars) - lookback:
        return False
    bar_high = bars[idx].high
    for i in range(1, lookback + 1):
        if bar_high <= bars[idx - i].high or bar_high <= bars[idx + i].high:
            return False
    return True


def is_swing_low(bars, idx, lookback=2):
    if idx < lookback or idx >= len(bars) - lookback:
        return False
    bar_low = bars[idx].low
    for i in range(1, lookback + 1):
        if bar_low >= bars[idx - i].low or bar_low >= bars[idx + i].low:
            return False
    return True


def find_recent_swing_high(bars, end_idx, lookback=10, swing_lookback=2):
    for i in range(end_idx - swing_lookback - 1, max(0, end_idx - lookback), -1):
        if is_swing_high(bars, i, swing_lookback):
            return i, bars[i].high
    return None, None


def find_recent_swing_low(bars, end_idx, lookback=10, swing_lookback=2):
    for i in range(end_idx - swing_lookback - 1, max(0, end_idx - lookback), -1):
        if is_swing_low(bars, i, swing_lookback):
            return i, bars[i].low
    return None, None


def detect_bos(bars, idx, lookback=10, swing_lookback=2):
    if idx < lookback:
        return None, None
    bar = bars[idx]
    sh_idx, sh_price = find_recent_swing_high(bars, idx, lookback, swing_lookback)
    if sh_idx is not None and bar.close > sh_price:
        return 'BULLISH', sh_price
    sl_idx, sl_price = find_recent_swing_low(bars, idx, lookback, swing_lookback)
    if sl_idx is not None and bar.close < sl_price:
        return 'BEARISH', sl_price
    return None, None


def run_bos_test(bars, symbol, tick_size, tick_value, contracts,
                 swing_lookback=2, bos_lookback=10, bos_fvg_window=5, skip_adx_for_bos=False):
    """Run BOS-only backtest with adjustable parameters."""
    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:]

    min_risk = 1.5 if symbol in ['ES', 'MES'] else 6.0
    max_bos_risk = 8.0 if symbol in ['ES', 'MES'] else 20.0
    min_adx = 17

    results = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0}

    for target_date in recent_dates:
        day_bars = [b for b in bars if b.timestamp.date() == target_date]
        session_bars = [b for b in day_bars if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]

        if len(session_bars) < 50:
            continue

        # Build index mappings
        session_to_all_idx = {}
        all_to_session_idx = {}
        for i, sbar in enumerate(session_bars):
            for j, abar in enumerate(bars):
                if abar.timestamp == sbar.timestamp:
                    session_to_all_idx[i] = j
                    all_to_session_idx[j] = i
                    break

        # Detect FVGs
        fvg_config = {
            'min_fvg_ticks': 5,
            'tick_size': tick_size,
            'max_fvg_age_bars': 200,
            'invalidate_on_close_through': True
        }
        all_fvgs = detect_fvgs(bars, fvg_config)

        rth_start = dt_time(9, 30)
        bos_fvgs = []

        # Find BOS events and associated FVGs
        for i in range(bos_lookback, len(session_bars)):
            bar = session_bars[i]
            if bar.timestamp.time() < rth_start:
                continue

            bos_dir, bos_level = detect_bos(session_bars, i, bos_lookback, swing_lookback)
            if bos_dir is None:
                continue

            for fvg in all_fvgs:
                fvg_session_idx = all_to_session_idx.get(fvg.created_bar_index)
                if fvg_session_idx is None:
                    continue

                bars_after_bos = fvg_session_idx - i
                if bars_after_bos < 0 or bars_after_bos > bos_fvg_window:
                    continue

                expected_dir = 'BULLISH' if bos_dir == 'BULLISH' else 'BEARISH'
                if fvg.direction != expected_dir:
                    continue

                fvg_size_ticks = (fvg.high - fvg.low) / tick_size
                if fvg_size_ticks < 5:
                    continue

                already_tracked = any(e[2].low == fvg.low and e[2].high == fvg.high for e in bos_fvgs)
                if not already_tracked:
                    bos_fvgs.append((i, bos_dir, fvg))

        # Find retracement entries
        entries_taken = set()

        for bos_bar_idx, bos_dir, fvg in bos_fvgs:
            fvg_session_idx = all_to_session_idx.get(fvg.created_bar_index)
            if fvg_session_idx is None:
                continue

            direction = 'LONG' if bos_dir == 'BULLISH' else 'SHORT'
            is_long = direction == 'LONG'

            for i in range(fvg_session_idx + 1, len(session_bars)):
                bar = session_bars[i]
                all_bar_idx = session_to_all_idx.get(i)
                if all_bar_idx is None:
                    continue

                # Check retracement
                if is_long:
                    touches_fvg = bar.low <= fvg.high and bar.low >= fvg.low - (tick_size * 2)
                    if not touches_fvg:
                        continue
                    entry_price = max(fvg.midpoint, bar.close)
                    stop_price = fvg.low - (2 * tick_size)
                else:
                    touches_fvg = bar.high >= fvg.low and bar.high <= fvg.high + (tick_size * 2)
                    if not touches_fvg:
                        continue
                    entry_price = min(fvg.midpoint, bar.close)
                    stop_price = fvg.high + (2 * tick_size)

                risk = abs(entry_price - stop_price)
                if risk < min_risk or risk > max_bos_risk:
                    continue

                # Apply filters (optionally skip ADX for BOS)
                bars_to_entry = bars[:all_bar_idx + 1]
                ema_fast = calculate_ema(bars_to_entry, 20)
                ema_slow = calculate_ema(bars_to_entry, 50)
                adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)

                ema_ok = ema_fast is None or ema_slow is None or (ema_fast > ema_slow if is_long else ema_fast < ema_slow)

                if skip_adx_for_bos:
                    adx_ok = True  # Skip ADX check for BOS
                else:
                    adx_ok = adx is None or adx >= min_adx

                di_ok = adx is None or (plus_di > minus_di if is_long else minus_di > plus_di)

                if not (ema_ok and adx_ok and di_ok):
                    continue

                # Time filters
                entry_hour = bar.timestamp.hour
                if 12 <= entry_hour < 14:
                    continue
                if symbol in ['NQ', 'MNQ'] and entry_hour >= 14:
                    continue

                # Check duplicate
                entry_key = (target_date, round(entry_price, 2), direction)
                if entry_key in entries_taken:
                    continue
                entries_taken.add(entry_key)

                # Simulate trade (simplified - assume 4R target or stop)
                target_price = entry_price + (4 * risk) if is_long else entry_price - (4 * risk)

                # Check future bars for outcome
                won = False
                for future_i in range(i + 1, len(session_bars)):
                    future_bar = session_bars[future_i]

                    if is_long:
                        if future_bar.low <= stop_price:
                            break  # Stopped out
                        if future_bar.high >= target_price:
                            won = True
                            break
                    else:
                        if future_bar.high >= stop_price:
                            break  # Stopped out
                        if future_bar.low <= target_price:
                            won = True
                            break

                results['trades'] += 1
                if won:
                    results['wins'] += 1
                    results['pnl'] += 4 * risk * tick_value / tick_size * contracts
                else:
                    results['losses'] += 1
                    results['pnl'] -= risk * tick_value / tick_size * contracts

                break  # One entry per BOS FVG

    return results


def main():
    print('Fetching data...')
    es_bars = fetch_futures_bars('ES', interval='3m', n_bars=15000)
    nq_bars = fetch_futures_bars('NQ', interval='3m', n_bars=15000)

    # Test configurations
    configs = [
        # (swing_lookback, bos_lookback, bos_fvg_window, skip_adx, name)
        (2, 10, 5, False, 'DEFAULT'),
        (1, 10, 5, False, 'swing=1'),
        (2, 15, 5, False, 'bos_lb=15'),
        (2, 20, 5, False, 'bos_lb=20'),
        (2, 10, 8, False, 'fvg_win=8'),
        (2, 10, 10, False, 'fvg_win=10'),
        (2, 10, 5, True, 'skip_adx'),
        (1, 15, 8, False, 'swing=1+lb=15+win=8'),
        (1, 20, 10, False, 'swing=1+lb=20+win=10'),
        (1, 15, 8, True, 'LOOSE (all relaxed)'),
    ]

    print('\n' + '=' * 90)
    print('BOS PARAMETER TESTING - ES (30 days)')
    print('=' * 90)
    print(f"\n{'Config':<25} {'Trades':>8} {'Wins':>6} {'Losses':>7} {'Win%':>8} {'P/L':>14}")
    print('-' * 75)

    es_results = []
    for swing_lb, bos_lb, fvg_win, skip_adx, name in configs:
        r = run_bos_test(es_bars, 'ES', 0.25, 12.50, 3, swing_lb, bos_lb, fvg_win, skip_adx)
        wr = r['wins'] / r['trades'] * 100 if r['trades'] else 0
        print(f"{name:<25} {r['trades']:>8} {r['wins']:>6} {r['losses']:>7} {wr:>7.1f}% ${r['pnl']:>12,.0f}")
        es_results.append((name, r))

    print('\n' + '=' * 90)
    print('BOS PARAMETER TESTING - NQ (30 days)')
    print('=' * 90)
    print(f"\n{'Config':<25} {'Trades':>8} {'Wins':>6} {'Losses':>7} {'Win%':>8} {'P/L':>14}")
    print('-' * 75)

    nq_results = []
    for swing_lb, bos_lb, fvg_win, skip_adx, name in configs:
        r = run_bos_test(nq_bars, 'NQ', 0.25, 5.00, 3, swing_lb, bos_lb, fvg_win, skip_adx)
        wr = r['wins'] / r['trades'] * 100 if r['trades'] else 0
        print(f"{name:<25} {r['trades']:>8} {r['wins']:>6} {r['losses']:>7} {wr:>7.1f}% ${r['pnl']:>12,.0f}")
        nq_results.append((name, r))

    # Find best configs
    print('\n' + '=' * 90)
    print('BEST CONFIGURATIONS')
    print('=' * 90)

    # Best by win rate (min 3 trades)
    es_by_wr = [(n, r, r['wins']/r['trades']*100 if r['trades'] >= 3 else 0) for n, r in es_results]
    es_by_wr.sort(key=lambda x: x[2], reverse=True)

    nq_by_wr = [(n, r, r['wins']/r['trades']*100 if r['trades'] >= 3 else 0) for n, r in nq_results]
    nq_by_wr.sort(key=lambda x: x[2], reverse=True)

    print('\nES - Best by Win Rate:')
    for name, r, wr in es_by_wr[:3]:
        print(f"  {name}: {wr:.1f}% ({r['trades']} trades, ${r['pnl']:+,.0f})")

    print('\nNQ - Best by Win Rate:')
    for name, r, wr in nq_by_wr[:3]:
        print(f"  {name}: {wr:.1f}% ({r['trades']} trades, ${r['pnl']:+,.0f})")

    # Best by P/L
    es_by_pnl = sorted(es_results, key=lambda x: x[1]['pnl'], reverse=True)
    nq_by_pnl = sorted(nq_results, key=lambda x: x[1]['pnl'], reverse=True)

    print('\nES - Best by P/L:')
    for name, r in es_by_pnl[:3]:
        wr = r['wins'] / r['trades'] * 100 if r['trades'] else 0
        print(f"  {name}: ${r['pnl']:+,.0f} ({wr:.1f}% WR, {r['trades']} trades)")

    print('\nNQ - Best by P/L:')
    for name, r in nq_by_pnl[:3]:
        wr = r['wins'] / r['trades'] * 100 if r['trades'] else 0
        print(f"  {name}: ${r['pnl']:+,.0f} ({wr:.1f}% WR, {r['trades']} trades)")


if __name__ == '__main__':
    main()
