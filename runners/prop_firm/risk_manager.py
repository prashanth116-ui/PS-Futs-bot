"""
Prop Firm Risk Manager — Forked from runners/risk_manager.py

Adds prop-firm-specific risk controls:
- Daily loss limit (hard stop in dollars from prop firm rules)
- Trailing drawdown (max drawdown from peak equity)
- Max total contracts (across all open positions)
- Peak equity tracking (high-water mark for trailing DD)
"""
import sys
sys.path.insert(0, '.')

from version import STRATEGY_VERSION
from runners.prop_firm.symbol_defaults import get_consec_loss_limit, FUTURES_DEFAULTS

from datetime import datetime, time as dt_time
from typing import Optional, Dict, List, Callable
from dataclasses import dataclass, field
from enum import Enum
import threading
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

# EST timezone for time-based filters
EST = ZoneInfo('America/New_York')


def get_est_time(dt: datetime = None) -> dt_time:
    """Get current time in EST timezone."""
    if dt is None:
        dt = datetime.now(EST)
    elif dt.tzinfo is None:
        return dt.time()
    else:
        dt = dt.astimezone(EST)
    return dt.time()


def get_est_date():
    """Get current date in EST timezone."""
    return datetime.now(EST).date()


class RiskStatus(Enum):
    OK = "ok"
    WARNING = "warning"
    BLOCKED = "blocked"
    KILLED = "killed"


@dataclass
class RiskLimits:
    """Risk limit configuration for prop firm accounts."""
    # Daily limits
    max_daily_loss: float = 2000.0        # Stop trading after this loss
    max_daily_trades: int = 0             # 0 = unlimited
    max_consecutive_losses: int = 0       # Global consecutive loss limit (0=disabled)

    # Position limits
    max_open_trades: int = 3              # Max simultaneous trades
    max_contracts_per_trade: int = 3      # Max contracts per single trade
    max_total_contracts: int = 5          # Prop firm: tighter than personal (6 -> 5)

    # Per-symbol limits
    max_contracts_per_symbol: int = 6     # Max contracts per symbol

    # Time filters (V10.2/V10.4)
    midday_cutoff_start: dt_time = dt_time(12, 0)
    midday_cutoff_end: dt_time = dt_time(14, 0)
    pm_cutoff_nq: dt_time = dt_time(14, 0)
    pm_cutoff_qqq: dt_time = dt_time(14, 0)
    rth_start: dt_time = dt_time(9, 30)
    rth_end: dt_time = dt_time(16, 0)

    # BOS risk caps — from centralized symbol_defaults
    max_bos_risk_es: float = FUTURES_DEFAULTS['ES']['max_bos_risk']
    max_bos_risk_nq: float = FUTURES_DEFAULTS['NQ']['max_bos_risk']

    # SPY INTRADAY filter
    disable_spy_intraday: bool = True

    # Prop firm specific
    trailing_drawdown: float = 2500.0     # Max trailing drawdown from peak ($)
    account_size: float = 50000.0         # Eval account size ($)


@dataclass
class RiskState:
    """Current risk state tracking with prop firm additions."""
    daily_pnl: float = 0.0
    daily_trades: int = 0
    consecutive_losses: int = 0
    consecutive_losses_by_symbol: Dict[str, int] = field(default_factory=dict)
    open_trades: int = 0
    open_contracts: int = 0
    contracts_by_symbol: Dict[str, int] = field(default_factory=dict)
    last_trade_result: Optional[str] = None
    kill_switch_active: bool = False
    blocked_reason: Optional[str] = None

    # Today's date for reset (EST timezone)
    current_date: datetime = field(default_factory=get_est_date)

    # Prop firm additions
    peak_equity: float = 0.0             # High-water mark for trailing DD
    current_equity: float = 0.0          # Running session P/L


