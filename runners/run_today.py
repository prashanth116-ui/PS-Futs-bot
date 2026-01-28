"""
Run backtest for today with Partial Fill entry.
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations


def run_trade(session_bars, direction, fvg_num, tick_size=0.25, tick_value=12.50, contracts=3, target1_r=4, target2_r=8):
    """Run trade with Partial Fill entry (1 at edge, 2 at midpoint)."""
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'
    opposing_fvg_dir = 'BEARISH' if is_long else 'BULLISH'

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

    # Partial Fill Entry Levels
    edge_price = entry_fvg.high if is_long else entry_fvg.low
    midpoint_price = entry_fvg.midpoint

    # Contracts at each level
    cts_edge = 1
    cts_midpoint = contracts - cts_edge

    fvg_stop_level = entry_fvg.low if is_long else entry_fvg.high

    # Find entry triggers for both levels
    edge_entry_bar_idx = None
    edge_entry_time = None
    midpoint_entry_bar_idx = None
    midpoint_entry_time = None

    for i in range(entry_fvg.created_bar_index + 1, len(session_bars)):
        bar = session_bars[i]

        if edge_entry_bar_idx is None:
            edge_hit = bar.low <= edge_price if is_long else bar.high >= edge_price
            if edge_hit:
                edge_entry_bar_idx = i
                edge_entry_time = bar.timestamp

        if midpoint_entry_bar_idx is None:
            midpoint_hit = bar.low <= midpoint_price if is_long else bar.high >= midpoint_price
            if midpoint_hit:
                midpoint_entry_bar_idx = i
                midpoint_entry_time = bar.timestamp
                break

    if edge_entry_bar_idx is None:
        return None

    # Calculate filled contracts and average entry
    if midpoint_entry_bar_idx is not None:
        contracts_filled = contracts
        avg_entry = (edge_price * cts_edge + midpoint_price * cts_midpoint) / contracts
        entry_bar_idx = midpoint_entry_bar_idx
        entry_time = midpoint_entry_time
        fill_type = 'FULL'
    else:
        contracts_filled = cts_edge
        avg_entry = edge_price
        entry_bar_idx = edge_entry_bar_idx
        entry_time = edge_entry_time
        fill_type = 'EDGE'

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
        if cts_t1 == 0: cts_t1 = 1
        if cts_t2 == 0: cts_t2 = 1
        if cts_runner == 0: cts_runner = 1
    else:
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

        stop_hit = bar.close < fvg_stop_level if is_long else bar.close > fvg_stop_level
        if stop_hit:
            pnl = (bar.close - avg_entry) * remaining if is_long else (avg_entry - bar.close) * remaining
            exits.append({'type': 'STOP', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': remaining})
            remaining = 0
            break

        if cts_t1 > 0:
            t1_hit = bar.high >= target_t1 if is_long else bar.low <= target_t1
            if not exited_t1 and t1_hit:
                exit_cts = min(cts_t1, remaining)
                pnl = (target_t1 - avg_entry) * exit_cts if is_long else (avg_entry - target_t1) * exit_cts
                exits.append({'type': f'T{target1_r}R', 'pnl': pnl, 'price': target_t1, 'time': bar.timestamp, 'cts': exit_cts})
                remaining -= exit_cts
                exited_t1 = True

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
        'edge_price': edge_price,
        'midpoint_price': midpoint_price,
        'contracts_filled': contracts_filled,
        'fill_type': fill_type,
        'stop_price': stop_price,
        'fvg_low': entry_fvg.low,
        'fvg_high': entry_fvg.high,
        'target_4r': target_t1,
        'target_8r': target_t2,
        'risk': risk,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'was_stopped': was_stopped,
        'exits': exits,
    }


def run_today(symbol='ES', contracts=3):
    """Run backtest for today with Partial Fill entry."""

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25

    print(f'Fetching {symbol} 3m data for today...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=1000)

    if all_bars:
        today = all_bars[-1].timestamp.date()
    else:
        print('No data available')
        return []

    today_bars = [b for b in all_bars if b.timestamp.date() == today]

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

    print(f'Date: {today}')
    print(f'Session bars: {len(session_bars)}')
    print()
    print('='*70)
    print(f'{symbol} BACKTEST - {today} - {contracts} Contracts - Partial Fill')
    print('='*70)
    print(f'Entry: 1 ct @ Edge, {contracts-1} cts @ Midpoint')
    print('='*70)

    all_results = []

    # Try LONG
    result = run_trade(session_bars, 'LONG', 1, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
    if result:
        result['date'] = today
        all_results.append(result)
        if result['was_stopped']:
            result2 = run_trade(session_bars, 'LONG', 2, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
            if result2:
                result2['date'] = today
                result2['is_reentry'] = True
                all_results.append(result2)

    # Try SHORT
    result = run_trade(session_bars, 'SHORT', 1, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
    if result:
        result['date'] = today
        all_results.append(result)
        if result['was_stopped']:
            result2 = run_trade(session_bars, 'SHORT', 2, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
            if result2:
                result2['date'] = today
                result2['is_reentry'] = True
                all_results.append(result2)

    total_pnl = 0
    for r in all_results:
        tag = ' [RE-ENTRY]' if r.get('is_reentry') else ''
        result_str = 'WIN' if r['total_pnl'] > 0.01 else 'LOSS' if r['total_pnl'] < -0.01 else 'BE'
        total_pnl += r['total_dollars']

        print(f"\n{r['direction']} TRADE{tag}")
        print(f"  Fill: {r['fill_type']} ({r['contracts_filled']} cts)")
        print(f"  Entry: {r['entry_price']:.2f} @ {r['entry_time'].strftime('%H:%M')}")
        print(f"    Edge: {r['edge_price']:.2f} | Midpoint: {r['midpoint_price']:.2f}")
        print(f"  FVG: {r['fvg_low']:.2f} - {r['fvg_high']:.2f}")
        print(f"  Stop: {r['stop_price']:.2f} (FVG mitigation)")
        print(f"  Risk: {r['risk']:.2f} pts")
        print(f"  Targets: 4R={r['target_4r']:.2f}, 8R={r['target_8r']:.2f}")
        print(f"  Exits:")
        for e in r['exits']:
            dollars = (e['pnl'] / tick_size) * tick_value
            print(f"    {e['type']}: {e['cts']} ct @ {e['price']:.2f} = ${dollars:+,.2f}")
        print(f"  Result: {result_str} | P/L: ${r['total_dollars']:+,.2f}")

    print()
    print('='*70)
    print(f'TOTAL P/L: ${total_pnl:+,.2f}')
    print('='*70)

    return all_results


if __name__ == '__main__':
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    contracts = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    run_today(symbol=symbol, contracts=contracts)
