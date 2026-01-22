"""
Tradovate WebSocket Data Feed

Provides real-time market data streaming.
"""
from __future__ import annotations
import json
import asyncio
import websockets
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Callable, Any
from collections import defaultdict

from core.types import Bar
from broker.tradovate.api_client import TradovateClient, TradovateConfig


@dataclass
class Quote:
    """Real-time quote data."""
    symbol: str
    bid: float
    ask: float
    last: float
    volume: int
    timestamp: datetime


@dataclass
class Trade:
    """Real-time trade data."""
    symbol: str
    price: float
    size: int
    timestamp: datetime


class TradovateDataFeed:
    """
    WebSocket-based real-time data feed from Tradovate.

    Provides:
    - Real-time quotes
    - Real-time trades
    - Bar aggregation
    """

    def __init__(self, client: TradovateClient):
        self.client = client
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.subscriptions: set[str] = set()
        self.running = False

        # Callbacks
        self.on_quote: Optional[Callable[[Quote], None]] = None
        self.on_trade: Optional[Callable[[Trade], None]] = None
        self.on_bar: Optional[Callable[[Bar], None]] = None

        # Bar aggregation
        self.bar_interval = 60  # seconds (1 minute)
        self.current_bars: dict[str, dict] = defaultdict(dict)
        self.last_bar_time: dict[str, datetime] = {}

        # Message ID counter
        self._msg_id = 0

    def _next_msg_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def connect(self) -> bool:
        """Connect to Tradovate WebSocket."""
        if not self.client.is_authenticated():
            if not self.client.authenticate():
                print("Failed to authenticate")
                return False

        try:
            self.ws = await websockets.connect(
                self.client.config.md_url,
                extra_headers={"Authorization": f"Bearer {self.client.access_token}"}
            )
            print(f"Connected to {self.client.config.md_url}")

            # Authorize the connection
            auth_msg = {
                "op": "authorize",
                "token": self.client.access_token
            }
            await self.ws.send(json.dumps(auth_msg))
            response = await self.ws.recv()
            print(f"Auth response: {response}")

            self.running = True
            return True

        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    async def disconnect(self):
        """Disconnect from WebSocket."""
        self.running = False
        if self.ws:
            await self.ws.close()
            self.ws = None
        print("Disconnected from Tradovate")

    async def subscribe(self, symbol: str):
        """Subscribe to market data for a symbol."""
        if not self.ws:
            print("Not connected")
            return

        # Get contract ID
        contract = self.client.get_contract(symbol)
        if not contract:
            print(f"Contract not found: {symbol}")
            return

        contract_id = contract.get("id")

        # Subscribe to quotes
        msg = {
            "op": "subscribe",
            "channel": "md",
            "args": {
                "symbol": symbol,
                "contractId": contract_id,
                "charts": ["tick", "quote"]
            }
        }
        await self.ws.send(json.dumps(msg))
        self.subscriptions.add(symbol)
        print(f"Subscribed to {symbol}")

    async def unsubscribe(self, symbol: str):
        """Unsubscribe from market data."""
        if not self.ws:
            return

        msg = {
            "op": "unsubscribe",
            "channel": "md",
            "args": {"symbol": symbol}
        }
        await self.ws.send(json.dumps(msg))
        self.subscriptions.discard(symbol)
        print(f"Unsubscribed from {symbol}")

    def _process_quote(self, data: dict):
        """Process incoming quote data."""
        try:
            quote = Quote(
                symbol=data.get("symbol", ""),
                bid=float(data.get("bid", 0)),
                ask=float(data.get("ask", 0)),
                last=float(data.get("last", 0)),
                volume=int(data.get("volume", 0)),
                timestamp=datetime.now()
            )
            if self.on_quote:
                self.on_quote(quote)
        except Exception as e:
            print(f"Error processing quote: {e}")

    def _process_trade(self, data: dict):
        """Process incoming trade data."""
        try:
            trade = Trade(
                symbol=data.get("symbol", ""),
                price=float(data.get("price", 0)),
                size=int(data.get("size", 0)),
                timestamp=datetime.now()
            )
            if self.on_trade:
                self.on_trade(trade)

            # Update current bar
            self._update_bar(trade)

        except Exception as e:
            print(f"Error processing trade: {e}")

    def _update_bar(self, trade: Trade):
        """Update the current bar with trade data."""
        symbol = trade.symbol
        now = trade.timestamp

        # Calculate bar start time
        bar_seconds = int(now.timestamp()) // self.bar_interval * self.bar_interval
        bar_time = datetime.fromtimestamp(bar_seconds)

        # Check if we need to emit a completed bar
        if symbol in self.last_bar_time and self.last_bar_time[symbol] < bar_time:
            # Emit the previous bar
            prev_bar = self.current_bars.get(symbol)
            if prev_bar and self.on_bar:
                bar = Bar(
                    timestamp=self.last_bar_time[symbol],
                    open=prev_bar["open"],
                    high=prev_bar["high"],
                    low=prev_bar["low"],
                    close=prev_bar["close"],
                    volume=prev_bar["volume"],
                    symbol=symbol,
                    timeframe=f"{self.bar_interval // 60}m"
                )
                self.on_bar(bar)

            # Reset for new bar
            self.current_bars[symbol] = {}

        # Update current bar
        bar = self.current_bars[symbol]
        if not bar:
            bar["open"] = trade.price
            bar["high"] = trade.price
            bar["low"] = trade.price
            bar["volume"] = 0

        bar["high"] = max(bar.get("high", trade.price), trade.price)
        bar["low"] = min(bar.get("low", trade.price), trade.price)
        bar["close"] = trade.price
        bar["volume"] = bar.get("volume", 0) + trade.size

        self.current_bars[symbol] = bar
        self.last_bar_time[symbol] = bar_time

    async def listen(self):
        """Listen for incoming messages."""
        if not self.ws:
            print("Not connected")
            return

        print("Listening for market data...")

        try:
            while self.running:
                try:
                    message = await asyncio.wait_for(self.ws.recv(), timeout=30)
                    data = json.loads(message)

                    # Process based on message type
                    msg_type = data.get("e") or data.get("type")

                    if msg_type == "quote":
                        self._process_quote(data.get("d", data))
                    elif msg_type == "trade":
                        self._process_trade(data.get("d", data))
                    elif msg_type == "md":
                        # Market data update
                        for item in data.get("d", []):
                            if "bid" in item or "ask" in item:
                                self._process_quote(item)
                            elif "price" in item and "size" in item:
                                self._process_trade(item)

                except asyncio.TimeoutError:
                    # Send heartbeat
                    if self.ws:
                        await self.ws.ping()

        except websockets.exceptions.ConnectionClosed:
            print("Connection closed")
            self.running = False
        except Exception as e:
            print(f"Error in listen loop: {e}")
            self.running = False

    async def run(self, symbols: list[str]):
        """
        Main entry point - connect, subscribe, and listen.

        Args:
            symbols: List of symbols to subscribe to (e.g., ["ESH5", "NQH5"])
        """
        if not await self.connect():
            return

        # Subscribe to all symbols
        for symbol in symbols:
            await self.subscribe(symbol)

        # Listen for data
        await self.listen()


