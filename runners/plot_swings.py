"""
Plot swing highs and lows on price chart.

Simple market structure visualization.
"""
from __future__ import annotations
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import date, time as dt_time

from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.sweep import find_swing_highs, find_swing_lows


def plot_swings(
    symbol: str = "ES",
    session_date: date = None,
    interval: str = "2m",
    left_bars: int = 3,
    right_bars: int = 2,
):
    """Plot price chart with swing highs and lows marked."""
    if session_date is None:
        session_date = date.today()

    print(f"Fetching {interval} data for {symbol} from TradingView...")
    all_bars = fetch_futures_bars(
        symbol=symbol,
        interval=interval,
        n_bars=2000,
    )

    # Filter to target date (premarket 4:00 AM to RTH close 16:00)
    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)

    session_bars = [
        b for b in all_bars
        if b.timestamp.date() == session_date
        and premarket_start <= b.timestamp.time() <= rth_end
    ]

    if not session_bars:
        print(f"No data for {session_date}")
        return

    print(f"Got {len(session_bars)} bars for {session_date}")
    print(f"Time range: {session_bars[0].timestamp} to {session_bars[-1].timestamp}")

    # Find swing points
    swing_highs = find_swing_highs(session_bars, left_bars, right_bars)
    swing_lows = find_swing_lows(session_bars, left_bars, right_bars)

    print(f"Found {len(swing_highs)} swing highs, {len(swing_lows)} swing lows")

    # Extract data for plotting
    times = [b.timestamp for b in session_bars]

    # Create figure
    fig, ax = plt.subplots(figsize=(18, 10))

    # Plot candlesticks
    for i, bar in enumerate(session_bars):
        color = 'green' if bar.close >= bar.open else 'red'
        # Wick
        ax.plot([times[i], times[i]], [bar.low, bar.high], color=color, linewidth=0.8)
        # Body
        ax.plot([times[i], times[i]], [bar.open, bar.close], color=color, linewidth=2.5)

    # Plot swing highs (red triangles pointing down)
    sh_times = [session_bars[sh.bar_index].timestamp for sh in swing_highs]
    sh_prices = [sh.price for sh in swing_highs]
    ax.scatter(sh_times, sh_prices, marker='v', color='red', s=120,
               edgecolors='darkred', linewidths=1.5, zorder=5, label=f'Swing High ({len(swing_highs)})')

    # Plot swing lows (green triangles pointing up)
    sl_times = [session_bars[sl.bar_index].timestamp for sl in swing_lows]
    sl_prices = [sl.price for sl in swing_lows]
    ax.scatter(sl_times, sl_prices, marker='^', color='lime', s=120,
               edgecolors='darkgreen', linewidths=1.5, zorder=5, label=f'Swing Low ({len(swing_lows)})')

    # Connect swing points to show structure flow
    # Combine and sort all swings by time
    all_swings = [(sh.bar_index, sh.price, 'HIGH') for sh in swing_highs]
    all_swings += [(sl.bar_index, sl.price, 'LOW') for sl in swing_lows]
    all_swings.sort(key=lambda x: x[0])

    # Draw structure lines connecting alternating highs and lows
    if len(all_swings) >= 2:
        for i in range(len(all_swings) - 1):
            idx1, price1, type1 = all_swings[i]
            idx2, price2, type2 = all_swings[i + 1]
            t1 = session_bars[idx1].timestamp
            t2 = session_bars[idx2].timestamp
            # Use gray for structure lines
            ax.plot([t1, t2], [price1, price2], color='gray', linewidth=1, alpha=0.5, zorder=2)

    # Annotate key levels (only major ones - first/last of the day and extremes)
    if swing_highs:
        # Day's high
        day_high = max(swing_highs, key=lambda x: x.price)
        sh_time = session_bars[day_high.bar_index].timestamp
        ax.annotate(f'HOD {day_high.price:.2f}', xy=(sh_time, day_high.price),
                   xytext=(5, 8), textcoords='offset points',
                   fontsize=9, color='darkred', fontweight='bold')

    if swing_lows:
        # Day's low
        day_low = min(swing_lows, key=lambda x: x.price)
        sl_time = session_bars[day_low.bar_index].timestamp
        ax.annotate(f'LOD {day_low.price:.2f}', xy=(sl_time, day_low.price),
                   xytext=(5, -15), textcoords='offset points',
                   fontsize=9, color='darkgreen', fontweight='bold')

    # Session markers
    rth_start = dt_time(9, 30)
    for bar in session_bars:
        if bar.timestamp.time() == rth_start or (
            bar.timestamp.time() > rth_start and
            session_bars[session_bars.index(bar)-1].timestamp.time() < rth_start
        ):
            ax.axvline(x=bar.timestamp, color='blue', linestyle='-', alpha=0.5, linewidth=1)
            ax.annotate('RTH Open 9:30', xy=(bar.timestamp, ax.get_ylim()[1]),
                       xytext=(5, -15), textcoords='offset points',
                       fontsize=9, color='blue')
            break

    # Formatting
    ax.set_ylabel('Price', fontsize=12)
    ax.set_xlabel('Time (ET)', fontsize=12)
    ax.set_title(f'{symbol} - {session_date} - Swing Structure ({interval} bars, L={left_bars}, R={right_bars})', fontsize=14)
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    plt.xticks(rotation=45)

    plt.tight_layout()

    # Save
    output_file = f"swings_{symbol}_{session_date}_{interval}.png"
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Chart saved to: {output_file}")
    plt.close()

    # Print swing details
    print(f"\n{'='*60}")
    print("SWING HIGHS")
    print(f"{'='*60}")
    for sh in swing_highs:
        t = session_bars[sh.bar_index].timestamp
        print(f"  {t.strftime('%H:%M')} - {sh.price:.2f}")

    print(f"\n{'='*60}")
    print("SWING LOWS")
    print(f"{'='*60}")
    for sl in swing_lows:
        t = session_bars[sl.bar_index].timestamp
        print(f"  {t.strftime('%H:%M')} - {sl.price:.2f}")

    return output_file


if __name__ == "__main__":
    # Default to yesterday (1/26)
    target_date = date(2026, 1, 26)

    # Parse args
    if len(sys.argv) > 1:
        symbol = sys.argv[1]
    else:
        symbol = "ES"

    if len(sys.argv) > 2:
        interval = sys.argv[2]
    else:
        interval = "2m"

    if len(sys.argv) > 3:
        left_bars = int(sys.argv[3])
    else:
        left_bars = 3

    if len(sys.argv) > 4:
        right_bars = int(sys.argv[4])
    else:
        right_bars = 2

    plot_swings(symbol, target_date, interval, left_bars, right_bars)
