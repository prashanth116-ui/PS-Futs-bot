"""
V10.15 Live Trading Runner - Combined Futures + Equities

Main entry point for live trading with the V10.15 strategy.
Supports both futures (ES, NQ, MES, MNQ) and equities (SPY, QQQ).

V10.10 Changes:
- Hybrid filter system (2 mandatory + 2/3 optional filters)
- Paper mode now simulates trades and tracks P/L
- Full trade lifecycle: entry -> stops/targets -> P/L tracking

Usage:
    python -m runners.run_live --paper                    # Paper mode, default symbols
    python -m runners.run_live --paper --symbols ES MES   # Paper mode, specific futures
    python -m runners.run_live --paper --symbols SPY QQQ  # Paper mode, equities
    python -m runners.run_live --paper --symbols ES NQ SPY QQQ  # All supported
    python -m runners.run_live --live                     # Live mode (be careful!)
"""
import sys
sys.path.insert(0, '.')

from version import STRATEGY_VERSION

import argparse
import time
import signal
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time
from enum import Enum
from typing import Optional, Dict, List
from zoneinfo import ZoneInfo

from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10, is_swing_high, is_swing_low
from strategies.ict.signals.fvg import detect_fvgs, update_fvg_mitigation
from runners.run_v10_equity import run_session_v10_equity
from runners.tradovate_client import TradovateClient, create_client
from runners.order_manager import OrderManager
from runners.risk_manager import RiskManager, create_default_risk_manager
from runners.notifier import notify_entry, notify_exit, notify_daily_summary, notify_status, notify_next_day_outlook
from runners.bar_storage import save_daily_bars, load_bars_with_history
from runners.webhook_executor import WebhookExecutor
from runners.executor_interface import ExecutorInterface
from runners.divergence_tracker import save_live_trades, compare_day, format_console_report, format_telegram_alert

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

    # V10.9 targets
    plus_4r: float = 0.0  # 3R price level (floor for T2/runner after 6R touch)
    has_runner: bool = True  # False for 2-ct trades

    # P/L tracking - 3 contract structure (or 2-ct: T1+T2 only)
    t1_hit: bool = False  # 1 contract at 3R (V10.9)
    t2_hit: bool = False  # 1 contract at trail
    runner_exit: bool = False  # 1 contract at trail (only if has_runner)

    t1_pnl: float = 0.0
    t2_pnl: float = 0.0
    runner_pnl: float = 0.0

    # Two-stage trail (V10.9 parity)
    t1_trail_stop: float = 0.0  # Between 3R and 6R: trail for all remaining cts
    t2_trail_stop: float = 0.0  # After 6R: T2 trail (4-tick buffer)
    runner_trail_stop: float = 0.0  # After 6R: runner trail (6-tick buffer)
    touched_8r: bool = False  # Whether 6R has been touched (gates T2/runner trails)
    trail_active: bool = False  # T1 has been hit

    # Last swing tracking (backtest parity — only accept swings beyond previous)
    t1_last_swing: float = 0.0
    t2_last_swing: float = 0.0
    runner_last_swing: float = 0.0

    # Pending broker operations — retried every scan until they succeed
    # Each entry: {'op': 'close'|'partial_close'|'update_stop', **kwargs}
    pending_broker_ops: List = field(default_factory=list)

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
    V10.15 Live Trading System - Combined Futures + Equities

    Runs the strategy in real-time, generating signals and executing trades.

    V10.15: Global consecutive loss stop (ES/MES: 2 consec losses → stop for day)
    """

    # Futures symbol configurations
    FUTURES_SYMBOLS = {
        'ES': {
            'tradovate_symbol': 'ESM6',
            'tick_size': 0.25,
            'tick_value': 12.50,
            'min_risk': 1.5,
            'max_bos_risk': 8.0,
            'max_retrace_risk': 8.0,
            'contracts': 3,
            'type': 'futures',
            'opp_fvg_exit': True,
            'opp_fvg_min_ticks': 10,   # B2: after 6R, 10 ticks
            'opp_fvg_after_6r': True,
        },
        'NQ': {
            'tradovate_symbol': 'NQM6',
            'tick_size': 0.25,
            'tick_value': 5.00,
            'min_risk': 6.0,
            'max_bos_risk': 20.0,
            'max_retrace_risk': None,
            'contracts': 3,
            'type': 'futures',
            'opp_fvg_exit': True,
            'opp_fvg_min_ticks': 5,    # B1: after 6R, 5 ticks
            'opp_fvg_after_6r': True,
        },
        'MES': {
            'tradovate_symbol': 'MESM6',
            'tick_size': 0.25,
            'tick_value': 1.25,
            'min_risk': 1.5,
            'max_bos_risk': 8.0,
            'max_retrace_risk': 8.0,
            'contracts': 3,
            'type': 'futures',
            'opp_fvg_exit': True,
            'opp_fvg_min_ticks': 10,   # B2: after 6R, 10 ticks (same as ES)
            'opp_fvg_after_6r': True,
        },
        'MNQ': {
            'tradovate_symbol': 'MNQM6',
            'tick_size': 0.25,
            'tick_value': 0.50,
            'min_risk': 6.0,
            'max_bos_risk': 20.0,
            'max_retrace_risk': None,
            'contracts': 3,
            'type': 'futures',
            'opp_fvg_exit': True,
            'opp_fvg_min_ticks': 5,    # B1: after 6R, 5 ticks (same as NQ)
            'opp_fvg_after_6r': True,
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
        executor: Optional[ExecutorInterface] = None,
    ):
        """
        Initialize live trader.

        Args:
            client: Tradovate API client (None for paper mode)
            risk_manager: Risk manager instance
            paper_mode: If True, only log signals without executing
            symbols: List of symbols to trade (default: ['ES', 'NQ'])
            equity_risk: Risk per trade for equities in dollars
            executor: Executor backend (TradovateExecutor, WebhookExecutor,
                      or MultiExecutor). None = no broker execution.
        """
        self.client = client
        self.risk_manager = risk_manager or create_default_risk_manager()
        self.paper_mode = paper_mode
        self.symbols = symbols or ['ES', 'MES']
        self.equity_risk = equity_risk
        self.executor = executor

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
        self.paper_trade_history: List[Dict] = []  # Snapshots of closed trades for divergence tracking

        # Orphaned broker ops from closed trades (retried until they succeed)
        self._orphaned_broker_ops: List[Dict] = []

        # Broker health tracking
        self._broker_healthy: bool = True
        self._last_broker_health_check: Optional[datetime] = None
        self._broker_health_interval = 900  # 15 minutes between health checks

        # Cached bars and FVGs for opposing FVG exit (refreshed each scan cycle)
        self._cached_all_bars: Dict[str, list] = {}
        self._cached_fvgs: Dict[str, list] = {}
        self._cached_fvgs_time: Dict[str, datetime] = {}  # Track when FVG cache was last updated

        # Price tracking for heartbeat
        self.last_prices: Dict[str, float] = {}

        # Telegram heartbeat (every 1 hour)
        self.last_telegram_heartbeat: datetime = None

        # Scan interval (3 minutes to match bar interval)
        self.scan_interval = 180  # seconds

        # Signal for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _check_broker_health(self):
        """Periodic broker health check. Attempts reconnect if down, alerts via Telegram.

        Checks every 15 min when healthy, every 5 min when down (faster recovery).
        """
        if not self.executor or not hasattr(self.executor, 'client'):
            return

        now = get_est_now()
        interval = 300 if not self._broker_healthy else self._broker_health_interval  # 5 min when down
        if (self._last_broker_health_check and
                (now - self._last_broker_health_check).total_seconds() < interval):
            return

        self._last_broker_health_check = now
        try:
            positions = self.executor.client.get_positions()
            # get_positions() returns empty list on success (even with no positions)
            # but raises or returns None-ish on auth failure
            if positions is not None:
                if not self._broker_healthy:
                    log("[BROKER] Connection restored")
                    notify_status("[BROKER] Connection restored — resuming broker execution")
                self._broker_healthy = True
                return
        except Exception as e:
            log(f"[BROKER] Health check failed: {e}")

        # Broker is down — try to reconnect
        if self._broker_healthy:
            # First failure — try reconnect before alerting
            log("[BROKER] Connection lost, attempting reconnect...")
            try:
                if self.executor.client.connect():
                    log("[BROKER] Reconnected successfully")
                    self._broker_healthy = True
                    return
            except Exception:
                pass

        self._broker_healthy = False
        log("[BROKER] DOWN — paper trades will continue but broker orders will fail")
        notify_status(
            "[BROKER DOWN] Tradovate API unreachable. Paper trades continuing "
            "but NO broker execution. Check credentials/connection."
        )

    def _retry_pending_broker_ops(self):
        """Retry failed broker operations (close, partial_close, update_stop).

        Each scan cycle, attempts any queued operations. On success, removes
        from the queue. On failure, keeps retrying. Sends alert on first failure.
        """
        # Collect all trades with pending ops (including closed trades not yet cleaned up)
        all_trades = list(self.paper_trades.values())
        for trade in all_trades:
            if not hasattr(trade, 'pending_broker_ops') or not trade.pending_broker_ops:
                continue

            remaining_ops = []
            for op in trade.pending_broker_ops:
                op_type = op['op']
                success = False
                try:
                    if op_type == 'close':
                        result = self.executor.close_position(
                            symbol=trade.symbol, direction=trade.direction,
                            paper_trade_id=trade.id,
                        )
                        success = result and result.get('success', False)
                    elif op_type == 'partial_close':
                        result = self.executor.partial_close(
                            symbol=trade.symbol, direction=trade.direction,
                            contracts=op['contracts'], paper_trade_id=trade.id,
                        )
                        success = result and result.get('success', False)
                    elif op_type == 'update_stop':
                        result = self.executor.update_stop(
                            symbol=trade.symbol, direction=trade.direction,
                            new_stop_price=op['stop_price'],
                            entry_price=trade.entry_price,
                            paper_trade_id=trade.id,
                        )
                        success = result and result.get('success', False)
                except Exception as e:
                    log(f"    [BROKER RETRY] {op_type} {trade.id} still failing: {e}")

                if success:
                    log(f"    [BROKER RETRY] {op_type} {trade.id} succeeded")
                else:
                    remaining_ops.append(op)

            trade.pending_broker_ops = remaining_ops

        # Retry orphaned ops from deleted trades
        if self._orphaned_broker_ops:
            still_orphaned = []
            for op in self._orphaned_broker_ops:
                op_type = op['op']
                trade_id = op.get('_trade_id', 'unknown')
                success = False
                try:
                    if op_type == 'close':
                        result = self.executor.close_position(
                            symbol=op['_symbol'], direction=op['_direction'],
                            paper_trade_id=trade_id,
                        )
                        success = result and result.get('success', False)
                    elif op_type == 'partial_close':
                        result = self.executor.partial_close(
                            symbol=op['_symbol'], direction=op['_direction'],
                            contracts=op['contracts'], paper_trade_id=trade_id,
                        )
                        success = result and result.get('success', False)
                    elif op_type == 'update_stop':
                        result = self.executor.update_stop(
                            symbol=op['_symbol'], direction=op['_direction'],
                            new_stop_price=op['stop_price'],
                            entry_price=op['_entry_price'],
                            paper_trade_id=trade_id,
                        )
                        success = result and result.get('success', False)
                except Exception as e:
                    log(f"    [BROKER RETRY] orphaned {op_type} {trade_id} still failing: {e}")

                if success:
                    log(f"    [BROKER RETRY] orphaned {op_type} {trade_id} succeeded")
                else:
                    still_orphaned.append(op)

            self._orphaned_broker_ops = still_orphaned

    def _should_retry_broker_op(self, result) -> bool:
        """Check if a failed broker op should be retried.

        Returns False for permanent failures (e.g., stop order already fired)
        that would loop forever in the retry queue.
        """
        if result and result.get('permanent'):
            return False
        return True

    def _queue_broker_op(self, trade, op_type: str, result=None, **kwargs):
        """Queue a failed broker operation for retry on next scan.

        Skips queueing if the failure is permanent (stop already fired, etc.).
        Deduplicates: if an op of the same type is already queued, updates its
        parameters (e.g. stop_price) instead of appending a duplicate.
        Only sends Telegram alert on the first failure, not on every retry.
        """
        if result and result.get('permanent'):
            log(f"    [BROKER] {op_type} {trade.id} failed permanently — not retrying")
            return
        if not hasattr(trade, 'pending_broker_ops'):
            trade.pending_broker_ops = []

        # Deduplicate: update existing op of same type instead of appending
        for existing_op in trade.pending_broker_ops:
            if existing_op['op'] == op_type:
                existing_op.update(kwargs)
                log(f"    [BROKER] Updated pending {op_type} for {trade.id}")
                return

        op = {'op': op_type, **kwargs}
        trade.pending_broker_ops.append(op)
        log(f"    [BROKER] Queued {op_type} for retry: {trade.id}")
        notify_status(f"[BROKER] {op_type} failed for {trade.id} — queued for retry")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print("\nShutdown signal received...")
        self.stop()

    def start(self):
        """Start the live trading loop."""
        self.running = True
        print("=" * 70)
        print(f"{STRATEGY_VERSION} LIVE TRADER - Combined Futures + Equities")
        print("=" * 70)
        print(f"Mode: {'PAPER' if self.paper_mode else 'LIVE'}")
        if self.executor:
            executor_name = type(self.executor).__name__
            print(f"Executor: {executor_name} ({self.executor.get_account_count()} account(s))")
        else:
            print("Executor: OFF (paper only)")
        if self.futures_symbols:
            print(f"Futures: {', '.join(self.futures_symbols)} (2-tick buffer)")
        if self.equity_symbols:
            print(f"Equities: {', '.join(self.equity_symbols)} (${self.equity_risk}/trade, ATR buffer)")
        print(f"Scan: bar-aligned (3m close + 5s buffer)")
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
        notify_status(f"{STRATEGY_VERSION} {mode} Trading started\nSymbols: {', '.join(self.symbols)}")

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

        # Broker: close all open paper trades at EOD
        if self.executor and self.paper_trades:
            log(f"  [BROKER] EOD: closing {len(self.paper_trades)} open trade(s)")
            for trade_id, trade in self.paper_trades.items():
                if trade.status == PaperTradeStatus.OPEN and trade.asset_type == 'futures':
                    try:
                        self.executor.close_position(
                            symbol=trade.symbol, direction=trade.direction,
                            paper_trade_id=trade.id,
                        )
                    except Exception as e:
                        log(f"    [BROKER] EOD close {trade.id} failed: {e}")

        # Safety net: flatten all broker positions and verify
        if self.executor and hasattr(self.executor, 'close_all'):
            import time
            time.sleep(2)
            try:
                self.executor.close_all()
                time.sleep(3)
            except Exception as e:
                log(f"    [BROKER] EOD flatten_all failed: {e}")

            # Verify positions are flat
            if hasattr(self.executor, 'client'):
                try:
                    remaining = [p for p in self.executor.client.get_positions() if p.net_pos != 0]
                    if remaining:
                        log(f"  [EOD] WARNING: {len(remaining)} position(s) still open after close!")
                        for p in remaining:
                            log(f"    contract_id={p.contract_id}, net_pos={p.net_pos}")
                        notify_status(f"[EOD WARNING] {len(remaining)} position(s) still open after close!")
                    else:
                        log("  [EOD] All broker positions verified flat")
                except Exception as e:
                    log(f"  [EOD] Position verification failed: {e}")

        if self.client:
            self.client.disconnect()

        # Calculate P/L for all open paper trades before summary
        if self.paper_mode:
            self._close_paper_trades_eod()

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

                # Check risk status (only gates new entries — open trades always managed)
                trading_allowed = self.risk_manager.is_trading_allowed()
                if not trading_allowed:
                    status = self.risk_manager.get_summary()
                    log(f"[{current_time.strftime('%H:%M:%S')}] Trading blocked: {status['blocked_reason']}")

                # Scan for new entries
                # Even if globally blocked, scan anyway — per-symbol limits may allow some symbols
                # can_enter_trade() in risk_manager gates each symbol individually
                for symbol in self.futures_symbols:
                    if not self.running:
                        break
                    try:
                        self._scan_futures_symbol(symbol)
                    except Exception as e:
                        log(f"  Error scanning {symbol}: {e}")

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

                # Retry any failed broker operations
                if self.executor:
                    self._retry_pending_broker_ops()

                # Print status
                try:
                    self._print_status()
                except Exception as e:
                    import traceback
                    log(f"  Error in _print_status: {e}")
                    for line in traceback.format_exc().splitlines():
                        log(f"  {line}")
                    # Debug: dump paper_trades contents
                    for tid, t in self.paper_trades.items():
                        log(f"  paper_trades[{tid}] = {type(t).__name__}: {t!r}")

                # Periodic broker health check (every 15 min)
                self._check_broker_health()

                self._sleep_until_next_bar_close()

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

    def _sleep_until_next_bar_close(self):
        """Sleep until the next 3-minute bar close + 5s buffer.

        Aligns scans to bar boundaries so the bot always processes
        finalized OHLC data, matching backtest behavior.
        """
        now = datetime.now()
        total_seconds = now.minute * 60 + now.second
        seconds_into_bar = total_seconds % 180
        sleep_seconds = 180 - seconds_into_bar + 5  # 5s after bar close
        if sleep_seconds < 10:
            sleep_seconds += 180  # Don't scan too quickly if we're right at boundary
        self._interruptible_sleep(sleep_seconds)

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

        # Fetch bars with local history merge for instant indicator warmup
        bars = load_bars_with_history(symbol, interval='3m', n_bars=500)
        if not bars:
            log(f"  No data for {symbol}")
            return

        # Get today's session bars
        today = get_est_now().date()
        today_bars = [b for b in bars if b.timestamp.date() == today]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 1:
            log(f"  No session bars yet for {symbol}")
            return

        current_price = session_bars[-1].close
        self.last_prices[symbol] = current_price
        log(f"  {symbol}: {current_price:.2f} ({len(session_bars)} session bars, {len(bars)} total)")

        # Cache bars and FVGs for opposing FVG exit in _manage_paper_trades
        self._cached_all_bars[symbol] = bars
        if config.get('opp_fvg_exit'):
            fvg_config = {'min_fvg_ticks': 2, 'tick_size': config['tick_size'],
                          'max_fvg_age_bars': 200, 'invalidate_on_close_through': True, 'fvg_mode': 'wick'}
            fvgs = detect_fvgs(bars, fvg_config)
            for fvg in fvgs:
                if not fvg.mitigated:
                    for bar_idx in range(fvg.created_bar_index + 1, len(bars)):
                        update_fvg_mitigation(fvg, bars[bar_idx], bar_idx, fvg_config)
                        if fvg.mitigated:
                            break
            self._cached_fvgs[symbol] = fvgs
            self._cached_fvgs_time[symbol] = get_est_now()

        # V10.10: ES BOS disabled (20% WR), NQ BOS enabled with loss limit
        disable_bos = symbol in ['ES', 'MES']

        # Run V10.15 strategy to get signals (all params explicit for backtest parity)
        results = run_session_v10(
            session_bars,
            bars,
            tick_size=config['tick_size'],
            tick_value=config['tick_value'],
            contracts=config['contracts'],
            max_open_trades=3,
            min_risk_pts=config['min_risk'],
            enable_creation_entry=True,
            enable_retracement_entry=True,
            enable_bos_entry=True,
            retracement_morning_only=False,  # Backtest parity: allow overnight retrace all day
            overnight_retrace_min_adx=22,
            t1_fixed_4r=True,
            midday_cutoff=True,
            pm_cutoff_nq=True,
            max_bos_risk_pts=config['max_bos_risk'],
            max_retrace_risk_pts=config['max_retrace_risk'],  # V10.11: Reduce retrace cts if high risk
            symbol=symbol,
            high_displacement_override=3.0,
            # V10.10 BOS controls
            disable_bos_retrace=disable_bos,  # ES/MES: off, NQ/MNQ: on
            bos_daily_loss_limit=1,  # Stop BOS after 1 loss per day
            # V10.9 R-targets (explicit)
            t1_r_target=3,
            trail_r_trigger=6,
            consol_threshold=0.0,  # V10.12: Disabled until A/B validated
            max_consec_losses=0,  # Per-symbol consec losses handled by risk_manager
            # Opposing FVG exit
            opposing_fvg_exit=config.get('opp_fvg_exit', False),
            opposing_fvg_min_ticks=config.get('opp_fvg_min_ticks', 5),
            opposing_fvg_after_6r_only=config.get('opp_fvg_after_6r', False),
        )

        # Process signals
        self._process_futures_signals(symbol, results, config)

    def _scan_equity_symbol(self, symbol: str):
        """Scan an equity symbol for trading signals."""
        config = self.EQUITY_SYMBOLS.get(symbol)
        if not config:
            return

        log(f"\n[{get_est_now().strftime('%H:%M:%S')}] Scanning {symbol} (equity)...")

        # Fetch bars with local history merge for instant indicator warmup
        bars = load_bars_with_history(symbol, interval='3m', n_bars=500)
        if not bars:
            log(f"  No data for {symbol}")
            return

        # Get today's session bars
        today = get_est_now().date()
        today_bars = [b for b in bars if b.timestamp.date() == today]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 1:
            log(f"  No session bars yet for {symbol}")
            return

        current_price = session_bars[-1].close
        self.last_prices[symbol] = current_price
        log(f"  {symbol}: ${current_price:.2f} ({len(session_bars)} session bars, {len(bars)} total)")

        # V10.10: SPY BOS disabled, QQQ BOS enabled with loss limit
        disable_bos = symbol == 'SPY'

        # Run V10.15 equity strategy
        results = run_session_v10_equity(
            session_bars,
            bars,
            symbol=symbol,
            risk_per_trade=config['risk_per_trade'],
            max_open_trades=3,
            t1_fixed_4r=True,
            overnight_retrace_min_adx=22,
            midday_cutoff=True,
            pm_cutoff_qqq=True,
            disable_intraday_spy=True,
            # V10.10 BOS controls
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

        # Create managed trade with pre-calculated targets from strategy
        trade = self.order_manager.create_trade_from_signal(
            symbol=config['tradovate_symbol'],
            direction=result['direction'],
            entry_type=result['entry_type'],
            entry_price=result['entry_price'],
            stop_price=result['stop_price'],
            contracts=result.get('contracts', config['contracts']),
            target_4r=result.get('target_4r'),
            target_8r=result.get('target_8r'),
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
        """Create a simulated paper trade with V10.9 parity."""
        self.paper_trade_counter += 1
        trade_id = f"PAPER_{symbol}_{self.paper_trade_counter}"

        entry_price = result['entry_price']
        stop_price = result['stop_price']

        # Use pre-calculated targets from strategy (V10.9: 3R/6R)
        target_4r = result['target_4r']
        target_8r = result['target_8r']
        plus_4r = result.get('plus_4r', target_4r)

        # Get contracts/shares with dynamic sizing
        if asset_type == 'futures':
            # V10.7: Use strategy's dynamic sizing (3 for 1st, 2 for 2nd+)
            contracts = result.get('contracts', config['contracts'])
            tick_size = config['tick_size']
            tick_value = config['tick_value']
        else:
            contracts = result.get('total_shares', 100)
            tick_size = 0.01
            tick_value = 1.0

        # V10.7: 2-ct trades have no runner (T1 + T2 only)
        has_runner = contracts >= 3

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
            plus_4r=plus_4r,
            has_runner=has_runner,
            contracts=contracts,
            tick_size=tick_size,
            tick_value=tick_value,
            asset_type=asset_type,
            entry_time=get_est_now(),
            # Initialize last_swing at entry price (matches backtest)
            t1_last_swing=entry_price,
            t2_last_swing=entry_price,
            runner_last_swing=entry_price,
        )

        # Broker-first gating: if executor is configured, broker must succeed
        # before we create the paper trade. Prevents paper/broker divergence.
        if self.executor and asset_type == 'futures':
            try:
                result_dict = self.executor.open_position(
                    symbol=symbol,
                    direction=result['direction'],
                    contracts=contracts,
                    stop_price=stop_price,
                    entry_price=entry_price,
                    paper_trade_id=trade_id,
                )
                if result_dict and not result_dict.get('success'):
                    error = result_dict.get('error', 'unknown')
                    log(f"    [BROKER] Entry REJECTED — skipping paper trade: {error}")
                    notify_status(f"[BROKER] Entry {trade_id} rejected: {error}")
                    self._broker_healthy = False
                    return
            except Exception as e:
                log(f"    [BROKER] Entry FAILED — skipping paper trade: {e}")
                notify_status(f"[BROKER] Entry {trade_id} failed: {e}")
                self._broker_healthy = False
                return

        self.paper_trades[trade_id] = paper_trade

        # Track in risk manager (paper mode parity with live execution)
        self.risk_manager.record_trade_entry(symbol, contracts)

        sizing_note = " (no runner)" if not has_runner else ""
        log(f"    [PAPER] OPENED: {result['direction']} {contracts} {symbol}{sizing_note}")
        log(f"    Entry: {entry_price:.2f} | Stop: {stop_price:.2f} | T1: {target_4r:.2f} | Trail: {target_8r:.2f}")
        log(f"    Trade ID: {trade_id}")

    def _manage_paper_trades(self):
        """Manage open paper trades - matches backtest exit logic exactly.

        Two-stage trail system (V10.9 parity):
        1. Before T1 (3R): full stop → all contracts exit at stop
        2. At T1 (3R): T1 exits fixed profit, t1_trail_stop set at entry
        3. Between T1 and 6R: t1_trail_stop structure-trails (2-tick buffer)
           - If hit, ALL remaining contracts exit (breakeven floor)
        4. At 6R touch: T2/runner trails activate at plus_4r (3R floor)
        5. After 6R: T2 trail (4-tick), runner trail (6-tick) independently
        """
        closed_trades = []

        for trade_id, trade in self.paper_trades.items():
            if trade.status != PaperTradeStatus.OPEN:
                continue

            # Fetch current price (20 bars for swing detection context)
            bars = fetch_futures_bars(trade.symbol, interval='3m', n_bars=20, timeout=15)
            if not bars or len(bars) < 1:
                log(f"    [WARNING] No bars for {trade.symbol} ({trade.id}) — trade unmanaged this cycle")
                continue

            current_high = bars[-1].high
            current_low = bars[-1].low

            # Contract split (matches backtest: 1 T1, 1 T2, remainder runner)
            cts_t1 = 1
            cts_t2 = 1
            cts_runner = max(0, trade.contracts - cts_t1 - cts_t2)

            # === STRUCTURE TRAIL UPDATES (before exit checks) ===

            # T1 trail: update between 3R and 6R (2-tick buffer)
            # Match backtest: check single bar at i-2 with last_swing gate
            if trade.t1_hit and not trade.touched_8r and len(bars) >= 5:
                old_t1_trail = trade.t1_trail_stop
                check_idx = len(bars) - 3  # Equivalent to backtest's i-2
                if trade.is_long:
                    if is_swing_low(bars, check_idx, 2):
                        swing = bars[check_idx].low
                        if swing > trade.t1_last_swing:
                            new_trail = swing - (2 * trade.tick_size)
                            if new_trail > trade.t1_trail_stop:
                                trade.t1_trail_stop = new_trail
                                trade.t1_last_swing = swing
                else:
                    if is_swing_high(bars, check_idx, 2):
                        swing = bars[check_idx].high
                        if swing < trade.t1_last_swing:
                            new_trail = swing + (2 * trade.tick_size)
                            if new_trail < trade.t1_trail_stop:
                                trade.t1_trail_stop = new_trail
                                trade.t1_last_swing = swing
                # Broker: update stop to new t1 trail
                if self.executor and trade.asset_type == 'futures' and trade.t1_trail_stop != old_t1_trail:
                    try:
                        r = self.executor.update_stop(
                            symbol=trade.symbol, direction=trade.direction,
                            new_stop_price=trade.t1_trail_stop, entry_price=trade.entry_price,
                            paper_trade_id=trade.id,
                        )
                        if not (r and r.get('success')):
                            self._queue_broker_op(trade, 'update_stop', result=r, stop_price=trade.t1_trail_stop)
                    except Exception as e:
                        log(f"    [BROKER] T1 trail update failed: {e}")
                        self._queue_broker_op(trade, 'update_stop', stop_price=trade.t1_trail_stop)

            # T2 trail: update after 6R touch (4-tick buffer)
            # Match backtest: check single bar at i-2 with last_swing gate
            if trade.touched_8r and not trade.t2_hit and len(bars) >= 5:
                old_t2_trail = trade.t2_trail_stop
                check_idx = len(bars) - 3  # Equivalent to backtest's i-2
                if trade.is_long:
                    if is_swing_low(bars, check_idx, 2):
                        swing = bars[check_idx].low
                        if swing > trade.t2_last_swing:
                            new_trail = swing - (4 * trade.tick_size)
                            if new_trail > trade.t2_trail_stop:
                                trade.t2_trail_stop = new_trail
                                trade.t2_last_swing = swing
                else:
                    if is_swing_high(bars, check_idx, 2):
                        swing = bars[check_idx].high
                        if swing < trade.t2_last_swing:
                            new_trail = swing + (4 * trade.tick_size)
                            if new_trail < trade.t2_trail_stop:
                                trade.t2_trail_stop = new_trail
                                trade.t2_last_swing = swing
                # Broker: set stop to tighter T2 trail (covers T2+Runner)
                if self.executor and trade.asset_type == 'futures' and trade.t2_trail_stop != old_t2_trail:
                    try:
                        r = self.executor.update_stop(
                            symbol=trade.symbol, direction=trade.direction,
                            new_stop_price=trade.t2_trail_stop, entry_price=trade.entry_price,
                            paper_trade_id=trade.id,
                        )
                        if not (r and r.get('success')):
                            self._queue_broker_op(trade, 'update_stop', result=r, stop_price=trade.t2_trail_stop)
                    except Exception as e:
                        log(f"    [BROKER] T2 trail update failed: {e}")
                        self._queue_broker_op(trade, 'update_stop', stop_price=trade.t2_trail_stop)

            # Runner trail: update after 6R touch AND T2 exited (6-tick buffer)
            # Match backtest: check single bar at i-2 with last_swing gate
            if trade.touched_8r and trade.t2_hit and not trade.runner_exit and trade.has_runner and len(bars) >= 5:
                old_runner_trail = trade.runner_trail_stop
                check_idx = len(bars) - 3  # Equivalent to backtest's i-2
                if trade.is_long:
                    if is_swing_low(bars, check_idx, 2):
                        swing = bars[check_idx].low
                        if swing > trade.runner_last_swing:
                            new_trail = swing - (6 * trade.tick_size)
                            if new_trail > trade.runner_trail_stop:
                                trade.runner_trail_stop = new_trail
                                trade.runner_last_swing = swing
                else:
                    if is_swing_high(bars, check_idx, 2):
                        swing = bars[check_idx].high
                        if swing < trade.runner_last_swing:
                            new_trail = swing + (6 * trade.tick_size)
                            if new_trail < trade.runner_trail_stop:
                                trade.runner_trail_stop = new_trail
                                trade.runner_last_swing = swing
                # Broker: update stop to runner trail (only runner remains)
                if self.executor and trade.asset_type == 'futures' and trade.runner_trail_stop != old_runner_trail:
                    try:
                        r = self.executor.update_stop(
                            symbol=trade.symbol, direction=trade.direction,
                            new_stop_price=trade.runner_trail_stop,
                            entry_price=trade.entry_price,
                            paper_trade_id=trade.id,
                        )
                        if not (r and r.get('success')):
                            self._queue_broker_op(trade, 'update_stop', result=r, stop_price=trade.runner_trail_stop)
                    except Exception as e:
                        log(f"    [BROKER] Runner trail update failed: {e}")
                        self._queue_broker_op(trade, 'update_stop', stop_price=trade.runner_trail_stop)

            # === CHECK 3R TOUCH (T1 exit) ===
            if not trade.t1_hit:
                t1_hit = (current_high >= trade.target_4r) if trade.is_long else (current_low <= trade.target_4r)
                if t1_hit:
                    trade.t1_hit = True
                    trade.trail_active = True
                    trade.t1_pnl = trade.calculate_pnl(trade.target_4r, cts_t1)
                    # Set t1_trail_stop at entry (breakeven floor for remaining cts)
                    trade.t1_trail_stop = trade.entry_price
                    trade.t1_last_swing = trade.entry_price
                    log(f"\n  [PAPER] T1 HIT: {trade.symbol} +${trade.t1_pnl:,.2f} (3R)")
                    log(f"    Breakeven trail active for {trade.contracts - cts_t1} remaining cts")

                    # Broker: partial close T1 (1ct) + move stop to breakeven
                    if self.executor and trade.asset_type == 'futures':
                        try:
                            r = self.executor.partial_close(
                                symbol=trade.symbol, direction=trade.direction,
                                contracts=cts_t1, paper_trade_id=trade.id,
                            )
                            if not (r and r.get('success')):
                                self._queue_broker_op(trade, 'partial_close', result=r, contracts=cts_t1)
                        except Exception as e:
                            log(f"    [BROKER] T1 partial close failed: {e}")
                            self._queue_broker_op(trade, 'partial_close', contracts=cts_t1)
                        try:
                            r = self.executor.update_stop(
                                symbol=trade.symbol, direction=trade.direction,
                                new_stop_price=trade.entry_price, entry_price=trade.entry_price,
                                paper_trade_id=trade.id,
                            )
                            if not (r and r.get('success')):
                                self._queue_broker_op(trade, 'update_stop', result=r, stop_price=trade.entry_price)
                        except Exception as e:
                            log(f"    [BROKER] T1 stop update failed: {e}")
                            self._queue_broker_op(trade, 'update_stop', stop_price=trade.entry_price)

            # === CHECK 6R TOUCH (activates T2/runner trails) ===
            if trade.t1_hit and not trade.touched_8r:
                t8r_hit = (current_high >= trade.target_8r) if trade.is_long else (current_low <= trade.target_8r)
                if t8r_hit:
                    trade.touched_8r = True
                    # Set T2 and runner floors at plus_4r (3R guaranteed profit)
                    trade.t2_trail_stop = trade.plus_4r
                    trade.runner_trail_stop = trade.plus_4r
                    # Initialize last_swing at current bar high/low (matches backtest)
                    trade.t2_last_swing = current_high if trade.is_long else current_low
                    trade.runner_last_swing = current_high if trade.is_long else current_low
                    log(f"\n  [PAPER] 6R TOUCHED: {trade.symbol} - T2/Runner trails at 3R floor")

                    # Broker: move stop to 3R floor
                    if self.executor and trade.asset_type == 'futures':
                        try:
                            r = self.executor.update_stop(
                                symbol=trade.symbol, direction=trade.direction,
                                new_stop_price=trade.plus_4r, entry_price=trade.entry_price,
                                paper_trade_id=trade.id,
                            )
                            if not (r and r.get('success')):
                                self._queue_broker_op(trade, 'update_stop', result=r, stop_price=trade.plus_4r)
                        except Exception as e:
                            log(f"    [BROKER] 6R stop update failed: {e}")
                            self._queue_broker_op(trade, 'update_stop', stop_price=trade.plus_4r)

            # === STOP CHECKS ===

            # Before T1: full stop
            if not trade.t1_hit:
                stop_hit = (current_low <= trade.stop_price) if trade.is_long else (current_high >= trade.stop_price)
                if stop_hit:
                    trade.exit_price = trade.stop_price
                    trade.exit_reason = "STOP"
                    trade.t1_pnl = trade.calculate_pnl(trade.stop_price, cts_t1)
                    trade.t2_pnl = trade.calculate_pnl(trade.stop_price, cts_t2)
                    trade.runner_pnl = trade.calculate_pnl(trade.stop_price, cts_runner) if trade.has_runner else 0.0
                    trade.status = PaperTradeStatus.CLOSED
                    trade.exit_time = get_est_now()

                    self.paper_daily_pnl += trade.total_pnl
                    self.paper_daily_trades += 1
                    self.paper_daily_losses += 1

                    log(f"\n  [PAPER] STOPPED: {trade.symbol} {trade.direction}")
                    log(f"    P/L: ${trade.total_pnl:+,.2f} (full stop, {trade.contracts} cts)")

                    notify_exit(
                        symbol=trade.symbol, direction=trade.direction,
                        exit_type="STOP", exit_price=trade.stop_price,
                        pnl=trade.total_pnl, contracts=trade.contracts,
                    )

                    # Broker: close all remaining (stop may have fired already)
                    if self.executor and trade.asset_type == 'futures':
                        try:
                            r = self.executor.close_position(
                                symbol=trade.symbol, direction=trade.direction,
                                paper_trade_id=trade.id,
                            )
                            if not (r and r.get('success')):
                                self._queue_broker_op(trade, 'close', result=r)
                        except Exception as e:
                            log(f"    [BROKER] Stop close failed: {e}")
                            self._queue_broker_op(trade, 'close')

                    closed_trades.append(trade_id)
                    continue

            # Between T1 and 6R: t1_trail_stop covers ALL remaining
            if trade.t1_hit and not trade.touched_8r:
                trail_hit = (current_low <= trade.t1_trail_stop) if trade.is_long else (current_high >= trade.t1_trail_stop)
                if trail_hit:
                    # All remaining contracts exit at t1_trail_stop
                    trade.t2_pnl = trade.calculate_pnl(trade.t1_trail_stop, cts_t2)
                    trade.t2_hit = True
                    if trade.has_runner and cts_runner > 0:
                        trade.runner_pnl = trade.calculate_pnl(trade.t1_trail_stop, cts_runner)
                        trade.runner_exit = True
                    trade.status = PaperTradeStatus.CLOSED
                    trade.exit_time = get_est_now()
                    trade.exit_price = trade.t1_trail_stop
                    trade.exit_reason = "TRAIL_STOP"

                    self.paper_daily_pnl += trade.total_pnl
                    self.paper_daily_trades += 1
                    if trade.total_pnl > 0:
                        self.paper_daily_wins += 1
                    else:
                        self.paper_daily_losses += 1

                    log(f"\n  [PAPER] TRAIL STOP: {trade.symbol} {trade.direction} (before 6R)")
                    log(f"    T1: ${trade.t1_pnl:+,.2f} | T2: ${trade.t2_pnl:+,.2f}" +
                        (f" | Runner: ${trade.runner_pnl:+,.2f}" if trade.has_runner else ""))
                    log(f"    Total P/L: ${trade.total_pnl:+,.2f}")

                    notify_exit(
                        symbol=trade.symbol, direction=trade.direction,
                        exit_type="TRAIL_STOP", exit_price=trade.t1_trail_stop,
                        pnl=trade.total_pnl, contracts=trade.contracts,
                    )

                    # Broker: close remaining (T2+Runner exiting together)
                    if self.executor and trade.asset_type == 'futures':
                        try:
                            r = self.executor.close_position(
                                symbol=trade.symbol, direction=trade.direction,
                                paper_trade_id=trade.id,
                            )
                            if not (r and r.get('success')):
                                self._queue_broker_op(trade, 'close', result=r)
                        except Exception as e:
                            log(f"    [BROKER] Trail stop close failed: {e}")
                            self._queue_broker_op(trade, 'close')

                    closed_trades.append(trade_id)
                    continue

            # After 6R: T2 trail stop
            if trade.touched_8r and not trade.t2_hit:
                t2_stopped = (current_low <= trade.t2_trail_stop) if trade.is_long else (current_high >= trade.t2_trail_stop)
                if t2_stopped:
                    trade.t2_hit = True
                    trade.t2_pnl = trade.calculate_pnl(trade.t2_trail_stop, cts_t2)
                    log(f"\n  [PAPER] T2 TRAIL: {trade.symbol} ${trade.t2_pnl:+,.2f}")

                    # For 2-ct trades (no runner), trade is done
                    if not trade.has_runner:
                        trade.status = PaperTradeStatus.CLOSED
                        trade.exit_time = get_est_now()
                        trade.exit_price = trade.t2_trail_stop
                        trade.exit_reason = "T2_TRAIL"

                        self.paper_daily_pnl += trade.total_pnl
                        self.paper_daily_trades += 1
                        self.paper_daily_wins += 1

                        log(f"    CLOSED (2-ct): T1: ${trade.t1_pnl:+,.2f} | T2: ${trade.t2_pnl:+,.2f}")
                        log(f"    Total P/L: ${trade.total_pnl:+,.2f}")

                        notify_exit(
                            symbol=trade.symbol, direction=trade.direction,
                            exit_type="T2_TRAIL", exit_price=trade.t2_trail_stop,
                            pnl=trade.total_pnl, contracts=trade.contracts,
                        )

                        # Broker: close remaining (2-ct, no runner)
                        if self.executor and trade.asset_type == 'futures':
                            try:
                                r = self.executor.close_position(
                                    symbol=trade.symbol, direction=trade.direction,
                                    paper_trade_id=trade.id,
                                )
                                if not (r and r.get('success')):
                                    self._queue_broker_op(trade, 'close', result=r)
                            except Exception as e:
                                log(f"    [BROKER] T2 close failed: {e}")
                                self._queue_broker_op(trade, 'close')

                        closed_trades.append(trade_id)
                        continue

                    # 3-ct trade: T2 exits, runner continues
                    # Broker: partial close T2 (1ct) + move stop to runner trail
                    if self.executor and trade.asset_type == 'futures':
                        try:
                            r = self.executor.partial_close(
                                symbol=trade.symbol, direction=trade.direction,
                                contracts=cts_t2, paper_trade_id=trade.id,
                            )
                            if not (r and r.get('success')):
                                self._queue_broker_op(trade, 'partial_close', result=r, contracts=cts_t2)
                        except Exception as e:
                            log(f"    [BROKER] T2 partial close failed: {e}")
                            self._queue_broker_op(trade, 'partial_close', contracts=cts_t2)
                        try:
                            r = self.executor.update_stop(
                                symbol=trade.symbol, direction=trade.direction,
                                new_stop_price=trade.runner_trail_stop,
                                entry_price=trade.entry_price,
                                paper_trade_id=trade.id,
                            )
                            if not (r and r.get('success')):
                                self._queue_broker_op(trade, 'update_stop', result=r, stop_price=trade.runner_trail_stop)
                        except Exception as e:
                            log(f"    [BROKER] T2 stop update failed: {e}")
                            self._queue_broker_op(trade, 'update_stop', stop_price=trade.runner_trail_stop)

            # After 6R: Runner trail stop (only after T2 exited)
            if trade.touched_8r and trade.t2_hit and not trade.runner_exit and trade.has_runner:
                runner_stopped = (current_low <= trade.runner_trail_stop) if trade.is_long else (current_high >= trade.runner_trail_stop)
                if runner_stopped:
                    trade.runner_exit = True
                    trade.runner_pnl = trade.calculate_pnl(trade.runner_trail_stop, cts_runner)
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
                        symbol=trade.symbol, direction=trade.direction,
                        exit_type="RUNNER_TRAIL", exit_price=trade.runner_trail_stop,
                        pnl=trade.total_pnl, contracts=trade.contracts,
                    )

                    # Broker: close runner (last contract)
                    if self.executor and trade.asset_type == 'futures':
                        try:
                            r = self.executor.close_position(
                                symbol=trade.symbol, direction=trade.direction,
                                paper_trade_id=trade.id,
                            )
                            if not (r and r.get('success')):
                                self._queue_broker_op(trade, 'close', result=r)
                        except Exception as e:
                            log(f"    [BROKER] Runner close failed: {e}")
                            self._queue_broker_op(trade, 'close')

                    closed_trades.append(trade_id)
                    continue

            # Opposing FVG exit for T2/Runner (after T1 or 6R depending on config)
            if trade.status == PaperTradeStatus.OPEN and trade.t1_hit and trade.asset_type == 'futures':
                sym_config = self.FUTURES_SYMBOLS.get(trade.symbol, {})
                if sym_config.get('opp_fvg_exit') and trade.symbol in self._cached_fvgs:
                    # Skip opposing FVG check if cache is stale (> 360s = 2 scan cycles)
                    cache_time = self._cached_fvgs_time.get(trade.symbol)
                    if cache_time and safe_datetime_diff_seconds(get_est_now(), cache_time) > 360:
                        continue
                    trigger_met = trade.touched_8r if sym_config.get('opp_fvg_after_6r') else trade.t1_hit
                    if trigger_met:
                        opposing_dir = 'BULLISH' if not trade.is_long else 'BEARISH'
                        min_size = sym_config.get('opp_fvg_min_ticks', 5) * trade.tick_size
                        all_bars = self._cached_all_bars.get(trade.symbol, [])
                        entry_time_aware = to_est_aware(trade.entry_time)

                        for fvg in self._cached_fvgs[trade.symbol]:
                            if fvg.direction != opposing_dir:
                                continue
                            if (fvg.high - fvg.low) < min_size:
                                continue
                            if fvg.created_bar_index >= len(all_bars):
                                continue
                            fvg_time = to_est_aware(all_bars[fvg.created_bar_index].timestamp)
                            if fvg_time <= entry_time_aware:
                                continue

                            # Opposing FVG found — exit all remaining contracts
                            current_close = bars[-1].close if bars else trade.entry_price
                            remaining_cts = 0
                            if not trade.t2_hit:
                                trade.t2_pnl = trade.calculate_pnl(current_close, cts_t2)
                                trade.t2_hit = True
                                remaining_cts += cts_t2
                            if trade.has_runner and not trade.runner_exit:
                                trade.runner_pnl = trade.calculate_pnl(current_close, cts_runner)
                                trade.runner_exit = True
                                remaining_cts += cts_runner

                            if remaining_cts > 0:
                                trade.status = PaperTradeStatus.CLOSED
                                trade.exit_time = get_est_now()
                                trade.exit_price = current_close
                                trade.exit_reason = "OPP_FVG"

                                self.paper_daily_pnl += trade.total_pnl
                                self.paper_daily_trades += 1
                                if trade.total_pnl > 0:
                                    self.paper_daily_wins += 1
                                else:
                                    self.paper_daily_losses += 1

                                fvg_size_ticks = (fvg.high - fvg.low) / trade.tick_size
                                log(f"\n  [PAPER] OPP FVG EXIT: {trade.symbol} {trade.direction}")
                                log(f"    Opposing {opposing_dir} FVG: {fvg_size_ticks:.0f} ticks @ {fvg_time.strftime('%H:%M')}")
                                log(f"    T1: ${trade.t1_pnl:+,.2f} | T2: ${trade.t2_pnl:+,.2f}" +
                                    (f" | Runner: ${trade.runner_pnl:+,.2f}" if trade.has_runner else ""))
                                log(f"    Total P/L: ${trade.total_pnl:+,.2f}")

                                notify_exit(
                                    symbol=trade.symbol, direction=trade.direction,
                                    exit_type="OPP_FVG", exit_price=current_close,
                                    pnl=trade.total_pnl, contracts=trade.contracts,
                                )

                                if self.executor and trade.asset_type == 'futures':
                                    try:
                                        r = self.executor.close_position(
                                            symbol=trade.symbol, direction=trade.direction,
                                            paper_trade_id=trade.id,
                                        )
                                        if not (r and r.get('success')):
                                            self._queue_broker_op(trade, 'close', result=r)
                                    except Exception as e:
                                        log(f"    [BROKER] OPP FVG close failed: {e}")
                                        self._queue_broker_op(trade, 'close')

                                closed_trades.append(trade_id)
                            break  # Only need first matching opposing FVG

        # Remove closed trades from active tracking
        for trade_id in closed_trades:
            trade = self.paper_trades[trade_id]
            self.risk_manager.record_trade_exit(
                trade.symbol, trade.contracts, trade.total_pnl,
                is_win=trade.total_pnl > 0,
            )
            self.paper_trade_history.append(self._snapshot_paper_trade(trade))
            # Preserve any pending broker ops before deleting the trade
            if hasattr(trade, 'pending_broker_ops') and trade.pending_broker_ops:
                for op in trade.pending_broker_ops:
                    op['_trade_id'] = trade.id
                    op['_symbol'] = trade.symbol
                    op['_direction'] = trade.direction
                    op['_entry_price'] = trade.entry_price
                self._orphaned_broker_ops.extend(trade.pending_broker_ops)
                log(f"    [BROKER] {len(trade.pending_broker_ops)} op(s) orphaned from {trade.id}")
            del self.paper_trades[trade_id]

    def _close_paper_trades_eod(self):
        """Calculate P/L for all open paper trades at EOD shutdown.

        Iterates all open paper trades (futures + equity), fetches current price,
        calculates per-leg P/L for remaining contracts, updates daily counters,
        records in risk manager, snapshots to history, sends Telegram exit.
        """
        if not self.paper_trades:
            return

        log(f"\n  [EOD] Closing {len(self.paper_trades)} open paper trade(s) with P/L calculation")

        for trade_id, trade in list(self.paper_trades.items()):
            if trade.status != PaperTradeStatus.OPEN:
                continue

            # Get current price: try fresh bars, fallback to last_prices, then entry_price
            current_price = None
            try:
                bars = fetch_futures_bars(trade.symbol, interval='3m', n_bars=1, timeout=10)
                if bars:
                    current_price = bars[-1].close
            except Exception:
                pass

            if current_price is None:
                current_price = self.last_prices.get(trade.symbol, trade.entry_price)

            # Contract split
            cts_t1 = 1
            cts_t2 = 1
            cts_runner = max(0, trade.contracts - cts_t1 - cts_t2)

            # Calculate P/L for remaining legs
            if not trade.t1_hit:
                trade.t1_pnl = trade.calculate_pnl(current_price, cts_t1)
            if not trade.t2_hit:
                trade.t2_pnl = trade.calculate_pnl(current_price, cts_t2)
            if trade.has_runner and not trade.runner_exit:
                trade.runner_pnl = trade.calculate_pnl(current_price, cts_runner)

            trade.status = PaperTradeStatus.CLOSED
            trade.exit_time = get_est_now()
            trade.exit_price = current_price
            trade.exit_reason = "EOD"

            # Update daily counters
            self.paper_daily_pnl += trade.total_pnl
            self.paper_daily_trades += 1
            if trade.total_pnl > 0:
                self.paper_daily_wins += 1
            else:
                self.paper_daily_losses += 1

            # Record in risk manager
            self.risk_manager.record_trade_exit(
                trade.symbol, trade.contracts, trade.total_pnl,
                is_win=trade.total_pnl > 0,
            )

            # Snapshot for divergence tracking
            self.paper_trade_history.append(self._snapshot_paper_trade(trade))

            log(f"    [EOD] {trade.symbol} {trade.direction} @ {current_price:.2f}")
            log(f"      T1: ${trade.t1_pnl:+,.2f} | T2: ${trade.t2_pnl:+,.2f}" +
                (f" | Runner: ${trade.runner_pnl:+,.2f}" if trade.has_runner else ""))
            log(f"      Total P/L: ${trade.total_pnl:+,.2f}")

            notify_exit(
                symbol=trade.symbol, direction=trade.direction,
                exit_type="EOD", exit_price=current_price,
                pnl=trade.total_pnl, contracts=trade.contracts,
            )

        # Clear all paper trades after processing
        self.paper_trades.clear()

    def _snapshot_paper_trade(self, trade: PaperTrade) -> Dict:
        """Capture a closed PaperTrade as a plain dict for divergence tracking."""
        return {
            'id': trade.id,
            'symbol': trade.symbol,
            'direction': trade.direction,
            'entry_type': trade.entry_type,
            'entry_price': trade.entry_price,
            'stop_price': trade.stop_price,
            'exit_price': trade.exit_price,
            'exit_reason': trade.exit_reason,
            'contracts': trade.contracts,
            'has_runner': trade.has_runner,
            'entry_time': trade.entry_time.isoformat() if trade.entry_time else None,
            'exit_time': trade.exit_time.isoformat() if trade.exit_time else None,
            'risk_pts': trade.risk_pts,
            't1_pnl': trade.t1_pnl,
            't2_pnl': trade.t2_pnl,
            'runner_pnl': trade.runner_pnl,
            'total_pnl': trade.total_pnl,
            'tick_size': trade.tick_size,
            'tick_value': trade.tick_value,
        }

    def _run_divergence_check(self):
        """Run live vs backtest divergence comparison at EOD."""
        today = get_est_now().date()
        reports = []

        for symbol in self.futures_symbols:
            # Filter trades for this symbol
            sym_trades = [t for t in self.paper_trade_history if t['symbol'] == symbol]
            if not sym_trades:
                continue

            sym_wins = sum(1 for t in sym_trades if t['total_pnl'] > 0)
            sym_losses = sum(1 for t in sym_trades if t['total_pnl'] < 0)
            sym_pnl = sum(t['total_pnl'] for t in sym_trades)
            summary = {
                'trades': len(sym_trades),
                'wins': sym_wins,
                'losses': sym_losses,
                'pnl': sym_pnl,
            }

            # Save live trades to JSON
            save_live_trades(symbol, today, sym_trades, summary)
            log(f"  [DIVERGENCE] Saved {len(sym_trades)} {symbol} trades to JSON")

            # Run comparison
            report = compare_day(symbol, today, live_trades=sym_trades)
            reports.append(report)

        if not reports:
            log("  [DIVERGENCE] No futures trades to compare")
            return

        # Print console report
        console = format_console_report(reports)
        print(console)

        # Send Telegram alert if gap exceeds threshold
        alert = format_telegram_alert(reports)
        if alert:
            try:
                from runners.notifier import notify_error
                notify_error(alert)
                log("  [DIVERGENCE] Telegram alert sent (gap exceeds threshold)")
            except Exception as e:
                log(f"  [DIVERGENCE] Telegram alert failed: {e}")

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
            open_cts = self._count_open_contracts()
            cts_str = f" ({open_cts} cts)" if open_trades > 0 else ""
            log(f"[HEARTBEAT] {timestamp} | {prices_str} | Trades: {self.paper_daily_trades} | P/L: ${self.paper_daily_pnl:+,.2f} | Open: {open_trades}{cts_str}")
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

        # Position reconciliation every 15 min (TradovateExecutor only)
        if self.executor and hasattr(self.executor, 'reconcile_positions'):
            if self.last_telegram_heartbeat is None or safe_datetime_diff_seconds(now, self.last_telegram_heartbeat) >= 900:
                try:
                    warnings = self.executor.reconcile_positions(self.paper_trades)
                    for w in warnings:
                        log(f"  {w}")
                        notify_status(w)
                except Exception as e:
                    log(f"  [RECONCILE] Error: {e}")

        if send_telegram:
            self.last_telegram_heartbeat = now
            mode = "PAPER" if self.paper_mode else "LIVE"
            if self.paper_mode:
                open_trades = len(self.paper_trades)
                open_cts = self._count_open_contracts()
                cts_str = f" ({open_cts} cts)" if open_trades > 0 else ""
                tg_msg = f"[{mode}] {timestamp} | {prices_str} | Trades: {self.paper_daily_trades} | P/L: ${self.paper_daily_pnl:+,.2f} | Open: {open_trades}{cts_str}"
            else:
                risk_summary = self.risk_manager.get_summary()
                tg_msg = f"[{mode}] {timestamp} | {prices_str} | Trades: {risk_summary['daily_trades']} | P/L: ${risk_summary['daily_pnl']:+,.2f} | Open: {risk_summary['open_trades']}"
            try:
                notify_status(tg_msg)
            except Exception:
                pass  # Don't let Telegram failures break the loop

    def _count_open_contracts(self):
        """Count total remaining contracts across all open paper trades."""
        total = 0
        for trade_id, trade in list(self.paper_trades.items()):
            try:
                if not isinstance(trade, PaperTrade):
                    log(f"  [BUG] paper_trades[{trade_id}] is {type(trade).__name__}: {trade!r}")
                    continue
                remaining = trade.contracts
                if trade.t1_hit:
                    remaining -= 1
                if trade.t2_hit:
                    remaining -= 1
                if trade.runner_exit:
                    remaining -= 1
                total += remaining
            except AttributeError as e:
                log(f"  [BUG] _count_open_contracts: {e} | trade_id={trade_id} type={type(trade).__name__} repr={trade!r}")
        return total

    def _calculate_next_day_outlook(self):
        """Calculate and send next-day outlook for each symbol.

        Fetches daily bars, computes CPR, standard pivots, ATR, and
        sends a Telegram alert per symbol.
        """
        from datetime import timedelta

        now = get_est_now()
        # Next trading day (skip weekends)
        next_day = now + timedelta(days=1)
        while next_day.weekday() >= 5:  # 5=Sat, 6=Sun
            next_day += timedelta(days=1)
        next_date_str = next_day.strftime('%b %d, %Y')

        # CPR narrow thresholds per symbol family
        narrow_thresholds = {
            'ES': 5.0, 'MES': 5.0, 'SPY': 1.0,
            'NQ': 15.0, 'MNQ': 15.0, 'QQQ': 3.0,
        }

        # Only ES outlook for now (NQ to be enabled later)
        outlook_symbols = [s for s in self.symbols if s in ('ES', 'MES')]
        if not outlook_symbols:
            return

        for symbol in outlook_symbols[:1]:  # One alert (ES or MES, not both)
            try:
                # Fetch last 15 daily bars
                daily_bars = fetch_futures_bars(symbol, interval='1d', n_bars=15, timeout=30)
                if not daily_bars or len(daily_bars) < 2:
                    log(f"  [OUTLOOK] Not enough daily data for {symbol}")
                    continue

                # Today = last bar (use today's H/L/C for tomorrow's CPR)
                today_bar = daily_bars[-1]

                # CPR for next day uses today's H/L/C
                pivot = (today_bar.high + today_bar.low + today_bar.close) / 3
                bc = (today_bar.high + today_bar.low) / 2
                tc = (2 * pivot) - bc
                cpr_width = abs(tc - bc)

                # R1/S1 for next day
                r1 = (2 * pivot) - today_bar.low
                s1 = (2 * pivot) - today_bar.high

                # ATR (5-day) and prior day range
                ranges = [b.high - b.low for b in daily_bars]
                atr_5d = sum(ranges[-5:]) / min(5, len(ranges[-5:])) if len(ranges) >= 1 else 0
                prior_range = today_bar.high - today_bar.low
                prior_range_pct = (prior_range / atr_5d * 100) if atr_5d > 0 else 0

                # Narrow CPR check
                threshold = narrow_thresholds.get(symbol, 5.0)
                is_narrow = cpr_width < threshold

                # CPR context
                if is_narrow:
                    if prior_range_pct < 80:
                        cpr_context = f"NARROW -- coiling ({prior_range_pct:.0f}% ATR prior day)"
                    else:
                        cpr_context = f"NARROW -- prior day expanded ({prior_range_pct:.0f}% ATR)"
                else:
                    cpr_context = "WIDE -- expect range/chop"

                # Bias signals
                bearish_bias = today_bar.close < pivot
                bullish_bias = today_bar.close > pivot

                # Close position
                close_pct = (today_bar.close - today_bar.low) / prior_range * 100 if prior_range > 0 else 50
                weak_close = close_pct < 25
                strong_close = close_pct >= 75

                # Volume vs 5-day average
                volumes = [b.volume for b in daily_bars if b.volume > 0]
                if len(volumes) >= 5:
                    avg_vol = sum(volumes[-5:]) / 5
                    today_vol = today_bar.volume
                    vol_ratio = today_vol / avg_vol if avg_vol > 0 else 1.0
                    if vol_ratio >= 1.2:
                        volume_context = f"Vol: {today_vol/1e6:.1f}M (above avg -- confirms move)"
                    elif vol_ratio <= 0.8:
                        volume_context = f"Vol: {today_vol/1e6:.1f}M (below avg -- weak conviction)"
                    else:
                        volume_context = f"Vol: {today_vol/1e6:.1f}M (avg)"
                    high_volume = vol_ratio >= 1.2
                else:
                    volume_context = "Vol: n/a"
                    high_volume = False

                # Conviction summary
                if bearish_bias:
                    signals = []
                    if weak_close:
                        signals.append("weak close")
                    if is_narrow:
                        signals.append("narrow CPR")
                    if high_volume:
                        signals.append("high volume")
                    if len(signals) >= 2:
                        conviction = f"HIGH CONVICTION BEARISH -- {' + '.join(signals)}"
                    elif signals:
                        conviction = f"LEAN BEARISH -- bias + {signals[0]}"
                    elif strong_close:
                        conviction = "MIXED -- bearish bias vs strong close"
                    else:
                        conviction = "LEAN BEARISH -- bias bearish"
                elif bullish_bias:
                    signals = []
                    if strong_close:
                        signals.append("strong close")
                    if is_narrow:
                        signals.append("narrow CPR")
                    if high_volume:
                        signals.append("high volume")
                    if len(signals) >= 2:
                        conviction = f"HIGH CONVICTION BULLISH -- {' + '.join(signals)}"
                    elif signals:
                        conviction = f"LEAN BULLISH -- bias + {signals[0]}"
                    elif weak_close:
                        conviction = "MIXED -- bullish bias vs weak close"
                    else:
                        conviction = "LEAN BULLISH -- bias bullish"
                else:
                    conviction = "NEUTRAL -- close at pivot, wait for direction"

                log(f"\n  [OUTLOOK] {symbol}: Pivot={pivot:.2f} CPR={cpr_width:.2f} ATR={atr_5d:.1f}")

                notify_next_day_outlook(
                    symbol=symbol,
                    conviction=conviction,
                    volume_context=volume_context,
                    pivot=pivot, tc=tc, bc=bc, cpr_width=cpr_width,
                    cpr_context=cpr_context,
                    r1=r1, s1=s1,
                    atr_5d=atr_5d,
                    prior_range=prior_range,
                    prior_range_pct=prior_range_pct,
                    today_high=today_bar.high,
                    today_low=today_bar.low,
                    today_close=today_bar.close,
                    next_date=next_date_str,
                )

            except Exception as e:
                log(f"  [OUTLOOK] Error for {symbol}: {e}")

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

        # Send next-day outlook after daily summary
        try:
            self._calculate_next_day_outlook()
        except Exception as e:
            log(f"  [OUTLOOK] Error calculating outlook: {e}")

        # Save today's bars to local storage for deeper backtests
        valid_futures = ['ES', 'NQ', 'MES', 'MNQ']
        for sym in self.symbols:
            if sym in valid_futures:
                try:
                    bars = fetch_futures_bars(sym, interval='3m', n_bars=500, timeout=30)
                    created = save_daily_bars(sym, bars)
                    if created:
                        log(f"  [BARS] Saved {len(created)} CSV(s) for {sym}")
                except Exception as e:
                    log(f"  [BARS] Error saving {sym} bars: {e}")

        # Run divergence check (live vs backtest comparison)
        if self.paper_mode and self.futures_symbols:
            try:
                self._run_divergence_check()
            except Exception as e:
                log(f"  [DIVERGENCE] Error running divergence check: {e}")

        print("=" * 70)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description=f'{STRATEGY_VERSION} Live Trading - Futures + Equities')
    parser.add_argument('--live', action='store_true', help='Enable live trading (default: demo)')
    parser.add_argument('--paper', action='store_true', help='Paper trading mode (signals only)')
    parser.add_argument('--symbols', nargs='+', default=['ES', 'MES'],
                       help='Symbols to trade (ES, NQ, MES, MNQ, SPY, QQQ)')
    parser.add_argument('--equity-risk', type=int, default=500,
                       help='Risk per trade for equities in dollars (default: 500)')
    parser.add_argument('--webhook', action='store_true',
                       help='Enable PickMyTrade webhook execution')
    parser.add_argument('--strategy-group', default='ict_v10',
                       help='PickMyTrade strategy group (default: ict_v10)')
    parser.add_argument('--webhook-config', default='config/pickmytrade_accounts.json',
                       help='Path to PickMyTrade config (default: config/pickmytrade_accounts.json)')
    parser.add_argument('--direct-api', action='store_true',
                       help='Enable Tradovate direct API execution (personal accounts)')
    parser.add_argument('--direct-api-config', default='config/tradovate_direct.json',
                       help='Path to Tradovate direct API config (default: config/tradovate_direct.json)')
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

    print(f"Starting {STRATEGY_VERSION} Live Trader...")
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

    # Create executor(s) based on CLI flags
    executors = []

    if args.direct_api:
        try:
            from runners.tradovate_executor import TradovateExecutor
            direct_executor = TradovateExecutor(args.direct_api_config)
            executors.append(direct_executor)
            print(f"Direct API: ACTIVE (env={direct_executor.environment}, account={direct_executor.client.account_id})")

            # Check for orphaned positions on startup
            orphan_warnings = direct_executor.check_orphaned_positions()
            for w in orphan_warnings:
                print(f"  WARNING: {w}")
        except Exception as e:
            print(f"Failed to create Tradovate executor: {e}")
            print("Continuing without direct API")

    if args.webhook:
        try:
            wh_executor = WebhookExecutor(args.webhook_config, args.strategy_group)
            executors.append(wh_executor)
            print(f"Webhook: ACTIVE ({wh_executor.get_account_count()} account(s))")
        except Exception as e:
            print(f"Failed to create webhook executor: {e}")
            print("Continuing without webhooks")

    # Combine executors
    broker_executor = None
    if len(executors) > 1:
        from runners.multi_executor import MultiExecutor
        broker_executor = MultiExecutor(executors)
        print(f"Executor: MultiExecutor ({broker_executor.get_account_count()} total account(s))")
    elif len(executors) == 1:
        broker_executor = executors[0]

    # Create trader
    trader = LiveTrader(
        client=client,
        paper_mode=paper_mode,
        symbols=args.symbols,
        equity_risk=args.equity_risk,
        executor=broker_executor,
    )

    # Start trading
    trader.start()


if __name__ == '__main__':
    main()
