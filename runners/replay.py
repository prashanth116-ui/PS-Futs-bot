from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from core.types import Bar, Signal

@dataclass
class ReplayResult:
    signals: list[Signal]
    bars_processed: int

class ReplayEngine:
    def __init__(self, strategy: Any):
        self.strategy = strategy

    def run(self, bars: list[Bar]) -> ReplayResult:
        signals: list[Signal] = []

        for bar in bars:
            out = self.strategy.on_bar(bar)  # your ICTStrategy returns list[Signal] or []
            if out:
                signals.extend(out)

        return ReplayResult(signals=signals, bars_processed=len(bars))
