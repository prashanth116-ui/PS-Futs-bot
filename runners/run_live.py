"""
V10.8 Live Trading Runner - Combined Futures + Equities

Main entry point for live trading with the V10.8 strategy.
Supports both futures (ES, NQ, MES, MNQ) and equities (SPY, QQQ).

V10.8 Changes:
- Hybrid filter system (2 mandatory + 2/3 optional filters)
- Paper mode now simulates trades and tracks P/L
- Full trade lifecycle: entry -> stops/targets -> P/L tracking

Usage:
    python -m runners.run_live --paper                    # Paper mode, default symbols
    python -m runners.run_live --paper --symbols ES NQ    # Paper mode, specific futures
    python -m runners.run_live --paper --symbols SPY QQQ  # Paper mode, equities
    python -m runners.run_live --paper --symbols ES NQ SPY QQQ  # All supported
    python -m runners.run_live --live                     # Live mode (be careful!)
"""
import sys
sys.path.insert(0, '.')

import argparse
import time
import signal
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

# EST timezone for all trading operations
EST = ZoneInfo('America/New_York')


def get_est_now() -> datetime:
    """Get current time in EST."""
    return datetime.now(EST)


def to_est_aware(dt: datetime) -> datetime:
    """Convert any datetime to EST-aware datetime.

    Handles both naive (assumed EST) and aware datetimes.
    """
    if dt is None:
        return get_est_now()
    if dt.tzinfo is None:
        # Naive datetime - assume it's already EST (TradingView convention)
        return dt.replace(tzinfo=EST)
    else:
        # Aware datetime - convert to EST
        return dt.astimezone(EST)


def safe_datetime_diff_seconds(dt1: datetime, dt2: datetime) -> float:
    """Safely calculate difference between two datetimes in seconds.

    Handles mixed timezone-aware and naive datetimes.
    """
    dt1_aware = to_est_aware(dt1)
    dt2_aware = to_est_aware(dt2)
    return (dt1_aware - dt2_aware).total_seconds()


def log(msg: str):
    """Print with explicit flush for reliable output."""
    print(msg)
    sys.stdout.flush()

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, List

from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10, is_swing_high, is_swing_low
from runners.run_v10_equity import run_session_v10_equity
from runners.tradovate_client import TradovateClient, create_client
from runners.order_manager import OrderManager
from runners.risk_manager import RiskManager, create_default_risk_manager
from runners.notifier import notify_entry, notify_exit, notify_daily_summary, notify_status


class PaperTradeStatus(Enum):
    """Status of a paper trade."""
    PENDING = "pending"       # Waiting for entry fill
    OPEN = "open"             # Trade is active
    CLOSED = "closed"         # Trade completed


@dataclass
class PaperTrade:
    """Simulated paper trade with full lifecycle tracking."""
    id: str
    symbol: str
    direction: str  # LONG or SHORT
    entry_type: str
    entry_price: float
    stop_price: float
    target_4r: float
    target_8r: float

    # Position details
    contracts: int = 3
    tick_size: float = 0.25
    tick_value: float = 12.50
    asset_type: str = "futures"  # futures or equity

    # Trade state
    status: PaperTradeStatus = PaperTradeStatus.OPEN
    entry_time: datetime = None
    exit_time: datetime = None
    exit_price: float = 0.0
    exit_reason: str = ""

    # P/L tracking - 3 contract structure
    t1_hit: bool = False  # 1 contract at 4R
    t2_hit: bool = False  # 1 contract at trail
    runner_exit: bool = False  # 1 contract at trail

    t1_pnl: float = 0.0
    t2_pnl: float = 0.0
    runner_pnl: float = 0.0

    # Trail stops (activated after 4R)
    t2_trail_stop: float = 0.0
    runner_trail_stop: float = 0.0
    trail_active: bool = False

    @property
    def is_long(self) -> bool:
        return self.direction == "LONG"

    @property
    def total_pnl(self) -> float:
        return self.t1_pnl + self.t2_pnl + self.runner_pnl

    @property
    def risk_pts(self) -> float:
        return abs(self.entry_price - self.stop_price)

    def calculate_pnl(self, exit_price: float, contracts: int) -> float:
        """Calculate P/L for given exit price and contracts."""
        if self.asset_type == "futures":
            pts_move = (exit_price - self.entry_price) if self.is_long else (self.entry_price - exit_price)
            ticks = pts_move / self.tick_size
            return ticks * self.tick_value * contracts
        else:
            # Equity: simple price difference
            price_move = (exit_price - self.entry_price) if self.is_long else (self.entry_price - exit_price)
            return price_move * contracts


