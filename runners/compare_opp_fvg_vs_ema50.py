"""
Compare Opposing FVG vs EMA50 runner exit strategies.
Run fresh 30-day backtest for both methods.
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


def run_trade_ema50(session_bars, direction, fvg_num, tick_size=0.25, tick_value=12.50, contracts=3, target1_r=4, target2_r=8):
    """Run trade with EMA50 runner exit."""
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

    # Calculate levels
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

    # Calculate EMA50
    closes = [b.close for b in session_bars]
    ema50 = calculate_ema(closes, 50)

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

        # Check stop - FVG Mitigation
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

        # Check EMA50 runner exit
        if remaining > 0 and remaining <= cts_runner and ema50[i] is not None:
            ema_cross = bar.close < ema50[i] if is_long else bar.close > ema50[i]
            if ema_cross:
                pnl = (bar.close - entry_price) * remaining if is_long else (entry_price - bar.close) * remaining
                exits.append({'type': 'EMA50', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': remaining})
                remaining = 0

    # EOD close if still holding
    if remaining > 0:
        last_bar = session_bars[-1]
        pnl = (last_bar.close - entry_price) * remaining if is_long else (entry_price - last_bar.close) * remaining
        exits.append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'cts': remaining})

    total_pnl = sum(e['pnl'] for e in exits)
    total_dollars = (total_pnl / tick_size) * tick_value
    was_stopped = any(e['type'] == 'STOP' for e in exits)

    # Calculate runner P/L
    runner_pnl = sum(e['pnl'] for e in exits if e['type'] in ['EMA50', 'EOD'])
    runner_dollars = (runner_pnl / tick_size) * tick_value

    return {
        'direction': direction,
        'entry_time': entry_time,
        'entry_price': entry_price,
        'stop_price': stop_price,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'runner_dollars': runner_dollars,
        'was_stopped': was_stopped,
        'exits': exits,
    }


def run_trade_opp_fvg(session_bars, direction, fvg_num, tick_size=0.25, tick_value=12.50, contracts=3, target1_r=4, target2_r=8):
    """Run trade with Opposing FVG runner exit."""
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

    # Calculate levels
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

        # Check stop - FVG Mitigation
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

        # Check Opposing FVG runner exit
        if remaining > 0 and remaining <= cts_runner:
            opposing_fvgs = [f for f in all_fvgs if f.direction == opposing_fvg_dir
                           and f.created_bar_index > entry_bar_idx
                           and f.created_bar_index <= i]
            if opposing_fvgs:
                pnl = (bar.close - entry_price) * remaining if is_long else (entry_price - bar.close) * remaining
                exits.append({'type': 'OPP_FVG', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': remaining})
                remaining = 0

    # EOD close if still holding
    if remaining > 0:
        last_bar = session_bars[-1]
        pnl = (last_bar.close - entry_price) * remaining if is_long else (entry_price - last_bar.close) * remaining
        exits.append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'cts': remaining})

    total_pnl = sum(e['pnl'] for e in exits)
    total_dollars = (total_pnl / tick_size) * tick_value
    was_stopped = any(e['type'] == 'STOP' for e in exits)

    # Calculate runner P/L
    runner_pnl = sum(e['pnl'] for e in exits if e['type'] in ['OPP_FVG', 'EOD'])
    runner_dollars = (runner_pnl / tick_size) * tick_value

    return {
        'direction': direction,
        'entry_time': entry_time,
        'entry_price': entry_price,
        'stop_price': stop_price,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'runner_dollars': runner_dollars,
        'was_stopped': was_stopped,
        'exits': exits,
    }


def run_comparison():
    """Run comparison between EMA50 and Opposing FVG exit strategies."""

    contracts = 3
    target1_r = 4
    target2_r = 8

    # Fetch data - use 5m bars for more history
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

    print('\n' + '='*100)
    print('COMPARING RUNNER EXIT STRATEGIES: EMA50 vs OPPOSING FVG')
    print('='*100)
    print(f'Period: {trading_days[0]} to {trading_days[-1]} ({len(trading_days)} days)')
    print(f'Contracts: {contracts} | Exits: 4R, 8R, Runner')
    print('='*100)

    ema50_results = []
    opp_fvg_results = []

    for d in trading_days:
        day_bars = bars_by_date[d]
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Run both strategies for LONG
        ema50_result = run_trade_ema50(session_bars, 'LONG', 1, contracts=contracts, target1_r=target1_r, target2_r=target2_r)
        opp_fvg_result = run_trade_opp_fvg(session_bars, 'LONG', 1, contracts=contracts, target1_r=target1_r, target2_r=target2_r)

        if ema50_result:
            ema50_result['date'] = d
            ema50_results.append(ema50_result)
            if ema50_result['was_stopped']:
                ema50_result2 = run_trade_ema50(session_bars, 'LONG', 2, contracts=contracts, target1_r=target1_r, target2_r=target2_r)
                if ema50_result2:
                    ema50_result2['date'] = d
                    ema50_result2['is_reentry'] = True
                    ema50_results.append(ema50_result2)

        if opp_fvg_result:
            opp_fvg_result['date'] = d
            opp_fvg_results.append(opp_fvg_result)
            if opp_fvg_result['was_stopped']:
                opp_fvg_result2 = run_trade_opp_fvg(session_bars, 'LONG', 2, contracts=contracts, target1_r=target1_r, target2_r=target2_r)
                if opp_fvg_result2:
                    opp_fvg_result2['date'] = d
                    opp_fvg_result2['is_reentry'] = True
                    opp_fvg_results.append(opp_fvg_result2)

        # Run both strategies for SHORT
        ema50_result = run_trade_ema50(session_bars, 'SHORT', 1, contracts=contracts, target1_r=target1_r, target2_r=target2_r)
        opp_fvg_result = run_trade_opp_fvg(session_bars, 'SHORT', 1, contracts=contracts, target1_r=target1_r, target2_r=target2_r)

        if ema50_result:
            ema50_result['date'] = d
            ema50_results.append(ema50_result)
            if ema50_result['was_stopped']:
                ema50_result2 = run_trade_ema50(session_bars, 'SHORT', 2, contracts=contracts, target1_r=target1_r, target2_r=target2_r)
                if ema50_result2:
                    ema50_result2['date'] = d
                    ema50_result2['is_reentry'] = True
                    ema50_results.append(ema50_result2)

        if opp_fvg_result:
            opp_fvg_result['date'] = d
            opp_fvg_results.append(opp_fvg_result)
            if opp_fvg_result['was_stopped']:
                opp_fvg_result2 = run_trade_opp_fvg(session_bars, 'SHORT', 2, contracts=contracts, target1_r=target1_r, target2_r=target2_r)
                if opp_fvg_result2:
                    opp_fvg_result2['date'] = d
                    opp_fvg_result2['is_reentry'] = True
                    opp_fvg_results.append(opp_fvg_result2)

    # Calculate stats for each strategy
    def calc_stats(results, name):
        wins = sum(1 for r in results if r['total_pnl'] > 0.01)
        losses = sum(1 for r in results if r['total_pnl'] < -0.01)
        total_pnl = sum(r['total_dollars'] for r in results)
        runner_pnl = sum(r['runner_dollars'] for r in results)
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
            'runner_pnl': runner_pnl,
            'long_pnl': long_pnl,
            'short_pnl': short_pnl,
            'profit_factor': profit_factor,
            'avg_per_trade': total_pnl / len(results) if results else 0,
        }

    ema50_stats = calc_stats(ema50_results, 'EMA50')
    opp_fvg_stats = calc_stats(opp_fvg_results, 'Opposing FVG')

    # Print trade-by-trade comparison
    print('\n' + '-'*100)
    print('TRADE-BY-TRADE COMPARISON')
    print('-'*100)
    print(f'{"Date":<12} {"Dir":<6} {"EMA50 P/L":>12} {"OPP_FVG P/L":>12} {"Difference":>12} {"Winner":<12}')
    print('-'*100)

    # Match trades by date and direction
    ema50_by_key = {}
    for r in ema50_results:
        key = (r['date'], r['direction'], r.get('is_reentry', False))
        ema50_by_key[key] = r

    opp_fvg_by_key = {}
    for r in opp_fvg_results:
        key = (r['date'], r['direction'], r.get('is_reentry', False))
        opp_fvg_by_key[key] = r

    all_keys = sorted(set(ema50_by_key.keys()) | set(opp_fvg_by_key.keys()))

    for key in all_keys:
        d, direction, is_reentry = key
        ema50_r = ema50_by_key.get(key)
        opp_fvg_r = opp_fvg_by_key.get(key)

        ema50_pnl = ema50_r['total_dollars'] if ema50_r else 0
        opp_fvg_pnl = opp_fvg_r['total_dollars'] if opp_fvg_r else 0
        diff = opp_fvg_pnl - ema50_pnl

        if diff > 0:
            winner = 'OPP_FVG'
        elif diff < 0:
            winner = 'EMA50'
        else:
            winner = 'TIE'

        reentry_tag = ' [RE]' if is_reentry else ''
        print(f'{str(d):<12} {direction:<6} ${ema50_pnl:>10,.2f} ${opp_fvg_pnl:>10,.2f} ${diff:>+10,.2f} {winner:<12}{reentry_tag}')

    # Print summary comparison
    print('\n' + '='*100)
    print('SUMMARY COMPARISON')
    print('='*100)
    print(f'{"Metric":<25} {"EMA50":>20} {"Opposing FVG":>20} {"Difference":>20}')
    print('-'*100)

    pnl_diff = opp_fvg_stats['total_pnl'] - ema50_stats['total_pnl']
    pnl_pct = (pnl_diff / ema50_stats['total_pnl'] * 100) if ema50_stats['total_pnl'] != 0 else 0

    print(f'{"Total Trades":<25} {ema50_stats["trades"]:>20} {opp_fvg_stats["trades"]:>20} {"":>20}')
    print(f'{"Wins":<25} {ema50_stats["wins"]:>20} {opp_fvg_stats["wins"]:>20} {"":>20}')
    print(f'{"Losses":<25} {ema50_stats["losses"]:>20} {opp_fvg_stats["losses"]:>20} {"":>20}')
    print(f'{"Win Rate":<25} {ema50_stats["win_rate"]:>19.1f}% {opp_fvg_stats["win_rate"]:>19.1f}% {"":>20}')
    print('-'*100)
    print(f'{"TOTAL P/L":<25} ${ema50_stats["total_pnl"]:>18,.2f} ${opp_fvg_stats["total_pnl"]:>18,.2f} ${pnl_diff:>+17,.2f} ({pnl_pct:+.1f}%)')
    print(f'{"Runner P/L":<25} ${ema50_stats["runner_pnl"]:>18,.2f} ${opp_fvg_stats["runner_pnl"]:>18,.2f} ${opp_fvg_stats["runner_pnl"] - ema50_stats["runner_pnl"]:>+17,.2f}')
    print(f'{"Long P/L":<25} ${ema50_stats["long_pnl"]:>18,.2f} ${opp_fvg_stats["long_pnl"]:>18,.2f} ${opp_fvg_stats["long_pnl"] - ema50_stats["long_pnl"]:>+17,.2f}')
    print(f'{"Short P/L":<25} ${ema50_stats["short_pnl"]:>18,.2f} ${opp_fvg_stats["short_pnl"]:>18,.2f} ${opp_fvg_stats["short_pnl"] - ema50_stats["short_pnl"]:>+17,.2f}')
    print('-'*100)
    print(f'{"Avg per Trade":<25} ${ema50_stats["avg_per_trade"]:>18,.2f} ${opp_fvg_stats["avg_per_trade"]:>18,.2f} ${opp_fvg_stats["avg_per_trade"] - ema50_stats["avg_per_trade"]:>+17,.2f}')
    pf_ema = f'{ema50_stats["profit_factor"]:.2f}' if ema50_stats["profit_factor"] != float('inf') else 'inf'
    pf_opp = f'{opp_fvg_stats["profit_factor"]:.2f}' if opp_fvg_stats["profit_factor"] != float('inf') else 'inf'
    print(f'{"Profit Factor":<25} {pf_ema:>20} {pf_opp:>20} {"":>20}')

    print('\n' + '='*100)
    if pnl_diff > 0:
        print(f'WINNER: OPPOSING FVG (+${pnl_diff:,.2f} | +{pnl_pct:.1f}%)')
    elif pnl_diff < 0:
        print(f'WINNER: EMA50 (+${-pnl_diff:,.2f} | +{-pnl_pct:.1f}%)')
    else:
        print('RESULT: TIE')
    print('='*100)

    return ema50_stats, opp_fvg_stats


if __name__ == '__main__':
    run_comparison()
