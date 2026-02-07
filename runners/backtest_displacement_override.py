"""
Backtest comparison: Baseline V10 vs High-Displacement Override (3x).

Tests the hypothesis that skipping ADX filter for 3x+ displacement
Creation entries would improve results.
"""
import sys
sys.path.insert(0, '.')

from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs
from datetime import datetime, timedelta, time as dt_time
from runners.run_v10_dual_entry import calculate_ema, calculate_adx


def run_session_with_override(
    session_bars,
    all_bars,
    tick_size=0.25,
    tick_value=12.50,
    contracts=3,
    min_risk_pts=1.5,
    max_bos_risk_pts=8.0,
    min_adx=17,
    displacement_threshold=1.0,
    high_displacement_override=None,  # NEW: Skip ADX if displacement >= this
    symbol='ES',
):
    """
    Modified V10 strategy with optional high-displacement ADX override.

    If high_displacement_override is set (e.g., 3.0), Creation entries with
    displacement >= 3x avg body will skip the ADX check.
    """
    from runners.run_v10_dual_entry import (
        is_swing_high, is_swing_low, detect_bos
    )

    # Build mappings
    session_to_all_idx = {}
    all_to_session_idx = {}
    for i, sbar in enumerate(session_bars):
        for j, abar in enumerate(all_bars):
            if abar.timestamp == sbar.timestamp:
                session_to_all_idx[i] = j
                all_to_session_idx[j] = i
                break

    # Calculate avg body from first 50 session bars
    body_sizes = [abs(b.close - b.open) for b in session_bars[:50]]
    avg_body_size = sum(body_sizes) / len(body_sizes) if body_sizes else tick_size * 4

    # Detect FVGs
    fvg_config = {
        'min_fvg_ticks': 2,
        'tick_size': tick_size,
        'max_fvg_age_bars': 200,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(all_bars, fvg_config)

    valid_entries = {'LONG': [], 'SHORT': []}

    # === CREATION ENTRIES (with optional high-displacement override) ===
    for direction in ['LONG', 'SHORT']:
        is_long = direction == 'LONG'
        fvg_dir = 'BULLISH' if is_long else 'BEARISH'

        for fvg in all_fvgs:
            if fvg.direction != fvg_dir:
                continue

            session_bar_idx = all_to_session_idx.get(fvg.created_bar_index)
            if session_bar_idx is None:
                continue

            fvg_size_ticks = (fvg.high - fvg.low) / tick_size
            if fvg_size_ticks < 5:
                continue

            creating_bar = all_bars[fvg.created_bar_index]
            body = abs(creating_bar.close - creating_bar.open)

            if body <= avg_body_size * displacement_threshold:
                continue

            # Calculate displacement ratio
            displacement_ratio = body / avg_body_size if avg_body_size > 0 else 0

            bars_to_entry = all_bars[:fvg.created_bar_index + 1]
            ema_fast = calculate_ema(bars_to_entry, 20)
            ema_slow = calculate_ema(bars_to_entry, 50)
            adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)

            ema_ok = ema_fast is None or ema_slow is None or (ema_fast > ema_slow if is_long else ema_fast < ema_slow)
            di_ok = adx is None or (plus_di > minus_di if is_long else minus_di > plus_di)

            # ADX check with optional high-displacement override
            if high_displacement_override and displacement_ratio >= high_displacement_override:
                adx_ok = True  # Skip ADX check for high displacement
            else:
                adx_ok = adx is None or adx >= min_adx

            if ema_ok and adx_ok and di_ok:
                entry_price = fvg.midpoint
                stop_price = fvg.low - (2 * tick_size) if is_long else fvg.high + (2 * tick_size)
                risk = abs(entry_price - stop_price)

                if min_risk_pts > 0 and risk < min_risk_pts:
                    continue

                entry_hour = creating_bar.timestamp.hour
                if 12 <= entry_hour < 14:
                    continue
                if symbol in ['NQ', 'MNQ'] and entry_hour >= 14:
                    continue

                valid_entries[direction].append({
                    'fvg': fvg,
                    'direction': direction,
                    'entry_type': 'CREATION',
                    'entry_bar_idx': session_bar_idx,
                    'entry_time': creating_bar.timestamp,
                    'entry_price': entry_price,
                    'stop_price': stop_price,
                    'fvg_low': fvg.low,
                    'fvg_high': fvg.high,
                    'displacement_ratio': displacement_ratio,
                })

    # === RETRACEMENT ENTRIES (unchanged - always require ADX) ===
    rth_start = dt_time(9, 30)
    overnight_fvgs = [f for f in all_fvgs if all_bars[f.created_bar_index].timestamp.time() < rth_start]
    session_fvgs = [f for f in all_fvgs if all_bars[f.created_bar_index].timestamp.time() >= rth_start]

    for i, bar in enumerate(session_bars):
        if i < 1:
            continue
        if bar.timestamp.time() < rth_start:
            continue

        all_bar_idx = session_to_all_idx.get(i, i)

        for direction in ['LONG', 'SHORT']:
            is_long = direction == 'LONG'
            fvg_dir = 'BULLISH' if is_long else 'BEARISH'

            # Check overnight FVGs
            for fvg in overnight_fvgs:
                if fvg.direction != fvg_dir or fvg.mitigated:
                    continue

                touched = (bar.low <= fvg.high and bar.high >= fvg.low)
                if not touched:
                    continue

                prev_bar = session_bars[i-1]
                rejection = (is_long and bar.close > prev_bar.close) or (not is_long and bar.close < prev_bar.close)
                if not rejection:
                    continue

                bars_to_entry = all_bars[:all_bar_idx + 1]
                ema_fast = calculate_ema(bars_to_entry, 20)
                ema_slow = calculate_ema(bars_to_entry, 50)
                adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)

                ema_ok = ema_fast is None or ema_slow is None or (ema_fast > ema_slow if is_long else ema_fast < ema_slow)
                adx_ok = adx is None or adx >= 22  # Overnight needs ADX >= 22
                di_ok = adx is None or (plus_di > minus_di if is_long else minus_di > plus_di)

                if ema_ok and adx_ok and di_ok:
                    entry_price = fvg.midpoint
                    stop_price = fvg.low - (2 * tick_size) if is_long else fvg.high + (2 * tick_size)
                    risk = abs(entry_price - stop_price)

                    if min_risk_pts > 0 and risk < min_risk_pts:
                        continue

                    entry_hour = bar.timestamp.hour
                    if 12 <= entry_hour < 14:
                        continue

                    valid_entries[direction].append({
                        'fvg': fvg,
                        'direction': direction,
                        'entry_type': 'RETRACEMENT',
                        'entry_bar_idx': i,
                        'entry_time': bar.timestamp,
                        'entry_price': entry_price,
                        'stop_price': stop_price,
                        'fvg_low': fvg.low,
                        'fvg_high': fvg.high,
                    })
                    break

    # Combine and sort entries
    all_valid_entries = valid_entries['LONG'] + valid_entries['SHORT']
    all_valid_entries.sort(key=lambda x: x['entry_bar_idx'])

    # === TRADE EXECUTION (simplified) ===
    active_trades = []
    completed_results = []
    entries_taken = {'LONG': 0, 'SHORT': 0}

    for i in range(len(session_bars)):
        bar = session_bars[i]

        # Manage active trades
        for trade in list(active_trades):
            is_long = trade['direction'] == 'LONG'

            # Check stop
            if (is_long and bar.low <= trade['stop_price']) or (not is_long and bar.high >= trade['stop_price']):
                pnl = (trade['stop_price'] - trade['entry_price']) if is_long else (trade['entry_price'] - trade['stop_price'])
                trade['exits'] = [{'type': 'STOP', 'pnl': pnl * contracts, 'price': trade['stop_price'], 'time': bar.timestamp, 'cts': contracts}]
                trade['exit_bar_idx'] = i
                completed_results.append(trade)
                active_trades.remove(trade)
                continue

            # Check 4R target
            risk = abs(trade['entry_price'] - trade['stop_price'])
            target_4r = trade['entry_price'] + (4 * risk) if is_long else trade['entry_price'] - (4 * risk)

            if (is_long and bar.high >= target_4r) or (not is_long and bar.low <= target_4r):
                if not trade.get('hit_4r'):
                    trade['hit_4r'] = True
                    # Take 1 ct at 4R
                    pnl_4r = (target_4r - trade['entry_price']) if is_long else (trade['entry_price'] - target_4r)
                    trade['partial_pnl'] = pnl_4r

            # Simple exit: if hit 4R, trail stop to entry
            if trade.get('hit_4r'):
                if (is_long and bar.low <= trade['entry_price']) or (not is_long and bar.high >= trade['entry_price']):
                    pnl = trade['partial_pnl'] + 0  # 1 ct at 4R, 2 ct at entry
                    trade['exits'] = [
                        {'type': '4R_PARTIAL', 'pnl': trade['partial_pnl'], 'price': target_4r, 'time': bar.timestamp, 'cts': 1},
                        {'type': 'TRAIL_STOP', 'pnl': 0, 'price': trade['entry_price'], 'time': bar.timestamp, 'cts': 2},
                    ]
                    trade['exit_bar_idx'] = i
                    completed_results.append(trade)
                    active_trades.remove(trade)

        # Check for new entries
        for entry in all_valid_entries:
            if entry['entry_bar_idx'] != i:
                continue

            direction = entry['direction']

            if len(active_trades) >= 2:
                continue
            if entries_taken[direction] >= 2:
                continue

            new_trade = {
                'direction': direction,
                'entry_type': entry['entry_type'],
                'entry_bar_idx': i,
                'entry_time': entry['entry_time'],
                'entry_price': entry['entry_price'],
                'stop_price': entry['stop_price'],
                'fvg_low': entry['fvg_low'],
                'fvg_high': entry['fvg_high'],
                'risk': abs(entry['entry_price'] - entry['stop_price']),
                'hit_4r': False,
                'exits': [],
            }

            active_trades.append(new_trade)
            entries_taken[direction] += 1

    # EOD exit
    if session_bars:
        last_bar = session_bars[-1]
        for trade in active_trades:
            is_long = trade['direction'] == 'LONG'
            pnl = (last_bar.close - trade['entry_price']) * contracts if is_long else (trade['entry_price'] - last_bar.close) * contracts
            if trade.get('hit_4r'):
                pnl = trade['partial_pnl'] + (last_bar.close - trade['entry_price']) * 2 if is_long else trade['partial_pnl'] + (trade['entry_price'] - last_bar.close) * 2
            trade['exits'] = [{'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'cts': contracts}]
            completed_results.append(trade)

    # Build final results
    final_results = []
    for trade in completed_results:
        if not trade.get('exits'):
            continue

        total_pnl = sum(e['pnl'] for e in trade['exits'])
        total_dollars = (total_pnl / tick_size) * tick_value

        final_results.append({
            'direction': trade['direction'],
            'entry_type': trade['entry_type'],
            'entry_time': trade['entry_time'],
            'entry_price': trade['entry_price'],
            'stop_price': trade['stop_price'],
            'fvg_low': trade['fvg_low'],
            'fvg_high': trade['fvg_high'],
            'risk': trade['risk'],
            'total_pnl': total_pnl,
            'total_dollars': total_dollars,
            'exits': trade['exits'],
        })

    return final_results


def run_30_day_comparison(symbol='ES'):
    """Compare baseline vs high-displacement override for 30 days."""

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25 if symbol == 'MES' else 0.50
    min_risk_pts = 1.5 if symbol in ['ES', 'MES'] else 6.0
    max_bos_risk = 8.0 if symbol in ['ES', 'MES'] else 20.0

    print(f'Fetching {symbol} data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=5000)

    if not all_bars:
        print('No data')
        return

    # Get unique dates
    dates = sorted(set(b.timestamp.date() for b in all_bars))
    dates = dates[-30:] if len(dates) > 30 else dates

    print(f'Testing {len(dates)} days: {dates[0]} to {dates[-1]}')
    print()

    baseline_total = {'trades': 0, 'wins': 0, 'pnl': 0, 'creation': 0}
    modified_total = {'trades': 0, 'wins': 0, 'pnl': 0, 'creation': 0}

    daily_diff = []

    for test_date in dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == test_date]
        if len(day_bars) < 100:
            continue

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Baseline (no override)
        baseline = run_session_with_override(
            session_bars=session_bars,
            all_bars=all_bars,
            tick_size=tick_size,
            tick_value=tick_value,
            contracts=3,
            min_risk_pts=min_risk_pts,
            max_bos_risk_pts=max_bos_risk,
            min_adx=17,
            high_displacement_override=None,  # No override
            symbol=symbol,
        )

        # Modified (3x displacement override)
        modified = run_session_with_override(
            session_bars=session_bars,
            all_bars=all_bars,
            tick_size=tick_size,
            tick_value=tick_value,
            contracts=3,
            min_risk_pts=min_risk_pts,
            max_bos_risk_pts=max_bos_risk,
            min_adx=17,
            high_displacement_override=3.0,  # 3x override
            symbol=symbol,
        )

        # Tally
        base_pnl = sum(r['total_dollars'] for r in baseline)
        base_wins = sum(1 for r in baseline if r['total_dollars'] > 0)
        base_creation = sum(1 for r in baseline if r['entry_type'] == 'CREATION')

        mod_pnl = sum(r['total_dollars'] for r in modified)
        mod_wins = sum(1 for r in modified if r['total_dollars'] > 0)
        mod_creation = sum(1 for r in modified if r['entry_type'] == 'CREATION')

        baseline_total['trades'] += len(baseline)
        baseline_total['wins'] += base_wins
        baseline_total['pnl'] += base_pnl
        baseline_total['creation'] += base_creation

        modified_total['trades'] += len(modified)
        modified_total['wins'] += mod_wins
        modified_total['pnl'] += mod_pnl
        modified_total['creation'] += mod_creation

        diff = mod_pnl - base_pnl
        if abs(diff) > 0.01 or mod_creation != base_creation:
            daily_diff.append({
                'date': test_date,
                'base_pnl': base_pnl,
                'mod_pnl': mod_pnl,
                'diff': diff,
                'base_creation': base_creation,
                'mod_creation': mod_creation,
            })

    # Print results
    print('=' * 70)
    print(f'{symbol} 30-DAY COMPARISON')
    print('Baseline V10 vs High-Displacement Override (3x)')
    print('=' * 70)
    print()
    print(f'{"Metric":<20} {"Baseline":>15} {"Modified":>15} {"Diff":>15}')
    print('-' * 65)
    print(f'{"Trades":<20} {baseline_total["trades"]:>15} {modified_total["trades"]:>15} {modified_total["trades"] - baseline_total["trades"]:>+15}')
    print(f'{"Wins":<20} {baseline_total["wins"]:>15} {modified_total["wins"]:>15} {modified_total["wins"] - baseline_total["wins"]:>+15}')

    base_wr = baseline_total['wins'] / baseline_total['trades'] * 100 if baseline_total['trades'] > 0 else 0
    mod_wr = modified_total['wins'] / modified_total['trades'] * 100 if modified_total['trades'] > 0 else 0
    print(f'{"Win Rate":<20} {base_wr:>14.1f}% {mod_wr:>14.1f}% {mod_wr - base_wr:>+14.1f}%')

    print(f'{"Creation Entries":<20} {baseline_total["creation"]:>15} {modified_total["creation"]:>15} {modified_total["creation"] - baseline_total["creation"]:>+15}')
    base_pnl_str = f"${baseline_total['pnl']:,.2f}"
    mod_pnl_str = f"${modified_total['pnl']:,.2f}"
    diff_pnl_str = f"${modified_total['pnl'] - baseline_total['pnl']:+,.2f}"
    print(f'{"Total P/L":<20} {base_pnl_str:>15} {mod_pnl_str:>15} {diff_pnl_str:>15}')
    print()

    if daily_diff:
        print('Days with differences:')
        print(f'{"Date":<12} {"Base P/L":>12} {"Mod P/L":>12} {"Diff":>12} {"Base Cre":>10} {"Mod Cre":>10}')
        print('-' * 70)
        for d in daily_diff:
            print(f'{str(d["date"]):<12} ${d["base_pnl"]:>10,.2f} ${d["mod_pnl"]:>10,.2f} ${d["diff"]:>+10,.2f} {d["base_creation"]:>10} {d["mod_creation"]:>10}')
        print()

    print('=' * 70)
    improvement = modified_total['pnl'] - baseline_total['pnl']
    print(f'NET IMPROVEMENT: ${improvement:+,.2f}')
    print('=' * 70)


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    run_30_day_comparison(symbol)
