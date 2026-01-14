"""
Base Strategy Module

Defines the abstract base class for all trading strategies.
Provides common interfaces for signal generation, position management,
and risk control that all strategy implementations must follow.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

    from core.types import Bar, Signal


class Strategy(ABC):
    """
    Abstract base class for all trading strategies.

    A Strategy receives market data (bars) and produces trading signals.
    It also handles fill notifications to track its own state.

    Subclasses must implement:
        - on_bar(): Process new bar data and generate signals
        - on_fill(): React to order fills

    Attributes:
        name (str): A human-readable name for this strategy instance.
                    Used for logging, reporting, and identification.
        params (dict): Configuration parameters for this strategy.
                       Can include thresholds, timeframes, indicator settings, etc.

    Example:
        from core.types import Bar, Signal, Direction

        class MyStrategy(Strategy):
            def on_bar(self, bar: Bar) -> list[Signal]:
                # Analyze bar, return list of Signal objects
                return []

            def on_fill(self, fill_event) -> None:
                # Update internal state based on fill
                pass
    """

    def __init__(self, name: str, params: dict | None = None) -> None:
        """
        Initialize the strategy with a name and optional parameters.

        Args:
            name: A descriptive name for this strategy instance.
                  Example: "ICT_Silver_Bullet_5min"
            params: A dictionary of configuration parameters.
                    Defaults to an empty dict if not provided.
                    Example: {"lookback": 20, "threshold": 0.5}
        """
        self.name: str = name
        self.params: dict = params if params is not None else {}

    def reset_daily(self) -> None:
        """
        Reset strategy state at the start of each trading day.

        Called automatically at the beginning of each new trading session.
        Override this method to clear any day-specific state such as:
            - Daily trade counts
            - Accumulated P&L for the day
            - Intraday indicators or buffers
            - Session-specific flags

        The default implementation does nothing. Subclasses should override
        this method if they maintain any state that needs daily resetting.

        Example:
            def reset_daily(self) -> None:
                self.trades_today = 0
                self.daily_pnl = 0.0
                self.has_traded_session = False
        """
        pass

    @abstractmethod
    def on_bar(self, bar: "Bar") -> list["Signal"]:
        """
        Process a new price bar and generate trading signals.

        This is the core method where strategy logic lives. It receives
        market data and decides whether to generate any trading signals.

        Args:
            bar: A Bar dataclass containing OHLCV data and timestamp.
                 See core.types.Bar for the full structure.

        Returns:
            A list of Signal objects representing trading intentions.
            Return an empty list if no signals are generated.
            Each Signal will be processed by the execution engine.

        Note:
            - This method is called once per bar, in chronological order
            - Do NOT place orders directly; return Signal objects instead
            - Keep this method fast; heavy computation should be cached
            - Signal is defined in core.types

        Example:
            def on_bar(self, bar: Bar) -> list[Signal]:
                signals = []
                if self.should_buy(bar):
                    signals.append(Signal(
                        symbol="ES",
                        direction=Direction.LONG,
                        entry_price=bar.close,
                        stop_price=bar.low,
                        target_prices=[bar.close + 10],
                        risk_units=1.0,
                        reason={"setup": "Example signal"}
                    ))
                return signals
        """
        pass

    @abstractmethod
    def on_fill(self, fill_event: "Any") -> None:
        """
        Handle notification that an order has been filled.

        Called by the execution engine when a trade is executed.
        Use this to update internal strategy state based on fills.

        Args:
            fill_event: Information about the completed trade.
                        Will be a FillEvent dataclass (to be defined in core.types).
                        Typically includes: symbol, side, quantity,
                        fill_price, timestamp, order_id, etc.

        Returns:
            None. This method updates internal state only.

        Common uses:
            - Track current position size
            - Record entry prices for stop/target calculations
            - Update trade statistics
            - Log trade information

        Example:
            def on_fill(self, fill_event) -> None:
                if fill_event.side == "buy":
                    self.position_size += fill_event.quantity
                    self.entry_price = fill_event.fill_price
        """
        pass
