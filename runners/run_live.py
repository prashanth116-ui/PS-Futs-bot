"""
V10.4 Live Trading Runner - Combined Futures + Equities

Main entry point for live trading with the V10.4 strategy.
Supports both futures (ES, NQ, MES, MNQ) and equities (SPY, QQQ).

V10.4 Changes:
- ATR-based stop buffer for equities (ATR × 0.5 vs fixed $0.02)
- Improves equity P/L by +$54k over 30 days

Usage:
    python -m runners.run_live --paper                    # Paper mode, default symbols
    python -m runners.run_live --paper --symbols ES NQ    # Paper mode, specific futures
    python -m runners.run_live --paper --symbols SPY QQQ  # Paper mode, equities
    python -m runners.run_live --paper --symbols ES NQ SPY QQQ  # All supported
    python -m runners.run_live --live                     # Live mode (be careful!)
"""
import sys
sys.path.insert(0, '.')

import os
import argparse
import time
import signal
from datetime import datetime, time as dt_time, timedelta
from typing import Optional, Dict, List


def log(msg: str):
    """Print with explicit flush for reliable output."""
    print(msg)
    sys.stdout.flush()

from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10, is_swing_high, is_swing_low
from runners.run_v10_equity import run_session_v10_equity, EQUITY_CONFIG
from runners.tradovate_client import TradovateClient, TradovateConfig, Environment, create_client
from runners.order_manager import OrderManager, ManagedTrade, TradeStatus
from runners.risk_manager import RiskManager, RiskLimits, create_default_risk_manager


