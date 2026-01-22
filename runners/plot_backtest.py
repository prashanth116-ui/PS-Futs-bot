"""
Plot backtest signals on price chart.
"""
from __future__ import annotations
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import date
from runners.yfinance_loader import fetch_futures_bars
from strategies.factory import build_ict_from_yaml


def plot_backtest(symbol: str = "ES", session_date: date = None, interval: str = "5m"):
    """Plot price chart with strategy signals."""
    if session_date is None:
        session_date = date.today()

    yf_symbol = f"{symbol}=F"
    config_path = "config/strategies/ict_es.yaml"

    # Fetch data
    print(f"Fetching {interval} data for {symbol}...")
    bars = fetch_futures_bars(yf_symbol, period="1d", interval=interval)

    if not bars:
        print("No data")
        return

    # Filter to session date
    session_bars = [b for b in bars if b.timestamp.date() == session_date]
    if not session_bars:
        session_bars = bars

    print(f"Got {len(session_bars)} bars")

    # Run strategy
    strategy = build_ict_from_yaml(config_path)
    signals = []

    for bar in session_bars:
        signal = strategy.on_bar(bar)
        if signal:
            if isinstance(signal, list):
                for s in signal:
                    if s:
                        signals.append((bar.timestamp, bar.close, s))
            else:
                signals.append((bar.timestamp, bar.close, signal))

    print(f"Generated {len(signals)} signals")

    # Extract data for plotting
    times = [b.timestamp for b in session_bars]
    opens = [b.open for b in session_bars]
    highs = [b.high for b in session_bars]
    lows = [b.low for b in session_bars]
    closes = [b.close for b in session_bars]

    # Create figure
    fig, ax = plt.subplots(figsize=(16, 8))

    # Plot candlesticks (simplified as line with high/low range)
    for i, bar in enumerate(session_bars):
        color = 'green' if bar.close >= bar.open else 'red'
        # High-low line
        ax.plot([times[i], times[i]], [bar.low, bar.high], color=color, linewidth=0.8)
        # Body
        ax.plot([times[i], times[i]], [bar.open, bar.close], color=color, linewidth=2.5)

    # Plot signals
    long_times = []
    long_prices = []
    short_times = []
    short_prices = []

    for ts, price, sig in signals:
        if sig.direction.value == "LONG":
            long_times.append(ts)
            long_prices.append(sig.entry_price)
        else:
            short_times.append(ts)
            short_prices.append(sig.entry_price)

    # Plot long entries (green triangles pointing up)
    if long_times:
        ax.scatter(long_times, long_prices, marker='^', color='lime', s=100,
                   edgecolors='darkgreen', linewidths=1.5, zorder=5, label=f'LONG ({len(long_times)})')

    # Plot short entries (red triangles pointing down)
    if short_times:
        ax.scatter(short_times, short_prices, marker='v', color='red', s=100,
                   edgecolors='darkred', linewidths=1.5, zorder=5, label=f'SHORT ({len(short_times)})')

    # Format x-axis
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    plt.xticks(rotation=45)

    # Labels and title
    ax.set_xlabel('Time (ET)')
    ax.set_ylabel('Price')
    ax.set_title(f'{symbol} - {session_date} - ICT Strategy Signals ({len(signals)} total)')
    ax.legend(loc='upper left')
    ax.grid(True, alpha=0.3)

    # Tight layout
    plt.tight_layout()

    # Save to file
    output_file = f"backtest_{symbol}_{session_date}.png"
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Chart saved to: {output_file}")
    plt.close()

    return output_file


if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "ES"
    interval = sys.argv[2] if len(sys.argv) > 2 else "2m"
    plot_backtest(symbol, date.today(), interval)
