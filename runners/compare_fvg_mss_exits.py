"""
Deep comparison of Opposing FVG vs Market Structure Shift vs EMA50 baseline.
Uses 5-minute bars to get ~27 days of data.
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


def find_swing_points(bars, lookback=3):
    """Find swing highs and lows."""
    swing_highs = []
    swing_lows = []

    for i in range(lookback, len(bars) - lookback):
        # Swing high
        is_swing_high = all(bars[i].high >= bars[i-j].high for j in range(1, lookback+1)) and \
                        all(bars[i].high >= bars[i+j].high for j in range(1, lookback+1))
        if is_swing_high:
            swing_highs.append((i, bars[i].high))

        # Swing low
        is_swing_low = all(bars[i].low <= bars[i-j].low for j in range(1, lookback+1)) and \
                       all(bars[i].low <= bars[i+j].low for j in range(1, lookback+1))
        if is_swing_low:
            swing_lows.append((i, bars[i].low))

    return swing_highs, swing_lows


def run_trade_with_strategy(session_bars, direction, fvg_num, runner_strategy='ema50',
                            tick_size=0.25, tick_value=12.50, contracts=3,
                            target1_r=4, target2_r=8):
    """
    Run trade with specific runner exit strategy:
    - 'ema50': EMA50 cross (baseline)
    - 'opposing_fvg': Exit when opposing FVG forms
    - 'mss': Exit on market structure shift
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

    if risk <= 0:
        return None

    target_t1 = entry_price + (target1_r * risk) if is_long else entry_price - (target1_r * risk)
    target_t2 = entry_price + (target2_r * risk) if is_long else entry_price - (target2_r * risk)

    closes = [b.close for b in session_bars]
    ema_50 = calculate_ema(closes, 50)

    # Find swing points for MSS
    swing_highs, swing_lows = find_swing_points(session_bars, lookback=3)

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

    # Track last swing for MSS
    last_swing_low = None
    last_swing_high = None
    for idx, price in swing_lows:
        if idx < entry_bar_idx:
            last_swing_low = price
    for idx, price in swing_highs:
        if idx < entry_bar_idx:
            last_swing_high = price

    # Track runner exit details
    runner_exit_type = None

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]
        bar_ema50 = ema_50[i] if i < len(ema_50) and ema_50[i] else None

        # Update swing points
        for idx, price in swing_lows:
            if idx == i - 3:
                last_swing_low = price
        for idx, price in swing_highs:
            if idx == i - 3:
                last_swing_high = price

        # Check FVG mitigation stop
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

        # Runner exit logic
        if remaining > 0 and remaining <= cts_runner:
            runner_exit = False
            exit_price = None
            exit_type = None

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

            elif runner_strategy == 'opposing_fvg':
                # Exit when opposing FVG forms
                opposing_dir = 'BEARISH' if is_long else 'BULLISH'
                recent_fvgs = [f for f in all_fvgs if f.direction == opposing_dir
                              and f.created_bar_index > entry_bar_idx
                              and f.created_bar_index <= i]
                if recent_fvgs:
                    runner_exit = True
                    exit_price = bar.close
                    exit_type = 'OPP_FVG'

            elif runner_strategy == 'mss':
                # Market Structure Shift - exit when swing breaks against trade
                if is_long and last_swing_low and bar.close < last_swing_low:
                    runner_exit = True
                    exit_price = bar.close
                    exit_type = 'MSS'
                elif not is_long and last_swing_high and bar.close > last_swing_high:
                    runner_exit = True
                    exit_price = bar.close
                    exit_type = 'MSS'

            if runner_exit and exit_price:
                pnl = (exit_price - entry_price) * remaining if is_long else (entry_price - exit_price) * remaining
                exits.append({'type': exit_type, 'pnl': pnl, 'price': exit_price, 'time': bar.timestamp, 'cts': remaining})
                runner_exit_type = exit_type
                remaining = 0

    # EOD close
    if remaining > 0:
        last_bar = session_bars[-1]
        pnl = (last_bar.close - entry_price) * remaining if is_long else (entry_price - last_bar.close) * remaining
        exits.append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'cts': remaining})
        runner_exit_type = 'EOD'

    total_pnl = sum(e['pnl'] for e in exits)
    total_dollars = (total_pnl / tick_size) * tick_value
    was_stopped = any(e['type'] == 'STOP' for e in exits)

    runner_exits = [e for e in exits if e['type'] not in [f'T{target1_r}R', f'T{target2_r}R', 'STOP']]
    runner_pnl = sum((e['pnl'] / tick_size) * tick_value for e in runner_exits)

    return {
        'direction': direction,
        'entry_time': entry_time,
        'entry_price': entry_price,
        'stop_price': stop_price,
        'risk': risk,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'runner_dollars': runner_pnl,
        'runner_exit_type': runner_exit_type,
        'was_stopped': was_stopped,
        'exits': exits,
    }


