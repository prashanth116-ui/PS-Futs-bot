"""
ICT Sweep Strategy — Trade Simulator

Shared by runner and plotter. Accepts TradeEntry, simulates T1/T2/Runner exits.
"""
from strategies.ict_sweep.strategy import TradeEntry


def is_swing_high(bars, idx, lookback=2):
    """Check if bar at idx is a swing high."""
    if idx < lookback or idx >= len(bars) - lookback:
        return False
    bar_high = bars[idx].high
    for i in range(1, lookback + 1):
        if bar_high <= bars[idx - i].high or bar_high <= bars[idx + i].high:
            return False
    return True


def is_swing_low(bars, idx, lookback=2):
    """Check if bar at idx is a swing low."""
    if idx < lookback or idx >= len(bars) - lookback:
        return False
    bar_low = bars[idx].low
    for i in range(1, lookback + 1):
        if bar_low >= bars[idx - i].low or bar_low >= bars[idx + i].low:
            return False
    return True


def simulate_trade(bars, entry: TradeEntry, tick_size: float, tick_value: float,
                   contracts: int, t1_r: int = 3, trail_r: int = 6,
                   t2_buffer_ticks: int = 4, runner_buffer_ticks: int = 6,
                   debug: bool = False):
    """
    Simulate trade execution with hybrid exit: partial T1 + structure trailing.

    FVG-close stop: candle CLOSE past FVG boundary stops out.
    Safety cap prevents runaway losses.

    Exit structure:
    - Pre-T1: FVG-close stop exits ALL contracts
    - T1 hit (t1_r): Fixed exit 1 contract, floor at t1_r for remaining
    - Between T1 and trail_r: Floor at T1 profit as hard stop
    - trail_r hit: Activate structure trailing for T2 (4-tick) and Runner (6-tick)
    - EOD: Exit all remaining at close

    Contract allocation:
    - 3 contracts: T1=1ct, T2=1ct, Runner=1ct
    - 2 contracts: T1=1ct, T2=1ct, Runner=0

    Returns:
        Trade result dict with 'exits' list, or None if insufficient bars.
    """
    if len(bars) < 2:
        return None

    ep = entry.entry_price
    risk = entry.risk_pts

    is_long = entry.direction == 'LONG'
    if is_long:
        t1_price = ep + (risk * t1_r)
        trail_activate_price = ep + (risk * trail_r)
        t1_floor_price = ep + (risk * t1_r)
    else:
        t1_price = ep - (risk * t1_r)
        trail_activate_price = ep - (risk * trail_r)
        t1_floor_price = ep - (risk * t1_r)

    # FVG-close stop level
    fvg_stop_level = entry.fvg.top if entry.direction == 'SHORT' else entry.fvg.bottom
    max_loss_ticks = 100

    # Contract allocation
    t1_contracts = 1
    t2_contracts = 1
    runner_contracts = max(0, contracts - 2)

    t2_buffer = t2_buffer_ticks * tick_size
    runner_buffer = runner_buffer_ticks * tick_size

    # State
    t1_exited = False
    t2_exited = False
    runner_exited = (runner_contracts == 0)
    trail_active = False
    trail_activation_bar = None
    t2_trail_stop = None
    runner_trail_stop = None

    exits = []
    total_pnl = 0.0

    for i, bar in enumerate(bars[1:], 1):
        remaining = (0 if t1_exited else t1_contracts) + \
                    (0 if t2_exited else t2_contracts) + \
                    (0 if runner_exited else runner_contracts)
        if remaining == 0:
            break

        # --- PRE-T1: FVG-close stop exits ALL ---
        if not t1_exited:
            stopped = False
            if is_long:
                loss_ticks = (ep - bar.low) / tick_size
                if bar.close < fvg_stop_level or loss_ticks >= max_loss_ticks:
                    exit_price = bar.close if bar.close < fvg_stop_level else bar.low
                    stopped = True
            else:
                loss_ticks = (bar.high - ep) / tick_size
                if bar.close > fvg_stop_level or loss_ticks >= max_loss_ticks:
                    exit_price = bar.close if bar.close > fvg_stop_level else bar.high
                    stopped = True

            if stopped:
                pnl_ticks = ((exit_price - ep) if is_long else (ep - exit_price)) / tick_size
                leg_pnl = pnl_ticks * tick_value * remaining
                total_pnl += leg_pnl
                exits.append({'leg': 'STOP', 'price': exit_price, 'contracts': remaining,
                              'pnl': leg_pnl, 'bar_idx': i})
                return {
                    'entry': ep, 'exit': exit_price,
                    'pnl_ticks': pnl_ticks, 'pnl_dollars': total_pnl,
                    'hit_target': False, 'bars_held': i, 'exits': exits,
                }

        # --- Check T1 hit ---
        if not t1_exited:
            t1_hit = (bar.high >= t1_price) if is_long else (bar.low <= t1_price)
            if t1_hit:
                t1_exited = True
                pnl_ticks_t1 = ((t1_price - ep) if is_long else (ep - t1_price)) / tick_size
                leg_pnl = pnl_ticks_t1 * tick_value * t1_contracts
                total_pnl += leg_pnl
                exits.append({'leg': 'T1', 'price': t1_price, 'contracts': t1_contracts,
                              'pnl': leg_pnl, 'bar_idx': i})
                if debug:
                    print(f"  SIM bar {i}: T1 hit | H={bar.high} L={bar.low} C={bar.close} | trail_activate={trail_activate_price} floor={t1_floor_price}")

        # --- Check trail activation (BEFORE floor — if trail activates, trail stops take over) ---
        if t1_exited and not trail_active:
            trail_hit = (bar.high >= trail_activate_price) if is_long else (bar.low <= trail_activate_price)
            if debug and not trail_active:
                print(f"  SIM bar {i}: trail_check | H={bar.high} L={bar.low} | need {'<=' if not is_long else '>='}{trail_activate_price} | hit={trail_hit}")
            if trail_hit:
                trail_active = True
                trail_activation_bar = i
                if is_long:
                    # Start with lowest low of recent bars as fallback
                    best_swing = min(bars[j].low for j in range(max(0, i - 10), i + 1))
                    for j in range(max(0, i - 10), i):
                        if j >= 1 and is_swing_low(bars, j, lookback=2):
                            best_swing = max(best_swing, bars[j].low)
                    t2_trail_stop = best_swing - t2_buffer
                    runner_trail_stop = best_swing - runner_buffer
                else:
                    # Start with highest high of recent bars as fallback
                    best_swing = max(bars[j].high for j in range(max(0, i - 10), i + 1))
                    for j in range(max(0, i - 10), i):
                        if j >= 1 and is_swing_high(bars, j, lookback=2):
                            best_swing = min(best_swing, bars[j].high)
                    t2_trail_stop = best_swing + t2_buffer
                    runner_trail_stop = best_swing + runner_buffer
                if debug:
                    print(f"  SIM bar {i}: TRAIL ACTIVE | swing={best_swing} t2_stop={t2_trail_stop} runner_stop={runner_trail_stop}")

        # --- Post-T1: floor at T1 profit (only if trail NOT active) ---
        if t1_exited and not trail_active:
            floor_hit = False
            if is_long and bar.low <= t1_floor_price:
                floor_hit = True
                exit_price = t1_floor_price
            elif not is_long and bar.high >= t1_floor_price:
                floor_hit = True
                exit_price = t1_floor_price

            if floor_hit:
                remaining_after_t1 = (0 if t2_exited else t2_contracts) + \
                                     (0 if runner_exited else runner_contracts)
                if remaining_after_t1 > 0:
                    pnl_ticks_floor = ((exit_price - ep) if is_long else (ep - exit_price)) / tick_size
                    leg_pnl = pnl_ticks_floor * tick_value * remaining_after_t1
                    total_pnl += leg_pnl
                    exits.append({'leg': 'FLOOR', 'price': exit_price,
                                  'contracts': remaining_after_t1, 'pnl': leg_pnl, 'bar_idx': i})
                    t2_exited = True
                    runner_exited = True
                    pnl_ticks = ((exit_price - ep) if is_long else (ep - exit_price)) / tick_size
                    return {
                        'entry': ep, 'exit': exit_price,
                        'pnl_ticks': pnl_ticks, 'pnl_dollars': total_pnl,
                        'hit_target': True, 'bars_held': i, 'exits': exits,
                    }

        # --- Update structure trail ---
        if trail_active:
            if is_long:
                if i >= 3 and is_swing_low(bars, i - 2, lookback=2):
                    new_trail = bars[i - 2].low
                    t2_trail_stop = max(t2_trail_stop, new_trail - t2_buffer)
                    runner_trail_stop = max(runner_trail_stop, new_trail - runner_buffer)
            else:
                if i >= 3 and is_swing_high(bars, i - 2, lookback=2):
                    new_trail = bars[i - 2].high
                    t2_trail_stop = min(t2_trail_stop, new_trail + t2_buffer)
                    runner_trail_stop = min(runner_trail_stop, new_trail + runner_buffer)

            # Check T2 trail (skip activation bar — give 1 bar of room)
            if not t2_exited and i > trail_activation_bar:
                t2_stopped = (bar.low <= t2_trail_stop) if is_long else (bar.high >= t2_trail_stop)
                if t2_stopped:
                    t2_exited = True
                    exit_price = t2_trail_stop
                    pnl_ticks_t2 = ((exit_price - ep) if is_long else (ep - exit_price)) / tick_size
                    leg_pnl = pnl_ticks_t2 * tick_value * t2_contracts
                    total_pnl += leg_pnl
                    exits.append({'leg': 'T2', 'price': exit_price, 'contracts': t2_contracts,
                                  'pnl': leg_pnl, 'bar_idx': i})
                    if debug:
                        print(f"  SIM bar {i}: T2 EXIT @ {exit_price} | H={bar.high} L={bar.low}")

            # Check Runner trail (skip activation bar)
            if not runner_exited and i > trail_activation_bar:
                runner_stopped = (bar.low <= runner_trail_stop) if is_long else (bar.high >= runner_trail_stop)
                if runner_stopped:
                    runner_exited = True
                    exit_price = runner_trail_stop
                    pnl_ticks_r = ((exit_price - ep) if is_long else (ep - exit_price)) / tick_size
                    leg_pnl = pnl_ticks_r * tick_value * runner_contracts
                    total_pnl += leg_pnl
                    exits.append({'leg': 'Runner', 'price': exit_price, 'contracts': runner_contracts,
                                  'pnl': leg_pnl, 'bar_idx': i})
                    if debug:
                        print(f"  SIM bar {i}: Runner EXIT @ {exit_price} | H={bar.high} L={bar.low}")

        # All legs exited?
        if t1_exited and t2_exited and runner_exited:
            last_exit = exits[-1] if exits else {'price': ep, 'bar_idx': i}
            pnl_ticks = ((last_exit['price'] - ep) if is_long else (ep - last_exit['price'])) / tick_size
            return {
                'entry': ep, 'exit': last_exit['price'],
                'pnl_ticks': pnl_ticks, 'pnl_dollars': total_pnl,
                'hit_target': True, 'bars_held': i, 'exits': exits,
            }

    # End of day
    exit_price = bars[-1].close
    remaining = (0 if t1_exited else t1_contracts) + \
                (0 if t2_exited else t2_contracts) + \
                (0 if runner_exited else runner_contracts)

    if remaining > 0:
        pnl_ticks_eod = ((exit_price - ep) if is_long else (ep - exit_price)) / tick_size
        leg_pnl = pnl_ticks_eod * tick_value * remaining
        total_pnl += leg_pnl
        exits.append({'leg': 'EOD', 'price': exit_price, 'contracts': remaining,
                      'pnl': leg_pnl, 'bar_idx': len(bars) - 1})

    pnl_ticks = ((exit_price - ep) if is_long else (ep - exit_price)) / tick_size
    return {
        'entry': ep, 'exit': exit_price,
        'pnl_ticks': pnl_ticks, 'pnl_dollars': total_pnl,
        'hit_target': t1_exited, 'bars_held': len(bars) - 1, 'exits': exits,
    }
