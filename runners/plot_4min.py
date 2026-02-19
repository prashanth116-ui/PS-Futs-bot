"""
Plot 4-minute chart with trades
"""
import sys
sys.path.insert(0, '.')
import matplotlib.pyplot as plt
from datetime import time as dt_time
from collections import namedtuple
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10, calculate_ema

Bar = namedtuple('Bar', ['timestamp', 'open', 'high', 'low', 'close', 'volume'])


def aggregate_to_4min(bars_1m):
    """Aggregate 1-minute bars to 4-minute bars."""
    if not bars_1m:
        return []
    aggregated = []
    current_group = []
    for bar in bars_1m:
        minutes = bar.timestamp.hour * 60 + bar.timestamp.minute
        interval_start = (minutes // 4) * 4
        if current_group:
            first_minutes = current_group[0].timestamp.hour * 60 + current_group[0].timestamp.minute
            first_interval = (first_minutes // 4) * 4
            if bar.timestamp.date() == current_group[0].timestamp.date() and interval_start == first_interval:
                current_group.append(bar)
            else:
                agg_bar = Bar(current_group[0].timestamp, current_group[0].open,
                    max(b.high for b in current_group), min(b.low for b in current_group),
                    current_group[-1].close, sum(getattr(b, 'volume', 0) for b in current_group))
                aggregated.append(agg_bar)
                current_group = [bar]
        else:
            current_group = [bar]
    if current_group:
        agg_bar = Bar(current_group[0].timestamp, current_group[0].open,
            max(b.high for b in current_group), min(b.low for b in current_group),
            current_group[-1].close, sum(getattr(b, 'volume', 0) for b in current_group))
        aggregated.append(agg_bar)
    return aggregated


def plot_4min(symbol):
    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00
    min_risk_pts = 1.5 if symbol == 'ES' else 6.0
    max_bos_risk_pts = 8.0 if symbol == 'ES' else 20.0

    print(f'Fetching {symbol} 1m data and aggregating to 4m...')
    bars_1m = fetch_futures_bars(symbol=symbol, interval='1m', n_bars=15000)
    all_bars = aggregate_to_4min(bars_1m)
    print(f'Aggregated to {len(all_bars)} 4m bars')

    today = all_bars[-1].timestamp.date()
    today_bars = [b for b in all_bars if b.timestamp.date() == today]
    session_bars = [b for b in today_bars if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]

    rth_bars = [b for b in session_bars if b.timestamp.time() >= dt_time(9, 30)]
    rth_open = rth_bars[0].open if rth_bars else 0
    rth_high = max(b.high for b in rth_bars) if rth_bars else 0
    rth_low = min(b.low for b in rth_bars) if rth_bars else 0
    rth_close = rth_bars[-1].close if rth_bars else 0

    print(f'Date: {today}')
    print(f'Session bars: {len(session_bars)}')
    print(f'RTH: Open={rth_open:.2f} High={rth_high:.2f} Low={rth_low:.2f} Close={rth_close:.2f}')

    results = run_session_v10(
        session_bars, all_bars,
        tick_size=tick_size, tick_value=tick_value, contracts=3,
        min_risk_pts=min_risk_pts,
        enable_creation_entry=True, enable_retracement_entry=True, enable_bos_entry=True,
        retracement_morning_only=True, t1_fixed_4r=True,
        midday_cutoff=True, pm_cutoff_nq=(symbol == 'NQ'),
        max_bos_risk_pts=max_bos_risk_pts, symbol=symbol,
    )

    # Print trades
    print()
    print('=' * 70)
    print(f'{symbol} 4-MIN BACKTEST - {today}')
    print('=' * 70)

    total_pnl = 0
    for r in results:
        entry_type = r['entry_type']
        tag = ' [2nd]' if r.get('is_reentry') else ''
        result = 'WIN' if r['total_dollars'] > 0 else 'LOSS'
        total_pnl += r['total_dollars']
        print(f"\n{r['direction']} [{entry_type}]{tag}")
        print(f"  Entry: {r['entry_price']:.2f} @ {r['entry_time'].strftime('%H:%M')}")
        print(f"  FVG: {r['fvg_low']:.2f} - {r['fvg_high']:.2f}")
        print(f"  Stop: {r['stop_price']:.2f}, Risk: {r['risk']:.2f} pts")
        print("  Exits: ", end='')
        for e in r['exits']:
            dollars = (e['pnl'] / tick_size) * tick_value
            print(f"{e['type']}@{e['price']:.2f}=${dollars:+,.0f} ", end='')
        print(f"\n  Result: {result} | P/L: ${r['total_dollars']:+,.2f}")

    print()
    print('=' * 70)
    print(f'TOTAL P/L: ${total_pnl:+,.2f}')
    print('=' * 70)

    # Plot
    fig, ax = plt.subplots(figsize=(16, 10))

    # Candlesticks
    for i, bar in enumerate(session_bars):
        color = 'green' if bar.close >= bar.open else 'red'
        ax.plot([i, i], [bar.low, bar.high], color=color, linewidth=0.8)
        ax.plot([i, i], [bar.open, bar.close], color=color, linewidth=3)

    # EMAs
    ema20_vals, ema50_vals = [], []
    for i in range(len(session_bars)):
        idx = next((j for j, b in enumerate(all_bars) if b.timestamp == session_bars[i].timestamp), None)
        if idx:
            bars_to_i = all_bars[:idx+1]
        else:
            bars_to_i = session_bars[:i+1]
        ema20 = calculate_ema(bars_to_i, 20)
        ema50 = calculate_ema(bars_to_i, 50)
        ema20_vals.append(ema20)
        ema50_vals.append(ema50)

    ax.plot(range(len(session_bars)), ema20_vals, 'c-', linewidth=1, alpha=0.7, label='EMA 20')
    ax.plot(range(len(session_bars)), ema50_vals, 'm-', linewidth=1, alpha=0.7, label='EMA 50')

    # Plot trades
    for r in results:
        entry_idx = next((i for i, b in enumerate(session_bars) if b.timestamp == r['entry_time']), None)
        if entry_idx is None:
            continue

        is_long = r['direction'] == 'LONG'
        color = 'blue' if is_long else 'orange'
        marker = '^' if is_long else 'v'

        # Entry marker
        ax.scatter(entry_idx, r['entry_price'], marker=marker, s=150, c=color, zorder=5, edgecolors='black')

        # FVG zone
        ax.axhspan(r['fvg_low'], r['fvg_high'], alpha=0.2, color='green' if is_long else 'red',
                   xmin=max(0, (entry_idx-5)/len(session_bars)), xmax=min(1, (entry_idx+25)/len(session_bars)))

        # Stop line
        ax.hlines(r['stop_price'], entry_idx, min(entry_idx+20, len(session_bars)-1),
                  colors='red', linestyles='--', linewidth=1.5)

        # Exits
        for e in r['exits']:
            for j in range(entry_idx, len(session_bars)):
                b = session_bars[j]
                if b.low <= e['price'] <= b.high or abs(b.close - e['price']) < tick_size * 2:
                    exit_color = 'lime' if e['pnl'] > 0 else 'red'
                    ax.scatter(j, e['price'], marker='x', s=100, c=exit_color, zorder=5, linewidths=2)
                    break

        # Annotation
        entry_type = r['entry_type'][:4]
        tag = '[2nd]' if r.get('is_reentry') else ''
        pnl_color = 'lightgreen' if r['total_dollars'] > 0 else 'lightsalmon'
        ax.annotate(f"{r['direction']} [{entry_type}] {tag}\n{r['entry_time'].strftime('%H:%M')}\n${r['total_dollars']:+,.0f}",
                   (entry_idx, r['entry_price']), fontsize=8,
                   xytext=(10, 20 if is_long else -20), textcoords='offset points',
                   bbox=dict(boxstyle='round', facecolor=pnl_color, alpha=0.9),
                   arrowprops=dict(arrowstyle='->', color='gray'))

    # X-axis labels
    tick_positions = list(range(0, len(session_bars), max(1, len(session_bars)//12)))
    tick_labels = [session_bars[i].timestamp.strftime('%H:%M') for i in tick_positions]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, rotation=45)

    ax.set_xlabel('Time')
    ax.set_ylabel('Price')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)

    result_str = 'WIN' if total_pnl > 0 else 'LOSS'
    creation = sum(1 for r in results if r['entry_type'] == 'CREATION')
    overnight = sum(1 for r in results if r['entry_type'] == 'RETRACEMENT')
    intraday = sum(1 for r in results if r['entry_type'] == 'INTRADAY_RETRACE')
    bos = sum(1 for r in results if r['entry_type'] == 'BOS_RETRACE')

    ax.set_title(f"{symbol} 4-Minute | {today} | V10.7 Quad Entry Mode\n"
                f"Trades: {len(results)} ({creation} Creation, {overnight} Overnight, {intraday} Intraday, {bos} BOS)\n"
                f"Result: {result_str} | Total P/L: ${total_pnl:+,.2f}", fontsize=12)

    # RTH box
    textstr = f'RTH KEY LEVELS\nOpen: {rth_open:.2f}\nHigh: {rth_high:.2f}\nLow: {rth_low:.2f}\nClose: {rth_close:.2f}'
    props = dict(boxstyle='round', facecolor='lightyellow', alpha=0.9)
    ax.text(0.02, 0.15, textstr, transform=ax.transAxes, fontsize=9, verticalalignment='top', bbox=props)

    plt.tight_layout()
    filename = f'backtest_{symbol}_4MIN_{today}.png'
    plt.savefig(filename, dpi=150)
    print(f'Saved: {filename}')
    plt.close()

    return results


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    plot_4min(symbol)