def run_backtest(runner_strategy, all_bars, contracts=3):
    """Run full backtest."""
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
        result = run_trade_with_strategy(session_bars, 'LONG', 1, runner_strategy, contracts=contracts)
        if result:
            result['date'] = d
            all_results.append(result)
            if result['was_stopped']:
                result2 = run_trade_with_strategy(session_bars, 'LONG', 2, runner_strategy, contracts=contracts)
                if result2:
                    result2['date'] = d
                    result2['is_reentry'] = True
                    all_results.append(result2)

        # Try SHORT
        result = run_trade_with_strategy(session_bars, 'SHORT', 1, runner_strategy, contracts=contracts)
        if result:
            result['date'] = d
            all_results.append(result)
            if result['was_stopped']:
                result2 = run_trade_with_strategy(session_bars, 'SHORT', 2, runner_strategy, contracts=contracts)
                if result2:
                    result2['date'] = d
                    result2['is_reentry'] = True
                    all_results.append(result2)

    return all_results


def main():
    print('='*100)
    print('OPPOSING FVG vs MARKET STRUCTURE SHIFT vs EMA50 - DEEP COMPARISON')
    print('='*100)
    print()

    # Use 5-minute bars for more data (~27 days)
    print('Fetching ES 5m data for extended backtest...')
    all_bars = fetch_futures_bars(symbol='ES', interval='5m', n_bars=20000)

    if not all_bars:
        print('No data available')
        return

    print(f'Got {len(all_bars)} bars')

    bars_by_date = defaultdict(list)
    for bar in all_bars:
        bars_by_date[bar.timestamp.date()].append(bar)
    trading_days = sorted(bars_by_date.keys())
    print(f'Trading days: {len(trading_days)} ({trading_days[0]} to {trading_days[-1]})')
    print()

    strategies = ['ema50', 'opposing_fvg', 'mss']
    strategy_names = {
        'ema50': 'EMA50 Cross (Baseline)',
        'opposing_fvg': 'Opposing FVG',
        'mss': 'Market Structure Shift',
    }

    all_results = {}
    all_stats = {}

    for strategy in strategies:
        print(f'Running {strategy_names[strategy]}...')
        results = run_backtest(strategy, all_bars)
        all_results[strategy] = results

        # Calculate stats
        wins = len([r for r in results if r['total_pnl'] > 0.01])
        losses = len([r for r in results if r['total_pnl'] < -0.01])
        total_pnl = sum(r['total_dollars'] for r in results)
        runner_pnl = sum(r['runner_dollars'] for r in results)
        long_pnl = sum(r['total_dollars'] for r in results if r['direction'] == 'LONG')
        short_pnl = sum(r['total_dollars'] for r in results if r['direction'] == 'SHORT')

        winning_pnl = sum(r['total_dollars'] for r in results if r['total_dollars'] > 0)
        losing_pnl = sum(r['total_dollars'] for r in results if r['total_dollars'] < 0)
        profit_factor = abs(winning_pnl / losing_pnl) if losing_pnl < 0 else float('inf')

        all_stats[strategy] = {
            'trades': len(results),
            'wins': wins,
            'losses': losses,
            'win_rate': wins / (wins + losses) * 100 if (wins + losses) > 0 else 0,
            'total_pnl': total_pnl,
            'runner_pnl': runner_pnl,
            'long_pnl': long_pnl,
            'short_pnl': short_pnl,
            'profit_factor': profit_factor,
            'avg_trade': total_pnl / len(results) if results else 0,
            'avg_runner': runner_pnl / len(results) if results else 0,
        }

    # Print summary comparison
    print()
    print('='*100)
    print(f'SUMMARY COMPARISON - {len(trading_days)} TRADING DAYS')
    print('='*100)
    print()

    baseline_pnl = all_stats['ema50']['total_pnl']

    print(f'{"Metric":<25} {"EMA50 (Base)":<18} {"Opposing FVG":<18} {"MSS":<18}')
    print('-'*100)

    for metric, label in [
        ('trades', 'Total Trades'),
        ('win_rate', 'Win Rate'),
        ('total_pnl', 'Total P/L'),
        ('runner_pnl', 'Runner P/L'),
        ('long_pnl', 'Long P/L'),
        ('short_pnl', 'Short P/L'),
        ('avg_trade', 'Avg per Trade'),
        ('avg_runner', 'Avg Runner'),
    ]:
        values = []
        for strategy in strategies:
            val = all_stats[strategy][metric]
            if metric == 'win_rate':
                values.append(f'{val:.1f}%')
            elif metric == 'trades':
                values.append(f'{val}')
            else:
                values.append(f'${val:+,.2f}')
        print(f'{label:<25} {values[0]:<18} {values[1]:<18} {values[2]:<18}')

    # Improvement vs baseline
    print()
    print('-'*100)
    opp_fvg_improvement = all_stats['opposing_fvg']['total_pnl'] - baseline_pnl
    mss_improvement = all_stats['mss']['total_pnl'] - baseline_pnl
    print(f'{"vs Baseline":<25} {"--":<18} ${opp_fvg_improvement:+,.2f} ({opp_fvg_improvement/baseline_pnl*100:+.1f}%){"":5} ${mss_improvement:+,.2f} ({mss_improvement/baseline_pnl*100:+.1f}%)')

    # Trade-by-trade comparison
    print()
    print('='*100)
    print('TRADE-BY-TRADE BREAKDOWN')
    print('='*100)
    print()
    print(f'{"Date":<12} {"Dir":<6} {"EMA50":<20} {"Opposing FVG":<20} {"MSS":<20}')
    print('-'*100)

    # Align trades by date and direction
    for d in trading_days:
        for direction in ['LONG', 'SHORT']:
            row = [f'{d}', f'{direction}']
            for strategy in strategies:
                trades = [r for r in all_results[strategy] if r['date'] == d and r['direction'] == direction and not r.get('is_reentry')]
                if trades:
                    t = trades[0]
                    exit_type = t['runner_exit_type'] or 'N/A'
                    row.append(f"${t['total_dollars']:+,.0f} ({exit_type})")
                else:
                    row.append('--')
            if any(r != '--' for r in row[2:]):
                print(f'{row[0]:<12} {row[1]:<6} {row[2]:<20} {row[3]:<20} {row[4]:<20}')

    # Runner exit type breakdown
    print()
    print('='*100)
    print('RUNNER EXIT TYPE ANALYSIS')
    print('='*100)
    print()

    for strategy in strategies:
        results = all_results[strategy]
        exit_types = defaultdict(lambda: {'count': 0, 'pnl': 0})
        for r in results:
            exit_type = r['runner_exit_type'] or 'N/A'
            exit_types[exit_type]['count'] += 1
            exit_types[exit_type]['pnl'] += r['runner_dollars']

        print(f'{strategy_names[strategy]}:')
        for exit_type, data in sorted(exit_types.items(), key=lambda x: -x[1]['pnl']):
            print(f'  {exit_type:<12}: {data["count"]:>3} trades, ${data["pnl"]:>+10,.2f} runner P/L')
        print()

    # Recommendation
    print('='*100)
    print('RECOMMENDATION')
    print('='*100)
    print()

    best_strategy = max(strategies, key=lambda x: all_stats[x]['total_pnl'])
    print(f'BEST PERFORMER: {strategy_names[best_strategy]}')
    print(f'Total P/L: ${all_stats[best_strategy]["total_pnl"]:+,.2f}')
    print(f'Runner P/L: ${all_stats[best_strategy]["runner_pnl"]:+,.2f}')
    print()

    if best_strategy != 'ema50':
        improvement = all_stats[best_strategy]['total_pnl'] - baseline_pnl
        print(f'Improvement vs EMA50: ${improvement:+,.2f} ({improvement/baseline_pnl*100:+.1f}%)')


if __name__ == '__main__':
    main()
