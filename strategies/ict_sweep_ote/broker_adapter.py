"""
ICT_Sweep_OTE_MSS_FVG_Long_v1 - Broker Adapter Interface

Abstract interface for connecting to different brokers/platforms.
Implementations can include:
- Tradovate
- Interactive Brokers
- NinjaTrader
- Paper trading
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal, Callable
from enum import Enum
import logging

from strategies.ict_sweep_ote.signals import TradeSignal, SignalDirection


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Order:
    """Represents a broker order."""
    order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType
    price: Optional[float] = None  # For limit/stop orders
    stop_price: Optional[float] = None  # For stop orders
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    filled_price: float = 0.0
    submitted_time: Optional[datetime] = None
    filled_time: Optional[datetime] = None
    parent_order_id: Optional[str] = None  # For bracket orders
    metadata: dict = field(default_factory=dict)


@dataclass
class Position:
    """Represents an open position."""
    symbol: str
    quantity: int  # Positive for long, negative for short
    avg_entry_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    market_value: float = 0.0


@dataclass
class AccountInfo:
    """Broker account information."""
    account_id: str
    equity: float
    cash: float
    buying_power: float
    margin_used: float = 0.0
    margin_available: float = 0.0
    daily_pnl: float = 0.0


class BrokerAdapter(ABC):
    """
    Abstract base class for broker connections.

    Implementations should handle:
    - Order submission and management
    - Position tracking
    - Account information
    - Real-time data subscriptions
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self._connected = False
        self._order_callbacks: list[Callable[[Order], None]] = []
        self._position_callbacks: list[Callable[[Position], None]] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    # =========================================================================
    # CONNECTION
    # =========================================================================

    @abstractmethod
    def connect(self) -> bool:
        """
        Establish connection to broker.

        Returns:
            True if connection successful
        """
        pass

    @abstractmethod
    def disconnect(self):
        """Disconnect from broker."""
        pass

    # =========================================================================
    # ACCOUNT
    # =========================================================================

    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        """Get current account information."""
        pass

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Get all open positions."""
        pass

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for specific symbol."""
        positions = self.get_positions()
        for pos in positions:
            if pos.symbol.upper() == symbol.upper():
                return pos
        return None

    # =========================================================================
    # ORDER MANAGEMENT
    # =========================================================================

    @abstractmethod
    def submit_order(self, order: Order) -> str:
        """
        Submit order to broker.

        Args:
            order: Order to submit

        Returns:
            Order ID from broker
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.

        Returns:
            True if cancellation successful
        """
        pass

    @abstractmethod
    def modify_order(self, order_id: str, new_price: float = None, new_quantity: int = None) -> bool:
        """
        Modify an existing order.

        Returns:
            True if modification successful
        """
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> Order:
        """Get current status of an order."""
        pass

    @abstractmethod
    def get_open_orders(self, symbol: str = None) -> list[Order]:
        """Get all open orders, optionally filtered by symbol."""
        pass

    # =========================================================================
    # BRACKET ORDERS
    # =========================================================================

    def submit_bracket_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: int,
        entry_price: float,
        stop_price: float,
        take_profit_prices: list[float],
        tp_quantities: list[int] = None,
        order_type: OrderType = OrderType.LIMIT,
    ) -> tuple[str, list[str]]:
        """
        Submit a bracket order (entry + SL + TPs).

        Args:
            symbol: Trading symbol
            side: BUY or SELL
            quantity: Total position size
            entry_price: Entry price (for limit orders)
            stop_price: Stop loss price
            take_profit_prices: List of TP prices
            tp_quantities: List of quantities for each TP (defaults to equal split)
            order_type: Entry order type

        Returns:
            Tuple of (entry_order_id, [exit_order_ids])
        """
        # Default: split quantity equally among TPs
        if tp_quantities is None:
            base_qty = quantity // len(take_profit_prices)
            tp_quantities = [base_qty] * len(take_profit_prices)
            # Add remainder to first TP
            tp_quantities[0] += quantity - sum(tp_quantities)

        # Create entry order
        entry_order = Order(
            order_id="",  # Will be assigned by broker
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=entry_price if order_type != OrderType.MARKET else None,
        )
        entry_id = self.submit_order(entry_order)

        # Create stop loss order
        sl_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        sl_order = Order(
            order_id="",
            symbol=symbol,
            side=sl_side,
            quantity=quantity,
            order_type=OrderType.STOP,
            stop_price=stop_price,
            parent_order_id=entry_id,
        )
        sl_id = self.submit_order(sl_order)

        # Create take profit orders
        tp_ids = []
        tp_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        for tp_price, tp_qty in zip(take_profit_prices, tp_quantities):
            tp_order = Order(
                order_id="",
                symbol=symbol,
                side=tp_side,
                quantity=tp_qty,
                order_type=OrderType.LIMIT,
                price=tp_price,
                parent_order_id=entry_id,
            )
            tp_id = self.submit_order(tp_order)
            tp_ids.append(tp_id)

        return entry_id, [sl_id] + tp_ids

    # =========================================================================
    # SIGNAL EXECUTION
    # =========================================================================

    def execute_signal(
        self,
        signal: TradeSignal,
        use_market_entry: bool = False,
    ) -> tuple[str, list[str]]:
        """
        Execute a trade signal by creating appropriate orders.

        Args:
            signal: TradeSignal from strategy
            use_market_entry: If True, use market order for entry

        Returns:
            Tuple of (entry_order_id, [exit_order_ids])
        """
        side = OrderSide.BUY if signal.direction == SignalDirection.LONG else OrderSide.SELL
        order_type = OrderType.MARKET if use_market_entry else OrderType.LIMIT

        # Calculate TP quantities based on config
        # Default: 50% TP1, 30% TP2, 20% TP3
        tp_pcts = [0.50, 0.30, 0.20]
        tp_quantities = []
        remaining = signal.position_size

        for i, pct in enumerate(tp_pcts):
            if i < len(signal.targets):
                qty = int(signal.position_size * pct)
                qty = min(qty, remaining)
                tp_quantities.append(qty)
                remaining -= qty

        # Add any remainder to last TP
        if remaining > 0 and tp_quantities:
            tp_quantities[-1] += remaining

        return self.submit_bracket_order(
            symbol=signal.symbol,
            side=side,
            quantity=signal.position_size,
            entry_price=signal.entry_price,
            stop_price=signal.stop_price,
            take_profit_prices=signal.targets[:len(tp_quantities)],
            tp_quantities=tp_quantities,
            order_type=order_type,
        )

    # =========================================================================
    # CALLBACKS
    # =========================================================================

    def on_order_update(self, callback: Callable[[Order], None]):
        """Register callback for order updates."""
        self._order_callbacks.append(callback)

    def on_position_update(self, callback: Callable[[Position], None]):
        """Register callback for position updates."""
        self._position_callbacks.append(callback)

    def _notify_order_update(self, order: Order):
        """Notify all registered callbacks of order update."""
        for cb in self._order_callbacks:
            try:
                cb(order)
            except Exception as e:
                self.logger.error(f"Order callback error: {e}")

    def _notify_position_update(self, position: Position):
        """Notify all registered callbacks of position update."""
        for cb in self._position_callbacks:
            try:
                cb(position)
            except Exception as e:
                self.logger.error(f"Position callback error: {e}")


