"""
Compare ICT-specific runner exit strategies.
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time, timedelta
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


def get_asian_range(all_bars_for_date, trade_date):
    """Get Asian session high/low (18:00-00:00 previous day to current day)."""
    # Asian session: 6PM - midnight ET (previous calendar day in data)
    asian_start = dt_time(18, 0)
    asian_end = dt_time(23, 59)

    # Get previous day's evening session
    prev_date = trade_date - timedelta(days=1)
    asian_bars = [b for b in all_bars_for_date.get(prev_date, [])
                  if asian_start <= b.timestamp.time() <= asian_end]

    if not asian_bars:
        return None, None

    asian_high = max(b.high for b in asian_bars)
    asian_low = min(b.low for b in asian_bars)
    return asian_high, asian_low


def get_prev_day_hl(all_bars_for_date, trade_date):
    """Get previous day's high and low."""
    prev_date = trade_date - timedelta(days=1)
    # Skip weekends
    while prev_date.weekday() >= 5:  # Saturday=5, Sunday=6
        prev_date -= timedelta(days=1)

    prev_bars = all_bars_for_date.get(prev_date, [])
    # Filter to regular trading hours
    rth_bars = [b for b in prev_bars if dt_time(9, 30) <= b.timestamp.time() <= dt_time(16, 0)]

    if not rth_bars:
        return None, None

    pdh = max(b.high for b in rth_bars)
    pdl = min(b.low for b in rth_bars)
    return pdh, pdl


def find_swing_points(bars, lookback=5):
    """Find swing highs and lows."""
    swing_highs = []
    swing_lows = []

    for i in range(lookback, len(bars) - lookback):
        # Swing high: higher than lookback bars on both sides
        is_swing_high = all(bars[i].high >= bars[i-j].high for j in range(1, lookback+1)) and \
                        all(bars[i].high >= bars[i+j].high for j in range(1, lookback+1))
        if is_swing_high:
            swing_highs.append((i, bars[i].high))

        # Swing low: lower than lookback bars on both sides
        is_swing_low = all(bars[i].low <= bars[i-j].low for j in range(1, lookback+1)) and \
                       all(bars[i].low <= bars[i+j].low for j in range(1, lookback+1))
        if is_swing_low:
            swing_lows.append((i, bars[i].low))

    return swing_highs, swing_lows


