"""
Compare different runner exit strategies.
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from collections import defaultdict
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations


def calculate_ema(closes, period):
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


def run_trade_with_runner_strategy(session_bars, direction, fvg_num, runner_strategy='ema50',
                                    tick_size=0.25, tick_value=12.50, contracts=3,
                                    target1_r=4, target2_r=8):
    """
    Run trade with different runner exit strategies:
    - 'ema50': Exit on close below/above EMA50 (current)
    - 'trail_2pt': Fixed 2-point trailing stop
    - 'trail_1r': Trail by 1x risk
    - 'prev_bar': Use previous bar's low (long) or high (short)
    - 'fixed_12r': Take profit at 12R
    - 'fixed_16r': Take profit at 16R
    - 'time_1530': Exit at 15:30
    - 'ema21': Exit on close below/above EMA21 (faster)
    """
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'

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
    target_12r = entry_price + (12 * risk) if is_long else entry_price - (12 * risk)
    target_16r = entry_price + (16 * risk) if is_long else entry_price - (16 * risk)

    closes = [b.close for b in session_bars]
    ema_50 = calculate_ema(closes, 50)
    ema_21 = calculate_ema(closes, 21)

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

    # Contract allocation
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

    # Trailing stop tracking
    trail_stop = None
    highest_price = entry_price if is_long else None
    lowest_price = entry_price if not is_long else None

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]
        bar_ema50 = ema_50[i] if i < len(ema_50) and ema_50[i] else None
        bar_ema21 = ema_21[i] if i < len(ema_21) and ema_21[i] else None

        # Check FVG mitigation stop (for all contracts)
        stop_hit = bar.close < fvg_stop_level if is_long else bar.close > fvg_stop_level
        if stop_hit:
            pnl = (bar.close - entry_price) * remaining if is_long else (entry_price - bar.close) * remaining
            exits.append({'type': 'STOP', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': remaining})
            remaining = 0
            break

        # Check T1
        t1_hit = bar.high >= target_t1 if is_long else bar.low <= target_t1
        if not exited_t1 and t1_hit:
            exit_cts = min(cts_t1, remaining)
            pnl = (target_t1 - entry_price) * exit_cts if is_long else (entry_price - target_t1) * exit_cts
            exits.append({'type': f'T{target1_r}R', 'pnl': pnl, 'price': target_t1, 'time': bar.timestamp, 'cts': exit_cts})
            remaining -= exit_cts
            exited_t1 = True

        # Check T2
        t2_hit = bar.high >= target_t2 if is_long else bar.low <= target_t2
        if not exited_t2 and t2_hit and remaining > cts_runner:
            exit_cts = min(cts_t2, remaining - cts_runner)
            pnl = (target_t2 - entry_price) * exit_cts if is_long else (entry_price - target_t2) * exit_cts
            exits.append({'type': f'T{target2_r}R', 'pnl': pnl, 'price': target_t2, 'time': bar.timestamp, 'cts': exit_cts})
            remaining -= exit_cts
            exited_t2 = True

        # Runner exit logic (only when we're down to runner contracts)
        if remaining > 0 and remaining <= cts_runner:
            runner_exit = False
            exit_price = None
            exit_type = None

            # Update trailing info
            if is_long:
                if bar.high > highest_price:
                    highest_price = bar.high
            else:
                if bar.low < lowest_price:
                    lowest_price = bar.low

            if runner_strategy == 'ema50':
                if bar_ema50:
                    if is_long and bar.close < bar_ema50:
                        runner_exit = True
                        exit_price = bar.close
                        exit_type = 'EMA50'
                    elif not is_long and bar.close > bar_ema50:
                        runner_exit = True
                        exit_price = bar.close
                        exit_type = 'EMA50'

            elif runner_strategy == 'ema21':
                if bar_ema21:
                    if is_long and bar.close < bar_ema21:
                        runner_exit = True
                        exit_price = bar.close
                        exit_type = 'EMA21'
                    elif not is_long and bar.close > bar_ema21:
                        runner_exit = True
                        exit_price = bar.close
                        exit_type = 'EMA21'

            elif runner_strategy == 'trail_2pt':
                if is_long:
                    trail_stop = highest_price - 2.0
                    if bar.low <= trail_stop:
                        runner_exit = True
                        exit_price = trail_stop
                        exit_type = 'TRAIL_2PT'
                else:
                    trail_stop = lowest_price + 2.0
                    if bar.high >= trail_stop:
                        runner_exit = True
                        exit_price = trail_stop
                        exit_type = 'TRAIL_2PT'

            elif runner_strategy == 'trail_1r':
                if is_long:
                    trail_stop = highest_price - risk
                    if bar.low <= trail_stop:
                        runner_exit = True
                        exit_price = trail_stop
                        exit_type = 'TRAIL_1R'
                else:
                    trail_stop = lowest_price + risk
                    if bar.high >= trail_stop:
                        runner_exit = True
                        exit_price = trail_stop
                        exit_type = 'TRAIL_1R'

            elif runner_strategy == 'prev_bar':
                prev_bar = session_bars[i - 1]
                if is_long and bar.close < prev_bar.low:
                    runner_exit = True
                    exit_price = bar.close
                    exit_type = 'PREV_BAR'
                elif not is_long and bar.close > prev_bar.high:
                    runner_exit = True
                    exit_price = bar.close
                    exit_type = 'PREV_BAR'

            elif runner_strategy == 'fixed_12r':
                if is_long and bar.high >= target_12r:
                    runner_exit = True
                    exit_price = target_12r
                    exit_type = 'T12R'
                elif not is_long and bar.low <= target_12r:
                    runner_exit = True
                    exit_price = target_12r
                    exit_type = 'T12R'

            elif runner_strategy == 'fixed_16r':
                if is_long and bar.high >= target_16r:
                    runner_exit = True
                    exit_price = target_16r
                    exit_type = 'T16R'
                elif not is_long and bar.low <= target_16r:
                    runner_exit = True
                    exit_price = target_16r
                    exit_type = 'T16R'

            elif runner_strategy == 'time_1530':
                if bar.timestamp.time() >= dt_time(15, 30):
                    runner_exit = True
                    exit_price = bar.close
                    exit_type = 'TIME_1530'

            if runner_exit and exit_price:
                pnl = (exit_price - entry_price) * remaining if is_long else (entry_price - exit_price) * remaining
                exits.append({'type': exit_type, 'pnl': pnl, 'price': exit_price, 'time': bar.timestamp, 'cts': remaining})
                remaining = 0

    # EOD close
    if remaining > 0:
        last_bar = session_bars[-1]
        pnl = (last_bar.close - entry_price) * remaining if is_long else (entry_price - last_bar.close) * remaining
        exits.append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'cts': remaining})

    total_pnl = sum(e['pnl'] for e in exits)
    total_dollars = (total_pnl / tick_size) * tick_value
    was_stopped = any(e['type'] == 'STOP' for e in exits)

    # Calculate runner-specific P/L
    runner_exits = [e for e in exits if e['type'] not in [f'T{target1_r}R', f'T{target2_r}R', 'STOP']]
    runner_pnl = sum((e['pnl'] / tick_size) * tick_value for e in runner_exits)

    return {
        'direction': direction,
        'entry_time': entry_time,
        'entry_price': entry_price,
        'stop_price': stop_price,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'runner_dollars': runner_pnl,
        'was_stopped': was_stopped,
        'exits': exits,
    }


def run_backtest_with_runner_strategy(runner_strategy, all_bars, contracts=3):
    """Run full backtest with a specific runner strategy."""

    bars_by_date = defaultdict(list)
    for bar in all_bars:
        bars_by_date[bar.timestamp.date()].append(bar)

    trading_days = sorted(bars_by_date.keys())

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)

    all_results = []

    for d in trading_days:
        day_bars = bars_by_date[d]
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Try LONG
        result = run_trade_with_runner_strategy(session_bars, 'LONG', 1, runner_strategy, contracts=contracts)
        if result:
            result['date'] = d
            all_results.append(result)
            if result['was_stopped']:
                result2 = run_trade_with_runner_strategy(session_bars, 'LONG', 2, runner_strategy, contracts=contracts)
                if result2:
                    result2['date'] = d
                    result2['is_reentry'] = True
                    all_results.append(result2)

        # Try SHORT
        result = run_trade_with_runner_strategy(session_bars, 'SHORT', 1, runner_strategy, contracts=contracts)
        if result:
            result['date'] = d
            all_results.append(result)
            if result['was_stopped']:
                result2 = run_trade_with_runner_strategy(session_bars, 'SHORT', 2, runner_strategy, contracts=contracts)
                if result2:
                    result2['date'] = d
                    result2['is_reentry'] = True
                    all_results.append(result2)

    return all_results


def calculate_stats(results):
    """Calculate statistics from results."""
    wins = len([r for r in results if r['total_pnl'] > 0.01])
    losses = len([r for r in results if r['total_pnl'] < -0.01])
    total_pnl = sum(r['total_dollars'] for r in results)
    runner_pnl = sum(r['runner_dollars'] for r in results)

    winning_pnl = sum(r['total_dollars'] for r in results if r['total_dollars'] > 0)
    losing_pnl = sum(r['total_dollars'] for r in results if r['total_dollars'] < 0)

    win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
    profit_factor = abs(winning_pnl / losing_pnl) if losing_pnl < 0 else float('inf')

    return {
        'trades': len(results),
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'runner_pnl': runner_pnl,
        'profit_factor': profit_factor,
    }


def main():
    print('Fetching ES 3m data...')
    all_bars = fetch_futures_bars(symbol='ES', interval='3m', n_bars=10000)

    if not all_bars:
        print('No data available')
        return

    print(f'Got {len(all_bars)} bars')

    bars_by_date = defaultdict(list)
    for bar in all_bars:
        bars_by_date[bar.timestamp.date()].append(bar)
    trading_days = sorted(bars_by_date.keys())
    print(f'Trading days: {len(trading_days)} ({trading_days[0]} to {trading_days[-1]})')

    strategies = ['ema50', 'ema21', 'trail_2pt', 'trail_1r', 'prev_bar', 'fixed_12r', 'fixed_16r', 'time_1530']
    strategy_names = {
        'ema50': 'EMA50 Cross (current)',
        'ema21': 'EMA21 Cross (faster)',
        'trail_2pt': 'Trailing Stop (2 pts)',
        'trail_1r': 'Trailing Stop (1R)',
        'prev_bar': 'Previous Bar Low/High',
        'fixed_12r': 'Fixed 12R Target',
        'fixed_16r': 'Fixed 16R Target',
        'time_1530': 'Time Exit (15:30)',
    }

    print()
    print('='*90)
    print('RUNNER EXIT STRATEGY COMPARISON - ES 3m - 3 Contracts - 15 Day Backtest')
    print('='*90)
    print()
    print('Note: 4R and 8R exits are the same across all strategies.')
    print('Only the RUNNER (3rd contract) exit differs.')
    print()

    all_stats = {}

    for strategy in strategies:
        print(f'Testing {strategy_names[strategy]}...')
        results = run_backtest_with_runner_strategy(strategy, all_bars)
        stats = calculate_stats(results)
        all_stats[strategy] = stats

    # Print comparison table
    print()
    print('='*90)
    print('COMPARISON SUMMARY')
    print('='*90)
    print()
    print(f'{"Strategy":<28} {"Trades":<8} {"W/L":<10} {"Total P/L":<14} {"Runner P/L":<14} {"PF":<8}')
    print('-'*90)

    for strategy in strategies:
        s = all_stats[strategy]
        pf_str = f'{s["profit_factor"]:.2f}' if s["profit_factor"] != float('inf') else 'inf'
        print(f'{strategy_names[strategy]:<28} {s["trades"]:<8} {s["wins"]}W/{s["losses"]}L{"":<3} '
              f'${s["total_pnl"]:>+10,.2f}   ${s["runner_pnl"]:>+10,.2f}   {pf_str:<8}')

    # Find best strategy
    best_strategy = max(all_stats.keys(), key=lambda x: all_stats[x]['total_pnl'])
    best_pnl = all_stats[best_strategy]['total_pnl']
    current_pnl = all_stats['ema50']['total_pnl']
    improvement = best_pnl - current_pnl

    # Best runner P/L
    best_runner = max(all_stats.keys(), key=lambda x: all_stats[x]['runner_pnl'])
    best_runner_pnl = all_stats[best_runner]['runner_pnl']
    current_runner_pnl = all_stats['ema50']['runner_pnl']

    print()
    print('='*90)
    print('ANALYSIS')
    print('='*90)
    print()
    print(f'Best Overall P/L:     {strategy_names[best_strategy]}')
    print(f'                      ${best_pnl:+,.2f} (vs EMA50: ${improvement:+,.2f})')
    print()
    print(f'Best Runner P/L:      {strategy_names[best_runner]}')
    print(f'                      ${best_runner_pnl:+,.2f} (vs EMA50: ${best_runner_pnl - current_runner_pnl:+,.2f})')
    print()

    # Detailed breakdown for top 3
    print('='*90)
    print('TOP 3 STRATEGIES - DETAILED BREAKDOWN')
    print('='*90)

    sorted_strategies = sorted(all_stats.keys(), key=lambda x: all_stats[x]['total_pnl'], reverse=True)[:3]

    for strategy in sorted_strategies:
        print(f'\n{strategy_names[strategy]}:')
        results = run_backtest_with_runner_strategy(strategy, all_bars)
        for r in results:
            tag = ' [RE]' if r.get('is_reentry') else ''
            result_str = 'WIN' if r['total_pnl'] > 0.01 else 'LOSS' if r['total_pnl'] < -0.01 else 'BE'
            runner_exit = [e for e in r['exits'] if e['type'] not in ['T4R', 'T8R', 'STOP']]
            runner_type = runner_exit[0]['type'] if runner_exit else 'N/A'
            print(f"  {r['date']} | {r['direction']:5} | {result_str:4} | Total: ${r['total_dollars']:+,.2f} | Runner: ${r['runner_dollars']:+,.2f} ({runner_type}){tag}")


if __name__ == '__main__':
    main()
