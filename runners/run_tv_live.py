"""
Live ICT Strategy Runner using TradingView Real-Time Data

Uses tvdatafeed to get real-time ES/NQ futures data from TradingView
and runs the ICT strategy against it.

Supports multiple symbols (ES, NQ) and runs in a continuous loop.
"""
from __future__ import annotations
import os
import time
from pathlib import Path
from datetime import datetime
from tvDatafeed import TvDatafeed, Interval

from core.types import Bar
from strategies.factory import build_ict_from_yaml

# Configuration
SYMBOLS = [
    {"symbol": "ES1!", "exchange": "CME_MINI", "name": "ES", "config": "config/strategies/ict_es.yaml"},
    {"symbol": "NQ1!", "exchange": "CME_MINI", "name": "NQ", "config": "config/strategies/ict_es.yaml"},
]
LOOP_INTERVAL_SECONDS = 180  # 3 minutes
N_BARS = 500
INTERVAL = Interval.in_5_minute


def load_tv_credentials():
    """Load TradingView credentials."""
    env_path = Path("config/tradingview.env")
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

    return (
        os.environ.get("TRADINGVIEW_USERNAME", ""),
        os.environ.get("TRADINGVIEW_PASSWORD", "")
    )


def tv_to_bars(df, symbol: str, timeframe: str) -> list[Bar]:
    """Convert TradingView dataframe to Bar objects."""
    bars = []
    for idx, row in df.iterrows():
        bar = Bar(
            timestamp=idx.to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=int(row["volume"]),
            symbol=symbol,
            timeframe=timeframe
        )
        bars.append(bar)
    return bars


def analyze_symbol(tv, symbol_config: dict, strategy) -> dict:
    """Analyze a single symbol and return results."""
    symbol = symbol_config["symbol"]
    exchange = symbol_config["exchange"]
    name = symbol_config["name"]

    print(f"\n--- {name} ({symbol}) ---")

    # Fetch data
    df = tv.get_hist(
        symbol=symbol,
        exchange=exchange,
        interval=INTERVAL,
        n_bars=N_BARS
    )

    if df is None or df.empty:
        print(f"  No data received for {name}")
        return {"name": name, "bars": 0, "signals": [], "last_bar": None}

    print(f"  Bars: {len(df)} | Range: {df.index[0]} to {df.index[-1]}")
    print(f"  Latest: {df['close'].iloc[-1]:.2f}")

    # Convert to Bar objects
    bars = tv_to_bars(df, name, "5m")

    # Run strategy
    signals = []
    for bar in bars:
        signal = strategy.on_bar(bar)
        if signal:
            signals.append((bar.timestamp, signal))

    return {
        "name": name,
        "bars": len(bars),
        "signals": signals,
        "last_bar": bars[-1] if bars else None
    }


def print_signals(signals: list, symbol_name: str):
    """Print the last few signals for a symbol."""
    if not signals:
        print(f"  No signals for {symbol_name}")
        return

    print(f"\n  {symbol_name} Signals ({len(signals)} total):")
    for i, (ts, signal) in enumerate(signals[-5:], 1):  # Last 5 signals
        # Handle if signal is a list
        if isinstance(signal, list):
            signal = signal[0] if signal else None
        if signal:
            print(f"    {i}. [{ts}] {signal.direction.value} @ {signal.entry_price}")
            print(f"       Stop: {signal.stop_price} | Targets: {signal.targets}")


def run_cycle(tv, strategies: dict):
    """Run one analysis cycle for all symbols."""
    print("\n" + "=" * 60)
    print(f"ICT Strategy Scan - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = []
    for sym_config in SYMBOLS:
        strategy = strategies.get(sym_config["config"])
        if not strategy:
            strategy = build_ict_from_yaml(sym_config["config"])
            strategies[sym_config["config"]] = strategy

        result = analyze_symbol(tv, sym_config, strategy)
        results.append(result)

    # Summary
    print("\n" + "-" * 60)
    print("SUMMARY")
    print("-" * 60)

    for result in results:
        if result["last_bar"]:
            bar = result["last_bar"]
            signal_count = len(result["signals"])
            print(f"{result['name']}: {bar.close:.2f} | {signal_count} signals")
            print_signals(result["signals"], result["name"])

    return results


def main():
    print("=" * 60)
    print("ICT Strategy - TradingView Live Runner")
    print("=" * 60)
    print(f"Symbols: {', '.join(s['name'] for s in SYMBOLS)}")
    print(f"Interval: 5 minutes")
    print(f"Loop: Every {LOOP_INTERVAL_SECONDS // 60} minutes")
    print("-" * 60)

    # Load credentials
    username, password = load_tv_credentials()
    if not username:
        print("Error: No TradingView credentials found")
        return

    # Connect to TradingView
    print(f"\nConnecting as {username}...")
    try:
        tv = TvDatafeed(username, password)
        print("Connected to TradingView!")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    # Cache for strategies
    strategies = {}

    # Run continuous loop
    print(f"\nStarting continuous monitoring (Ctrl+C to stop)...")

    try:
        while True:
            run_cycle(tv, strategies)

            # Wait for next cycle
            next_run = datetime.now().strftime('%H:%M:%S')
            print(f"\n[{next_run}] Waiting {LOOP_INTERVAL_SECONDS // 60} minutes for next scan...")
            time.sleep(LOOP_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\n\nStopped by user.")
        print("=" * 60)


if __name__ == "__main__":
    main()
