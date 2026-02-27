"""
Tradovate Direct API Executor

Executes trades directly via the Tradovate API for personal accounts.
Implements the same ExecutorInterface as WebhookExecutor, so the LiveTrader
can use either backend interchangeably.

Unlike WebhookExecutor (fire-and-forget HTTP calls), this tracks order IDs
to modify/cancel stops and manage partial closes.

Usage:
    executor = TradovateExecutor("config/tradovate_direct.json")
    executor.open_position("ES", "LONG", 3, stop_price=6100.0, entry_price=6110.0)
    executor.partial_close("ES", "LONG", 1, paper_trade_id="PAPER_ES_1")
    executor.update_stop("ES", "LONG", new_stop_price=6110.0, entry_price=6110.0)
    executor.close_position("ES", "LONG", paper_trade_id="PAPER_ES_1")
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from runners.executor_interface import ExecutorInterface
from runners.tradovate_client import (
    TradovateClient,
    TradovateConfig,
    OrderAction,
    OrderType,
    Environment,
)

logger = logging.getLogger(__name__)


@dataclass
class OrderState:
    """Tracks broker-side order IDs for a paper trade."""
    paper_trade_id: str
    symbol: str
    direction: str
    stop_order_id: Optional[int] = None
    remaining_contracts: int = 0
    entry_order_id: Optional[int] = None


class TradovateExecutor(ExecutorInterface):
    """Direct Tradovate API executor for personal accounts.

    Wraps TradovateClient with the ExecutorInterface so it can be used
    as a drop-in replacement for WebhookExecutor.
    """

    def __init__(self, config_path: str = "config/tradovate_direct.json"):
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"Tradovate direct config not found: {config_path}")

        with open(config_file) as f:
            self.config = json.load(f)

        self.contract_months: Dict[str, str] = self.config.get("contract_months", {})
        self.environment = self.config.get("environment", "demo")
        self.retry_max = self.config.get("retry_max", 2)
        self.retry_delay = self.config.get("retry_delay_sec", 1.0)

        # Create Tradovate client
        credentials_path = self.config.get("credentials_path", "config/tradovate_credentials.json")
        tv_config = TradovateConfig.from_file(credentials_path)
        tv_config.environment = Environment(self.environment)
        self.client = TradovateClient(tv_config, contract_months=self.contract_months)

        # Track orders per paper trade
        self._orders: Dict[str, OrderState] = {}  # paper_trade_id -> OrderState

        # Connect on init
        if not self.client.connect():
            raise ConnectionError("Failed to connect to Tradovate API")

        logger.info(
            "TradovateExecutor initialized: env=%s, account=%s",
            self.environment, self.client.account_id,
        )

    def get_account_count(self) -> int:
        """Return 1 (single direct API account)."""
        return 1

    def _get_contract_symbol(self, symbol: str) -> str:
        """Map base symbol (ES) to contract month symbol (ESM6)."""
        return self.contract_months.get(symbol, symbol)

    def _opposing_action(self, direction: str) -> OrderAction:
        """Get the opposing order action for a direction."""
        return OrderAction.SELL if direction == "LONG" else OrderAction.BUY

    def _entry_action(self, direction: str) -> OrderAction:
        """Get the entry order action for a direction."""
        return OrderAction.BUY if direction == "LONG" else OrderAction.SELL

    def _retry_operation(self, operation_name: str, fn, *args, **kwargs):
        """Execute an operation with retries."""
        last_error = None
        for attempt in range(self.retry_max + 1):
            try:
                result = fn(*args, **kwargs)
                if result is not None:
                    return result
                last_error = f"{operation_name} returned None"
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "[TRADOVATE] %s failed (attempt %d): %s",
                    operation_name, attempt + 1, e,
                )

            if attempt < self.retry_max:
                time.sleep(self.retry_delay)

        logger.error("[TRADOVATE] %s failed after %d attempts: %s",
                     operation_name, self.retry_max + 1, last_error)
        return None

    def open_position(
        self,
        symbol: str,
        direction: str,
        contracts: int,
        stop_price: float,
        entry_price: float,
        paper_trade_id: str = "",
    ) -> Dict:
        """Open a new position with market order + protective stop.

        Places:
        1. Market order for entry
        2. Stop order at stop_price for protection
        """
        contract_symbol = self._get_contract_symbol(symbol)
        action = self._entry_action(direction)
        opposing = self._opposing_action(direction)

        logger.info(
            "[TRADOVATE] ENTRY: %s %s %d @ market, stop=%.2f [%s]",
            action.value, contract_symbol, contracts, stop_price, paper_trade_id,
        )

        # Place market entry order
        entry_order = self._retry_operation(
            f"Entry {contract_symbol}",
            self.client.place_order,
            symbol=contract_symbol,
            action=action,
            quantity=contracts,
            order_type=OrderType.MARKET,
        )

        if not entry_order:
            logger.error("[TRADOVATE] Entry order failed for %s", paper_trade_id)
            return {"success": False, "error": "Entry order failed"}

        # Place protective stop order
        stop_order = self._retry_operation(
            f"Stop {contract_symbol}",
            self.client.place_order,
            symbol=contract_symbol,
            action=opposing,
            quantity=contracts,
            order_type=OrderType.STOP,
            stop_price=stop_price,
        )

        stop_id = stop_order.id if stop_order else None
        if not stop_id:
            logger.warning("[TRADOVATE] Stop order failed for %s — position unprotected!", paper_trade_id)

        # Track order state
        self._orders[paper_trade_id] = OrderState(
            paper_trade_id=paper_trade_id,
            symbol=contract_symbol,
            direction=direction,
            stop_order_id=stop_id,
            remaining_contracts=contracts,
            entry_order_id=entry_order.id,
        )

        logger.info(
            "[TRADOVATE] OPENED: %s %d %s, entry_id=%s, stop_id=%s",
            direction, contracts, contract_symbol, entry_order.id, stop_id,
        )

        return {
            "success": True,
            "entry_order_id": entry_order.id,
            "stop_order_id": stop_id,
        }

    def partial_close(
        self,
        symbol: str,
        direction: str,
        contracts: int,
        paper_trade_id: str = "",
    ) -> Dict:
        """Close part of a position via opposing market order.

        Also modifies the stop order quantity to match remaining contracts.
        """
        contract_symbol = self._get_contract_symbol(symbol)
        opposing = self._opposing_action(direction)
        state = self._orders.get(paper_trade_id)

        logger.info(
            "[TRADOVATE] PARTIAL CLOSE: %s %s %d [%s]",
            opposing.value, contract_symbol, contracts, paper_trade_id,
        )

        # Place opposing market order to close partial
        close_order = self._retry_operation(
            f"Partial close {contract_symbol}",
            self.client.place_order,
            symbol=contract_symbol,
            action=opposing,
            quantity=contracts,
            order_type=OrderType.MARKET,
        )

        if not close_order:
            return {"success": False, "error": "Partial close order failed"}

        # Update remaining contracts
        if state:
            state.remaining_contracts = max(0, state.remaining_contracts - contracts)

            # Modify stop order quantity to match remaining
            if state.stop_order_id and state.remaining_contracts > 0:
                self._retry_operation(
                    f"Modify stop qty {state.stop_order_id}",
                    self.client.modify_order,
                    order_id=state.stop_order_id,
                    quantity=state.remaining_contracts,
                )

        return {"success": True, "close_order_id": close_order.id}

    def update_stop(
        self,
        symbol: str,
        direction: str,
        new_stop_price: float,
        entry_price: float,
        paper_trade_id: str = "",
    ) -> Dict:
        """Update the broker-side stop loss price."""
        state = self._orders.get(paper_trade_id)

        if not state or not state.stop_order_id:
            logger.warning(
                "[TRADOVATE] No stop order to update for %s", paper_trade_id,
            )
            return {"success": False, "error": "No stop order found"}

        logger.info(
            "[TRADOVATE] UPDATE STOP: %s new_stop=%.2f [%s]",
            state.symbol, new_stop_price, paper_trade_id,
        )

        # Check if stop order is still active before modifying
        success = self._retry_operation(
            f"Modify stop {state.stop_order_id}",
            self.client.modify_order,
            order_id=state.stop_order_id,
            stop_price=new_stop_price,
        )

        if success is None or success is False:
            # Stop may have already fired — not an error in gap scenarios
            logger.warning(
                "[TRADOVATE] Stop modify failed for %s (may have already fired)",
                paper_trade_id,
            )
            return {"success": False, "error": "Stop modify failed"}

        return {"success": True}

    def close_position(
        self,
        symbol: str,
        direction: str,
        paper_trade_id: str = "",
    ) -> Dict:
        """Close entire remaining position for a trade.

        Cancels the stop order and places an opposing market order.
        """
        contract_symbol = self._get_contract_symbol(symbol)
        opposing = self._opposing_action(direction)
        state = self._orders.get(paper_trade_id)

        logger.info(
            "[TRADOVATE] CLOSE: %s %s [%s]",
            direction, contract_symbol, paper_trade_id,
        )

        # Cancel existing stop order (may fail if already fired — that's OK)
        if state and state.stop_order_id:
            cancel_ok = self.client.cancel_order(state.stop_order_id)
            if not cancel_ok:
                logger.info(
                    "[TRADOVATE] Stop cancel failed for %s (may have already fired)",
                    paper_trade_id,
                )

        # Determine remaining contracts
        remaining = state.remaining_contracts if state else 0

        if remaining > 0:
            close_order = self._retry_operation(
                f"Close {contract_symbol}",
                self.client.place_order,
                symbol=contract_symbol,
                action=opposing,
                quantity=remaining,
                order_type=OrderType.MARKET,
            )

            if not close_order:
                # Fallback: try flatten
                logger.warning("[TRADOVATE] Close order failed, attempting flatten for %s", contract_symbol)
                self.client.flatten_position(contract_symbol)
        else:
            logger.info("[TRADOVATE] No remaining contracts for %s", paper_trade_id)

        # Clean up order state
        if paper_trade_id in self._orders:
            del self._orders[paper_trade_id]

        return {"success": True}

    def close_all(self, symbol: Optional[str] = None) -> Dict:
        """Close all positions, optionally filtered by symbol.

        Emergency/EOD catch-all. Cancels all stops and flattens.
        """
        if symbol:
            contract_symbol = self._get_contract_symbol(symbol)
            logger.info("[TRADOVATE] CLOSE ALL: %s", contract_symbol)
        else:
            logger.info("[TRADOVATE] CLOSE ALL positions")

        # Cancel all tracked stop orders
        for trade_id, state in list(self._orders.items()):
            if symbol and state.symbol != self._get_contract_symbol(symbol):
                continue
            if state.stop_order_id:
                try:
                    self.client.cancel_order(state.stop_order_id)
                except Exception as e:
                    logger.warning("[TRADOVATE] Failed to cancel stop %s: %s", state.stop_order_id, e)

        # Flatten positions
        if symbol:
            contract_symbol = self._get_contract_symbol(symbol)
            self.client.flatten_position(contract_symbol)
        else:
            self.client.flatten_all()

        # Clean up order state
        if symbol:
            contract_symbol = self._get_contract_symbol(symbol)
            to_remove = [tid for tid, s in self._orders.items() if s.symbol == contract_symbol]
        else:
            to_remove = list(self._orders.keys())
        for tid in to_remove:
            del self._orders[tid]

        return {"success": True}

    def reconcile_positions(self, paper_trades: Dict) -> List[str]:
        """Compare broker positions vs paper state. Advisory only.

        Returns list of warning messages for any mismatches.
        """
        warnings = []
        try:
            broker_positions = self.client.get_positions()

            # Build broker position map: contract_symbol -> net_pos
            broker_map: Dict[str, int] = {}
            for pos in broker_positions:
                # Get symbol name from contract ID
                for base_sym, month_sym in self.contract_months.items():
                    contract_id = self.client.get_contract_id(month_sym)
                    if contract_id == pos.contract_id:
                        broker_map[base_sym] = pos.net_pos
                        break

            # Build paper position map: symbol -> expected net position
            paper_map: Dict[str, int] = {}
            for trade in paper_trades.values():
                if not hasattr(trade, 'status') or str(trade.status) != 'PaperTradeStatus.OPEN':
                    # Also check the enum value directly
                    try:
                        if trade.status.value != 'open':
                            continue
                    except AttributeError:
                        continue
                if trade.asset_type != 'futures':
                    continue

                remaining = trade.contracts
                if trade.t1_hit:
                    remaining -= 1
                if trade.t2_hit:
                    remaining -= 1
                if trade.runner_exit:
                    remaining -= max(0, trade.contracts - 2)

                signed = remaining if trade.direction == "LONG" else -remaining
                paper_map[trade.symbol] = paper_map.get(trade.symbol, 0) + signed

            # Compare
            all_symbols = set(list(broker_map.keys()) + list(paper_map.keys()))
            for sym in all_symbols:
                broker_qty = broker_map.get(sym, 0)
                paper_qty = paper_map.get(sym, 0)
                if broker_qty != paper_qty:
                    msg = f"[RECONCILE] {sym}: broker={broker_qty} vs paper={paper_qty}"
                    warnings.append(msg)
                    logger.warning(msg)

            if not warnings:
                logger.info("[RECONCILE] All positions match")

        except Exception as e:
            msg = f"[RECONCILE] Error: {e}"
            warnings.append(msg)
            logger.error(msg)

        return warnings

    def check_orphaned_positions(self) -> List[str]:
        """Check for orphaned broker positions on startup.

        Returns warning messages for any open positions found.
        Does NOT auto-close — advisory only.
        """
        warnings = []
        try:
            positions = self.client.get_positions()
            for pos in positions:
                if pos.net_pos != 0:
                    msg = (
                        f"[STARTUP] Orphaned position: contract_id={pos.contract_id}, "
                        f"net_pos={pos.net_pos}, price={pos.net_price:.2f}"
                    )
                    warnings.append(msg)
                    logger.warning(msg)

            if not warnings:
                logger.info("[STARTUP] No orphaned positions found")

        except Exception as e:
            msg = f"[STARTUP] Error checking positions: {e}"
            warnings.append(msg)
            logger.error(msg)

        return warnings
