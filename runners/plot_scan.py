"""
Plot ICT Sweep Scanner results for any symbol.

Usage:
    python -m runners.plot_scan PLTR
    python -m runners.plot_scan NVDA 2026 2 13
"""
import sys
sys.path.insert(0, '.')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from datetime import date, time as dt_time, timedelta

from runners.tradingview_loader import fetch_futures_bars
from strategies.ict_sweep.strategy import ICTSweepStrategy, TradeSetup
from strategies.ict_sweep.filters.displacement import calculate_avg_body
from runners.scan_ict_sweep import SYMBOL_CONFIGS, EQUITY_SYMBOLS


def plot_scan(symbol='PLTR', target_date=None, htf_tf='15m'):
    symbol = symbol.upper()
    if symbol not in SYMBOL_CONFIGS:
        print(f'Unknown symbol: {symbol}. Valid: {list(SYMBOL_CONFIGS.keys())}')
        return

    cfg = SYMBOL_CONFIGS[symbol]
    is_equity = symbol in EQUITY_SYMBOLS
    today = target_date or date.today()

    print(f'Fetching {symbol} data...')
    bars_5m = fetch_futures_bars(symbol, interval='5m', n_bars=500)
    bars_htf = fetch_futures_bars(symbol, interval=htf_tf, n_bars=500)

    if not bars_5m or not bars_htf:
        print('No data available')
        return

    # Filter to target date
    if is_equity:
        session_start = dt_time(9, 30)
    else:
        session_start = dt_time(8, 0)
    session_end = dt_time(16, 0)

    day_5m = [b for b in bars_5m if b.timestamp.date() == today
              and session_start <= b.timestamp.time() <= session_end]
    day_htf = [b for b in bars_htf if b.timestamp.date() == today
               and session_start <= b.timestamp.time() <= session_end]

    if not day_5m:
        print(f'No 5m bars for {today}. Available dates:')
        dates = sorted(set(b.timestamp.date() for b in bars_5m))
        for d in dates[-10:]:
            print(f'  {d}')
        return

    # Get prev day for lookback
    prev_day = today - timedelta(days=1)
    while prev_day.weekday() >= 5:
        prev_day -= timedelta(days=1)

    print(f'Date: {today} | 5m bars: {len(day_5m)} | {htf_tf} bars: {len(day_htf)}')

    # Build strategy
    config = {
        'symbol': symbol, 'tick_size': cfg['tick_size'], 'tick_value': cfg['tick_value'],
        'swing_lookback': 20, 'swing_strength': 3,
        'min_sweep_ticks': 2, 'max_sweep_ticks': cfg['max_sweep'],
        'displacement_multiplier': 2.0, 'avg_body_lookback': 20,
        'min_fvg_ticks': cfg['min_fvg'], 'max_fvg_age_bars': 50,
        'mss_lookback': 20, 'mss_swing_strength': 1,
        'stop_buffer_ticks': 2, 'min_risk_ticks': cfg['min_risk'], 'max_risk_ticks': cfg['max_risk'],
        'loss_cooldown_minutes': 0, 'allow_lunch': True, 'require_killzone': False,
        'max_daily_trades': 10, 'max_daily_losses': 10,
        'use_mtf_for_fvg': True, 'entry_on_mitigation': True,
        'use_trend_filter': False, 'stop_buffer_pts': 0.10,
        't1_r': 3, 'trail_r': 6, 'debug': False,
    }

    strategy = ICTSweepStrategy(config)

    # Seed with lookback
    lookback_htf = [b for b in bars_htf if b.timestamp.date() < today][-50:]
    for bar in lookback_htf:
        strategy.htf_bars.append(bar)

    lookback_5m = [b for b in bars_5m if b.timestamp.date() < today][-100:]
    for bar in lookback_5m:
        strategy.mtf_bars.append(bar)

    if strategy.htf_bars:
        strategy.avg_body = calculate_avg_body(strategy.htf_bars, strategy.avg_body_lookback)

    # Process today's bars
    setups = []
    entries = []
    mtf_cursor = 0

    for bar in day_htf:
        while mtf_cursor < len(day_5m) and day_5m[mtf_cursor].timestamp <= bar.timestamp:
            strategy.update_mtf(day_5m[mtf_cursor])
            mtf_cursor += 1

        setup = strategy.update_htf(bar)
        if setup:
            setups.append((bar, setup))

        result = strategy.check_htf_mitigation(bar)
        if isinstance(result, TradeSetup):
            entries.append((bar, result))

    print(f'Setups: {len(setups)}, Entry zones: {len(entries)}')

    # --- PLOT ---
    fig, ax = plt.subplots(figsize=(22, 12))

    # Candlesticks (5m)
    for i, bar in enumerate(day_5m):
        color = '#4CAF50' if bar.close >= bar.open else '#F44336'
        ax.plot([i, i], [bar.low, bar.high], color=color, linewidth=0.8)
        body_bottom = min(bar.open, bar.close)
        body_height = abs(bar.close - bar.open)
        rect = plt.Rectangle((i - 0.3, body_bottom), 0.6, body_height,
                             facecolor=color, edgecolor=color)
        ax.add_patch(rect)

    def find_bar_idx(timestamp):
        for i, b in enumerate(day_5m):
            if b.timestamp >= timestamp:
                return i
        return len(day_5m) - 1

    # Plot FVG zones and sweep markers
    plotted_fvgs = set()
    for bar, setup in setups:
        fvg = setup.fvg
        sweep = setup.sweep
        idx = find_bar_idx(bar.timestamp)
        is_bull = sweep.sweep_type == 'BULLISH'
        fvg_color = '#2196F3' if is_bull else '#FF5722'

        fvg_key = f'{fvg.bottom:.2f}_{fvg.top:.2f}'
        if fvg_key not in plotted_fvgs:
            plotted_fvgs.add(fvg_key)
            fvg_width = min(50, len(day_5m) - max(0, idx - 5))
            fvg_rect = plt.Rectangle(
                (max(0, idx - 5), fvg.bottom), fvg_width, fvg.top - fvg.bottom,
                facecolor=fvg_color, alpha=0.15, edgecolor=fvg_color,
                linewidth=1, linestyle='--')
            ax.add_patch(fvg_rect)

            label_y = fvg.top + 0.15 if is_bull else fvg.bottom - 0.15
            va = 'bottom' if is_bull else 'top'
            ax.text(idx, label_y,
                    f'FVG {fvg.bottom:.2f}-{fvg.top:.2f}',
                    fontsize=7, color=fvg_color, alpha=0.9, va=va,
                    bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7, edgecolor=fvg_color))

        # Sweep star marker
        ax.scatter([idx], [sweep.sweep_price], color=fvg_color, s=200,
                  marker='*', zorder=8, edgecolors='black', linewidths=1)

        # Liquidity level line
        ax.hlines(sweep.liquidity_level, max(0, idx - 15), min(len(day_5m) - 1, idx + 5),
                 colors=fvg_color, linestyles=':', linewidth=1.5, alpha=0.6)

    # Plot entry zones
    for bar, trade in entries:
        idx = find_bar_idx(bar.timestamp)
        is_long = trade.direction in ('LONG', 'BULLISH')
        color = '#2196F3' if is_long else '#FF5722'

        # Entry triangle
        marker = '^' if is_long else 'v'
        ax.scatter([idx], [trade.entry_price], color=color, s=250, zorder=10,
                   marker=marker, edgecolors='black', linewidths=2)

        # Annotation
        et_time = bar.timestamp.strftime('%H:%M')
        y_off = 1.0 if is_long else -1.0
        ax.annotate(
            f'{trade.direction}\n{et_time} ET\n${trade.entry_price:.2f}',
            xy=(idx, trade.entry_price),
            xytext=(idx + 8, trade.entry_price + y_off * 2),
            fontsize=8, fontweight='bold', color=color,
            arrowprops=dict(arrowstyle='->', color=color, lw=1.5),
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor=color))

        # Stop and T1 lines
        line_end = min(len(day_5m) - 1, idx + 30)
        ax.hlines(trade.stop_price, idx, line_end, colors='#F44336',
                 linestyles='--', linewidth=1.5, alpha=0.6)
        ax.text(line_end + 0.5, trade.stop_price,
                f'Stop {trade.stop_price:.2f}', fontsize=7, color='#F44336', va='center')

        ax.hlines(trade.t1_price, idx, line_end, colors='#4CAF50',
                 linestyles=':', linewidth=1.5, alpha=0.6)
        ax.text(line_end + 0.5, trade.t1_price,
                f'T1 {trade.t1_price:.2f} (3R)', fontsize=7, color='#4CAF50', va='center')

    # X-axis time labels
    tick_step = max(1, len(day_5m) // 15)
    tick_positions = list(range(0, len(day_5m), tick_step))
    tick_labels = [day_5m[i].timestamp.strftime('%H:%M') for i in tick_positions if i < len(day_5m)]
    ax.set_xticks(tick_positions[:len(tick_labels)])
    ax.set_xticklabels(tick_labels, rotation=45)

    # Title
    ax.set_title(
        f'{symbol} ICT Liquidity Sweep Scanner \u2014 {today} (ET)\n'
        f'Setups: {len(setups)} | Entry Zones: {len(entries)} | HTF: {htf_tf} | LTF: 5m',
        fontsize=14, fontweight='bold')
    ax.set_xlabel('Time (ET)')
    ax.set_ylabel('Price ($)')
    ax.grid(True, alpha=0.3)

    # Legend
    legend_elements = [
        Line2D([0], [0], marker='^', color='w', markerfacecolor='#2196F3', markersize=12, label='BULLISH Entry'),
        Line2D([0], [0], marker='v', color='w', markerfacecolor='#FF5722', markersize=12, label='BEARISH Entry'),
        Line2D([0], [0], marker='*', color='w', markerfacecolor='#2196F3', markersize=12, label='Sweep (Bull)'),
        Line2D([0], [0], marker='*', color='w', markerfacecolor='#FF5722', markersize=12, label='Sweep (Bear)'),
        Line2D([0], [0], color='#F44336', linestyle='--', label='Stop Loss'),
        Line2D([0], [0], color='#4CAF50', linestyle=':', label='T1 Target (3R)'),
        plt.Rectangle((0, 0), 1, 1, facecolor='#2196F3', alpha=0.15, label='Bullish FVG'),
        plt.Rectangle((0, 0), 1, 1, facecolor='#FF5722', alpha=0.15, label='Bearish FVG'),
    ]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=9)

    plt.tight_layout()
    fname = f'scan_{symbol}_{today}.png'
    plt.savefig(fname, dpi=150)
    print(f'\nSaved: {fname}')

    # Print alert summary
    print()
    print('=' * 70)
    print(f'{symbol} ALERTS \u2014 {today} ({htf_tf})')
    print('=' * 70)
    for bar, setup in setups:
        s = setup.sweep
        f = setup.fvg
        ft = (f.top - f.bottom) / cfg['tick_size']
        print(f'  [SETUP] {bar.timestamp.strftime("%H:%M")} | {s.sweep_type:<8} | '
              f'Sweep={s.sweep_price:.2f} | FVG={f.bottom:.2f}-{f.top:.2f} ({ft:.0f}t) | '
              f'{setup.displacement_ratio:.1f}x')

    for bar, trade in entries:
        print(f'  [ENTRY] {bar.timestamp.strftime("%H:%M")} | {trade.direction:<8} | '
              f'Entry={trade.entry_price:.2f} Stop={trade.stop_price:.2f} '
              f'Risk={trade.risk_ticks:.0f}t | T1={trade.t1_price:.2f}')


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    sym = args[0] if args else 'PLTR'

    if len(args) >= 4:
        target = date(int(args[1]), int(args[2]), int(args[3]))
    else:
        target = None

    plot_scan(sym, target)
