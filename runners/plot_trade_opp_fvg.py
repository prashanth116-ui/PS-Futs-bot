"""
Plot trade with Opposing FVG runner exit.
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations


def plot_trade(trade_date, direction='LONG', symbol='ES'):
    """Plot trade for a specific date with Opposing FVG runner exit."""

    tick_size = 0.25
    tick_value = 12.50

    print(f'Fetching {symbol} 3m data for {trade_date}...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=5000)

    if not all_bars:
        print('No data available')
        return

    # Filter for the specific date
    date_bars = [b for b in all_bars if b.timestamp.date() == trade_date]

    # Session filter
    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in date_bars if premarket_start <= b.timestamp.time() <= rth_end]

    print(f'Got {len(session_bars)} session bars')

    if len(session_bars) < 50:
        print('Not enough bars')
        return

    # Trade parameters
    contracts = 3
    target1_r = 4
    target2_r = 8

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
    exit_opp_fvg_idx = None
    exit_opp_fvg_price = None
    stop_idx = None

    exited_4r = False
    exited_8r = False
    was_stopped = False
    remaining = contracts
    cts_runner = 1

    for i in range(entry_bar_idx + 1, len(session_bars)):
        bar = session_bars[i]

        # Check stop (FVG mitigation)
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
                remaining -= 1
            if not exited_8r and bar.high >= target_8r:
                exit_8r_idx = i
                exited_8r = True
                remaining -= 1
        else:
            if not exited_4r and bar.low <= target_4r:
                exit_4r_idx = i
                exited_4r = True
                remaining -= 1
            if not exited_8r and bar.low <= target_8r:
                exit_8r_idx = i
                exited_8r = True
                remaining -= 1

        # Check Opposing FVG exit for runner
        if remaining == cts_runner and exited_4r and exited_8r:
            opposing_fvgs = [f for f in all_fvgs if f.direction == opposing_fvg_dir
                           and f.created_bar_index > entry_bar_idx
                           and f.created_bar_index <= i]
            if opposing_fvgs:
                exit_opp_fvg_idx = i
                exit_opp_fvg_price = bar.close
                # Find the opposing FVG that triggered the exit
                triggering_fvg = opposing_fvgs[-1]
                break

    # Calculate P/L
    total_dollars = 0
    if was_stopped:
        pnl = -risk * contracts
        total_dollars = (pnl / tick_size) * tick_value
        result_str = 'LOSS (STOPPED)'
    else:
        if exit_4r_idx:
            total_dollars += (target1_r * risk / tick_size) * tick_value
        if exit_8r_idx:
            total_dollars += (target2_r * risk / tick_size) * tick_value
        if exit_opp_fvg_idx and exit_opp_fvg_price:
            if is_long:
                runner_pnl = ((exit_opp_fvg_price - entry_price) / tick_size) * tick_value
            else:
                runner_pnl = ((entry_price - exit_opp_fvg_price) / tick_size) * tick_value
            total_dollars += runner_pnl
        elif remaining > 0:
            # EOD exit
            last_bar = session_bars[-1]
            if is_long:
                runner_pnl = ((last_bar.close - entry_price) / tick_size) * tick_value
            else:
                runner_pnl = ((entry_price - last_bar.close) / tick_size) * tick_value
            total_dollars += runner_pnl
            exit_opp_fvg_idx = len(session_bars) - 1
            exit_opp_fvg_price = last_bar.close
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

    # Highlight entry FVG
    fvg_start = entry_fvg.created_bar_index
    fvg_color = '#4CAF50' if is_long else '#F44336'
    fvg_rect = plt.Rectangle((fvg_start - 0.5, entry_fvg.low),
                              len(session_bars) - fvg_start,
                              entry_fvg.high - entry_fvg.low,
                              facecolor=fvg_color, alpha=0.2, edgecolor=fvg_color, linewidth=2,
                              label=f'Entry FVG ({fvg_dir})')
    ax.add_patch(fvg_rect)

    # Highlight opposing FVGs
    for fvg in all_fvgs:
        if fvg.direction == opposing_fvg_dir and fvg.created_bar_index > entry_bar_idx:
            opp_color = '#F44336' if is_long else '#4CAF50'
            opp_rect = plt.Rectangle((fvg.created_bar_index - 0.5, fvg.low),
                                      20, fvg.high - fvg.low,
                                      facecolor=opp_color, alpha=0.3, edgecolor=opp_color,
                                      linewidth=2, linestyle='--')
            ax.add_patch(opp_rect)

    # Plot trade levels
    line_start = max(0, entry_bar_idx - 10)
    line_end = min(len(session_bars), (stop_idx or exit_opp_fvg_idx or exit_8r_idx or entry_bar_idx) + 30)

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
                        xy=(exit_4r_idx, target_4r), xytext=(exit_4r_idx + 3, target_4r + (1 if is_long else -1)),
                        fontsize=9, fontweight='bold', color='#4CAF50')
        if exit_8r_idx:
            ax.scatter([exit_8r_idx], [target_8r], color='#8BC34A', s=200, zorder=5,
                       marker='v' if is_long else '^', edgecolors='black', linewidths=2)
            ax.annotate(f'8R EXIT\n{session_bars[exit_8r_idx].timestamp.strftime("%H:%M")}',
                        xy=(exit_8r_idx, target_8r), xytext=(exit_8r_idx + 3, target_8r + (1 if is_long else -1)),
                        fontsize=9, fontweight='bold', color='#8BC34A')
        if exit_opp_fvg_idx and exit_opp_fvg_price:
            ax.scatter([exit_opp_fvg_idx], [exit_opp_fvg_price], color='#FF9800', s=200, zorder=5,
                       marker='v' if is_long else '^', edgecolors='black', linewidths=2)
            exit_type = 'OPP FVG' if exit_opp_fvg_idx < len(session_bars) - 1 else 'EOD'
            ax.annotate(f'{exit_type} EXIT\n{session_bars[exit_opp_fvg_idx].timestamp.strftime("%H:%M")}\n{exit_opp_fvg_price:.2f}',
                        xy=(exit_opp_fvg_idx, exit_opp_fvg_price),
                        xytext=(exit_opp_fvg_idx + 3, exit_opp_fvg_price + (2 if is_long else -2)),
                        fontsize=9, fontweight='bold', color='#FF9800',
                        arrowprops=dict(arrowstyle='->', color='#FF9800', lw=2))
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
    focus_start = max(0, entry_bar_idx - 20)
    focus_end = min(len(session_bars), (stop_idx or exit_opp_fvg_idx or exit_8r_idx or entry_bar_idx) + 40)
    ax.set_xlim(focus_start, focus_end)

    # Y-axis range
    if is_long:
        y_min = stop_price - 3
        y_max = max(target_8r, exit_opp_fvg_price or target_8r) + 3
    else:
        y_min = min(target_8r, exit_opp_fvg_price or target_8r) - 3
        y_max = stop_price + 3
    ax.set_ylim(y_min, y_max)

    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Price', fontsize=12)
    ax.set_title(f'{symbol} 3-Minute | {trade_date} | {direction} Trade | 3 Contracts | Opposing FVG Runner\n'
                 f'Result: {result_str} | P/L: ${total_dollars:+,.2f} | Risk: {risk:.2f} pts',
                 fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Add summary box
    runner_exit = 'Opposing FVG' if exit_opp_fvg_idx and exit_opp_fvg_idx < len(session_bars) - 1 else 'EOD'
    summary = (f'TRADE SUMMARY\n'
               f'Direction: {direction}\n'
               f'Entry: {entry_price:.2f}\n'
               f'Stop: {stop_price:.2f}\n'
               f'Risk: {risk:.2f} pts\n'
               f'---------------\n'
               f'4R Target: {target_4r:.2f}\n'
               f'8R Target: {target_8r:.2f}\n'
               f'Runner Exit: {runner_exit}\n'
               f'---------------\n'
               f'Result: {result_str}\n'
               f'P/L: ${total_dollars:+,.2f}')

    box_color = '#FFCDD2' if total_dollars < 0 else '#C8E6C9'
    edge_color = '#F44336' if total_dollars < 0 else '#4CAF50'
    props = dict(boxstyle='round', facecolor=box_color, alpha=0.9, edgecolor=edge_color, linewidth=2)
    ax.text(0.98, 0.98, summary, transform=ax.transAxes, fontsize=11,
            verticalalignment='top', horizontalalignment='right',
            fontweight='bold', bbox=props, family='monospace')

    plt.tight_layout()
    filename = f'backtest_{symbol}_{trade_date}_{direction}_opp_fvg.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f'Saved: {filename}')
    plt.close()

    return filename


if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 3:
        year, month, day = map(int, sys.argv[1].split('-'))
        trade_date = date(year, month, day)
        direction = sys.argv[2]
    else:
        trade_date = date(2026, 1, 21)
        direction = 'LONG'
    plot_trade(trade_date, direction)
