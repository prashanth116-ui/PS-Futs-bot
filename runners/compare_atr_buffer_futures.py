"""
ATR Buffer vs Fixed Buffer Comparison - FUTURES VERSION

Compares stop-loss performance between:
- Fixed buffer: 2 ticks for all futures
- ATR buffer: ATR(14) × 0.5 (adaptive)

Futures have different tick values:
- ES: $12.50/tick (0.25 pts)
- NQ: $5.00/tick (0.25 pts)
- MES: $1.25/tick (0.25 pts)
- MNQ: $0.50/tick (0.25 pts)
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time, timedelta
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import (
    calculate_ema,
    calculate_adx,
    is_swing_high,
    is_swing_low,
)
from strategies.ict.signals.fvg import detect_fvgs


# Futures configuration
FUTURES_CONFIG = {
    'ES': {'tick_size': 0.25, 'tick_value': 12.50, 'min_fvg_ticks': 5, 'min_risk_pts': 1.5, 'max_bos_risk': 8.0},
    'NQ': {'tick_size': 0.25, 'tick_value': 5.00, 'min_fvg_ticks': 5, 'min_risk_pts': 6.0, 'max_bos_risk': 20.0},
    'MES': {'tick_size': 0.25, 'tick_value': 1.25, 'min_fvg_ticks': 5, 'min_risk_pts': 1.5, 'max_bos_risk': 8.0},
    'MNQ': {'tick_size': 0.25, 'tick_value': 0.50, 'min_fvg_ticks': 5, 'min_risk_pts': 6.0, 'max_bos_risk': 20.0},
}


def calculate_atr(bars, period=14):
    """Calculate Average True Range."""
    if len(bars) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        prev_close = bars[i-1].close

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    return sum(true_ranges[-period:]) / period


def run_backtest_with_buffer_futures(
    session_bars,
    all_bars,
    symbol='ES',
    contracts=3,
    use_atr_buffer=False,
    atr_multiplier=0.5,
):
    """
    Run V10 strategy on futures with configurable stop buffer.
    """
    if not session_bars or len(session_bars) < 50:
        return []

    config = FUTURES_CONFIG.get(symbol, FUTURES_CONFIG['ES'])
    tick_size = config['tick_size']
    tick_value = config['tick_value']
    min_fvg_ticks = config['min_fvg_ticks']
    min_risk = config['min_risk_pts']
    max_bos_risk = config['max_bos_risk']

    # Fixed buffer = 2 ticks
    fixed_buffer_pts = 2 * tick_size  # 0.50 pts for ES/NQ

    fvg_config = {
        'min_fvg_ticks': min_fvg_ticks,
        'tick_size': tick_size,
        'max_fvg_age_bars': 200,
        'invalidate_on_close_through': True
    }

    session_start = session_bars[0].timestamp
    pre_session_bars = [b for b in all_bars if b.timestamp < session_start]

    rth_start = dt_time(9, 30)
    morning_end = dt_time(12, 0)

    all_fvgs = detect_fvgs(all_bars, fvg_config)

    overnight_fvgs = []
    session_fvgs = []
    all_valid_entries = []

    for fvg in all_fvgs:
        fvg_time = fvg.created_at.time() if hasattr(fvg, 'created_at') else None
        direction = 'LONG' if fvg.direction == 'BULLISH' else 'SHORT'
        fvg_dict = {
            'direction': direction,
            'low': fvg.low,
            'high': fvg.high,
            'created_at': fvg.created_at,
            'is_overnight': fvg_time and fvg_time < rth_start if fvg_time else False,
            'used_for_entry': False,
            'creation_bar_idx': next((i for i, b in enumerate(session_bars) if b.timestamp >= fvg.created_at), 0),
        }
        if fvg_dict['is_overnight']:
            overnight_fvgs.append(fvg_dict)
        else:
            session_fvgs.append(fvg_dict)

    # Initial indicators
    indicator_bars = pre_session_bars[-100:] if len(pre_session_bars) >= 100 else pre_session_bars
    ema_20 = calculate_ema(indicator_bars, 20) if len(indicator_bars) >= 20 else None
    ema_50 = calculate_ema(indicator_bars, 50) if len(indicator_bars) >= 50 else None
    adx, plus_di, minus_di = calculate_adx(indicator_bars, 14) if len(indicator_bars) >= 28 else (None, None, None)

    htf_bias = 'LONG' if ema_20 and ema_50 and ema_20 > ema_50 else 'SHORT' if ema_20 and ema_50 else None

    recent_swing_high = None
    recent_swing_low = None
    current_atr = calculate_atr(indicator_bars, 14)

    for i, bar in enumerate(session_bars):
        bar_time = bar.timestamp.time()

        # Update indicators every 5 bars
        if i % 5 == 0:
            bars_to_now = [b for b in all_bars if b.timestamp <= bar.timestamp][-100:]
            ema_20 = calculate_ema(bars_to_now, 20)
            ema_50 = calculate_ema(bars_to_now, 50)
            adx, plus_di, minus_di = calculate_adx(bars_to_now, 14)
            current_atr = calculate_atr(bars_to_now, 14)
            if ema_20 and ema_50:
                htf_bias = 'LONG' if ema_20 > ema_50 else 'SHORT'

        # Calculate stop buffer
        if use_atr_buffer and current_atr:
            stop_buffer = current_atr * atr_multiplier
        else:
            stop_buffer = fixed_buffer_pts

        # Track swings
        if i >= 4:
            check_idx = i - 2
            if is_swing_high(session_bars, check_idx, 2):
                recent_swing_high = {'price': session_bars[check_idx].high, 'idx': check_idx}
            if is_swing_low(session_bars, check_idx, 2):
                recent_swing_low = {'price': session_bars[check_idx].low, 'idx': check_idx}

        if bar_time < rth_start:
            continue

        # Type A: Creation Entry
        for fvg in session_fvgs:
            if fvg['used_for_entry']:
                continue
            if abs(fvg['creation_bar_idx'] - i) > 2:
                continue

            direction = fvg['direction']

            if adx is None or adx < 17:
                continue
            if htf_bias and htf_bias != direction:
                continue
            if plus_di and minus_di:
                if direction == 'LONG' and plus_di < minus_di:
                    continue
                if direction == 'SHORT' and minus_di < plus_di:
                    continue

            if i >= 1:
                prev_bar = session_bars[i-1]
                body = abs(prev_bar.close - prev_bar.open)
                avg_body = sum(abs(b.close - b.open) for b in session_bars[max(0,i-10):i]) / min(10, i) if i > 0 else body
                if body < avg_body * 1.0:
                    continue

            entry_price = (fvg['low'] + fvg['high']) / 2
            if direction == 'LONG':
                stop_price = fvg['low'] - stop_buffer
            else:
                stop_price = fvg['high'] + stop_buffer

            risk = abs(entry_price - stop_price)
            if risk < min_risk:
                continue

            entry_hour = bar.timestamp.hour
            if 12 <= entry_hour < 14:
                continue
            if symbol in ['NQ', 'MNQ'] and entry_hour >= 14:
                continue

            fvg['used_for_entry'] = True
            all_valid_entries.append({
                'entry_type': 'CREATION',
                'direction': direction,
                'entry_bar_idx': i,
                'entry_time': bar.timestamp,
                'entry_price': entry_price,
                'stop_price': stop_price,
                'fvg_low': fvg['low'],
                'fvg_high': fvg['high'],
                'risk': risk,
                'stop_buffer': stop_buffer,
                'atr': current_atr,
            })

        # Type B1: Overnight Retrace
        for fvg in overnight_fvgs:
            if fvg['used_for_entry']:
                continue

            direction = fvg['direction']
            fvg_mid = (fvg['low'] + fvg['high']) / 2

            if bar_time > morning_end:
                continue
            if adx is None or adx < 22:
                continue

            in_fvg = False
            if direction == 'LONG' and bar.low <= fvg['high'] and bar.close > fvg['low']:
                in_fvg = True
            elif direction == 'SHORT' and bar.high >= fvg['low'] and bar.close < fvg['high']:
                in_fvg = True

            if not in_fvg:
                continue

            body = abs(bar.close - bar.open)
            wick = bar.high - max(bar.close, bar.open) if direction == 'SHORT' else min(bar.close, bar.open) - bar.low
            if wick <= body:
                continue

            entry_price = fvg_mid
            if direction == 'LONG':
                stop_price = bar.low - stop_buffer
            else:
                stop_price = bar.high + stop_buffer

            risk = abs(entry_price - stop_price)
            if risk < min_risk:
                continue

            entry_hour = bar.timestamp.hour
            if 12 <= entry_hour < 14:
                continue
            if symbol in ['NQ', 'MNQ'] and entry_hour >= 14:
                continue

            fvg['used_for_entry'] = True
            all_valid_entries.append({
                'entry_type': 'RETRACEMENT',
                'direction': direction,
                'entry_bar_idx': i,
                'entry_time': bar.timestamp,
                'entry_price': entry_price,
                'stop_price': stop_price,
                'fvg_low': fvg['low'],
                'fvg_high': fvg['high'],
                'risk': risk,
                'stop_buffer': stop_buffer,
                'atr': current_atr,
            })

        # Type B2: Intraday Retrace
        for fvg in session_fvgs:
            if fvg['used_for_entry']:
                continue
            if i - fvg['creation_bar_idx'] < 5:
                continue

            direction = fvg['direction']
            fvg_mid = (fvg['low'] + fvg['high']) / 2

            if htf_bias and htf_bias != direction:
                continue
            if plus_di and minus_di:
                if direction == 'LONG' and plus_di < minus_di:
                    continue
                if direction == 'SHORT' and minus_di < plus_di:
                    continue

            in_fvg = False
            if direction == 'LONG' and bar.low <= fvg['high'] and bar.close > fvg['low']:
                in_fvg = True
            elif direction == 'SHORT' and bar.high >= fvg['low'] and bar.close < fvg['high']:
                in_fvg = True

            if not in_fvg:
                continue

            body = abs(bar.close - bar.open)
            wick = bar.high - max(bar.close, bar.open) if direction == 'SHORT' else min(bar.close, bar.open) - bar.low
            if wick <= body:
                continue

            entry_price = fvg_mid
            if direction == 'LONG':
                stop_price = bar.low - stop_buffer
            else:
                stop_price = bar.high + stop_buffer

            risk = abs(entry_price - stop_price)
            if risk < min_risk:
                continue

            entry_hour = bar.timestamp.hour
            if 12 <= entry_hour < 14:
                continue
            if symbol in ['NQ', 'MNQ'] and entry_hour >= 14:
                continue

            fvg['used_for_entry'] = True
            all_valid_entries.append({
                'entry_type': 'INTRADAY',
                'direction': direction,
                'entry_bar_idx': i,
                'entry_time': bar.timestamp,
                'entry_price': entry_price,
                'stop_price': stop_price,
                'fvg_low': fvg['low'],
                'fvg_high': fvg['high'],
                'risk': risk,
                'stop_buffer': stop_buffer,
                'atr': current_atr,
            })

        # Type C: BOS
        if recent_swing_high and bar.high > recent_swing_high['price']:
            for fvg in session_fvgs:
                if fvg['used_for_entry']:
                    continue
                if fvg['direction'] != 'LONG':
                    continue
                if fvg['creation_bar_idx'] < recent_swing_high['idx']:
                    continue
                if i - fvg['creation_bar_idx'] > 5:
                    continue

                entry_price = (fvg['low'] + fvg['high']) / 2
                stop_price = fvg['low'] - stop_buffer
                risk = abs(entry_price - stop_price)

                if risk < min_risk or risk > max_bos_risk:
                    continue

                entry_hour = bar.timestamp.hour
                if 12 <= entry_hour < 14:
                    continue
                if symbol in ['NQ', 'MNQ'] and entry_hour >= 14:
                    continue

                fvg['used_for_entry'] = True
                all_valid_entries.append({
                    'entry_type': 'BOS',
                    'direction': 'LONG',
                    'entry_bar_idx': i,
                    'entry_time': bar.timestamp,
                    'entry_price': entry_price,
                    'stop_price': stop_price,
                    'fvg_low': fvg['low'],
                    'fvg_high': fvg['high'],
                    'risk': risk,
                    'stop_buffer': stop_buffer,
                    'atr': current_atr,
                })

            recent_swing_high = None

        if recent_swing_low and bar.low < recent_swing_low['price']:
            for fvg in session_fvgs:
                if fvg['used_for_entry']:
                    continue
                if fvg['direction'] != 'SHORT':
                    continue
                if fvg['creation_bar_idx'] < recent_swing_low['idx']:
                    continue
                if i - fvg['creation_bar_idx'] > 5:
                    continue

                entry_price = (fvg['low'] + fvg['high']) / 2
                stop_price = fvg['high'] + stop_buffer
                risk = abs(entry_price - stop_price)

                if risk < min_risk or risk > max_bos_risk:
                    continue

                entry_hour = bar.timestamp.hour
                if 12 <= entry_hour < 14:
                    continue
                if symbol in ['NQ', 'MNQ'] and entry_hour >= 14:
                    continue

                fvg['used_for_entry'] = True
                all_valid_entries.append({
                    'entry_type': 'BOS',
                    'direction': 'SHORT',
                    'entry_bar_idx': i,
                    'entry_time': bar.timestamp,
                    'entry_price': entry_price,
                    'stop_price': stop_price,
                    'fvg_low': fvg['low'],
                    'fvg_high': fvg['high'],
                    'risk': risk,
                    'stop_buffer': stop_buffer,
                    'atr': current_atr,
                })

            recent_swing_low = None

    # Trade management
    active_trades = []
    completed_results = []
    entries_taken = {'LONG': 0, 'SHORT': 0}
    loss_count = 0
    max_losses = 2
    max_open_trades = 2

    # Trail buffers in points (4 ticks, 6 ticks)
    trail_buffer_t2 = 4 * tick_size
    trail_buffer_runner = 6 * tick_size

    for i, bar in enumerate(session_bars):
        trades_to_remove = []

        for trade in active_trades:
            is_long = trade['direction'] == 'LONG'
            remaining = trade['remaining_contracts']

            # Update trails
            if trade['touched_4r'] and not trade['touched_8r']:
                check_idx = i - 2
                if check_idx > trade['entry_bar_idx']:
                    if is_long and is_swing_low(session_bars, check_idx, 2):
                        swing = session_bars[check_idx].low
                        if swing > trade['t1_last_swing']:
                            new_trail = swing - trail_buffer_t2
                            if new_trail > trade['t1_trail_stop']:
                                trade['t1_trail_stop'] = new_trail
                                trade['t1_last_swing'] = swing
                    elif not is_long and is_swing_high(session_bars, check_idx, 2):
                        swing = session_bars[check_idx].high
                        if swing < trade['t1_last_swing']:
                            new_trail = swing + trail_buffer_t2
                            if new_trail < trade['t1_trail_stop']:
                                trade['t1_trail_stop'] = new_trail
                                trade['t1_last_swing'] = swing

            # Check 4R
            if not trade['touched_4r']:
                t4r_hit = bar.high >= trade['target_4r'] if is_long else bar.low <= trade['target_4r']
                if t4r_hit:
                    trade['touched_4r'] = True
                    trade['t1_trail_stop'] = trade['entry_price']
                    trade['t1_last_swing'] = trade['entry_price']

                    # Take T1 at 4R
                    if not trade['t1_exited'] and remaining > 0:
                        exit_contracts = 1
                        pnl_pts = (trade['target_4r'] - trade['entry_price']) if is_long else (trade['entry_price'] - trade['target_4r'])
                        pnl_ticks = pnl_pts / tick_size
                        pnl_dollars = pnl_ticks * tick_value * exit_contracts
                        trade['exits'].append({'type': '4R_PARTIAL', 'pnl': pnl_dollars, 'price': trade['target_4r'], 'time': bar.timestamp})
                        trade['remaining_contracts'] -= exit_contracts
                        trade['t1_exited'] = True
                        remaining = trade['remaining_contracts']

            # Check 8R
            if trade['touched_4r'] and not trade['touched_8r']:
                t8r_hit = bar.high >= trade['target_8r'] if is_long else bar.low <= trade['target_8r']
                if t8r_hit:
                    trade['touched_8r'] = True
                    trade['t2_trail_stop'] = trade['plus_4r']
                    trade['runner_stop'] = trade['plus_4r']

            # Check stops
            if not trade['touched_4r'] and remaining > 0:
                stop_hit = bar.low <= trade['stop_price'] if is_long else bar.high >= trade['stop_price']
                if stop_hit:
                    pnl_pts = (trade['stop_price'] - trade['entry_price']) if is_long else (trade['entry_price'] - trade['stop_price'])
                    pnl_ticks = pnl_pts / tick_size
                    pnl_dollars = pnl_ticks * tick_value * remaining
                    trade['exits'].append({'type': 'STOP', 'pnl': pnl_dollars, 'price': trade['stop_price'], 'time': bar.timestamp})
                    trade['remaining_contracts'] = 0
                    loss_count += 1
                    remaining = 0

            # Trail stop after 4R
            if trade['touched_4r'] and not trade['touched_8r'] and remaining > 0:
                t1_stop_hit = bar.low <= trade['t1_trail_stop'] if is_long else bar.high >= trade['t1_trail_stop']
                if t1_stop_hit:
                    pnl_pts = (trade['t1_trail_stop'] - trade['entry_price']) if is_long else (trade['entry_price'] - trade['t1_trail_stop'])
                    pnl_ticks = pnl_pts / tick_size
                    pnl_dollars = pnl_ticks * tick_value * remaining
                    trade['exits'].append({'type': 'TRAIL_STOP', 'pnl': pnl_dollars, 'price': trade['t1_trail_stop'], 'time': bar.timestamp})
                    trade['remaining_contracts'] = 0
                    remaining = 0

            # After 8R
            if trade['touched_8r'] and remaining > 0:
                if not trade['t2_exited'] and remaining > 1:
                    t2_stop_hit = bar.low <= trade['t2_trail_stop'] if is_long else bar.high >= trade['t2_trail_stop']
                    if t2_stop_hit:
                        exit_contracts = 1
                        pnl_pts = (trade['t2_trail_stop'] - trade['entry_price']) if is_long else (trade['entry_price'] - trade['t2_trail_stop'])
                        pnl_ticks = pnl_pts / tick_size
                        pnl_dollars = pnl_ticks * tick_value * exit_contracts
                        trade['exits'].append({'type': 'T2_STRUCT', 'pnl': pnl_dollars, 'price': trade['t2_trail_stop'], 'time': bar.timestamp})
                        trade['remaining_contracts'] -= exit_contracts
                        trade['t2_exited'] = True
                        remaining = trade['remaining_contracts']

                if trade['t1_exited'] and trade['t2_exited'] and remaining > 0:
                    runner_stop_hit = bar.low <= trade['runner_stop'] if is_long else bar.high >= trade['runner_stop']
                    if runner_stop_hit:
                        pnl_pts = (trade['runner_stop'] - trade['entry_price']) if is_long else (trade['entry_price'] - trade['runner_stop'])
                        pnl_ticks = pnl_pts / tick_size
                        pnl_dollars = pnl_ticks * tick_value * remaining
                        trade['exits'].append({'type': 'RUNNER_STOP', 'pnl': pnl_dollars, 'price': trade['runner_stop'], 'time': bar.timestamp})
                        trade['remaining_contracts'] = 0
                        remaining = 0

            if trade['remaining_contracts'] <= 0:
                trades_to_remove.append(trade)

        for trade in trades_to_remove:
            if trade in active_trades:
                active_trades.remove(trade)
                completed_results.append(trade)

        # New entries
        if loss_count >= max_losses:
            continue

        current_open = len(active_trades)

        for entry in all_valid_entries:
            if entry['entry_bar_idx'] != i:
                continue

            direction = entry['direction']

            if current_open >= max_open_trades:
                continue
            if entries_taken[direction] >= 2:
                continue

            is_long = direction == 'LONG'
            entry_price = entry['entry_price']
            stop_price = entry['stop_price']
            risk = abs(entry_price - stop_price)

            target_4r = entry_price + (4 * risk) if is_long else entry_price - (4 * risk)
            target_8r = entry_price + (8 * risk) if is_long else entry_price - (8 * risk)
            plus_4r = target_4r

            new_trade = {
                'direction': direction,
                'entry_type': entry['entry_type'],
                'entry_bar_idx': i,
                'entry_time': entry['entry_time'],
                'entry_price': entry_price,
                'stop_price': stop_price,
                'risk': risk,
                'target_4r': target_4r,
                'target_8r': target_8r,
                'plus_4r': plus_4r,
                'touched_4r': False,
                'touched_8r': False,
                't1_trail_stop': stop_price,
                't1_last_swing': entry_price,
                't1_exited': False,
                't2_trail_stop': plus_4r,
                't2_exited': False,
                'runner_stop': plus_4r,
                'total_contracts': contracts,
                'remaining_contracts': contracts,
                'exits': [],
                'stop_buffer': entry['stop_buffer'],
                'atr': entry.get('atr'),
            }

            active_trades.append(new_trade)
            entries_taken[direction] += 1
            current_open += 1

    # EOD exit
    last_bar = session_bars[-1]
    for trade in active_trades:
        if trade['remaining_contracts'] > 0:
            is_long = trade['direction'] == 'LONG'
            pnl_pts = (last_bar.close - trade['entry_price']) if is_long else (trade['entry_price'] - last_bar.close)
            pnl_ticks = pnl_pts / tick_size
            pnl_dollars = pnl_ticks * tick_value * trade['remaining_contracts']
            trade['exits'].append({'type': 'EOD', 'pnl': pnl_dollars, 'price': last_bar.close, 'time': last_bar.timestamp})
            trade['remaining_contracts'] = 0
        completed_results.append(trade)

    # Build results
    final_results = []
    for trade in completed_results:
        if not trade.get('exits'):
            continue

        total_pnl = sum(e['pnl'] for e in trade['exits'])
        result = 'WIN' if total_pnl > 0 else 'LOSS'

        final_results.append({
            'direction': trade['direction'],
            'entry_type': trade['entry_type'],
            'entry_time': trade['entry_time'],
            'entry_price': trade['entry_price'],
            'stop_price': trade['stop_price'],
            'risk': trade['risk'],
            'total_pnl': total_pnl,
            'exits': trade['exits'],
            'result': result,
            'stop_buffer': trade.get('stop_buffer'),
            'atr': trade.get('atr'),
        })

    return final_results


def run_comparison(symbol='ES', contracts=3, days=13):
    """Run comparison for a futures symbol."""
    print(f"\nFetching {symbol} data for {days}-day comparison...")
    bars = fetch_futures_bars(symbol, interval='3m', n_bars=20000)

    if not bars:
        print(f"No data for {symbol}")
        return None

    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:] if len(all_dates) >= days else all_dates

    print(f"Testing {len(recent_dates)} days: {recent_dates[0]} to {recent_dates[-1]}")

    fixed_results = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0, 'stopped_out': 0}
    atr_results = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0, 'stopped_out': 0}

    for day in recent_dates:
        day_bars = [b for b in bars if b.timestamp.date() == day]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Fixed buffer
        fixed = run_backtest_with_buffer_futures(
            session_bars, bars, symbol=symbol,
            contracts=contracts,
            use_atr_buffer=False
        )

        # ATR buffer
        atr = run_backtest_with_buffer_futures(
            session_bars, bars, symbol=symbol,
            contracts=contracts,
            use_atr_buffer=True,
            atr_multiplier=0.5
        )

        fixed_results['trades'] += len(fixed)
        fixed_results['pnl'] += sum(r['total_pnl'] for r in fixed)
        fixed_results['wins'] += sum(1 for r in fixed if r['result'] == 'WIN')
        fixed_results['losses'] += sum(1 for r in fixed if r['result'] == 'LOSS')
        fixed_results['stopped_out'] += sum(1 for r in fixed if any(e['type'] == 'STOP' for e in r['exits']))

        atr_results['trades'] += len(atr)
        atr_results['pnl'] += sum(r['total_pnl'] for r in atr)
        atr_results['wins'] += sum(1 for r in atr if r['result'] == 'WIN')
        atr_results['losses'] += sum(1 for r in atr if r['result'] == 'LOSS')
        atr_results['stopped_out'] += sum(1 for r in atr if any(e['type'] == 'STOP' for e in r['exits']))

    return {'fixed': fixed_results, 'atr': atr_results}


def main():
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ['ES', 'NQ', 'MES', 'MNQ']
    days = 13

    print(f"\n{'='*70}")
    print(f"ATR BUFFER vs FIXED BUFFER - FUTURES COMPARISON")
    print(f"{'='*70}")
    print(f"Fixed Buffer: 2 ticks (0.50 pts)")
    print(f"ATR Buffer: ATR(14) x 0.5 (adaptive)")
    print(f"{'='*70}")

    all_results = {}

    for symbol in symbols:
        contracts = 3
        result = run_comparison(symbol, contracts, days)
        if result:
            all_results[symbol] = result

    # Summary table
    print(f"\n{'='*70}")
    print(f"{days}-DAY COMPARISON SUMMARY")
    print(f"{'='*70}")
    print(f"\n{'Symbol':<8} {'Method':<12} {'Trades':>8} {'Wins':>6} {'Losses':>8} {'Win%':>8} {'Stops':>8} {'P/L':>12}")
    print(f"{'-'*70}")

    total_fixed_pnl = 0
    total_atr_pnl = 0

    for symbol, result in all_results.items():
        fixed = result['fixed']
        atr = result['atr']

        fixed_wr = fixed['wins'] / fixed['trades'] * 100 if fixed['trades'] > 0 else 0
        atr_wr = atr['wins'] / atr['trades'] * 100 if atr['trades'] > 0 else 0

        print(f"{symbol:<8} {'Fixed':<12} {fixed['trades']:>8} {fixed['wins']:>6} {fixed['losses']:>8} {fixed_wr:>7.1f}% {fixed['stopped_out']:>8} ${fixed['pnl']:>+10,.0f}")
        print(f"{'':<8} {'ATR x 0.5':<12} {atr['trades']:>8} {atr['wins']:>6} {atr['losses']:>8} {atr_wr:>7.1f}% {atr['stopped_out']:>8} ${atr['pnl']:>+10,.0f}")
        print()

        total_fixed_pnl += fixed['pnl']
        total_atr_pnl += atr['pnl']

    print(f"{'='*70}")
    print(f"TOTAL IMPACT")
    print(f"{'='*70}")
    print(f"Fixed Total: ${total_fixed_pnl:+,.0f}")
    print(f"ATR Total:   ${total_atr_pnl:+,.0f}")
    print(f"Improvement: ${total_atr_pnl - total_fixed_pnl:+,.0f}")


if __name__ == "__main__":
    main()