# Synchronous wrapper for easier use
class SyncDataFeed:
    """Synchronous wrapper around TradovateDataFeed."""

    def __init__(self, client: TradovateClient):
        self.feed = TradovateDataFeed(client)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_callbacks(
        self,
        on_quote: Optional[Callable[[Quote], None]] = None,
        on_trade: Optional[Callable[[Trade], None]] = None,
        on_bar: Optional[Callable[[Bar], None]] = None,
    ):
        """Set callback functions."""
        self.feed.on_quote = on_quote
        self.feed.on_trade = on_trade
        self.feed.on_bar = on_bar

    def run(self, symbols: list[str]):
        """Run the data feed (blocking)."""
        asyncio.run(self.feed.run(symbols))

    def stop(self):
        """Stop the data feed."""
        self.feed.running = False


if __name__ == "__main__":
    # Test the data feed
    from broker.tradovate.api_client import TradovateClient

    client = TradovateClient()

    if client.authenticate():
        feed = SyncDataFeed(client)

        def on_quote(quote: Quote):
            print(f"Quote: {quote.symbol} bid={quote.bid} ask={quote.ask}")

        def on_bar(bar: Bar):
            print(f"Bar: {bar}")

        feed.set_callbacks(on_quote=on_quote, on_bar=on_bar)

        # Subscribe to ES front month
        feed.run(["ESH5"])
