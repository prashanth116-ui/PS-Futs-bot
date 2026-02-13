"""
MSS (Market Structure Shift) vs BOS Comparison

MSS Criteria (ICT Style):
1. Swing Failure: Price fails to make new high/low (lower high or higher low)
2. Displacement: Large body candle breaks through previous swing with momentum
3. FVG Forms: Gap left during the displacement move
4. Entry: Retrace into the FVG after the shift confirms

Key Difference from BOS:
- BOS = continuation (break swing in trend direction)
- MSS = reversal (break swing AGAINST prior trend after failure)
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


def find_swing_highs(bars, start_idx, end_idx, lookback=2):
    """Find all swing highs in range."""
    swings = []
    for i in range(start_idx, end_idx):
        if is_swing_high(bars, i, lookback):
            swings.append((i, bars[i].high))
    return swings


def find_swing_lows(bars, start_idx, end_idx, lookback=2):
    """Find all swing lows in range."""
    swings = []
    for i in range(start_idx, end_idx):
        if is_swing_low(bars, i, lookback):
            swings.append((i, bars[i].low))
    return swings


def detect_mss(bars, idx, lookback=15, displacement_mult=1.5):
    """
    Detect Market Structure Shift at bar index.

    MSS = Swing Failure + Displacement Break

    Bearish MSS (LONG signal - shift from bearish to bullish):
    1. Find two consecutive swing lows where second is HIGHER (higher low = failure)
    2. Current bar has displacement (big body) breaking ABOVE recent swing high

    Bullish MSS (SHORT signal - shift from bullish to bearish):
    1. Find two consecutive swing highs where second is LOWER (lower high = failure)
    2. Current bar has displacement (big body) breaking BELOW recent swing low

    Returns:
        ('BULLISH', swing_level) - bearish-to-bullish shift, go LONG
        ('BEARISH', swing_level) - bullish-to-bearish shift, go SHORT
        (None, None) - no MSS
    """
    if idx < lookback + 5:
        return None, None

    bar = bars[idx]
    body = abs(bar.close - bar.open)

    # Calculate average body for displacement check
    recent_bodies = [abs(bars[i].close - bars[i].open) for i in range(max(0, idx-20), idx)]
    avg_body = sum(recent_bodies) / len(recent_bodies) if recent_bodies else body

    # Require displacement
    if body < avg_body * displacement_mult:
        return None, None

    # Find recent swing points
    swing_highs = find_swing_highs(bars, idx - lookback, idx - 2, lookback=2)
    swing_lows = find_swing_lows(bars, idx - lookback, idx - 2, lookback=2)

    # Check for Bearish-to-Bullish MSS (LONG signal)
    # Need: higher low (swing failure) + displacement break above swing high
    if len(swing_lows) >= 2 and len(swing_highs) >= 1:
        # Sort by index
        swing_lows.sort(key=lambda x: x[0])
        swing_highs.sort(key=lambda x: x[0])

        # Check for higher low (most recent low > previous low)
        recent_low = swing_lows[-1]
        prev_low = swing_lows[-2]

        if recent_low[1] > prev_low[1]:  # Higher low = bearish failure
            # Find swing high to break
            recent_high = swing_highs[-1]

            # Check if current bar breaks above swing high with displacement
            if bar.close > recent_high[1] and bar.close > bar.open:  # Bullish displacement
                return 'BULLISH', recent_high[1]

    # Check for Bullish-to-Bearish MSS (SHORT signal)
    # Need: lower high (swing failure) + displacement break below swing low
    if len(swing_highs) >= 2 and len(swing_lows) >= 1:
        swing_highs.sort(key=lambda x: x[0])
        swing_lows.sort(key=lambda x: x[0])

        # Check for lower high (most recent high < previous high)
        recent_high = swing_highs[-1]
        prev_high = swing_highs[-2]

        if recent_high[1] < prev_high[1]:  # Lower high = bullish failure
            # Find swing low to break
            recent_low = swing_lows[-1]

            # Check if current bar breaks below swing low with displacement
            if bar.close < recent_low[1] and bar.close < bar.open:  # Bearish displacement
                return 'BEARISH', recent_low[1]

    return None, None


def detect_bos(bars, idx, lookback=10, swing_lookback=2):
    """Detect Break of Structure (continuation signal)."""
    if idx < lookback:
        return None, None

    bar = bars[idx]

    # Find recent swing high
    for i in range(idx - swing_lookback - 1, max(0, idx - lookback), -1):
        if is_swing_high(bars, i, swing_lookback):
            if bar.close > bars[i].high:
                return 'BULLISH', bars[i].high
            break

    # Find recent swing low
    for i in range(idx - swing_lookback - 1, max(0, idx - lookback), -1):
        if is_swing_low(bars, i, swing_lookback):
            if bar.close < bars[i].low:
                return 'BEARISH', bars[i].low
            break

    return None, None


def run_entry_test(bars, symbol, tick_size, tick_value, contracts, entry_type='MSS'):
    """Run backtest for MSS or BOS entries."""
    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:]

    min_risk = 1.5 if symbol in ['ES', 'MES'] else 6.0
    max_risk = 8.0 if symbol in ['ES', 'MES'] else 20.0

    results = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0, 'entries': []}

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
        structure_fvgs = []  # (signal_bar_idx, direction, fvg)

        # Find structure signals (MSS or BOS) and associated FVGs
        for i in range(15, len(session_bars)):
            bar = session_bars[i]
            if bar.timestamp.time() < rth_start:
                continue

            # Detect structure signal
            if entry_type == 'MSS':
                signal_dir, signal_level = detect_mss(session_bars, i)
            else:  # BOS
                signal_dir, signal_level = detect_bos(session_bars, i)

            if signal_dir is None:
                continue

            # Find FVGs created within 5 bars after signal
            for fvg in all_fvgs:
                fvg_session_idx = all_to_session_idx.get(fvg.created_bar_index)
                if fvg_session_idx is None:
                    continue

                bars_after = fvg_session_idx - i
                if bars_after < 0 or bars_after > 5:
                    continue

                expected_dir = 'BULLISH' if signal_dir == 'BULLISH' else 'BEARISH'
                if fvg.direction != expected_dir:
                    continue

                fvg_size_ticks = (fvg.high - fvg.low) / tick_size
                if fvg_size_ticks < 5:
                    continue

                already_tracked = any(e[2].low == fvg.low and e[2].high == fvg.high for e in structure_fvgs)
                if not already_tracked:
                    structure_fvgs.append((i, signal_dir, fvg))

        # Find retracement entries
        entries_taken = set()

        for signal_bar_idx, signal_dir, fvg in structure_fvgs:
            fvg_session_idx = all_to_session_idx.get(fvg.created_bar_index)
            if fvg_session_idx is None:
                continue

            direction = 'LONG' if signal_dir == 'BULLISH' else 'SHORT'
            is_long = direction == 'LONG'

            for i in range(fvg_session_idx + 1, len(session_bars)):
                bar = session_bars[i]
                all_bar_idx = session_to_all_idx.get(i)
                if all_bar_idx is None:
                    continue

                # Check retracement into FVG
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
                if risk < min_risk or risk > max_risk:
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

                # Simulate trade
                target_price = entry_price + (4 * risk) if is_long else entry_price - (4 * risk)

                won = False
                for future_i in range(i + 1, len(session_bars)):
                    future_bar = session_bars[future_i]

                    if is_long:
                        if future_bar.low <= stop_price:
                            break
                        if future_bar.high >= target_price:
                            won = True
                            break
                    else:
                        if future_bar.high >= stop_price:
                            break
                        if future_bar.low <= target_price:
                            won = True
                            break

                results['trades'] += 1
                pnl = 4 * risk * tick_value / tick_size * contracts if won else -risk * tick_value / tick_size * contracts

                if won:
                    results['wins'] += 1
                else:
                    results['losses'] += 1
                results['pnl'] += pnl

                results['entries'].append({
                    'date': target_date,
                    'direction': direction,
                    'entry_type': entry_type,
                    'won': won,
                    'pnl': pnl
                })

                break

    return results


def run_baseline(bars, symbol, tick_size, tick_value, contracts):
    """Run baseline (Creation + Retracement entries only, no BOS/MSS)."""
    # This is a simplified version - just count FVG creation entries
    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:]

    min_risk = 1.5 if symbol in ['ES', 'MES'] else 6.0

    results = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0}

    for target_date in recent_dates:
        day_bars = [b for b in bars if b.timestamp.date() == target_date]
        session_bars = [b for b in day_bars if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]

        if len(session_bars) < 50:
            continue

        # Build index mappings
        session_to_all_idx = {}
        for i, sbar in enumerate(session_bars):
            for j, abar in enumerate(bars):
                if abar.timestamp == sbar.timestamp:
                    session_to_all_idx[i] = j
                    break

        # Calculate average body
        body_sizes = [abs(b.close - b.open) for b in session_bars[:50]]
        avg_body = sum(body_sizes) / len(body_sizes) if body_sizes else tick_size * 4

        # Detect FVGs
        fvg_config = {
            'min_fvg_ticks': 5,
            'tick_size': tick_size,
            'max_fvg_age_bars': 200,
            'invalidate_on_close_through': True
        }
        all_fvgs = detect_fvgs(bars, fvg_config)

        rth_start = dt_time(9, 30)
        entries_taken = set()

        for fvg in all_fvgs:
            # Only session FVGs
            creating_bar_idx = fvg.created_bar_index
            if creating_bar_idx >= len(bars):
                continue
            creating_bar = bars[creating_bar_idx]

            if creating_bar.timestamp.date() != target_date:
                continue
            if creating_bar.timestamp.time() < rth_start:
                continue

            # Check displacement
            body = abs(creating_bar.close - creating_bar.open)
            if body < avg_body * 1.0:
                continue

            # FVG size check
            fvg_size_ticks = (fvg.high - fvg.low) / tick_size
            if fvg_size_ticks < 5:
                continue

            direction = 'LONG' if fvg.direction == 'BULLISH' else 'SHORT'
            is_long = direction == 'LONG'

            entry_price = fvg.midpoint
            stop_price = fvg.low - (2 * tick_size) if is_long else fvg.high + (2 * tick_size)
            risk = abs(entry_price - stop_price)

            if risk < min_risk:
                continue

            # Time filters
            entry_hour = creating_bar.timestamp.hour
            if 12 <= entry_hour < 14:
                continue
            if symbol in ['NQ', 'MNQ'] and entry_hour >= 14:
                continue

            entry_key = (target_date, round(entry_price, 2), direction)
            if entry_key in entries_taken:
                continue
            entries_taken.add(entry_key)

            # Find session bar index for simulation
            session_idx = None
            for i, sbar in enumerate(session_bars):
                if sbar.timestamp == creating_bar.timestamp:
                    session_idx = i
                    break

            if session_idx is None:
                continue

            # Simulate trade
            target_price = entry_price + (4 * risk) if is_long else entry_price - (4 * risk)

            won = False
            for future_i in range(session_idx + 1, len(session_bars)):
                future_bar = session_bars[future_i]

                if is_long:
                    if future_bar.low <= stop_price:
                        break
                    if future_bar.high >= target_price:
                        won = True
                        break
                else:
                    if future_bar.high >= stop_price:
                        break
                    if future_bar.low <= target_price:
                        won = True
                        break

            results['trades'] += 1
            pnl = 4 * risk * tick_value / tick_size * contracts if won else -risk * tick_value / tick_size * contracts

            if won:
                results['wins'] += 1
            else:
                results['losses'] += 1
            results['pnl'] += pnl

    return results


def main():
    print('Fetching data...')
    es_bars = fetch_futures_bars('ES', interval='3m', n_bars=15000)
    nq_bars = fetch_futures_bars('NQ', interval='3m', n_bars=15000)
    spy_bars = fetch_futures_bars('SPY', interval='3m', n_bars=15000)
    qqq_bars = fetch_futures_bars('QQQ', interval='3m', n_bars=15000)

    print('\n' + '=' * 90)
    print('MSS vs BOS vs BASELINE COMPARISON (30 days)')
    print('=' * 90)

    all_results = {}

    for symbol, bars, tick_size, tick_value in [
        ('ES', es_bars, 0.25, 12.50),
        ('NQ', nq_bars, 0.25, 5.00),
        ('SPY', spy_bars, 0.01, 1.00),
        ('QQQ', qqq_bars, 0.01, 1.00),
    ]:
        contracts = 3 if symbol in ['ES', 'NQ'] else 100  # Shares for equities

        print(f'\nTesting {symbol}...')

        baseline = run_baseline(bars, symbol, tick_size, tick_value, contracts)
        bos = run_entry_test(bars, symbol, tick_size, tick_value, contracts, 'BOS')
        mss = run_entry_test(bars, symbol, tick_size, tick_value, contracts, 'MSS')

        all_results[symbol] = {
            'BASELINE': baseline,
            'BOS': bos,
            'MSS': mss
        }

    # Print results
    print('\n' + '=' * 90)
    print('RESULTS BY SYMBOL')
    print('=' * 90)

    for symbol in ['ES', 'NQ', 'SPY', 'QQQ']:
        print(f'\n{symbol}:')
        print(f"{'Entry Type':<12} {'Trades':>8} {'Wins':>6} {'Losses':>7} {'Win%':>8} {'P/L':>14}")
        print('-' * 60)

        for entry_type in ['BASELINE', 'BOS', 'MSS']:
            r = all_results[symbol][entry_type]
            wr = r['wins'] / r['trades'] * 100 if r['trades'] else 0
            print(f"{entry_type:<12} {r['trades']:>8} {r['wins']:>6} {r['losses']:>7} {wr:>7.1f}% ${r['pnl']:>12,.0f}")

    # Summary comparison
    print('\n' + '=' * 90)
    print('SUMMARY: TOTAL ACROSS ALL SYMBOLS')
    print('=' * 90)

    totals = {'BASELINE': {'trades': 0, 'wins': 0, 'pnl': 0},
              'BOS': {'trades': 0, 'wins': 0, 'pnl': 0},
              'MSS': {'trades': 0, 'wins': 0, 'pnl': 0}}

    for symbol in all_results:
        for entry_type in ['BASELINE', 'BOS', 'MSS']:
            r = all_results[symbol][entry_type]
            totals[entry_type]['trades'] += r['trades']
            totals[entry_type]['wins'] += r['wins']
            totals[entry_type]['pnl'] += r['pnl']

    print(f"\n{'Entry Type':<12} {'Trades':>8} {'Wins':>6} {'Win%':>8} {'P/L':>14}")
    print('-' * 50)

    for entry_type in ['BASELINE', 'BOS', 'MSS']:
        t = totals[entry_type]
        wr = t['wins'] / t['trades'] * 100 if t['trades'] else 0
        print(f"{entry_type:<12} {t['trades']:>8} {t['wins']:>6} {wr:>7.1f}% ${t['pnl']:>12,.0f}")

    # Recommendation
    print('\n' + '=' * 90)
    print('RECOMMENDATION')
    print('=' * 90)

    best = max(totals.items(), key=lambda x: x[1]['pnl'])
    print(f"\nBest overall: {best[0]} with ${best[1]['pnl']:,.0f} P/L")

    print('\nPer-symbol best:')
    for symbol in ['ES', 'NQ', 'SPY', 'QQQ']:
        best_type = max(all_results[symbol].items(), key=lambda x: x[1]['pnl'])
        r = best_type[1]
        wr = r['wins'] / r['trades'] * 100 if r['trades'] else 0
        print(f"  {symbol}: {best_type[0]} (${r['pnl']:+,.0f}, {wr:.1f}% WR)")


if __name__ == '__main__':
    main()
