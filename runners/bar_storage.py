"""
Local bar storage for deeper backtests.

TradingView caps 3m bar history at ~6,800 bars (15 trading days).
This module saves bars to CSV daily and merges local + live data
to enable 30+ day backtests.

Storage layout: data/bars/{symbol}/YYYY-MM-DD.csv
CSV format matches data_loader.py: timestamp,open,high,low,close,volume,symbol,timeframe
"""
from __future__ import annotations

import csv
from datetime import datetime, date, timedelta
from pathlib import Path

from core.types import Bar
from runners.data_loader import load_csv_bars
from runners.tradingview_loader import fetch_futures_bars

# Root directory for bar storage
_BARS_DIR = Path(__file__).parent.parent / "data" / "bars"

# Maximum retention period — CSVs older than this are deleted on save
_MAX_RETENTION_DAYS = 90  # 3 months


def save_daily_bars(symbol: str, bars: list[Bar]) -> list[Path]:
    """
    Save bars to per-date CSV files under data/bars/{symbol}/.

    Idempotent: skips dates that already have a CSV on disk.
    Returns list of newly created file paths.
    """
    if not bars:
        return []

    sym_dir = _BARS_DIR / symbol.upper()
    sym_dir.mkdir(parents=True, exist_ok=True)

    # Group bars by date
    by_date: dict[str, list[Bar]] = {}
    for b in bars:
        date_str = b.timestamp.strftime("%Y-%m-%d")
        by_date.setdefault(date_str, []).append(b)

    created: list[Path] = []
    for date_str, day_bars in sorted(by_date.items()):
        csv_path = sym_dir / f"{date_str}.csv"
        if csv_path.exists():
            continue

        # Sort by timestamp within the day
        day_bars.sort(key=lambda b: b.timestamp)

        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"])
            for b in day_bars:
                writer.writerow([
                    b.timestamp.strftime("%Y-%m-%dT%H:%M:%S"),
                    b.open,
                    b.high,
                    b.low,
                    b.close,
                    b.volume,
                    b.symbol,
                    b.timeframe,
                ])
        created.append(csv_path)

    # Prune CSVs older than 3 months
    cutoff = date.today() - timedelta(days=_MAX_RETENTION_DAYS)
    for csv_path in sym_dir.glob("*.csv"):
        try:
            file_date = date.fromisoformat(csv_path.stem)
            if file_date < cutoff:
                csv_path.unlink()
        except ValueError:
            pass

    return created


def load_local_bars(symbol: str) -> list[Bar]:
    """
    Load all locally stored CSVs for a symbol.

    Returns list[Bar] sorted chronologically, deduplicated by timestamp.
    """
    sym_dir = _BARS_DIR / symbol.upper()
    if not sym_dir.exists():
        return []

    cutoff = date.today() - timedelta(days=_MAX_RETENTION_DAYS)
    csv_files = sorted(sym_dir.glob("*.csv"))
    if not csv_files:
        return []

    all_bars: list[Bar] = []
    for csv_path in csv_files:
        # Skip files older than retention period
        try:
            file_date = date.fromisoformat(csv_path.stem)
            if file_date < cutoff:
                continue
        except ValueError:
            pass
        try:
            all_bars.extend(load_csv_bars(csv_path))
        except Exception as e:
            print(f"  Warning: failed to load {csv_path}: {e}")

    # Deduplicate by timestamp and sort
    seen: set[datetime] = set()
    unique: list[Bar] = []
    for b in sorted(all_bars, key=lambda b: b.timestamp):
        if b.timestamp not in seen:
            seen.add(b.timestamp)
            unique.append(b)

    return unique


def load_bars_with_history(
    symbol: str,
    interval: str = "3m",
    n_bars: int = 10000,
) -> list[Bar]:
    """
    Merge local stored bars with live TradingView bars.

    Fetches live bars from TradingView, loads local bars from disk,
    merges and deduplicates by timestamp. Returns combined list sorted
    chronologically.
    """
    # Fetch live bars from TradingView
    live_bars = fetch_futures_bars(symbol=symbol, interval=interval, n_bars=n_bars)

    # Load local bars from disk
    local_bars = load_local_bars(symbol)

    if not local_bars:
        return live_bars
    if not live_bars:
        return local_bars

    # Merge + deduplicate by timestamp
    combined = local_bars + live_bars
    seen: set[datetime] = set()
    unique: list[Bar] = []
    for b in sorted(combined, key=lambda b: b.timestamp):
        if b.timestamp not in seen:
            seen.add(b.timestamp)
            unique.append(b)

    return unique
