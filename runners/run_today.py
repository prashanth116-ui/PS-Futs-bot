"""
Run backtest for today with ICT FVG Strategy (V2-Balanced).

Strategy Features:
- Stop buffer: +2 ticks beyond FVG boundary (reduces whipsaws)
- HTF bias: EMA 20/50 trend filter (trade with trend)
- Min FVG size: 6 ticks (filters tiny FVGs)
- Displacement: 1.2x body size (filters weak FVGs)
- Extended killzones: London (3-5 AM), NY AM (9:30-12), NY PM (1:30-3:30)
- Partial fill entry: 1 ct @ edge, 2 cts @ midpoint
- Hybrid trailing: Fixed stop until 8R, then trail to +4R
- Runner exit: Opposing FVG or trailing stop
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_fvg_mitigation


def calculate_ema(bars, period):
    """Calculate EMA for the given bars."""
    if len(bars) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(b.close for b in bars[:period]) / period
    for bar in bars[period:]:
        ema = (bar.close - ema) * multiplier + ema
    return ema


def is_displacement_candle(bar, avg_body_size, threshold=1.2):
    """Check if candle is a displacement candle (strong momentum)."""
    body_size = abs(bar.close - bar.open)
    return body_size > avg_body_size * threshold


def is_in_killzone(timestamp):
    """Check if time is in extended killzones."""
    t = timestamp.time()

    # London Open: 3:00 AM - 5:00 AM ET
    london = dt_time(3, 0) <= t <= dt_time(5, 0)

    # NY AM Session: 9:30 AM - 12:00 PM ET
    ny_am = dt_time(9, 30) <= t <= dt_time(12, 0)

    # NY PM Session: 1:30 PM - 3:30 PM ET
    ny_pm = dt_time(13, 30) <= t <= dt_time(15, 30)

    return london or ny_am or ny_pm


def run_trade(
    session_bars,
    direction,
    fvg_num,
    tick_size=0.25,
    tick_value=12.50,
    contracts=3,
    target1_r=4,
    target2_r=8,
    # Strategy Parameters
    stop_buffer_ticks=2,
    min_fvg_ticks=6,
    displacement_threshold=1.2,
    require_displacement=True,
    require_killzone=True,
    require_htf_bias=True,
):
    """Run trade with ICT FVG Strategy (V2-Balanced)."""
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'
    opposing_fvg_dir = 'BEARISH' if is_long else 'BULLISH'

    # Calculate average body size for displacement detection
    body_sizes = [abs(b.close - b.open) for b in session_bars[:50]]
    avg_body_size = sum(body_sizes) / len(body_sizes) if body_sizes else tick_size * 4

    # Calculate EMA for HTF bias
    ema_fast = calculate_ema(session_bars, 20)
    ema_slow = calculate_ema(session_bars, 50)

    # HTF Bias filter - only trade with trend
    if require_htf_bias and ema_fast is not None and ema_slow is not None:
        if is_long and ema_fast < ema_slow:
            return None  # Don't go long in downtrend
        if not is_long and ema_fast > ema_slow:
            return None  # Don't go short in uptrend

    fvg_config = {
        'min_fvg_ticks': min_fvg_ticks,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)

    candidate_fvgs = [f for f in all_fvgs if f.direction == fvg_dir]
    candidate_fvgs.sort(key=lambda f: f.created_bar_index)

    if len(candidate_fvgs) < fvg_num:
        return None

    valid_fvg_count = 0
    entry_fvg = None
    edge_entry_bar_idx = None
    edge_entry_time = None
    midpoint_entry_bar_idx = None
    midpoint_entry_time = None

    for fvg in candidate_fvgs:
        fvg.mitigated = False
        fvg.mitigation_bar_index = None

        # Displacement filter - only trade FVGs from strong moves
        if require_displacement:
            if fvg.created_bar_index < len(session_bars):
                creating_bar = session_bars[fvg.created_bar_index]
                if not is_displacement_candle(creating_bar, avg_body_size, displacement_threshold):
                    continue

        edge_price = fvg.high if is_long else fvg.low
        midpoint_price = fvg.midpoint

        edge_hit_idx = None
        edge_hit_time = None
        midpoint_hit_idx = None
        midpoint_hit_time = None

        for i in range(fvg.created_bar_index + 1, len(session_bars)):
            bar = session_bars[i]

            # Update FVG mitigation status
            update_fvg_mitigation(fvg, bar, i, fvg_config)

            # If FVG mitigated before entry, skip this FVG
            if fvg.mitigated and edge_hit_idx is None:
                break

            # Killzone filter - only enter during high-probability times
            if require_killzone and not is_in_killzone(bar.timestamp):
                continue

            # Check for price entering FVG zone
            if edge_hit_idx is None and not fvg.mitigated:
                if is_long:
                    edge_hit = bar.low <= edge_price
                else:
                    edge_hit = bar.high >= edge_price

                if edge_hit:
                    edge_hit_idx = i
                    edge_hit_time = bar.timestamp

            # Check midpoint for full fill
            if edge_hit_idx is not None and midpoint_hit_idx is None and not fvg.mitigated:
                midpoint_hit = bar.low <= midpoint_price if is_long else bar.high >= midpoint_price
                if midpoint_hit:
                    midpoint_hit_idx = i
                    midpoint_hit_time = bar.timestamp
                    break

            if fvg.mitigated and edge_hit_idx is not None:
                break

        if edge_hit_idx is not None:
            valid_fvg_count += 1
            if valid_fvg_count == fvg_num:
                entry_fvg = fvg
                edge_entry_bar_idx = edge_hit_idx
                edge_entry_time = edge_hit_time
                midpoint_entry_bar_idx = midpoint_hit_idx
                midpoint_entry_time = midpoint_hit_time
                break

    if entry_fvg is None or edge_entry_bar_idx is None:
        return None

    # Entry levels
    edge_price = entry_fvg.high if is_long else entry_fvg.low
    midpoint_price = entry_fvg.midpoint

    cts_edge = 1
    cts_midpoint = contracts - cts_edge

    # Stop with buffer
    if is_long:
        stop_price = entry_fvg.low - (stop_buffer_ticks * tick_size)
    else:
        stop_price = entry_fvg.high + (stop_buffer_ticks * tick_size)

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

    # Risk calculation
    if is_long:
        risk = avg_entry - stop_price
    else:
        risk = stop_price - avg_entry

    if risk <= 0:
        return None

    # Targets
    target_t1 = avg_entry + (target1_r * risk) if is_long else avg_entry - (target1_r * risk)
    target_t2 = avg_entry + (target2_r * risk) if is_long else avg_entry - (target2_r * risk)
    plus_4r = avg_entry + (4 * risk) if is_long else avg_entry - (4 * risk)

    # Position sizing (1/3 each)
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

    # Runner stop - starts at buffered stop, moves to +4R after 8R hits
    runner_stop = stop_price
    runner_stop_type = 'STOP'

    # Reset FVG mitigation for trade simulation
    entry_fvg.mitigated = False
    entry_fvg.mitigation_bar_index = None

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]

        # Check stop (using buffered stop)
        if not exited_t1 or not exited_t2:
            if is_long:
                stop_hit = bar.low <= stop_price
            else:
                stop_hit = bar.high >= stop_price

            if stop_hit:
                pnl = (stop_price - avg_entry) * remaining if is_long else (avg_entry - stop_price) * remaining
                exits.append({'type': 'STOP', 'pnl': pnl, 'price': stop_price, 'time': bar.timestamp, 'cts': remaining})
                remaining = 0
                break

        # Check runner trailing stop (after T1 and T2 exited)
        if remaining > 0 and remaining <= cts_runner and exited_t1 and exited_t2:
            if is_long:
                if bar.low <= runner_stop:
                    pnl = (runner_stop - avg_entry) * remaining
                    exits.append({'type': runner_stop_type, 'pnl': pnl, 'price': runner_stop, 'time': bar.timestamp, 'cts': remaining})
                    remaining = 0
                    break
            else:
                if bar.high >= runner_stop:
                    pnl = (avg_entry - runner_stop) * remaining
                    exits.append({'type': runner_stop_type, 'pnl': pnl, 'price': runner_stop, 'time': bar.timestamp, 'cts': remaining})
                    remaining = 0
                    break

        # Check 4R target
        if cts_t1 > 0 and not exited_t1:
            t1_hit = bar.high >= target_t1 if is_long else bar.low <= target_t1
            if t1_hit:
                exit_cts = min(cts_t1, remaining)
                pnl = (target_t1 - avg_entry) * exit_cts if is_long else (avg_entry - target_t1) * exit_cts
                exits.append({'type': f'T{target1_r}R', 'pnl': pnl, 'price': target_t1, 'time': bar.timestamp, 'cts': exit_cts})
                remaining -= exit_cts
                exited_t1 = True

        # Check 8R target
        if cts_t2 > 0 and not exited_t2 and remaining > cts_runner:
            t2_hit = bar.high >= target_t2 if is_long else bar.low <= target_t2
            if t2_hit:
                exit_cts = min(cts_t2, remaining - cts_runner)
                pnl = (target_t2 - avg_entry) * exit_cts if is_long else (avg_entry - target_t2) * exit_cts
                exits.append({'type': f'T{target2_r}R', 'pnl': pnl, 'price': target_t2, 'time': bar.timestamp, 'cts': exit_cts})
                remaining -= exit_cts
                exited_t2 = True
                # HYBRID: Move runner stop to +4R after 8R hits
                runner_stop = plus_4r
                runner_stop_type = 'STOP_+4R'

        # Check Opposing FVG runner exit
        if remaining > 0 and remaining <= cts_runner:
            opposing_fvgs = [f for f in all_fvgs if f.direction == opposing_fvg_dir
                           and f.created_bar_index > entry_bar_idx
                           and f.created_bar_index <= i]
            if opposing_fvgs:
                pnl = (bar.close - avg_entry) * remaining if is_long else (avg_entry - bar.close) * remaining
                exits.append({'type': 'OPP_FVG', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': remaining})
                remaining = 0

    # End of day exit for remaining contracts
    if remaining > 0:
        last_bar = session_bars[-1]
        pnl = (last_bar.close - avg_entry) * remaining if is_long else (avg_entry - last_bar.close) * remaining
        exits.append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'cts': remaining})

    total_pnl = sum(e['pnl'] for e in exits)
    total_dollars = (total_pnl / tick_size) * tick_value
    was_stopped = any(e['type'] in ['STOP', 'STOP_+4R'] for e in exits)

    return {
        'direction': direction,
        'entry_time': entry_time,
        'entry_price': avg_entry,
        'edge_price': edge_price,
        'midpoint_price': midpoint_price,
        'contracts_filled': contracts_filled,
        'fill_type': fill_type,
        'stop_price': stop_price,
        'runner_stop': runner_stop,
        'fvg_low': entry_fvg.low,
        'fvg_high': entry_fvg.high,
        'target_4r': target_t1,
        'target_8r': target_t2,
        'plus_4r': plus_4r,
        'risk': risk,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'was_stopped': was_stopped,
        'exits': exits,
    }


def run_today(symbol='ES', contracts=3):
    """Run backtest for today."""

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
    print(f'{symbol} BACKTEST - {today} - {contracts} Contracts')
    print('='*70)
    print('Strategy: ICT FVG V2-Balanced')
    print('  - Stop buffer: +2 ticks')
    print('  - HTF bias: EMA 20/50')
    print('  - Min FVG: 6 ticks')
    print('  - Displacement: 1.2x')
    print('  - Killzones: London + NY AM + NY PM')
    print('  - Entry: 1 ct @ edge, 2 cts @ midpoint')
    print('  - Targets: 4R, 8R, Runner')
    print('  - Hybrid trailing: +4R after 8R hits')
    print('='*70)

    all_results = []

    for direction in ['LONG', 'SHORT']:
        result = run_trade(session_bars, direction, 1, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
        if result:
            result['date'] = today
            all_results.append(result)
            # Try re-entry if stopped out
            if result['was_stopped']:
                result2 = run_trade(session_bars, direction, 2, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
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
        print(f"  Stop: {r['stop_price']:.2f} (buffered) | Runner +4R: {r['plus_4r']:.2f}")
        print(f"  Risk: {r['risk']:.2f} pts")
        print(f"  Targets: 4R={r['target_4r']:.2f}, 8R={r['target_8r']:.2f}")
        print(f"  Exits:")
        for e in r['exits']:
            dollars = (e['pnl'] / tick_size) * tick_value
            print(f"    {e['type']}: {e['cts']} ct @ {e['price']:.2f} = ${dollars:+,.2f}")
        print(f"  Result: {result_str} | P/L: ${r['total_dollars']:+,.2f}")

    if not all_results:
        print("\nNo trades - all setups filtered out by strategy criteria")

    print()
    print('='*70)
    print(f'TOTAL P/L: ${total_pnl:+,.2f}')
    print('='*70)

    return all_results


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    contracts = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    run_today(symbol=symbol, contracts=contracts)