class LiveTrader:
    """
    V10.8 Live Trading System - Combined Futures + Equities

    Runs the strategy in real-time, generating signals and executing trades.

    V10.8: BOS LOSS_LIMIT (stop after 1 BOS loss/day), ES/SPY BOS disabled
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

        # Paper trading simulation
        self.paper_trades: Dict[str, PaperTrade] = {}  # trade_id -> PaperTrade
        self.paper_trade_counter = 0
        self.paper_daily_pnl = 0.0
        self.paper_daily_trades = 0
        self.paper_daily_wins = 0
        self.paper_daily_losses = 0

        # Price tracking for heartbeat
        self.last_prices: Dict[str, float] = {}

        # Telegram heartbeat (every 30 min)
        self.last_telegram_heartbeat: datetime = None

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
        print("V10.8 LIVE TRADER - Combined Futures + Equities")
        print("=" * 70)
        print(f"Mode: {'PAPER' if self.paper_mode else 'LIVE'}")
        if self.futures_symbols:
            print(f"Futures: {', '.join(self.futures_symbols)} (2-tick buffer)")
        if self.equity_symbols:
            print(f"Equities: {', '.join(self.equity_symbols)} (${self.equity_risk}/trade, ATR buffer)")
        print(f"Scan interval: {self.scan_interval}s")
        print(f"Timezone: EST (Current: {get_est_now().strftime('%H:%M:%S')})")
        print("Futures hours: 4:00-16:00 ET | Equities: 9:30-16:00 ET")
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

        # Send Telegram startup notification
        mode = "PAPER" if self.paper_mode else "LIVE"
        notify_status(f"V10.8 {mode} Trading started\nSymbols: {', '.join(self.symbols)}")

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
                current_time = get_est_now()

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

                # Manage paper trades (in paper mode)
                if self.paper_mode and self.paper_trades:
                    self._manage_paper_trades()

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
        """Sleep in small increments, allowing for interrupt."""
        elapsed = 0
        while elapsed < seconds and self.running:
            sleep_chunk = min(30, seconds - elapsed)
            time.sleep(sleep_chunk)
            elapsed += sleep_chunk

    def _is_trading_hours(self, dt: datetime) -> bool:
        """Check if within trading hours (EST).

        Futures: 4:00-16:00 ET (pre-market + RTH)
        Equities: 9:30-16:00 ET (RTH only)
        """
        # Convert to EST if not already
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=EST)
        else:
            dt = dt.astimezone(EST)

        current_time = dt.time()

        # Futures trade pre-market (4:00 AM ET)
        if self.futures_symbols:
            futures_start = dt_time(4, 0)
            futures_end = dt_time(16, 0)
            if futures_start <= current_time <= futures_end:
                return True

        # Equities trade RTH only (9:30 AM ET)
        if self.equity_symbols:
            equity_start = dt_time(9, 30)
            equity_end = dt_time(16, 0)
            if equity_start <= current_time <= equity_end:
                return True

        return False

    def _scan_futures_symbol(self, symbol: str):
        """Scan a futures symbol for trading signals."""
        config = self.FUTURES_SYMBOLS.get(symbol)
        if not config:
            return

        log(f"\n[{get_est_now().strftime('%H:%M:%S')}] Scanning {symbol} (futures)...")

        # Fetch bars with timeout
        bars = fetch_futures_bars(symbol, interval='3m', n_bars=500, timeout=30)
        if not bars:
            log(f"  No data for {symbol}")
            return

        # Get today's session bars
        today = get_est_now().date()
        today_bars = [b for b in bars if b.timestamp.date() == today]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 20:
            log(f"  Not enough bars for {symbol}: {len(session_bars)}")
            return

        current_price = session_bars[-1].close
        self.last_prices[symbol] = current_price
        log(f"  {symbol}: {current_price:.2f} ({len(session_bars)} bars)")

        # V10.8: ES BOS disabled (20% WR), NQ BOS enabled with loss limit
        disable_bos = symbol in ['ES', 'MES']

        # Run V10.8 strategy to get signals
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
            # V10.8 BOS controls
            disable_bos_retrace=disable_bos,  # ES/MES: off, NQ/MNQ: on
            bos_daily_loss_limit=1,  # Stop BOS after 1 loss per day
        )

        # Process signals
        self._process_futures_signals(symbol, results, config)

    def _scan_equity_symbol(self, symbol: str):
        """Scan an equity symbol for trading signals."""
        config = self.EQUITY_SYMBOLS.get(symbol)
        if not config:
            return

        log(f"\n[{get_est_now().strftime('%H:%M:%S')}] Scanning {symbol} (equity)...")

        # Fetch bars with timeout
        bars = fetch_futures_bars(symbol, interval='3m', n_bars=500, timeout=30)
        if not bars:
            log(f"  No data for {symbol}")
            return

        # Get today's session bars
        today = get_est_now().date()
        today_bars = [b for b in bars if b.timestamp.date() == today]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 20:
            log(f"  Not enough bars for {symbol}: {len(session_bars)}")
            return

        current_price = session_bars[-1].close
        self.last_prices[symbol] = current_price
        log(f"  {symbol}: ${current_price:.2f} ({len(session_bars)} bars)")

        # V10.8: SPY BOS disabled, QQQ BOS enabled with loss limit
        disable_bos = symbol == 'SPY'

        # Run V10.8 equity strategy
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
            # V10.8 BOS controls
            disable_bos_retrace=disable_bos,  # SPY: off, QQQ: on
            bos_daily_loss_limit=1,  # Stop BOS after 1 loss per day
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
            entry_time = result['entry_time']
            signal_age = safe_datetime_diff_seconds(get_est_now(), entry_time)
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

            # Send Telegram notification (only for trades that pass risk check)
            notify_entry(
                symbol=symbol,
                direction=result['direction'],
                entry_type=result['entry_type'],
                entry_price=result['entry_price'],
                stop_price=result['stop_price'],
                contracts=config['contracts'],
                risk_pts=result['risk'],
            )

            # Execute trade
            if self.paper_mode:
                # Create simulated paper trade
                self._create_paper_trade(symbol, result, config, asset_type='futures')
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
            entry_time = result['entry_time']
            signal_age = safe_datetime_diff_seconds(get_est_now(), entry_time)
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

            # Send Telegram notification (only for trades that pass filters)
            notify_entry(
                symbol=symbol,
                direction=result['direction'],
                entry_type=result['entry_type'],
                entry_price=result['entry_price'],
                stop_price=result['stop_price'],
                contracts=result['total_shares'],
                risk_pts=result['risk'],
            )

            # Execute trade
            if self.paper_mode:
                # Create simulated paper trade for equity
                self._create_paper_trade(symbol, result, config, asset_type='equity')
            else:
                print("    [EQUITY LIVE NOT IMPLEMENTED]")

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
                print("    Price moved past entry, skipping")

    def _create_paper_trade(self, symbol: str, result: Dict, config: Dict, asset_type: str = 'futures'):
        """Create a simulated paper trade."""
        self.paper_trade_counter += 1
        trade_id = f"PAPER_{symbol}_{self.paper_trade_counter}"

        # Calculate risk and targets
        entry_price = result['entry_price']
        stop_price = result['stop_price']
        risk = abs(entry_price - stop_price)
        is_long = result['direction'] == 'LONG'

        if is_long:
            target_4r = entry_price + (4 * risk)
            target_8r = entry_price + (8 * risk)
        else:
            target_4r = entry_price - (4 * risk)
            target_8r = entry_price - (8 * risk)

        # Get contracts/shares
        if asset_type == 'futures':
            contracts = config['contracts']
            tick_size = config['tick_size']
            tick_value = config['tick_value']
        else:
            contracts = result.get('total_shares', 100)
            tick_size = 0.01
            tick_value = 1.0

        # Create paper trade
        paper_trade = PaperTrade(
            id=trade_id,
            symbol=symbol,
            direction=result['direction'],
            entry_type=result['entry_type'],
            entry_price=entry_price,
            stop_price=stop_price,
            target_4r=target_4r,
            target_8r=target_8r,
            contracts=contracts,
            tick_size=tick_size,
            tick_value=tick_value,
            asset_type=asset_type,
            entry_time=get_est_now(),
        )

        self.paper_trades[trade_id] = paper_trade

        log(f"    [PAPER] OPENED: {result['direction']} {contracts} {symbol}")
        log(f"    Entry: {entry_price:.2f} | Stop: {stop_price:.2f} | 4R: {target_4r:.2f}")
        log(f"    Trade ID: {trade_id}")

    def _manage_paper_trades(self):
        """Manage open paper trades - check stops and targets."""
        closed_trades = []

        for trade_id, trade in self.paper_trades.items():
            if trade.status != PaperTradeStatus.OPEN:
                continue

            # Fetch current price
            bars = fetch_futures_bars(trade.symbol, interval='3m', n_bars=10, timeout=15)
            if not bars or len(bars) < 1:
                continue

            bars[-1].close
            current_high = bars[-1].high
            current_low = bars[-1].low

            # Check stop loss (full position if not yet at 4R)
            stop_hit = False
            if trade.is_long:
                stop_hit = current_low <= trade.stop_price
            else:
                stop_hit = current_high >= trade.stop_price

            if stop_hit and not trade.t1_hit:
                # Full stop - all 3 contracts
                trade.exit_price = trade.stop_price
                trade.exit_reason = "STOP"
                trade.t1_pnl = trade.calculate_pnl(trade.stop_price, 1)
                trade.t2_pnl = trade.calculate_pnl(trade.stop_price, 1)
                trade.runner_pnl = trade.calculate_pnl(trade.stop_price, 1)
                trade.status = PaperTradeStatus.CLOSED
                trade.exit_time = get_est_now()

                self.paper_daily_pnl += trade.total_pnl
                self.paper_daily_trades += 1
                self.paper_daily_losses += 1

                log(f"\n  [PAPER] STOPPED: {trade.symbol} {trade.direction}")
                log(f"    P/L: ${trade.total_pnl:+,.2f} (full stop)")

                notify_exit(
                    symbol=trade.symbol,
                    direction=trade.direction,
                    exit_type="STOP",
                    exit_price=trade.stop_price,
                    pnl=trade.total_pnl,
                    contracts=trade.contracts,
                )

                closed_trades.append(trade_id)
                continue

            # Check 4R target (T1 - 1 contract)
            if not trade.t1_hit:
                t1_hit = False
                if trade.is_long:
                    t1_hit = current_high >= trade.target_4r
                else:
                    t1_hit = current_low <= trade.target_4r

                if t1_hit:
                    trade.t1_hit = True
                    trade.t1_pnl = trade.calculate_pnl(trade.target_4r, 1)
                    trade.trail_active = True

                    # Set initial trail stops at entry (breakeven)
                    trade.t2_trail_stop = trade.entry_price
                    trade.runner_trail_stop = trade.entry_price

                    log(f"\n  [PAPER] T1 HIT: {trade.symbol} +${trade.t1_pnl:,.2f} (4R)")
                    log("    Trail stops activated at breakeven")

            # Update trail stops based on structure (if trail active)
            if trade.trail_active and len(bars) >= 5:
                # Look for swing points to update trails
                for i in range(len(bars) - 4, len(bars) - 1):
                    if trade.is_long:
                        # For longs, trail below swing lows
                        if is_swing_low(bars, i, 2):
                            new_trail = bars[i].low - (4 * trade.tick_size)  # 4-tick buffer
                            if new_trail > trade.t2_trail_stop:
                                trade.t2_trail_stop = new_trail
                            new_runner_trail = bars[i].low - (6 * trade.tick_size)  # 6-tick buffer
                            if new_runner_trail > trade.runner_trail_stop:
                                trade.runner_trail_stop = new_runner_trail
                    else:
                        # For shorts, trail above swing highs
                        if is_swing_high(bars, i, 2):
                            new_trail = bars[i].high + (4 * trade.tick_size)
                            if new_trail < trade.t2_trail_stop or trade.t2_trail_stop == trade.entry_price:
                                trade.t2_trail_stop = new_trail
                            new_runner_trail = bars[i].high + (6 * trade.tick_size)
                            if new_runner_trail < trade.runner_trail_stop or trade.runner_trail_stop == trade.entry_price:
                                trade.runner_trail_stop = new_runner_trail

            # Check T2 trail stop (after T1 hit)
            if trade.t1_hit and not trade.t2_hit and trade.t2_trail_stop > 0:
                t2_stopped = False
                if trade.is_long:
                    t2_stopped = current_low <= trade.t2_trail_stop
                else:
                    t2_stopped = current_high >= trade.t2_trail_stop

                if t2_stopped:
                    trade.t2_hit = True
                    trade.t2_pnl = trade.calculate_pnl(trade.t2_trail_stop, 1)
                    log(f"\n  [PAPER] T2 TRAIL: {trade.symbol} +${trade.t2_pnl:,.2f}")

            # Check runner trail stop
            if trade.t1_hit and trade.t2_hit and not trade.runner_exit and trade.runner_trail_stop > 0:
                runner_stopped = False
                if trade.is_long:
                    runner_stopped = current_low <= trade.runner_trail_stop
                else:
                    runner_stopped = current_high >= trade.runner_trail_stop

                if runner_stopped:
                    trade.runner_exit = True
                    trade.runner_pnl = trade.calculate_pnl(trade.runner_trail_stop, 1)
                    trade.status = PaperTradeStatus.CLOSED
                    trade.exit_time = get_est_now()
                    trade.exit_price = trade.runner_trail_stop
                    trade.exit_reason = "RUNNER_TRAIL"

                    self.paper_daily_pnl += trade.total_pnl
                    self.paper_daily_trades += 1
                    self.paper_daily_wins += 1

                    log(f"\n  [PAPER] CLOSED: {trade.symbol} {trade.direction}")
                    log(f"    T1: ${trade.t1_pnl:+,.2f} | T2: ${trade.t2_pnl:+,.2f} | Runner: ${trade.runner_pnl:+,.2f}")
                    log(f"    Total P/L: ${trade.total_pnl:+,.2f}")

                    notify_exit(
                        symbol=trade.symbol,
                        direction=trade.direction,
                        exit_type="RUNNER_TRAIL",
                        exit_price=trade.runner_trail_stop,
                        pnl=trade.total_pnl,
                        contracts=trade.contracts,
                    )

                    closed_trades.append(trade_id)

            # Check 8R target (close runner early for big win)
            if trade.t1_hit and not trade.runner_exit:
                t8r_hit = False
                if trade.is_long:
                    t8r_hit = current_high >= trade.target_8r
                else:
                    t8r_hit = current_low <= trade.target_8r

                if t8r_hit:
                    # Close T2 and runner at 8R
                    if not trade.t2_hit:
                        trade.t2_hit = True
                        trade.t2_pnl = trade.calculate_pnl(trade.target_8r, 1)

                    trade.runner_exit = True
                    trade.runner_pnl = trade.calculate_pnl(trade.target_8r, 1)
                    trade.status = PaperTradeStatus.CLOSED
                    trade.exit_time = get_est_now()
                    trade.exit_price = trade.target_8r
                    trade.exit_reason = "8R_TARGET"

                    self.paper_daily_pnl += trade.total_pnl
                    self.paper_daily_trades += 1
                    self.paper_daily_wins += 1

                    log(f"\n  [PAPER] 8R TARGET: {trade.symbol} {trade.direction}")
                    log(f"    T1: ${trade.t1_pnl:+,.2f} | T2: ${trade.t2_pnl:+,.2f} | Runner: ${trade.runner_pnl:+,.2f}")
                    log(f"    Total P/L: ${trade.total_pnl:+,.2f}")

                    notify_exit(
                        symbol=trade.symbol,
                        direction=trade.direction,
                        exit_type="8R_TARGET",
                        exit_price=trade.target_8r,
                        pnl=trade.total_pnl,
                        contracts=trade.contracts,
                    )

                    closed_trades.append(trade_id)

        # Remove closed trades from active tracking
        for trade_id in closed_trades:
            del self.paper_trades[trade_id]

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
        """Print heartbeat status line for log monitoring."""
        now = get_est_now()
        timestamp = now.strftime('%H:%M:%S')

        # Build price string from last known prices
        price_parts = []
        for sym in self.symbols:
            if sym in self.last_prices:
                price = self.last_prices[sym]
                if sym in self.EQUITY_SYMBOLS:
                    price_parts.append(f"{sym}=${price:.2f}")
                else:
                    price_parts.append(f"{sym}={price:.2f}")
        prices_str = " ".join(price_parts) if price_parts else "no data"

        if self.paper_mode:
            open_trades = len(self.paper_trades)
            log(f"[HEARTBEAT] {timestamp} | {prices_str} | Trades: {self.paper_daily_trades} | P/L: ${self.paper_daily_pnl:+,.2f} | Open: {open_trades}")
        else:
            risk_summary = self.risk_manager.get_summary()
            log(f"[HEARTBEAT] {timestamp} | {prices_str} | Trades: {risk_summary['daily_trades']} | P/L: ${risk_summary['daily_pnl']:+,.2f} | Open: {risk_summary['open_trades']}")

        # Telegram heartbeat every 1 hour
        send_telegram = False
        if self.last_telegram_heartbeat is None:
            send_telegram = True
        else:
            elapsed = safe_datetime_diff_seconds(now, self.last_telegram_heartbeat)
            if elapsed >= 3600:  # 1 hour
                send_telegram = True

        if send_telegram:
            self.last_telegram_heartbeat = now
            mode = "PAPER" if self.paper_mode else "LIVE"
            if self.paper_mode:
                open_trades = len(self.paper_trades)
                tg_msg = f"[{mode}] {timestamp} | {prices_str} | Trades: {self.paper_daily_trades} | P/L: ${self.paper_daily_pnl:+,.2f} | Open: {open_trades}"
            else:
                risk_summary = self.risk_manager.get_summary()
                tg_msg = f"[{mode}] {timestamp} | {prices_str} | Trades: {risk_summary['daily_trades']} | P/L: ${risk_summary['daily_pnl']:+,.2f} | Open: {risk_summary['open_trades']}"
            try:
                notify_status(tg_msg)
            except Exception:
                pass  # Don't let Telegram failures break the loop

    def _print_summary(self):
        """Print end-of-session summary."""
        print("\n" + "=" * 70)
        print("SESSION SUMMARY")
        print("=" * 70)

        if self.paper_mode:
            # Paper mode summary
            print("Mode: PAPER TRADING")
            print(f"Total Trades: {self.paper_daily_trades}")
            print(f"Wins: {self.paper_daily_wins} | Losses: {self.paper_daily_losses}")
            if self.paper_daily_trades > 0:
                win_rate = (self.paper_daily_wins / self.paper_daily_trades) * 100
                print(f"Win Rate: {win_rate:.1f}%")
            print(f"Daily P/L: ${self.paper_daily_pnl:+,.2f}")

            # Show any still-open trades
            if self.paper_trades:
                print(f"\nOpen Trades ({len(self.paper_trades)}):")
                for trade in self.paper_trades.values():
                    partial = f" [T1: ${trade.t1_pnl:+,.2f}]" if trade.t1_hit else ""
                    print(f"  {trade.symbol} {trade.direction} @ {trade.entry_price:.2f}{partial}")

            # Send Telegram summary
            notify_daily_summary(
                trades=self.paper_daily_trades,
                wins=self.paper_daily_wins,
                losses=self.paper_daily_losses,
                total_pnl=self.paper_daily_pnl,
                symbols_traded=self.symbols,
            )
        else:
            # Live mode summary
            risk_summary = self.risk_manager.get_summary()
            print(f"Total Trades: {risk_summary['daily_trades']}")
            print(f"Daily P/L: ${risk_summary['daily_pnl']:+,.2f}")

            if self.order_manager:
                trade_summary = self.order_manager.get_trade_summary()
                print(f"Closed: {trade_summary['closed']}")
                print(f"Stopped: {trade_summary['stopped']}")

            notify_daily_summary(
                trades=risk_summary['daily_trades'],
                wins=risk_summary.get('daily_wins', 0),
                losses=risk_summary.get('daily_losses', 0),
                total_pnl=risk_summary['daily_pnl'],
                symbols_traded=self.symbols,
            )

        print("=" * 70)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='V10.8 Live Trading - Futures + Equities')
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

    print("Starting V10.8 Live Trader...")
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
