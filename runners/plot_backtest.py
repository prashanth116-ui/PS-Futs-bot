"""
Plot backtest signals on price chart with P/L tracking.

Uses TradingView data via tvDatafeed.
"""
from __future__ import annotations
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.factory import build_ict_from_yaml


def calculate_pnl(signals, session_bars, tick_value=12.50):
    """
    Calculate P/L for each signal by simulating trade execution.

    Returns list of trade results with P/L in dollars.
    """
    results = []

    # Create bar lookup by timestamp
    bar_times = [b.timestamp for b in session_bars]

    for ts, price, sig in signals:
        entry = sig.entry_price
        stop = sig.stop_price
        targets = sig.targets if sig.targets else []
        direction = sig.direction.value

        # Find bar index where signal occurred
        try:
            start_idx = next(i for i, t in enumerate(bar_times) if t >= ts)
        except StopIteration:
            continue

        # Track through subsequent bars
        trade_result = {
            'timestamp': ts,
            'direction': direction,
            'entry': entry,
            'stop': stop,
            'targets': targets,
            'exit_price': None,
            'exit_time': None,
            'pnl_ticks': 0,
            'pnl_dollars': 0,
            'outcome': 'open',
        }

        # Risk in ticks
        risk_ticks = abs(entry - stop) / 0.25  # ES tick size

        for bar in session_bars[start_idx + 1:]:
            if direction == "LONG":
                # Check stop hit first (worst case)
                if bar.low <= stop:
                    trade_result['exit_price'] = stop
                    trade_result['exit_time'] = bar.timestamp
                    trade_result['pnl_ticks'] = -risk_ticks
                    trade_result['outcome'] = 'loss'
                    break
                # Check target 1 hit
                elif targets and bar.high >= targets[0]:
                    trade_result['exit_price'] = targets[0]
                    trade_result['exit_time'] = bar.timestamp
                    trade_result['pnl_ticks'] = abs(targets[0] - entry) / 0.25
                    trade_result['outcome'] = 'win'
                    break
            else:  # SHORT
                # Check stop hit first
                if bar.high >= stop:
                    trade_result['exit_price'] = stop
                    trade_result['exit_time'] = bar.timestamp
                    trade_result['pnl_ticks'] = -risk_ticks
                    trade_result['outcome'] = 'loss'
                    break
                # Check target 1 hit
                elif targets and bar.low <= targets[0]:
                    trade_result['exit_price'] = targets[0]
                    trade_result['exit_time'] = bar.timestamp
                    trade_result['pnl_ticks'] = abs(entry - targets[0]) / 0.25
                    trade_result['outcome'] = 'win'
                    break

        # If still open at end of session, mark at last price
        if trade_result['outcome'] == 'open':
            last_bar = session_bars[-1]
            trade_result['exit_price'] = last_bar.close
            trade_result['exit_time'] = last_bar.timestamp
            if direction == "LONG":
                trade_result['pnl_ticks'] = (last_bar.close - entry) / 0.25
            else:
                trade_result['pnl_ticks'] = (entry - last_bar.close) / 0.25
            trade_result['outcome'] = 'open (EOD)'

        trade_result['pnl_dollars'] = trade_result['pnl_ticks'] * tick_value
        results.append(trade_result)

    return results