class LiveTrader:
    """
    V10.4 Live Trading System - Combined Futures + Equities

    Runs the strategy in real-time, generating signals and executing trades.

    V10.4: ATR buffer for equities (adaptive stops based on volatility)
    """

    # Futures symbol configurations
    FUTURES_SYMBOLS = {
        'ES': {
            'tradovate_symbol': 'ESH5',
            'tick_size': 0.25,
            'tick_value': 12.50,
            'min_risk': 1.5,
            'max_bos_risk': 8.0,
            'contracts': 3,
            'type': 'futures',
        },
        'NQ': {
            'tradovate_symbol': 'NQH5',
            'tick_size': 0.25,
            'tick_value': 5.00,
            'min_risk': 6.0,
            'max_bos_risk': 20.0,
            'contracts': 3,
            'type': 'futures',
        },
        'MES': {
            'tradovate_symbol': 'MESH5',
            'tick_size': 0.25,
            'tick_value': 1.25,
            'min_risk': 1.5,
            'max_bos_risk': 8.0,
            'contracts': 3,
            'type': 'futures',
        },
        'MNQ': {
            'tradovate_symbol': 'MNQH5',
            'tick_size': 0.25,
            'tick_value': 0.50,
            'min_risk': 6.0,
            'max_bos_risk': 20.0,
            'contracts': 3,
            'type': 'futures',
        },
    }

    # Equity symbol configurations
    EQUITY_SYMBOLS = {
        'SPY': {
            'name': 'S&P 500 ETF',
            'min_risk': 0.30,
            'risk_per_trade': 500,  # $ risk per trade
            'type': 'equity',
        },
        'QQQ': {
            'name': 'Nasdaq 100 ETF',
            'min_risk': 0.50,
            'risk_per_trade': 500,  # $ risk per trade
            'type': 'equity',
        },
    }

    def __init__(
        self,
        client: Optional[TradovateClient] = None,
        risk_manager: Optional[RiskManager] = None,
        paper_mode: bool = True,
        symbols: List[str] = None,
        equity_risk: int = 500,
    ):
        """
        Initialize live trader.

        Args:
            client: Tradovate API client (None for paper mode)
            risk_manager: Risk manager instance
            paper_mode: If True, only log signals without executing
            symbols: List of symbols to trade (default: ['ES', 'NQ'])
            equity_risk: Risk per trade for equities in dollars
        """
        self.client = client
        self.risk_manager = risk_manager or create_default_risk_manager()
        self.paper_mode = paper_mode
        self.symbols = symbols or ['ES', 'NQ']
        self.equity_risk = equity_risk

        # Categorize symbols
        self.futures_symbols = [s for s in self.symbols if s in self.FUTURES_SYMBOLS]
        self.equity_symbols = [s for s in self.symbols if s in self.EQUITY_SYMBOLS]

        # Update equity risk config
        for sym in self.equity_symbols:
            self.EQUITY_SYMBOLS[sym]['risk_per_trade'] = equity_risk

        # Order manager (only if client provided)
        self.order_manager = OrderManager(client) if client else None

        # State
        self.running = False
        self.last_scan_time: Dict[str, datetime] = {}
        self.processed_signals: Dict[str, set] = {s: set() for s in self.symbols}

        # Scan interval (3 minutes to match bar interval)
        self.scan_interval = 180  # seconds

        # Signal for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print("\nShutdown signal received...")
        self.stop()

    def start(self):
        """Start the live trading loop."""
        self.running = True
        print("=" * 70)
        print("V10.4 LIVE TRADER - Combined Futures + Equities")
        print("=" * 70)
        print(f"Mode: {'PAPER' if self.paper_mode else 'LIVE'}")
        if self.futures_symbols:
            print(f"Futures: {', '.join(self.futures_symbols)} (2-tick buffer)")
        if self.equity_symbols:
            print(f"Equities: {', '.join(self.equity_symbols)} (${self.equity_risk}/trade, ATR buffer)")
        print(f"Scan interval: {self.scan_interval}s")
        print("=" * 70)

        if not self.paper_mode and self.client:
            print("\nConnecting to Tradovate...")
            if not self.client.connect():
                print("Failed to connect to Tradovate")
                return

            balance = self.client.get_account_balance()
            print(f"Account balance: ${balance.get('cash_balance', 0):,.2f}")
            print(f"Available margin: ${balance.get('available_margin', 0):,.2f}")

        print("\nStarting trading loop...")
        print("Press Ctrl+C to stop\n")

        self._trading_loop()

    def stop(self):
        """Stop the trading loop."""
        self.running = False
        print("\nStopping trader...")

        # Close any open positions if in live mode
        if not self.paper_mode and self.order_manager:
            active_trades = self.order_manager.get_active_trades()
            if active_trades:
                print(f"Closing {len(active_trades)} active trades...")
                for trade in active_trades:
                    # Get current price for EOD close
                    bars = fetch_futures_bars(trade.symbol, interval='3m', n_bars=1)
                    if bars:
                        self.order_manager.close_trade_eod(trade, bars[-1].close)

        if self.client:
            self.client.disconnect()

        # Print summary
        self._print_summary()

    def _trading_loop(self):
        """Main trading loop."""
        while self.running:
            try:
                current_time = datetime.now()

                # Check if within trading hours (RTH: 9:30-16:00 ET)
                if not self._is_trading_hours(current_time):
                    log(f"[{current_time.strftime('%H:%M:%S')}] Outside trading hours")
                    self._interruptible_sleep(60)
                    continue

                # Check risk status
                if not self.risk_manager.is_trading_allowed():
                    status = self.risk_manager.get_summary()
                    log(f"[{current_time.strftime('%H:%M:%S')}] Trading blocked: {status['blocked_reason']}")
                    self._interruptible_sleep(60)
                    continue

                # Scan futures symbols
                for symbol in self.futures_symbols:
                    if not self.running:
                        break
                    try:
                        self._scan_futures_symbol(symbol)
                    except Exception as e:
                        log(f"  Error scanning {symbol}: {e}")

                # Scan equity symbols
                for symbol in self.equity_symbols:
                    if not self.running:
                        break
                    try:
                        self._scan_equity_symbol(symbol)
                    except Exception as e:
                        log(f"  Error scanning {symbol}: {e}")

                sys.stdout.flush()

                # Manage active trades
                if self.order_manager:
                    self._manage_active_trades()

                # Print status
                try:
                    self._print_status()
                except Exception as e:
                    log(f"  Error in _print_status: {e}")
                self._interruptible_sleep(self.scan_interval)

            except KeyboardInterrupt:
                break
            except Exception as e:
                log(f"Error in trading loop: {e}")
                import traceback
                traceback.print_exc()
                sys.stdout.flush()
                self._interruptible_sleep(10)

    def _interruptible_sleep(self, seconds: int):
        """Sleep in small increments with heartbeat, allowing for interrupt."""
        heartbeat_interval = 30  # Show heartbeat every 30 seconds
        elapsed = 0
        while elapsed < seconds and self.running:
            sleep_chunk = min(heartbeat_interval, seconds - elapsed)
            time.sleep(sleep_chunk)
            elapsed += sleep_chunk
            if elapsed < seconds and self.running:
                remaining = seconds - elapsed
                log(f"  ... waiting {remaining}s until next scan")

    def _is_trading_hours(self, dt: datetime) -> bool:
        """Check if within RTH trading hours."""
        current_time = dt.time()
        rth_start = dt_time(9, 30)
        rth_end = dt_time(16, 0)
        return rth_start <= current_time <= rth_end

    def _scan_futures_symbol(self, symbol: str):
        """Scan a futures symbol for trading signals."""
        config = self.FUTURES_SYMBOLS.get(symbol)
        if not config:
            return

        log(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scanning {symbol} (futures)...")

        # Fetch bars with timeout
        bars = fetch_futures_bars(symbol, interval='3m', n_bars=500, timeout=30)
        if not bars:
            log(f"  No data for {symbol}")
            return

        # Get today's session bars
        today = datetime.now().date()
        today_bars = [b for b in bars if b.timestamp.date() == today]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 20:
            log(f"  Not enough bars for {symbol}: {len(session_bars)}")
            return

        current_price = session_bars[-1].close
        log(f"  {symbol}: {current_price:.2f} ({len(session_bars)} bars)")

        # Run V10.3 strategy to get signals
        results = run_session_v10(
            session_bars,
            bars,
            tick_size=config['tick_size'],
            tick_value=config['tick_value'],
            contracts=config['contracts'],
            min_risk_pts=config['min_risk'],
            enable_creation_entry=True,
            enable_retracement_entry=True,
            enable_bos_entry=True,
            retracement_morning_only=True,
            t1_fixed_4r=True,
            midday_cutoff=True,
            pm_cutoff_nq=True,
            max_bos_risk_pts=config['max_bos_risk'],
            symbol=symbol,
        )

        # Process signals
        self._process_futures_signals(symbol, results, config)

    def _scan_equity_symbol(self, symbol: str):
        """Scan an equity symbol for trading signals."""
        config = self.EQUITY_SYMBOLS.get(symbol)
        if not config:
            return

        log(f"\n[{datetime.now().strftime('%H:%M:%S')}] Scanning {symbol} (equity)...")

        # Fetch bars with timeout
        bars = fetch_futures_bars(symbol, interval='3m', n_bars=500, timeout=30)
        if not bars:
            log(f"  No data for {symbol}")
            return

        # Get today's session bars
        today = datetime.now().date()
        today_bars = [b for b in bars if b.timestamp.date() == today]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 20:
            log(f"  Not enough bars for {symbol}: {len(session_bars)}")
            return

        current_price = session_bars[-1].close
        log(f"  {symbol}: ${current_price:.2f} ({len(session_bars)} bars)")

        # Run V10.3 equity strategy
        results = run_session_v10_equity(
            session_bars,
            bars,
            symbol=symbol,
            risk_per_trade=config['risk_per_trade'],
            max_open_trades=2,
            t1_fixed_4r=True,
            overnight_retrace_min_adx=22,
            midday_cutoff=True,
            pm_cutoff_qqq=True,
            disable_intraday_spy=True,
        )

        # Process signals
        self._process_equity_signals(symbol, results, config)

    def _process_futures_signals(self, symbol: str, results: List[Dict], config: Dict):
        """Process signals from futures strategy."""
        for result in results:
            signal_id = f"{symbol}_{result['entry_time'].strftime('%H%M')}_{result['direction']}"

            # Skip already processed signals
            if signal_id in self.processed_signals[symbol]:
                continue

            # Check if signal is recent (within last scan interval)
            signal_age = (datetime.now() - result['entry_time']).total_seconds()
            if signal_age > self.scan_interval * 2:
                # Old signal, just mark as processed
                self.processed_signals[symbol].add(signal_id)
                continue

            print(f"\n  NEW SIGNAL: {result['direction']} {symbol}")
            print(f"    Entry Type: {result['entry_type']}")
            print(f"    Entry: {result['entry_price']:.2f}")
            print(f"    Stop: {result['stop_price']:.2f}")
            print(f"    Risk: {result['risk']:.2f} pts")
            print(f"    4R Target: {result['target_4r']:.2f}")

            # Check risk manager
            allowed, reason = self.risk_manager.can_enter_trade(
                symbol=symbol,
                direction=result['direction'],
                entry_type=result['entry_type'],
                contracts=config['contracts'],
                risk_pts=result['risk'],
            )

            if not allowed:
                print(f"    BLOCKED: {reason}")
                self.processed_signals[symbol].add(signal_id)
                continue

            # Execute trade
            if self.paper_mode:
                print(f"    [PAPER] Would enter {result['direction']} {config['contracts']} {symbol}")
            else:
                self._execute_futures_signal(symbol, result, config)

            self.processed_signals[symbol].add(signal_id)

    def _process_equity_signals(self, symbol: str, results: List[Dict], config: Dict):
        """Process signals from equity strategy."""
        for result in results:
            signal_id = f"{symbol}_{result['entry_time'].strftime('%H%M')}_{result['direction']}"

            # Skip already processed signals
            if signal_id in self.processed_signals[symbol]:
                continue

            # Check if signal is recent (within last scan interval)
            signal_age = (datetime.now() - result['entry_time']).total_seconds()
            if signal_age > self.scan_interval * 2:
                # Old signal, just mark as processed
                self.processed_signals[symbol].add(signal_id)
                continue

            print(f"\n  NEW SIGNAL: {result['direction']} {symbol}")
            print(f"    Entry Type: {result['entry_type']}")
            print(f"    Entry: ${result['entry_price']:.2f}")
            print(f"    Stop: ${result['stop_price']:.2f}")
            buffer_str = f"${result.get('stop_buffer', 0.02):.3f}" if result.get('stop_buffer') else "$0.02"
            atr_str = f"(ATR=${result.get('atr', 0):.3f})" if result.get('atr') else ""
            print(f"    Risk: ${result['risk']:.2f} | Buffer: {buffer_str} {atr_str}")
            print(f"    Shares: {result['total_shares']}")
            print(f"    P/L: ${result['total_dollars']:+,.2f}")

            # Execute trade (paper mode only for equities currently)
            if self.paper_mode:
                print(f"    [PAPER] Would enter {result['direction']} {result['total_shares']} shares {symbol}")
            else:
                print(f"    [EQUITY LIVE NOT IMPLEMENTED]")

            self.processed_signals[symbol].add(signal_id)

    def _execute_futures_signal(self, symbol: str, result: Dict, config: Dict):
        """Execute a futures trading signal."""
        if not self.order_manager:
            return

        # Create managed trade
        trade = self.order_manager.create_trade_from_signal(
            symbol=config['tradovate_symbol'],
            direction=result['direction'],
            entry_type=result['entry_type'],
            entry_price=result['entry_price'],
            stop_price=result['stop_price'],
            contracts=config['contracts'],
        )

        # Check if price has already moved to entry
        current_bars = fetch_futures_bars(symbol, interval='3m', n_bars=1)
        if current_bars:
            current_price = current_bars[-1].close
            is_long = result['direction'] == 'LONG'

            # Check if we can still get filled at entry price
            if (is_long and current_price <= result['entry_price'] + config['tick_size']) or \
               (not is_long and current_price >= result['entry_price'] - config['tick_size']):
                # Use limit order at entry price
                if self.order_manager.execute_entry(trade):
                    self.risk_manager.record_trade_entry(symbol, config['contracts'])
                    print(f"    ENTRY SENT: {trade.id}")
            else:
                print(f"    Price moved past entry, skipping")

    def _manage_active_trades(self):
        """Manage active trades - check targets and stops."""
        if not self.order_manager:
            return

        active_trades = self.order_manager.get_active_trades()

        for trade in active_trades:
            # Get base symbol for data fetch
            base_symbol = trade.symbol[:2]
            if base_symbol == 'ME':
                base_symbol = trade.symbol[:3]  # MES, MNQ

            # Fetch current price
            bars = fetch_futures_bars(base_symbol, interval='3m', n_bars=10)
            if not bars:
                continue

            current_price = bars[-1].close

            # Check stop (before 4R)
            if self.order_manager.check_stop_hit(trade, current_price):
                self.risk_manager.record_trade_exit(
                    base_symbol,
                    trade.contracts,
                    trade.realized_pnl,
                    is_win=False
                )
                continue

            # Check T1 (4R target)
            if self.order_manager.check_and_execute_t1(trade, current_price):
                self.risk_manager.record_partial_exit(
                    base_symbol,
                    trade.t1_contracts,
                    trade.exits[-1]['pnl_dollars']
                )

            # Update trail stops based on structure
            if len(bars) >= 5:
                # Check for swing highs/lows
                for i in range(len(bars) - 3, len(bars) - 1):
                    if is_swing_high(bars, i, 2):
                        self.order_manager.update_trail_stops(
                            trade,
                            swing_high=bars[i].high
                        )
                    if is_swing_low(bars, i, 2):
                        self.order_manager.update_trail_stops(
                            trade,
                            swing_low=bars[i].low
                        )

            # Check T2 trail
            if self.order_manager.check_and_execute_t2(trade, current_price):
                self.risk_manager.record_partial_exit(
                    base_symbol,
                    trade.t2_contracts,
                    trade.exits[-1]['pnl_dollars']
                )

            # Check runner trail
            if self.order_manager.check_and_execute_runner(trade, current_price):
                self.risk_manager.record_trade_exit(
                    base_symbol,
                    trade.runner_contracts,
                    trade.exits[-1]['pnl_dollars'],
                    is_win=trade.realized_pnl > 0
                )

    def _print_status(self):
        """Print current status."""
        risk_summary = self.risk_manager.get_summary()
        log(f"\n--- Status [{datetime.now().strftime('%H:%M:%S')}] ---")
        log(f"Daily P/L: ${risk_summary['daily_pnl']:+,.2f}")
        log(f"Trades: {risk_summary['daily_trades']} | Open: {risk_summary['open_trades']}")
        log(f"Status: {risk_summary['status'].upper()}")

    def _print_summary(self):
        """Print end-of-session summary."""
        print("\n" + "=" * 70)
        print("SESSION SUMMARY")
        print("=" * 70)

        risk_summary = self.risk_manager.get_summary()
        print(f"Total Trades: {risk_summary['daily_trades']}")
        print(f"Daily P/L: ${risk_summary['daily_pnl']:+,.2f}")

        if self.order_manager:
            trade_summary = self.order_manager.get_trade_summary()
            print(f"Closed: {trade_summary['closed']}")
            print(f"Stopped: {trade_summary['stopped']}")

        print("=" * 70)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='V10.4 Live Trading - Futures + Equities')
    parser.add_argument('--live', action='store_true', help='Enable live trading (default: demo)')
    parser.add_argument('--paper', action='store_true', help='Paper trading mode (signals only)')
    parser.add_argument('--symbols', nargs='+', default=['ES', 'NQ'],
                       help='Symbols to trade (ES, NQ, MES, MNQ, SPY, QQQ)')
    parser.add_argument('--equity-risk', type=int, default=500,
                       help='Risk per trade for equities in dollars (default: 500)')
    args = parser.parse_args()

    # Validate symbols
    valid_futures = ['ES', 'NQ', 'MES', 'MNQ']
    valid_equities = ['SPY', 'QQQ']
    valid_symbols = valid_futures + valid_equities

    for sym in args.symbols:
        if sym not in valid_symbols:
            print(f"Invalid symbol: {sym}")
            print(f"Valid symbols: {', '.join(valid_symbols)}")
            return

    # Determine mode
    paper_mode = args.paper or (not args.live)
    environment = 'live' if args.live else 'demo'

    # Categorize symbols
    futures = [s for s in args.symbols if s in valid_futures]
    equities = [s for s in args.symbols if s in valid_equities]

    print(f"Starting V10.4 Live Trader...")
    print(f"Environment: {environment.upper()}")
    print(f"Paper Mode: {paper_mode}")
    if futures:
        print(f"Futures: {', '.join(futures)} (2-tick buffer)")
    if equities:
        print(f"Equities: {', '.join(equities)} (${args.equity_risk}/trade, ATR buffer)")

    # Create client (unless paper mode)
    client = None
    if not paper_mode:
        try:
            client = create_client(environment)
        except Exception as e:
            print(f"Failed to create client: {e}")
            print("Falling back to paper mode")
            paper_mode = True

    # Create trader
    trader = LiveTrader(
        client=client,
        paper_mode=paper_mode,
        symbols=args.symbols,
        equity_risk=args.equity_risk,
    )

    # Start trading
    trader.start()


if __name__ == '__main__':
    main()
