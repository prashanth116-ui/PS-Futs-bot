"""
Plot today's trade.
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
from datetime import date, time as dt_time
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


def plot_today(symbol='ES', direction='LONG', contracts=3):
    """Plot today's trade."""

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25

    print(f'Fetching {symbol} 3m data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=1000)

    if not all_bars:
        print('No data available')
        return

    # Get today's date from most recent bar
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

    # Detect FVGs
    fvg_config = {
        'min_fvg_ticks': 4,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)
    update_all_fvg_mitigations(all_fvgs, session_bars, fvg_config)

    # Get FVGs for direction
    dir_fvgs = [f for f in all_fvgs if f.direction == fvg_dir and not f.mitigated]
    dir_fvgs.sort(key=lambda f: f.created_bar_index)

    if not dir_fvgs:
        print(f'No {fvg_dir} FVGs found')
        return

    entry_fvg = dir_fvgs[0]

    # Calculate levels
    entry_price = entry_fvg.midpoint
    fvg_stop_level = entry_fvg.low if is_long else entry_fvg.high

    if is_long:
        stop_price = entry_fvg.low
        risk = entry_price - stop_price
    else:
        stop_price = entry_fvg.high
        risk = stop_price - entry_price

    target_4r = entry_price + (target1_r * risk) if is_long else entry_price - (target1_r * risk)
    target_8r = entry_price + (target2_r * risk) if is_long else entry_price - (target2_r * risk)

    # Calculate EMAs
    closes = [b.close for b in session_bars]
    ema_50 = calculate_ema(closes, 50)

    # Find entry bar
    entry_bar_idx = None
    for i in range(entry_fvg.created_bar_index + 1, len(session_bars)):
        bar = session_bars[i]
        if is_long:
            if bar.low <= entry_price:
                entry_bar_idx = i
                break
        else:
            if bar.high >= entry_price:
                entry_bar_idx = i
                break

    if not entry_bar_idx:
        print('No entry triggered')
        return

    # Find exit points
    exit_4r_idx = None
    exit_8r_idx = None
    exit_ema_idx = None
    exit_ema_price = None
    stop_idx = None

    exited_4r = False
    exited_8r = False
    was_stopped = False

    for i in range(entry_bar_idx + 1, len(session_bars)):
        bar = session_bars[i]
        bar_ema50 = ema_50[i] if i < len(ema_50) and ema_50[i] else None

        # Check stop (FVG mitigation - close based)
        if is_long:
            if bar.close < fvg_stop_level:
                stop_idx = i
                was_stopped = True
                break
        else:
            if bar.close > fvg_stop_level:
                stop_idx = i
                was_stopped = True
                break

        # Check targets
        if is_long:
            if not exited_4r and bar.high >= target_4r:
                exit_4r_idx = i
                exited_4r = True
            if not exited_8r and bar.high >= target_8r:
                exit_8r_idx = i
                exited_8r = True
        else:
            if not exited_4r and bar.low <= target_4r:
                exit_4r_idx = i
                exited_4r = True
            if not exited_8r and bar.low <= target_8r:
                exit_8r_idx = i
                exited_8r = True

        # Check EMA exit for runner
        if exited_4r and exited_8r and bar_ema50:
            if is_long:
                if bar.close < bar_ema50:
                    exit_ema_idx = i
                    exit_ema_price = bar.close
                    break
            else:
                if bar.close > bar_ema50:
                    exit_ema_idx = i
                    exit_ema_price = bar.close
                    break

    # Calculate P/L
    total_dollars = 0
    if was_stopped:
        total_dollars = -risk * contracts / tick_size * tick_value
        result_str = 'LOSS (STOPPED)'
    else:
        if exit_4r_idx:
            total_dollars += (target1_r * risk / tick_size) * tick_value
        if exit_8r_idx:
            total_dollars += (target2_r * risk / tick_size) * tick_value
        if exit_ema_idx and exit_ema_price:
            if is_long:
                runner_pnl = ((exit_ema_price - entry_price) / tick_size) * tick_value
            else:
                runner_pnl = ((entry_price - exit_ema_price) / tick_size) * tick_value
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

    # Plot EMA50
    ema_x = [i for i, e in enumerate(ema_50) if e is not None]
    ema_y = [e for e in ema_50 if e is not None]
    ax.plot(ema_x, ema_y, color='#9C27B0', linewidth=2, label='EMA 50', alpha=0.8)

    # Highlight entry FVG
    fvg_start = entry_fvg.created_bar_index
    fvg_color = '#4CAF50' if is_long else '#F44336'
    fvg_rect = plt.Rectangle((fvg_start - 0.5, entry_fvg.low),
                              len(session_bars) - fvg_start,
                              entry_fvg.high - entry_fvg.low,
                              facecolor=fvg_color, alpha=0.2, edgecolor=fvg_color, linewidth=2)
    ax.add_patch(fvg_rect)

    # Plot trade levels
    line_start = max(0, entry_bar_idx - 10)
    line_end = min(len(session_bars), (stop_idx or exit_ema_idx or exit_8r_idx or entry_bar_idx) + 20)

    # Entry line
    ax.hlines(entry_price, line_start, line_end, colors='#2196F3', linestyles='-', linewidth=2, label=f'Entry: {entry_price:.2f}')

    # Stop line
    ax.hlines(stop_price, line_start, line_end, colors='#F44336', linestyles='--', linewidth=2, label=f'Stop: {stop_price:.2f}')

    # Target lines
    ax.hlines(target_4r, line_start, line_end, colors='#4CAF50', linestyles='--', linewidth=2, label=f'4R: {target_4r:.2f}')
    ax.hlines(target_8r, line_start, line_end, colors='#8BC34A', linestyles='--', linewidth=2, label=f'8R: {target_8r:.2f}')

    # Mark entry point
    entry_marker = '^' if is_long else 'v'
    ax.scatter([entry_bar_idx], [entry_price], color='#2196F3', s=200, zorder=5,
               marker=entry_marker, edgecolors='black', linewidths=2)
    ax.annotate(f'ENTRY\n{session_bars[entry_bar_idx].timestamp.strftime("%H:%M")}\n{entry_price:.2f}',
                xy=(entry_bar_idx, entry_price),
                xytext=(entry_bar_idx - 8, entry_price + (3 if is_long else -3)),
                fontsize=10, fontweight='bold', color='#2196F3',
                arrowprops=dict(arrowstyle='->', color='#2196F3', lw=2))

    # Mark exits
    if not was_stopped:
        if exit_4r_idx:
            ax.scatter([exit_4r_idx], [target_4r], color='#4CAF50', s=200, zorder=5,
                       marker='v' if is_long else '^', edgecolors='black', linewidths=2)
            ax.annotate(f'4R EXIT\n{session_bars[exit_4r_idx].timestamp.strftime("%H:%M")}',
                        xy=(exit_4r_idx, target_4r), xytext=(exit_4r_idx + 3, target_4r),
                        fontsize=9, fontweight='bold', color='#4CAF50')
        if exit_8r_idx:
            ax.scatter([exit_8r_idx], [target_8r], color='#8BC34A', s=200, zorder=5,
                       marker='v' if is_long else '^', edgecolors='black', linewidths=2)
            ax.annotate(f'8R EXIT\n{session_bars[exit_8r_idx].timestamp.strftime("%H:%M")}',
                        xy=(exit_8r_idx, target_8r), xytext=(exit_8r_idx + 3, target_8r),
                        fontsize=9, fontweight='bold', color='#8BC34A')
        if exit_ema_idx and exit_ema_price:
            ax.scatter([exit_ema_idx], [exit_ema_price], color='#9C27B0', s=200, zorder=5,
                       marker='v' if is_long else '^', edgecolors='black', linewidths=2)
            ax.annotate(f'EMA50 EXIT\n{session_bars[exit_ema_idx].timestamp.strftime("%H:%M")}\n{exit_ema_price:.2f}',
                        xy=(exit_ema_idx, exit_ema_price), xytext=(exit_ema_idx + 3, exit_ema_price),
                        fontsize=9, fontweight='bold', color='#9C27B0')
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
    focus_end = min(len(session_bars), (stop_idx or exit_ema_idx or exit_8r_idx or entry_bar_idx) + 50)
    ax.set_xlim(focus_start, focus_end)

    # Y-axis range
    if is_long:
        y_min = stop_price - 3
        y_max = max(target_8r, exit_ema_price or target_8r) + 3
    else:
        y_min = min(target_8r, exit_ema_price or target_8r) - 3
        y_max = stop_price + 3
    ax.set_ylim(y_min, y_max)

    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Price', fontsize=12)
    ax.set_title(f'{symbol} 3-Minute | {today} | {direction} Trade | {contracts} Contracts | 4R/8R Targets\n'
                 f'Result: {result_str} | P/L: ${total_dollars:+,.2f} | Risk: {risk:.2f} pts',
                 fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Add summary box
    summary = (f'TRADE SUMMARY\n'
               f'Direction: {direction}\n'
               f'Entry: {entry_price:.2f}\n'
               f'Stop: {stop_price:.2f}\n'
               f'Risk: {risk:.2f} pts\n'
               f'─────────────\n'
               f'4R Target: {target_4r:.2f}\n'
               f'8R Target: {target_8r:.2f}\n'
               f'─────────────\n'
               f'Result: {result_str}\n'
               f'P/L: ${total_dollars:+,.2f}')

    box_color = '#FFCDD2' if total_dollars < 0 else '#C8E6C9'
    edge_color = '#F44336' if total_dollars < 0 else '#4CAF50'
    props = dict(boxstyle='round', facecolor=box_color, alpha=0.9, edgecolor=edge_color, linewidth=2)
    ax.text(0.98, 0.98, summary, transform=ax.transAxes, fontsize=11,
            verticalalignment='top', horizontalalignment='right',
            fontweight='bold', bbox=props, family='monospace')

    plt.tight_layout()
    filename = f'backtest_{symbol}_today_{today}.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f'Saved: {filename}')
    plt.close()

    return filename


if __name__ == '__main__':
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    direction = sys.argv[2] if len(sys.argv) > 2 else 'LONG'
    contracts = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    plot_today(symbol=symbol, direction=direction, contracts=contracts)
