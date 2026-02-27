"""
Plot TTFM (TTrades Fractal Model) trades.

Visualizes:
- Price chart with candlesticks
- Swing points (C2 labeled)
- CISD zones highlighted
- Entry/exit arrows
- HTF bias annotation
- 15m structure overlaid

Usage:
    python -m ttfm.runners.plot_ttfm ES 3
    python -m ttfm.runners.plot_ttfm NQ 3
    python -m ttfm.runners.plot_ttfm ES 3 --date=2026-02-24
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import date as dt_date, datetime, time as dt_time
from ttfm.tradingview_loader import fetch_futures_bars
from ttfm.bar_storage import load_bars_with_history
from ttfm.runners.run_ttfm import run_session_ttfm, SYMBOL_CONFIG, _build_daily_bars
from ttfm.timeframe import aggregate_bars
from ttfm.signals.swing import find_swings
from ttfm.signals.bias import determine_bias
from ttfm.signals.cisd import detect_cisd
from ttfm.signals.candles import label_candles


def plot_ttfm(symbol='ES', contracts=3, t1_r=2, trail_r=4, target_date=None):
    """Plot TTFM trades for today or a specific date."""
    cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG['ES'])
    tick_size = cfg['tick_size']
    tick_value = cfg['tick_value']
    min_risk = cfg['min_risk']
    max_risk = cfg['max_risk']

    if target_date:
        print(f'Loading {symbol} 3m data for {target_date} (local + live)...')
        all_bars = load_bars_with_history(symbol=symbol, interval='3m', n_bars=10000)
        today = target_date
    else:
        print(f'Fetching {symbol} 3m data...')
        all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=1000)
        today = all_bars[-1].timestamp.date() if all_bars else None

    if not all_bars:
        print('No data available')
        return

    today_bars = [b for b in all_bars if b.timestamp.date() == today]

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

    print(f'Date: {today}')
    print(f'Session bars: {len(session_bars)}')

    rth_bars = [b for b in session_bars if b.timestamp.time() >= dt_time(9, 30)]
    if rth_bars:
        print(f'RTH: Open={rth_bars[0].open:.2f} High={max(b.high for b in rth_bars):.2f} Low={min(b.low for b in rth_bars):.2f}')

    if len(session_bars) < 50:
        print('Not enough bars')
        return

    # Run strategy
    results = run_session_ttfm(
        session_bars, all_bars,
        tick_size=tick_size, tick_value=tick_value,
        contracts=contracts,
        min_risk_pts=min_risk, max_risk_pts=max_risk,
        t1_r_target=t1_r, trail_r_trigger=trail_r,
        symbol=symbol,
    )

    # Compute signals for overlay
    bars_15m = aggregate_bars(session_bars, 15)
    ltf_swings = find_swings(bars_15m, left=2, right=2, timeframe="15m")
    ltf_cisds = detect_cisd(bars_15m, ltf_swings, lookback=10)
    ltf_labels = label_candles(bars_15m, ltf_swings)
    daily_bars = _build_daily_bars(all_bars)
    htf_bias = determine_bias(daily_bars)

    # ── Create figure ───────────────────────────────────────────────────────
    fig = plt.figure(figsize=(22, 16))
    ax = fig.add_axes([0.05, 0.28, 0.90, 0.65])

    # Plot candlesticks
    for i, bar in enumerate(session_bars):
        color = '#4CAF50' if bar.close >= bar.open else '#F44336'
        ax.plot([i, i], [bar.low, bar.high], color=color, linewidth=1)
        body_bottom = min(bar.open, bar.close)
        body_height = abs(bar.close - bar.open)
        rect = plt.Rectangle((i - 0.3, body_bottom), 0.6, body_height,
                             facecolor=color, edgecolor=color)
        ax.add_patch(rect)

    # ── Map 15m bar indices to 3m chart positions ─────────────────────────
    def _15m_to_3m(idx_15m):
        if idx_15m >= len(bars_15m):
            return None
        ts = bars_15m[idx_15m].timestamp
        for si, sb in enumerate(session_bars):
            if sb.timestamp >= ts:
                return si
        return len(session_bars) - 1

    # ── Overlay swing points ───────────────────────────────────────────────
    for swing in ltf_swings:
        idx = _15m_to_3m(swing.bar_index)
        if idx is None:
            continue
        if swing.swing_type == "HIGH":
            ax.annotate('SH', xy=(idx, swing.price), fontsize=7,
                       color='red', ha='center', va='bottom',
                       fontweight='bold')
            ax.plot(idx, swing.price, 'v', color='red', markersize=5, alpha=0.7)
        else:
            ax.annotate('SL', xy=(idx, swing.price), fontsize=7,
                       color='green', ha='center', va='top',
                       fontweight='bold')
            ax.plot(idx, swing.price, '^', color='green', markersize=5, alpha=0.7)

    # ── Overlay candle labels ──────────────────────────────────────────────
    for lbl in ltf_labels:
        idx = _15m_to_3m(lbl.bar_index)
        if idx is None or idx >= len(session_bars):
            continue
        bar = session_bars[idx]
        if lbl.label == "C2":
            y_pos = bar.high + tick_size * 4 if lbl.direction == "BEARISH" else bar.low - tick_size * 4
            ax.annotate(f'C2', xy=(idx, y_pos), fontsize=8,
                       color='#FF5722', ha='center', fontweight='bold',
                       bbox=dict(boxstyle='round,pad=0.2', facecolor='yellow', alpha=0.7))
        elif lbl.label in ("C3", "C4"):
            y_pos = bar.low - tick_size * 2 if lbl.direction == "BULLISH" else bar.high + tick_size * 2
            ax.annotate(lbl.label, xy=(idx, y_pos), fontsize=7,
                       color='#2196F3', ha='center', fontweight='bold')

    # ── Overlay CISD zones ─────────────────────────────────────────────────
    for cisd in ltf_cisds:
        idx = _15m_to_3m(cisd.bar_index)
        if idx is None:
            continue
        color = '#FF572255' if cisd.direction == "BEARISH" else '#4CAF5055'
        rect = plt.Rectangle((idx - 2.5, cisd.ob_low), 5, cisd.ob_high - cisd.ob_low,
                             facecolor=color, edgecolor=color[:7], linewidth=1, alpha=0.3)
        ax.add_patch(rect)
        ax.annotate('CISD', xy=(idx, (cisd.ob_high + cisd.ob_low) / 2),
                    fontsize=6, color=color[:7], ha='center', va='center', alpha=0.8)

    # ── Plot trades ─────────────────────────────────────────────────────────
    total_pnl = 0
    for t_idx, result in enumerate(results):
        direction = result['direction']
        is_long = direction == 'BULLISH'
        entry_price = result['entry_price']
        stop_price = result['stop_price']
        risk = result['risk']

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

        color = '#2196F3' if is_long else '#F44336'
        marker = '^' if is_long else 'v'
        ax.plot(entry_bar_idx, entry_price, marker, color=color, markersize=12, zorder=5)

        ax.hlines(stop_price, entry_bar_idx - 1, entry_bar_idx + 5,
                 color='#F44336', linewidth=1, linestyle='--', alpha=0.5)

        t1 = entry_price + risk * t1_r if is_long else entry_price - risk * t1_r
        ax.hlines(t1, entry_bar_idx - 1, entry_bar_idx + 10,
                 color='#4CAF50', linewidth=1, linestyle=':', alpha=0.5)

        last_exit_idx = entry_bar_idx
        for exit_info in result['exits']:
            exit_time = exit_info['time']
            for i, bar in enumerate(session_bars):
                if bar.timestamp == exit_time:
                    exit_color = '#4CAF50' if exit_info['pnl'] > 0 else '#F44336'
                    if exit_info['type'] == 'EOD':
                        exit_color = '#607D8B'
                    ax.plot(i, exit_info['price'], 'x', color=exit_color, markersize=10, zorder=5, markeredgewidth=2)
                    last_exit_idx = max(last_exit_idx, i)
                    break

        ax.hlines(entry_price, entry_bar_idx, last_exit_idx,
                 color=color, linewidth=0.8, alpha=0.3)

        total_pnl += result['total_dollars']

    # ── HTF bias annotation ─────────────────────────────────────────────────
    bias_color = '#4CAF50' if htf_bias.direction == 'BULLISH' else '#F44336' if htf_bias.direction == 'BEARISH' else '#607D8B'
    ax.text(0.01, 0.97, f'HTF Bias: {htf_bias.direction} ({htf_bias.bias_type})',
           transform=ax.transAxes, fontsize=10, fontweight='bold',
           color=bias_color, va='top',
           bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

    # ── X-axis labels ───────────────────────────────────────────────────────
    tick_interval = max(1, len(session_bars) // 30)
    ax.set_xticks(range(0, len(session_bars), tick_interval))
    ax.set_xticklabels(
        [session_bars[i].timestamp.strftime('%H:%M') for i in range(0, len(session_bars), tick_interval)],
        rotation=45, fontsize=8,
    )

    # ── Title ───────────────────────────────────────────────────────────────
    n_trades = len(results)
    wins = sum(1 for r in results if r['total_dollars'] > 0)
    losses = sum(1 for r in results if r['total_dollars'] < 0)
    win_rate = (wins / n_trades * 100) if n_trades > 0 else 0

    ax.set_title(
        f'{symbol} TTFM - {today} - '
        f'{n_trades} trades ({wins}W/{losses}L, {win_rate:.0f}%) - '
        f'P/L: ${total_pnl:+,.0f}',
        fontsize=14, fontweight='bold',
    )
    ax.grid(True, alpha=0.2)
    ax.set_ylabel('Price', fontsize=12)

    # ── Trade table below chart ─────────────────────────────────────────────
    if results:
        table_ax = fig.add_axes([0.05, 0.02, 0.90, 0.22])
        table_ax.axis('off')

        headers = ['#', 'Time', 'Dir', 'Type', 'Entry', 'Stop', 'Risk', 'Cts', 'P/L', 'Exit']
        table_data = []
        for i, r in enumerate(results):
            t = r['entry_time']
            time_str = t.strftime('%H:%M') if t else '??:??'
            exit_types = ', '.join(e['type'] for e in r['exits'])
            table_data.append([
                str(i + 1),
                time_str,
                r['direction'][:4],
                r['entry_type'].replace('TTFM_', ''),
                f'{r["entry_price"]:.2f}',
                f'{r["stop_price"]:.2f}',
                f'{r["risk"]:.2f}',
                str(r['contracts']),
                f'${r["total_dollars"]:+,.0f}',
                exit_types,
            ])

        table_data.append([
            '', '', '', '', '', '', '', '',
            f'${total_pnl:+,.0f}', f'{wins}W/{losses}L',
        ])

        cell_colors = []
        for i, row in enumerate(table_data):
            row_colors = ['white'] * len(row)
            if i < len(results):
                pnl = results[i]['total_dollars']
                pnl_color = '#E8F5E9' if pnl > 0 else '#FFEBEE' if pnl < 0 else 'white'
                row_colors[-2] = pnl_color
            else:
                row_colors = ['#E3F2FD'] * len(row)
            cell_colors.append(row_colors)

        table = table_ax.table(
            cellText=table_data,
            colLabels=headers,
            cellLoc='center',
            loc='center',
            cellColours=cell_colors,
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1, 1.4)

        for j in range(len(headers)):
            table[0, j].set_facecolor('#1565C0')
            table[0, j].set_text_props(color='white', fontweight='bold')

    # ── Legend ───────────────────────────────────────────────────────────────
    legend_elements = [
        mpatches.Patch(facecolor='yellow', alpha=0.7, label='C2 (Swing)'),
        mpatches.Patch(facecolor='#FF572255', label='Bearish CISD'),
        mpatches.Patch(facecolor='#4CAF5055', label='Bullish CISD'),
    ]
    ax.legend(handles=legend_elements, loc='upper right', fontsize=8)

    plt.savefig(f'ttfm_{symbol}_{today}.png', dpi=150, bbox_inches='tight')
    print(f'\nSaved: ttfm_{symbol}_{today}.png')
    plt.show()


if __name__ == '__main__':
    positional = []
    t1_r = 2
    trail_r = 4
    target_date = None
    for arg in sys.argv[1:]:
        if arg.startswith('--t1-r='):
            t1_r = int(arg.split('=')[1])
        elif arg.startswith('--trail-r='):
            trail_r = int(arg.split('=')[1])
        elif arg.startswith('--date='):
            target_date = dt_date.fromisoformat(arg.split('=')[1])
        else:
            positional.append(arg)

    symbol = positional[0] if len(positional) > 0 else 'ES'
    contracts = int(positional[1]) if len(positional) > 1 else 3

    plot_ttfm(symbol=symbol, contracts=contracts, t1_r=t1_r, trail_r=trail_r, target_date=target_date)
