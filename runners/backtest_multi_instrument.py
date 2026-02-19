"""
Backtest strategy across multiple instruments: ES, NQ, CL, GC.
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from collections import defaultdict
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations


# Instrument specifications
INSTRUMENTS = {
    'ES': {'tick_size': 0.25, 'tick_value': 12.50, 'min_fvg_ticks': 4, 'name': 'E-mini S&P 500'},
    'NQ': {'tick_size': 0.25, 'tick_value': 5.00, 'min_fvg_ticks': 4, 'name': 'E-mini Nasdaq'},
    'CL': {'tick_size': 0.01, 'tick_value': 10.00, 'min_fvg_ticks': 10, 'name': 'Crude Oil'},
    'GC': {'tick_size': 0.10, 'tick_value': 10.00, 'min_fvg_ticks': 10, 'name': 'Gold'},
}


def run_trade(session_bars, direction, fvg_num, tick_size, tick_value, min_fvg_ticks, contracts=3, target1_r=4, target2_r=8):
    """Run trade with Partial Fill entry."""
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'
    opposing_fvg_dir = 'BEARISH' if is_long else 'BULLISH'

    fvg_config = {
        'min_fvg_ticks': min_fvg_ticks,
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

    # Partial Fill Entry
    edge_price = entry_fvg.high if is_long else entry_fvg.low
    midpoint_price = entry_fvg.midpoint
    cts_edge = 1
    cts_midpoint = contracts - cts_edge

    fvg_stop_level = entry_fvg.low if is_long else entry_fvg.high

    # Find entry triggers
    edge_entry_bar_idx = None
    midpoint_entry_bar_idx = None

    for i in range(entry_fvg.created_bar_index + 1, len(session_bars)):
        bar = session_bars[i]

        if edge_entry_bar_idx is None:
            edge_hit = bar.low <= edge_price if is_long else bar.high >= edge_price
            if edge_hit:
                edge_entry_bar_idx = i

        if midpoint_entry_bar_idx is None:
            midpoint_hit = bar.low <= midpoint_price if is_long else bar.high >= midpoint_price
            if midpoint_hit:
                midpoint_entry_bar_idx = i
                break

    if edge_entry_bar_idx is None:
        return None

    # Calculate filled contracts and average entry
    if midpoint_entry_bar_idx is not None:
        contracts_filled = contracts
        avg_entry = (edge_price * cts_edge + midpoint_price * cts_midpoint) / contracts
        entry_bar_idx = midpoint_entry_bar_idx
        entry_time = session_bars[midpoint_entry_bar_idx].timestamp
    else:
        contracts_filled = cts_edge
        avg_entry = edge_price
        entry_bar_idx = edge_entry_bar_idx
        entry_time = session_bars[edge_entry_bar_idx].timestamp

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

    # Exit simulation
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
            exits.append({'type': 'STOP', 'pnl': pnl, 'cts': remaining})
            remaining = 0
            break

        if cts_t1 > 0:
            t1_hit = bar.high >= target_t1 if is_long else bar.low <= target_t1
            if not exited_t1 and t1_hit:
                exit_cts = min(cts_t1, remaining)
                pnl = (target_t1 - avg_entry) * exit_cts if is_long else (avg_entry - target_t1) * exit_cts
                exits.append({'type': f'T{target1_r}R', 'pnl': pnl, 'cts': exit_cts})
                remaining -= exit_cts
                exited_t1 = True

        if cts_t2 > 0:
            t2_hit = bar.high >= target_t2 if is_long else bar.low <= target_t2
            if not exited_t2 and t2_hit and remaining > cts_runner:
                exit_cts = min(cts_t2, remaining - cts_runner)
                pnl = (target_t2 - avg_entry) * exit_cts if is_long else (avg_entry - target_t2) * exit_cts
                exits.append({'type': f'T{target2_r}R', 'pnl': pnl, 'cts': exit_cts})
                remaining -= exit_cts
                exited_t2 = True

        if remaining > 0 and remaining <= cts_runner:
            opposing_fvgs = [f for f in all_fvgs if f.direction == opposing_fvg_dir
                           and f.created_bar_index > entry_bar_idx
                           and f.created_bar_index <= i]
            if opposing_fvgs:
                pnl = (bar.close - avg_entry) * remaining if is_long else (avg_entry - bar.close) * remaining
                exits.append({'type': 'OPP_FVG', 'pnl': pnl, 'cts': remaining})
                remaining = 0

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
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'was_stopped': was_stopped,
        'exits': exits,
    }


def backtest_instrument(symbol, contracts=3):
    """Run backtest for a single instrument."""

    spec = INSTRUMENTS[symbol]
    tick_size = spec['tick_size']
    tick_value = spec['tick_value']
    min_fvg_ticks = spec['min_fvg_ticks']

    print(f'\nFetching {symbol} 3m data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=10000)

    if not all_bars:
        print(f'  No data available for {symbol}')
        return None

    print(f'  Got {len(all_bars)} bars')

    # Group by date
    bars_by_date = defaultdict(list)
    for bar in all_bars:
        bars_by_date[bar.timestamp.date()].append(bar)

    trading_days = sorted(bars_by_date.keys())
    print(f'  Trading days: {len(trading_days)} ({trading_days[0]} to {trading_days[-1]})')

    # Session filter
    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)

    all_results = []

    for d in trading_days:
        day_bars = bars_by_date[d]
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        for direction in ['LONG', 'SHORT']:
            result = run_trade(session_bars, direction, 1, tick_size, tick_value, min_fvg_ticks, contracts=contracts)
            if result:
                result['date'] = d
                all_results.append(result)
                if result['was_stopped']:
                    result2 = run_trade(session_bars, direction, 2, tick_size, tick_value, min_fvg_ticks, contracts=contracts)
                    if result2:
                        result2['date'] = d
                        result2['is_reentry'] = True
                        all_results.append(result2)

    # Calculate stats
    wins = sum(1 for r in all_results if r['total_pnl'] > 0.01)
    losses = sum(1 for r in all_results if r['total_pnl'] < -0.01)
    total_pnl = sum(r['total_dollars'] for r in all_results)
    long_pnl = sum(r['total_dollars'] for r in all_results if r['direction'] == 'LONG')
    short_pnl = sum(r['total_dollars'] for r in all_results if r['direction'] == 'SHORT')
    win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0

    return {
        'symbol': symbol,
        'name': spec['name'],
        'trading_days': len(trading_days),
        'trades': len(all_results),
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'long_pnl': long_pnl,
        'short_pnl': short_pnl,
        'avg_per_trade': total_pnl / len(all_results) if all_results else 0,
        'avg_per_day': total_pnl / len(trading_days) if trading_days else 0,
        'results': all_results,
    }


def run_multi_instrument_backtest():
    """Run backtest across all instruments and compare."""

    contracts = 3

    print('='*100)
    print('MULTI-INSTRUMENT BACKTEST - ICT Strategy with Partial Fill Entry')
    print('='*100)
    print(f'Contracts: {contracts} | Entry: 1 Edge + 2 Midpoint | Exit: 4R/8R/Opposing FVG')
    print('='*100)

    results = {}

    for symbol in ['ES', 'NQ', 'CL', 'GC']:
        stats = backtest_instrument(symbol, contracts)
        if stats:
            results[symbol] = stats

    # Print comparison table
    print('\n' + '='*100)
    print('COMPARISON SUMMARY')
    print('='*100)
    print(f'{"Symbol":<8} {"Name":<20} {"Days":>6} {"Trades":>8} {"Wins":>6} {"Losses":>8} {"Win%":>8} {"Total P/L":>15} {"Avg/Trade":>12}')
    print('-'*100)

    for symbol, stats in results.items():
        print(f'{symbol:<8} {stats["name"]:<20} {stats["trading_days"]:>6} {stats["trades"]:>8} {stats["wins"]:>6} {stats["losses"]:>8} {stats["win_rate"]:>7.1f}% ${stats["total_pnl"]:>13,.2f} ${stats["avg_per_trade"]:>10,.2f}')

    # Print detailed results for each instrument
    for symbol, stats in results.items():
        print(f'\n{"-"*100}')
        print(f'{symbol} - {stats["name"]} DETAILS')
        print(f'{"-"*100}')
        print(f'{"Date":<12} {"Dir":<6} {"Cts":>4} {"Entry":>12} {"P/L":>12} {"Result":<8}')
        print('-'*60)

        for r in stats['results']:
            result_str = 'WIN' if r['total_pnl'] > 0.01 else 'LOSS' if r['total_pnl'] < -0.01 else 'BE'
            tag = ' [RE]' if r.get('is_reentry') else ''
            print(f'{str(r["date"]):<12} {r["direction"]:<6} {r["contracts_filled"]:>4} {r["entry_price"]:>12.2f} ${r["total_dollars"]:>10,.2f} {result_str:<8}{tag}')

        print(f'\n  Long P/L:  ${stats["long_pnl"]:>12,.2f}')
        print(f'  Short P/L: ${stats["short_pnl"]:>12,.2f}')
        print(f'  TOTAL:     ${stats["total_pnl"]:>12,.2f}')

    # Find best instrument
    print('\n' + '='*100)
    if results:
        best = max(results.values(), key=lambda x: x['total_pnl'])
        print(f'BEST INSTRUMENT: {best["symbol"]} ({best["name"]}) with ${best["total_pnl"]:,.2f}')
    print('='*100)

    return results


if __name__ == '__main__':
    run_multi_instrument_backtest()