# =============================================================================
# PAPER TRADING IMPLEMENTATION
# =============================================================================

class PaperBroker(BrokerAdapter):
    """
    Paper trading broker for backtesting and simulation.

    Simulates order execution with configurable slippage and latency.
    """

    def __init__(
        self,
        starting_equity: float = 100000.0,
        slippage_ticks: float = 0.5,
        commission_per_contract: float = 2.25,
        config: dict = None,
    ):
        super().__init__(config)
        self.starting_equity = starting_equity
        self.equity = starting_equity
        self.slippage_ticks = slippage_ticks
        self.commission = commission_per_contract

        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._order_counter = 0
        self._current_prices: dict[str, float] = {}

    def connect(self) -> bool:
        self._connected = True
        self.logger.info("Paper broker connected")
        return True

    def disconnect(self):
        self._connected = False
        self.logger.info("Paper broker disconnected")

    def get_account_info(self) -> AccountInfo:
        return AccountInfo(
            account_id="PAPER",
            equity=self.equity,
            cash=self.equity,
            buying_power=self.equity * 4,  # 4:1 margin for futures
            margin_used=0,
            margin_available=self.equity * 4,
        )

    def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    def submit_order(self, order: Order) -> str:
        self._order_counter += 1
        order_id = f"PAPER_{self._order_counter:06d}"
        order.order_id = order_id
        order.status = OrderStatus.SUBMITTED
        order.submitted_time = datetime.now()
        self._orders[order_id] = order
        self.logger.info(f"Order submitted: {order_id} {order.side.value} {order.quantity} {order.symbol}")
        return order_id

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self._orders:
            order = self._orders[order_id]
            if order.status in [OrderStatus.PENDING, OrderStatus.SUBMITTED]:
                order.status = OrderStatus.CANCELLED
                self.logger.info(f"Order cancelled: {order_id}")
                return True
        return False

    def modify_order(self, order_id: str, new_price: float = None, new_quantity: int = None) -> bool:
        if order_id in self._orders:
            order = self._orders[order_id]
            if new_price is not None:
                order.price = new_price
            if new_quantity is not None:
                order.quantity = new_quantity
            self.logger.info(f"Order modified: {order_id}")
            return True
        return False

    def get_order_status(self, order_id: str) -> Order:
        return self._orders.get(order_id)

    def get_open_orders(self, symbol: str = None) -> list[Order]:
        orders = []
        for order in self._orders.values():
            if order.status in [OrderStatus.PENDING, OrderStatus.SUBMITTED]:
                if symbol is None or order.symbol.upper() == symbol.upper():
                    orders.append(order)
        return orders

    def update_price(self, symbol: str, price: float):
        """Update current price and check for order fills."""
        self._current_prices[symbol.upper()] = price
        self._check_order_fills(symbol, price)

    def _check_order_fills(self, symbol: str, price: float):
        """Check if any orders should be filled at current price."""
        for order in list(self._orders.values()):
            if order.symbol.upper() != symbol.upper():
                continue
            if order.status != OrderStatus.SUBMITTED:
                continue

            filled = False
            fill_price = price

            if order.order_type == OrderType.MARKET:
                filled = True
                # Add slippage
                if order.side == OrderSide.BUY:
                    fill_price = price + (self.slippage_ticks * 0.25)
                else:
                    fill_price = price - (self.slippage_ticks * 0.25)

            elif order.order_type == OrderType.LIMIT:
                if order.side == OrderSide.BUY and price <= order.price:
                    filled = True
                    fill_price = order.price
                elif order.side == OrderSide.SELL and price >= order.price:
                    filled = True
                    fill_price = order.price

            elif order.order_type == OrderType.STOP:
                if order.side == OrderSide.BUY and price >= order.stop_price:
                    filled = True
                    fill_price = order.stop_price + (self.slippage_ticks * 0.25)
                elif order.side == OrderSide.SELL and price <= order.stop_price:
                    filled = True
                    fill_price = order.stop_price - (self.slippage_ticks * 0.25)

            if filled:
                self._fill_order(order, fill_price)

    def _fill_order(self, order: Order, fill_price: float):
        """Fill an order and update positions."""
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.filled_price = fill_price
        order.filled_time = datetime.now()

        # Update position
        symbol = order.symbol.upper()
        qty_delta = order.quantity if order.side == OrderSide.BUY else -order.quantity

        if symbol in self._positions:
            pos = self._positions[symbol]
            old_qty = pos.quantity
            new_qty = old_qty + qty_delta

            if new_qty == 0:
                # Position closed
                del self._positions[symbol]
            else:
                # Update average price
                if (old_qty > 0 and qty_delta > 0) or (old_qty < 0 and qty_delta < 0):
                    # Adding to position
                    total_value = (pos.avg_entry_price * abs(old_qty)) + (fill_price * abs(qty_delta))
                    pos.avg_entry_price = total_value / abs(new_qty)
                pos.quantity = new_qty
        else:
            # New position
            self._positions[symbol] = Position(
                symbol=symbol,
                quantity=qty_delta,
                avg_entry_price=fill_price,
            )

        # Calculate commission
        commission = self.commission * order.quantity
        self.equity -= commission

        self.logger.info(
            f"Order filled: {order.order_id} @ {fill_price:.2f} "
            f"(commission: ${commission:.2f})"
        )

        self._notify_order_update(order)


