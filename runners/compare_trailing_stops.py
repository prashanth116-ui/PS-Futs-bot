"""
Compare current stop approach vs trailing stop approach.

Current: Fixed stop at FVG boundary for all contracts
Trailing:
  - Contract 1: Exit at 4R (same)
  - Contract 2: Exit at 8R, stop moves to breakeven after 4R
  - Contract 3: Runner - stop moves to +2R after 4R, then +4R after 8R
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations


def run_trade_current(session_bars, direction, fvg_num, tick_size=0.25, tick_value=12.50, contracts=3, target1_r=4, target2_r=8):
    """Current approach: Fixed stop at FVG boundary."""
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

    edge_price = entry_fvg.high if is_long else entry_fvg.low
    midpoint_price = entry_fvg.midpoint
    cts_edge = 1
    cts_midpoint = contracts - cts_edge

    fvg_stop_level = entry_fvg.low if is_long else entry_fvg.high

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

    if midpoint_entry_bar_idx is not None:
        contracts_filled = contracts
        avg_entry = (edge_price * cts_edge + midpoint_price * cts_midpoint) / contracts
        entry_bar_idx = midpoint_entry_bar_idx
    else:
        contracts_filled = cts_edge
        avg_entry = edge_price
        entry_bar_idx = edge_entry_bar_idx

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

    if contracts_filled == contracts:
        cts_t1, cts_t2, cts_runner = 1, 1, 1
    else:
        cts_t1, cts_t2, cts_runner = 0, 0, contracts_filled

    exits = []
    remaining = contracts_filled
    exited_t1 = False
    exited_t2 = False

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]

        # Fixed stop - never changes
        stop_hit = bar.close < fvg_stop_level if is_long else bar.close > fvg_stop_level
        if stop_hit:
            pnl = (bar.close - avg_entry) * remaining if is_long else (avg_entry - bar.close) * remaining
            exits.append({'type': 'STOP', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': remaining})
            remaining = 0
            break

        if cts_t1 > 0 and not exited_t1:
            t1_hit = bar.high >= target_t1 if is_long else bar.low <= target_t1
            if t1_hit:
                pnl = (target_t1 - avg_entry) * cts_t1 if is_long else (avg_entry - target_t1) * cts_t1
                exits.append({'type': 'T4R', 'pnl': pnl, 'price': target_t1, 'time': bar.timestamp, 'cts': cts_t1})
                remaining -= cts_t1
                exited_t1 = True

        if cts_t2 > 0 and not exited_t2:
            t2_hit = bar.high >= target_t2 if is_long else bar.low <= target_t2
            if t2_hit:
                pnl = (target_t2 - avg_entry) * cts_t2 if is_long else (avg_entry - target_t2) * cts_t2
                exits.append({'type': 'T8R', 'pnl': pnl, 'price': target_t2, 'time': bar.timestamp, 'cts': cts_t2})
                remaining -= cts_t2
                exited_t2 = True

        # Runner exit on opposing FVG
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

    return {
        'direction': direction,
        'entry_price': avg_entry,
        'stop_price': stop_price,
        'risk': risk,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'exits': exits,
    }


def run_trade_trailing(session_bars, direction, fvg_num, tick_size=0.25, tick_value=12.50, contracts=3, target1_r=4, target2_r=8):
    """Trailing stop approach:
    - Contract 1: Exit at 4R
    - Contract 2: Exit at 8R, stop to breakeven after 4R
    - Contract 3: Runner, stop to +2R after 4R, +4R after 8R
    """
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

    edge_price = entry_fvg.high if is_long else entry_fvg.low
    midpoint_price = entry_fvg.midpoint
    cts_edge = 1
    cts_midpoint = contracts - cts_edge


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

    if midpoint_entry_bar_idx is not None:
        contracts_filled = contracts
        avg_entry = (edge_price * cts_edge + midpoint_price * cts_midpoint) / contracts
        entry_bar_idx = midpoint_entry_bar_idx
    else:
        contracts_filled = cts_edge
        avg_entry = edge_price
        entry_bar_idx = edge_entry_bar_idx

    if is_long:
        initial_stop = entry_fvg.low
        risk = avg_entry - initial_stop
    else:
        initial_stop = entry_fvg.high
        risk = initial_stop - avg_entry

    if risk <= 0:
        return None

    target_t1 = avg_entry + (target1_r * risk) if is_long else avg_entry - (target1_r * risk)
    target_t2 = avg_entry + (target2_r * risk) if is_long else avg_entry - (target2_r * risk)

    # Trailing stop levels
    breakeven = avg_entry
    plus_2r = avg_entry + (2 * risk) if is_long else avg_entry - (2 * risk)
    plus_4r = avg_entry + (4 * risk) if is_long else avg_entry - (4 * risk)

    if contracts_filled == contracts:
        cts_t1, cts_t2, cts_runner = 1, 1, 1
    else:
        cts_t1, cts_t2, cts_runner = 0, 0, contracts_filled

    exits = []
    remaining = contracts_filled
    exited_t1 = False
    exited_t2 = False

    # Track stops per "remaining contracts" concept
    # After 4R: ct2 stop -> breakeven, ct3 stop -> +2R
    # After 8R: ct3 stop -> +4R
    current_stop_ct2 = initial_stop  # for contract 2
    current_stop_runner = initial_stop  # for runner

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]

        # Check stops based on current trailing levels
        if is_long:
            # Contract 2 stop check (if still holding)
            if not exited_t2 and cts_t2 > 0 and remaining > cts_runner:
                if bar.close < current_stop_ct2:
                    exit_price = current_stop_ct2
                    pnl = (exit_price - avg_entry) * cts_t2
                    stop_type = 'STOP_BE' if current_stop_ct2 == breakeven else 'STOP'
                    exits.append({'type': stop_type, 'pnl': pnl, 'price': exit_price, 'time': bar.timestamp, 'cts': cts_t2})
                    remaining -= cts_t2
                    exited_t2 = True

            # Runner stop check
            if remaining > 0 and remaining <= cts_runner:
                if bar.close < current_stop_runner:
                    exit_price = current_stop_runner
                    pnl = (exit_price - avg_entry) * remaining
                    if current_stop_runner == plus_4r:
                        stop_type = 'STOP_+4R'
                    elif current_stop_runner == plus_2r:
                        stop_type = 'STOP_+2R'
                    elif current_stop_runner == breakeven:
                        stop_type = 'STOP_BE'
                    else:
                        stop_type = 'STOP'
                    exits.append({'type': stop_type, 'pnl': pnl, 'price': exit_price, 'time': bar.timestamp, 'cts': remaining})
                    remaining = 0
                    break
        else:  # SHORT
            # Contract 2 stop check
            if not exited_t2 and cts_t2 > 0 and remaining > cts_runner:
                if bar.close > current_stop_ct2:
                    exit_price = current_stop_ct2
                    pnl = (avg_entry - exit_price) * cts_t2
                    stop_type = 'STOP_BE' if current_stop_ct2 == breakeven else 'STOP'
                    exits.append({'type': stop_type, 'pnl': pnl, 'price': exit_price, 'time': bar.timestamp, 'cts': cts_t2})
                    remaining -= cts_t2
                    exited_t2 = True

            # Runner stop check
            if remaining > 0 and remaining <= cts_runner:
                if bar.close > current_stop_runner:
                    exit_price = current_stop_runner
                    pnl = (avg_entry - exit_price) * remaining
                    if current_stop_runner == plus_4r:
                        stop_type = 'STOP_+4R'
                    elif current_stop_runner == plus_2r:
                        stop_type = 'STOP_+2R'
                    elif current_stop_runner == breakeven:
                        stop_type = 'STOP_BE'
                    else:
                        stop_type = 'STOP'
                    exits.append({'type': stop_type, 'pnl': pnl, 'price': exit_price, 'time': bar.timestamp, 'cts': remaining})
                    remaining = 0
                    break

        # Check 4R target
        if cts_t1 > 0 and not exited_t1:
            t1_hit = bar.high >= target_t1 if is_long else bar.low <= target_t1
            if t1_hit:
                pnl = (target_t1 - avg_entry) * cts_t1 if is_long else (avg_entry - target_t1) * cts_t1
                exits.append({'type': 'T4R', 'pnl': pnl, 'price': target_t1, 'time': bar.timestamp, 'cts': cts_t1})
                remaining -= cts_t1
                exited_t1 = True
                # TRAIL: Move stops after 4R hit
                current_stop_ct2 = breakeven
                current_stop_runner = plus_2r

        # Check 8R target
        if cts_t2 > 0 and not exited_t2:
            t2_hit = bar.high >= target_t2 if is_long else bar.low <= target_t2
            if t2_hit:
                pnl = (target_t2 - avg_entry) * cts_t2 if is_long else (avg_entry - target_t2) * cts_t2
                exits.append({'type': 'T8R', 'pnl': pnl, 'price': target_t2, 'time': bar.timestamp, 'cts': cts_t2})
                remaining -= cts_t2
                exited_t2 = True
                # TRAIL: Move runner stop to +4R after 8R hit
                current_stop_runner = plus_4r

        # Runner exit on opposing FVG (same as current)
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

    return {
        'direction': direction,
        'entry_price': avg_entry,
        'stop_price': initial_stop,
        'risk': risk,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'exits': exits,
    }


def run_trade_hybrid(session_bars, direction, fvg_num, tick_size=0.25, tick_value=12.50, contracts=3, target1_r=4, target2_r=8):
    """Hybrid approach: Only trail after 8R hits.
    - Contract 1: Exit at 4R
    - Contract 2: Exit at 8R (no stop change)
    - Contract 3: Runner - stop stays original until 8R, then moves to +4R
    """
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

    edge_price = entry_fvg.high if is_long else entry_fvg.low
    midpoint_price = entry_fvg.midpoint
    cts_edge = 1
    cts_midpoint = contracts - cts_edge

    fvg_stop_level = entry_fvg.low if is_long else entry_fvg.high

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

    if midpoint_entry_bar_idx is not None:
        contracts_filled = contracts
        avg_entry = (edge_price * cts_edge + midpoint_price * cts_midpoint) / contracts
        entry_bar_idx = midpoint_entry_bar_idx
    else:
        contracts_filled = cts_edge
        avg_entry = edge_price
        entry_bar_idx = edge_entry_bar_idx

    if is_long:
        initial_stop = entry_fvg.low
        risk = avg_entry - initial_stop
    else:
        initial_stop = entry_fvg.high
        risk = initial_stop - avg_entry

    if risk <= 0:
        return None

    target_t1 = avg_entry + (target1_r * risk) if is_long else avg_entry - (target1_r * risk)
    target_t2 = avg_entry + (target2_r * risk) if is_long else avg_entry - (target2_r * risk)

    # Trailing stop level - only used after 8R
    plus_4r = avg_entry + (4 * risk) if is_long else avg_entry - (4 * risk)

    if contracts_filled == contracts:
        cts_t1, cts_t2, cts_runner = 1, 1, 1
    else:
        cts_t1, cts_t2, cts_runner = 0, 0, contracts_filled

    exits = []
    remaining = contracts_filled
    exited_t1 = False
    exited_t2 = False

    # Runner stop - starts at initial, moves to +4R only after 8R hits
    current_stop_runner = initial_stop

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]

        # Check stops - fixed for ct1/ct2, trailing for runner only after 8R
        if is_long:
            # Fixed stop for contracts 1 & 2
            if (not exited_t1 or not exited_t2) and remaining > cts_runner:
                if bar.close < fvg_stop_level:
                    # Stop out remaining non-runner contracts
                    stopped_cts = remaining - (cts_runner if exited_t1 and exited_t2 else 0)
                    if stopped_cts > 0:
                        pnl = (bar.close - avg_entry) * stopped_cts
                        exits.append({'type': 'STOP', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': stopped_cts})
                        remaining -= stopped_cts
                        if not exited_t1:
                            exited_t1 = True
                        if not exited_t2:
                            exited_t2 = True

            # Runner stop check (uses trailing stop after 8R)
            if remaining > 0 and remaining <= cts_runner:
                if bar.close < current_stop_runner:
                    exit_price = current_stop_runner
                    pnl = (exit_price - avg_entry) * remaining
                    stop_type = 'STOP_+4R' if current_stop_runner == plus_4r else 'STOP'
                    exits.append({'type': stop_type, 'pnl': pnl, 'price': exit_price, 'time': bar.timestamp, 'cts': remaining})
                    remaining = 0
                    break
        else:  # SHORT
            # Fixed stop for contracts 1 & 2
            if (not exited_t1 or not exited_t2) and remaining > cts_runner:
                if bar.close > fvg_stop_level:
                    stopped_cts = remaining - (cts_runner if exited_t1 and exited_t2 else 0)
                    if stopped_cts > 0:
                        pnl = (avg_entry - bar.close) * stopped_cts
                        exits.append({'type': 'STOP', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': stopped_cts})
                        remaining -= stopped_cts
                        if not exited_t1:
                            exited_t1 = True
                        if not exited_t2:
                            exited_t2 = True

            # Runner stop check
            if remaining > 0 and remaining <= cts_runner:
                if bar.close > current_stop_runner:
                    exit_price = current_stop_runner
                    pnl = (avg_entry - exit_price) * remaining
                    stop_type = 'STOP_+4R' if current_stop_runner == plus_4r else 'STOP'
                    exits.append({'type': stop_type, 'pnl': pnl, 'price': exit_price, 'time': bar.timestamp, 'cts': remaining})
                    remaining = 0
                    break

        # Check 4R target
        if cts_t1 > 0 and not exited_t1:
            t1_hit = bar.high >= target_t1 if is_long else bar.low <= target_t1
            if t1_hit:
                pnl = (target_t1 - avg_entry) * cts_t1 if is_long else (avg_entry - target_t1) * cts_t1
                exits.append({'type': 'T4R', 'pnl': pnl, 'price': target_t1, 'time': bar.timestamp, 'cts': cts_t1})
                remaining -= cts_t1
                exited_t1 = True
                # HYBRID: NO stop change after 4R

        # Check 8R target
        if cts_t2 > 0 and not exited_t2:
            t2_hit = bar.high >= target_t2 if is_long else bar.low <= target_t2
            if t2_hit:
                pnl = (target_t2 - avg_entry) * cts_t2 if is_long else (avg_entry - target_t2) * cts_t2
                exits.append({'type': 'T8R', 'pnl': pnl, 'price': target_t2, 'time': bar.timestamp, 'cts': cts_t2})
                remaining -= cts_t2
                exited_t2 = True
                # HYBRID: Move runner stop to +4R ONLY after 8R hits
                current_stop_runner = plus_4r

        # Runner exit on opposing FVG
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

    return {
        'direction': direction,
        'entry_price': avg_entry,
        'stop_price': initial_stop,
        'risk': risk,
        'total_pnl': total_pnl,
        'total_dollars': total_dollars,
        'exits': exits,
    }


def run_comparison(symbol='ES', days=10, contracts=3):
    """Run comparison backtest over multiple days."""

    tick_size = 0.25 if symbol == 'ES' else 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25

    print(f'Fetching {symbol} 3m data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=5000)

    if not all_bars:
        print('No data available')
        return

    # Get unique dates
    dates = sorted(set(b.timestamp.date() for b in all_bars))
    dates = dates[-days:] if len(dates) > days else dates

    print(f'Testing {len(dates)} days: {dates[0]} to {dates[-1]}')
    print()

    current_results = []
    trailing_results = []
    hybrid_results = []

    for test_date in dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == test_date]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        for direction in ['LONG', 'SHORT']:
            # Current approach
            result_current = run_trade_current(session_bars, direction, 1, tick_size, tick_value, contracts)
            if result_current:
                result_current['date'] = test_date
                current_results.append(result_current)

            # Trailing approach
            result_trailing = run_trade_trailing(session_bars, direction, 1, tick_size, tick_value, contracts)
            if result_trailing:
                result_trailing['date'] = test_date
                trailing_results.append(result_trailing)

            # Hybrid approach
            result_hybrid = run_trade_hybrid(session_bars, direction, 1, tick_size, tick_value, contracts)
            if result_hybrid:
                result_hybrid['date'] = test_date
                hybrid_results.append(result_hybrid)

    # Print comparison
    print('='*80)
    print(f'{symbol} BACKTEST COMPARISON - {len(dates)} Days - {contracts} Contracts')
    print('='*80)

    print('\n' + '-'*80)
    print('CURRENT APPROACH (Fixed Stop at FVG)')
    print('-'*80)

    current_total = 0
    current_wins = 0
    current_losses = 0
    for r in current_results:
        pnl = r['total_dollars']
        current_total += pnl
        if pnl > 0:
            current_wins += 1
        elif pnl < 0:
            current_losses += 1
        exits_str = ', '.join([f"{e['type']}:{e['cts']}ct" for e in r['exits']])
        print(f"  {r['date']} {r['direction']:5} | Entry: {r['entry_price']:.2f} | P/L: ${pnl:+,.2f} | {exits_str}")

    print(f'\n  Total Trades: {len(current_results)} | Wins: {current_wins} | Losses: {current_losses}')
    print(f'  Win Rate: {current_wins/len(current_results)*100:.1f}%' if current_results else '  No trades')
    print(f'  TOTAL P/L: ${current_total:+,.2f}')

    print('\n' + '-'*80)
    print('TRAILING APPROACH (BE after 4R, +2R/+4R trail)')
    print('-'*80)

    trailing_total = 0
    trailing_wins = 0
    trailing_losses = 0
    for r in trailing_results:
        pnl = r['total_dollars']
        trailing_total += pnl
        if pnl > 0:
            trailing_wins += 1
        elif pnl < 0:
            trailing_losses += 1
        exits_str = ', '.join([f"{e['type']}:{e['cts']}ct" for e in r['exits']])
        print(f"  {r['date']} {r['direction']:5} | Entry: {r['entry_price']:.2f} | P/L: ${pnl:+,.2f} | {exits_str}")

    print(f'\n  Total Trades: {len(trailing_results)} | Wins: {trailing_wins} | Losses: {trailing_losses}')
    print(f'  Win Rate: {trailing_wins/len(trailing_results)*100:.1f}%' if trailing_results else '  No trades')
    print(f'  TOTAL P/L: ${trailing_total:+,.2f}')

    print('\n' + '-'*80)
    print('HYBRID APPROACH (Trail +4R only after 8R hits)')
    print('-'*80)

    hybrid_total = 0
    hybrid_wins = 0
    hybrid_losses = 0
    for r in hybrid_results:
        pnl = r['total_dollars']
        hybrid_total += pnl
        if pnl > 0:
            hybrid_wins += 1
        elif pnl < 0:
            hybrid_losses += 1
        exits_str = ', '.join([f"{e['type']}:{e['cts']}ct" for e in r['exits']])
        print(f"  {r['date']} {r['direction']:5} | Entry: {r['entry_price']:.2f} | P/L: ${pnl:+,.2f} | {exits_str}")

    print(f'\n  Total Trades: {len(hybrid_results)} | Wins: {hybrid_wins} | Losses: {hybrid_losses}')
    print(f'  Win Rate: {hybrid_wins/len(hybrid_results)*100:.1f}%' if hybrid_results else '  No trades')
    print(f'  TOTAL P/L: ${hybrid_total:+,.2f}')

    print('\n' + '='*80)
    print('COMPARISON SUMMARY')
    print('='*80)
    print(f'  Current Approach:  ${current_total:+,.2f} ({current_wins}W/{current_losses}L)')
    print(f'  Trailing Approach: ${trailing_total:+,.2f} ({trailing_wins}W/{trailing_losses}L)')
    print(f'  Hybrid Approach:   ${hybrid_total:+,.2f} ({hybrid_wins}W/{hybrid_losses}L)')
    print('-'*80)
    print(f'  Trailing vs Current: ${trailing_total - current_total:+,.2f}')
    print(f'  Hybrid vs Current:   ${hybrid_total - current_total:+,.2f}')
    print('='*80)

    return {
        'current': {'total': current_total, 'wins': current_wins, 'losses': current_losses, 'trades': current_results},
        'trailing': {'total': trailing_total, 'wins': trailing_wins, 'losses': trailing_losses, 'trades': trailing_results},
        'hybrid': {'total': hybrid_total, 'wins': hybrid_wins, 'losses': hybrid_losses, 'trades': hybrid_results},
    }


if __name__ == '__main__':
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    run_comparison(symbol=symbol, days=days)
