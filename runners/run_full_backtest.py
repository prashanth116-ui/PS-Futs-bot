"""
Run full backtest with re-entry strategy across all available data.
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from collections import defaultdict
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations


def calculate_ema(closes, period):
    """Calculate EMA for a list of closes."""
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


def run_trade(session_bars, direction, fvg_num, tick_size=0.25, tick_value=12.50, contracts=3, target1_r=4, target2_r=8):
    """Run single trade simulation with Partial Fill entry, FVG Mitigation stop, and Opposing FVG runner exit.

    Entry Logic: Partial Fill
    - 1 contract at FVG edge (higher fill rate)
    - 2 contracts at FVG midpoint (better price)

    Stop Logic: FVG Mitigation
    - Only exit if candle CLOSES through FVG boundary
    - Ignores wicks/spikes that don't invalidate the FVG

    Runner Exit: Opposing FVG
    - Exit runner when a Fair Value Gap forms in the opposite direction
    - LONG: Exit when Bearish FVG forms (sellers stepping in)
    - SHORT: Exit when Bullish FVG forms (buyers stepping in)
    """
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'
    opposing_fvg_dir = 'BEARISH' if is_long else 'BULLISH'

    # Detect FVGs
    fvg_config = {
        'min_fvg_ticks': 4,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)
    update_all_fvg_mitigations(all_fvgs, session_bars, fvg_config)

    # Get active FVGs
    active_fvgs = [f for f in all_fvgs if f.direction == fvg_dir and not f.mitigated]
    active_fvgs.sort(key=lambda f: f.created_bar_index)

    if len(active_fvgs) < fvg_num:
        return None

    entry_fvg = active_fvgs[fvg_num - 1]

    # Partial Fill Entry Levels
    edge_price = entry_fvg.high if is_long else entry_fvg.low  # Edge (closer to price)
    midpoint_price = entry_fvg.midpoint

    # Contracts at each level
    cts_edge = 1
    cts_midpoint = contracts - cts_edge  # 2 contracts at midpoint

    # FVG boundaries for mitigation stop
    fvg_stop_level = entry_fvg.low if is_long else entry_fvg.high

    # Find entry triggers for both levels
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
        # Both filled - full position
        contracts_filled = contracts
        avg_entry = (edge_price * cts_edge + midpoint_price * cts_midpoint) / contracts
        entry_bar_idx = midpoint_entry_bar_idx
        entry_time = midpoint_entry_time
    else:
        # Only edge filled - partial position
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

    if risk <= 0:
        return None

    target_t1 = avg_entry + (target1_r * risk) if is_long else avg_entry - (target1_r * risk)
    target_t2 = avg_entry + (target2_r * risk) if is_long else avg_entry - (target2_r * risk)

    # Simulate exits based on filled contracts
    if contracts_filled == contracts:
        cts_t1 = contracts // 3
        cts_t2 = contracts // 3
        cts_runner = contracts - cts_t1 - cts_t2
        if cts_t1 == 0:
            cts_t1 = 1
        if cts_t2 == 0:
            cts_t2 = 1
        if cts_runner == 0:
            cts_runner = 1
    else:
        # Only 1 contract filled - all goes to runner
        cts_t1 = 0
        cts_t2 = 0
        cts_runner = contracts_filled

    exits = []
    remaining = contracts_filled
    exited_t1 = False
    exited_t2 = False

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]

        # Check stop - FVG Mitigation: only stop if candle CLOSES through FVG boundary
        stop_hit = bar.close < fvg_stop_level if is_long else bar.close > fvg_stop_level
        if stop_hit:
            pnl = (bar.close - avg_entry) * remaining if is_long else (avg_entry - bar.close) * remaining
            exits.append({'type': 'STOP', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': remaining})
            remaining = 0
            break

        # Check T1 - exit portion of contracts (only if full fill)
        if cts_t1 > 0:
            t1_hit = bar.high >= target_t1 if is_long else bar.low <= target_t1
            if not exited_t1 and t1_hit:
                exit_cts = min(cts_t1, remaining)
                pnl = (target_t1 - avg_entry) * exit_cts if is_long else (avg_entry - target_t1) * exit_cts
                exits.append({'type': f'T{target1_r}R', 'pnl': pnl, 'price': target_t1, 'time': bar.timestamp, 'cts': exit_cts})
                remaining -= exit_cts
                exited_t1 = True

        # Check T2 - exit portion of contracts (only if full fill)
        if cts_t2 > 0:
            t2_hit = bar.high >= target_t2 if is_long else bar.low <= target_t2
            if not exited_t2 and t2_hit and remaining > cts_runner:
                exit_cts = min(cts_t2, remaining - cts_runner)
                pnl = (target_t2 - avg_entry) * exit_cts if is_long else (avg_entry - target_t2) * exit_cts
                exits.append({'type': f'T{target2_r}R', 'pnl': pnl, 'price': target_t2, 'time': bar.timestamp, 'cts': exit_cts})
                remaining -= exit_cts
                exited_t2 = True

        # Check Opposing FVG runner exit
        if remaining > 0 and remaining <= cts_runner:
            opposing_fvgs = [f for f in all_fvgs if f.direction == opposing_fvg_dir
                           and f.created_bar_index > entry_bar_idx
                           and f.created_bar_index <= i]
            if opposing_fvgs:
                pnl = (bar.close - avg_entry) * remaining if is_long else (avg_entry - bar.close) * remaining
                exits.append({'type': 'OPP_FVG', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': remaining})
                remaining = 0

    # EOD close if still holding
    if remaining > 0:
        last_bar = session_bars[-1]
        pnl = (last_bar.close - avg_entry) * remaining if is_long else (avg_entry - last_bar.close) * remaining
        exits.append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'cts': remaining})

    total_pnl = sum(e['pnl'] for e in exits)
    total_dollars = (total_pnl / tick_size) * tick_value
    was_stopped = any(e['type'] == 'STOP' for e in exits)

    return {
        'direction': direction,
        'entry_time': entry_time,
        'entry_price': avg_entry,
        'contracts_filled': contracts_filled,
        'stop_price': stop_price,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'was_stopped': was_stopped,
        'exits': exits,
    }


def run_full_backtest(symbol='ES', interval='3m', n_bars=10000, contracts=3, target1_r=4, target2_r=8):
    """Run full backtest with re-entry strategy."""

    # Fetch all data at once
    print(f'Fetching {symbol} {interval} data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval=interval, n_bars=n_bars)

    if not all_bars:
        print('No data available')
        return []

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

    print('\n' + '='*80)
    print(f'{len(trading_days)}-DAY BACKTEST - {symbol} {interval} - Partial Fill Entry - {contracts} CONTRACTS')
    print('='*80)
    print(f'Entry: 1 ct @ Edge, {contracts-1} cts @ Midpoint')
    print(f'Exit: {contracts//3} cts @ {target1_r}R, {contracts//3} cts @ {target2_r}R, {contracts - 2*(contracts//3)} cts @ Opposing FVG')
    print('='*80)

    all_results = []

    for d in trading_days:
        day_bars = bars_by_date[d]
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Try LONG
        result = run_trade(session_bars, 'LONG', 1, contracts=contracts, target1_r=target1_r, target2_r=target2_r)
        if result:
            result['date'] = d
            all_results.append(result)
            if result['was_stopped']:
                result2 = run_trade(session_bars, 'LONG', 2, contracts=contracts, target1_r=target1_r, target2_r=target2_r)
                if result2:
                    result2['date'] = d
                    result2['is_reentry'] = True
                    all_results.append(result2)

        # Try SHORT
        result = run_trade(session_bars, 'SHORT', 1, contracts=contracts, target1_r=target1_r, target2_r=target2_r)
        if result:
            result['date'] = d
            all_results.append(result)
            if result['was_stopped']:
                result2 = run_trade(session_bars, 'SHORT', 2, contracts=contracts, target1_r=target1_r, target2_r=target2_r)
                if result2:
                    result2['date'] = d
                    result2['is_reentry'] = True
                    all_results.append(result2)

    # Print results
    wins = 0
    losses = 0
    breakeven = 0
    long_pnl = 0
    short_pnl = 0
    reentries = 0
    losing_trades_pnl = 0

    for r in all_results:
        if r['total_pnl'] > 0.01:
            wins += 1
        elif r['total_pnl'] < -0.01:
            losses += 1
            losing_trades_pnl += r['total_dollars']
        else:
            breakeven += 1

        if r['direction'] == 'LONG':
            long_pnl += r['total_dollars']
        else:
            short_pnl += r['total_dollars']

        if r.get('is_reentry'):
            reentries += 1

        tag = ' [RE-ENTRY]' if r.get('is_reentry') else ''
        result_str = 'WIN' if r['total_pnl'] > 0.01 else 'LOSS' if r['total_pnl'] < -0.01 else 'BE'
        print(f"  {r['date']} | {r['direction']:5} | {r['entry_time'].strftime('%H:%M')} | {result_str:4} | ${r['total_dollars']:+,.2f}{tag}")

    total_trades = len(all_results)
    total_pnl = long_pnl + short_pnl
    win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
    profit_factor = abs(total_pnl) / abs(losing_trades_pnl) if losing_trades_pnl < 0 else float('inf')

    print('\n' + '='*80)
    print('SUMMARY')
    print('='*80)
    print(f'  Total Trades:   {total_trades} ({reentries} re-entries)')
    print(f'  Win Rate:       {wins}W / {losses}L / {breakeven}BE = {win_rate:.1f}%')
    print(f'  Long P/L:       ${long_pnl:+,.2f}')
    print(f'  Short P/L:      ${short_pnl:+,.2f}')
    print(f'  TOTAL P/L:      ${total_pnl:+,.2f}')
    print()
    if total_trades > 0:
        print(f'  Avg per Trade:  ${total_pnl/total_trades:+,.2f}')
    print(f'  Avg per Day:    ${total_pnl/len(trading_days):+,.2f}')
    print(f'  Profit Factor:  {profit_factor:.2f}')

    return all_results


if __name__ == '__main__':
    import sys
    contracts = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    results = run_full_backtest('ES', '3m', 10000, contracts=contracts)
