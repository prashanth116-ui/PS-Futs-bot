from __future__ import annotations
import csv
from datetime import datetime
from pathlib import Path

from core.types import Bar

def load_csv_bars(path: str | Path) -> list[Bar]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSV not found: {p.resolve()}")

    bars: list[Bar] = []
    with p.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        if not r.fieldnames:
            raise ValueError("CSV has no header row.")

        # normalize header names (sometimes CSVs vary in case)
        fieldnames = [h.strip() for h in r.fieldnames]
        # quick sanity check
        required = {"timestamp","open","high","low","close","volume","symbol","timeframe"}
        if set(fieldnames) < required:
            raise ValueError(f"CSV missing columns. Found={fieldnames}")

        for row in r:
            ts = row["timestamp"].strip()
            # handles "2026-01-13T09:30:00"
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