# =============================================================================
# TRADOVATE ADAPTER (STUB)
# =============================================================================

class TradovateAdapter(BrokerAdapter):
    """
    Tradovate broker adapter.

    This is a stub that would need to be implemented with
    Tradovate's REST API and WebSocket connections.

    API Documentation: https://api.tradovate.com/
    """

    def __init__(self, api_key: str = None, api_secret: str = None, config: dict = None):
        super().__init__(config)
        self.api_key = api_key
        self.api_secret = api_secret
        # Would need:
        # - Authentication handling
        # - WebSocket connection for real-time data
        # - REST client for order management

    def connect(self) -> bool:
        # TODO: Implement Tradovate authentication
        raise NotImplementedError("Tradovate adapter not yet implemented")

    def disconnect(self):
        raise NotImplementedError()

    def get_account_info(self) -> AccountInfo:
        raise NotImplementedError()

    def get_positions(self) -> list[Position]:
        raise NotImplementedError()

    def submit_order(self, order: Order) -> str:
        raise NotImplementedError()

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError()

    def modify_order(self, order_id: str, new_price: float = None, new_quantity: int = None) -> bool:
        raise NotImplementedError()

    def get_order_status(self, order_id: str) -> Order:
        raise NotImplementedError()

    def get_open_orders(self, symbol: str = None) -> list[Order]:
        raise NotImplementedError()
