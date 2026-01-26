"""
Plot ICT Sweep+OTE+MSS+FVG strategy signals on price chart.

Uses TradingView data via tvDatafeed.
"""
from __future__ import annotations
import matplotlib.pyplot as plt
from datetime import date, timedelta
from runners.tradingview_loader import fetch_rth_bars
from strategies.ict_sweep_ote import ICTSweepOTEStrategy, StrategyConfig


def plot_backtest(symbol: str = "ES", session_date: date = None, interval: str = "3m", extended_hours: bool = False):
    """Plot price chart with strategy signals.

    Args:
        symbol: Trading symbol
        session_date: Date to plot
        interval: Bar interval
        extended_hours: If True, include pre-market and post-market data
    """
    if session_date is None:
        session_date = date.today()

    if extended_hours:
        # Fetch all data including pre/post market
        from runners.tradingview_loader import fetch_futures_bars
        print(f"Fetching {interval} data for {symbol} (with extended hours) from TradingView...")
        all_bars = fetch_futures_bars(
            symbol=symbol,
            interval=interval,
            n_bars=1500,
        )
        # Filter to target date
        session_bars = [b for b in all_bars if b.timestamp.date() == session_date]
    else:
        # Fetch RTH data only
        print(f"Fetching {interval} data for {symbol} from TradingView...")
        session_bars = fetch_rth_bars(
            symbol=symbol,
            interval=interval,
            n_bars=1000,
            target_date=session_date,
        )

    if not session_bars:
        print(f"No data for {symbol} on {session_date}")
        return None

    print(f"Got {len(session_bars)} bars")

    # Create strategy and run
    config = StrategyConfig(symbol=symbol, timeframe=interval)
    config.mss.max_bars_after_sweep = 20
    config.mss.lh_lookback_bars = 30
    strategy = ICTSweepOTEStrategy(config=config, equity=100000)

    signals = []
    for bar in session_bars:
        signal = strategy.on_bar(bar)
        if signal:
            signals.append((bar.timestamp, bar.close, signal))

    print(f"Generated {len(signals)} signals")

    # Extract data for plotting
    # Use bar indices for x-axis to avoid matplotlib timezone conversion issues
    opens = [b.open for b in session_bars]
    highs = [b.high for b in session_bars]
    lows = [b.low for b in session_bars]
    closes = [b.close for b in session_bars]
    timestamps = [b.timestamp for b in session_bars]

    # Create numeric indices for x-axis
    x_indices = list(range(len(session_bars)))

    # Create figure
    fig, ax = plt.subplots(figsize=(16, 8))

    # Plot candlesticks using indices
    for i, bar in enumerate(session_bars):
        color = 'green' if bar.close >= bar.open else 'red'
        # High-low line
        ax.plot([i, i], [bar.low, bar.high], color=color, linewidth=0.8)
        # Body
        ax.plot([i, i], [bar.open, bar.close], color=color, linewidth=2.5)

    # Create timestamp to index mapping
    ts_to_idx = {b.timestamp: i for i, b in enumerate(session_bars)}

    # Plot signals
    long_indices = []
    long_prices = []
    long_labels = []
    short_indices = []
    short_prices = []

    for ts, price, sig in signals:
        idx = ts_to_idx.get(ts, None)
        if idx is None:
            # Find closest timestamp
            for i, b in enumerate(session_bars):
                if abs((b.timestamp - ts).total_seconds()) < 200:
                    idx = i
                    break
        if idx is not None:
            if sig.direction.value == "LONG":
                long_indices.append(idx)
                long_prices.append(sig.entry_price)
                long_labels.append(f"L@{sig.entry_price:.2f}\nSL:{sig.stop_price:.2f}")
            else:
                short_indices.append(idx)
                short_prices.append(sig.entry_price)

    # Plot long entries (green triangles pointing up)
    if long_indices:
        ax.scatter(long_indices, long_prices, marker='^', color='lime', s=150,
                   edgecolors='darkgreen', linewidths=2, zorder=5, label=f'LONG ({len(long_indices)})')
        # Add labels
        for idx, p, lbl in zip(long_indices, long_prices, long_labels):
            ax.annotate(lbl, (idx, p), textcoords="offset points", xytext=(10, 10),
                       fontsize=8, color='darkgreen', fontweight='bold')

    # Plot short entries (red triangles pointing down)
    if short_indices:
        ax.scatter(short_indices, short_prices, marker='v', color='red', s=150,
                   edgecolors='darkred', linewidths=2, zorder=5, label=f'SHORT ({len(short_indices)})')

    # Plot swing points
    swing_low_indices = []
    swing_low_prices = []
    swing_high_indices = []
    swing_high_prices = []

    for swing in strategy.swings:
        idx = ts_to_idx.get(swing.timestamp, None)
        if idx is not None:
            if swing.swing_type.value == "LOW":
                swing_low_indices.append(idx)
                swing_low_prices.append(swing.price)
            else:
                swing_high_indices.append(idx)
                swing_high_prices.append(swing.price)

    # Plot swing lows (small blue dots)
    if swing_low_indices:
        ax.scatter(swing_low_indices, swing_low_prices, marker='o', color='blue', s=30,
                   alpha=0.5, zorder=3, label=f'Swing Lows ({len(swing_low_indices)})')

    # Plot swing highs (small orange dots)
    if swing_high_indices:
        ax.scatter(swing_high_indices, swing_high_prices, marker='o', color='orange', s=30,
                   alpha=0.5, zorder=3, label=f'Swing Highs ({len(swing_high_indices)})')

    # Format x-axis with custom time labels
    # Show time labels every hour
    tick_indices = []
    tick_labels = []
    last_hour = None
    for i, ts in enumerate(timestamps):
        hour = ts.hour
        if hour != last_hour:
            tick_indices.append(i)
            tick_labels.append(ts.strftime('%H:%M'))
            last_hour = hour

    ax.set_xticks(tick_indices)
    ax.set_xticklabels(tick_labels, rotation=45)

    # Add RTH markers if showing extended hours
    if extended_hours:
        from datetime import time as dt_time
        rth_start = dt_time(9, 30)
        rth_end = dt_time(16, 0)

        # Find RTH boundaries
        rth_start_idx = None
        rth_end_idx = None
        for i, ts in enumerate(timestamps):
            if rth_start_idx is None and ts.time() >= rth_start:
                rth_start_idx = i
            if ts.time() <= rth_end:
                rth_end_idx = i

        # Shade pre-market and post-market
        if rth_start_idx is not None and rth_start_idx > 0:
            ax.axvspan(0, rth_start_idx, alpha=0.1, color='gray', label='Pre-market')
        if rth_end_idx is not None and rth_end_idx < len(timestamps) - 1:
            ax.axvspan(rth_end_idx, len(timestamps) - 1, alpha=0.1, color='gray', label='Post-market')

        # Add vertical lines at RTH boundaries
        if rth_start_idx is not None:
            ax.axvline(x=rth_start_idx, color='blue', linestyle='--', alpha=0.5, linewidth=1)
        if rth_end_idx is not None:
            ax.axvline(x=rth_end_idx, color='blue', linestyle='--', alpha=0.5, linewidth=1)

    # Labels and title
    ax.set_xlabel('Time (ET)')
    ax.set_ylabel('Price')

    session_high = max(highs)
    session_low = min(lows)
    change = closes[-1] - opens[0]
    change_pct = (change / opens[0]) * 100

    hours_label = " (Extended Hours)" if extended_hours else ""
    ax.set_title(f'{symbol} - {session_date} - ICT Sweep+OTE Strategy{hours_label}\n'
                 f'O:{opens[0]:.2f} H:{session_high:.2f} L:{session_low:.2f} C:{closes[-1]:.2f} '
                 f'({change:+.2f}, {change_pct:+.2f}%) | Signals: {len(signals)}')

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
    symbol = sys.argv[1] if len(sys.argv) > 1 else "TSLA"
    extended = "--extended" in sys.argv or "-e" in sys.argv

    today = date.today()
    yesterday = today - timedelta(days=1)

    # Generate charts for today and yesterday
    plot_backtest(symbol, today, "3m", extended_hours=extended)
    plot_backtest(symbol, yesterday, "3m", extended_hours=extended)
