"""
Test aggressive entry strategies:
1. V5-Optimized (baseline): 1.2x displacement, enter on retracement to FVG edge
2. V6-LowDisp: 1.0x displacement, enter on retracement to FVG edge
3. V6-Aggressive: 1.0x displacement, enter at FVG creation (no retracement needed)
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


def is_displacement_candle(bar, avg_body_size, threshold):
    body_size = abs(bar.close - bar.open)
    return body_size > avg_body_size * threshold


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


def run_trade(
    session_bars,
    direction,
    fvg_num,
    tick_size=0.25,
    tick_value=12.50,
    contracts=3,
    target1_r=4,
    target2_r=8,
    stop_buffer_ticks=2,
    min_fvg_ticks=5,
    displacement_threshold=1.2,
    require_displacement=True,
    require_htf_bias=True,
    ema_fast_period=20,
    ema_slow_period=50,
    require_adx=True,
    min_adx=17,
    require_di_direction=True,
    enter_at_creation=False,  # NEW: Enter at FVG creation instead of retracement
):
    """Run trade with configurable strategy parameters."""
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'
    opposing_fvg_dir = 'BEARISH' if is_long else 'BULLISH'

    body_sizes = [abs(b.close - b.open) for b in session_bars[:50]]
    avg_body_size = sum(body_sizes) / len(body_sizes) if body_sizes else tick_size * 4

    fvg_config = {
        'min_fvg_ticks': min_fvg_ticks,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)

    candidate_fvgs = [f for f in all_fvgs if f.direction == fvg_dir]
    candidate_fvgs.sort(key=lambda f: f.created_bar_index)

    if len(candidate_fvgs) < fvg_num:
        return None

    valid_fvg_count = 0
    entry_fvg = None
    entry_bar_idx = None
    entry_time = None
    entry_price = None

    for fvg in candidate_fvgs:
        fvg.mitigated = False
        fvg.mitigation_bar_index = None

        # Displacement filter
        if require_displacement:
            if fvg.created_bar_index < len(session_bars):
                creating_bar = session_bars[fvg.created_bar_index]
                if not is_displacement_candle(creating_bar, avg_body_size, displacement_threshold):
                    continue

        edge_price = fvg.high if is_long else fvg.low
        midpoint_price = fvg.midpoint

        if enter_at_creation:
            # AGGRESSIVE: Enter at FVG creation bar close
            i = fvg.created_bar_index
            bar = session_bars[i]

            # Check filters at creation time
            bars_to_entry = session_bars[:i+1]

            # EMA filter
            if require_htf_bias:
                ema_fast = calculate_ema(bars_to_entry, ema_fast_period)
                ema_slow = calculate_ema(bars_to_entry, ema_slow_period)
                if ema_fast is not None and ema_slow is not None:
                    if is_long and ema_fast < ema_slow:
                        continue
                    if not is_long and ema_fast > ema_slow:
                        continue

            # ADX filter
            if require_adx:
                adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)
                if adx is not None:
                    if adx < min_adx:
                        continue
                    if require_di_direction:
                        if is_long and plus_di <= minus_di:
                            continue
                        if not is_long and minus_di <= plus_di:
                            continue

            valid_fvg_count += 1
            if valid_fvg_count == fvg_num:
                entry_fvg = fvg
                entry_bar_idx = i
                entry_time = bar.timestamp
                # Enter at midpoint price (aggressive entry)
                entry_price = midpoint_price
                break
        else:
            # STANDARD: Wait for retracement to FVG edge
            edge_hit_idx = None
            edge_hit_time = None
            midpoint_hit_idx = None
            midpoint_hit_time = None

            for i in range(fvg.created_bar_index + 1, len(session_bars)):
                bar = session_bars[i]

                update_fvg_mitigation(fvg, bar, i, fvg_config)

                if fvg.mitigated and edge_hit_idx is None:
                    break

                if edge_hit_idx is None and not fvg.mitigated:
                    if is_long:
                        edge_hit = bar.low <= edge_price
                    else:
                        edge_hit = bar.high >= edge_price

                    if edge_hit:
                        # EMA filter
                        if require_htf_bias:
                            bars_to_entry = session_bars[:i+1]
                            ema_fast = calculate_ema(bars_to_entry, ema_fast_period)
                            ema_slow = calculate_ema(bars_to_entry, ema_slow_period)
                            if ema_fast is not None and ema_slow is not None:
                                if is_long and ema_fast < ema_slow:
                                    continue
                                if not is_long and ema_fast > ema_slow:
                                    continue

                        # ADX filter
                        if require_adx:
                            bars_to_entry = session_bars[:i+1]
                            adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)
                            if adx is not None:
                                if adx < min_adx:
                                    continue
                                if require_di_direction:
                                    if is_long and plus_di <= minus_di:
                                        continue
                                    if not is_long and minus_di <= plus_di:
                                        continue

                        edge_hit_idx = i
                        edge_hit_time = bar.timestamp

                if edge_hit_idx is not None and midpoint_hit_idx is None and not fvg.mitigated:
                    midpoint_hit = bar.low <= midpoint_price if is_long else bar.high >= midpoint_price
                    if midpoint_hit:
                        midpoint_hit_idx = i
                        midpoint_hit_time = bar.timestamp
                        break

                if fvg.mitigated and edge_hit_idx is not None:
                    break

            if edge_hit_idx is not None:
                valid_fvg_count += 1
                if valid_fvg_count == fvg_num:
                    entry_fvg = fvg
                    # Calculate fill
                    if midpoint_hit_idx is not None:
                        entry_bar_idx = midpoint_hit_idx
                        entry_time = midpoint_hit_time
                        entry_price = (edge_price * 1 + midpoint_price * 2) / 3
                    else:
                        entry_bar_idx = edge_hit_idx
                        entry_time = edge_hit_time
                        entry_price = edge_price
                    break

    if entry_fvg is None or entry_bar_idx is None:
        return None

    # Stop with buffer
    if is_long:
        stop_price = entry_fvg.low - (stop_buffer_ticks * tick_size)
        risk = entry_price - stop_price
    else:
        stop_price = entry_fvg.high + (stop_buffer_ticks * tick_size)
        risk = stop_price - entry_price

    if risk <= 0:
        return None

    # Targets
    target_t1 = entry_price + (target1_r * risk) if is_long else entry_price - (target1_r * risk)
    target_t2 = entry_price + (target2_r * risk) if is_long else entry_price - (target2_r * risk)
    plus_4r = entry_price + (4 * risk) if is_long else entry_price - (4 * risk)

    # Position sizing
    cts_t1 = 1
    cts_t2 = 1
    cts_runner = 1

    exits = []
    remaining = contracts
    exited_t1 = False
    exited_t2 = False
    t1_touched = False
    t2_touched = False

    runner_stop = stop_price
    runner_stop_type = 'STOP'

    t1_trail_stop = stop_price
    last_swing_t1 = entry_price
    t1_buffer_ticks = 2

    t2_trail_stop = plus_4r
    last_swing_t2 = entry_price
    t2_buffer_ticks = 4

    entry_fvg.mitigated = False
    entry_fvg.mitigation_bar_index = None

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]

        # Check stop
        if (not exited_t1 and not t1_touched) or (not exited_t2 and not t2_touched):
            if is_long:
                stop_hit = bar.low <= stop_price
            else:
                stop_hit = bar.high >= stop_price

            if stop_hit:
                pnl = (stop_price - entry_price) * remaining if is_long else (entry_price - stop_price) * remaining
                exits.append({'type': 'STOP', 'pnl': pnl, 'price': stop_price, 'time': bar.timestamp, 'cts': remaining})
                remaining = 0
                break

        # T1 structure trail
        if t1_touched and not exited_t1:
            check_idx = i - 2
            if check_idx > entry_bar_idx:
                if is_long:
                    if is_swing_low(session_bars, check_idx, lookback=2):
                        swing_low = session_bars[check_idx].low
                        if swing_low > last_swing_t1:
                            new_trail = swing_low - (t1_buffer_ticks * tick_size)
                            if new_trail > t1_trail_stop:
                                t1_trail_stop = new_trail
                                last_swing_t1 = swing_low
                else:
                    if is_swing_high(session_bars, check_idx, lookback=2):
                        swing_high = session_bars[check_idx].high
                        if swing_high < last_swing_t1:
                            new_trail = swing_high + (t1_buffer_ticks * tick_size)
                            if new_trail < t1_trail_stop:
                                t1_trail_stop = new_trail
                                last_swing_t1 = swing_high

            if is_long:
                if bar.low <= t1_trail_stop:
                    pnl = (t1_trail_stop - entry_price) * cts_t1
                    exits.append({'type': 'T1_STRUCT', 'pnl': pnl, 'price': t1_trail_stop, 'time': bar.timestamp, 'cts': cts_t1})
                    remaining -= cts_t1
                    exited_t1 = True
            else:
                if bar.high >= t1_trail_stop:
                    pnl = (entry_price - t1_trail_stop) * cts_t1
                    exits.append({'type': 'T1_STRUCT', 'pnl': pnl, 'price': t1_trail_stop, 'time': bar.timestamp, 'cts': cts_t1})
                    remaining -= cts_t1
                    exited_t1 = True

        # T2 structure trail
        if t2_touched and not exited_t2 and remaining > cts_runner:
            check_idx = i - 2
            if check_idx > entry_bar_idx:
                if is_long:
                    if is_swing_low(session_bars, check_idx, lookback=2):
                        swing_low = session_bars[check_idx].low
                        if swing_low > last_swing_t2:
                            new_trail = swing_low - (t2_buffer_ticks * tick_size)
                            if new_trail > t2_trail_stop:
                                t2_trail_stop = new_trail
                                last_swing_t2 = swing_low
                else:
                    if is_swing_high(session_bars, check_idx, lookback=2):
                        swing_high = session_bars[check_idx].high
                        if swing_high < last_swing_t2:
                            new_trail = swing_high + (t2_buffer_ticks * tick_size)
                            if new_trail < t2_trail_stop:
                                t2_trail_stop = new_trail
                                last_swing_t2 = swing_high

            if is_long:
                if bar.low <= t2_trail_stop:
                    pnl = (t2_trail_stop - entry_price) * cts_t2
                    exits.append({'type': 'T2_STRUCT', 'pnl': pnl, 'price': t2_trail_stop, 'time': bar.timestamp, 'cts': cts_t2})
                    remaining -= cts_t2
                    exited_t2 = True
            else:
                if bar.high >= t2_trail_stop:
                    pnl = (entry_price - t2_trail_stop) * cts_t2
                    exits.append({'type': 'T2_STRUCT', 'pnl': pnl, 'price': t2_trail_stop, 'time': bar.timestamp, 'cts': cts_t2})
                    remaining -= cts_t2
                    exited_t2 = True

        # Runner stop
        if remaining > 0 and remaining <= cts_runner and exited_t1 and exited_t2:
            if is_long:
                if bar.low <= runner_stop:
                    pnl = (runner_stop - entry_price) * remaining
                    exits.append({'type': runner_stop_type, 'pnl': pnl, 'price': runner_stop, 'time': bar.timestamp, 'cts': remaining})
                    remaining = 0
                    break
            else:
                if bar.high >= runner_stop:
                    pnl = (entry_price - runner_stop) * remaining
                    exits.append({'type': runner_stop_type, 'pnl': pnl, 'price': runner_stop, 'time': bar.timestamp, 'cts': remaining})
                    remaining = 0
                    break

        # Check 4R touch
        if cts_t1 > 0 and not t1_touched and not exited_t1:
            t1_hit = bar.high >= target_t1 if is_long else bar.low <= target_t1
            if t1_hit:
                t1_touched = True
                t1_trail_stop = entry_price

        # Check 8R touch
        if cts_t2 > 0 and not t2_touched and remaining > cts_runner:
            t2_hit = bar.high >= target_t2 if is_long else bar.low <= target_t2
            if t2_hit:
                t2_touched = True
                runner_stop = plus_4r
                runner_stop_type = 'STOP_+4R'

        # Opposing FVG for runner
        if remaining > 0 and remaining <= cts_runner:
            opposing_fvgs = [f for f in all_fvgs if f.direction == opposing_fvg_dir
                           and f.created_bar_index > entry_bar_idx
                           and f.created_bar_index <= i]
            if opposing_fvgs:
                pnl = (bar.close - entry_price) * remaining if is_long else (entry_price - bar.close) * remaining
                exits.append({'type': 'OPP_FVG', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': remaining})
                remaining = 0

    # EOD exit
    if remaining > 0:
        last_bar = session_bars[-1]
        pnl = (last_bar.close - entry_price) * remaining if is_long else (entry_price - last_bar.close) * remaining
        exits.append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'cts': remaining})

    total_pnl = sum(e['pnl'] for e in exits)
    total_dollars = (total_pnl / tick_size) * tick_value
    was_stopped = any(e['type'] in ['STOP', 'STOP_+4R'] for e in exits)

    return {
        'direction': direction,
        'entry_time': entry_time,
        'entry_price': entry_price,
        'stop_price': stop_price,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'was_stopped': was_stopped,
        'exits': exits,
        'fvg_low': entry_fvg.low,
        'fvg_high': entry_fvg.high,
    }


def run_strategy(session_bars, strategy_name, symbol, contracts, tick_size, tick_value):
    """Run a specific strategy variant."""

    strategies = {
        'V5-Optimized': {
            'displacement_threshold': 1.2,
            'enter_at_creation': False,
        },
        'V6-LowDisp': {
            'displacement_threshold': 1.0,
            'enter_at_creation': False,
        },
        'V6-Aggressive': {
            'displacement_threshold': 1.0,
            'enter_at_creation': True,
        },
    }

    config = strategies[strategy_name]
    all_results = []
    loss_count = 0
    max_losses = 2

    for direction in ['LONG', 'SHORT']:
        if loss_count >= max_losses:
            continue

        result = run_trade(
            session_bars, direction, 1,
            tick_size=tick_size, tick_value=tick_value, contracts=contracts,
            **config
        )
        if result:
            all_results.append(result)
            if result['total_dollars'] < 0:
                loss_count += 1

            if result['was_stopped'] and loss_count < max_losses:
                result2 = run_trade(
                    session_bars, direction, 2,
                    tick_size=tick_size, tick_value=tick_value, contracts=contracts,
                    **config
                )
                if result2:
                    result2['is_reentry'] = True
                    all_results.append(result2)
                    if result2['total_dollars'] < 0:
                        loss_count += 1

    return all_results


def test_aggressive(symbol='ES', contracts=3):
    """Test aggressive entry strategies."""

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25

    print(f'Fetching {symbol} 3m data for today...')
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

    strategies = ['V5-Optimized', 'V6-LowDisp', 'V6-Aggressive']
    results = {}

    for strat in strategies:
        results[strat] = run_strategy(session_bars, strat, symbol, contracts, tick_size, tick_value)

    # Print comparison
    print('=' * 90)
    print(f'{symbol} AGGRESSIVE STRATEGY TEST - {today}')
    print('=' * 90)
    print()
    print('STRATEGY CONFIGURATIONS:')
    print('-' * 90)
    print(f'{"Strategy":<20} {"Displacement":<15} {"Entry Mode":<25}')
    print('-' * 90)
    print(f'{"V5-Optimized":<20} {"1.2x":<15} {"Retracement to FVG edge":<25}')
    print(f'{"V6-LowDisp":<20} {"1.0x":<15} {"Retracement to FVG edge":<25}')
    print(f'{"V6-Aggressive":<20} {"1.0x":<15} {"At FVG creation (no retrace)":<25}')
    print()

    print('=' * 90)
    print('RESULTS SUMMARY:')
    print('=' * 90)
    print(f'{"Strategy":<20} {"Trades":<8} {"Wins":<6} {"Losses":<8} {"Win %":<8} {"P/L":<12}')
    print('-' * 90)

    for strat in strategies:
        trades = results[strat]
        num_trades = len(trades)
        wins = sum(1 for t in trades if t['total_dollars'] > 0)
        losses = sum(1 for t in trades if t['total_dollars'] < 0)
        win_pct = (wins / num_trades * 100) if num_trades > 0 else 0
        total_pnl = sum(t['total_dollars'] for t in trades)

        print(f'{strat:<20} {num_trades:<8} {wins:<6} {losses:<8} {win_pct:<7.1f}% ${total_pnl:>+10,.2f}')

    print('=' * 90)
    print()

    # Detailed trade breakdown
    for strat in strategies:
        trades = results[strat]
        total_pnl = sum(t['total_dollars'] for t in trades)

        print(f'\n{strat} TRADES:')
        print('-' * 70)

        if not trades:
            print('  No trades (filtered out)')
        else:
            for t in trades:
                tag = ' [RE-ENTRY]' if t.get('is_reentry') else ''
                result_str = 'WIN' if t['total_dollars'] > 0 else 'LOSS'
                fvg_range = f"FVG: {t['fvg_low']:.2f}-{t['fvg_high']:.2f}"
                print(f"  {t['direction']}{tag}: Entry {t['entry_price']:.2f} @ {t['entry_time'].strftime('%H:%M')} | {fvg_range} | ${t['total_dollars']:+,.2f} ({result_str})")

        print(f'  TOTAL: ${total_pnl:+,.2f}')

    return results


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    contracts = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    test_aggressive(symbol=symbol, contracts=contracts)
