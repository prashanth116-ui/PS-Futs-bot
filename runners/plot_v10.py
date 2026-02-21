"""
Plot today's trades with V10.11 Quad Entry Mode.

V10.7 Entry Types:
- Type A (Creation): Enter when FVG forms with displacement
- Type B1 (Overnight Retrace): Enter when price retraces into overnight FVG (ADX >= 22)
- Type B2 (Intraday Retrace): Enter when price retraces into session FVG
- Type C (BOS + Retrace): Per-symbol control with daily loss limit

V10.7 BOS Settings:
- ES/MES: BOS disabled (20% win rate)
- NQ/MNQ: BOS enabled with 1 loss/day limit
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10
from runners.run_v10_equity import run_session_v10_equity


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


def plot_v10(symbol='ES', contracts=3, retracement_morning_only=True, interval='3m', risk_per_trade=50, losses_only=False):
    """Plot today's trades with V10.7 Quad Entry strategy. Supports futures and equities."""

    is_equity = symbol.upper() in ['SPY', 'QQQ']

    if is_equity:
        tick_size = 0.01
        tick_value = 1.0
    else:
        tick_size = 0.25
        tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25 if symbol == 'MES' else 0.50
    min_risk_pts = 1.5 if symbol in ['ES', 'MES'] else 6.0 if symbol in ['NQ', 'MNQ'] else 1.5
    max_bos_risk = 8.0 if symbol in ['ES', 'MES'] else 20.0 if symbol in ['NQ', 'MNQ'] else 8.0
    max_retrace_risk = 8.0 if symbol in ['ES', 'MES'] else None
    # V10.7: ES/MES BOS disabled, NQ/MNQ BOS enabled with loss limit
    disable_bos = symbol in ['ES', 'MES']

    print(f'Fetching {symbol} {interval} data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval=interval, n_bars=3000 if is_equity else 1000)

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

    # Print RTH key levels (safeguard against misreading chart)
    rth_bars = [b for b in session_bars if b.timestamp.time() >= dt_time(9, 30)]
    if rth_bars:
        rth_open = rth_bars[0].open
        rth_high = max(b.high for b in rth_bars)
        rth_low = min(b.low for b in rth_bars)
        rth_close = rth_bars[-1].close
        print(f'RTH: Open={rth_open:.2f} High={rth_high:.2f} Low={rth_low:.2f} Close={rth_close:.2f}')

    if len(session_bars) < 50:
        print('Not enough bars')
        return

    if is_equity:
        all_results = run_session_v10_equity(
            session_bars,
            all_bars,
            symbol=symbol,
            risk_per_trade=risk_per_trade,
            t1_fixed_4r=True,
            overnight_retrace_min_adx=22,
        )
    else:
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
            t1_fixed_4r=True,
            overnight_retrace_min_adx=22,
            midday_cutoff=True,
            pm_cutoff_nq=True,
            symbol=symbol,
            max_bos_risk_pts=max_bos_risk,
            high_displacement_override=3.0,
            disable_bos_retrace=disable_bos,
            bos_daily_loss_limit=1,
            max_retrace_risk_pts=max_retrace_risk,  # V10.11: Reduce retrace cts if high risk
        )

    if losses_only:
        all_results = [r for r in all_results if r['total_dollars'] < 0]

    if not all_results:
        print('No trades found')
        return

    # Calculate EMAs for display
    closes = [b.close for b in session_bars]
    ema_20 = calculate_ema(closes, 20)
    ema_50 = calculate_ema(closes, 50)

    # Create figure with space for trade table below chart
    fig = plt.figure(figsize=(22, 16))
    ax = fig.add_axes([0.05, 0.28, 0.90, 0.65])  # left, bottom, width, height

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
        if result.get('is_reentry') or result.get('is_2nd_entry'):
            trade_label += ' [2nd]'

        entry_price = result['entry_price']
        stop_price = result['stop_price']
        risk = result.get('risk', abs(entry_price - stop_price))
        target_4r = result.get('target_4r', entry_price + 3 * risk if is_long else entry_price - 3 * risk)
        target_8r = result.get('target_8r', entry_price + 6 * risk if is_long else entry_price - 6 * risk)

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
                        'qty': exit.get('cts') or exit.get('shares', 0),
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
        y_offset = (1 if is_equity else 8) if is_long else (-1 if is_equity else -8)
        ax.annotate(f'{trade_label}\n{entry_time.strftime("%H:%M")}\n{entry_price:.2f}',
                    xy=(entry_bar_idx, entry_price),
                    xytext=(entry_bar_idx - 5, entry_price + y_offset),
                    fontsize=9, fontweight='bold', color=color,
                    bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor=color))

        # Mark each exit point
        exit_marker = 'v' if is_long else '^'
        for e_idx, ed in enumerate(exit_data):
            ec = exit_colors.get(ed['type'], '#4CAF50')
            dollars = ed['pnl'] if is_equity else (ed['pnl'] / tick_size) * tick_value
            ax.scatter([ed['bar_idx']], [ed['price']], color=ec, s=150, zorder=5,
                       marker=exit_marker, edgecolors='black', linewidths=1.5)

            unit = 'sh' if is_equity else 'ct'
            x_offset = 2 + (e_idx * 3)
            ax.annotate(f"{ed['type']}\n{ed['qty']}{unit} @ {ed['price']:.2f}\n${dollars:+,.0f}",
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
        y_pad = 2 if is_equity else 15
        y_min = min(all_prices) - y_pad
        y_max = max(all_prices) + y_pad
        ax.set_ylim(y_min, y_max)

    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Price', fontsize=12)

    # Count entry types
    creation_count = sum(1 for r in all_results if r['entry_type'] == 'CREATION')
    overnight_count = sum(1 for r in all_results if r['entry_type'] == 'RETRACEMENT')
    intraday_count = sum(1 for r in all_results if r['entry_type'] == 'INTRADAY_RETRACE')
    bos_count = sum(1 for r in all_results if r['entry_type'] == 'BOS_RETRACE')

    result_str = 'WIN' if total_pnl > 0 else 'LOSS' if total_pnl < 0 else 'BE'
    bos_status = "OFF" if disable_bos else "ON (1 loss limit)"
    ax.set_title(f'{symbol} 3-Minute | {today} | V10.11 Quad Entry Mode\n'
                 f'Trades: {len(all_results)} ({creation_count} Creation, {overnight_count} Overnight, {intraday_count} Intraday, {bos_count} BOS) | BOS: {bos_status}\n'
                 f'Result: {result_str} | Total P/L: ${total_pnl:+,.2f}',
                 fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Add trade summary table below chart
    table_ax = fig.add_axes([0.05, 0.02, 0.90, 0.22])  # left, bottom, width, height
    table_ax.axis('off')

    col_labels = ['#', 'Dir', 'Type', 'Entry', 'Time', 'Risk', 'Exits', 'Result', 'P/L']
    table_data = []
    for t_idx, result in enumerate(all_results):
        direction = result['direction']
        entry_type = result['entry_type'].replace('_RETRACE', '').replace('RETRACEMENT', 'OVERNIGHT')
        entry_time = result['entry_time'].strftime('%H:%M')
        res_str = 'WIN' if result['total_dollars'] > 0 else 'LOSS' if result['total_dollars'] < 0 else 'BE'
        reentry = ' (2nd)' if (result.get('is_reentry') or result.get('is_2nd_entry')) else ''

        exit_parts = []
        for ex in result['exits']:
            dollars = ex['pnl'] if is_equity else (ex['pnl'] / tick_size) * tick_value
            unit = 'sh' if is_equity else 'ct'
            qty = ex.get('cts') or ex.get('shares', 0)
            exit_parts.append(f"{ex['type'].replace('_PARTIAL','').replace('_STRUCT','').replace('_STOP','')}: {qty}{unit} ${dollars:+,.0f}")
        exits_str = ' | '.join(exit_parts)

        table_data.append([
            str(t_idx + 1),
            direction,
            entry_type + reentry,
            f"{result['entry_price']:.2f}",
            entry_time,
            f"{result['risk']:.2f}",
            exits_str,
            res_str,
            f"${result['total_dollars']:+,.2f}",
        ])

    # Add total row
    table_data.append(['', '', '', '', '', '', '', 'TOTAL', f'${total_pnl:+,.2f}'])

    table = table_ax.table(cellText=table_data, colLabels=col_labels,
                           loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.3)

    # Style header
    for j, label in enumerate(col_labels):
        table[0, j].set_facecolor('#1976D2')
        table[0, j].set_text_props(color='white', fontweight='bold')

    # Style rows
    for i, result in enumerate(all_results):
        row = i + 1
        bg = '#C8E6C9' if result['total_dollars'] > 0 else '#FFCDD2' if result['total_dollars'] < 0 else '#FFF9C4'
        for j in range(len(col_labels)):
            table[row, j].set_facecolor(bg)

    # Style total row
    total_row = len(table_data)
    total_bg = '#C8E6C9' if total_pnl > 0 else '#FFCDD2' if total_pnl < 0 else '#FFF9C4'
    for j in range(len(col_labels)):
        table[total_row, j].set_facecolor(total_bg)
        table[total_row, j].set_text_props(fontweight='bold')

    # Add RTH key levels box (bottom left) - prevents misreading chart
    rth_bars = [b for b in session_bars if b.timestamp.time() >= dt_time(9, 30)]
    if rth_bars:
        rth_info = (
            f"RTH KEY LEVELS\n"
            f"Open:  {rth_bars[0].open:.2f}\n"
            f"High:  {max(b.high for b in rth_bars):.2f}\n"
            f"Low:   {min(b.low for b in rth_bars):.2f}\n"
            f"Close: {rth_bars[-1].close:.2f}"
        )
        rth_props = dict(boxstyle='round', facecolor='#E3F2FD', alpha=0.95, edgecolor='#1976D2', linewidth=2)
        ax.text(0.02, 0.02, rth_info, transform=ax.transAxes, fontsize=10,
                verticalalignment='bottom', horizontalalignment='left',
                fontweight='bold', bbox=rth_props, family='monospace')

    filename = f'backtest_{symbol}_V10.11_{today}.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f'Saved: {filename}')
    plt.close()

    return filename


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    contracts = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    interval = sys.argv[3] if len(sys.argv) > 3 else '3m'
    risk = int(sys.argv[4]) if len(sys.argv) > 4 else 50
    losses = '--losses' in sys.argv
    plot_v10(symbol=symbol, contracts=contracts, interval=interval, risk_per_trade=risk, losses_only=losses)
