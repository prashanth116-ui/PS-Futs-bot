"""Load bars from CSV files for the TTFM standalone strategy."""
from __future__ import annotations
import csv
from datetime import datetime
from pathlib import Path

from ttfm.core import Bar


def load_csv_bars(path: str | Path) -> list[Bar]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSV not found: {p.resolve()}")

    bars: list[Bar] = []
    with p.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        if not r.fieldnames:
            raise ValueError("CSV has no header row.")

        fieldnames = [h.strip() for h in r.fieldnames]
        required = {"timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"}
        if set(fieldnames) < required:
            raise ValueError(f"CSV missing columns. Found={fieldnames}")

        for row in r:
            ts = row["timestamp"].strip()
            timestamp = datetime.fromisoformat(ts)

            bars.append(
                Bar(
                    timestamp=timestamp,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    symbol=row["symbol"].strip(),
                    timeframe=row["timeframe"].strip(),
                )
            )
    return bars