def plot_backtest(symbol: str = "ES", session_date: date = None, interval: str = "3m"):
    """Plot price chart with strategy signals and P/L."""
    if session_date is None:
        session_date = date.today()

    config_path = "config/strategies/ict_es.yaml"

    # Fetch ALL data (including overnight/previous day) for key level calculation
    print(f"Fetching {interval} data for {symbol} from TradingView...")
    all_bars = fetch_futures_bars(
        symbol=symbol,
        interval=interval,
        n_bars=2000,  # Get 2 days of data for key levels
    )

    # Filter to target date for extended session (premarket + RTH)
    # Premarket starts at 4:00 AM ET, RTH ends at 16:00
    premarket_start = dt_time(4, 0)
    rth_start = dt_time(9, 30)
    rth_end = dt_time(16, 0)

    # Get all bars for the target date (premarket + RTH)
    session_bars = [
        b for b in all_bars
        if b.timestamp.date() == session_date
        and premarket_start <= b.timestamp.time() <= rth_end
    ]

    # Get all bars up to and including session for strategy processing
    historical_bars = [
        b for b in all_bars
        if b.timestamp.date() <= session_date
    ]

    print(f"Got {len(session_bars)} RTH bars, {len(historical_bars)} historical bars")

    # Run strategy on ALL historical bars (needed for key level calculation)
    # but only record signals from the target RTH session
    strategy = build_ict_from_yaml(config_path)
    signals = []

    for bar in historical_bars:
        signal = strategy.on_bar(bar)

        # Only record signals from target session (premarket + RTH)
        if bar.timestamp.date() != session_date:
            continue
        if not (premarket_start <= bar.timestamp.time() <= rth_end):
            continue

        if signal:
            if isinstance(signal, list):
                for s in signal:
                    if s:
                        signals.append((bar.timestamp, bar.close, s))
            else:
                signals.append((bar.timestamp, bar.close, signal))

    print(f"Generated {len(signals)} signals")

    # Calculate P/L for each trade
    trade_results = calculate_pnl(signals, session_bars)

    # Print P/L summary
    print(f"\n{'='*60}")
    print("P/L ANALYSIS")
    print(f"{'='*60}")

    total_pnl = 0
    wins = 0
    losses = 0

    for i, tr in enumerate(trade_results, 1):
        total_pnl += tr['pnl_dollars']
        if tr['outcome'] == 'win':
            wins += 1
        elif tr['outcome'] == 'loss':
            losses += 1

        outcome_str = f"{'WIN' if tr['outcome'] == 'win' else 'LOSS' if tr['outcome'] == 'loss' else 'OPEN'}"
        print(f"  {i}. {tr['timestamp'].strftime('%H:%M')} {tr['direction']:5} @ {tr['entry']:.2f} -> {tr['exit_price']:.2f} | {tr['pnl_ticks']:+.0f} ticks | ${tr['pnl_dollars']:+.2f} | {outcome_str}")

    print(f"\n{'='*60}")
    print(f"TOTAL P/L: ${total_pnl:+.2f} ({total_pnl/12.50:+.0f} ticks)")
    print(f"Wins: {wins} | Losses: {losses} | Open: {len(trade_results) - wins - losses}")
    if wins + losses > 0:
        print(f"Win Rate: {wins/(wins+losses)*100:.1f}%")
    print(f"{'='*60}\n")

    # Extract data for plotting
    times = [b.timestamp for b in session_bars]
    opens = [b.open for b in session_bars]
    highs = [b.high for b in session_bars]
    lows = [b.low for b in session_bars]
    closes = [b.close for b in session_bars]

    # Create figure with 2 subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), height_ratios=[3, 1], sharex=True)

    # === TOP PANEL: Price chart with signals ===
    # Plot candlesticks
    for i, bar in enumerate(session_bars):
        color = 'green' if bar.close >= bar.open else 'red'
        ax1.plot([times[i], times[i]], [bar.low, bar.high], color=color, linewidth=0.8)
        ax1.plot([times[i], times[i]], [bar.open, bar.close], color=color, linewidth=2.5)

    # Plot signals with win/loss coloring
    win_long_times, win_long_prices = [], []
    loss_long_times, loss_long_prices = [], []
    win_short_times, win_short_prices = [], []
    loss_short_times, loss_short_prices = [], []
    open_times, open_prices, open_dirs = [], [], []

    for tr in trade_results:
        if tr['direction'] == 'LONG':
            if tr['outcome'] == 'win':
                win_long_times.append(tr['timestamp'])
                win_long_prices.append(tr['entry'])
            elif tr['outcome'] == 'loss':
                loss_long_times.append(tr['timestamp'])
                loss_long_prices.append(tr['entry'])
            else:
                open_times.append(tr['timestamp'])
                open_prices.append(tr['entry'])
                open_dirs.append('LONG')
        else:
            if tr['outcome'] == 'win':
                win_short_times.append(tr['timestamp'])
                win_short_prices.append(tr['entry'])
            elif tr['outcome'] == 'loss':
                loss_short_times.append(tr['timestamp'])
                loss_short_prices.append(tr['entry'])
            else:
                open_times.append(tr['timestamp'])
                open_prices.append(tr['entry'])
                open_dirs.append('SHORT')

    # Plot winning longs (green with gold edge)
    if win_long_times:
        ax1.scatter(win_long_times, win_long_prices, marker='^', color='lime', s=150,
                   edgecolors='gold', linewidths=2, zorder=5, label=f'WIN LONG ({len(win_long_times)})')

    # Plot losing longs (green with black edge)
    if loss_long_times:
        ax1.scatter(loss_long_times, loss_long_prices, marker='^', color='gray', s=100,
                   edgecolors='black', linewidths=1.5, zorder=5, label=f'LOSS LONG ({len(loss_long_times)})')

    # Plot winning shorts (red with gold edge)
    if win_short_times:
        ax1.scatter(win_short_times, win_short_prices, marker='v', color='red', s=150,
                   edgecolors='gold', linewidths=2, zorder=5, label=f'WIN SHORT ({len(win_short_times)})')

    # Plot losing shorts (red with black edge)
    if loss_short_times:
        ax1.scatter(loss_short_times, loss_short_prices, marker='v', color='gray', s=100,
                   edgecolors='black', linewidths=1.5, zorder=5, label=f'LOSS SHORT ({len(loss_short_times)})')

    # Plot open trades (yellow)
    for t, p, d in zip(open_times, open_prices, open_dirs):
        marker = '^' if d == 'LONG' else 'v'
        ax1.scatter([t], [p], marker=marker, color='yellow', s=100,
                   edgecolors='orange', linewidths=1.5, zorder=5)

    ax1.set_ylabel('Price')
    ax1.set_title(f'{symbol} - {session_date} - ICT Strategy P/L Analysis ({len(signals)} trades, ${total_pnl:+.2f})')
    ax1.legend(loc='upper left', fontsize=8)
    ax1.grid(True, alpha=0.3)

    # === BOTTOM PANEL: Cumulative P/L ===
    cumulative_pnl = []
    running_total = 0
    pnl_times = []

    for tr in trade_results:
        running_total += tr['pnl_dollars']
        cumulative_pnl.append(running_total)
        pnl_times.append(tr['exit_time'] if tr['exit_time'] else tr['timestamp'])

    # Plot cumulative P/L line
    if pnl_times:
        ax2.plot(pnl_times, cumulative_pnl, 'b-', linewidth=2, marker='o', markersize=6)
        ax2.axhline(y=0, color='gray', linestyle='--', linewidth=1)

        # Fill green above 0, red below 0
        ax2.fill_between(pnl_times, cumulative_pnl, 0,
                        where=[p >= 0 for p in cumulative_pnl],
                        color='green', alpha=0.3)
        ax2.fill_between(pnl_times, cumulative_pnl, 0,
                        where=[p < 0 for p in cumulative_pnl],
                        color='red', alpha=0.3)

    ax2.set_ylabel('Cumulative P/L ($)')
    ax2.set_xlabel('Time (ET)')
    ax2.grid(True, alpha=0.3)

    # Format x-axis
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax2.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    plt.xticks(rotation=45)

    # Tight layout
    plt.tight_layout()

    # Save to file
    output_file = f"backtest_{symbol}_pnl_{session_date}.png"
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"Chart saved to: {output_file}")
    plt.close()

    return output_file, total_pnl, trade_results


if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "ES"
    interval = sys.argv[2] if len(sys.argv) > 2 else "3m"
    result = plot_backtest(symbol, date.today(), interval)
    if isinstance(result, tuple):
        output_file, total_pnl, _ = result
        print(f"\nFinal P/L: ${total_pnl:+.2f}")
