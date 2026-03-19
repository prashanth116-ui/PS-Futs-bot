"""Plot V10.16 strategy for a specific date."""
import sys
sys.path.insert(0, '.')

from version import STRATEGY_VERSION

from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10
from runners.symbol_defaults import get_symbol_config, get_session_v10_kwargs
import matplotlib.pyplot as plt


def plot_v10_date(symbol, target_date, contracts=3):
    cfg = get_symbol_config(symbol)
    tick_size = cfg['tick_size']
    tick_value = cfg['tick_value']
    disable_bos = cfg['disable_bos']

    print(f'Fetching {symbol} 3m data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=2000)

    # Filter for target date
    target_bars = [b for b in all_bars if b.timestamp.date() == target_date]

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in target_bars if premarket_start <= b.timestamp.time() <= rth_end]

    print(f'Date: {target_date}')
    print(f'Session bars: {len(session_bars)}')

    if len(session_bars) < 50:
        print('Not enough bars')
        return

    # Run V10.16 with Hybrid exit using centralized config
    kwargs = get_session_v10_kwargs(symbol)
    kwargs['contracts'] = contracts
    kwargs['retracement_morning_only'] = True

    all_results = run_session_v10(
        session_bars,
        all_bars,
        **kwargs,
    )

    if not all_results:
        print('No trades found')
        return

    # Calculate EMAs
    closes = [b.close for b in session_bars]
    def calc_ema(data, period):
        ema = []
        mult = 2 / (period + 1)
        for i, c in enumerate(data):
            if i < period - 1:
                ema.append(None)
            elif i == period - 1:
                ema.append(sum(data[:period]) / period)
            else:
                ema.append((c * mult) + (ema[-1] * (1 - mult)))
        return ema

    ema_20 = calc_ema(closes, 20)
    ema_50 = calc_ema(closes, 50)

    # Create figure with space for trade table below chart
    fig = plt.figure(figsize=(22, 16))
    ax = fig.add_axes([0.05, 0.28, 0.90, 0.65])

    # Plot candlesticks
    for i, bar in enumerate(session_bars):
        color = '#4CAF50' if bar.close >= bar.open else '#F44336'
        ax.plot([i, i], [bar.low, bar.high], color=color, linewidth=1)
        body_bottom = min(bar.open, bar.close)
        body_height = abs(bar.close - bar.open)
        rect = plt.Rectangle((i - 0.3, body_bottom), 0.6, body_height, facecolor=color, edgecolor=color)
        ax.add_patch(rect)

    # Plot EMAs
    ema_x_20 = [i for i, e in enumerate(ema_20) if e]
    ema_y_20 = [e for e in ema_20 if e]
    ax.plot(ema_x_20, ema_y_20, color='#2196F3', linewidth=1.5, label='EMA 20', alpha=0.7)
    ema_x_50 = [i for i, e in enumerate(ema_50) if e]
    ema_y_50 = [e for e in ema_50 if e]
    ax.plot(ema_x_50, ema_y_50, color='#9C27B0', linewidth=2, label='EMA 50', alpha=0.8)

    entry_colors = {'CREATION': '#2196F3', 'RETRACEMENT': '#FF9800', 'INTRADAY_RETRACE': '#4CAF50', 'BOS_RETRACE': '#9C27B0'}
    exit_colors = {'4R_PARTIAL': '#4CAF50', 'T1_STRUCT': '#4CAF50', 'T2_STRUCT': '#2196F3', 'RUNNER_STOP': '#9C27B0', 'TRAIL_STOP': '#FF9800', 'STOP': '#F44336', 'EOD': '#607D8B'}

    total_pnl = 0
    all_indices = []
    all_prices = []

    for result in all_results:
        entry_type = result['entry_type']
        color = entry_colors.get(entry_type, '#2196F3')
        direction = result['direction']
        is_long = direction == 'LONG'

        entry_price = result['entry_price']
        entry_time = result['entry_time']

        entry_bar_idx = None
        for i, bar in enumerate(session_bars):
            if bar.timestamp == entry_time:
                entry_bar_idx = i
                break
        if entry_bar_idx is None:
            continue

        exit_data = []
        last_exit_bar_idx = entry_bar_idx
        for exit in result['exits']:
            for i, bar in enumerate(session_bars):
                if bar.timestamp == exit['time']:
                    exit_data.append({'bar_idx': i, 'price': exit['price'], 'type': exit['type'], 'cts': exit['cts'], 'pnl': exit['pnl']})
                    last_exit_bar_idx = max(last_exit_bar_idx, i)
                    break

        all_indices.extend([entry_bar_idx, last_exit_bar_idx])
        all_prices.extend([entry_price, result['stop_price'], result['target_4r'], result['target_8r']])
        for ed in exit_data:
            all_prices.append(ed['price'])

        # FVG zone
        fvg_rect = plt.Rectangle((entry_bar_idx - 0.5, result['fvg_low']), last_exit_bar_idx - entry_bar_idx + 10, result['fvg_high'] - result['fvg_low'], facecolor=color, alpha=0.15, edgecolor=color, linewidth=2)
        ax.add_patch(fvg_rect)

        line_end = min(len(session_bars), last_exit_bar_idx + 20)
        ax.hlines(entry_price, entry_bar_idx, line_end, colors=color, linestyles='-', linewidth=2, alpha=0.8)
        ax.hlines(result['stop_price'], entry_bar_idx, line_end, colors='#F44336', linestyles='--', linewidth=1.5, alpha=0.6)
        ax.hlines(result['target_4r'], entry_bar_idx, line_end, colors='#4CAF50', linestyles=':', linewidth=1.5, alpha=0.6)
        ax.hlines(result['target_8r'], entry_bar_idx, line_end, colors='#2196F3', linestyles=':', linewidth=1.5, alpha=0.6)

        entry_marker = '^' if is_long else 'v'
        ax.scatter([entry_bar_idx], [entry_price], color=color, s=200, zorder=5, marker=entry_marker, edgecolors='black', linewidths=2)

        trade_label = f"{direction} [{entry_type}]"
        if result.get('is_reentry'):
            trade_label += ' [2nd]'
        y_offset = 8 if is_long else -8
        ax.annotate(f'{trade_label}\n{entry_time.strftime("%H:%M")}\n{entry_price:.2f}', xy=(entry_bar_idx, entry_price), xytext=(entry_bar_idx - 5, entry_price + y_offset), fontsize=9, fontweight='bold', color=color, bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor=color))

        exit_marker = 'v' if is_long else '^'
        for e_idx, ed in enumerate(exit_data):
            ec = exit_colors.get(ed['type'], '#4CAF50')
            dollars = (ed['pnl'] / tick_size) * tick_value
            ax.scatter([ed['bar_idx']], [ed['price']], color=ec, s=150, zorder=5, marker=exit_marker, edgecolors='black', linewidths=1.5)
            x_offset = 2 + (e_idx * 3)
            ax.annotate(f"{ed['type']}\n{ed['cts']}ct @ {ed['price']:.2f}\n${dollars:+,.0f}", xy=(ed['bar_idx'], ed['price']), xytext=(ed['bar_idx'] + x_offset, ed['price']), fontsize=8, fontweight='bold', color=ec, bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor=ec))

        total_pnl += result['total_dollars']

    tick_indices = list(range(0, len(session_bars), 20))
    tick_labels = [session_bars[i].timestamp.strftime('%H:%M') for i in tick_indices]
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(tick_labels, rotation=45)

    if all_indices:
        ax.set_xlim(max(0, min(all_indices) - 30), min(len(session_bars), max(all_indices) + 50))
    if all_prices:
        ax.set_ylim(min(all_prices) - 15, max(all_prices) + 15)

    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Price', fontsize=12)

    creation_count = sum(1 for r in all_results if r['entry_type'] == 'CREATION')
    overnight_count = sum(1 for r in all_results if r['entry_type'] == 'RETRACEMENT')
    intraday_count = sum(1 for r in all_results if r['entry_type'] == 'INTRADAY_RETRACE')
    bos_count = sum(1 for r in all_results if r['entry_type'] == 'BOS_RETRACE')

    result_str = 'WIN' if total_pnl > 0 else 'LOSS' if total_pnl < 0 else 'BE'
    bos_status = "OFF" if disable_bos else "ON (1 loss limit)"
    ax.set_title(f'{symbol} 3-Minute | {target_date} | {STRATEGY_VERSION} Quad Entry (Hybrid Exit)\n'
                 f'Trades: {len(all_results)} ({creation_count} Creation, {overnight_count} Overnight, {intraday_count} Intraday, {bos_count} BOS) | BOS: {bos_status}\n'
                 f'Result: {result_str} | Total P/L: ${total_pnl:+,.2f}', fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Trade summary table below chart
    table_ax = fig.add_axes([0.05, 0.02, 0.90, 0.22])
    table_ax.axis('off')

    col_labels = ['#', 'Dir', 'Type', 'Entry', 'Time', 'Risk', 'Exits', 'Result', 'P/L']
    table_data = []
    for t_idx, result in enumerate(all_results):
        direction = result['direction']
        entry_type = result['entry_type'].replace('_RETRACE', '').replace('RETRACEMENT', 'OVERNIGHT')
        entry_time = result['entry_time'].strftime('%H:%M')
        res_str = 'WIN' if result['total_dollars'] > 0 else 'LOSS' if result['total_dollars'] < 0 else 'BE'
        reentry = ' (2nd)' if result.get('is_reentry') else ''

        exit_parts = []
        for ex in result['exits']:
            dollars = (ex['pnl'] / tick_size) * tick_value
            short_type = ex['type'].replace('_PARTIAL', '').replace('_STRUCT', '').replace('_STOP', '').replace('_FIXED', 'F').replace('OPP_FVG', 'OPP')
            exit_parts.append(f"{short_type}:{ex['cts']}ct ${dollars:+,.0f}")
        exits_str = ' | '.join(exit_parts)

        table_data.append([
            str(t_idx + 1), direction, entry_type + reentry,
            f"{result['entry_price']:.2f}", entry_time, f"{result['risk']:.2f}",
            exits_str, res_str, f"${result['total_dollars']:+,.2f}",
        ])

    table_data.append(['', '', '', '', '', '', '', 'TOTAL', f'${total_pnl:+,.2f}'])

    table = table_ax.table(cellText=table_data, colLabels=col_labels, loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.3)

    # Custom column widths: give Exits the most room
    col_widths = [0.03, 0.05, 0.10, 0.07, 0.05, 0.05, 0.35, 0.06, 0.08]
    for i, w in enumerate(col_widths):
        for row_key in range(len(table_data) + 1):
            table[row_key, i].set_width(w)

    for j in range(len(col_labels)):
        table[0, j].set_facecolor('#1976D2')
        table[0, j].set_text_props(color='white', fontweight='bold')

    for i, result in enumerate(all_results):
        row = i + 1
        bg = '#C8E6C9' if result['total_dollars'] > 0 else '#FFCDD2' if result['total_dollars'] < 0 else '#FFF9C4'
        for j in range(len(col_labels)):
            table[row, j].set_facecolor(bg)

    total_row = len(table_data)
    total_bg = '#C8E6C9' if total_pnl > 0 else '#FFCDD2'
    for j in range(len(col_labels)):
        table[total_row, j].set_facecolor(total_bg)
        table[total_row, j].set_text_props(fontweight='bold')
    filename = f'backtest_{symbol}_{STRATEGY_VERSION}_{target_date}.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f'Saved: {filename}')
    plt.close()
    return filename


if __name__ == '__main__':
    # Default to Feb 3, 2026
    year = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
    month = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    day = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    target = date(year, month, day)

    plot_v10_date('ES', target, 3)
    plot_v10_date('NQ', target, 3)
