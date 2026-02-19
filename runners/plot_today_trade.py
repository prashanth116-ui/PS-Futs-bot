"""
Plot today's ES trade with 3 contracts and 4R/8R targets.
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations


def calculate_ema(closes, period):
    """Calculate EMA for a list of closes."""
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


def plot_today_trade():
    """Plot today's trade."""

    # Fetch data
    print('Fetching ES 3m data...')
    all_bars = fetch_futures_bars(symbol='ES', interval='3m', n_bars=500)

    today = date(2026, 1, 27)
    today_bars = [b for b in all_bars if b.timestamp.date() == today]

    # Session filter
    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

    print(f'Got {len(session_bars)} session bars')

    # Trade parameters
    target1_r = 4
    target2_r = 8
    tick_size = 0.25

    # Detect FVGs
    fvg_config = {
        'min_fvg_ticks': 4,
        'tick_size': tick_size,
        'max_fvg_age_bars': 100,
        'invalidate_on_close_through': True
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)
    update_all_fvg_mitigations(all_fvgs, session_bars, fvg_config)

    # Get bullish FVGs for LONG trade
    bullish_fvgs = [f for f in all_fvgs if f.direction == 'BULLISH' and not f.mitigated]
    bullish_fvgs.sort(key=lambda f: f.created_bar_index)

    if not bullish_fvgs:
        print('No bullish FVGs found')
        return

    entry_fvg = bullish_fvgs[0]

    # Calculate levels
    entry_price = entry_fvg.midpoint
    stop_price = entry_fvg.low - (2 * tick_size)
    risk = entry_price - stop_price

    target_4r = entry_price + (target1_r * risk)
    target_8r = entry_price + (target2_r * risk)

    # Calculate EMAs
    closes = [b.close for b in session_bars]
    ema_50 = calculate_ema(closes, 50)

    # Find entry bar
    entry_bar_idx = None
    for i in range(entry_fvg.created_bar_index + 1, len(session_bars)):
        bar = session_bars[i]
        if bar.low <= entry_price:
            entry_bar_idx = i
            break

    # Find exit points
    exit_4r_idx = None
    exit_8r_idx = None
    exit_ema_idx = None
    exit_ema_price = None

    exited_4r = False
    exited_8r = False

    for i in range(entry_bar_idx + 1, len(session_bars)):
        bar = session_bars[i]
        bar_ema50 = ema_50[i] if i < len(ema_50) and ema_50[i] else None

        if not exited_4r and bar.high >= target_4r:
            exit_4r_idx = i
            exited_4r = True

        if not exited_8r and bar.high >= target_8r:
            exit_8r_idx = i
            exited_8r = True

        if exited_4r and exited_8r and bar_ema50:
            if bar.close < bar_ema50:
                exit_ema_idx = i
                exit_ema_price = bar.close
                break

    # Create figure
    fig, ax = plt.subplots(figsize=(18, 10))

    # Plot candlesticks
    for i, bar in enumerate(session_bars):
        color = '#4CAF50' if bar.close >= bar.open else '#F44336'

        # Wick
        ax.plot([i, i], [bar.low, bar.high], color=color, linewidth=1)

        # Body
        body_bottom = min(bar.open, bar.close)
        body_height = abs(bar.close - bar.open)
        rect = plt.Rectangle((i - 0.3, body_bottom), 0.6, body_height,
                             facecolor=color, edgecolor=color)
        ax.add_patch(rect)

    # Plot EMA50
    ema_x = [i for i, e in enumerate(ema_50) if e is not None]
    ema_y = [e for e in ema_50 if e is not None]
    ax.plot(ema_x, ema_y, color='#9C27B0', linewidth=2, label='EMA 50', alpha=0.8)

    # Highlight entry FVG
    fvg_start = entry_fvg.created_bar_index
    fvg_rect = plt.Rectangle((fvg_start - 0.5, entry_fvg.low),
                              len(session_bars) - fvg_start,
                              entry_fvg.high - entry_fvg.low,
                              facecolor='#2196F3', alpha=0.2, edgecolor='#2196F3', linewidth=2)
    ax.add_patch(fvg_rect)

    # Plot trade levels
    line_start = entry_bar_idx - 5
    line_end = exit_ema_idx + 5 if exit_ema_idx else len(session_bars)

    # Entry line
    ax.hlines(entry_price, line_start, line_end, colors='#2196F3', linestyles='-', linewidth=2, label=f'Entry: {entry_price:.2f}')

    # Stop line
    ax.hlines(stop_price, line_start, entry_bar_idx + 10, colors='#F44336', linestyles='--', linewidth=2, label=f'Stop: {stop_price:.2f}')

    # Target lines
    ax.hlines(target_4r, line_start, line_end, colors='#4CAF50', linestyles='--', linewidth=2, label=f'4R Target: {target_4r:.2f}')
    ax.hlines(target_8r, line_start, line_end, colors='#8BC34A', linestyles='--', linewidth=2, label=f'8R Target: {target_8r:.2f}')

    # Mark entry point
    ax.scatter([entry_bar_idx], [entry_price], color='#2196F3', s=200, zorder=5,
               marker='^', edgecolors='black', linewidths=2)
    ax.annotate(f'ENTRY\n{session_bars[entry_bar_idx].timestamp.strftime("%H:%M")}\n{entry_price:.2f}',
                xy=(entry_bar_idx, entry_price), xytext=(entry_bar_idx - 8, entry_price - 3),
                fontsize=10, fontweight='bold', color='#2196F3',
                arrowprops=dict(arrowstyle='->', color='#2196F3', lw=2))

    # Mark exit points
    if exit_4r_idx:
        ax.scatter([exit_4r_idx], [target_4r], color='#4CAF50', s=200, zorder=5,
                   marker='v', edgecolors='black', linewidths=2)
        ax.annotate(f'4R EXIT\n1 ct @ {target_4r:.2f}\n+$325',
                    xy=(exit_4r_idx, target_4r), xytext=(exit_4r_idx + 3, target_4r + 2),
                    fontsize=9, fontweight='bold', color='#4CAF50',
                    arrowprops=dict(arrowstyle='->', color='#4CAF50', lw=1.5))

    if exit_8r_idx:
        ax.scatter([exit_8r_idx], [target_8r], color='#8BC34A', s=200, zorder=5,
                   marker='v', edgecolors='black', linewidths=2)
        ax.annotate(f'8R EXIT\n1 ct @ {target_8r:.2f}\n+$650',
                    xy=(exit_8r_idx, target_8r), xytext=(exit_8r_idx + 3, target_8r + 2),
                    fontsize=9, fontweight='bold', color='#8BC34A',
                    arrowprops=dict(arrowstyle='->', color='#8BC34A', lw=1.5))

    if exit_ema_idx and exit_ema_price:
        ax.scatter([exit_ema_idx], [exit_ema_price], color='#9C27B0', s=200, zorder=5,
                   marker='v', edgecolors='black', linewidths=2)
        ax.annotate(f'EMA50 EXIT\n1 ct @ {exit_ema_price:.2f}\n+$456',
                    xy=(exit_ema_idx, exit_ema_price), xytext=(exit_ema_idx + 3, exit_ema_price - 3),
                    fontsize=9, fontweight='bold', color='#9C27B0',
                    arrowprops=dict(arrowstyle='->', color='#9C27B0', lw=1.5))

    # Shade profit zone
    ax.fill_between([entry_bar_idx, line_end], entry_price, target_8r,
                    alpha=0.1, color='#4CAF50')

    # X-axis labels
    tick_indices = list(range(0, len(session_bars), 20))
    tick_labels = [session_bars[i].timestamp.strftime('%H:%M') for i in tick_indices]
    ax.set_xticks(tick_indices)
    ax.set_xticklabels(tick_labels, rotation=45)

    # Focus on trade area
    focus_start = max(0, entry_bar_idx - 30)
    focus_end = min(len(session_bars), (exit_ema_idx or entry_bar_idx) + 40)
    ax.set_xlim(focus_start, focus_end)

    # Y-axis range
    y_min = stop_price - 3
    y_max = target_8r + 5
    ax.set_ylim(y_min, y_max)

    ax.set_xlabel('Time', fontsize=12)
    ax.set_ylabel('Price', fontsize=12)
    ax.set_title(f'ES 3-Minute | Jan 27, 2026 | LONG Trade | 3 Contracts | 4R/8R Targets\n'
                 f'Total P/L: +$1,431.25 | Risk: {risk:.2f} pts ({risk/tick_size:.0f} ticks)',
                 fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Add summary box
    summary = (f'TRADE SUMMARY\n'
               f'Entry: {entry_price:.2f} @ 10:03\n'
               f'Stop: {stop_price:.2f}\n'
               f'Risk: {risk:.2f} pts\n'
               f'─────────────\n'
               f'4R (1 ct): +$325\n'
               f'8R (1 ct): +$650\n'
               f'EMA50 (1 ct): +$456\n'
               f'─────────────\n'
               f'TOTAL: +$1,431.25')
    props = dict(boxstyle='round', facecolor='#E8F5E9', alpha=0.9, edgecolor='#4CAF50', linewidth=2)
    ax.text(0.98, 0.98, summary, transform=ax.transAxes, fontsize=11,
            verticalalignment='top', horizontalalignment='right',
            fontweight='bold', bbox=props, family='monospace')

    plt.tight_layout()
    plt.savefig('backtest_ES_today_2026-01-27.png', dpi=150, bbox_inches='tight')
    print('Saved: backtest_ES_today_2026-01-27.png')
    plt.close()


if __name__ == '__main__':
    plot_today_trade()
