"""
Plot today's trades with V10 Triple Entry Mode.

V10 Entry Types:
- Type A (Creation): Enter when FVG forms with displacement
- Type B (Overnight Retrace): Enter when price retraces into overnight FVG
- Type C (BOS + Retrace): Enter when price retraces into session FVG after BOS
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10
from strategies.ict.signals.fvg import detect_fvgs


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


def plot_v10(symbol='ES', contracts=3, retracement_morning_only=True):
    """Plot today's trades with V10 Triple Entry strategy."""

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25
    min_risk_pts = 1.5 if symbol == 'ES' else 6.0 if symbol == 'NQ' else 1.5

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

    # Run V10 strategy with all entry types (Hybrid exit: T1 at 4R)
    all_results = run_session_v10(
        session_bars,
        all_bars,
        tick_size=tick_size,
        tick_value=tick_value,
        contracts=contracts,
        min_risk_pts=min_risk_pts,
        enable_creation_entry=True,
        enable_retracement_entry=True,
        enable_bos_entry=True,
        retracement_morning_only=retracement_morning_only,
        t1_fixed_4r=True,  # Hybrid: T1 takes profit at 4R
    )

    if not all_results:
        print('No trades found')
        return

    # Calculate EMAs for display
    closes = [b.close for b in session_bars]
    ema_20 = calculate_ema(closes, 20)
    ema_50 = calculate_ema(closes, 50)

    # Create figure
    fig, ax = plt.subplots(figsize=(22, 14))

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

    # Colors for entry types
    entry_type_colors = {
        'CREATION': '#2196F3',      # Blue
        'RETRACEMENT': '#FF9800',   # Orange (overnight)
        'INTRADAY_RETRACE': '#4CAF50',  # Green (intraday)
        'BOS_RETRACE': '#9C27B0',   # Purple
    }

    exit_colors = {
        '4R_PARTIAL': '#4CAF50',  # Green - guaranteed profit
        'T1_STRUCT': '#4CAF50',
        'T2_STRUCT': '#2196F3',
        'RUNNER_STOP': '#9C27B0',
        'TRAIL_STOP': '#FF9800',
        'STOP': '#F44336',
        'EOD': '#607D8B',
    }

    total_pnl = 0
    all_indices = []
    all_prices = []

    # Plot each trade
    for t_idx, result in enumerate(all_results):
        entry_type = result['entry_type']
        color = entry_type_colors.get(entry_type, '#2196F3')
        direction = result['direction']
        is_long = direction == 'LONG'

        trade_label = f"{direction} [{entry_type}]"
        if result.get('is_reentry'):
            trade_label += ' [2nd]'

        entry_price = result['entry_price']
        stop_price = result['stop_price']
        target_4r = result['target_4r']
        target_8r = result['target_8r']

        # Find entry bar index
        entry_time = result['entry_time']
        entry_bar_idx = None
        for i, bar in enumerate(session_bars):
            if bar.timestamp == entry_time:
                entry_bar_idx = i
                break

        if entry_bar_idx is None:
            for i, bar in enumerate(session_bars):
                if bar.timestamp >= entry_time:
                    entry_bar_idx = i
                    break

        if entry_bar_idx is None:
            continue

        # Find all exit bar indices and prices
        exit_data = []
        last_exit_bar_idx = entry_bar_idx
        for exit in result['exits']:
            exit_time = exit['time']
            for i, bar in enumerate(session_bars):
                if bar.timestamp == exit_time:
                    exit_data.append({
                        'bar_idx': i,
                        'price': exit['price'],
                        'type': exit['type'],
                        'cts': exit['cts'],
                        'pnl': exit['pnl'],
                    })
                    last_exit_bar_idx = max(last_exit_bar_idx, i)
                    break

        all_indices.extend([entry_bar_idx, last_exit_bar_idx])
        all_prices.extend([entry_price, stop_price, target_4r, target_8r])
        for ed in exit_data:
            all_prices.append(ed['price'])

        # Highlight entry FVG
        fvg_low = result['fvg_low']
        fvg_high = result['fvg_high']
        fvg_rect = plt.Rectangle((entry_bar_idx - 0.5, fvg_low),
                                  last_exit_bar_idx - entry_bar_idx + 10,
                                  fvg_high - fvg_low,
                                  facecolor=color, alpha=0.15, edgecolor=color, linewidth=2)
        ax.add_patch(fvg_rect)

        # Plot trade levels
        line_end = min(len(session_bars), last_exit_bar_idx + 20)

        # Entry line
        ax.hlines(entry_price, entry_bar_idx, line_end, colors=color, linestyles='-', linewidth=2, alpha=0.8)

        # Stop line
        ax.hlines(stop_price, entry_bar_idx, line_end, colors='#F44336', linestyles='--', linewidth=1.5, alpha=0.6)

        # Target lines
        ax.hlines(target_4r, entry_bar_idx, line_end, colors='#4CAF50', linestyles=':', linewidth=1.5, alpha=0.6)
        ax.hlines(target_8r, entry_bar_idx, line_end, colors='#2196F3', linestyles=':', linewidth=1.5, alpha=0.6)

        # Mark entry point
        entry_marker = '^' if is_long else 'v'
        ax.scatter([entry_bar_idx], [entry_price], color=color, s=200, zorder=5,
                   marker=entry_marker, edgecolors='black', linewidths=2)

        # Entry annotation
        y_offset = 8 if is_long else -8
        ax.annotate(f'{trade_label}\n{entry_time.strftime("%H:%M")}\n{entry_price:.2f}',
                    xy=(entry_bar_idx, entry_price),
                    xytext=(entry_bar_idx - 5, entry_price + y_offset),
                    fontsize=9, fontweight='bold', color=color,
                    bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor=color))

        # Mark each exit point
        exit_marker = 'v' if is_long else '^'
        for e_idx, ed in enumerate(exit_data):
            ec = exit_colors.get(ed['type'], '#4CAF50')
            dollars = (ed['pnl'] / tick_size) * tick_value
            ax.scatter([ed['bar_idx']], [ed['price']], color=ec, s=150, zorder=5,
                       marker=exit_marker, edgecolors='black', linewidths=1.5)

            x_offset = 2 + (e_idx * 3)
            ax.annotate(f"{ed['type']}\n{ed['cts']}ct @ {ed['price']:.2f}\n${dollars:+,.0f}",
                        xy=(ed['bar_idx'], ed['price']),
                        xytext=(ed['bar_idx'] + x_offset, ed['price']),
                        fontsize=8, fontweight='bold', color=ec,
                        bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor=ec))

        total_pnl += result['total_dollars']

    # X-axis labels
    tick_indices = list(range(0, len(session_bars), 20))
    tick_labels = [session_bars[i].timestamp.strftime('%H:%M') for i in tick_indices]
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(tick_labels, rotation=45)

    # Focus on trade area with padding
    if all_indices:
        focus_start = max(0, min(all_indices) - 30)
        focus_end = min(len(session_bars), max(all_indices) + 50)
        ax.set_xlim(focus_start, focus_end)

    # Y-axis range
    if all_prices:
        y_min = min(all_prices) - 15
        y_max = max(all_prices) + 15
        ax.set_ylim(y_min, y_max)

    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Price', fontsize=12)

    # Count entry types
    creation_count = sum(1 for r in all_results if r['entry_type'] == 'CREATION')
    overnight_count = sum(1 for r in all_results if r['entry_type'] == 'RETRACEMENT')
    intraday_count = sum(1 for r in all_results if r['entry_type'] == 'INTRADAY_RETRACE')
    bos_count = sum(1 for r in all_results if r['entry_type'] == 'BOS_RETRACE')

    result_str = 'WIN' if total_pnl > 0 else 'LOSS' if total_pnl < 0 else 'BE'
    ax.set_title(f'{symbol} 3-Minute | {today} | V10 Quad Entry Mode\n'
                 f'Trades: {len(all_results)} ({creation_count} Creation, {overnight_count} Overnight, {intraday_count} Intraday, {bos_count} BOS) | '
                 f'Result: {result_str} | Total P/L: ${total_pnl:+,.2f}',
                 fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Add summary box
    summary_lines = [
        'V10 QUAD ENTRY',
        f'Symbol: {symbol}',
        f'Trades: {len(all_results)}',
        f'  Creation: {creation_count}',
        f'  Overnight: {overnight_count}',
        f'  Intraday: {intraday_count}',
        f'  BOS: {bos_count}',
        '-' * 20,
    ]

    for t_idx, result in enumerate(all_results):
        entry_type = result['entry_type']
        direction = result['direction']
        entry_time = result['entry_time'].strftime('%H:%M')
        res_str = 'WIN' if result['total_dollars'] > 0 else 'LOSS' if result['total_dollars'] < 0 else 'BE'

        summary_lines.append(f'{direction} [{entry_type}]')
        summary_lines.append(f'  Entry: {result["entry_price"]:.2f} @ {entry_time}')
        summary_lines.append(f'  Risk: {result["risk"]:.2f} pts')
        for exit in result['exits']:
            dollars = (exit['pnl'] / tick_size) * tick_value
            summary_lines.append(f'  {exit["type"]}: {exit["cts"]}ct ${dollars:+,.0f}')
        summary_lines.append(f'  {res_str}: ${result["total_dollars"]:+,.2f}')
        summary_lines.append('')

    summary_lines.append('-' * 20)
    summary_lines.append(f'TOTAL: ${total_pnl:+,.2f}')

    summary = '\n'.join(summary_lines)

    box_color = '#FFCDD2' if total_pnl < 0 else '#C8E6C9'
    edge_color = '#F44336' if total_pnl < 0 else '#4CAF50'
    props = dict(boxstyle='round', facecolor=box_color, alpha=0.9, edgecolor=edge_color, linewidth=2)
    ax.text(0.98, 0.98, summary, transform=ax.transAxes, fontsize=9,
            verticalalignment='top', horizontalalignment='right',
            fontweight='bold', bbox=props, family='monospace')

    plt.tight_layout()
    filename = f'backtest_{symbol}_V10_{today}.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f'Saved: {filename}')
    plt.close()

    return filename


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    contracts = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    plot_v10(symbol=symbol, contracts=contracts)
