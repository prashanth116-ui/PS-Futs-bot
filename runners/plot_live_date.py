"""Plot LIVE BOT trades on candlestick chart for a specific date.

Uses trade data extracted from live bot logs (not backtest engine).
"""
import sys
sys.path.insert(0, '.')

from version import STRATEGY_VERSION
from datetime import date, time as dt_time, datetime
from runners.tradingview_loader import fetch_futures_bars
import matplotlib.pyplot as plt


def plot_live_trades(symbol, target_date, trades, tick_size=0.25, tick_value=12.50):
    """Plot live bot trades on candlestick chart.

    trades: list of dicts with keys:
        direction, entry_type, entry_price, entry_time (HH:MM string),
        stop_price, contracts, total_dollars,
        exits: list of {time (HH:MM), price, type, cts, dollars}
    """
    print(f'Fetching {symbol} 3m data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=2000)

    target_bars = [b for b in all_bars if b.timestamp.date() == target_date]
    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in target_bars if premarket_start <= b.timestamp.time() <= rth_end]

    print(f'Date: {target_date}')
    print(f'Session bars: {len(session_bars)}')

    if len(session_bars) < 50:
        print('Not enough bars')
        return

    # Build time->index lookup
    time_to_idx = {}
    for i, bar in enumerate(session_bars):
        t_str = bar.timestamp.strftime('%H:%M')
        time_to_idx[t_str] = i

    def find_bar_idx(time_str):
        """Find closest bar index for a HH:MM time string."""
        if time_str in time_to_idx:
            return time_to_idx[time_str]
        # Find closest
        target_mins = int(time_str[:2]) * 60 + int(time_str[3:])
        best_idx = 0
        best_diff = 9999
        for i, bar in enumerate(session_bars):
            bar_mins = bar.timestamp.hour * 60 + bar.timestamp.minute
            diff = abs(bar_mins - target_mins)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        return best_idx

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

    # Create figure
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
    exit_colors = {'T1': '#4CAF50', 'T2': '#2196F3', 'RUNNER': '#9C27B0', 'TRAIL': '#FF9800', 'OPP_FVG': '#FF9800', 'STOP': '#F44336', 'EOD': '#607D8B'}

    total_pnl = 0
    all_indices = []
    all_prices = []

    for result in trades:
        entry_type = result['entry_type']
        color = entry_colors.get(entry_type, '#2196F3')
        direction = result['direction']
        is_long = direction == 'LONG'

        entry_price = result['entry_price']
        entry_bar_idx = find_bar_idx(result['entry_time'])

        stop_price = result['stop_price']
        risk = abs(entry_price - stop_price)

        # Calculate R targets
        if is_long:
            target_4r = entry_price + risk * 4
            target_8r = entry_price + risk * 8
        else:
            target_4r = entry_price - risk * 4
            target_8r = entry_price - risk * 8

        exit_data = []
        last_exit_bar_idx = entry_bar_idx
        for ex in result['exits']:
            ex_idx = find_bar_idx(ex['time'])
            exit_data.append({
                'bar_idx': ex_idx,
                'price': ex['price'],
                'type': ex['type'],
                'cts': ex['cts'],
                'dollars': ex['dollars'],
            })
            last_exit_bar_idx = max(last_exit_bar_idx, ex_idx)

        all_indices.extend([entry_bar_idx, last_exit_bar_idx])
        all_prices.extend([entry_price, stop_price, target_4r])
        for ed in exit_data:
            all_prices.append(ed['price'])

        # Entry/stop/target lines
        line_end = min(len(session_bars), last_exit_bar_idx + 10)
        ax.hlines(entry_price, entry_bar_idx, line_end, colors=color, linestyles='-', linewidth=2, alpha=0.8)
        ax.hlines(stop_price, entry_bar_idx, line_end, colors='#F44336', linestyles='--', linewidth=1.5, alpha=0.6)
        ax.hlines(target_4r, entry_bar_idx, line_end, colors='#4CAF50', linestyles=':', linewidth=1.5, alpha=0.6)

        # Entry marker
        entry_marker = '^' if is_long else 'v'
        ax.scatter([entry_bar_idx], [entry_price], color=color, s=200, zorder=5, marker=entry_marker, edgecolors='black', linewidths=2)

        trade_label = f"{direction} [{entry_type}]"
        y_offset = 8 if is_long else -8
        ax.annotate(f'{trade_label}\n{result["entry_time"]}\n{entry_price:.2f}',
                     xy=(entry_bar_idx, entry_price),
                     xytext=(entry_bar_idx - 5, entry_price + y_offset),
                     fontsize=8, fontweight='bold', color=color,
                     bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor=color))

        # Exit markers
        exit_marker = 'v' if is_long else '^'
        for e_idx, ed in enumerate(exit_data):
            ec = exit_colors.get(ed['type'], '#4CAF50')
            ax.scatter([ed['bar_idx']], [ed['price']], color=ec, s=150, zorder=5, marker=exit_marker, edgecolors='black', linewidths=1.5)
            x_offset = 2 + (e_idx * 3)
            ax.annotate(f"{ed['type']}\n{ed['cts']}ct @ {ed['price']:.2f}\n${ed['dollars']:+,.0f}",
                         xy=(ed['bar_idx'], ed['price']),
                         xytext=(ed['bar_idx'] + x_offset, ed['price']),
                         fontsize=7, fontweight='bold', color=ec,
                         bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor=ec))

        total_pnl += result['total_dollars']

    # X-axis time labels
    tick_indices = list(range(0, len(session_bars), 20))
    tick_labels = [session_bars[i].timestamp.strftime('%H:%M') for i in tick_indices]
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(tick_labels, rotation=45)

    if all_indices:
        ax.set_xlim(max(0, min(all_indices) - 10), min(len(session_bars), max(all_indices) + 30))
    if all_prices:
        ax.set_ylim(min(all_prices) - 15, max(all_prices) + 15)

    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Price', fontsize=12)

    creation_count = sum(1 for t in trades if t['entry_type'] == 'CREATION')
    intraday_count = sum(1 for t in trades if t['entry_type'] == 'INTRADAY_RETRACE')

    result_str = 'WIN' if total_pnl > 0 else 'LOSS' if total_pnl < 0 else 'BE'
    ax.set_title(f'{symbol} 3-Minute | {target_date} | LIVE BOT ({STRATEGY_VERSION})\n'
                 f'Trades: {len(trades)} ({creation_count} Creation, {intraday_count} Intraday) | '
                 f'Result: {result_str} | Total P/L: ${total_pnl:+,.2f}', fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Trade summary table
    table_ax = fig.add_axes([0.05, 0.02, 0.90, 0.22])
    table_ax.axis('off')

    col_labels = ['#', 'Dir', 'Type', 'Entry', 'Time', 'Cts', 'Risk', 'Exits', 'Result', 'P/L']
    table_data = []
    for t_idx, t in enumerate(trades):
        res_str = 'WIN' if t['total_dollars'] > 0 else 'LOSS' if t['total_dollars'] < 0 else 'BE'
        entry_type_short = t['entry_type'].replace('_RETRACE', '').replace('RETRACEMENT', 'OVERNIGHT')

        exit_parts = []
        for ex in t['exits']:
            exit_parts.append(f"{ex['type']}: {ex['cts']}ct ${ex['dollars']:+,.0f}")
        exits_str = ' | '.join(exit_parts)

        risk = abs(t['entry_price'] - t['stop_price'])
        table_data.append([
            str(t_idx + 1), t['direction'], entry_type_short,
            f"{t['entry_price']:.2f}", t['entry_time'], str(t['contracts']),
            f"{risk:.2f}", exits_str, res_str, f"${t['total_dollars']:+,.2f}",
        ])

    table_data.append(['', '', '', '', '', '', '', '', 'TOTAL', f'${total_pnl:+,.2f}'])

    table = table_ax.table(cellText=table_data, colLabels=col_labels, loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(7)
    table.scale(1, 1.3)

    for j in range(len(col_labels)):
        table[0, j].set_facecolor('#1976D2')
        table[0, j].set_text_props(color='white', fontweight='bold')

    for i, t in enumerate(trades):
        row = i + 1
        bg = '#C8E6C9' if t['total_dollars'] > 0 else '#FFCDD2' if t['total_dollars'] < 0 else '#FFF9C4'
        for j in range(len(col_labels)):
            table[row, j].set_facecolor(bg)

    total_row = len(table_data)
    total_bg = '#C8E6C9' if total_pnl > 0 else '#FFCDD2'
    for j in range(len(col_labels)):
        table[total_row, j].set_facecolor(total_bg)
        table[total_row, j].set_text_props(fontweight='bold')

    filename = f'livebot_{symbol}_{STRATEGY_VERSION}_{target_date}.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f'Saved: {filename}')
    plt.close()
    return filename


# ── Mar 6, 2026 Live Bot Trades (ES) ─────────────────────────────────
MAR6_ES_TRADES = [
    {
        'direction': 'SHORT', 'entry_type': 'CREATION', 'contracts': 3,
        'entry_price': 6829.00, 'entry_time': '04:12', 'stop_price': 6830.75,
        'total_dollars': 1612.50,
        'exits': [
            {'time': '04:18', 'price': 6823.75, 'type': 'T1', 'cts': 1, 'dollars': 262.50},
            {'time': '04:18', 'price': 6820.25, 'type': 'T2', 'cts': 1, 'dollars': 437.50},
            {'time': '05:06', 'price': 6810.75, 'type': 'RUNNER', 'cts': 1, 'dollars': 912.50},
        ],
    },
    {
        'direction': 'SHORT', 'entry_type': 'CREATION', 'contracts': 3,
        'entry_price': 6824.00, 'entry_time': '04:18', 'stop_price': 6826.50,
        'total_dollars': 1662.50,
        'exits': [
            {'time': '04:27', 'price': 6816.50, 'type': 'T1', 'cts': 1, 'dollars': 375.00},
            {'time': '04:36', 'price': 6811.50, 'type': 'T2', 'cts': 1, 'dollars': 625.00},
            {'time': '05:06', 'price': 6810.75, 'type': 'RUNNER', 'cts': 1, 'dollars': 662.50},
        ],
    },
    {
        'direction': 'SHORT', 'entry_type': 'CREATION', 'contracts': 3,
        'entry_price': 6812.38, 'entry_time': '06:06', 'stop_price': 6815.25,
        'total_dollars': 431.25,
        'exits': [
            {'time': '06:06', 'price': 6803.75, 'type': 'T1', 'cts': 1, 'dollars': 431.25},
            {'time': '06:15', 'price': 6812.38, 'type': 'TRAIL', 'cts': 2, 'dollars': 0.00},
        ],
    },
    {
        'direction': 'SHORT', 'entry_type': 'CREATION', 'contracts': 2,
        'entry_price': 6806.88, 'entry_time': '06:06', 'stop_price': 6810.00,
        'total_dollars': -312.50,
        'exits': [
            {'time': '06:12', 'price': 6810.00, 'type': 'STOP', 'cts': 2, 'dollars': -312.50},
        ],
    },
    {
        'direction': 'SHORT', 'entry_type': 'CREATION', 'contracts': 3,
        'entry_price': 6812.88, 'entry_time': '06:33', 'stop_price': 6814.50,
        'total_dollars': 1656.25,
        'exits': [
            {'time': '06:36', 'price': 6808.00, 'type': 'T1', 'cts': 1, 'dollars': 243.75},
            {'time': '06:42', 'price': 6804.75, 'type': 'T2', 'cts': 1, 'dollars': 406.25},
            {'time': '08:03', 'price': 6792.75, 'type': 'OPP_FVG', 'cts': 1, 'dollars': 1006.25},
        ],
    },
    {
        'direction': 'SHORT', 'entry_type': 'CREATION', 'contracts': 2,
        'entry_price': 6809.88, 'entry_time': '06:36', 'stop_price': 6812.00,
        'total_dollars': 850.00,
        'exits': [
            {'time': '06:42', 'price': 6803.50, 'type': 'T1', 'cts': 1, 'dollars': 318.75},
            {'time': '06:42', 'price': 6799.25, 'type': 'T2', 'cts': 1, 'dollars': 531.25},
        ],
    },
    {
        'direction': 'SHORT', 'entry_type': 'CREATION', 'contracts': 3,
        'entry_price': 6794.00, 'entry_time': '07:33', 'stop_price': 6795.50,
        'total_dollars': 225.00,
        'exits': [
            {'time': '07:36', 'price': 6789.50, 'type': 'T1', 'cts': 1, 'dollars': 225.00},
            {'time': '07:42', 'price': 6794.00, 'type': 'TRAIL', 'cts': 2, 'dollars': 0.00},
        ],
    },
    {
        'direction': 'SHORT', 'entry_type': 'CREATION', 'contracts': 3,
        'entry_price': 6787.62, 'entry_time': '07:48', 'stop_price': 6790.50,
        'total_dollars': -431.25,
        'exits': [
            {'time': '08:03', 'price': 6790.50, 'type': 'STOP', 'cts': 3, 'dollars': -431.25},
        ],
    },
    {
        'direction': 'SHORT', 'entry_type': 'CREATION', 'contracts': 3,
        'entry_price': 6791.62, 'entry_time': '08:33', 'stop_price': 6796.50,
        'total_dollars': 3956.25,
        'exits': [
            {'time': '08:39', 'price': 6777.00, 'type': 'T1', 'cts': 1, 'dollars': 731.25},
            {'time': '08:42', 'price': 6767.25, 'type': 'T2', 'cts': 1, 'dollars': 1218.75},
            {'time': '09:30', 'price': 6751.50, 'type': 'RUNNER', 'cts': 1, 'dollars': 2006.25},
        ],
    },
    {
        'direction': 'SHORT', 'entry_type': 'CREATION', 'contracts': 3,
        'entry_price': 6773.00, 'entry_time': '08:42', 'stop_price': 6777.25,
        'total_dollars': 2775.00,
        'exits': [
            {'time': '08:45', 'price': 6760.25, 'type': 'T1', 'cts': 1, 'dollars': 637.50},
            {'time': '08:48', 'price': 6751.50, 'type': 'T2', 'cts': 1, 'dollars': 1062.50},
            {'time': '09:30', 'price': 6751.50, 'type': 'RUNNER', 'cts': 1, 'dollars': 1075.00},
        ],
    },
    {
        'direction': 'SHORT', 'entry_type': 'CREATION', 'contracts': 3,
        'entry_price': 6734.00, 'entry_time': '09:36', 'stop_price': 6739.00,
        'total_dollars': -750.00,
        'exits': [
            {'time': '10:03', 'price': 6739.00, 'type': 'STOP', 'cts': 3, 'dollars': -750.00},
        ],
    },
    {
        'direction': 'SHORT', 'entry_type': 'INTRADAY_RETRACE', 'contracts': 1,
        'entry_price': 6728.00, 'entry_time': '09:45', 'stop_price': 6740.75,
        'total_dollars': -1275.00,
        'exits': [
            {'time': '10:03', 'price': 6740.75, 'type': 'STOP', 'cts': 1, 'dollars': -1275.00},
        ],
    },
    {
        'direction': 'LONG', 'entry_type': 'CREATION', 'contracts': 3,
        'entry_price': 6762.62, 'entry_time': '10:33', 'stop_price': 6760.50,
        'total_dollars': 1168.75,
        'exits': [
            {'time': '10:36', 'price': 6769.00, 'type': 'T1', 'cts': 1, 'dollars': 318.75},
            {'time': '10:39', 'price': 6773.25, 'type': 'T2', 'cts': 1, 'dollars': 531.25},
            {'time': '10:42', 'price': 6769.00, 'type': 'RUNNER', 'cts': 1, 'dollars': 318.75},
        ],
    },
    {
        'direction': 'LONG', 'entry_type': 'INTRADAY_RETRACE', 'contracts': 3,
        'entry_price': 6765.75, 'entry_time': '10:45', 'stop_price': 6759.75,
        'total_dollars': -900.00,
        'exits': [
            {'time': '10:48', 'price': 6759.75, 'type': 'STOP', 'cts': 3, 'dollars': -900.00},
        ],
    },
    {
        'direction': 'SHORT', 'entry_type': 'CREATION', 'contracts': 3,
        'entry_price': 6753.00, 'entry_time': '10:51', 'stop_price': 6758.25,
        'total_dollars': -787.50,
        'exits': [
            {'time': '10:57', 'price': 6758.25, 'type': 'STOP', 'cts': 3, 'dollars': -787.50},
        ],
    },
    {
        'direction': 'LONG', 'entry_type': 'CREATION', 'contracts': 3,
        'entry_price': 6757.88, 'entry_time': '11:00', 'stop_price': 6749.50,
        'total_dollars': -1256.25,
        'exits': [
            {'time': '12:39', 'price': 6749.50, 'type': 'STOP', 'cts': 3, 'dollars': -1256.25},
        ],
    },
    {
        'direction': 'LONG', 'entry_type': 'INTRADAY_RETRACE', 'contracts': 2,
        'entry_price': 6766.25, 'entry_time': '11:42', 'stop_price': 6763.25,
        'total_dollars': -300.00,
        'exits': [
            {'time': '11:45', 'price': 6763.25, 'type': 'STOP', 'cts': 2, 'dollars': -300.00},
        ],
    },
]


if __name__ == '__main__':
    target = date(2026, 3, 6)
    plot_live_trades('ES', target, MAR6_ES_TRADES)
