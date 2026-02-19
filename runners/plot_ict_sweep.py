"""
Plot ICT Liquidity Sweep Strategy trades.

Reads cached results from runner to ensure identical P/L.
Run backtest first: python -m runners.run_ict_sweep ES 30

Usage:
    python -m runners.plot_ict_sweep ES 2026 2 12
    python -m runners.plot_ict_sweep ES  # Today
"""
import sys
sys.path.insert(0, '.')

import pickle
from pathlib import Path
import matplotlib.pyplot as plt
from datetime import date
from matplotlib.lines import Line2D

CACHE_DIR = Path('.cache')


def plot_ict_sweep(symbol='ES', year=None, month=None, day=None, contracts=3, zoom_first_trade=False):
    """Plot ICT Sweep strategy for a specific date using cached runner results."""

    # Instrument config
    if symbol in ['ES', 'MES']:
        pass
    elif symbol in ['NQ', 'MNQ']:
        pass
    else:
        pass

    # Determine target date
    if year and month and day:
        target_date = date(year, month, day)
    else:
        target_date = date.today()

    # Load cached day results from runner
    day_cache = CACHE_DIR / f'ict_sweep_{symbol}_{target_date}.pkl'
    if not day_cache.exists():
        print(f'No cached results for {target_date}.')
        print(f'Run backtest first: python -m runners.run_ict_sweep {symbol} 30')
        return

    print(f'Loading cached results from {day_cache}...')
    with open(day_cache, 'rb') as f:
        cached = pickle.load(f)

    day_trades = cached['trades']
    day_ltf = cached['day_ltf']

    print(f'Plotting date: {target_date} (ET)')
    print(f'LTF bars: {len(day_ltf)}, Trades: {len(day_trades)}')

    if not day_ltf:
        print('No bar data for this day')
        return

    # Create plot
    fig, ax = plt.subplots(figsize=(20, 12))

    # Plot candlesticks (use 3m bars for detail)
    for i, bar in enumerate(day_ltf):
        color = '#4CAF50' if bar.close >= bar.open else '#F44336'
        ax.plot([i, i], [bar.low, bar.high], color=color, linewidth=0.8)
        body_bottom = min(bar.open, bar.close)
        body_height = abs(bar.close - bar.open)
        rect = plt.Rectangle((i - 0.3, body_bottom), 0.6, body_height,
                             facecolor=color, edgecolor=color)
        ax.add_patch(rect)

    # Plot trades from runner results
    total_pnl = 0
    for t in day_trades:
        trade = t.get('trade')
        if not trade:
            continue

        pnl = t.get('pnl_dollars', 0)
        total_pnl += pnl
        entry_price = t.get('entry', trade.entry_price)
        exit_price = t.get('exit', entry_price)
        bars_held = t.get('bars_held', 1)

        # Find entry bar index in day_ltf
        entry_idx = None
        for i, bar in enumerate(day_ltf):
            if bar.timestamp >= trade.timestamp:
                entry_idx = i
                break
        if entry_idx is None:
            continue

        exit_idx = min(entry_idx + bars_held, len(day_ltf) - 1)

        is_long = trade.direction in ('LONG', 'BULLISH')
        color = '#2196F3' if is_long else '#FF5722'
        result_color = '#4CAF50' if pnl > 0 else '#F44336'

        # Entry marker
        marker = '^' if is_long else 'v'
        ax.scatter([entry_idx], [trade.entry_price], color=color, s=200, zorder=5,
                   marker=marker, edgecolors='black', linewidths=2)

        # Entry annotation
        y_offset = 5 if is_long else -5
        et_time = trade.timestamp.strftime('%H:%M')
        ax.annotate(f'{trade.direction}\n{et_time} ET\n{trade.entry_price:.2f}',
                    xy=(entry_idx, trade.entry_price),
                    xytext=(entry_idx + 10, trade.entry_price + y_offset),
                    fontsize=8, fontweight='bold', color=color,
                    arrowprops=dict(arrowstyle='->', color=color, lw=1),
                    bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor=color))

        # FVG zone
        fvg = trade.fvg
        fvg_color = '#2196F3' if is_long else '#FF5722'
        fvg_rect = plt.Rectangle((max(0, entry_idx - 10), fvg.bottom),
                                  40, fvg.top - fvg.bottom,
                                  facecolor=fvg_color, alpha=0.2, edgecolor=fvg_color, linewidth=1)
        ax.add_patch(fvg_rect)

        # Sweep level
        sweep = trade.sweep
        ax.hlines(sweep.sweep_price, max(0, entry_idx - 20), min(len(day_ltf)-1, entry_idx + 60),
                 colors=fvg_color, linestyles='--', linewidth=2, alpha=0.8)
        ax.scatter([entry_idx - 5], [sweep.sweep_price], color=fvg_color, s=300,
                  marker='*', zorder=10, edgecolors='black', linewidths=1)
        ax.annotate(f"SWEEP\n{sweep.sweep_price:.2f}",
                   xy=(entry_idx - 5, sweep.sweep_price),
                   xytext=(entry_idx + 15, sweep.sweep_price + 5),
                   fontsize=10, fontweight='bold', color=fvg_color,
                   arrowprops=dict(arrowstyle='->', color=fvg_color, lw=2),
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.9, edgecolor=fvg_color))

        # Trade lines
        line_end = min(len(day_ltf) - 1, exit_idx + 10)
        ax.hlines(trade.entry_price, entry_idx, line_end, colors=color, linestyles='-', linewidth=2, alpha=0.8)
        ax.hlines(trade.stop_price, entry_idx, line_end, colors='#F44336', linestyles='--', linewidth=1.5, alpha=0.6)
        ax.hlines(trade.t2_price, entry_idx, line_end, colors='#4CAF50', linestyles=':', linewidth=1.5, alpha=0.6)

        # Exit markers - per-leg if available, else single marker
        leg_exits = t.get('exits', [])
        if leg_exits:
            leg_markers = {'T1': 'D', 'T2': 's', 'Runner': 'p', 'STOP': 'x', 'FLOOR': 's', 'EOD': 'o'}
            for leg in leg_exits:
                leg_idx = min(entry_idx + leg['bar_idx'], len(day_ltf) - 1)
                leg_color = '#4CAF50' if leg['pnl'] > 0 else '#F44336'
                mkr = leg_markers.get(leg['leg'], 'o')
                ax.scatter([leg_idx], [leg['price']], color=leg_color, s=120, zorder=6,
                           marker=mkr, edgecolors='black', linewidths=1.5)
                ax.annotate(f"{leg['leg']}\n${leg['pnl']:+,.0f}",
                            xy=(leg_idx, leg['price']),
                            xytext=(leg_idx + 5, leg['price'] + (2 if leg['pnl'] > 0 else -2)),
                            fontsize=7, color=leg_color,
                            arrowprops=dict(arrowstyle='->', color=leg_color, lw=0.8),
                            bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
        else:
            exit_marker = 'v' if is_long else '^'
            ax.scatter([exit_idx], [exit_price], color=result_color, s=150, zorder=5,
                       marker=exit_marker, edgecolors='black', linewidths=1.5)

        result_str = 'WIN' if pnl > 0 else ('LOSS' if pnl < 0 else 'BE')
        result_text = f"{result_str}\n${pnl:+,.0f}"
        exit_y_offset = 3 if pnl > 0 else -3
        ax.annotate(result_text,
                    xy=(exit_idx, exit_price),
                    xytext=(exit_idx + 8, exit_price + exit_y_offset),
                    fontsize=8, fontweight='bold', color=result_color,
                    arrowprops=dict(arrowstyle='->', color=result_color, lw=1),
                    bbox=dict(boxstyle='round', facecolor='white', alpha=0.9))

    # X-axis labels in ET
    tick_positions = list(range(0, len(day_ltf), 20))
    tick_labels = [day_ltf[i].timestamp.strftime('%H:%M') for i in tick_positions if i < len(day_ltf)]
    ax.set_xticks(tick_positions[:len(tick_labels)])
    ax.set_xticklabels(tick_labels, rotation=45)

    # Title and labels
    win_count = sum(1 for t in day_trades if t.get('pnl_dollars', 0) > 0)
    loss_count = sum(1 for t in day_trades if t.get('pnl_dollars', 0) < 0)
    win_rate = (win_count / len(day_trades) * 100) if day_trades else 0

    ax.set_title(f'{symbol} ICT Liquidity Sweep - {target_date} (ET)\n'
                 f'Trades: {len(day_trades)} | Wins: {win_count} | Losses: {loss_count} | '
                 f'Win Rate: {win_rate:.0f}% | Total P/L: ${total_pnl:+,.2f}',
                 fontsize=14, fontweight='bold')
    ax.set_xlabel('Time (ET)')
    ax.set_ylabel('Price')
    ax.grid(True, alpha=0.3)

    # Legend
    legend_elements = [
        Line2D([0], [0], marker='^', color='w', markerfacecolor='#2196F3', markersize=12, label='LONG Entry'),
        Line2D([0], [0], marker='v', color='w', markerfacecolor='#FF5722', markersize=12, label='SHORT Entry'),
        Line2D([0], [0], color='#F44336', linestyle='--', label='Stop Loss'),
        Line2D([0], [0], color='#4CAF50', linestyle=':', label='Trail Activate'),
        Line2D([0], [0], marker='D', color='w', markerfacecolor='#4CAF50', markersize=8, label='T1 Exit'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor='#4CAF50', markersize=8, label='T2/Floor Exit'),
        Line2D([0], [0], marker='p', color='w', markerfacecolor='#4CAF50', markersize=8, label='Runner Exit'),
        plt.Rectangle((0,0), 1, 1, facecolor='#2196F3', alpha=0.2, label='Bullish FVG'),
        plt.Rectangle((0,0), 1, 1, facecolor='#FF5722', alpha=0.2, label='Bearish FVG'),
    ]
    ax.legend(handles=legend_elements, loc='upper right')

    plt.tight_layout()
    plt.show()

    # Print trade summary
    print()
    print('=' * 60)
    print('TRADE SUMMARY (ET)')
    print('=' * 60)
    for i, t in enumerate(day_trades, 1):
        trade = t.get('trade')
        if not trade:
            continue
        pnl = t.get('pnl_dollars', 0)
        et_time = trade.timestamp.strftime('%H:%M')
        print(f"Trade {i}: {trade.direction} @ {trade.entry_price:.2f}")
        print(f"  Entry: {et_time} ET")
        print(f"  Stop: {trade.stop_price:.2f}, T1: {trade.t1_price:.2f}, Trail: {trade.t2_price:.2f}")
        leg_exits = t.get('exits', [])
        if leg_exits:
            for leg in leg_exits:
                print(f"  {leg['leg']}: {leg['price']:.2f} ({leg['contracts']}ct) ${leg['pnl']:+,.2f}")
        else:
            print(f"  Exit: {t.get('exit', trade.entry_price):.2f}")
        print(f"  P/L: ${pnl:+,.2f}")
        print()
    print(f"TOTAL P/L: ${total_pnl:+,.2f}")


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'

    # Check for --zoom flag
    zoom = '--zoom' in sys.argv
    args = [a for a in sys.argv if a != '--zoom']

    if len(args) >= 5:
        year = int(args[2])
        month = int(args[3])
        day = int(args[4])
        plot_ict_sweep(symbol, year, month, day, zoom_first_trade=zoom)
    else:
        plot_ict_sweep(symbol, zoom_first_trade=zoom)