def run_trade_with_ict_exit(session_bars, direction, fvg_num, runner_strategy='ema50',
                            tick_size=0.25, tick_value=12.50, contracts=3,
                            target1_r=4, target2_r=8, pdh=None, pdl=None,
                            asian_high=None, asian_low=None):
    """
    Run trade with ICT-specific runner exit strategies:
    - 'ema50': EMA50 cross (baseline)
    - 'killzone_end': Exit at 12:00 (end of NY AM kill zone)
    - 'ny_lunch': Exit at 11:30 (before NY lunch)
    - 'silver_bullet': Exit at 11:00 (end of silver bullet)
    - 'pdh_pdl': Exit at previous day high (long) or low (short)
    - 'asian_range': Exit at Asian high (long) or low (short)
    - 'mss': Exit on market structure shift (swing break)
    - 'opposing_fvg': Exit when opposing FVG forms
    - 'liquidity_sweep': Exit after liquidity taken
    - 'time_1530': Time exit at 15:30
    - 'ny_pm_open': Exit at 13:30 (NY PM session open)
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

    closes = [b.close for b in session_bars]
    ema_50 = calculate_ema(closes, 50)

    # Find swing points for MSS strategy
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
    if cts_t1 == 0: cts_t1 = 1
    if cts_t2 == 0: cts_t2 = 1
    if cts_runner == 0: cts_runner = 1

    exits = []
    remaining = contracts
    exited_t1 = False
    exited_t2 = False

    # Track highest/lowest since entry for trailing/liquidity
    highest_since_entry = entry_price
    lowest_since_entry = entry_price

    # Track last swing for MSS
    last_swing_low = None
    last_swing_high = None
    for idx, price in swing_lows:
        if idx < entry_bar_idx:
            last_swing_low = price
    for idx, price in swing_highs:
        if idx < entry_bar_idx:
            last_swing_high = price

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]
        bar_ema50 = ema_50[i] if i < len(ema_50) and ema_50[i] else None

        # Update tracking
        if bar.high > highest_since_entry:
            highest_since_entry = bar.high
        if bar.low < lowest_since_entry:
            lowest_since_entry = bar.low

        # Update swing points
        for idx, price in swing_lows:
            if idx == i - 3:  # Confirmed swing
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

            elif runner_strategy == 'killzone_end':
                # NY AM Kill Zone ends at 12:00
                if bar.timestamp.time() >= dt_time(12, 0):
                    runner_exit = True
                    exit_price = bar.close
                    exit_type = 'KZ_END'

            elif runner_strategy == 'ny_lunch':
                # Exit before NY lunch at 11:30
                if bar.timestamp.time() >= dt_time(11, 30):
                    runner_exit = True
                    exit_price = bar.close
                    exit_type = 'NY_LUNCH'

            elif runner_strategy == 'silver_bullet':
                # Silver bullet window ends at 11:00
                if bar.timestamp.time() >= dt_time(11, 0):
                    runner_exit = True
                    exit_price = bar.close
                    exit_type = 'SILVER_BULLET'

            elif runner_strategy == 'ny_pm_open':
                # NY PM session opens at 13:30
                if bar.timestamp.time() >= dt_time(13, 30):
                    runner_exit = True
                    exit_price = bar.close
                    exit_type = 'NY_PM'

            elif runner_strategy == 'pdh_pdl':
                # Exit at previous day high (long) or low (short)
                if pdh and pdl:
                    if is_long and bar.high >= pdh:
                        runner_exit = True
                        exit_price = pdh
                        exit_type = 'PDH'
                    elif not is_long and bar.low <= pdl:
                        runner_exit = True
                        exit_price = pdl
                        exit_type = 'PDL'

            elif runner_strategy == 'asian_range':
                # Exit at Asian high (long) or low (short)
                if asian_high and asian_low:
                    if is_long and bar.high >= asian_high:
                        runner_exit = True
                        exit_price = asian_high
                        exit_type = 'ASIAN_H'
                    elif not is_long and bar.low <= asian_low:
                        runner_exit = True
                        exit_price = asian_low
                        exit_type = 'ASIAN_L'

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

            elif runner_strategy == 'liquidity_sweep':
                # Exit after liquidity is swept (price exceeds recent high/low then reverses)
                if is_long:
                    # Look for sweep of recent high then reversal
                    if highest_since_entry > entry_price + (8 * risk):
                        if bar.close < highest_since_entry - (2 * risk):
                            runner_exit = True
                            exit_price = bar.close
                            exit_type = 'LIQ_SWEEP'
                else:
                    if lowest_since_entry < entry_price - (8 * risk):
                        if bar.close > lowest_since_entry + (2 * risk):
                            runner_exit = True
                            exit_price = bar.close
                            exit_type = 'LIQ_SWEEP'

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


def run_backtest_with_ict_strategy(runner_strategy, all_bars, bars_by_date, contracts=3):
    """Run full backtest with ICT runner strategy."""

    trading_days = sorted(bars_by_date.keys())

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)

    all_results = []

    for d in trading_days:
        day_bars = bars_by_date[d]
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Get PDH/PDL and Asian range
        pdh, pdl = get_prev_day_hl(bars_by_date, d)
        asian_high, asian_low = get_asian_range(bars_by_date, d)

        # Try LONG
        result = run_trade_with_ict_exit(session_bars, 'LONG', 1, runner_strategy,
                                         contracts=contracts, pdh=pdh, pdl=pdl,
                                         asian_high=asian_high, asian_low=asian_low)
        if result:
            result['date'] = d
            all_results.append(result)
            if result['was_stopped']:
                result2 = run_trade_with_ict_exit(session_bars, 'LONG', 2, runner_strategy,
                                                  contracts=contracts, pdh=pdh, pdl=pdl,
                                                  asian_high=asian_high, asian_low=asian_low)
                if result2:
                    result2['date'] = d
                    result2['is_reentry'] = True
                    all_results.append(result2)

        # Try SHORT
        result = run_trade_with_ict_exit(session_bars, 'SHORT', 1, runner_strategy,
                                         contracts=contracts, pdh=pdh, pdl=pdl,
                                         asian_high=asian_high, asian_low=asian_low)
        if result:
            result['date'] = d
            all_results.append(result)
            if result['was_stopped']:
                result2 = run_trade_with_ict_exit(session_bars, 'SHORT', 2, runner_strategy,
                                                  contracts=contracts, pdh=pdh, pdl=pdl,
                                                  asian_high=asian_high, asian_low=asian_low)
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

    strategies = [
        'ema50', 'time_1530', 'killzone_end', 'ny_lunch', 'silver_bullet',
        'ny_pm_open', 'pdh_pdl', 'mss', 'opposing_fvg', 'liquidity_sweep'
    ]
    strategy_names = {
        'ema50': 'EMA50 Cross (baseline)',
        'time_1530': 'Time Exit 15:30',
        'killzone_end': 'Kill Zone End (12:00)',
        'ny_lunch': 'NY Lunch (11:30)',
        'silver_bullet': 'Silver Bullet End (11:00)',
        'ny_pm_open': 'NY PM Open (13:30)',
        'pdh_pdl': 'Previous Day H/L',
        'mss': 'Market Structure Shift',
        'opposing_fvg': 'Opposing FVG',
        'liquidity_sweep': 'Liquidity Sweep',
    }

    print()
    print('='*95)
    print('ICT RUNNER EXIT STRATEGY COMPARISON - ES 3m - 3 Contracts')
    print('='*95)
    print()

    all_stats = {}

    for strategy in strategies:
        print(f'Testing {strategy_names[strategy]}...')
        results = run_backtest_with_ict_strategy(strategy, all_bars, bars_by_date)
        stats = calculate_stats(results)
        all_stats[strategy] = stats

    # Print comparison table
    print()
    print('='*95)
    print('COMPARISON SUMMARY')
    print('='*95)
    print()
    print(f'{"Strategy":<30} {"Trades":<8} {"W/L":<10} {"Total P/L":<14} {"Runner P/L":<14} {"PF":<8}')
    print('-'*95)

    # Sort by total P/L
    sorted_strategies = sorted(strategies, key=lambda x: all_stats[x]['total_pnl'], reverse=True)

    for strategy in sorted_strategies:
        s = all_stats[strategy]
        pf_str = f'{s["profit_factor"]:.2f}' if s["profit_factor"] != float('inf') else 'inf'
        marker = ' ***' if strategy == sorted_strategies[0] else ''
        print(f'{strategy_names[strategy]:<30} {s["trades"]:<8} {s["wins"]}W/{s["losses"]}L{"":<3} '
              f'${s["total_pnl"]:>+10,.2f}   ${s["runner_pnl"]:>+10,.2f}   {pf_str:<8}{marker}')

    # Analysis
    best_strategy = sorted_strategies[0]
    best_pnl = all_stats[best_strategy]['total_pnl']
    ema50_pnl = all_stats['ema50']['total_pnl']

    print()
    print('='*95)
    print('ANALYSIS')
    print('='*95)
    print()
    print(f'BEST STRATEGY:    {strategy_names[best_strategy]}')
    print(f'Total P/L:        ${best_pnl:+,.2f}')
    print(f'vs EMA50:         ${best_pnl - ema50_pnl:+,.2f} ({(best_pnl - ema50_pnl) / ema50_pnl * 100:+.1f}%)')
    print()

    print('ICT CONCEPTS RANKING:')
    print('-'*50)
    for i, strategy in enumerate(sorted_strategies[:5], 1):
        s = all_stats[strategy]
        print(f'{i}. {strategy_names[strategy]:<28} ${s["total_pnl"]:>+10,.2f}')


if __name__ == '__main__':
    main()
