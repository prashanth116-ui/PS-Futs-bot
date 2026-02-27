"""
Core Bar type for the TTFM standalone strategy.

Defines the Bar dataclass representing a single price candlestick (OHLCV data).
This is the only type shared across all TTFM modules.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Bar:
    """A single price bar (candlestick) of market data.

    Attributes:
        timestamp: When this bar opened (timezone-aware or naive ET).
        open: First traded price.
        high: Highest price reached.
        low: Lowest price reached.
        close: Last traded price.
        volume: Number of contracts traded (0 if unavailable).
        symbol: Instrument identifier (e.g., "ES", "NQ").
        timeframe: Bar duration string (e.g., "3m", "15m", "1h", "1d").
    """
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    symbol: str = ""
    timeframe: str = ""

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def upper_wick(self) -> float:
        body_top = max(self.open, self.close)
        return self.high - body_top

    @property
    def lower_wick(self) -> float:
        body_bottom = min(self.open, self.close)
        return body_bottom - self.low
