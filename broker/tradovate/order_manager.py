"""
Tradovate Order Manager

Handles order execution, management, and position tracking.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from enum import Enum
from datetime import datetime

from core.types import Signal, Direction
from broker.tradovate.api_client import TradovateClient


class OrderStatus(Enum):
    PENDING = "Pending"
    WORKING = "Working"
    FILLED = "Filled"
    CANCELLED = "Cancelled"
    REJECTED = "Rejected"


@dataclass
class Order:
    """Represents a trading order."""
    id: Optional[int] = None
    symbol: str = ""
    action: str = ""  # "Buy" or "Sell"
    qty: int = 0
    order_type: str = "Market"
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: int = 0
    avg_fill_price: Optional[float] = None
    created_at: datetime = None
    signal_reason: Optional[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


@dataclass
class Position:
    """Represents a trading position."""
    symbol: str
    qty: int  # Positive for long, negative for short
    avg_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0


class OrderManager:
    """
    Manages order execution and position tracking.

    Converts strategy signals into actual orders.
    """

    def __init__(self, client: TradovateClient, default_qty: int = 1):
        self.client = client
        self.default_qty = default_qty
        self.orders: dict[int, Order] = {}
        self.positions: dict[str, Position] = {}

        # Risk limits
        self.max_position_size = 5  # Max contracts per symbol
        self.max_daily_loss = 500.0  # Max daily loss in dollars
        self.daily_pnl = 0.0

    def can_trade(self, symbol: str, direction: Direction, qty: int = 1) -> tuple[bool, str]:
        """
        Check if we can take a trade based on risk limits.

        Returns (can_trade, reason)
        """
        # Check daily loss limit
        if self.daily_pnl <= -self.max_daily_loss:
            return False, f"Daily loss limit reached: ${self.daily_pnl:.2f}"

        # Check position size
        current_pos = self.positions.get(symbol)
        if current_pos:
            new_qty = current_pos.qty
            if direction == Direction.LONG:
                new_qty += qty
            else:
                new_qty -= qty

            if abs(new_qty) > self.max_position_size:
                return False, f"Position size limit: {abs(new_qty)} > {self.max_position_size}"

        return True, "OK"

    def signal_to_order(self, signal: Signal, qty: Optional[int] = None) -> Order:
        """Convert a strategy signal to an order."""
        qty = qty or self.default_qty

        # Determine action
        action = "Buy" if signal.direction == Direction.LONG else "Sell"

        # Determine order type
        if signal.entry_type.value == "MARKET":
            order_type = "Market"
            price = None
        elif signal.entry_type.value == "LIMIT":
            order_type = "Limit"
            price = signal.entry_price
        elif signal.entry_type.value == "STOP":
            order_type = "Stop"
            price = None
        else:
            order_type = "Market"
            price = None

        return Order(
            symbol=signal.symbol,
            action=action,
            qty=qty,
            order_type=order_type,
            price=price,
            stop_price=signal.stop_price if order_type in ["Stop", "StopLimit"] else None,
            signal_reason=str(signal.reason)
        )

    def execute_signal(self, signal: Signal, qty: Optional[int] = None) -> Optional[Order]:
        """
        Execute a strategy signal.

        Args:
            signal: The trading signal from the strategy
            qty: Number of contracts (uses default if not specified)

        Returns:
            Order object if submitted, None if rejected
        """
        qty = qty or self.default_qty

        # Risk check
        can_trade, reason = self.can_trade(signal.symbol, signal.direction, qty)
        if not can_trade:
            print(f"Trade rejected: {reason}")
            return None

        # Convert signal to order
        order = self.signal_to_order(signal, qty)

        # Submit to Tradovate
        result = self.client.place_order(
            symbol=order.symbol,
            action=order.action,
            qty=order.qty,
            order_type=order.order_type,
            price=order.price,
            stop_price=order.stop_price
        )

        if result:
            order.id = result.get("orderId")
            order.status = OrderStatus.WORKING
            self.orders[order.id] = order
            print(f"Order submitted: {order}")
            return order
        else:
            order.status = OrderStatus.REJECTED
            print("Order rejected by broker")
            return None

    def execute_bracket(
        self,
        signal: Signal,
        qty: Optional[int] = None
    ) -> list[Order]:
        """
        Execute a bracket order (entry + stop + targets).

        Args:
            signal: The trading signal with stop and targets
            qty: Number of contracts

        Returns:
            List of orders (entry, stop, targets)
        """
        orders = []
        qty = qty or self.default_qty

        # Entry order
        entry_order = self.execute_signal(signal, qty)
        if not entry_order:
            return orders
        orders.append(entry_order)

        # Stop loss order
        stop_action = "Sell" if signal.direction == Direction.LONG else "Buy"
        stop_result = self.client.place_order(
            symbol=signal.symbol,
            action=stop_action,
            qty=qty,
            order_type="Stop",
            stop_price=signal.stop_price
        )
        if stop_result:
            stop_order = Order(
                id=stop_result.get("orderId"),
                symbol=signal.symbol,
                action=stop_action,
                qty=qty,
                order_type="Stop",
                stop_price=signal.stop_price,
                status=OrderStatus.WORKING
            )
            self.orders[stop_order.id] = stop_order
            orders.append(stop_order)

        # Target orders (scale out)
        if signal.targets:
            target_qty = qty // len(signal.targets) or 1
            for i, target in enumerate(signal.targets):
                target_result = self.client.place_order(
                    symbol=signal.symbol,
                    action=stop_action,  # Same as stop (exit direction)
                    qty=target_qty if i < len(signal.targets) - 1 else qty - (target_qty * i),
                    order_type="Limit",
                    price=target
                )
                if target_result:
                    target_order = Order(
                        id=target_result.get("orderId"),
                        symbol=signal.symbol,
                        action=stop_action,
                        qty=target_qty,
                        order_type="Limit",
                        price=target,
                        status=OrderStatus.WORKING
                    )
                    self.orders[target_order.id] = target_order
                    orders.append(target_order)

        return orders

    def update_positions(self):
        """Sync positions with broker."""
        positions = self.client.get_positions()
        for pos in positions:
            symbol = pos.get("contractId", "")  # Need to map to symbol
            self.positions[symbol] = Position(
                symbol=symbol,
                qty=pos.get("netPos", 0),
                avg_price=pos.get("netPrice", 0),
                unrealized_pnl=pos.get("openPL", 0),
                realized_pnl=pos.get("realizedPL", 0)
            )

    def cancel_all_orders(self, symbol: Optional[str] = None):
        """Cancel all working orders (optionally for a specific symbol)."""
        for order_id, order in list(self.orders.items()):
            if order.status == OrderStatus.WORKING:
                if symbol is None or order.symbol == symbol:
                    if self.client.cancel_order(order_id):
                        order.status = OrderStatus.CANCELLED

    def flatten_position(self, symbol: str):
        """Close all positions for a symbol."""
        pos = self.positions.get(symbol)
        if not pos or pos.qty == 0:
            return

        action = "Sell" if pos.qty > 0 else "Buy"
        self.client.place_order(
            symbol=symbol,
            action=action,
            qty=abs(pos.qty),
            order_type="Market"
        )

    def flatten_all(self):
        """Close all positions."""
        for symbol in list(self.positions.keys()):
            self.flatten_position(symbol)


if __name__ == "__main__":
    # Test order manager
    from broker.tradovate.api_client import TradovateClient

    client = TradovateClient()
    if client.authenticate():
        client.get_accounts()

        manager = OrderManager(client, default_qty=1)

        # Create a test signal
        signal = Signal(
            symbol="ESH5",
            direction=Direction.LONG,
            entry_type="LIMIT",
            entry_price=5000.0,
            stop_price=4990.0,
            targets=[5010.0, 5020.0],
            reason={"test": True}
        )

        # Check if we can trade
        can_trade, reason = manager.can_trade("ESH5", Direction.LONG, 1)
        print(f"Can trade: {can_trade} - {reason}")