class RiskManager:
    """
    Risk manager for prop firm live trading.

    Extends personal risk manager with:
    - Trailing drawdown tracking (peak equity - current equity)
    - Stricter daily loss limits from prop firm rules
    - Total contract limits across all positions
    """

    def __init__(self, limits: Optional[RiskLimits] = None):
        """Initialize risk manager with limits."""
        self.limits = limits or RiskLimits()
        self.state = RiskState()
        self._lock = threading.RLock()
        self._alert_callbacks: List[Callable] = []

    def add_alert_callback(self, callback: Callable):
        """Add callback for risk alerts."""
        self._alert_callbacks.append(callback)

    def _send_alert(self, message: str, level: str = "warning"):
        """Send alert through registered callbacks."""
        for callback in self._alert_callbacks:
            try:
                callback(message, level)
            except Exception as e:
                print(f"Alert callback error: {e}")

    def _check_daily_reset(self):
        """Reset daily counters if new day (based on EST)."""
        today = get_est_date()
        if self.state.current_date != today:
            self.state.daily_pnl = 0.0
            self.state.daily_trades = 0
            self.state.consecutive_losses = 0
            self.state.consecutive_losses_by_symbol = {}
            self.state.current_date = today
            self.state.blocked_reason = None
            # Reset session equity but preserve peak for trailing DD
            self.state.current_equity = 0.0
            self.state.peak_equity = 0.0
            print(f"Daily reset: {today}")

    def activate_kill_switch(self, reason: str = "Manual"):
        """Activate kill switch - blocks all trading."""
        with self._lock:
            self.state.kill_switch_active = True
            self.state.blocked_reason = f"KILL SWITCH: {reason}"
            self._send_alert(f"KILL SWITCH ACTIVATED: {reason}", "critical")
            print(f"KILL SWITCH ACTIVATED: {reason}")

    def deactivate_kill_switch(self):
        """Deactivate kill switch."""
        with self._lock:
            self.state.kill_switch_active = False
            self.state.blocked_reason = None
            print("Kill switch deactivated")

    def _get_symbol_consec_limit(self, symbol: str) -> int:
        """Per-symbol consecutive loss limit from centralized config."""
        return get_consec_loss_limit(symbol)

    def can_enter_trade(
        self,
        symbol: str,
        direction: str,
        entry_type: str,
        contracts: int,
        risk_pts: float,
        entry_time: Optional[datetime] = None,
    ) -> tuple[bool, str]:
        """
        Check if a new trade entry is allowed.

        Includes all personal risk checks plus prop-specific:
        - Daily loss limit (prop firm rules)
        - Trailing drawdown from peak equity
        - Total contract limit
        """
        self._check_daily_reset()
        current_time = get_est_time(entry_time)

        with self._lock:
            # Kill switch check
            if self.state.kill_switch_active:
                return False, "Kill switch active"

            # Daily loss limit
            if self.state.daily_pnl <= -self.limits.max_daily_loss:
                self.state.blocked_reason = "Daily loss limit reached"
                return False, self.state.blocked_reason

            # Trailing drawdown check (prop firm specific)
            trailing_dd = self.state.peak_equity - self.state.current_equity
            if trailing_dd >= self.limits.trailing_drawdown:
                self.state.blocked_reason = f"Trailing drawdown limit (${trailing_dd:,.0f} >= ${self.limits.trailing_drawdown:,.0f})"
                return False, self.state.blocked_reason

            # Daily trade limit (0 = unlimited)
            if self.limits.max_daily_trades > 0 and self.state.daily_trades >= self.limits.max_daily_trades:
                return False, "Max daily trades reached"

            # Global consecutive losses (0=disabled)
            if self.limits.max_consecutive_losses > 0 and self.state.consecutive_losses >= self.limits.max_consecutive_losses:
                return False, f"Max consecutive losses ({self.limits.max_consecutive_losses}) reached"

            # Per-symbol consecutive losses: ES/MES=2, NQ/MNQ=3
            symbol_consec_limit = self._get_symbol_consec_limit(symbol)
            symbol_consec = self.state.consecutive_losses_by_symbol.get(symbol, 0)
            if symbol_consec_limit > 0 and symbol_consec >= symbol_consec_limit:
                return False, f"Consecutive losses for {symbol} ({symbol_consec}/{symbol_consec_limit})"

            # Open trade limit
            if self.state.open_trades >= self.limits.max_open_trades:
                return False, f"Max open trades ({self.limits.max_open_trades}) reached"

            # Total contracts limit
            if self.state.open_contracts + contracts > self.limits.max_total_contracts:
                return False, f"Max total contracts ({self.limits.max_total_contracts}) exceeded"

            # Per-symbol limit
            symbol_contracts = self.state.contracts_by_symbol.get(symbol, 0)
            if symbol_contracts + contracts > self.limits.max_contracts_per_symbol:
                return False, f"Max contracts for {symbol} exceeded"

            # Time-based filters (V10.2)
            if self.limits.midday_cutoff_start <= current_time < self.limits.midday_cutoff_end:
                return False, "Midday cutoff (12:00-14:00)"

            # PM cutoff for NQ
            if symbol in ['NQ', 'MNQ'] and current_time >= self.limits.pm_cutoff_nq:
                return False, "NQ PM cutoff (after 14:00)"

            # PM cutoff for QQQ
            if symbol == 'QQQ' and current_time >= self.limits.pm_cutoff_qqq:
                return False, "QQQ PM cutoff (after 14:00)"

            # BOS risk cap (V10.4)
            if entry_type == 'BOS_RETRACE':
                if symbol in ['ES', 'MES'] and risk_pts > self.limits.max_bos_risk_es:
                    return False, f"BOS risk {risk_pts:.1f}pts exceeds ES cap ({self.limits.max_bos_risk_es}pts)"
                if symbol in ['NQ', 'MNQ'] and risk_pts > self.limits.max_bos_risk_nq:
                    return False, f"BOS risk {risk_pts:.1f}pts exceeds NQ cap ({self.limits.max_bos_risk_nq}pts)"

            # SPY INTRADAY filter (V10.4)
            if symbol == 'SPY' and entry_type == 'INTRADAY' and self.limits.disable_spy_intraday:
                return False, "SPY INTRADAY disabled (V10.4)"

            return True, "OK"

    def record_trade_entry(self, symbol: str, contracts: int):
        """Record a new trade entry."""
        with self._lock:
            self.state.open_trades += 1
            self.state.open_contracts += contracts
            self.state.daily_trades += 1
            self.state.contracts_by_symbol[symbol] = self.state.contracts_by_symbol.get(symbol, 0) + contracts

    def record_trade_exit(self, symbol: str, contracts: int, pnl: float, is_win: bool):
        """Record a trade exit with prop-firm equity tracking."""
        with self._lock:
            self.state.open_trades = max(0, self.state.open_trades - 1)
            self.state.open_contracts = max(0, self.state.open_contracts - contracts)
            self.state.contracts_by_symbol[symbol] = max(0, self.state.contracts_by_symbol.get(symbol, 0) - contracts)
            self.state.daily_pnl += pnl

            # Update equity tracking for trailing drawdown
            self.state.current_equity += pnl
            if self.state.current_equity > self.state.peak_equity:
                self.state.peak_equity = self.state.current_equity

            if is_win:
                self.state.consecutive_losses = 0
                self.state.consecutive_losses_by_symbol[symbol] = 0
                self.state.last_trade_result = 'win'
            else:
                self.state.consecutive_losses += 1
                self.state.consecutive_losses_by_symbol[symbol] = self.state.consecutive_losses_by_symbol.get(symbol, 0) + 1
                self.state.last_trade_result = 'loss'

                # Per-symbol consecutive loss alert
                symbol_consec = self.state.consecutive_losses_by_symbol[symbol]
                symbol_limit = self._get_symbol_consec_limit(symbol)
                if symbol_limit > 0 and symbol_consec >= symbol_limit:
                    self._send_alert(
                        f"[PROP] Consecutive loss limit for {symbol} ({symbol_consec}/{symbol_limit}) — {symbol} entries blocked",
                        "warning"
                    )

                # Global consecutive loss alert (if enabled)
                if self.limits.max_consecutive_losses > 0 and self.state.consecutive_losses >= self.limits.max_consecutive_losses:
                    self._send_alert(
                        f"[PROP] Max consecutive losses reached ({self.state.consecutive_losses})",
                        "warning"
                    )

            # Daily loss alert
            if self.state.daily_pnl <= -self.limits.max_daily_loss * 0.8:
                self._send_alert(
                    f"[PROP] Approaching daily loss limit: ${self.state.daily_pnl:,.2f}",
                    "warning"
                )

            if self.state.daily_pnl <= -self.limits.max_daily_loss:
                self._send_alert(
                    f"[PROP] DAILY LOSS LIMIT REACHED: ${self.state.daily_pnl:,.2f}",
                    "critical"
                )

            # Trailing drawdown alert (prop firm specific)
            trailing_dd = self.state.peak_equity - self.state.current_equity
            if trailing_dd >= self.limits.trailing_drawdown * 0.8:
                self._send_alert(
                    f"[PROP] Approaching trailing DD limit: ${trailing_dd:,.0f} / ${self.limits.trailing_drawdown:,.0f}",
                    "warning"
                )
            if trailing_dd >= self.limits.trailing_drawdown:
                self._send_alert(
                    f"[PROP] TRAILING DRAWDOWN LIMIT BREACHED: ${trailing_dd:,.0f}",
                    "critical"
                )

    def record_partial_exit(self, symbol: str, contracts: int, pnl: float):
        """Record a partial exit (T1, T2)."""
        with self._lock:
            self.state.open_contracts = max(0, self.state.open_contracts - contracts)
            self.state.contracts_by_symbol[symbol] = max(0, self.state.contracts_by_symbol.get(symbol, 0) - contracts)
            self.state.daily_pnl += pnl

            # Update equity tracking for trailing drawdown
            self.state.current_equity += pnl
            if self.state.current_equity > self.state.peak_equity:
                self.state.peak_equity = self.state.current_equity

    def get_status(self) -> RiskStatus:
        """Get current risk status."""
        self._check_daily_reset()

        with self._lock:
            if self.state.kill_switch_active:
                return RiskStatus.KILLED

            if self.state.daily_pnl <= -self.limits.max_daily_loss:
                self.state.blocked_reason = f"Daily loss limit (${abs(self.state.daily_pnl):.0f})"
                return RiskStatus.BLOCKED

            # Trailing drawdown check
            trailing_dd = self.state.peak_equity - self.state.current_equity
            if trailing_dd >= self.limits.trailing_drawdown:
                self.state.blocked_reason = f"Trailing DD (${trailing_dd:,.0f})"
                return RiskStatus.BLOCKED

            if self.limits.max_consecutive_losses > 0 and self.state.consecutive_losses >= self.limits.max_consecutive_losses:
                self.state.blocked_reason = f"Consecutive losses ({self.state.consecutive_losses})"
                return RiskStatus.BLOCKED

            # Check if ALL symbols with limits are blocked
            all_blocked = True
            blocked_symbols = []
            for sym, consec in self.state.consecutive_losses_by_symbol.items():
                limit = self._get_symbol_consec_limit(sym)
                if limit > 0 and consec >= limit:
                    blocked_symbols.append(sym)
                elif limit > 0:
                    all_blocked = False
            if blocked_symbols and all_blocked:
                self.state.blocked_reason = f"Consecutive losses ({', '.join(blocked_symbols)})"
                return RiskStatus.BLOCKED

            if self.state.daily_pnl <= -self.limits.max_daily_loss * 0.5:
                return RiskStatus.WARNING

            if trailing_dd >= self.limits.trailing_drawdown * 0.5:
                return RiskStatus.WARNING

            if blocked_symbols:
                return RiskStatus.WARNING

            return RiskStatus.OK

    def get_summary(self) -> Dict:
        """Get risk summary with prop firm additions."""
        self._check_daily_reset()

        with self._lock:
            trailing_dd = self.state.peak_equity - self.state.current_equity
            return {
                'status': self.get_status().value,
                'daily_pnl': self.state.daily_pnl,
                'daily_trades': self.state.daily_trades,
                'consecutive_losses': self.state.consecutive_losses,
                'consecutive_losses_by_symbol': dict(self.state.consecutive_losses_by_symbol),
                'open_trades': self.state.open_trades,
                'open_contracts': self.state.open_contracts,
                'kill_switch': self.state.kill_switch_active,
                'blocked_reason': self.state.blocked_reason,
                # Prop firm additions
                'current_equity': self.state.current_equity,
                'peak_equity': self.state.peak_equity,
                'trailing_drawdown': trailing_dd,
                'limits': {
                    'max_daily_loss': self.limits.max_daily_loss,
                    'max_daily_trades': self.limits.max_daily_trades,
                    'max_open_trades': self.limits.max_open_trades,
                    'trailing_drawdown': self.limits.trailing_drawdown,
                    'account_size': self.limits.account_size,
                },
            }

    def is_trading_allowed(self) -> bool:
        """Quick check if trading is allowed."""
        status = self.get_status()
        return status in [RiskStatus.OK, RiskStatus.WARNING]


def create_default_risk_manager() -> RiskManager:
    """Create risk manager with default prop firm limits."""
    limits = RiskLimits(
        max_daily_loss=2000.0,
        max_daily_trades=0,
        max_consecutive_losses=0,  # Per-symbol limits handle this
        max_open_trades=3,
        max_contracts_per_trade=3,
        max_total_contracts=5,         # Prop firm: tighter than personal
        max_contracts_per_symbol=6,
        max_bos_risk_es=8.0,
        max_bos_risk_nq=20.0,
        disable_spy_intraday=True,
        trailing_drawdown=2500.0,
        account_size=50000.0,
    )
    return RiskManager(limits)
