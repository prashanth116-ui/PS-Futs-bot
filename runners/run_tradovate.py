"""
Live Trading Runner for Tradovate

Connects to Tradovate, streams real-time data, runs the ICT strategy,
and executes trades.

Usage:
    python -m runners.run_tradovate

Before running:
    1. Copy config/.env.example to config/.env
    2. Fill in your Tradovate credentials
    3. Set TRADOVATE_ENV to "demo" for paper trading
"""
from __future__ import annotations
import signal
import asyncio
from typing import Optional

from core.types import Bar, Signal
from broker.tradovate.api_client import TradovateClient
from broker.tradovate.data_feed import TradovateDataFeed, Quote
from broker.tradovate.order_manager import OrderManager
from strategies.factory import build_ict_from_yaml


class LiveTrader:
    """
    Live trading orchestrator.

    Connects strategy signals to order execution.
    """

    def __init__(
        self,
        strategy_config: str = "config/strategies/ict_es.yaml",
        symbols: list[str] = None,
        qty: int = 1,
        auto_execute: bool = False
    ):
        self.strategy_config = strategy_config
        self.symbols = symbols or ["ESH5"]  # Default to ES front month
        self.qty = qty
        self.auto_execute = auto_execute

        # Components
        self.client: Optional[TradovateClient] = None
        self.feed: Optional[TradovateDataFeed] = None
        self.order_manager: Optional[OrderManager] = None
        self.strategy = None

        # State
        self.running = False
        self.bars_received = 0
        self.signals_generated = 0
        self.orders_executed = 0

    def setup(self) -> bool:
        """Initialize all components."""
        print("=" * 60)
        print("ICT Strategy - Live Trader (Tradovate)")
        print("=" * 60)

        # Load strategy
        print(f"\nLoading strategy from {self.strategy_config}...")
        try:
            self.strategy = build_ict_from_yaml(self.strategy_config)
            print("Strategy loaded successfully")
        except Exception as e:
            print(f"Failed to load strategy: {e}")
            return False

        # Create Tradovate client
        print("\nConnecting to Tradovate...")
        self.client = TradovateClient()

        if not self.client.authenticate():
            print("Authentication failed. Check your credentials in config/.env")
            return False

        # Get accounts
        accounts = self.client.get_accounts()
        if not accounts:
            print("No trading accounts found")
            return False

        print(f"Account: {self.client.account_spec}")
        print(f"Environment: {self.client.config.env.upper()}")

        # Create order manager
        self.order_manager = OrderManager(self.client, default_qty=self.qty)
        print(f"Order quantity: {self.qty} contracts")
        print(f"Auto-execute: {'ENABLED' if self.auto_execute else 'DISABLED (signals only)'}")

        # Create data feed
        self.feed = TradovateDataFeed(self.client)
        self.feed.on_bar = self._on_bar
        self.feed.on_quote = self._on_quote

        print(f"\nSymbols: {', '.join(self.symbols)}")
        print("-" * 60)

        return True

    def _on_quote(self, quote: Quote):
        """Handle incoming quote."""
        # Just log periodically
        pass

    def _on_bar(self, bar: Bar):
        """Handle incoming bar - run strategy."""
        self.bars_received += 1

        # Log bar
        print(f"[{bar.timestamp}] {bar.symbol} O:{bar.open:.2f} H:{bar.high:.2f} "
              f"L:{bar.low:.2f} C:{bar.close:.2f} V:{bar.volume}")

        # Run strategy
        try:
            signal = self.strategy.on_bar(bar)

            if signal:
                self.signals_generated += 1
                self._handle_signal(signal)

        except Exception as e:
            print(f"Strategy error: {e}")

    def _handle_signal(self, signal: Signal):
        """Handle a strategy signal."""
        print("\n" + "=" * 40)
        print("SIGNAL GENERATED")
        print("=" * 40)
        print(f"Direction: {signal.direction.value}")
        print(f"Entry: {signal.entry_price} ({signal.entry_type.value})")
        print(f"Stop: {signal.stop_price}")
        print(f"Targets: {signal.targets}")
        print(f"Reason: {signal.reason}")
        print("=" * 40)

        if self.auto_execute:
            print("\nExecuting order...")
            orders = self.order_manager.execute_bracket(signal, self.qty)
            if orders:
                self.orders_executed += len(orders)
                print(f"Orders submitted: {len(orders)}")
            else:
                print("Order execution failed")
        else:
            print("\n[Auto-execute disabled - signal logged only]")
            print("Set auto_execute=True to trade automatically")

    async def run_async(self):
        """Run the live trader (async)."""
        if not self.setup():
            return

        self.running = True

        # Connect and subscribe
        if not await self.feed.connect():
            print("Failed to connect to data feed")
            return

        for symbol in self.symbols:
            await self.feed.subscribe(symbol)

        print("\nListening for market data... (Ctrl+C to stop)")
        print("-" * 60)

        # Listen for data
        await self.feed.listen()

    def run(self):
        """Run the live trader (blocking)."""
        # Handle Ctrl+C gracefully
        def signal_handler(sig, frame):
            print("\n\nShutting down...")
            self.running = False
            if self.feed:
                self.feed.running = False

        signal.signal(signal.SIGINT, signal_handler)

        try:
            asyncio.run(self.run_async())
        except KeyboardInterrupt:
            pass

        # Print summary
        print("\n" + "=" * 60)
        print("SESSION SUMMARY")
        print("=" * 60)
        print(f"Bars received: {self.bars_received}")
        print(f"Signals generated: {self.signals_generated}")
        print(f"Orders executed: {self.orders_executed}")
        print("=" * 60)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="ICT Strategy Live Trader")
    parser.add_argument("--symbol", default="ESH5", help="Symbol to trade (e.g., ESH5, NQH5)")
    parser.add_argument("--qty", type=int, default=1, help="Number of contracts")
    parser.add_argument("--execute", action="store_true", help="Enable auto-execution")
    parser.add_argument("--config", default="config/strategies/ict_es.yaml", help="Strategy config")

    args = parser.parse_args()

    trader = LiveTrader(
        strategy_config=args.config,
        symbols=[args.symbol],
        qty=args.qty,
        auto_execute=args.execute
    )

    trader.run()


if __name__ == "__main__":
    main()
