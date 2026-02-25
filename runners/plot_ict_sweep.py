"""
ICT Liquidity Sweep Strategy — Plot Module

Renders candlestick chart with sweep levels, FVG zones, entries, exits.

Usage:
    python -m runners.plot_ict_sweep ES
    python -m runners.plot_ict_sweep ES --date 2026-02-20
    python -m runners.plot_ict_sweep ES --date 2026-02-20 --debug
"""
import sys
sys.path.insert(0, '.')

import argparse
import pickle
from pathlib import Path
from datetime import time as dt_time, datetime, timedelta

import yaml
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from runners.tradingview_loader import fetch_futures_bars
from strategies.ict_sweep.strategy import ICTSweepStrategy, TradeEntry
from strategies.ict_sweep.trade_sim import simulate_trade
from strategies.ict_sweep.filters.session import get_session_name

CACHE_DIR = Path('.cache')
DEFAULT_CONFIG = Path('config/strategies/ict_sweep.yaml')


def load_config(config_path: Path = DEFAULT_CONFIG) -> dict:
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def merge_symbol_config(base: dict, symbol: str) -> dict:
    merged = {}
    for k, v in base.items():
        if k == 'symbols':
            continue
        merged[k] = v
    sym_overrides = base.get('symbols', {}).get(symbol, {})
    for k, v in sym_overrides.items():
        merged[k] = v
    return merged


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


def run_strategy_for_day(all_bars, target_date, config, all_mtf_bars=None):
    """Run strategy for a specific date. Returns (entries, results, day_bars)."""
    tick_size = config.get('tick_size', 0.25)
    tick_value = config.get('tick_value', 12.50)
    contracts_first = config.get('contracts', 3)
    contracts_sub = config.get('contracts_subsequent', 2)
    t1_r = config.get('t1_r', 3)
    trail_r = config.get('trail_r', 6)
    t2_buffer = config.get('t2_buffer_ticks', 4)
    runner_buffer = config.get('runner_buffer_ticks', 6)
    use_mtf_fvg = config.get('use_mtf_fvg', False) and all_mtf_bars

    # Build session bars
    overnight_start = dt_time(18, 0)
    session_end = dt_time(16, 0)
    prev_day = target_date - timedelta(days=1)
    if prev_day.weekday() == 5:
        prev_day = prev_day - timedelta(days=1)

    day_bars = [b for b in all_bars
                if (b.timestamp.date() == prev_day and b.timestamp.time() >= overnight_start)
                or (b.timestamp.date() == target_date and b.timestamp.time() <= session_end)]

    if len(day_bars) < 50:
        return [], [], day_bars

    # Build MTF day bars
    day_mtf_bars = []
    if use_mtf_fvg:
        session_start_mtf = dt_time(8, 0)
        day_mtf_bars = [b for b in all_mtf_bars
                        if b.timestamp.date() == target_date
                        and session_start_mtf <= b.timestamp.time() <= session_end]

    # Initialize strategy
    strategy = ICTSweepStrategy(config)

    # Warm up
    lookback_bars = [b for b in all_bars if b.timestamp.date() < prev_day][-50:]
    for bar in lookback_bars:
        strategy.bars.append(bar)

    if use_mtf_fvg:
        mtf_lookback = [b for b in all_mtf_bars if b.timestamp.date() < target_date][-100:]
        for bar in mtf_lookback:
            strategy.mtf_bars.append(bar)

    dir_trades = {'LONG': 0, 'SHORT': 0}
    all_entries = []
    all_results = []

    bar_idx = 0
    mtf_idx = 0
    while bar_idx < len(day_bars):
        bar = day_bars[bar_idx]

        # Feed MTF bars
        while mtf_idx < len(day_mtf_bars) and day_mtf_bars[mtf_idx].timestamp <= bar.timestamp:
            strategy.process_mtf_bar(day_mtf_bars[mtf_idx])
            mtf_idx += 1

        entries = strategy.process_bar(bar)

        for entry in entries:
            dir_count = dir_trades.get(entry.direction, 0)
            trade_contracts = contracts_first if dir_count == 0 else contracts_sub

            remaining_bars = day_bars[bar_idx:]
            result = simulate_trade(
                remaining_bars, entry, tick_size, tick_value,
                trade_contracts, t1_r=t1_r, trail_r=trail_r,
                t2_buffer_ticks=t2_buffer, runner_buffer_ticks=runner_buffer,
            )

            if result:
                dir_trades[entry.direction] = dir_count + 1
                exit_bar_idx = min(bar_idx + result.get('bars_held', 1), len(day_bars) - 1)
                exit_time = day_bars[exit_bar_idx].timestamp

                if result['pnl_dollars'] < 0:
                    strategy.on_trade_result(result['pnl_dollars'], entry.direction, exit_time)

                result['entry_obj'] = entry
                result['entry_bar_idx_in_day'] = bar_idx
                all_entries.append(entry)
                all_results.append(result)

        bar_idx += 1

    return all_entries, all_results, day_bars


