"""
ATR Buffer vs Fixed Buffer Comparison

Compares stop-loss performance between:
- Fixed buffer: $0.02 for all equities
- ATR buffer: ATR(14) × 0.5 (adaptive)

The ATR buffer should help avoid stop hunts by:
1. Wider stops during volatile periods
2. Tighter stops during quiet periods
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import (
    calculate_ema,
    calculate_adx,
    is_swing_high,
    is_swing_low,
)
from strategies.ict.signals.fvg import detect_fvgs


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

    # Simple average of recent TRs
    return sum(true_ranges[-period:]) / period


def run_backtest_with_buffer(
    session_bars,
    all_bars,
    symbol='SPY',
    risk_per_trade=500,
    use_atr_buffer=False,
    atr_multiplier=0.5,
):
    """
    Run V10 strategy with configurable stop buffer.

    Args:
        use_atr_buffer: If True, use ATR × multiplier for stop buffer
        atr_multiplier: Multiplier for ATR (0.5 = half ATR)
    """
    if not session_bars or len(session_bars) < 50:
        return []

    # Config
    min_fvg_size = 0.40 if symbol == 'QQQ' else 0.20
    min_risk = 0.50 if symbol == 'QQQ' else 0.30
    tick_size = 0.01

    fvg_config = {
        'min_fvg_ticks': int(min_fvg_size / tick_size),
        'tick_size': tick_size,
        'max_fvg_age_bars': 200,
        'invalidate_on_close_through': True
    }

    session_start = session_bars[0].timestamp
    pre_session_bars = [b for b in all_bars if b.timestamp < session_start]

    rth_start = dt_time(9, 30)
    dt_time(16, 0)
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

    if ema_20 and ema_50:
        htf_bias = 'LONG' if ema_20 > ema_50 else 'SHORT'
    else:
        htf_bias = None


    # Calculate initial ATR
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
            stop_buffer = 0.02  # Fixed buffer

        # Track swings
        if i >= 4:
            check_idx = i - 2
            if is_swing_high(session_bars, check_idx, 2):
                {'price': session_bars[check_idx].high, 'idx': check_idx}
            if is_swing_low(session_bars, check_idx, 2):
                {'price': session_bars[check_idx].low, 'idx': check_idx}

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
            if symbol == 'QQQ' and entry_hour >= 14:
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
            if symbol == 'QQQ' and entry_hour >= 14:
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

        # Type B2: Intraday Retrace (skip for SPY per V10.3)
        if symbol != 'SPY':
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
                if symbol == 'QQQ' and entry_hour >= 14:
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

    # Trade management (simplified for comparison)
    active_trades = []
    completed_results = []
    entries_taken = {'LONG': 0, 'SHORT': 0}
    loss_count = 0
    max_losses = 2
    max_open_trades = 2

    for i, bar in enumerate(session_bars):
        trades_to_remove = []

        for trade in active_trades:
            is_long = trade['direction'] == 'LONG'
            remaining = trade['remaining_shares']

            # Update trail
            if trade['touched_4r'] and not trade['touched_8r']:
                check_idx = i - 2
                if check_idx > trade['entry_bar_idx']:
                    if is_long and is_swing_low(session_bars, check_idx, 2):
                        swing = session_bars[check_idx].low
                        if swing > trade['t1_last_swing']:
                            new_trail = swing - 0.02
                            if new_trail > trade['t1_trail_stop']:
                                trade['t1_trail_stop'] = new_trail
                                trade['t1_last_swing'] = swing
                    elif not is_long and is_swing_high(session_bars, check_idx, 2):
                        swing = session_bars[check_idx].high
                        if swing < trade['t1_last_swing']:
                            new_trail = swing + 0.02
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
                        exit_shares = trade['t1_shares']
                        pnl = (trade['target_4r'] - trade['entry_price']) * exit_shares if is_long else (trade['entry_price'] - trade['target_4r']) * exit_shares
                        trade['exits'].append({'type': '4R_PARTIAL', 'pnl': pnl, 'price': trade['target_4r'], 'time': bar.timestamp, 'shares': exit_shares})
                        trade['remaining_shares'] -= exit_shares
                        trade['t1_exited'] = True
                        remaining = trade['remaining_shares']

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
                    pnl = (trade['stop_price'] - trade['entry_price']) * remaining if is_long else (trade['entry_price'] - trade['stop_price']) * remaining
                    trade['exits'].append({'type': 'STOP', 'pnl': pnl, 'price': trade['stop_price'], 'time': bar.timestamp, 'shares': remaining})
                    trade['remaining_shares'] = 0
                    loss_count += 1
                    remaining = 0

            # Trail stop after 4R
            if trade['touched_4r'] and not trade['touched_8r'] and remaining > 0:
                t1_stop_hit = bar.low <= trade['t1_trail_stop'] if is_long else bar.high >= trade['t1_trail_stop']
                if t1_stop_hit:
                    pnl = (trade['t1_trail_stop'] - trade['entry_price']) * remaining if is_long else (trade['entry_price'] - trade['t1_trail_stop']) * remaining
                    trade['exits'].append({'type': 'TRAIL_STOP', 'pnl': pnl, 'price': trade['t1_trail_stop'], 'time': bar.timestamp, 'shares': remaining})
                    trade['remaining_shares'] = 0
                    remaining = 0

            # After 8R - simplified exit
            if trade['touched_8r'] and remaining > 0:
                if not trade['t2_exited']:
                    t2_stop_hit = bar.low <= trade['t2_trail_stop'] if is_long else bar.high >= trade['t2_trail_stop']
                    if t2_stop_hit:
                        exit_shares = trade['t2_shares']
                        pnl = (trade['t2_trail_stop'] - trade['entry_price']) * exit_shares if is_long else (trade['entry_price'] - trade['t2_trail_stop']) * exit_shares
                        trade['exits'].append({'type': 'T2_STRUCT', 'pnl': pnl, 'price': trade['t2_trail_stop'], 'time': bar.timestamp, 'shares': exit_shares})
                        trade['remaining_shares'] -= exit_shares
                        trade['t2_exited'] = True
                        remaining = trade['remaining_shares']

                # Runner
                if trade['t1_exited'] and trade['t2_exited'] and remaining > 0:
                    runner_stop_hit = bar.low <= trade['runner_stop'] if is_long else bar.high >= trade['runner_stop']
                    if runner_stop_hit:
                        pnl = (trade['runner_stop'] - trade['entry_price']) * remaining if is_long else (trade['entry_price'] - trade['runner_stop']) * remaining
                        trade['exits'].append({'type': 'RUNNER_STOP', 'pnl': pnl, 'price': trade['runner_stop'], 'time': bar.timestamp, 'shares': remaining})
                        trade['remaining_shares'] = 0
                        remaining = 0

            if trade['remaining_shares'] <= 0:
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

            total_shares = int(risk_per_trade / risk)
            if total_shares < 3:
                total_shares = 3

            t1_shares = max(1, int(total_shares * 0.33))
            t2_shares = max(1, int(total_shares * 0.33))
            runner_shares = total_shares - t1_shares - t2_shares

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
                'fvg_low': entry['fvg_low'],
                'fvg_high': entry['fvg_high'],
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
                'total_shares': total_shares,
                't1_shares': t1_shares,
                't2_shares': t2_shares,
                'runner_shares': runner_shares,
                'remaining_shares': total_shares,
                'is_2nd_entry': entries_taken[direction] > 0,
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
        if trade['remaining_shares'] > 0:
            is_long = trade['direction'] == 'LONG'
            pnl = (last_bar.close - trade['entry_price']) * trade['remaining_shares'] if is_long else (trade['entry_price'] - last_bar.close) * trade['remaining_shares']
            trade['exits'].append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'shares': trade['remaining_shares']})
            trade['remaining_shares'] = 0
        completed_results.append(trade)

    # Build results
    final_results = []
    for trade in completed_results:
        if not trade.get('exits'):
            continue

        total_pnl = sum(e['pnl'] for e in trade['exits'])
        [e['type'] for e in trade['exits']]
        result = 'WIN' if total_pnl > 0 else 'LOSS'

        final_results.append({
            'direction': trade['direction'],
            'entry_type': trade['entry_type'],
            'entry_time': trade['entry_time'],
            'entry_price': trade['entry_price'],
            'stop_price': trade['stop_price'],
            'risk': trade['risk'],
            'total_shares': trade['total_shares'],
            'total_pnl': total_pnl,
            'exits': trade['exits'],
            'result': result,
            'stop_buffer': trade.get('stop_buffer'),
            'atr': trade.get('atr'),
        })

    return final_results


def run_30day_comparison(symbol='SPY', risk_per_trade=500):
    """Run 30-day comparison between fixed and ATR buffer."""
    print(f"\nFetching {symbol} data for 30-day comparison...")
    bars = fetch_futures_bars(symbol, interval='3m', n_bars=20000)

    if not bars:
        print(f"No data for {symbol}")
        return

    # Get unique dates
    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-30:] if len(all_dates) >= 30 else all_dates

    print(f"Testing {len(recent_dates)} days: {recent_dates[0]} to {recent_dates[-1]}")

    fixed_results = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0, 'stopped_out': 0}
    atr_results = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0, 'stopped_out': 0}

    detailed_comparison = []

    for day in recent_dates:
        day_bars = [b for b in bars if b.timestamp.date() == day]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Run with fixed buffer
        fixed = run_backtest_with_buffer(
            session_bars, bars, symbol=symbol,
            risk_per_trade=risk_per_trade,
            use_atr_buffer=False
        )

        # Run with ATR buffer
        atr = run_backtest_with_buffer(
            session_bars, bars, symbol=symbol,
            risk_per_trade=risk_per_trade,
            use_atr_buffer=True,
            atr_multiplier=0.5
        )

        day_fixed_pnl = sum(r['total_pnl'] for r in fixed)
        day_atr_pnl = sum(r['total_pnl'] for r in atr)

        fixed_results['trades'] += len(fixed)
        fixed_results['pnl'] += day_fixed_pnl
        fixed_results['wins'] += sum(1 for r in fixed if r['result'] == 'WIN')
        fixed_results['losses'] += sum(1 for r in fixed if r['result'] == 'LOSS')
        fixed_results['stopped_out'] += sum(1 for r in fixed if any(e['type'] == 'STOP' for e in r['exits']))

        atr_results['trades'] += len(atr)
        atr_results['pnl'] += day_atr_pnl
        atr_results['wins'] += sum(1 for r in atr if r['result'] == 'WIN')
        atr_results['losses'] += sum(1 for r in atr if r['result'] == 'LOSS')
        atr_results['stopped_out'] += sum(1 for r in atr if any(e['type'] == 'STOP' for e in r['exits']))

        # Compare individual trades
        for f_trade in fixed:
            matching_atr = None
            for a_trade in atr:
                if (a_trade['entry_time'] == f_trade['entry_time'] and
                    a_trade['direction'] == f_trade['direction']):
                    matching_atr = a_trade
                    break

            if matching_atr:
                f_stopped = any(e['type'] == 'STOP' for e in f_trade['exits'])
                a_stopped = any(e['type'] == 'STOP' for e in matching_atr['exits'])

                detailed_comparison.append({
                    'date': day,
                    'time': f_trade['entry_time'].strftime('%H:%M'),
                    'direction': f_trade['direction'],
                    'entry_type': f_trade['entry_type'],
                    'fixed_buffer': f_trade.get('stop_buffer', 0.02),
                    'atr_buffer': matching_atr.get('stop_buffer', 0),
                    'atr': matching_atr.get('atr'),
                    'fixed_pnl': f_trade['total_pnl'],
                    'atr_pnl': matching_atr['total_pnl'],
                    'fixed_stopped': f_stopped,
                    'atr_stopped': a_stopped,
                    'improvement': matching_atr['total_pnl'] - f_trade['total_pnl'],
                })

    # Print results
    print(f"\n{'='*70}")
    print(f"30-DAY COMPARISON - {symbol}")
    print(f"{'='*70}")

    print(f"\n{'Method':<15} {'Trades':>8} {'Wins':>6} {'Losses':>8} {'Win%':>8} {'Stops':>8} {'P/L':>12}")
    print(f"{'-'*70}")

    fixed_wr = fixed_results['wins'] / fixed_results['trades'] * 100 if fixed_results['trades'] > 0 else 0
    atr_wr = atr_results['wins'] / atr_results['trades'] * 100 if atr_results['trades'] > 0 else 0

    print(f"{'Fixed $0.02':<15} {fixed_results['trades']:>8} {fixed_results['wins']:>6} {fixed_results['losses']:>8} {fixed_wr:>7.1f}% {fixed_results['stopped_out']:>8} ${fixed_results['pnl']:>+10,.0f}")
    print(f"{'ATR × 0.5':<15} {atr_results['trades']:>8} {atr_results['wins']:>6} {atr_results['losses']:>8} {atr_wr:>7.1f}% {atr_results['stopped_out']:>8} ${atr_results['pnl']:>+10,.0f}")

    improvement = atr_results['pnl'] - fixed_results['pnl']
    stops_avoided = fixed_results['stopped_out'] - atr_results['stopped_out']

    print(f"\n{'='*70}")
    print("ATR BUFFER IMPACT")
    print(f"{'='*70}")
    print(f"P/L Improvement: ${improvement:+,.0f}")
    print(f"Stops Avoided: {stops_avoided}")
    print(f"Win Rate Change: {atr_wr - fixed_wr:+.1f}%")

    # Show trades where ATR buffer made biggest difference
    if detailed_comparison:
        print(f"\n{'='*70}")
        print("TOP IMPROVEMENTS (ATR buffer helped most)")
        print(f"{'='*70}")

        sorted_comp = sorted(detailed_comparison, key=lambda x: x['improvement'], reverse=True)

        for comp in sorted_comp[:5]:
            if comp['improvement'] > 0:
                print(f"\n{comp['date']} {comp['time']} {comp['direction']} ({comp['entry_type']})")
                print(f"  Fixed: ${comp['fixed_pnl']:+,.0f} (buffer=${comp['fixed_buffer']:.3f})")
                print(f"  ATR:   ${comp['atr_pnl']:+,.0f} (buffer=${comp['atr_buffer']:.3f}, ATR=${comp['atr']:.3f})")
                print(f"  Improvement: ${comp['improvement']:+,.0f}")

        print(f"\n{'='*70}")
        print("TOP REGRESSIONS (ATR buffer hurt)")
        print(f"{'='*70}")

        for comp in sorted_comp[-5:]:
            if comp['improvement'] < 0:
                print(f"\n{comp['date']} {comp['time']} {comp['direction']} ({comp['entry_type']})")
                print(f"  Fixed: ${comp['fixed_pnl']:+,.0f} (buffer=${comp['fixed_buffer']:.3f})")
                print(f"  ATR:   ${comp['atr_pnl']:+,.0f} (buffer=${comp['atr_buffer']:.3f}, ATR=${comp['atr']:.3f})")
                print(f"  Regression: ${comp['improvement']:+,.0f}")

    return {
        'fixed': fixed_results,
        'atr': atr_results,
        'improvement': improvement,
        'stops_avoided': stops_avoided,
        'details': detailed_comparison,
    }


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'SPY'

    print(f"\n{'='*70}")
    print("ATR BUFFER vs FIXED BUFFER COMPARISON")
    print(f"{'='*70}")
    print("Fixed Buffer: $0.02 (constant)")
    print("ATR Buffer: ATR(14) × 0.5 (adaptive)")
    print(f"{'='*70}")

    results = run_30day_comparison(symbol, risk_per_trade=500)
