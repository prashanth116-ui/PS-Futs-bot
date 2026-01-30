"""
Run backtest for today with ICT FVG Strategy (V4-Filtered).

Strategy Features:
- Stop buffer: +2 ticks beyond FVG boundary (reduces whipsaws)
- HTF bias: EMA 20/50 trend filter at entry time (trade with trend)
- ADX > 20 filter: Only trade when market is trending (avoids chop)
- Max 2 losses/day: Stop trading after 2 losing trades
- Min FVG size: 6 ticks (filters tiny FVGs)
- Displacement: 1.2x body size (filters weak FVGs)
- Extended killzones: London (3-5 AM), NY AM (9:30-12), NY PM (1:30-3:30)
- Partial fill entry: 1 ct @ edge, 2 cts @ midpoint

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
    """Calculate ADX (Average Directional Index) for trend strength.

    ADX > 25 = strong trend
    ADX 20-25 = developing trend
    ADX < 20 = weak/no trend (choppy market)
    """
    if len(bars) < period * 2:
        return None

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
        return None

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
        return None

    # ADX is smoothed DX
    adx = sum(dx_list[-period:]) / period
    return adx


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
    min_fvg_ticks=6,
    displacement_threshold=1.2,
    require_displacement=True,
    require_killzone=True,
    require_htf_bias=True,
    require_adx=True,
    min_adx=20,
):
    """Run trade with ICT FVG Strategy (V4-Filtered)."""
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
                    if require_adx:
                        bars_to_entry = session_bars[:i+1]
                        adx = calculate_adx(bars_to_entry, 14)
                        if adx is not None and adx < min_adx:
                            continue  # Skip this entry, market not trending

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
    print('Strategy: ICT FVG V4-Filtered')
    print('  - Stop buffer: +2 ticks')
    print('  - HTF bias: EMA 20/50')
    print('  - ADX filter: > 20 (trend strength)')
    print('  - Max losses: 2 per day')
    print('  - Min FVG: 6 ticks')
    print('  - Displacement: 1.2x')
    print('  - Killzones: London + NY AM + NY PM')
    print('  - Entry: 1 ct @ edge, 2 cts @ midpoint')
    print('  - Targets: 4R, 8R, Runner')
    print('  - Hybrid trailing: +4R after 8R hits')
    print('='*70)

    all_results = []
    loss_count = 0
    max_losses = 2

    for direction in ['LONG', 'SHORT']:
        # Check if we've hit max losses for the day
        if loss_count >= max_losses:
            print(f"\n** MAX LOSSES ({max_losses}) REACHED - Stopping {direction} trades **")
            continue

        result = run_trade(session_bars, direction, 1, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
        if result:
            result['date'] = today
            all_results.append(result)

            # Track losses
            if result['total_dollars'] < 0:
                loss_count += 1

            # Try re-entry if stopped out (and haven't hit max losses)
            if result['was_stopped'] and loss_count < max_losses:
                result2 = run_trade(session_bars, direction, 2, tick_size=tick_size, tick_value=tick_value, contracts=contracts)
                if result2:
                    result2['date'] = today
                    result2['is_reentry'] = True
                    all_results.append(result2)

                    # Track losses for re-entry
                    if result2['total_dollars'] < 0:
                        loss_count += 1

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
