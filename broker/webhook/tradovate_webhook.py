"""
Tradovate Webhook Integration

Sends trading signals via webhook to Tradovate AutoTrade.

Setup:
1. Enable AutoTrade in Tradovate: Settings -> AutoTrade
2. Copy your webhook URL
3. Add to config/.env: TRADOVATE_WEBHOOK_URL=your_url
"""
import os
import json
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent.parent.parent / "config" / ".env"
load_dotenv(env_path)


class TradovateWebhook:
    """Send orders to Tradovate via webhook."""

    # Symbol mapping: our names -> Tradovate contract names
    SYMBOL_MAP = {
        'ES': 'ES',   # Will append month/year (e.g., ESH25)
        'NQ': 'NQ',
        'MES': 'MES',
        'MNQ': 'MNQ',
        'CL': 'CL',
        'GC': 'GC',
    }

    def __init__(self, webhook_url: Optional[str] = None, paper_mode: bool = True):
        """
        Initialize webhook client.

        Args:
            webhook_url: Tradovate webhook URL (or set TRADOVATE_WEBHOOK_URL env var)
            paper_mode: If True, log orders but don't send (for testing)
        """
        self.webhook_url = webhook_url or os.getenv('TRADOVATE_WEBHOOK_URL')
        self.paper_mode = paper_mode
        self.order_log = []

        if not self.webhook_url and not paper_mode:
            raise ValueError("No webhook URL provided. Set TRADOVATE_WEBHOOK_URL in config/.env")

    def _get_contract_symbol(self, symbol: str) -> str:
        """Convert symbol to Tradovate contract format."""
        # Get base symbol
        base = self.SYMBOL_MAP.get(symbol.upper(), symbol.upper())

        # Add current front month (e.g., H25 for March 2025)
        # This is simplified - in production, calculate actual front month
        now = datetime.now()
        month_codes = ['F', 'G', 'H', 'J', 'K', 'M', 'N', 'Q', 'U', 'V', 'X', 'Z']
        month_code = month_codes[now.month - 1]
        year_code = str(now.year)[-2:]

        return f"{base}{month_code}{year_code}"

    def send_market_order(
        self,
        symbol: str,
        action: str,  # 'BUY' or 'SELL'
        qty: int,
        stop_price: Optional[float] = None,
        target_price: Optional[float] = None,
        order_id: Optional[str] = None,
    ) -> dict:
        """
        Send a market order via webhook.

        Args:
            symbol: Instrument symbol (ES, NQ, etc.)
            action: BUY or SELL
            qty: Number of contracts
            stop_price: Stop loss price (optional)
            target_price: Take profit price (optional)
            order_id: Custom order ID for tracking

        Returns:
            Response dict with status and details
        """
        contract = self._get_contract_symbol(symbol)
        order_id = order_id or f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Build webhook payload
        # Tradovate AutoTrade format
        payload = {
            "symbol": contract,
            "action": action.lower(),
            "qty": qty,
            "orderType": "market",
        }

        # Add bracket orders if provided
        if stop_price:
            payload["stopLoss"] = stop_price
        if target_price:
            payload["takeProfit"] = target_price

        # Log order
        order_record = {
            "id": order_id,
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "contract": contract,
            "action": action,
            "qty": qty,
            "stop": stop_price,
            "target": target_price,
            "payload": payload,
            "status": "PENDING",
        }

        if self.paper_mode:
            print(f"\n[PAPER MODE] Order logged (not sent):")
            print(f"  {action} {qty} {contract}")
            if stop_price:
                print(f"  Stop: {stop_price}")
            if target_price:
                print(f"  Target: {target_price}")
            order_record["status"] = "PAPER"
            self.order_log.append(order_record)
            return {"success": True, "paper_mode": True, "order": order_record}

        # Send webhook
        try:
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10
            )

            if response.status_code == 200:
                order_record["status"] = "SENT"
                order_record["response"] = response.text
                print(f"\n[WEBHOOK] Order sent successfully:")
                print(f"  {action} {qty} {contract}")
                result = {"success": True, "order": order_record, "response": response.text}
            else:
                order_record["status"] = "FAILED"
                order_record["error"] = response.text
                print(f"\n[WEBHOOK] Order failed: {response.status_code}")
                print(f"  {response.text}")
                result = {"success": False, "error": response.text, "order": order_record}

        except Exception as e:
            order_record["status"] = "ERROR"
            order_record["error"] = str(e)
            print(f"\n[WEBHOOK] Error: {e}")
            result = {"success": False, "error": str(e), "order": order_record}

        self.order_log.append(order_record)
        return result

    def send_bracket_order(
        self,
        symbol: str,
        action: str,
        qty: int,
        entry_price: float,
        stop_price: float,
        target_prices: list[float],
        order_id: Optional[str] = None,
    ) -> dict:
        """
        Send a bracket order (entry + stop + targets).

        For our strategy:
        - 1 contract exits at 4R
        - 1 contract exits at 8R
        - 1 contract is runner (trailing stop)

        Args:
            symbol: Instrument symbol
            action: BUY or SELL
            qty: Total contracts (typically 3)
            entry_price: Entry price
            stop_price: Stop loss price
            target_prices: List of target prices [4R, 8R]

        Returns:
            Response dict
        """
        results = []

        # For now, send as single market order with first target
        # More sophisticated bracket handling would require multiple orders
        main_order = self.send_market_order(
            symbol=symbol,
            action=action,
            qty=qty,
            stop_price=stop_price,
            target_price=target_prices[0] if target_prices else None,
            order_id=order_id,
        )
        results.append(main_order)

        return {
            "success": all(r.get("success") for r in results),
            "orders": results,
        }

    def close_position(self, symbol: str, qty: int, current_action: str) -> dict:
        """
        Close an open position.

        Args:
            symbol: Instrument symbol
            qty: Contracts to close
            current_action: Current position direction (BUY = long, SELL = short)

        Returns:
            Response dict
        """
        # Opposite action to close
        close_action = "SELL" if current_action.upper() == "BUY" else "BUY"

        return self.send_market_order(
            symbol=symbol,
            action=close_action,
            qty=qty,
            order_id=f"CLOSE-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        )

    def get_order_log(self) -> list:
        """Get all logged orders."""
        return self.order_log


# Convenience functions
def send_long_signal(symbol: str, qty: int, stop: float, target: float, paper_mode: bool = True) -> dict:
    """Quick function to send a LONG signal."""
    webhook = TradovateWebhook(paper_mode=paper_mode)
    return webhook.send_market_order(symbol, "BUY", qty, stop_price=stop, target_price=target)


def send_short_signal(symbol: str, qty: int, stop: float, target: float, paper_mode: bool = True) -> dict:
    """Quick function to send a SHORT signal."""
    webhook = TradovateWebhook(paper_mode=paper_mode)
    return webhook.send_market_order(symbol, "SELL", qty, stop_price=stop, target_price=target)


if __name__ == "__main__":
    # Test in paper mode
    print("Testing Tradovate Webhook (Paper Mode)")
    print("=" * 50)

    webhook = TradovateWebhook(paper_mode=True)

    # Test market order
    webhook.send_market_order(
        symbol="ES",
        action="SELL",
        qty=3,
        stop_price=7032.25,
        target_price=7019.75
    )

    # Test bracket order
    webhook.send_bracket_order(
        symbol="NQ",
        action="SELL",
        qty=3,
        entry_price=26300.50,
        stop_price=26308.00,
        target_prices=[26270.50, 26240.50]
    )

    print("\nOrder Log:")
    for order in webhook.get_order_log():
        print(f"  {order['id']}: {order['action']} {order['qty']} {order['contract']} - {order['status']}")
