"""
Compare entry strategies: Midpoint-only vs Partial Fill (Edge + Midpoint).
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from collections import defaultdict
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations


def run_trade_midpoint(session_bars, direction, fvg_num, all_fvgs, tick_size=0.25, tick_value=12.50, contracts=3, target1_r=4, target2_r=8):
    """Run trade with midpoint-only entry (current strategy)."""
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'
    opposing_fvg_dir = 'BEARISH' if is_long else 'BULLISH'

    # Get active FVGs
    active_fvgs = [f for f in all_fvgs if f.direction == fvg_dir and not f.mitigated]
    active_fvgs.sort(key=lambda f: f.created_bar_index)

    if len(active_fvgs) < fvg_num:
        return None

    entry_fvg = active_fvgs[fvg_num - 1]

    # Entry at midpoint
    entry_price = entry_fvg.midpoint
    fvg_stop_level = entry_fvg.low if is_long else entry_fvg.high

    if is_long:
        stop_price = entry_fvg.low
        risk = entry_price - stop_price
    else:
        stop_price = entry_fvg.high
        risk = stop_price - entry_price

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

    # Simulate exits
    cts_t1 = contracts // 3
    cts_t2 = contracts // 3
    cts_runner = contracts - cts_t1 - cts_t2
    if cts_t1 == 0:
        cts_t1 = 1
    if cts_t2 == 0:
        cts_t2 = 1
    if cts_runner == 0:
        cts_runner = 1

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
        'contracts_filled': contracts,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'was_stopped': was_stopped,
        'exits': exits,
    }


def run_trade_partial(session_bars, direction, fvg_num, all_fvgs, tick_size=0.25, tick_value=12.50, contracts=3, target1_r=4, target2_r=8):
    """Run trade with partial fill entry (1 at edge, 2 at midpoint)."""
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'
    opposing_fvg_dir = 'BEARISH' if is_long else 'BULLISH'

    # Get active FVGs
    active_fvgs = [f for f in all_fvgs if f.direction == fvg_dir and not f.mitigated]
    active_fvgs.sort(key=lambda f: f.created_bar_index)

    if len(active_fvgs) < fvg_num:
        return None

    entry_fvg = active_fvgs[fvg_num - 1]

    # Entry levels
    edge_price = entry_fvg.high if is_long else entry_fvg.low  # Enter at far edge
    midpoint_price = entry_fvg.midpoint
    fvg_stop_level = entry_fvg.low if is_long else entry_fvg.high

    # Contracts at each level
    cts_edge = 1
    cts_midpoint = contracts - cts_edge

    # Find edge entry trigger first
    edge_entry_bar_idx = None
    edge_entry_time = None
    midpoint_entry_bar_idx = None
    midpoint_entry_time = None

    for i in range(entry_fvg.created_bar_index + 1, len(session_bars)):
        bar = session_bars[i]

        # Check edge fill
        if edge_entry_bar_idx is None:
            edge_hit = bar.low <= edge_price if is_long else bar.high >= edge_price
            if edge_hit:
                edge_entry_bar_idx = i
                edge_entry_time = bar.timestamp

        # Check midpoint fill
        if midpoint_entry_bar_idx is None:
            midpoint_hit = bar.low <= midpoint_price if is_long else bar.high >= midpoint_price
            if midpoint_hit:
                midpoint_entry_bar_idx = i
                midpoint_entry_time = bar.timestamp
                break  # Both levels filled

    # Determine what got filled
    if edge_entry_bar_idx is None:
        return None  # Not even edge got filled

    # Calculate filled contracts and average entry
    if midpoint_entry_bar_idx is not None:
        # Both filled
        contracts_filled = contracts
        avg_entry = (edge_price * cts_edge + midpoint_price * cts_midpoint) / contracts
        entry_bar_idx = midpoint_entry_bar_idx
        entry_time = midpoint_entry_time
    else:
        # Only edge filled
        contracts_filled = cts_edge
        avg_entry = edge_price
        entry_bar_idx = edge_entry_bar_idx
        entry_time = edge_entry_time

    # Calculate risk from average entry
    if is_long:
        stop_price = entry_fvg.low
        risk = avg_entry - stop_price
    else:
        stop_price = entry_fvg.high
        risk = stop_price - avg_entry

    target_t1 = avg_entry + (target1_r * risk) if is_long else avg_entry - (target1_r * risk)
    target_t2 = avg_entry + (target2_r * risk) if is_long else avg_entry - (target2_r * risk)

    # Simulate exits based on filled contracts
    if contracts_filled == 3:
        cts_t1 = 1
        cts_t2 = 1
        cts_runner = 1
    else:
        # Only 1 contract filled - scale targets differently
        cts_t1 = 0
        cts_t2 = 0
        cts_runner = 1

    exits = []
    remaining = contracts_filled
    exited_t1 = False
    exited_t2 = False

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]

        # Check stop
        stop_hit = bar.close < fvg_stop_level if is_long else bar.close > fvg_stop_level
        if stop_hit:
            pnl = (bar.close - avg_entry) * remaining if is_long else (avg_entry - bar.close) * remaining
            exits.append({'type': 'STOP', 'pnl': pnl, 'cts': remaining})
            remaining = 0
            break

        # Check T1 (only if 3 contracts filled)
        if cts_t1 > 0:
            t1_hit = bar.high >= target_t1 if is_long else bar.low <= target_t1
            if not exited_t1 and t1_hit:
                exit_cts = min(cts_t1, remaining)
                pnl = (target_t1 - avg_entry) * exit_cts if is_long else (avg_entry - target_t1) * exit_cts
                exits.append({'type': f'T{target1_r}R', 'pnl': pnl, 'cts': exit_cts})
                remaining -= exit_cts
                exited_t1 = True

        # Check T2 (only if 3 contracts filled)
        if cts_t2 > 0:
            t2_hit = bar.high >= target_t2 if is_long else bar.low <= target_t2
            if not exited_t2 and t2_hit and remaining > cts_runner:
                exit_cts = min(cts_t2, remaining - cts_runner)
                pnl = (target_t2 - avg_entry) * exit_cts if is_long else (avg_entry - target_t2) * exit_cts
                exits.append({'type': f'T{target2_r}R', 'pnl': pnl, 'cts': exit_cts})
                remaining -= exit_cts
                exited_t2 = True

        # Check Opposing FVG runner exit
        if remaining > 0 and remaining <= cts_runner:
            opposing_fvgs = [f for f in all_fvgs if f.direction == opposing_fvg_dir
                           and f.created_bar_index > entry_bar_idx
                           and f.created_bar_index <= i]
            if opposing_fvgs:
                pnl = (bar.close - avg_entry) * remaining if is_long else (avg_entry - bar.close) * remaining
                exits.append({'type': 'OPP_FVG', 'pnl': pnl, 'cts': remaining})
                remaining = 0

    # EOD close
    if remaining > 0:
        last_bar = session_bars[-1]
        pnl = (last_bar.close - avg_entry) * remaining if is_long else (avg_entry - last_bar.close) * remaining
        exits.append({'type': 'EOD', 'pnl': pnl, 'cts': remaining})

    total_pnl = sum(e['pnl'] for e in exits)
    total_dollars = (total_pnl / tick_size) * tick_value
    was_stopped = any(e['type'] == 'STOP' for e in exits)

    return {
        'direction': direction,
        'entry_time': entry_time,
        'entry_price': avg_entry,
        'contracts_filled': contracts_filled,
        'edge_filled': True,
        'midpoint_filled': midpoint_entry_bar_idx is not None,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'was_stopped': was_stopped,
        'exits': exits,
    }


def run_comparison():
    """Run comparison between midpoint-only and partial fill entry strategies."""

    contracts = 3
    tick_size = 0.25
    tick_value = 12.50

    # Fetch data
    print('Fetching ES 5m data for last 30 days...')
    all_bars = fetch_futures_bars(symbol='ES', interval='5m', n_bars=10000)

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

    print('\n' + '='*110)
    print('COMPARING ENTRY STRATEGIES: MIDPOINT-ONLY vs PARTIAL FILL (1 Edge + 2 Midpoint)')
    print('='*110)
    print(f'Period: {trading_days[0]} to {trading_days[-1]} ({len(trading_days)} days)')
    print(f'Contracts: {contracts} | Exits: 4R, 8R, Opposing FVG')
    print('='*110)

    midpoint_results = []
    partial_results = []

    fvg_config = {
        'min_fvg_ticks': 4,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }

    for d in trading_days:
        day_bars = bars_by_date[d]
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Detect FVGs once per day
        all_fvgs = detect_fvgs(session_bars, fvg_config)
        update_all_fvg_mitigations(all_fvgs, session_bars, fvg_config)

        for direction in ['LONG', 'SHORT']:
            # Midpoint-only
            result = run_trade_midpoint(session_bars, direction, 1, all_fvgs, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
            if result:
                result['date'] = d
                midpoint_results.append(result)
                if result['was_stopped']:
                    result2 = run_trade_midpoint(session_bars, direction, 2, all_fvgs, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
                    if result2:
                        result2['date'] = d
                        result2['is_reentry'] = True
                        midpoint_results.append(result2)

            # Partial fill
            result = run_trade_partial(session_bars, direction, 1, all_fvgs, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
            if result:
                result['date'] = d
                partial_results.append(result)
                if result['was_stopped']:
                    result2 = run_trade_partial(session_bars, direction, 2, all_fvgs, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
                    if result2:
                        result2['date'] = d
                        result2['is_reentry'] = True
                        partial_results.append(result2)

    # Calculate stats
    def calc_stats(results, name):
        wins = sum(1 for r in results if r['total_pnl'] > 0.01)
        losses = sum(1 for r in results if r['total_pnl'] < -0.01)
        total_pnl = sum(r['total_dollars'] for r in results)
        total_contracts = sum(r['contracts_filled'] for r in results)
        long_pnl = sum(r['total_dollars'] for r in results if r['direction'] == 'LONG')
        short_pnl = sum(r['total_dollars'] for r in results if r['direction'] == 'SHORT')
        win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
        losing_pnl = sum(r['total_dollars'] for r in results if r['total_pnl'] < -0.01)
        profit_factor = abs(total_pnl) / abs(losing_pnl) if losing_pnl < 0 else float('inf')

        # For partial, count fill rates
        if 'edge_filled' in results[0] if results else {}:
            edge_only = sum(1 for r in results if r.get('edge_filled') and not r.get('midpoint_filled'))
            full_fills = sum(1 for r in results if r.get('midpoint_filled'))
        else:
            edge_only = 0
            full_fills = len(results)

        return {
            'name': name,
            'trades': len(results),
            'wins': wins,
            'losses': losses,
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'total_contracts': total_contracts,
            'long_pnl': long_pnl,
            'short_pnl': short_pnl,
            'profit_factor': profit_factor,
            'avg_per_trade': total_pnl / len(results) if results else 0,
            'edge_only': edge_only,
            'full_fills': full_fills,
        }

    midpoint_stats = calc_stats(midpoint_results, 'Midpoint-Only')
    partial_stats = calc_stats(partial_results, 'Partial Fill')

    # Print trade-by-trade comparison
    print('\n' + '-'*110)
    print('TRADE-BY-TRADE COMPARISON')
    print('-'*110)
    print(f'{"Date":<12} {"Dir":<6} {"Midpoint P/L":>12} {"Cts":>4} {"Partial P/L":>12} {"Cts":>4} {"Fill":>8} {"Diff":>12}')
    print('-'*110)

    # Match trades by date and direction
    midpoint_by_key = {}
    for r in midpoint_results:
        key = (r['date'], r['direction'], r.get('is_reentry', False))
        midpoint_by_key[key] = r

    partial_by_key = {}
    for r in partial_results:
        key = (r['date'], r['direction'], r.get('is_reentry', False))
        partial_by_key[key] = r

    all_keys = sorted(set(midpoint_by_key.keys()) | set(partial_by_key.keys()))

    for key in all_keys:
        d, direction, is_reentry = key
        mid_r = midpoint_by_key.get(key)
        par_r = partial_by_key.get(key)

        mid_pnl = mid_r['total_dollars'] if mid_r else 0
        mid_cts = mid_r['contracts_filled'] if mid_r else 0
        par_pnl = par_r['total_dollars'] if par_r else 0
        par_cts = par_r['contracts_filled'] if par_r else 0

        fill_type = ''
        if par_r:
            if par_r.get('midpoint_filled'):
                fill_type = 'FULL'
            else:
                fill_type = 'EDGE'

        diff = par_pnl - mid_pnl

        reentry_tag = ' [RE]' if is_reentry else ''
        print(f'{str(d):<12} {direction:<6} ${mid_pnl:>10,.2f} {mid_cts:>4} ${par_pnl:>10,.2f} {par_cts:>4} {fill_type:>8} ${diff:>+10,.2f}{reentry_tag}')

    # Print summary
    print('\n' + '='*110)
    print('SUMMARY COMPARISON')
    print('='*110)
    print(f'{"Metric":<25} {"Midpoint-Only":>20} {"Partial Fill":>20} {"Difference":>20}')
    print('-'*110)

    pnl_diff = partial_stats['total_pnl'] - midpoint_stats['total_pnl']
    pnl_pct = (pnl_diff / midpoint_stats['total_pnl'] * 100) if midpoint_stats['total_pnl'] != 0 else 0

    print(f'{"Total Trades":<25} {midpoint_stats["trades"]:>20} {partial_stats["trades"]:>20} {partial_stats["trades"] - midpoint_stats["trades"]:>+20}')
    print(f'{"Total Contracts":<25} {midpoint_stats["total_contracts"]:>20} {partial_stats["total_contracts"]:>20} {partial_stats["total_contracts"] - midpoint_stats["total_contracts"]:>+20}')
    print(f'{"Wins":<25} {midpoint_stats["wins"]:>20} {partial_stats["wins"]:>20} {"":>20}')
    print(f'{"Losses":<25} {midpoint_stats["losses"]:>20} {partial_stats["losses"]:>20} {"":>20}')
    print(f'{"Win Rate":<25} {midpoint_stats["win_rate"]:>19.1f}% {partial_stats["win_rate"]:>19.1f}% {"":>20}')
    print('-'*110)
    print(f'{"TOTAL P/L":<25} ${midpoint_stats["total_pnl"]:>18,.2f} ${partial_stats["total_pnl"]:>18,.2f} ${pnl_diff:>+17,.2f} ({pnl_pct:+.1f}%)')
    print(f'{"Long P/L":<25} ${midpoint_stats["long_pnl"]:>18,.2f} ${partial_stats["long_pnl"]:>18,.2f} ${partial_stats["long_pnl"] - midpoint_stats["long_pnl"]:>+17,.2f}')
    print(f'{"Short P/L":<25} ${midpoint_stats["short_pnl"]:>18,.2f} ${partial_stats["short_pnl"]:>18,.2f} ${partial_stats["short_pnl"] - midpoint_stats["short_pnl"]:>+17,.2f}')
    print('-'*110)
    print(f'{"Avg per Trade":<25} ${midpoint_stats["avg_per_trade"]:>18,.2f} ${partial_stats["avg_per_trade"]:>18,.2f} ${partial_stats["avg_per_trade"] - midpoint_stats["avg_per_trade"]:>+17,.2f}')
    pf_mid = f'{midpoint_stats["profit_factor"]:.2f}' if midpoint_stats["profit_factor"] != float('inf') else 'inf'
    pf_par = f'{partial_stats["profit_factor"]:.2f}' if partial_stats["profit_factor"] != float('inf') else 'inf'
    print(f'{"Profit Factor":<25} {pf_mid:>20} {pf_par:>20} {"":>20}')

    print('\n' + '-'*110)
    print('FILL ANALYSIS (Partial Fill Strategy)')
    print('-'*110)
    print(f'  Full Fills (3 cts):    {partial_stats["full_fills"]} trades')
    print(f'  Edge-Only (1 ct):      {partial_stats["edge_only"]} trades')
    if partial_stats["trades"] > 0:
        print(f'  Fill Rate:             {partial_stats["full_fills"] / partial_stats["trades"] * 100:.1f}% full, {partial_stats["edge_only"] / partial_stats["trades"] * 100:.1f}% edge-only')

    print('\n' + '='*110)
    if pnl_diff > 0:
        print(f'WINNER: PARTIAL FILL (+${pnl_diff:,.2f} | +{pnl_pct:.1f}%)')
    elif pnl_diff < 0:
        print(f'WINNER: MIDPOINT-ONLY (+${-pnl_diff:,.2f} | +{-pnl_pct:.1f}%)')
    else:
        print('RESULT: TIE')
    print('='*110)

    return midpoint_stats, partial_stats


if __name__ == '__main__':
    run_comparison()