def plot_sweep(symbol='ES', target_date=None, config_path=None, debug=False):
    """Plot ICT Sweep strategy for a single day."""
    base_config = load_config(Path(config_path) if config_path else DEFAULT_CONFIG)
    config = merge_symbol_config(base_config, symbol)
    if debug:
        config['debug'] = True

    tick_size = config.get('tick_size', 0.25)
    tick_value = config.get('tick_value', 12.50)
    timeframe = config.get('timeframe', '5m')

    use_mtf_fvg = config.get('use_mtf_fvg', False)
    mtf_timeframe = config.get('mtf_timeframe', '3m')

    # Fetch bars
    print(f"Fetching {symbol} {timeframe} data...")
    all_bars = fetch_futures_bars(symbol=symbol, interval=timeframe, n_bars=3000)

    if not all_bars:
        print("No data available")
        return

    # Fetch MTF bars
    all_mtf_bars = None
    if use_mtf_fvg:
        print(f"Fetching {symbol} {mtf_timeframe} data for FVG...")
        all_mtf_bars = fetch_futures_bars(symbol=symbol, interval=mtf_timeframe, n_bars=5000)

    if target_date is None:
        target_date = all_bars[-1].timestamp.date()

    print(f"Date: {target_date}")

    entries, results, day_bars = run_strategy_for_day(all_bars, target_date, config, all_mtf_bars)

    # Filter to session bars for plotting (premarket 04:00 through 16:00)
    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in day_bars
                    if b.timestamp.date() == target_date
                    and premarket_start <= b.timestamp.time() <= rth_end]

    if len(session_bars) < 10:
        print("Not enough session bars for plotting")
        return

    # Print RTH key levels
    rth_bars = [b for b in session_bars if b.timestamp.time() >= dt_time(9, 30)]
    if rth_bars:
        rth_open = rth_bars[0].open
        rth_high = max(b.high for b in rth_bars)
        rth_low = min(b.low for b in rth_bars)
        rth_close = rth_bars[-1].close
        print(f'RTH: Open={rth_open:.2f} High={rth_high:.2f} Low={rth_low:.2f} Close={rth_close:.2f}')

    print(f"Trades: {len(results)}")
    total_pnl = sum(r['pnl_dollars'] for r in results)
    print(f"Total P/L: ${total_pnl:+,.2f}")

    if not results:
        print("No trades to plot")
        return

    # EMAs
    closes = [b.close for b in session_bars]
    ema_20 = calculate_ema(closes, 20)
    ema_50 = calculate_ema(closes, 50)

    # Build timestamp->index map for session_bars
    ts_to_idx = {b.timestamp: i for i, b in enumerate(session_bars)}

    # Create figure
    fig = plt.figure(figsize=(22, 16))
    ax = fig.add_axes([0.05, 0.28, 0.90, 0.65])

    # Candlesticks
    for i, bar in enumerate(session_bars):
        color = '#4CAF50' if bar.close >= bar.open else '#F44336'
        ax.plot([i, i], [bar.low, bar.high], color=color, linewidth=1)
        body_bottom = min(bar.open, bar.close)
        body_height = abs(bar.close - bar.open)
        rect = plt.Rectangle((i - 0.3, body_bottom), 0.6, body_height,
                              facecolor=color, edgecolor=color)
        ax.add_patch(rect)

    # EMAs
    ema_x_20 = [i for i, e in enumerate(ema_20) if e is not None]
    ema_y_20 = [e for e in ema_20 if e is not None]
    ax.plot(ema_x_20, ema_y_20, color='#2196F3', linewidth=1.5, label='EMA 20', alpha=0.7)

    ema_x_50 = [i for i, e in enumerate(ema_50) if e is not None]
    ema_y_50 = [e for e in ema_50 if e is not None]
    ax.plot(ema_x_50, ema_y_50, color='#9C27B0', linewidth=2, label='EMA 50', alpha=0.8)

    exit_colors = {
        'T1': '#4CAF50',
        'T2': '#2196F3',
        'Runner': '#9C27B0',
        'FLOOR': '#FF9800',
        'STOP': '#F44336',
        'EOD': '#607D8B',
    }

    all_plot_indices = []
    all_plot_prices = []

    for t_idx, result in enumerate(results):
        entry = result['entry_obj']
        direction = entry.direction
        is_long = direction == 'LONG'
        trade_color = '#2196F3' if is_long else '#FF5722'

        # Find entry bar in session_bars
        entry_bar_idx = ts_to_idx.get(entry.timestamp)
        if entry_bar_idx is None:
            for i, bar in enumerate(session_bars):
                if bar.timestamp >= entry.timestamp:
                    entry_bar_idx = i
                    break
        if entry_bar_idx is None:
            continue

        entry_price = entry.entry_price
        stop_price = entry.stop_price
        risk = entry.risk_pts

        t1_price = entry_price + (risk * config.get('t1_r', 3)) if is_long else entry_price - (risk * config.get('t1_r', 3))
        trail_price = entry_price + (risk * config.get('trail_r', 6)) if is_long else entry_price - (risk * config.get('trail_r', 6))

        # Sweep level (dashed horizontal)
        sweep_level = entry.sweep.liquidity_level
        sweep_bar_idx = ts_to_idx.get(entry.sweep.timestamp, max(0, entry_bar_idx - 5))
        ax.hlines(sweep_level, max(0, sweep_bar_idx - 10), entry_bar_idx + 5,
                  colors='#FF9800', linestyles='--', linewidth=1.5, alpha=0.7)
        ax.annotate(f'Sweep {sweep_level:.2f}', xy=(max(0, sweep_bar_idx - 10), sweep_level),
                    fontsize=7, color='#FF9800', alpha=0.8)

        # FVG zone (shaded rectangle)
        fvg = entry.fvg
        fvg_bar_idx = ts_to_idx.get(fvg.timestamp, max(0, entry_bar_idx - 2))
        last_exit_bar_idx = entry_bar_idx
        for ex in result.get('exits', []):
            ex_bar_abs = result.get('entry_bar_idx_in_day', 0) + ex.get('bar_idx', 0)
            if ex_bar_abs < len(day_bars):
                ex_ts = day_bars[ex_bar_abs].timestamp
                ex_si = ts_to_idx.get(ex_ts)
                if ex_si is not None:
                    last_exit_bar_idx = max(last_exit_bar_idx, ex_si)

        fvg_rect = plt.Rectangle(
            (fvg_bar_idx - 0.5, fvg.bottom),
            last_exit_bar_idx - fvg_bar_idx + 5,
            fvg.top - fvg.bottom,
            facecolor=trade_color, alpha=0.12, edgecolor=trade_color, linewidth=1.5,
        )
        ax.add_patch(fvg_rect)

        # Trade level lines
        line_end = min(len(session_bars), last_exit_bar_idx + 15)
        ax.hlines(entry_price, entry_bar_idx, line_end, colors=trade_color, linestyles='-', linewidth=2, alpha=0.8)
        ax.hlines(stop_price, entry_bar_idx, line_end, colors='#F44336', linestyles='--', linewidth=1.5, alpha=0.6)
        ax.hlines(t1_price, entry_bar_idx, line_end, colors='#4CAF50', linestyles=':', linewidth=1.5, alpha=0.6)
        ax.hlines(trail_price, entry_bar_idx, line_end, colors='#2196F3', linestyles=':', linewidth=1.5, alpha=0.6)

        # Entry marker
        entry_marker = '^' if is_long else 'v'
        ax.scatter([entry_bar_idx], [entry_price], color=trade_color, s=200, zorder=5,
                   marker=entry_marker, edgecolors='black', linewidths=2)

        y_offset = 8 if is_long else -8
        ax.annotate(
            f'{direction} SWEEP\n{entry.timestamp.strftime("%H:%M")}\n{entry_price:.2f}',
            xy=(entry_bar_idx, entry_price),
            xytext=(entry_bar_idx - 5, entry_price + y_offset),
            fontsize=9, fontweight='bold', color=trade_color,
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor=trade_color),
        )

        # Exit markers
        exit_marker = 'v' if is_long else '^'
        for e_idx, ex in enumerate(result.get('exits', [])):
            ec = exit_colors.get(ex['leg'], '#4CAF50')
            ex_bar_abs = result.get('entry_bar_idx_in_day', 0) + ex.get('bar_idx', 0)
            if ex_bar_abs < len(day_bars):
                ex_ts = day_bars[ex_bar_abs].timestamp
                ex_si = ts_to_idx.get(ex_ts, entry_bar_idx + ex.get('bar_idx', 0))
            else:
                ex_si = entry_bar_idx + ex.get('bar_idx', 0)

            ax.scatter([ex_si], [ex['price']], color=ec, s=150, zorder=5,
                       marker=exit_marker, edgecolors='black', linewidths=1.5)

            x_offset = 2 + (e_idx * 3)
            ax.annotate(
                f"{ex['leg']}\n{ex['contracts']}ct @ {ex['price']:.2f}\n${ex['pnl']:+,.0f}",
                xy=(ex_si, ex['price']),
                xytext=(ex_si + x_offset, ex['price']),
                fontsize=8, fontweight='bold', color=ec,
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8, edgecolor=ec),
            )
            all_plot_prices.append(ex['price'])

        all_plot_indices.extend([entry_bar_idx, last_exit_bar_idx])
        all_plot_prices.extend([entry_price, stop_price, t1_price, trail_price, sweep_level])

    # Axes
    tick_indices = list(range(0, len(session_bars), 15))
    tick_labels = [session_bars[i].timestamp.strftime('%H:%M') for i in tick_indices]
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(tick_labels, rotation=45)

    if all_plot_indices:
        ax.set_xlim(max(0, min(all_plot_indices) - 30), min(len(session_bars), max(all_plot_indices) + 50))

    if all_plot_prices:
        y_pad = 15
        ax.set_ylim(min(all_plot_prices) - y_pad, max(all_plot_prices) + y_pad)

    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Price', fontsize=12)

    result_str = 'WIN' if total_pnl > 0 else 'LOSS' if total_pnl < 0 else 'BE'
    wins = sum(1 for r in results if r['pnl_dollars'] > 0)
    losses = sum(1 for r in results if r['pnl_dollars'] < 0)
    ax.set_title(
        f'{symbol} {timeframe} | {target_date} | ICT Sweep Strategy\n'
        f'Trades: {len(results)} ({wins}W / {losses}L) | '
        f'{result_str} | Total P/L: ${total_pnl:+,.2f}',
        fontsize=14, fontweight='bold',
    )
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Trade table below chart
    table_ax = fig.add_axes([0.05, 0.02, 0.90, 0.22])
    table_ax.axis('off')

    col_labels = ['#', 'Dir', 'Entry', 'Time', 'Risk', 'Sweep Lvl', 'Exits', 'Result', 'P/L', 'Filters']
    table_data = []
    for t_idx, result in enumerate(results):
        entry = result['entry_obj']
        res_str = 'WIN' if result['pnl_dollars'] > 0 else 'LOSS' if result['pnl_dollars'] < 0 else 'BE'

        exit_parts = []
        for ex in result.get('exits', []):
            exit_parts.append(f"{ex['leg']}: {ex['contracts']}ct ${ex['pnl']:+,.0f}")
        exits_str = ' | '.join(exit_parts)

        table_data.append([
            str(t_idx + 1),
            entry.direction,
            f"{entry.entry_price:.2f}",
            entry.timestamp.strftime('%H:%M'),
            f"{entry.risk_ticks:.0f}t",
            f"{entry.sweep.liquidity_level:.2f}",
            exits_str,
            res_str,
            f"${result['pnl_dollars']:+,.2f}",
            entry.filter_summary[:30],
        ])

    table_data.append(['', '', '', '', '', '', '', 'TOTAL', f'${total_pnl:+,.2f}', ''])

    table = table_ax.table(cellText=table_data, colLabels=col_labels,
                           loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(7)
    table.scale(1, 1.3)

    for j in range(len(col_labels)):
        table[0, j].set_facecolor('#1976D2')
        table[0, j].set_text_props(color='white', fontweight='bold')

    for i, result in enumerate(results):
        row = i + 1
        bg = '#C8E6C9' if result['pnl_dollars'] > 0 else '#FFCDD2' if result['pnl_dollars'] < 0 else '#FFF9C4'
        for j in range(len(col_labels)):
            table[row, j].set_facecolor(bg)

    total_row = len(table_data)
    total_bg = '#C8E6C9' if total_pnl > 0 else '#FFCDD2' if total_pnl < 0 else '#FFF9C4'
    for j in range(len(col_labels)):
        table[total_row, j].set_facecolor(total_bg)
        table[total_row, j].set_text_props(fontweight='bold')

    # RTH key levels box
    if rth_bars:
        rth_info = (
            f"RTH KEY LEVELS\n"
            f"Open:  {rth_bars[0].open:.2f}\n"
            f"High:  {max(b.high for b in rth_bars):.2f}\n"
            f"Low:   {min(b.low for b in rth_bars):.2f}\n"
            f"Close: {rth_bars[-1].close:.2f}"
        )
        rth_props = dict(boxstyle='round', facecolor='#E3F2FD', alpha=0.95,
                         edgecolor='#1976D2', linewidth=2)
        ax.text(0.02, 0.02, rth_info, transform=ax.transAxes, fontsize=10,
                verticalalignment='bottom', horizontalalignment='left',
                fontweight='bold', bbox=rth_props, family='monospace')

    filename = f'sweep_{symbol}_{target_date}.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f"\nSaved: {filename}")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description='ICT Sweep Strategy Plotter')
    parser.add_argument('symbol', nargs='?', default='ES', help='Symbol (default: ES)')
    parser.add_argument('--date', type=str, default=None, help='Date (YYYY-MM-DD)')
    parser.add_argument('--config', type=str, default=None, help='Custom YAML config path')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()

    plot_sweep(
        symbol=args.symbol.upper(),
        target_date=target_date,
        config_path=args.config,
        debug=args.debug,
    )


if __name__ == '__main__':
    main()
