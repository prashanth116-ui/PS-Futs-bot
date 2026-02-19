"""
Compare ICT Entry Strategies: Baseline vs IFVG vs Liquidity Sweep + FVG vs OTE + FVG.
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from collections import defaultdict
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations


def find_swings(bars, lookback=5):
    """Find swing highs and lows."""
    swing_highs = []
    swing_lows = []

    for i in range(lookback, len(bars) - lookback):
        # Swing high: higher than lookback bars on both sides
        is_swing_high = True
        is_swing_low = True

        for j in range(1, lookback + 1):
            if bars[i].high <= bars[i - j].high or bars[i].high <= bars[i + j].high:
                is_swing_high = False
            if bars[i].low >= bars[i - j].low or bars[i].low >= bars[i + j].low:
                is_swing_low = False

        if is_swing_high:
            swing_highs.append({'index': i, 'price': bars[i].high, 'time': bars[i].timestamp})
        if is_swing_low:
            swing_lows.append({'index': i, 'price': bars[i].low, 'time': bars[i].timestamp})

    return swing_highs, swing_lows


def find_liquidity_sweeps(bars, swing_highs, swing_lows, lookback=20):
    """Find liquidity sweeps (stop hunts)."""
    sweeps = []

    for i in range(lookback, len(bars)):
        bar = bars[i]

        # Check for sweep of recent swing low (bullish sweep)
        for sh in swing_lows:
            if sh['index'] < i - lookback:
                continue
            if sh['index'] >= i:
                break
            # Sweep: wick below swing low but close above
            if bar.low < sh['price'] and bar.close > sh['price']:
                sweeps.append({
                    'index': i,
                    'direction': 'BULLISH',
                    'swept_price': sh['price'],
                    'time': bar.timestamp
                })
                break

        # Check for sweep of recent swing high (bearish sweep)
        for sh in swing_highs:
            if sh['index'] < i - lookback:
                continue
            if sh['index'] >= i:
                break
            # Sweep: wick above swing high but close below
            if bar.high > sh['price'] and bar.close < sh['price']:
                sweeps.append({
                    'index': i,
                    'direction': 'BEARISH',
                    'swept_price': sh['price'],
                    'time': bar.timestamp
                })
                break

    return sweeps


def run_trade_baseline(session_bars, direction, fvg_num, all_fvgs, tick_size=0.25, tick_value=12.50, contracts=3, target1_r=4, target2_r=8):
    """Baseline: FVG midpoint entry."""
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'
    opposing_fvg_dir = 'BEARISH' if is_long else 'BULLISH'

    active_fvgs = [f for f in all_fvgs if f.direction == fvg_dir and not f.mitigated]
    active_fvgs.sort(key=lambda f: f.created_bar_index)

    if len(active_fvgs) < fvg_num:
        return None

    entry_fvg = active_fvgs[fvg_num - 1]
    entry_price = entry_fvg.midpoint
    fvg_stop_level = entry_fvg.low if is_long else entry_fvg.high

    if is_long:
        stop_price = entry_fvg.low
        risk = entry_price - stop_price
    else:
        stop_price = entry_fvg.high
        risk = stop_price - entry_price

    if risk <= 0:
        return None

    target_t1 = entry_price + (target1_r * risk) if is_long else entry_price - (target1_r * risk)
    target_t2 = entry_price + (target2_r * risk) if is_long else entry_price - (target2_r * risk)

    # Find entry trigger
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

    return simulate_exits(session_bars, entry_bar_idx, entry_price, fvg_stop_level, target_t1, target_t2,
                         is_long, all_fvgs, opposing_fvg_dir, contracts, tick_size, tick_value,
                         direction, entry_time, target1_r, target2_r)


def run_trade_ifvg(session_bars, direction, all_fvgs, tick_size=0.25, tick_value=12.50, contracts=3, target1_r=4, target2_r=8):
    """IFVG: Enter on Inverse FVG (FVG that got traded through, now acts as S/R in opposite direction)."""
    is_long = direction == 'LONG'
    # For LONG: Look for Bearish FVG that got mitigated (now acts as support)
    # For SHORT: Look for Bullish FVG that got mitigated (now acts as resistance)
    original_fvg_dir = 'BEARISH' if is_long else 'BULLISH'
    opposing_fvg_dir = 'BEARISH' if is_long else 'BULLISH'

    # Find mitigated FVGs (these become inverse FVGs)
    mitigated_fvgs = [f for f in all_fvgs if f.direction == original_fvg_dir and f.mitigated]
    mitigated_fvgs.sort(key=lambda f: f.mitigation_bar_index if f.mitigation_bar_index else f.created_bar_index)

    if not mitigated_fvgs:
        return None

    # Use the most recent mitigated FVG
    ifvg = mitigated_fvgs[-1]

    # Entry at IFVG midpoint (inverse direction)
    entry_price = ifvg.midpoint

    # For LONG on IFVG (was bearish, now support): stop below IFVG low
    # For SHORT on IFVG (was bullish, now resistance): stop above IFVG high
    if is_long:
        fvg_stop_level = ifvg.low
        stop_price = ifvg.low
        risk = entry_price - stop_price
    else:
        fvg_stop_level = ifvg.high
        stop_price = ifvg.high
        risk = stop_price - entry_price

    if risk <= 0:
        return None

    target_t1 = entry_price + (target1_r * risk) if is_long else entry_price - (target1_r * risk)
    target_t2 = entry_price + (target2_r * risk) if is_long else entry_price - (target2_r * risk)

    # Find entry after mitigation
    start_idx = ifvg.mitigation_bar_index if ifvg.mitigation_bar_index else ifvg.created_bar_index + 10
    entry_bar_idx = None
    entry_time = None

    for i in range(start_idx + 1, len(session_bars)):
        bar = session_bars[i]
        # Price returns to IFVG zone
        price_at_entry = bar.low <= entry_price if is_long else bar.high >= entry_price
        if price_at_entry:
            entry_bar_idx = i
            entry_time = bar.timestamp
            break

    if not entry_bar_idx:
        return None

    return simulate_exits(session_bars, entry_bar_idx, entry_price, fvg_stop_level, target_t1, target_t2,
                         is_long, all_fvgs, opposing_fvg_dir, contracts, tick_size, tick_value,
                         direction, entry_time, target1_r, target2_r)


def run_trade_sweep_fvg(session_bars, direction, all_fvgs, sweeps, tick_size=0.25, tick_value=12.50, contracts=3, target1_r=4, target2_r=8):
    """Liquidity Sweep + FVG: Enter FVG that forms after a liquidity sweep."""
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'
    sweep_dir = 'BULLISH' if is_long else 'BEARISH'
    opposing_fvg_dir = 'BEARISH' if is_long else 'BULLISH'

    # Find sweeps in our direction
    dir_sweeps = [s for s in sweeps if s['direction'] == sweep_dir]

    if not dir_sweeps:
        return None

    # Find FVG that forms after a sweep
    for sweep in dir_sweeps:
        # Look for FVG forming within 10 bars after sweep
        post_sweep_fvgs = [f for f in all_fvgs
                          if f.direction == fvg_dir
                          and not f.mitigated
                          and f.created_bar_index > sweep['index']
                          and f.created_bar_index <= sweep['index'] + 10]

        if not post_sweep_fvgs:
            continue

        entry_fvg = post_sweep_fvgs[0]
        entry_price = entry_fvg.midpoint
        fvg_stop_level = entry_fvg.low if is_long else entry_fvg.high

        if is_long:
            stop_price = entry_fvg.low
            risk = entry_price - stop_price
        else:
            stop_price = entry_fvg.high
            risk = stop_price - entry_price

        if risk <= 0:
            continue

        target_t1 = entry_price + (target1_r * risk) if is_long else entry_price - (target1_r * risk)
        target_t2 = entry_price + (target2_r * risk) if is_long else entry_price - (target2_r * risk)

        # Find entry trigger
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
            continue

        result = simulate_exits(session_bars, entry_bar_idx, entry_price, fvg_stop_level, target_t1, target_t2,
                               is_long, all_fvgs, opposing_fvg_dir, contracts, tick_size, tick_value,
                               direction, entry_time, target1_r, target2_r)
        if result:
            return result

    return None


def run_trade_ote_fvg(session_bars, direction, all_fvgs, swing_highs, swing_lows, tick_size=0.25, tick_value=12.50, contracts=3, target1_r=4, target2_r=8):
    """OTE + FVG: Enter FVG that falls within the 62-79% Fib retracement zone."""
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'
    opposing_fvg_dir = 'BEARISH' if is_long else 'BULLISH'

    # Find active FVGs
    active_fvgs = [f for f in all_fvgs if f.direction == fvg_dir and not f.mitigated]
    active_fvgs.sort(key=lambda f: f.created_bar_index)

    if not active_fvgs:
        return None

    # For each FVG, check if it's in OTE zone
    for entry_fvg in active_fvgs:
        fvg_idx = entry_fvg.created_bar_index

        # Find the most recent swing before FVG
        if is_long:
            # For LONG: Find swing low before FVG and swing high before that
            recent_lows = [s for s in swing_lows if s['index'] < fvg_idx]
            recent_highs = [s for s in swing_highs if s['index'] < fvg_idx]

            if not recent_lows or not recent_highs:
                continue

            swing_low = recent_lows[-1]
            # Find swing high that's before the swing low
            prior_highs = [s for s in recent_highs if s['index'] < swing_low['index']]
            if not prior_highs:
                continue
            swing_high = prior_highs[-1]

            # Calculate OTE zone (62-79% retracement from high to low)
            range_size = swing_high['price'] - swing_low['price']
            ote_high = swing_low['price'] + (0.79 * range_size)  # 79% retracement
            ote_low = swing_low['price'] + (0.62 * range_size)   # 62% retracement

            # Check if FVG midpoint is in OTE zone
            if not (ote_low <= entry_fvg.midpoint <= ote_high):
                continue
        else:
            # For SHORT: Find swing high before FVG and swing low before that
            recent_highs = [s for s in swing_highs if s['index'] < fvg_idx]
            recent_lows = [s for s in swing_lows if s['index'] < fvg_idx]

            if not recent_highs or not recent_lows:
                continue

            swing_high = recent_highs[-1]
            # Find swing low that's before the swing high
            prior_lows = [s for s in recent_lows if s['index'] < swing_high['index']]
            if not prior_lows:
                continue
            swing_low = prior_lows[-1]

            # Calculate OTE zone (62-79% retracement from low to high)
            range_size = swing_high['price'] - swing_low['price']
            ote_low = swing_high['price'] - (0.79 * range_size)   # 79% retracement
            ote_high = swing_high['price'] - (0.62 * range_size)  # 62% retracement

            # Check if FVG midpoint is in OTE zone
            if not (ote_low <= entry_fvg.midpoint <= ote_high):
                continue

        # FVG is in OTE zone - proceed with entry
        entry_price = entry_fvg.midpoint
        fvg_stop_level = entry_fvg.low if is_long else entry_fvg.high

        if is_long:
            stop_price = entry_fvg.low
            risk = entry_price - stop_price
        else:
            stop_price = entry_fvg.high
            risk = stop_price - entry_price

        if risk <= 0:
            continue

        target_t1 = entry_price + (target1_r * risk) if is_long else entry_price - (target1_r * risk)
        target_t2 = entry_price + (target2_r * risk) if is_long else entry_price - (target2_r * risk)

        # Find entry trigger
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
            continue

        result = simulate_exits(session_bars, entry_bar_idx, entry_price, fvg_stop_level, target_t1, target_t2,
                               is_long, all_fvgs, opposing_fvg_dir, contracts, tick_size, tick_value,
                               direction, entry_time, target1_r, target2_r)
        if result:
            return result

    return None


def simulate_exits(session_bars, entry_bar_idx, entry_price, fvg_stop_level, target_t1, target_t2,
                  is_long, all_fvgs, opposing_fvg_dir, contracts, tick_size, tick_value,
                  direction, entry_time, target1_r, target2_r):
    """Simulate exits for a trade."""

    cts_t1 = contracts // 3
    cts_t2 = contracts // 3
    cts_runner = contracts - cts_t1 - cts_t2
    if cts_t1 == 0: cts_t1 = 1
    if cts_t2 == 0: cts_t2 = 1
    if cts_runner == 0: cts_runner = 1

    exits = []
    remaining = contracts
    exited_t1 = False
    exited_t2 = False

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]

        # Check stop
        stop_hit = bar.close < fvg_stop_level if is_long else bar.close > fvg_stop_level
        if stop_hit:
            pnl = (bar.close - entry_price) * remaining if is_long else (entry_price - bar.close) * remaining
            exits.append({'type': 'STOP', 'pnl': pnl, 'cts': remaining})
            remaining = 0
            break

        # Check T1
        t1_hit = bar.high >= target_t1 if is_long else bar.low <= target_t1
        if not exited_t1 and t1_hit:
            exit_cts = min(cts_t1, remaining)
            pnl = (target_t1 - entry_price) * exit_cts if is_long else (entry_price - target_t1) * exit_cts
            exits.append({'type': f'T{target1_r}R', 'pnl': pnl, 'cts': exit_cts})
            remaining -= exit_cts
            exited_t1 = True

        # Check T2
        t2_hit = bar.high >= target_t2 if is_long else bar.low <= target_t2
        if not exited_t2 and t2_hit and remaining > cts_runner:
            exit_cts = min(cts_t2, remaining - cts_runner)
            pnl = (target_t2 - entry_price) * exit_cts if is_long else (entry_price - target_t2) * exit_cts
            exits.append({'type': f'T{target2_r}R', 'pnl': pnl, 'cts': exit_cts})
            remaining -= exit_cts
            exited_t2 = True

        # Check Opposing FVG runner exit
        if remaining > 0 and remaining <= cts_runner:
            opposing_fvgs = [f for f in all_fvgs if f.direction == opposing_fvg_dir
                           and f.created_bar_index > entry_bar_idx
                           and f.created_bar_index <= i]
            if opposing_fvgs:
                pnl = (bar.close - entry_price) * remaining if is_long else (entry_price - bar.close) * remaining
                exits.append({'type': 'OPP_FVG', 'pnl': pnl, 'cts': remaining})
                remaining = 0

    # EOD close
    if remaining > 0:
        last_bar = session_bars[-1]
        pnl = (last_bar.close - entry_price) * remaining if is_long else (entry_price - last_bar.close) * remaining
        exits.append({'type': 'EOD', 'pnl': pnl, 'cts': remaining})

    total_pnl = sum(e['pnl'] for e in exits)
    total_dollars = (total_pnl / tick_size) * tick_value
    was_stopped = any(e['type'] == 'STOP' for e in exits)

    return {
        'direction': direction,
        'entry_time': entry_time,
        'entry_price': entry_price,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'was_stopped': was_stopped,
        'exits': exits,
    }


def run_comparison():
    """Run comparison of all entry strategies."""

    contracts = 3
    tick_size = 0.25
    tick_value = 12.50

    # Fetch data - use 3m for 15 days
    print('Fetching ES 3m data for last 15 days...')
    all_bars = fetch_futures_bars(symbol='ES', interval='3m', n_bars=10000)

    if not all_bars:
        print('No data available')
        return

    print(f'Got {len(all_bars)} bars')

    # Group by date
    bars_by_date = defaultdict(list)
    for bar in all_bars:
        bars_by_date[bar.timestamp.date()].append(bar)

    trading_days = sorted(bars_by_date.keys())
    print(f'Trading days: {len(trading_days)}')
    print(f'Date range: {trading_days[0]} to {trading_days[-1]}')

    # Session filter
    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)

    print('\n' + '='*120)
    print('COMPARING ICT ENTRY STRATEGIES')
    print('='*120)
    print(f'Period: {trading_days[0]} to {trading_days[-1]} ({len(trading_days)} days)')
    print(f'Contracts: {contracts} | Exits: 4R, 8R, Opposing FVG')
    print('='*120)

    fvg_config = {
        'min_fvg_ticks': 4,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }

    # Results storage
    baseline_results = []
    ifvg_results = []
    sweep_fvg_results = []
    ote_fvg_results = []

    for d in trading_days:
        day_bars = bars_by_date[d]
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Detect FVGs and swings
        all_fvgs = detect_fvgs(session_bars, fvg_config)
        update_all_fvg_mitigations(all_fvgs, session_bars, fvg_config)
        swing_highs, swing_lows = find_swings(session_bars, lookback=5)
        sweeps = find_liquidity_sweeps(session_bars, swing_highs, swing_lows, lookback=20)

        for direction in ['LONG', 'SHORT']:
            # Baseline
            result = run_trade_baseline(session_bars, direction, 1, all_fvgs, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
            if result:
                result['date'] = d
                baseline_results.append(result)

            # IFVG
            result = run_trade_ifvg(session_bars, direction, all_fvgs, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
            if result:
                result['date'] = d
                ifvg_results.append(result)

            # Liquidity Sweep + FVG
            result = run_trade_sweep_fvg(session_bars, direction, all_fvgs, sweeps, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
            if result:
                result['date'] = d
                sweep_fvg_results.append(result)

            # OTE + FVG
            result = run_trade_ote_fvg(session_bars, direction, all_fvgs, swing_highs, swing_lows, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
            if result:
                result['date'] = d
                ote_fvg_results.append(result)

    # Calculate stats
    def calc_stats(results, name):
        if not results:
            return {
                'name': name,
                'trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'long_pnl': 0,
                'short_pnl': 0,
                'profit_factor': 0,
                'avg_per_trade': 0,
            }

        wins = sum(1 for r in results if r['total_pnl'] > 0.01)
        losses = sum(1 for r in results if r['total_pnl'] < -0.01)
        total_pnl = sum(r['total_dollars'] for r in results)
        long_pnl = sum(r['total_dollars'] for r in results if r['direction'] == 'LONG')
        short_pnl = sum(r['total_dollars'] for r in results if r['direction'] == 'SHORT')
        win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
        losing_pnl = sum(r['total_dollars'] for r in results if r['total_pnl'] < -0.01)
        profit_factor = abs(total_pnl) / abs(losing_pnl) if losing_pnl < 0 else float('inf')

        return {
            'name': name,
            'trades': len(results),
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'long_pnl': long_pnl,
            'short_pnl': short_pnl,
            'profit_factor': profit_factor,
            'avg_per_trade': total_pnl / len(results) if results else 0,
        }

    baseline_stats = calc_stats(baseline_results, 'Baseline (FVG Midpoint)')
    ifvg_stats = calc_stats(ifvg_results, 'IFVG (Inverse FVG)')
    sweep_stats = calc_stats(sweep_fvg_results, 'Sweep + FVG')
    ote_stats = calc_stats(ote_fvg_results, 'OTE + FVG')

    all_stats = [baseline_stats, ifvg_stats, sweep_stats, ote_stats]

    # Print detailed results for each strategy
    print('\n' + '-'*120)
    print('BASELINE (FVG Midpoint) TRADES')
    print('-'*120)
    for r in baseline_results:
        result_str = 'WIN' if r['total_pnl'] > 0.01 else 'LOSS' if r['total_pnl'] < -0.01 else 'BE'
        print(f"  {r['date']} | {r['direction']:5} | {r['entry_time'].strftime('%H:%M')} | {result_str:4} | ${r['total_dollars']:+,.2f}")

    print('\n' + '-'*120)
    print('IFVG (Inverse FVG) TRADES')
    print('-'*120)
    if ifvg_results:
        for r in ifvg_results:
            result_str = 'WIN' if r['total_pnl'] > 0.01 else 'LOSS' if r['total_pnl'] < -0.01 else 'BE'
            print(f"  {r['date']} | {r['direction']:5} | {r['entry_time'].strftime('%H:%M')} | {result_str:4} | ${r['total_dollars']:+,.2f}")
    else:
        print('  No trades')

    print('\n' + '-'*120)
    print('LIQUIDITY SWEEP + FVG TRADES')
    print('-'*120)
    if sweep_fvg_results:
        for r in sweep_fvg_results:
            result_str = 'WIN' if r['total_pnl'] > 0.01 else 'LOSS' if r['total_pnl'] < -0.01 else 'BE'
            print(f"  {r['date']} | {r['direction']:5} | {r['entry_time'].strftime('%H:%M')} | {result_str:4} | ${r['total_dollars']:+,.2f}")
    else:
        print('  No trades')

    print('\n' + '-'*120)
    print('OTE + FVG TRADES')
    print('-'*120)
    if ote_fvg_results:
        for r in ote_fvg_results:
            result_str = 'WIN' if r['total_pnl'] > 0.01 else 'LOSS' if r['total_pnl'] < -0.01 else 'BE'
            print(f"  {r['date']} | {r['direction']:5} | {r['entry_time'].strftime('%H:%M')} | {result_str:4} | ${r['total_dollars']:+,.2f}")
    else:
        print('  No trades')

    # Print summary comparison
    print('\n' + '='*120)
    print('SUMMARY COMPARISON')
    print('='*120)
    print(f'{"Strategy":<25} {"Trades":>8} {"Wins":>6} {"Losses":>8} {"Win Rate":>10} {"Total P/L":>15} {"Avg/Trade":>12} {"vs Baseline":>15}')
    print('-'*120)

    for stats in all_stats:
        f'{stats["profit_factor"]:.2f}' if stats["profit_factor"] != float('inf') else 'inf'
        diff = stats['total_pnl'] - baseline_stats['total_pnl']
        diff_pct = (diff / baseline_stats['total_pnl'] * 100) if baseline_stats['total_pnl'] != 0 else 0
        diff_str = f'${diff:+,.0f} ({diff_pct:+.1f}%)' if stats['name'] != 'Baseline (FVG Midpoint)' else '-'

        print(f'{stats["name"]:<25} {stats["trades"]:>8} {stats["wins"]:>6} {stats["losses"]:>8} {stats["win_rate"]:>9.1f}% ${stats["total_pnl"]:>13,.2f} ${stats["avg_per_trade"]:>10,.2f} {diff_str:>15}')

    # Find winner
    print('\n' + '='*120)
    best = max(all_stats, key=lambda x: x['total_pnl'])
    if best['total_pnl'] > baseline_stats['total_pnl']:
        diff = best['total_pnl'] - baseline_stats['total_pnl']
        pct = diff / baseline_stats['total_pnl'] * 100 if baseline_stats['total_pnl'] != 0 else 0
        print(f'BEST STRATEGY: {best["name"]} (+${diff:,.2f} | +{pct:.1f}% vs Baseline)')
    else:
        print(f'BEST STRATEGY: {best["name"]} (Baseline is best)')
    print('='*120)

    # Recommendations
    print('\n' + '-'*120)
    print('ANALYSIS')
    print('-'*120)
    print(f'  Baseline trades:      {baseline_stats["trades"]} ({baseline_stats["wins"]}W/{baseline_stats["losses"]}L)')
    print(f'  IFVG trades:          {ifvg_stats["trades"]} ({ifvg_stats["wins"]}W/{ifvg_stats["losses"]}L) - Inverse FVG entries')
    print(f'  Sweep + FVG trades:   {sweep_stats["trades"]} ({sweep_stats["wins"]}W/{sweep_stats["losses"]}L) - After liquidity sweep')
    print(f'  OTE + FVG trades:     {ote_stats["trades"]} ({ote_stats["wins"]}W/{ote_stats["losses"]}L) - FVG in 62-79% zone')

    return all_stats


if __name__ == '__main__':
    run_comparison()
