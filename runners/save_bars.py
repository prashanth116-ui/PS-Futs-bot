"""
CLI script to backfill local bar storage with current TradingView data.

Usage:
    python -m runners.save_bars ES NQ MES MNQ
    python -m runners.save_bars ES          # single symbol
"""
import sys
sys.path.insert(0, '.')

from runners.tradingview_loader import fetch_futures_bars
from runners.bar_storage import save_daily_bars


def main():
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ['ES', 'NQ', 'MES', 'MNQ']

    for symbol in symbols:
        print(f"Fetching {symbol} 3m bars from TradingView...")
        bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=10000)
        if not bars:
            print(f"  No data for {symbol}")
            continue

        dates = sorted(set(b.timestamp.strftime("%Y-%m-%d") for b in bars))
        print(f"  Got {len(bars)} bars across {len(dates)} dates ({dates[0]} to {dates[-1]})")

        created = save_daily_bars(symbol, bars)
        if created:
            print(f"  Saved {len(created)} new CSV files")
            for p in created:
                print(f"    {p}")
        else:
            print(f"  All dates already saved (no new files)")
        print()

    print("Done.")


if __name__ == '__main__':
    main()
