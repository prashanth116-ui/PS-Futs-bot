"""
Run backtest for today with ICT FVG Strategy (V6-Aggressive).

Strategy Features:
- Stop buffer: +2 ticks beyond FVG boundary (reduces whipsaws)
- HTF bias: EMA 20/50 trend filter at entry time (trade with trend)
- ADX > 17 filter: Only trade when market is trending (avoids chop)
- DI Direction: LONG only if +DI > -DI, SHORT only if -DI > +DI
- Max 2 losses/day: Stop trading after 2 losing trades
- Min FVG size: 5 ticks (filters tiny FVGs)
- Displacement: 1.0x body size (lower threshold to catch more setups)
- Killzones: DISABLED (trades any time during session)
- Entry: AT FVG CREATION (no waiting for retracement)

Exit Strategy (Tiered Structure Trail):
- 1st contract: Fast trail after 4R touch (2-tick buffer, trails swing highs/lows)
- 2nd contract: Standard trail after 8R touch (4-tick buffer, trails swing highs/lows)
- 3rd contract (Runner): Opposing FVG or +4R trailing stop
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


def calculate_adx(bars, period=14):
    """Calculate ADX (Average Directional Index) and DI values for trend strength/direction.

    Returns: (adx, plus_di, minus_di) or (None, None, None) if not enough data

    ADX > 25 = strong trend
    ADX 17-25 = developing trend
    ADX < 17 = weak/no trend (choppy market)

    +DI > -DI = bullish trend direction
    -DI > +DI = bearish trend direction
    """
    if len(bars) < period * 2:
        return None, None, None

    # Calculate True Range, +DM, -DM
    tr_list = []
    plus_dm_list = []
    minus_dm_list = []

    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        close_prev = bars[i-1].close
        high_prev = bars[i-1].high
        low_prev = bars[i-1].low

        # True Range
        tr = max(high - low, abs(high - close_prev), abs(low - close_prev))
        tr_list.append(tr)

        # Directional Movement
        up_move = high - high_prev
        down_move = low_prev - low

        plus_dm = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0

        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)

    if len(tr_list) < period:
        return None, None, None

    # Smoothed averages (Wilder's smoothing)
    def wilder_smooth(data, period):
        smoothed = [sum(data[:period])]
        for i in range(period, len(data)):
            smoothed.append(smoothed[-1] - (smoothed[-1] / period) + data[i])
        return smoothed

    atr = wilder_smooth(tr_list, period)
    plus_dm_smooth = wilder_smooth(plus_dm_list, period)
    minus_dm_smooth = wilder_smooth(minus_dm_list, period)

    # Calculate +DI and -DI
    dx_list = []
    plus_di = 0
    minus_di = 0
    for i in range(len(atr)):
        if atr[i] == 0:
            continue
        plus_di = 100 * plus_dm_smooth[i] / atr[i]
        minus_di = 100 * minus_dm_smooth[i] / atr[i]

        di_sum = plus_di + minus_di
        if di_sum == 0:
            continue
        dx = 100 * abs(plus_di - minus_di) / di_sum
        dx_list.append(dx)

    if len(dx_list) < period:
        return None, None, None

    # ADX is smoothed DX
    adx = sum(dx_list[-period:]) / period
    return adx, plus_di, minus_di


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


def is_swing_high(bars, idx, lookback=2):
    """Check if bar at idx is a swing high (higher than neighbors)."""
    if idx < lookback or idx >= len(bars) - lookback:
        return False
    bar_high = bars[idx].high
    for i in range(1, lookback + 1):
        if bar_high <= bars[idx - i].high or bar_high <= bars[idx + i].high:
            return False
    return True


def is_swing_low(bars, idx, lookback=2):
    """Check if bar at idx is a swing low (lower than neighbors)."""
    if idx < lookback or idx >= len(bars) - lookback:
        return False
    bar_low = bars[idx].low
    for i in range(1, lookback + 1):
        if bar_low >= bars[idx - i].low or bar_low >= bars[idx + i].low:
            return False
    return True


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
    min_fvg_ticks=5,
    displacement_threshold=1.0,  # V6-Aggressive: lower threshold
    require_displacement=True,
    require_killzone=False,
    require_htf_bias=True,
    require_adx=True,
    min_adx=17,
    enter_at_creation=True,  # V6-Aggressive: enter at FVG creation, not retracement
):
    """Run trade with ICT FVG Strategy (V6-Aggressive)."""
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'
    opposing_fvg_dir = 'BEARISH' if is_long else 'BULLISH'

    # Calculate average body size for displacement detection
    body_sizes = [abs(b.close - b.open) for b in session_bars[:50]]
    avg_body_size = sum(body_sizes) / len(body_sizes) if body_sizes else tick_size * 4

    # EMA bias check moved to entry time (see below)

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

        # V6-Aggressive: Enter at FVG creation (no waiting for retracement)
        if enter_at_creation:
            entry_idx = fvg.created_bar_index
            entry_bar = session_bars[entry_idx]

            # Killzone filter
            if require_killzone and not is_in_killzone(entry_bar.timestamp):
                continue

            # HTF Bias filter at FVG creation time
            if require_htf_bias:
                bars_to_entry = session_bars[:entry_idx+1]
                ema_fast = calculate_ema(bars_to_entry, 20)
                ema_slow = calculate_ema(bars_to_entry, 50)
                if ema_fast is not None and ema_slow is not None:
                    if is_long and ema_fast < ema_slow:
                        continue  # Skip, wrong bias
                    if not is_long and ema_fast > ema_slow:
                        continue  # Skip, wrong bias

            # ADX filter at FVG creation time
            if require_adx:
                bars_to_entry = session_bars[:entry_idx+1]
                adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)
                if adx is not None:
                    if adx < min_adx:
                        continue  # Skip, market not trending
                    if is_long and plus_di <= minus_di:
                        continue  # Skip LONG, bearish DI
                    if not is_long and minus_di <= plus_di:
                        continue  # Skip SHORT, bullish DI

            # Valid entry at creation
            valid_fvg_count += 1
            if valid_fvg_count == fvg_num:
                entry_fvg = fvg
                # Enter at midpoint price at creation time (all contracts)
                edge_entry_bar_idx = entry_idx
                edge_entry_time = entry_bar.timestamp
                midpoint_entry_bar_idx = entry_idx
                midpoint_entry_time = entry_bar.timestamp
                break
        else:
            # Original V5 logic: wait for price to retrace to FVG
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
                        # HTF Bias filter at entry time (not end of session)
                        # If not enough bars for EMA, allow trade (early session)
                        if require_htf_bias:
                            bars_to_entry = session_bars[:i+1]
                            ema_fast = calculate_ema(bars_to_entry, 20)
                            ema_slow = calculate_ema(bars_to_entry, 50)
                            if ema_fast is not None and ema_slow is not None:
                                if is_long and ema_fast < ema_slow:
                                    continue  # Skip this entry, wrong bias
                                if not is_long and ema_fast > ema_slow:
                                    continue  # Skip this entry, wrong bias

                        # ADX filter - only trade in trending markets
                        # Also check DI direction: LONG only if +DI > -DI, SHORT only if -DI > +DI
                        if require_adx:
                            bars_to_entry = session_bars[:i+1]
                            adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)
                            if adx is not None:
                                if adx < min_adx:
                                    continue  # Skip this entry, market not trending
                                # DI direction filter
                                if is_long and plus_di <= minus_di:
                                    continue  # Skip LONG, bearish DI direction
                                if not is_long and minus_di <= plus_di:
                                    continue  # Skip SHORT, bullish DI direction

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
    t1_touched = False  # 4R level touched, fast structure trail active
    t2_touched = False  # 8R level touched, standard structure trail active

    # Runner stop - starts at buffered stop, moves to +4R after 8R hits
    runner_stop = stop_price
    runner_stop_type = 'STOP'

    # T1 fast structure trail (active after 4R touched) - tighter buffer
    t1_trail_stop = stop_price  # Start at entry stop, moves to BE after 4R
    last_swing_t1 = avg_entry
    t1_buffer_ticks = 2  # Tighter buffer for faster exit

    # T2 standard structure trail (active after 8R touched)
    t2_trail_stop = plus_4r  # Start at +4R
    last_swing_t2 = avg_entry
    t2_buffer_ticks = 4  # Standard buffer

    # Reset FVG mitigation for trade simulation
    entry_fvg.mitigated = False
    entry_fvg.mitigation_bar_index = None

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]

        # Check stop (using buffered stop) - only before T1 and T2 are secured
        if (not exited_t1 and not t1_touched) or (not exited_t2 and not t2_touched):
            if is_long:
                stop_hit = bar.low <= stop_price
            else:
                stop_hit = bar.high >= stop_price

            if stop_hit:
                pnl = (stop_price - avg_entry) * remaining if is_long else (avg_entry - stop_price) * remaining
                exits.append({'type': 'STOP', 'pnl': pnl, 'price': stop_price, 'time': bar.timestamp, 'cts': remaining})
                remaining = 0
                break

        # Check T1 fast structure trail (after 4R touched, before T1 exited)
        if t1_touched and not exited_t1:
            # Update fast trail based on confirmed swing points (2-tick buffer)
            check_idx = i - 2
            if check_idx > entry_bar_idx:
                if is_long:
                    if is_swing_low(session_bars, check_idx, lookback=2):
                        swing_low = session_bars[check_idx].low
                        if swing_low > last_swing_t1:
                            new_trail = swing_low - (t1_buffer_ticks * tick_size)
                            if new_trail > t1_trail_stop:
                                t1_trail_stop = new_trail
                                last_swing_t1 = swing_low
                else:
                    if is_swing_high(session_bars, check_idx, lookback=2):
                        swing_high = session_bars[check_idx].high
                        if swing_high < last_swing_t1:
                            new_trail = swing_high + (t1_buffer_ticks * tick_size)
                            if new_trail < t1_trail_stop:
                                t1_trail_stop = new_trail
                                last_swing_t1 = swing_high

            # Check if T1 trail stop hit
            if is_long:
                if bar.low <= t1_trail_stop:
                    exit_cts = min(cts_t1, remaining)
                    pnl = (t1_trail_stop - avg_entry) * exit_cts
                    exits.append({'type': 'T1_STRUCT', 'pnl': pnl, 'price': t1_trail_stop, 'time': bar.timestamp, 'cts': exit_cts})
                    remaining -= exit_cts
                    exited_t1 = True
            else:
                if bar.high >= t1_trail_stop:
                    exit_cts = min(cts_t1, remaining)
                    pnl = (avg_entry - t1_trail_stop) * exit_cts
                    exits.append({'type': 'T1_STRUCT', 'pnl': pnl, 'price': t1_trail_stop, 'time': bar.timestamp, 'cts': exit_cts})
                    remaining -= exit_cts
                    exited_t1 = True

        # Check T2 structure trail stop (after 8R touched, before T2 exited)
        if t2_touched and not exited_t2 and remaining > cts_runner:
            # Update structure trail based on confirmed swing points
            # Need 2 bars after swing to confirm (lookback=2)
            check_idx = i - 2
            if check_idx > entry_bar_idx:
                if is_long:
                    # Trail above swing lows for long
                    if is_swing_low(session_bars, check_idx, lookback=2):
                        swing_low = session_bars[check_idx].low
                        if swing_low > last_swing_t2:  # Higher swing low (good for long)
                            new_trail = swing_low - (t2_buffer_ticks * tick_size)
                            if new_trail > t2_trail_stop:
                                t2_trail_stop = new_trail
                                last_swing_t2 = swing_low
                else:
                    # Trail below swing highs for short
                    if is_swing_high(session_bars, check_idx, lookback=2):
                        swing_high = session_bars[check_idx].high
                        if swing_high < last_swing_t2:  # Lower swing high (good for short)
                            new_trail = swing_high + (t2_buffer_ticks * tick_size)
                            if new_trail < t2_trail_stop:
                                t2_trail_stop = new_trail
                                last_swing_t2 = swing_high

            # Check if T2 trail stop hit
            if is_long:
                if bar.low <= t2_trail_stop:
                    exit_cts = min(cts_t2, remaining - cts_runner)
                    pnl = (t2_trail_stop - avg_entry) * exit_cts
                    exits.append({'type': 'T2_STRUCT', 'pnl': pnl, 'price': t2_trail_stop, 'time': bar.timestamp, 'cts': exit_cts})
                    remaining -= exit_cts
                    exited_t2 = True
            else:
                if bar.high >= t2_trail_stop:
                    exit_cts = min(cts_t2, remaining - cts_runner)
                    pnl = (avg_entry - t2_trail_stop) * exit_cts
                    exits.append({'type': 'T2_STRUCT', 'pnl': pnl, 'price': t2_trail_stop, 'time': bar.timestamp, 'cts': exit_cts})
                    remaining -= exit_cts
                    exited_t2 = True

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

        # Check 4R touch (activates fast structure trail for T1)
        if cts_t1 > 0 and not t1_touched and not exited_t1:
            t1_hit = bar.high >= target_t1 if is_long else bar.low <= target_t1
            if t1_hit:
                t1_touched = True
                # Move T1 trail stop to breakeven after 4R touched
                t1_trail_stop = avg_entry

        # Check 8R touch (activates structure trail, doesn't exit)
        if cts_t2 > 0 and not t2_touched and remaining > cts_runner:
            t2_hit = bar.high >= target_t2 if is_long else bar.low <= target_t2
            if t2_hit:
                t2_touched = True
                # Move runner stop to +4R after 8R touched
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


def run_multi_trade(
    session_bars,
    direction,
    tick_size=0.25,
    tick_value=12.50,
    contracts=3,
    target1_r=4,
    target2_r=8,
    stop_buffer_ticks=2,
    min_fvg_ticks=5,
    displacement_threshold=1.0,
    min_adx=17,
    reentry_r_threshold=2,  # Take 2nd entry when 1st is at +2R (only if independent_entries=False)
    lockin_r=1,  # Move 1st trade stop to +1R when 2nd entry triggers
    independent_entries=True,  # V8: Take 2nd entry independently (don't require 1st at +2R)
):
    """Run multi-entry trade with independent or profit-protected re-entry.

    If independent_entries=True (V8-Independent):
    - Take 2nd entry when new valid FVG forms (regardless of 1st trade status)
    - If 1st trade still active and profitable, lock stop to +1R

    If independent_entries=False (V7-MultiEntry):
    - Only take 2nd entry when 1st trade is at +2R AND still active
    - Move 1st trade stop to +1R when 2nd entry triggers
    """
    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'
    opposing_fvg_dir = 'BEARISH' if is_long else 'BULLISH'

    body_sizes = [abs(b.close - b.open) for b in session_bars[:50]]
    avg_body_size = sum(body_sizes) / len(body_sizes) if body_sizes else tick_size * 4

    fvg_config = {
        'min_fvg_ticks': min_fvg_ticks,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)

    # Find all valid FVG entries (pass displacement + filters at creation time)
    valid_entries = []
    for fvg in all_fvgs:
        if fvg.direction != fvg_dir:
            continue

        creating_bar = session_bars[fvg.created_bar_index]
        body = abs(creating_bar.close - creating_bar.open)
        if body <= avg_body_size * displacement_threshold:
            continue

        bars_to_entry = session_bars[:fvg.created_bar_index + 1]
        ema_fast = calculate_ema(bars_to_entry, 20)
        ema_slow = calculate_ema(bars_to_entry, 50)
        adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)

        ema_ok = ema_fast is None or ema_slow is None or (ema_fast > ema_slow if is_long else ema_fast < ema_slow)
        adx_ok = adx is None or adx >= min_adx
        di_ok = adx is None or (plus_di > minus_di if is_long else minus_di > plus_di)

        if ema_ok and adx_ok and di_ok:
            valid_entries.append({
                'fvg': fvg,
                'entry_bar_idx': fvg.created_bar_index,
                'entry_time': creating_bar.timestamp,
                'midpoint': fvg.midpoint,
                'stop': fvg.low - (stop_buffer_ticks * tick_size) if is_long else fvg.high + (stop_buffer_ticks * tick_size),
                'fvg_low': fvg.low,
                'fvg_high': fvg.high,
            })

    if not valid_entries:
        return []

    results = []

    # Trade 1: First valid entry
    t1 = valid_entries[0]
    t1_entry = t1['midpoint']
    t1_stop = t1['stop']
    t1_original_stop = t1_stop
    t1_risk = abs(t1_entry - t1_stop)
    t1_target_2r = t1_entry + (reentry_r_threshold * t1_risk) if is_long else t1_entry - (reentry_r_threshold * t1_risk)
    t1_target_4r = t1_entry + (target1_r * t1_risk) if is_long else t1_entry - (target1_r * t1_risk)
    t1_target_8r = t1_entry + (target2_r * t1_risk) if is_long else t1_entry - (target2_r * t1_risk)
    t1_plus_4r = t1_target_4r
    t1_lockin_price = t1_entry + (lockin_r * t1_risk) if is_long else t1_entry - (lockin_r * t1_risk)

    t1_remaining = contracts
    t1_exits = []
    t1_active = True
    t1_touched_4r = False
    t1_touched_8r = False
    t1_exited_t1 = False
    t1_exited_t2 = False
    t1_runner_stop = t1_stop
    t1_trail_stop = t1_stop
    t1_last_swing = t1_entry
    t1_stop_locked = False  # Track if stop was moved to +1R

    cts_t1 = contracts // 3 or 1
    cts_t2 = contracts // 3 or 1
    cts_runner = contracts - cts_t1 - cts_t2 or 1

    # Trade 2 state
    t2_entry = None
    t2_stop = None
    t2_risk = None
    t2_remaining = 0
    t2_exits = []
    t2_active = False
    t2_touched_4r = False
    t2_touched_8r = False
    t2_exited_t1 = False
    t2_exited_t2 = False
    t2_runner_stop = None
    t2_trail_stop = None
    t2_last_swing = None
    t2_entry_info = None
    t2_target_4r = None
    t2_target_8r = None
    t2_plus_4r = None

    # Track if 2nd entry was taken
    took_2nd_entry = False

    # Simulate bar by bar
    for i in range(t1['entry_bar_idx'] + 1, len(session_bars)):
        bar = session_bars[i]

        # === TRADE 1 MANAGEMENT ===
        if t1_active and t1_remaining > 0:
            current_price = bar.high if is_long else bar.low
            current_pnl_r = (current_price - t1_entry) / t1_risk if is_long else (t1_entry - current_price) / t1_risk

            # Check for 2nd entry opportunity
            # V8-Independent: Take when new FVG forms (regardless of 1st trade P/L)
            # V7-MultiEntry: Only when 1st trade at +2R
            can_take_2nd = not took_2nd_entry
            if not independent_entries:
                can_take_2nd = can_take_2nd and current_pnl_r >= reentry_r_threshold

            if can_take_2nd:
                # Look for a new valid FVG that formed after trade 1
                for entry in valid_entries[1:]:
                    if entry['entry_bar_idx'] <= i and entry['entry_bar_idx'] > t1['entry_bar_idx']:
                        # Found valid 2nd entry - take it!
                        t2_entry_info = entry
                        t2_entry = entry['midpoint']
                        t2_stop = entry['stop']
                        t2_risk = abs(t2_entry - t2_stop)
                        t2_remaining = contracts
                        t2_active = True
                        t2_target_4r = t2_entry + (target1_r * t2_risk) if is_long else t2_entry - (target1_r * t2_risk)
                        t2_target_8r = t2_entry + (target2_r * t2_risk) if is_long else t2_entry - (target2_r * t2_risk)
                        t2_plus_4r = t2_target_4r
                        t2_runner_stop = t2_stop
                        t2_trail_stop = t2_stop
                        t2_last_swing = t2_entry

                        # LOCK IN +1R on Trade 1
                        t1_stop = t1_lockin_price
                        t1_trail_stop = max(t1_trail_stop, t1_lockin_price) if is_long else min(t1_trail_stop, t1_lockin_price)
                        t1_runner_stop = max(t1_runner_stop, t1_lockin_price) if is_long else min(t1_runner_stop, t1_lockin_price)
                        t1_stop_locked = True

                        took_2nd_entry = True
                        break

            # Check 4R touch (T1 exit zone) - check BEFORE stop logic
            if t1_remaining > 0 and not t1_touched_4r:
                t1_hit = bar.high >= t1_target_4r if is_long else bar.low <= t1_target_4r
                if t1_hit:
                    t1_touched_4r = True
                    t1_trail_stop = t1_entry  # Move trail to BE after 4R

            # Update structure trail after 4R touched
            if t1_touched_4r and t1_remaining > 0:
                check_idx = i - 2
                if check_idx > t1['entry_bar_idx']:
                    if is_long and is_swing_low(session_bars, check_idx, lookback=2):
                        swing = session_bars[check_idx].low
                        if swing > t1_last_swing:
                            new_trail = swing - (2 * tick_size)
                            if new_trail > t1_trail_stop:
                                t1_trail_stop = new_trail
                                t1_last_swing = swing
                    elif not is_long and is_swing_high(session_bars, check_idx, lookback=2):
                        swing = session_bars[check_idx].high
                        if swing < t1_last_swing:
                            new_trail = swing + (2 * tick_size)
                            if new_trail < t1_trail_stop:
                                t1_trail_stop = new_trail
                                t1_last_swing = swing

            # Determine current stop level (use trail_stop if 4R touched, else original stop)
            current_stop = t1_trail_stop if t1_touched_4r else t1_stop

            # After 8R touched, runner uses +4R stop
            if t1_touched_8r and t1_exited_t1 and t1_exited_t2:
                current_stop = t1_runner_stop

            # Check stop/trail hit for ALL remaining contracts
            stop_hit = bar.low <= current_stop if is_long else bar.high >= current_stop
            if stop_hit and t1_remaining > 0:
                pnl = (current_stop - t1_entry) * t1_remaining if is_long else (t1_entry - current_stop) * t1_remaining
                if t1_touched_4r:
                    if t1_exited_t1 and t1_exited_t2:
                        exit_type = 'RUNNER_STOP' if t1_touched_8r else 'TRAIL_STOP'
                    elif t1_exited_t1:
                        exit_type = 'T2_TRAIL'
                    else:
                        exit_type = 'T1_STRUCT'
                else:
                    exit_type = 'STOP_+1R' if t1_stop_locked else 'STOP'
                t1_exits.append({'type': exit_type, 'pnl': pnl, 'price': current_stop, 'time': bar.timestamp, 'cts': t1_remaining})
                t1_remaining = 0
                t1_active = False
                continue  # Move to next bar

            # Exit T1 contract via structure trail (1 contract) after 4R
            if t1_touched_4r and not t1_exited_t1 and t1_remaining > 0:
                trail_hit = bar.low <= t1_trail_stop if is_long else bar.high >= t1_trail_stop
                if trail_hit:
                    exit_cts = min(cts_t1, t1_remaining)
                    pnl = (t1_trail_stop - t1_entry) * exit_cts if is_long else (t1_entry - t1_trail_stop) * exit_cts
                    t1_exits.append({'type': 'T1_STRUCT', 'pnl': pnl, 'price': t1_trail_stop, 'time': bar.timestamp, 'cts': exit_cts})
                    t1_remaining -= exit_cts
                    t1_exited_t1 = True

            # Check 8R touch
            if t1_remaining > 0 and not t1_touched_8r:
                t2_hit = bar.high >= t1_target_8r if is_long else bar.low <= t1_target_8r
                if t2_hit:
                    t1_touched_8r = True
                    t1_runner_stop = t1_plus_4r

            # T2 structure trail after 8R touched
            if t1_touched_8r and not t1_exited_t2 and t1_remaining > cts_runner:
                trail_hit = bar.low <= t1_runner_stop if is_long else bar.high >= t1_runner_stop
                if trail_hit:
                    exit_cts = min(cts_t2, t1_remaining - cts_runner)
                    pnl = (t1_runner_stop - t1_entry) * exit_cts if is_long else (t1_entry - t1_runner_stop) * exit_cts
                    t1_exits.append({'type': 'T2_STRUCT', 'pnl': pnl, 'price': t1_runner_stop, 'time': bar.timestamp, 'cts': exit_cts})
                    t1_remaining -= exit_cts
                    t1_exited_t2 = True

            # Runner exit (opposing FVG)
            if t1_remaining > 0 and t1_remaining <= cts_runner and t1_exited_t1:
                opp_fvgs = [f for f in all_fvgs if f.direction == opposing_fvg_dir and f.created_bar_index > t1['entry_bar_idx'] and f.created_bar_index <= i]
                if opp_fvgs:
                    pnl = (bar.close - t1_entry) * t1_remaining if is_long else (t1_entry - bar.close) * t1_remaining
                    t1_exits.append({'type': 'OPP_FVG', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': t1_remaining})
                    t1_remaining = 0

        # === CHECK FOR 2ND ENTRY (V8-Independent: even after 1st trade exits) ===
        if independent_entries and not took_2nd_entry and not t2_active:
            # Look for a new valid FVG that formed and we've reached that bar
            for entry in valid_entries[1:]:
                if entry['entry_bar_idx'] == i:  # FVG just formed on this bar
                    # Take 2nd entry!
                    t2_entry_info = entry
                    t2_entry = entry['midpoint']
                    t2_stop = entry['stop']
                    t2_risk = abs(t2_entry - t2_stop)
                    t2_remaining = contracts
                    t2_active = True
                    t2_target_4r = t2_entry + (target1_r * t2_risk) if is_long else t2_entry - (target1_r * t2_risk)
                    t2_target_8r = t2_entry + (target2_r * t2_risk) if is_long else t2_entry - (target2_r * t2_risk)
                    t2_plus_4r = t2_target_4r
                    t2_runner_stop = t2_stop
                    t2_trail_stop = t2_stop
                    t2_last_swing = t2_entry

                    # If 1st trade still active and profitable, lock in +1R
                    if t1_active and t1_remaining > 0:
                        current_pnl = (bar.close - t1_entry) if is_long else (t1_entry - bar.close)
                        if current_pnl >= lockin_r * t1_risk:
                            t1_stop = t1_lockin_price
                            t1_trail_stop = max(t1_trail_stop, t1_lockin_price) if is_long else min(t1_trail_stop, t1_lockin_price)
                            t1_runner_stop = max(t1_runner_stop, t1_lockin_price) if is_long else min(t1_runner_stop, t1_lockin_price)
                            t1_stop_locked = True

                    took_2nd_entry = True
                    break

        # === TRADE 2 MANAGEMENT ===
        if t2_active and t2_remaining > 0:
            # Check 4R touch first
            if t2_remaining > 0 and not t2_touched_4r:
                t2_4r_hit = bar.high >= t2_target_4r if is_long else bar.low <= t2_target_4r
                if t2_4r_hit:
                    t2_touched_4r = True
                    t2_trail_stop = t2_entry  # Move to BE

            # Update structure trail after 4R
            if t2_touched_4r and t2_remaining > 0:
                check_idx = i - 2
                if check_idx > t2_entry_info['entry_bar_idx']:
                    if is_long and is_swing_low(session_bars, check_idx, lookback=2):
                        swing = session_bars[check_idx].low
                        if swing > t2_last_swing:
                            new_trail = swing - (2 * tick_size)
                            if new_trail > t2_trail_stop:
                                t2_trail_stop = new_trail
                                t2_last_swing = swing
                    elif not is_long and is_swing_high(session_bars, check_idx, lookback=2):
                        swing = session_bars[check_idx].high
                        if swing < t2_last_swing:
                            new_trail = swing + (2 * tick_size)
                            if new_trail < t2_trail_stop:
                                t2_trail_stop = new_trail
                                t2_last_swing = swing

            # Determine current stop for Trade 2
            t2_current_stop = t2_trail_stop if t2_touched_4r else t2_stop
            if t2_touched_8r and t2_exited_t1 and t2_exited_t2:
                t2_current_stop = t2_runner_stop

            # Check stop/trail hit for Trade 2
            stop_hit = bar.low <= t2_current_stop if is_long else bar.high >= t2_current_stop
            if stop_hit and t2_remaining > 0:
                pnl = (t2_current_stop - t2_entry) * t2_remaining if is_long else (t2_entry - t2_current_stop) * t2_remaining
                if t2_touched_4r:
                    exit_type = 'RUNNER_STOP' if t2_touched_8r and t2_exited_t1 and t2_exited_t2 else 'TRAIL_STOP'
                else:
                    exit_type = 'STOP'
                t2_exits.append({'type': exit_type, 'pnl': pnl, 'price': t2_current_stop, 'time': bar.timestamp, 'cts': t2_remaining})
                t2_remaining = 0
                t2_active = False
                continue

            # Exit T1 contract via structure trail after 4R
            if t2_touched_4r and not t2_exited_t1 and t2_remaining > 0:
                trail_hit = bar.low <= t2_trail_stop if is_long else bar.high >= t2_trail_stop
                if trail_hit:
                    exit_cts = min(cts_t1, t2_remaining)
                    pnl = (t2_trail_stop - t2_entry) * exit_cts if is_long else (t2_entry - t2_trail_stop) * exit_cts
                    t2_exits.append({'type': 'T1_STRUCT', 'pnl': pnl, 'price': t2_trail_stop, 'time': bar.timestamp, 'cts': exit_cts})
                    t2_remaining -= exit_cts
                    t2_exited_t1 = True

            # Check 8R touch
            if t2_remaining > 0 and not t2_touched_8r:
                t2_8r_hit = bar.high >= t2_target_8r if is_long else bar.low <= t2_target_8r
                if t2_8r_hit:
                    t2_touched_8r = True
                    t2_runner_stop = t2_plus_4r

            # T2 exit after 8R
            if t2_touched_8r and not t2_exited_t2 and t2_remaining > cts_runner:
                trail_hit = bar.low <= t2_runner_stop if is_long else bar.high >= t2_runner_stop
                if trail_hit:
                    exit_cts = min(cts_t2, t2_remaining - cts_runner)
                    pnl = (t2_runner_stop - t2_entry) * exit_cts if is_long else (t2_entry - t2_runner_stop) * exit_cts
                    t2_exits.append({'type': 'T2_STRUCT', 'pnl': pnl, 'price': t2_runner_stop, 'time': bar.timestamp, 'cts': exit_cts})
                    t2_remaining -= exit_cts
                    t2_exited_t2 = True

            # Runner exit
            if t2_remaining > 0 and t2_remaining <= cts_runner and t2_exited_t1:
                opp_fvgs = [f for f in all_fvgs if f.direction == opposing_fvg_dir and f.created_bar_index > t2_entry_info['entry_bar_idx'] and f.created_bar_index <= i]
                if opp_fvgs:
                    pnl = (bar.close - t2_entry) * t2_remaining if is_long else (t2_entry - bar.close) * t2_remaining
                    t2_exits.append({'type': 'OPP_FVG', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': t2_remaining})
                    t2_remaining = 0

    # End of day exits
    last_bar = session_bars[-1]
    if t1_remaining > 0:
        pnl = (last_bar.close - t1_entry) * t1_remaining if is_long else (t1_entry - last_bar.close) * t1_remaining
        t1_exits.append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'cts': t1_remaining})
    if t2_remaining > 0:
        pnl = (last_bar.close - t2_entry) * t2_remaining if is_long else (t2_entry - last_bar.close) * t2_remaining
        t2_exits.append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'cts': t2_remaining})

    # Build Trade 1 result
    t1_total_pnl = sum(e['pnl'] for e in t1_exits)
    t1_total_dollars = (t1_total_pnl / tick_size) * tick_value
    results.append({
        'direction': direction,
        'entry_time': t1['entry_time'],
        'entry_price': t1_entry,
        'edge_price': t1['fvg_high'] if is_long else t1['fvg_low'],
        'midpoint_price': t1['midpoint'],
        'contracts_filled': contracts,
        'fill_type': 'FULL',
        'stop_price': t1_original_stop,
        'stop_locked_to': t1_lockin_price if t1_stop_locked else None,
        'runner_stop': t1_runner_stop,
        'fvg_low': t1['fvg_low'],
        'fvg_high': t1['fvg_high'],
        'target_4r': t1_target_4r,
        'target_8r': t1_target_8r,
        'plus_4r': t1_plus_4r,
        'risk': t1_risk,
        'total_pnl': t1_total_pnl,
        'total_dollars': t1_total_dollars,
        'was_stopped': any(e['type'] in ['STOP', 'STOP_+1R'] for e in t1_exits),
        'exits': t1_exits,
    })

    # Build Trade 2 result if taken
    if took_2nd_entry and t2_exits:
        t2_total_pnl = sum(e['pnl'] for e in t2_exits)
        t2_total_dollars = (t2_total_pnl / tick_size) * tick_value
        results.append({
            'direction': direction,
            'entry_time': t2_entry_info['entry_time'],
            'entry_price': t2_entry,
            'edge_price': t2_entry_info['fvg_high'] if is_long else t2_entry_info['fvg_low'],
            'midpoint_price': t2_entry_info['midpoint'],
            'contracts_filled': contracts,
            'fill_type': 'FULL',
            'stop_price': t2_entry_info['stop'],
            'runner_stop': t2_runner_stop,
            'fvg_low': t2_entry_info['fvg_low'],
            'fvg_high': t2_entry_info['fvg_high'],
            'target_4r': t2_target_4r,
            'target_8r': t2_target_8r,
            'plus_4r': t2_plus_4r,
            'risk': t2_risk,
            'total_pnl': t2_total_pnl,
            'total_dollars': t2_total_dollars,
            'was_stopped': any(e['type'] == 'STOP' for e in t2_exits),
            'exits': t2_exits,
            'is_reentry': True,
            'profit_protected': True,
        })

    return results


def run_session_with_position_limit(
    session_bars,
    tick_size=0.25,
    tick_value=12.50,
    contracts=3,
    max_open_trades=2,
    max_losses_per_day=2,
    displacement_threshold=1.0,
    min_adx=17,
    min_risk_pts=0,  # Minimum risk in points (0 = disabled)
    use_opposing_fvg_exit=False,  # Exit runner on opposing FVG
):
    """Run session with combined position limit across LONG and SHORT.

    Tiered Structure Trail exit strategy:
    - At 4R touch: Activate fast structure trail for 1st contract (2-tick buffer)
    - At 8R touch: Activate standard structure trail for 2nd contract (4-tick buffer)
    - Runner (3rd contract): +4R trailing stop OR opposing FVG exit

    Args:
        max_open_trades: Maximum concurrent open positions (LONG + SHORT combined)
        max_losses_per_day: Stop trading after this many losses
        min_risk_pts: Minimum risk in points to take a trade (filters small FVGs)
        use_opposing_fvg_exit: If True, runner exits on opposing FVG formation
    """

    # Find all valid FVG entries for both directions
    body_sizes = [abs(b.close - b.open) for b in session_bars[:50]]
    avg_body_size = sum(body_sizes) / len(body_sizes) if body_sizes else tick_size * 4

    fvg_config = {
        'min_fvg_ticks': 5,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)

    # Find valid entries for each direction
    valid_entries = {'LONG': [], 'SHORT': []}

    for direction in ['LONG', 'SHORT']:
        is_long = direction == 'LONG'
        fvg_dir = 'BULLISH' if is_long else 'BEARISH'

        for fvg in all_fvgs:
            if fvg.direction != fvg_dir:
                continue

            creating_bar = session_bars[fvg.created_bar_index]
            body = abs(creating_bar.close - creating_bar.open)
            if body <= avg_body_size * displacement_threshold:
                continue

            bars_to_entry = session_bars[:fvg.created_bar_index + 1]
            ema_fast = calculate_ema(bars_to_entry, 20)
            ema_slow = calculate_ema(bars_to_entry, 50)
            adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)

            ema_ok = ema_fast is None or ema_slow is None or (ema_fast > ema_slow if is_long else ema_fast < ema_slow)
            adx_ok = adx is None or adx >= min_adx
            di_ok = adx is None or (plus_di > minus_di if is_long else minus_di > plus_di)

            if ema_ok and adx_ok and di_ok:
                stop_buffer_ticks = 2
                entry_price = fvg.midpoint
                stop_price = fvg.low - (stop_buffer_ticks * tick_size) if is_long else fvg.high + (stop_buffer_ticks * tick_size)
                risk = abs(entry_price - stop_price)

                # Skip if risk is below minimum threshold
                if min_risk_pts > 0 and risk < min_risk_pts:
                    continue

                valid_entries[direction].append({
                    'fvg': fvg,
                    'direction': direction,
                    'entry_bar_idx': fvg.created_bar_index,
                    'entry_time': creating_bar.timestamp,
                    'midpoint': entry_price,
                    'stop': stop_price,
                    'fvg_low': fvg.low,
                    'fvg_high': fvg.high,
                })

    # Combine and sort all entries by bar index
    all_valid_entries = valid_entries['LONG'] + valid_entries['SHORT']
    all_valid_entries.sort(key=lambda x: x['entry_bar_idx'])

    # Track active trades and results
    active_trades = []  # List of active trade states
    completed_results = []
    entries_taken = {'LONG': 0, 'SHORT': 0}
    loss_count = 0

    # Contract allocation for tiered exits
    cts_t1 = 1  # 1st contract: fast structure trail after 4R
    cts_t2 = 1  # 2nd contract: standard structure trail after 8R
    cts_runner = contracts - cts_t1 - cts_t2  # Runner: +4R trail after 8R

    # Process bar by bar
    for i in range(len(session_bars)):
        bar = session_bars[i]

        # Check for stop/exit on active trades
        trades_to_remove = []
        for trade in active_trades:
            is_long = trade['direction'] == 'LONG'
            remaining = trade['remaining']

            if remaining <= 0:
                trades_to_remove.append(trade)
                continue

            # Update T1 fast structure trail (2-tick buffer) after 4R touched
            if trade['touched_4r'] and not trade['t1_exited']:
                check_idx = i - 2
                if check_idx > trade['entry_bar_idx']:
                    if is_long and is_swing_low(session_bars, check_idx, lookback=2):
                        swing = session_bars[check_idx].low
                        if swing > trade['t1_last_swing']:
                            new_trail = swing - (2 * tick_size)  # 2-tick buffer (fast)
                            if new_trail > trade['t1_trail_stop']:
                                trade['t1_trail_stop'] = new_trail
                                trade['t1_last_swing'] = swing
                    elif not is_long and is_swing_high(session_bars, check_idx, lookback=2):
                        swing = session_bars[check_idx].high
                        if swing < trade['t1_last_swing']:
                            new_trail = swing + (2 * tick_size)
                            if new_trail < trade['t1_trail_stop']:
                                trade['t1_trail_stop'] = new_trail
                                trade['t1_last_swing'] = swing

            # Update T2 standard structure trail (4-tick buffer) after 8R touched
            if trade['touched_8r'] and not trade['t2_exited']:
                check_idx = i - 2
                if check_idx > trade['entry_bar_idx']:
                    if is_long and is_swing_low(session_bars, check_idx, lookback=2):
                        swing = session_bars[check_idx].low
                        if swing > trade['t2_last_swing']:
                            new_trail = swing - (4 * tick_size)  # 4-tick buffer (standard)
                            if new_trail > trade['t2_trail_stop']:
                                trade['t2_trail_stop'] = new_trail
                                trade['t2_last_swing'] = swing
                    elif not is_long and is_swing_high(session_bars, check_idx, lookback=2):
                        swing = session_bars[check_idx].high
                        if swing < trade['t2_last_swing']:
                            new_trail = swing + (4 * tick_size)
                            if new_trail < trade['t2_trail_stop']:
                                trade['t2_trail_stop'] = new_trail
                                trade['t2_last_swing'] = swing

            # Check 4R touch (activates T1 fast structure trail)
            if not trade['touched_4r']:
                t4r_hit = bar.high >= trade['target_4r'] if is_long else bar.low <= trade['target_4r']
                if t4r_hit:
                    trade['touched_4r'] = True
                    trade['t1_trail_stop'] = trade['entry_price']  # Start at BE
                    trade['t1_last_swing'] = trade['entry_price']

            # Check 8R touch (activates T2 structure trail and runner +4R stop)
            if trade['touched_4r'] and not trade['touched_8r']:
                t8r_hit = bar.high >= trade['target_8r'] if is_long else bar.low <= trade['target_8r']
                if t8r_hit:
                    trade['touched_8r'] = True
                    trade['t2_trail_stop'] = trade['plus_4r']  # Start at +4R
                    trade['t2_last_swing'] = bar.high if is_long else bar.low
                    trade['runner_stop'] = trade['plus_4r']

            # Determine current stop based on trade state
            if not trade['touched_4r']:
                current_stop = trade['stop_price']
            elif not trade['touched_8r']:
                current_stop = trade['t1_trail_stop']
            else:
                # After 8R, use the tightest applicable stop
                current_stop = trade['t1_trail_stop'] if not trade['t1_exited'] else trade['t2_trail_stop']

            # Check original stop (before 4R touched)
            if not trade['touched_4r'] and remaining > 0:
                stop_hit = bar.low <= trade['stop_price'] if is_long else bar.high >= trade['stop_price']
                if stop_hit:
                    pnl = (trade['stop_price'] - trade['entry_price']) * remaining if is_long else (trade['entry_price'] - trade['stop_price']) * remaining
                    trade['exits'].append({'type': 'STOP', 'pnl': pnl, 'price': trade['stop_price'], 'time': bar.timestamp, 'cts': remaining})
                    trade['remaining'] = 0
                    loss_count += 1
                    remaining = 0

            # After 4R but BEFORE 8R - all contracts protected by T1 trail
            if trade['touched_4r'] and not trade['touched_8r'] and remaining > 0:
                t1_stop_hit = bar.low <= trade['t1_trail_stop'] if is_long else bar.high >= trade['t1_trail_stop']
                if t1_stop_hit:
                    # Exit all remaining contracts at T1 trail (they all share this protection before 8R)
                    if not trade['t1_exited']:
                        exit_cts = min(cts_t1, remaining)
                        pnl = (trade['t1_trail_stop'] - trade['entry_price']) * exit_cts if is_long else (trade['entry_price'] - trade['t1_trail_stop']) * exit_cts
                        trade['exits'].append({'type': 'T1_STRUCT', 'pnl': pnl, 'price': trade['t1_trail_stop'], 'time': bar.timestamp, 'cts': exit_cts})
                        trade['remaining'] -= exit_cts
                        trade['t1_exited'] = True
                        remaining = trade['remaining']

                    # T2 and runner exit at same price (before 8R, they use T1 protection)
                    if remaining > 0:
                        pnl = (trade['t1_trail_stop'] - trade['entry_price']) * remaining if is_long else (trade['entry_price'] - trade['t1_trail_stop']) * remaining
                        trade['exits'].append({'type': 'TRAIL_STOP', 'pnl': pnl, 'price': trade['t1_trail_stop'], 'time': bar.timestamp, 'cts': remaining})
                        trade['t2_exited'] = True
                        trade['remaining'] = 0
                        remaining = 0

            # After 8R touched - each tier has its own trail
            if trade['touched_8r'] and remaining > 0:
                # Check T1 trail (fast, 2-tick buffer)
                if not trade['t1_exited']:
                    t1_stop_hit = bar.low <= trade['t1_trail_stop'] if is_long else bar.high >= trade['t1_trail_stop']
                    if t1_stop_hit:
                        exit_cts = min(cts_t1, remaining)
                        pnl = (trade['t1_trail_stop'] - trade['entry_price']) * exit_cts if is_long else (trade['entry_price'] - trade['t1_trail_stop']) * exit_cts
                        trade['exits'].append({'type': 'T1_STRUCT', 'pnl': pnl, 'price': trade['t1_trail_stop'], 'time': bar.timestamp, 'cts': exit_cts})
                        trade['remaining'] -= exit_cts
                        trade['t1_exited'] = True
                        remaining = trade['remaining']

                # Check T2 trail (standard, 4-tick buffer)
                if not trade['t2_exited'] and remaining > cts_runner:
                    t2_stop_hit = bar.low <= trade['t2_trail_stop'] if is_long else bar.high >= trade['t2_trail_stop']
                    if t2_stop_hit:
                        exit_cts = min(cts_t2, remaining - cts_runner)
                        pnl = (trade['t2_trail_stop'] - trade['entry_price']) * exit_cts if is_long else (trade['entry_price'] - trade['t2_trail_stop']) * exit_cts
                        trade['exits'].append({'type': 'T2_STRUCT', 'pnl': pnl, 'price': trade['t2_trail_stop'], 'time': bar.timestamp, 'cts': exit_cts})
                        trade['remaining'] -= exit_cts
                        trade['t2_exited'] = True
                        remaining = trade['remaining']

                # Check runner stop (+4R trail)
                if trade['t1_exited'] and trade['t2_exited'] and remaining > 0:
                    runner_stop_hit = bar.low <= trade['runner_stop'] if is_long else bar.high >= trade['runner_stop']
                    if runner_stop_hit:
                        pnl = (trade['runner_stop'] - trade['entry_price']) * remaining if is_long else (trade['entry_price'] - trade['runner_stop']) * remaining
                        trade['exits'].append({'type': 'RUNNER_STOP', 'pnl': pnl, 'price': trade['runner_stop'], 'time': bar.timestamp, 'cts': remaining})
                        trade['remaining'] = 0
                        remaining = 0

                # Check opposing FVG exit for runner (if enabled)
                if use_opposing_fvg_exit and trade['t1_exited'] and remaining > 0:
                    opposing_dir = 'BEARISH' if is_long else 'BULLISH'
                    # Check if opposing FVG formed on this bar
                    for fvg in all_fvgs:
                        if fvg.direction == opposing_dir and fvg.created_bar_index == i:
                            # Opposing FVG just formed - exit runner at close
                            pnl = (bar.close - trade['entry_price']) * remaining if is_long else (trade['entry_price'] - bar.close) * remaining
                            trade['exits'].append({'type': 'OPP_FVG', 'pnl': pnl, 'price': bar.close, 'time': bar.timestamp, 'cts': remaining})
                            trade['remaining'] = 0
                            remaining = 0
                            break

            # Mark trade for removal if fully exited
            if trade['remaining'] <= 0:
                trades_to_remove.append(trade)

        # Remove completed trades and add to completed_results
        for trade in trades_to_remove:
            if trade in active_trades:
                active_trades.remove(trade)
                completed_results.append(trade)

        # Check if we can enter new trades (respect position limit and loss limit)
        if loss_count >= max_losses_per_day:
            continue

        current_open = len(active_trades)

        # Check for new entry opportunities
        for entry in all_valid_entries:
            if entry['entry_bar_idx'] != i:
                continue

            direction = entry['direction']

            # Check position limit
            if current_open >= max_open_trades:
                continue

            # Check if we've already taken 2 entries in this direction
            if entries_taken[direction] >= 2:
                continue

            # Enter the trade
            is_long = direction == 'LONG'
            entry_price = entry['midpoint']
            stop_price = entry['stop']
            risk = abs(entry_price - stop_price)

            target_4r = entry_price + (4 * risk) if is_long else entry_price - (4 * risk)
            target_8r = entry_price + (8 * risk) if is_long else entry_price - (8 * risk)
            plus_4r = entry_price + (4 * risk) if is_long else entry_price - (4 * risk)

            new_trade = {
                'direction': direction,
                'entry_bar_idx': i,
                'entry_time': entry['entry_time'],
                'entry_price': entry_price,
                'midpoint': entry['midpoint'],
                'stop_price': stop_price,
                'fvg_low': entry['fvg_low'],
                'fvg_high': entry['fvg_high'],
                'risk': risk,
                'target_4r': target_4r,
                'target_8r': target_8r,
                'plus_4r': plus_4r,
                'touched_4r': False,
                'touched_8r': False,
                # T1 fast structure trail (2-tick buffer, active after 4R)
                't1_trail_stop': stop_price,
                't1_last_swing': entry_price,
                't1_exited': False,
                # T2 standard structure trail (4-tick buffer, active after 8R)
                't2_trail_stop': plus_4r,
                't2_last_swing': entry_price,
                't2_exited': False,
                # Runner (+4R trailing stop after 8R)
                'runner_stop': plus_4r,
                'is_2nd_entry': entries_taken[direction] > 0,
                'remaining': contracts,
                'exits': [],
            }

            active_trades.append(new_trade)
            entries_taken[direction] += 1
            current_open += 1

    # EOD exit for remaining active trades
    last_bar = session_bars[-1]
    for trade in active_trades:
        if trade['remaining'] > 0:
            is_long = trade['direction'] == 'LONG'
            pnl = (last_bar.close - trade['entry_price']) * trade['remaining'] if is_long else (trade['entry_price'] - last_bar.close) * trade['remaining']
            trade['exits'].append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'cts': trade['remaining']})
            trade['remaining'] = 0
        completed_results.append(trade)

    # Build final results from all completed trades
    final_results = []

    for trade in completed_results:
        if not trade.get('exits'):
            continue

        is_long = trade['direction'] == 'LONG'
        total_pnl = sum(e['pnl'] for e in trade['exits'])
        total_dollars = (total_pnl / tick_size) * tick_value

        final_results.append({
            'direction': trade['direction'],
            'entry_time': trade['entry_time'],
            'entry_price': trade['entry_price'],
            'edge_price': trade['fvg_high'] if is_long else trade['fvg_low'],
            'midpoint_price': trade['midpoint'],
            'contracts_filled': contracts,
            'fill_type': 'FULL',
            'stop_price': trade['stop_price'],
            'fvg_low': trade['fvg_low'],
            'fvg_high': trade['fvg_high'],
            'target_4r': trade['target_4r'],
            'target_8r': trade['target_8r'],
            'plus_4r': trade.get('plus_4r', trade['target_4r']),
            'risk': trade['risk'],
            'total_pnl': total_pnl,
            'total_dollars': total_dollars,
            'was_stopped': any(e['type'] == 'STOP' for e in trade['exits']),
            'exits': trade['exits'],
            'is_reentry': trade.get('is_2nd_entry', False),
        })

    return final_results


def run_today(symbol='ES', contracts=3, max_open_trades=2, min_risk_pts=None, use_opposing_fvg_exit=False):
    """Run backtest for today with combined position limit.

    V9 Strategy Features:
    - Min risk filter: Skips small FVGs (ES: 2.0 pts, NQ: 8.0 pts)
    - Opposing FVG exit: DISABLED (runner uses +4R trail only)

    Args:
        min_risk_pts: Minimum risk in points (default: ES=2.0, NQ=8.0)
        use_opposing_fvg_exit: Exit runner on opposing FVG formation (default: False)
    """

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25

    # Set default min_risk based on symbol
    if min_risk_pts is None:
        min_risk_pts = 1.5 if symbol == 'ES' else 6.0 if symbol == 'NQ' else 1.5

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
    print('Strategy: ICT FVG V9 (Tiered Trail + Risk Filter)')
    print('  - Stop buffer: +2 ticks')
    print('  - HTF bias: EMA 20/50')
    print('  - ADX filter: > 17 (trend strength)')
    print('  - DI Direction: +DI/-DI alignment')
    print(f'  - Max open trades: {max_open_trades} (combined LONG+SHORT)')
    print('  - Max losses: 2 per day')
    print('  - Min FVG: 5 ticks')
    print('  - Displacement: 1.0x (lower threshold)')
    print(f'  - Min risk: {min_risk_pts} pts (filters small FVGs)')
    print(f'  - Runner exit: +4R trail {"+ opposing FVG" if use_opposing_fvg_exit else "only"}')
    print('  - Killzones: DISABLED')
    print('  - Entry: AT FVG CREATION (aggressive)')
    print('  - 2nd Entry: INDEPENDENT (if position limit allows)')
    print('  - T1 (1 ct): Fast structure trail after 4R (2-tick buffer)')
    print('  - T2 (1 ct): Standard structure trail after 8R (4-tick buffer)')
    print('='*70)

    # Use new position-limited function
    all_results = run_session_with_position_limit(
        session_bars,
        tick_size=tick_size,
        tick_value=tick_value,
        contracts=contracts,
        max_open_trades=max_open_trades,
        min_risk_pts=min_risk_pts,
        use_opposing_fvg_exit=use_opposing_fvg_exit,
    )

    for result in all_results:
        result['date'] = today

    loss_count = sum(1 for r in all_results if r['total_dollars'] < 0)

    total_pnl = 0
    for r in all_results:
        if r.get('is_reentry'):
            tag = ' [2nd FVG]'
        else:
            tag = ''
        result_str = 'WIN' if r['total_pnl'] > 0.01 else 'LOSS' if r['total_pnl'] < -0.01 else 'BE'
        total_pnl += r['total_dollars']

        print(f"\n{r['direction']} TRADE{tag}")
        print(f"  Fill: {r['fill_type']} ({r['contracts_filled']} cts)")
        print(f"  Entry: {r['entry_price']:.2f} @ {r['entry_time'].strftime('%H:%M')}")
        print(f"    Edge: {r['edge_price']:.2f} | Midpoint: {r['midpoint_price']:.2f}")
        print(f"  FVG: {r['fvg_low']:.2f} - {r['fvg_high']:.2f}")
        stop_info = f"{r['stop_price']:.2f}"
        if r.get('stop_locked_to'):
            stop_info += f" -> {r['stop_locked_to']:.2f} (+1R lock)"
        print(f"  Stop: {stop_info}")
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
    # V9 defaults: min_risk enabled, opposing FVG exit disabled
    # Override with CLI args if provided
    min_risk = float(sys.argv[3]) if len(sys.argv) > 3 else None  # None = use symbol default
    opp_fvg = bool(int(sys.argv[4])) if len(sys.argv) > 4 else False  # Default disabled
    run_today(symbol=symbol, contracts=contracts, min_risk_pts=min_risk, use_opposing_fvg_exit=opp_fvg)
