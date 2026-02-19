"""
Compare different stop loss strategies across 15-day backtest.
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


def run_trade_with_stop_strategy(session_bars, direction, fvg_num, stop_strategy='current',
                                  tick_size=0.25, tick_value=12.50, contracts=3,
                                  target1_r=4, target2_r=8):
    """
    Run trade with different stop strategies:
    - 'current': FVG high/low + 2 ticks
    - 'wider': FVG high/low + 4 ticks (1 point)
    - 'mitigation': Only stop on candle CLOSE through FVG
    - 'delayed': Ignore stops for first 3 bars
    """
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'

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

    # Calculate entry and base stop
    entry_price = entry_fvg.midpoint

    if is_long:
        base_stop = entry_fvg.low
        # Stop buffer based on strategy
        if stop_strategy == 'current':
            stop_price = base_stop - (2 * tick_size)  # 2 ticks
        elif stop_strategy == 'wider':
            stop_price = base_stop - (4 * tick_size)  # 4 ticks (1 point)
        elif stop_strategy == 'mitigation':
            stop_price = base_stop  # Will check close instead of wick
        elif stop_strategy == 'delayed':
            stop_price = base_stop - (2 * tick_size)  # Same as current but delayed
        risk = entry_price - stop_price
    else:
        base_stop = entry_fvg.high
        if stop_strategy == 'current':
            stop_price = base_stop + (2 * tick_size)
        elif stop_strategy == 'wider':
            stop_price = base_stop + (4 * tick_size)
        elif stop_strategy == 'mitigation':
            stop_price = base_stop
        elif stop_strategy == 'delayed':
            stop_price = base_stop + (2 * tick_size)
        risk = stop_price - entry_price

    target_t1 = entry_price + (target1_r * risk) if is_long else entry_price - (target1_r * risk)
    target_t2 = entry_price + (target2_r * risk) if is_long else entry_price - (target2_r * risk)

    # Calculate EMAs
    closes = [b.close for b in session_bars]
    ema_50 = calculate_ema(closes, 50)

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

    # Delayed stop: ignore stops for first N bars
    delay_bars = 3 if stop_strategy == 'delayed' else 0

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]
        bar_ema50 = ema_50[i] if i < len(ema_50) and ema_50[i] else None
        bars_since_entry = i - entry_bar_idx

        # Check stop based on strategy
        stop_hit = False

        if stop_strategy == 'mitigation':
            # Only stop on CLOSE through FVG boundary
            if is_long:
                stop_hit = bar.close < entry_fvg.low
            else:
                stop_hit = bar.close > entry_fvg.high
        elif stop_strategy == 'delayed':
            # Ignore stops for first N bars
            if bars_since_entry > delay_bars:
                stop_hit = bar.low <= stop_price if is_long else bar.high >= stop_price
        else:
            # Current and wider: standard stop check
            stop_hit = bar.low <= stop_price if is_long else bar.high >= stop_price

        if stop_hit:
            if stop_strategy == 'mitigation':
                # Exit at close price for mitigation strategy
                exit_price = bar.close
            else:
                exit_price = stop_price
            pnl = (exit_price - entry_price) * remaining if is_long else (entry_price - exit_price) * remaining
            exits.append({'type': 'STOP', 'pnl': pnl, 'price': exit_price, 'time': bar.timestamp, 'cts': remaining})
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

        # Check EMA50 runner exit
        if remaining > 0 and remaining <= cts_runner and bar_ema50:
            ema_exit = bar.close < bar_ema50 if is_long else bar.close > bar_ema50
            if ema_exit:
                pnl = (bar.close - entry_price) * remaining if is_long else (entry_price - bar.close) * remaining
                exits.append({'type': 'EMA50', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': remaining})
                remaining = 0

    # EOD close
    if remaining > 0:
        last_bar = session_bars[-1]
        pnl = (last_bar.close - entry_price) * remaining if is_long else (entry_price - last_bar.close) * remaining
        exits.append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'cts': remaining})

    total_pnl = sum(e['pnl'] for e in exits)
    total_dollars = (total_pnl / tick_size) * tick_value
    was_stopped = any(e['type'] == 'STOP' for e in exits)

    return {
        'direction': direction,
        'entry_time': entry_time,
        'entry_price': entry_price,
        'stop_price': stop_price,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'was_stopped': was_stopped,
        'exits': exits,
    }


def run_backtest_with_strategy(stop_strategy, all_bars, contracts=3, target1_r=4, target2_r=8):
    """Run full backtest with a specific stop strategy."""

    # Group by date
    bars_by_date = defaultdict(list)
    for bar in all_bars:
        bars_by_date[bar.timestamp.date()].append(bar)

    trading_days = sorted(bars_by_date.keys())

    # Session filter
    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)

    all_results = []

    for d in trading_days:
        day_bars = bars_by_date[d]
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Try LONG
        result = run_trade_with_stop_strategy(session_bars, 'LONG', 1, stop_strategy,
                                               contracts=contracts, target1_r=target1_r, target2_r=target2_r)
        if result:
            result['date'] = d
            all_results.append(result)
            if result['was_stopped']:
                result2 = run_trade_with_stop_strategy(session_bars, 'LONG', 2, stop_strategy,
                                                        contracts=contracts, target1_r=target1_r, target2_r=target2_r)
                if result2:
                    result2['date'] = d
                    result2['is_reentry'] = True
                    all_results.append(result2)

        # Try SHORT
        result = run_trade_with_stop_strategy(session_bars, 'SHORT', 1, stop_strategy,
                                               contracts=contracts, target1_r=target1_r, target2_r=target2_r)
        if result:
            result['date'] = d
            all_results.append(result)
            if result['was_stopped']:
                result2 = run_trade_with_stop_strategy(session_bars, 'SHORT', 2, stop_strategy,
                                                        contracts=contracts, target1_r=target1_r, target2_r=target2_r)
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

    winning_pnl = sum(r['total_dollars'] for r in results if r['total_dollars'] > 0)
    losing_pnl = sum(r['total_dollars'] for r in results if r['total_dollars'] < 0)

    win_rate = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
    profit_factor = abs(winning_pnl / losing_pnl) if losing_pnl < 0 else float('inf')
    avg_win = winning_pnl / wins if wins > 0 else 0
    avg_loss = losing_pnl / losses if losses > 0 else 0

    stopped_trades = len([r for r in results if r['was_stopped']])
    reentries = len([r for r in results if r.get('is_reentry')])

    return {
        'trades': len(results),
        'wins': wins,
        'losses': losses,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'profit_factor': profit_factor,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'stopped': stopped_trades,
        'reentries': reentries,
    }


def main():
    # Fetch data
    print('Fetching ES 3m data...')
    all_bars = fetch_futures_bars(symbol='ES', interval='3m', n_bars=10000)

    if not all_bars:
        print('No data available')
        return

    print(f'Got {len(all_bars)} bars')

    # Group by date to count days
    bars_by_date = defaultdict(list)
    for bar in all_bars:
        bars_by_date[bar.timestamp.date()].append(bar)
    trading_days = sorted(bars_by_date.keys())
    print(f'Trading days: {len(trading_days)} ({trading_days[0]} to {trading_days[-1]})')

    strategies = ['current', 'wider', 'mitigation', 'delayed']
    strategy_names = {
        'current': 'Current (FVG +2 ticks)',
        'wider': 'Wider (FVG +4 ticks)',
        'mitigation': 'FVG Mitigation (close only)',
        'delayed': 'Delayed (3-bar grace)',
    }

    print()
    print('='*80)
    print('STOP STRATEGY COMPARISON - 15 Day Backtest - ES 3m - 3 Contracts')
    print('='*80)

    all_stats = {}

    for strategy in strategies:
        print(f'\nRunning {strategy_names[strategy]}...')
        results = run_backtest_with_strategy(strategy, all_bars)
        stats = calculate_stats(results)
        all_stats[strategy] = stats

        print(f'  Trades: {stats["trades"]} | Wins: {stats["wins"]} | Losses: {stats["losses"]} | '
              f'Stopped: {stats["stopped"]} | P/L: ${stats["total_pnl"]:+,.2f}')

    # Print comparison table
    print()
    print('='*80)
    print('COMPARISON SUMMARY')
    print('='*80)
    print()
    print(f'{"Strategy":<30} {"Trades":<8} {"W/L":<10} {"Win%":<8} {"Stopped":<10} {"P/L":<15} {"PF":<8}')
    print('-'*80)

    for strategy in strategies:
        s = all_stats[strategy]
        print(f'{strategy_names[strategy]:<30} {s["trades"]:<8} {s["wins"]}W/{s["losses"]}L{"":<3} '
              f'{s["win_rate"]:.1f}%{"":<3} {s["stopped"]:<10} ${s["total_pnl"]:>+12,.2f}  {s["profit_factor"]:.2f}')

    # Find best strategy
    best_strategy = max(all_stats.keys(), key=lambda x: all_stats[x]['total_pnl'])
    best_pnl = all_stats[best_strategy]['total_pnl']
    current_pnl = all_stats['current']['total_pnl']
    improvement = best_pnl - current_pnl

    print()
    print('='*80)
    print('RECOMMENDATION')
    print('='*80)
    print()
    print(f'Best Strategy: {strategy_names[best_strategy]}')
    print(f'Total P/L: ${best_pnl:+,.2f}')
    print(f'Improvement vs Current: ${improvement:+,.2f}')
    print()

    # Detailed breakdown
    print('='*80)
    print('DETAILED TRADE-BY-TRADE FOR BEST STRATEGY')
    print('='*80)
    print()

    results = run_backtest_with_strategy(best_strategy, all_bars)
    for r in results:
        tag = ' [RE-ENTRY]' if r.get('is_reentry') else ''
        stopped = ' [STOPPED]' if r['was_stopped'] else ''
        result_str = 'WIN' if r['total_pnl'] > 0.01 else 'LOSS' if r['total_pnl'] < -0.01 else 'BE'
        print(f"  {r['date']} | {r['direction']:5} | {r['entry_time'].strftime('%H:%M')} | "
              f"{result_str:4} | ${r['total_dollars']:+,.2f}{tag}{stopped}")


if __name__ == '__main__':
    main()
