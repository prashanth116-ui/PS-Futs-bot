"""Plot V10.7 strategy for a specific date."""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10
import matplotlib.pyplot as plt


def plot_v10_date(symbol, target_date, contracts=3):
    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25 if symbol == 'MES' else 0.50
    min_risk_pts = 1.5 if symbol in ['ES', 'MES'] else 6.0 if symbol in ['NQ', 'MNQ'] else 1.5
    max_bos_risk = 8.0 if symbol in ['ES', 'MES'] else 20.0 if symbol in ['NQ', 'MNQ'] else 8.0
    # V10.7: ES/MES BOS disabled, NQ/MNQ BOS enabled with loss limit
    disable_bos = symbol in ['ES', 'MES']

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

    # Run V10.7 with Hybrid exit
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
        retracement_morning_only=True,
        t1_fixed_4r=True,
        overnight_retrace_min_adx=22,  # V10.1: ADX filter for overnight
        midday_cutoff=True,  # V10.2: No entries 12-14
        pm_cutoff_nq=True,  # V10.2: No NQ after 14:00
        symbol=symbol,
        max_bos_risk_pts=max_bos_risk,  # V10.4: Cap BOS risk
        high_displacement_override=3.0,  # V10.5: 3x displacement skips ADX
        disable_bos_retrace=disable_bos,  # V10.7: Per-symbol BOS control
        bos_daily_loss_limit=1,  # V10.7: Stop BOS after 1 loss/day
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

    # Create figure
    fig, ax = plt.subplots(figsize=(22, 14))

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
    ax.set_title(f'{symbol} 3-Minute | {target_date} | V10.7 Quad Entry (Hybrid Exit)\n'
                 f'Trades: {len(all_results)} ({creation_count} Creation, {overnight_count} Overnight, {intraday_count} Intraday, {bos_count} BOS) | BOS: {bos_status}\n'
                 f'Result: {result_str} | Total P/L: ${total_pnl:+,.2f}', fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Summary box
    summary_lines = ['V10.7 HYBRID EXIT', f'Symbol: {symbol}', f'BOS: {bos_status}', f'Trades: {len(all_results)}', f'  Creation: {creation_count}', f'  Overnight: {overnight_count}', f'  Intraday: {intraday_count}', f'  BOS: {bos_count}', '-' * 20]
    for result in all_results:
        entry_type = result['entry_type']
        direction = result['direction']
        etime = result['entry_time'].strftime('%H:%M')
        res_str = 'WIN' if result['total_dollars'] > 0 else 'LOSS' if result['total_dollars'] < 0 else 'BE'
        summary_lines.append(f'{direction} [{entry_type}]')
        summary_lines.append(f'  Entry: {result["entry_price"]:.2f} @ {etime}')
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
    ax.text(0.98, 0.98, summary, transform=ax.transAxes, fontsize=9, verticalalignment='top', horizontalalignment='right', fontweight='bold', bbox=props, family='monospace')

    plt.tight_layout()
    filename = f'backtest_{symbol}_V10.7_{target_date}.png'
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
