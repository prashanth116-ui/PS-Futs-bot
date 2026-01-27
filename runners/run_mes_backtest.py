"""
Run full MES backtest with re-entry strategy.
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time
from collections import defaultdict
from tvDatafeed import TvDatafeed, Interval
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations


class Bar:
    def __init__(self, timestamp, open_, high, low, close, volume):
        self.timestamp = timestamp
        self.open = open_
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume


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


def run_trade(session_bars, direction, fvg_num, tick_size=0.25, tick_value=1.25, contracts=3, target1_r=4, target2_r=8):
    """Run single trade simulation. Returns result dict or None."""
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
    if is_long:
        stop_price = entry_fvg.low - (2 * tick_size)
        risk = entry_price - stop_price
    else:
        stop_price = entry_fvg.high + (2 * tick_size)
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

    # Simulate exits - scale based on contract size
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
        bar_ema50 = ema_50[i] if i < len(ema_50) and ema_50[i] else None

        # Check stop
        stop_hit = bar.low <= stop_price if is_long else bar.high >= stop_price
        if stop_hit:
            pnl = (stop_price - entry_price) * remaining if is_long else (entry_price - stop_price) * remaining
            exits.append({'type': 'STOP', 'pnl': pnl, 'price': stop_price, 'time': bar.timestamp, 'cts': remaining})
            remaining = 0
            break

        # Check T1 - exit portion of contracts
        t1_hit = bar.high >= target_t1 if is_long else bar.low <= target_t1
        if not exited_t1 and t1_hit:
            exit_cts = min(cts_t1, remaining)
            pnl = (target_t1 - entry_price) * exit_cts if is_long else (entry_price - target_t1) * exit_cts
            exits.append({'type': f'T{target1_r}R', 'pnl': pnl, 'price': target_t1, 'time': bar.timestamp, 'cts': exit_cts})
            remaining -= exit_cts
            exited_t1 = True

        # Check T2 - exit portion of contracts
        t2_hit = bar.high >= target_t2 if is_long else bar.low <= target_t2
        if not exited_t2 and t2_hit and remaining > cts_runner:
            exit_cts = min(cts_t2, remaining - cts_runner)
            pnl = (target_t2 - entry_price) * exit_cts if is_long else (entry_price - target_t2) * exit_cts
            exits.append({'type': f'T{target2_r}R', 'pnl': pnl, 'price': target_t2, 'time': bar.timestamp, 'cts': exit_cts})
            remaining -= exit_cts
            exited_t2 = True

        # Check EMA50 runner exit - exit remaining contracts
        if remaining > 0 and remaining <= cts_runner and bar_ema50:
            ema_exit = bar.close < bar_ema50 if is_long else bar.close > bar_ema50
            if ema_exit:
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


def run_mes_backtest(contracts=3, target1_r=4, target2_r=8):
    """Run full MES backtest with re-entry strategy."""

    tick_size = 0.25
    tick_value = 1.25

    # Fetch all data at once
    print('Fetching MES 3m data...')
    tv = TvDatafeed()
    data = tv.get_hist(symbol='MES1!', exchange='CME_MINI', interval=Interval.in_3_minute, n_bars=10000)

    if data is None or len(data) == 0:
        print('No data available')
        return []

    # Convert to Bar objects
    all_bars = []
    for idx, row in data.iterrows():
        bar = Bar(idx.to_pydatetime(), row['open'], row['high'], row['low'], row['close'], row['volume'])
        all_bars.append(bar)

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
    print(f'{len(trading_days)}-DAY BACKTEST - MES 3m - Re-entry Strategy - {contracts} CONTRACTS')
    print('='*80)
    print(f'Exit plan: {contracts//3} cts @ {target1_r}R, {contracts//3} cts @ {target2_r}R, {contracts - 2*(contracts//3)} cts @ EMA50 runner')
    print(f'Tick value: ${tick_value} (micro)')
    print('='*80)

    all_results = []

    for d in trading_days:
        day_bars = bars_by_date[d]
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Try LONG
        result = run_trade(session_bars, 'LONG', 1, tick_size=tick_size, tick_value=tick_value,
                          contracts=contracts, target1_r=target1_r, target2_r=target2_r)
        if result:
            result['date'] = d
            all_results.append(result)
            if result['was_stopped']:
                result2 = run_trade(session_bars, 'LONG', 2, tick_size=tick_size, tick_value=tick_value,
                                   contracts=contracts, target1_r=target1_r, target2_r=target2_r)
                if result2:
                    result2['date'] = d
                    result2['is_reentry'] = True
                    all_results.append(result2)

        # Try SHORT
        result = run_trade(session_bars, 'SHORT', 1, tick_size=tick_size, tick_value=tick_value,
                          contracts=contracts, target1_r=target1_r, target2_r=target2_r)
        if result:
            result['date'] = d
            all_results.append(result)
            if result['was_stopped']:
                result2 = run_trade(session_bars, 'SHORT', 2, tick_size=tick_size, tick_value=tick_value,
                                   contracts=contracts, target1_r=target1_r, target2_r=target2_r)
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
    winning_trades_pnl = 0
    losing_trades_pnl = 0

    for r in all_results:
        if r['total_pnl'] > 0.01:
            wins += 1
            winning_trades_pnl += r['total_dollars']
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
    profit_factor = abs(winning_trades_pnl) / abs(losing_trades_pnl) if losing_trades_pnl < 0 else float('inf')

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
    print()
    print(f'  ES Equivalent:  ${total_pnl * 10:+,.2f} (10x)')

    return all_results


if __name__ == '__main__':
    import sys
    contracts = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    results = run_mes_backtest(contracts=contracts)
