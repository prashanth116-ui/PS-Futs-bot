"""
Plot V6-Aggressive strategy for today.

V6-Aggressive Settings:
- Displacement: 1.0x (lower threshold)
- Entry: At FVG creation (no retracement wait)
- EMA 20/50, ADX >17, DI Direction filters
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_fvg_mitigation


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


def calculate_ema_bars(bars, period):
    if len(bars) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(b.close for b in bars[:period]) / period
    for bar in bars[period:]:
        ema = (bar.close - ema) * multiplier + ema
    return ema


def calculate_adx(bars, period=14):
    if len(bars) < period * 2:
        return None, None, None

    tr_list = []
    plus_dm_list = []
    minus_dm_list = []

    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        close_prev = bars[i-1].close
        high_prev = bars[i-1].high
        low_prev = bars[i-1].low

        tr = max(high - low, abs(high - close_prev), abs(low - close_prev))
        tr_list.append(tr)

        up_move = high - high_prev
        down_move = low_prev - low

        plus_dm = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0

        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)

    if len(tr_list) < period:
        return None, None, None

    def wilder_smooth(data, period):
        smoothed = [sum(data[:period])]
        for i in range(period, len(data)):
            smoothed.append(smoothed[-1] - (smoothed[-1] / period) + data[i])
        return smoothed

    atr = wilder_smooth(tr_list, period)
    plus_dm_smooth = wilder_smooth(plus_dm_list, period)
    minus_dm_smooth = wilder_smooth(minus_dm_list, period)

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

    adx = sum(dx_list[-period:]) / period
    return adx, plus_di, minus_di


def is_displacement_candle(bar, avg_body_size, threshold=1.0):
    body_size = abs(bar.close - bar.open)
    return body_size > avg_body_size * threshold


def is_swing_high(bars, idx, lookback=2):
    if idx < lookback or idx >= len(bars) - lookback:
        return False
    bar_high = bars[idx].high
    for i in range(1, lookback + 1):
        if bar_high <= bars[idx - i].high or bar_high <= bars[idx + i].high:
            return False
    return True


def is_swing_low(bars, idx, lookback=2):
    if idx < lookback or idx >= len(bars) - lookback:
        return False
    bar_low = bars[idx].low
    for i in range(1, lookback + 1):
        if bar_low >= bars[idx - i].low or bar_low >= bars[idx + i].low:
            return False
    return True


def plot_v6_aggressive(symbol='ES', direction='LONG', contracts=3, trade_num=1):
    """Plot V6-Aggressive strategy for today."""

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25
    stop_buffer_ticks = 2
    displacement_threshold = 1.0  # V6-Aggressive uses 1.0x

    print(f'Fetching {symbol} 3m data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=1000)

    if not all_bars:
        print('No data available')
        return

    today = all_bars[-1].timestamp.date()
    today_bars = [b for b in all_bars if b.timestamp.date() == today]

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

    print(f'Date: {today}')
    print(f'Session bars: {len(session_bars)}')

    if len(session_bars) < 50:
        print('Not enough bars')
        return

    # Trade parameters
    target1_r = 4
    target2_r = 8

    is_long = direction == 'LONG'
    fvg_dir = 'BULLISH' if is_long else 'BEARISH'
    opposing_fvg_dir = 'BEARISH' if is_long else 'BULLISH'

    # Calculate average body size
    body_sizes = [abs(b.close - b.open) for b in session_bars[:50]]
    avg_body_size = sum(body_sizes) / len(body_sizes) if body_sizes else tick_size * 4

    # Detect FVGs
    fvg_config = {
        'min_fvg_ticks': 5,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)

    # Find Nth valid FVG for direction (V6-Aggressive: enter at creation)
    entry_fvg = None
    entry_bar_idx = None
    valid_count = 0

    dir_fvgs = [f for f in all_fvgs if f.direction == fvg_dir]
    dir_fvgs.sort(key=lambda f: f.created_bar_index)

    for fvg in dir_fvgs:
        creating_bar = session_bars[fvg.created_bar_index]

        # Displacement filter (1.0x for V6-Aggressive)
        if not is_displacement_candle(creating_bar, avg_body_size, displacement_threshold):
            continue

        # Check filters at FVG creation time
        bars_to_entry = session_bars[:fvg.created_bar_index + 1]

        # EMA filter
        ema_fast = calculate_ema_bars(bars_to_entry, 20)
        ema_slow = calculate_ema_bars(bars_to_entry, 50)
        if ema_fast is not None and ema_slow is not None:
            if is_long and ema_fast < ema_slow:
                continue
            if not is_long and ema_fast > ema_slow:
                continue

        # ADX filter
        adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)
        if adx is not None:
            if adx < 17:
                continue
            if is_long and plus_di <= minus_di:
                continue
            if not is_long and minus_di <= plus_di:
                continue

        # Valid entry found
        valid_count += 1
        if valid_count == trade_num:
            entry_fvg = fvg
            entry_bar_idx = fvg.created_bar_index
            break

    if entry_fvg is None:
        print(f'No valid {direction} FVG found for V6-Aggressive')
        return

    # Entry at midpoint (aggressive entry at FVG creation)
    entry_price = entry_fvg.midpoint
    entry_time = session_bars[entry_bar_idx].timestamp

    # Stop with buffer
    if is_long:
        stop_price = entry_fvg.low - (stop_buffer_ticks * tick_size)
        risk = entry_price - stop_price
    else:
        stop_price = entry_fvg.high + (stop_buffer_ticks * tick_size)
        risk = stop_price - entry_price

    if risk <= 0:
        print('Invalid risk')
        return

    # Targets
    target_4r = entry_price + (target1_r * risk) if is_long else entry_price - (target1_r * risk)
    target_8r = entry_price + (target2_r * risk) if is_long else entry_price - (target2_r * risk)
    plus_4r = entry_price + (4 * risk) if is_long else entry_price - (4 * risk)

    # Calculate EMAs for display
    closes = [b.close for b in session_bars]
    ema_20 = calculate_ema(closes, 20)
    ema_50 = calculate_ema(closes, 50)

    # Simulate exits
    cts_t1 = 1
    cts_t2 = 1
    cts_runner = 1

    exits = []
    remaining = contracts
    exited_t1 = False
    exited_t2 = False
    t1_touched = False
    t2_touched = False

    runner_stop = stop_price
    t1_trail_stop = stop_price
    t2_trail_stop = plus_4r
    last_swing_t1 = entry_price
    last_swing_t2 = entry_price

    exit_t1_idx = None
    exit_t1_price = None
    exit_t2_idx = None
    exit_t2_price = None
    exit_runner_idx = None
    exit_runner_price = None
    exit_runner_type = None
    stop_idx = None
    was_stopped = False

    for i in range(entry_bar_idx + 1, len(session_bars)):
        if remaining <= 0:
            break
        bar = session_bars[i]

        # Check stop
        if (not exited_t1 and not t1_touched) or (not exited_t2 and not t2_touched):
            if is_long:
                stop_hit = bar.low <= stop_price
            else:
                stop_hit = bar.high >= stop_price

            if stop_hit:
                stop_idx = i
                was_stopped = True
                remaining = 0
                break

        # T1 structure trail
        if t1_touched and not exited_t1:
            check_idx = i - 2
            if check_idx > entry_bar_idx:
                if is_long and is_swing_low(session_bars, check_idx, lookback=2):
                    swing_low = session_bars[check_idx].low
                    if swing_low > last_swing_t1:
                        new_trail = swing_low - (2 * tick_size)
                        if new_trail > t1_trail_stop:
                            t1_trail_stop = new_trail
                            last_swing_t1 = swing_low

            if is_long and bar.low <= t1_trail_stop:
                exit_t1_idx = i
                exit_t1_price = t1_trail_stop
                remaining -= cts_t1
                exited_t1 = True

        # T2 structure trail
        if t2_touched and not exited_t2 and remaining > cts_runner:
            check_idx = i - 2
            if check_idx > entry_bar_idx:
                if is_long and is_swing_low(session_bars, check_idx, lookback=2):
                    swing_low = session_bars[check_idx].low
                    if swing_low > last_swing_t2:
                        new_trail = swing_low - (4 * tick_size)
                        if new_trail > t2_trail_stop:
                            t2_trail_stop = new_trail
                            last_swing_t2 = swing_low

            if is_long and bar.low <= t2_trail_stop:
                exit_t2_idx = i
                exit_t2_price = t2_trail_stop
                remaining -= cts_t2
                exited_t2 = True

        # Runner stop
        if remaining > 0 and remaining <= cts_runner and exited_t1 and exited_t2:
            if is_long and bar.low <= runner_stop:
                exit_runner_idx = i
                exit_runner_price = runner_stop
                exit_runner_type = '+4R STOP'
                remaining = 0
                break

        # Check 4R touch
        if not t1_touched and not exited_t1:
            if (is_long and bar.high >= target_4r) or (not is_long and bar.low <= target_4r):
                t1_touched = True
                t1_trail_stop = entry_price

        # Check 8R touch
        if not t2_touched and remaining > cts_runner:
            if (is_long and bar.high >= target_8r) or (not is_long and bar.low <= target_8r):
                t2_touched = True
                runner_stop = plus_4r

        # Opposing FVG for runner
        if remaining > 0 and remaining <= cts_runner:
            opposing_fvgs = [f for f in all_fvgs if f.direction == opposing_fvg_dir
                           and f.created_bar_index > entry_bar_idx
                           and f.created_bar_index <= i]
            if opposing_fvgs:
                exit_runner_idx = i
                exit_runner_price = bar.close
                exit_runner_type = 'OPP FVG'
                remaining = 0
                break

    # EOD exit
    if remaining > 0:
        last_bar = session_bars[-1]
        if not exited_t1:
            exit_t1_idx = len(session_bars) - 1
            exit_t1_price = last_bar.close
        if not exited_t2:
            exit_t2_idx = len(session_bars) - 1
            exit_t2_price = last_bar.close
        if remaining <= cts_runner:
            exit_runner_idx = len(session_bars) - 1
            exit_runner_price = last_bar.close
            exit_runner_type = 'EOD'

    # Calculate P/L
    total_dollars = 0
    if was_stopped:
        total_dollars = ((stop_price - entry_price) if is_long else (entry_price - stop_price)) * contracts / tick_size * tick_value
        result_str = 'LOSS (STOPPED)'
    else:
        if exit_t1_price:
            t1_pnl = ((exit_t1_price - entry_price) if is_long else (entry_price - exit_t1_price)) * cts_t1 / tick_size * tick_value
            total_dollars += t1_pnl
        if exit_t2_price:
            t2_pnl = ((exit_t2_price - entry_price) if is_long else (entry_price - exit_t2_price)) * cts_t2 / tick_size * tick_value
            total_dollars += t2_pnl
        if exit_runner_price:
            runner_pnl = ((exit_runner_price - entry_price) if is_long else (entry_price - exit_runner_price)) * cts_runner / tick_size * tick_value
            total_dollars += runner_pnl
        result_str = 'WIN' if total_dollars > 0 else 'LOSS'

    # Create figure
    fig, ax = plt.subplots(figsize=(18, 10))

    # Plot candlesticks
    for i, bar in enumerate(session_bars):
        color = '#4CAF50' if bar.close >= bar.open else '#F44336'
        ax.plot([i, i], [bar.low, bar.high], color=color, linewidth=1)
        body_bottom = min(bar.open, bar.close)
        body_height = abs(bar.close - bar.open)
        rect = plt.Rectangle((i - 0.3, body_bottom), 0.6, body_height,
                             facecolor=color, edgecolor=color)
        ax.add_patch(rect)

    # Plot EMAs
    ema_x_20 = [i for i, e in enumerate(ema_20) if e is not None]
    ema_y_20 = [e for e in ema_20 if e is not None]
    ax.plot(ema_x_20, ema_y_20, color='#2196F3', linewidth=1.5, label='EMA 20', alpha=0.7)

    ema_x_50 = [i for i, e in enumerate(ema_50) if e is not None]
    ema_y_50 = [e for e in ema_50 if e is not None]
    ax.plot(ema_x_50, ema_y_50, color='#9C27B0', linewidth=2, label='EMA 50', alpha=0.8)

    # Highlight entry FVG
    fvg_start = entry_fvg.created_bar_index
    fvg_color = '#4CAF50' if is_long else '#F44336'
    fvg_rect = plt.Rectangle((fvg_start - 0.5, entry_fvg.low),
                              len(session_bars) - fvg_start,
                              entry_fvg.high - entry_fvg.low,
                              facecolor=fvg_color, alpha=0.2, edgecolor=fvg_color, linewidth=2)
    ax.add_patch(fvg_rect)

    # Plot trade levels
    last_exit_idx = max(filter(None, [stop_idx, exit_t1_idx, exit_t2_idx, exit_runner_idx, entry_bar_idx]))
    line_start = max(0, entry_bar_idx - 10)
    line_end = min(len(session_bars), last_exit_idx + 20)

    ax.hlines(entry_price, line_start, line_end, colors='#2196F3', linestyles='-', linewidth=2, label=f'Entry: {entry_price:.2f}')
    ax.hlines(stop_price, line_start, line_end, colors='#F44336', linestyles='--', linewidth=2, label=f'Stop: {stop_price:.2f}')
    ax.hlines(target_4r, line_start, line_end, colors='#4CAF50', linestyles='--', linewidth=2, label=f'4R: {target_4r:.2f}')
    ax.hlines(target_8r, line_start, line_end, colors='#8BC34A', linestyles='--', linewidth=2, label=f'8R: {target_8r:.2f}')

    if t2_touched:
        ax.hlines(plus_4r, line_start, line_end, colors='#FF9800', linestyles=':', linewidth=2, label=f'+4R Stop: {plus_4r:.2f}')

    # Mark entry point
    entry_marker = '^' if is_long else 'v'
    ax.scatter([entry_bar_idx], [entry_price], color='#2196F3', s=200, zorder=5,
               marker=entry_marker, edgecolors='black', linewidths=2)
    trade_label = f'TRADE #{trade_num}' if trade_num > 1 else 'ENTRY (AT CREATION)'
    ax.annotate(f'{trade_label}\n{entry_time.strftime("%H:%M")}\n{entry_price:.2f}',
                xy=(entry_bar_idx, entry_price),
                xytext=(entry_bar_idx - 8, entry_price + (3 if is_long else -3)),
                fontsize=10, fontweight='bold', color='#2196F3',
                arrowprops=dict(arrowstyle='->', color='#2196F3', lw=2))

    # Mark exits
    if not was_stopped:
        if exit_t1_idx and exit_t1_price:
            ax.scatter([exit_t1_idx], [exit_t1_price], color='#4CAF50', s=200, zorder=5,
                       marker='v' if is_long else '^', edgecolors='black', linewidths=2)
            ax.annotate(f'T1 EXIT\n{session_bars[exit_t1_idx].timestamp.strftime("%H:%M")}\n{exit_t1_price:.2f}',
                        xy=(exit_t1_idx, exit_t1_price), xytext=(exit_t1_idx + 3, exit_t1_price),
                        fontsize=9, fontweight='bold', color='#4CAF50')

        if exit_t2_idx and exit_t2_price:
            ax.scatter([exit_t2_idx], [exit_t2_price], color='#8BC34A', s=200, zorder=5,
                       marker='v' if is_long else '^', edgecolors='black', linewidths=2)
            ax.annotate(f'T2 EXIT\n{session_bars[exit_t2_idx].timestamp.strftime("%H:%M")}\n{exit_t2_price:.2f}',
                        xy=(exit_t2_idx, exit_t2_price), xytext=(exit_t2_idx + 3, exit_t2_price),
                        fontsize=9, fontweight='bold', color='#8BC34A')

        if exit_runner_idx and exit_runner_price:
            runner_color = '#FF9800' if exit_runner_type == '+4R STOP' else '#E91E63' if exit_runner_type == 'OPP FVG' else '#9E9E9E'
            ax.scatter([exit_runner_idx], [exit_runner_price], color=runner_color, s=200, zorder=5,
                       marker='v' if is_long else '^', edgecolors='black', linewidths=2)
            ax.annotate(f'RUNNER\n{exit_runner_type}\n{session_bars[exit_runner_idx].timestamp.strftime("%H:%M")}\n{exit_runner_price:.2f}',
                        xy=(exit_runner_idx, exit_runner_price), xytext=(exit_runner_idx + 3, exit_runner_price),
                        fontsize=9, fontweight='bold', color=runner_color)
    else:
        if stop_idx:
            ax.scatter([stop_idx], [stop_price], color='#F44336', s=200, zorder=5,
                       marker='X', edgecolors='black', linewidths=2)
            ax.annotate(f'STOPPED\n{session_bars[stop_idx].timestamp.strftime("%H:%M")}',
                        xy=(stop_idx, stop_price), xytext=(stop_idx + 3, stop_price),
                        fontsize=10, fontweight='bold', color='#F44336')

    # X-axis labels
    tick_indices = list(range(0, len(session_bars), 20))
    tick_labels = [session_bars[i].timestamp.strftime('%H:%M') for i in tick_indices]
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(tick_labels, rotation=45)

    # Focus on trade area
    focus_start = max(0, entry_bar_idx - 30)
    focus_end = min(len(session_bars), last_exit_idx + 50)
    ax.set_xlim(focus_start, focus_end)

    # Y-axis range
    all_prices = [stop_price, entry_price, target_4r, target_8r]
    if exit_runner_price:
        all_prices.append(exit_runner_price)
    y_min = min(all_prices) - 5
    y_max = max(all_prices) + 5
    ax.set_ylim(y_min, y_max)

    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Price', fontsize=12)
    trade_title = f'Trade #{trade_num}' if trade_num > 1 else 'Trade'
    ax.set_title(f'{symbol} 3-Minute | {today} | {direction} {trade_title} | V6-AGGRESSIVE\n'
                 f'Result: {result_str} | P/L: ${total_dollars:+,.2f} | Risk: {risk:.2f} pts',
                 fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Add summary box
    t1_exit_str = f'{exit_t1_price:.2f}' if exit_t1_price else 'N/A'
    t2_exit_str = f'{exit_t2_price:.2f}' if exit_t2_price else 'N/A'
    runner_exit_str = f'{exit_runner_price:.2f} ({exit_runner_type})' if exit_runner_price else 'N/A'

    summary = (f'V6-AGGRESSIVE\n'
               f'Disp: 1.0x | Entry: At Creation\n'
               f'─────────────\n'
               f'Direction: {direction}\n'
               f'Entry: {entry_price:.2f}\n'
               f'Stop: {stop_price:.2f}\n'
               f'Risk: {risk:.2f} pts\n'
               f'─────────────\n'
               f'4R Target: {target_4r:.2f}\n'
               f'8R Target: {target_8r:.2f}\n'
               f'+4R Stop: {plus_4r:.2f}\n'
               f'─────────────\n'
               f'T1 Exit: {t1_exit_str}\n'
               f'T2 Exit: {t2_exit_str}\n'
               f'Runner: {runner_exit_str}\n'
               f'─────────────\n'
               f'Result: {result_str}\n'
               f'P/L: ${total_dollars:+,.2f}')

    box_color = '#FFCDD2' if total_dollars < 0 else '#C8E6C9'
    edge_color = '#F44336' if total_dollars < 0 else '#4CAF50'
    props = dict(boxstyle='round', facecolor=box_color, alpha=0.9, edgecolor=edge_color, linewidth=2)
    ax.text(0.98, 0.98, summary, transform=ax.transAxes, fontsize=10,
            verticalalignment='top', horizontalalignment='right',
            fontweight='bold', bbox=props, family='monospace')

    plt.tight_layout()
    trade_suffix = f'_trade{trade_num}' if trade_num > 1 else ''
    filename = f'backtest_{symbol}_V6Aggressive_{today}{trade_suffix}.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f'Saved: {filename}')
    plt.close()

    return filename


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    direction = sys.argv[2] if len(sys.argv) > 2 else 'LONG'
    contracts = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    trade_num = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    plot_v6_aggressive(symbol=symbol, direction=direction, contracts=contracts, trade_num=trade_num)
