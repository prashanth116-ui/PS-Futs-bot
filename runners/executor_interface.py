"""
Executor Interface - Abstract base class for trade execution backends.

Both WebhookExecutor (PickMyTrade) and TradovateExecutor (direct API)
implement this interface, so the LiveTrader can use either interchangeably.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional


class ExecutorInterface(ABC):
    """Abstract base class for trade execution backends.

    The LiveTrader's paper mode is the "brain" — it manages the full trade
    lifecycle and calls these methods at each lifecycle event. The executor
    handles broker-side execution.
    """

    @abstractmethod
    def open_position(
        self,
        symbol: str,
        direction: str,
        contracts: int,
        stop_price: float,
        entry_price: float,
        paper_trade_id: str = "",
    ) -> Dict:
        """Open a new position with an initial protective stop."""
        ...

    @abstractmethod
    def partial_close(
        self,
        symbol: str,
        direction: str,
        contracts: int,
        paper_trade_id: str = "",
    ) -> Dict:
        """Close part of a position (T1/T2 exits)."""
        ...

    @abstractmethod
    def update_stop(
        self,
        symbol: str,
        direction: str,
        new_stop_price: float,
        entry_price: float,
        paper_trade_id: str = "",
    ) -> Dict:
        """Update the broker-side stop loss price."""
        ...

    @abstractmethod
    def close_position(
        self,
        symbol: str,
        direction: str,
        paper_trade_id: str = "",
    ) -> Dict:
        """Close entire remaining position for a trade."""
        ...

    @abstractmethod
    def close_all(self, symbol: Optional[str] = None) -> Dict:
        """Close all positions, optionally filtered by symbol."""
        ...

    @abstractmethod
    def get_account_count(self) -> int:
        """Return number of enabled accounts."""
        ...
