"""
Run ICT strategy with live/recent data from Yahoo Finance.
"""
from __future__ import annotations


def main():
    print("=" * 50)
    print("ICT Strategy - Live Data Runner")
    print("=" * 50)

    from runners.yfinance_loader import fetch_futures_bars
    from runners.replay import ReplayEngine
    from strategies.factory import build_ict_from_yaml

    # Configuration
    symbol = "ES=F"
    period = "5d"      # Last 5 days
    interval = "5m"    # 5-minute bars
    config_path = "config/strategies/ict_es.yaml"

    print(f"\nSymbol: {symbol}")
    print(f"Period: {period}")
    print(f"Interval: {interval}")
    print(f"Config: {config_path}")
    print("-" * 50)

    # Fetch data
    print("\nFetching data from Yahoo Finance...")
    bars = fetch_futures_bars(symbol=symbol, period=period, interval=interval)
    print(f"Received {len(bars)} bars")

    if not bars:
        print("No data received. Market may be closed.")
        return

    print(f"Date range: {bars[0].timestamp} to {bars[-1].timestamp}")
    print("-" * 50)

    # Build strategy
    print("\nLoading ICT strategy...")
    strategy = build_ict_from_yaml(config_path)

    # Run replay
    print("Running strategy...")
    engine = ReplayEngine(strategy)
    result = engine.run(bars)

    # Results
    print("\n" + "=" * 50)
    print("RESULTS")
    print("=" * 50)
    print(f"Bars processed: {result.bars_processed}")
    print(f"Signals generated: {len(result.signals)}")

    if result.signals:
        print("\n--- Signals ---")
        for i, signal in enumerate(result.signals[:10], 1):
            print(f"{i}. {signal}")
        if len(result.signals) > 10:
            print(f"   ... and {len(result.signals) - 10} more")
    else:
        print("\nNo signals generated.")
        print("This could mean:")
        print("  - Market conditions don't match ICT criteria")
        print("  - Outside killzone hours")
        print("  - No liquidity sweeps detected")


if __name__ == "__main__":
    main()
