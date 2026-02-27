"""
Local bar storage for TTFM standalone strategy.

Saves bars to CSV daily and merges local + live data for 30+ day backtests.
Storage layout: data/bars/{symbol}/YYYY-MM-DD.csv
"""
from __future__ import annotations

import csv
from datetime import datetime, date, timedelta
from pathlib import Path

from ttfm.core import Bar
from ttfm.data_loader import load_csv_bars
from ttfm.tradingview_loader import fetch_futures_bars

# Root directory for bar storage
_BARS_DIR = Path(__file__).parent.parent / "data" / "bars"

# Maximum retention period
_MAX_RETENTION_DAYS = 90


def save_daily_bars(symbol: str, bars: list[Bar]) -> list[Path]:
    """Save bars to per-date CSV files. Idempotent: skips existing dates."""
    if not bars:
        return []

    sym_dir = _BARS_DIR / symbol.upper()
    sym_dir.mkdir(parents=True, exist_ok=True)

    by_date: dict[str, list[Bar]] = {}
    for b in bars:
        date_str = b.timestamp.strftime("%Y-%m-%d")
        by_date.setdefault(date_str, []).append(b)

    created: list[Path] = []
    for date_str, day_bars in sorted(by_date.items()):
        csv_path = sym_dir / f"{date_str}.csv"
        if csv_path.exists():
            continue

        day_bars.sort(key=lambda b: b.timestamp)

        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"])
            for b in day_bars:
                writer.writerow([
                    b.timestamp.strftime("%Y-%m-%dT%H:%M:%S"),
                    b.open, b.high, b.low, b.close,
                    b.volume, b.symbol, b.timeframe,
                ])
        created.append(csv_path)

    # Prune old CSVs
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
    """Load all locally stored CSVs for a symbol."""
    sym_dir = _BARS_DIR / symbol.upper()
    if not sym_dir.exists():
        return []

    cutoff = date.today() - timedelta(days=_MAX_RETENTION_DAYS)
    csv_files = sorted(sym_dir.glob("*.csv"))
    if not csv_files:
        return []

    all_bars: list[Bar] = []
    for csv_path in csv_files:
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
    """Merge local stored bars with live TradingView bars."""
    live_bars = fetch_futures_bars(symbol=symbol, interval=interval, n_bars=n_bars)
    local_bars = load_local_bars(symbol)

    if not local_bars:
        return live_bars
    if not live_bars:
        return local_bars

    combined = local_bars + live_bars
    seen: set[datetime] = set()
    unique: list[Bar] = []
    for b in sorted(combined, key=lambda b: b.timestamp):
        if b.timestamp not in seen:
            seen.add(b.timestamp)
            unique.append(b)

    return unique
