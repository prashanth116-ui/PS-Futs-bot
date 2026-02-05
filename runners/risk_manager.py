"""
Risk Manager for V10.3 Strategy

Implements risk controls including:
- Daily loss limit
- Max position size
- Max open trades
- Time-based filters (V10.2/V10.3)
- Kill switch for emergencies
"""
import sys
sys.path.insert(0, '.')

from datetime import datetime, time as dt_time
from typing import Optional, Dict, List, Callable
from dataclasses import dataclass, field
from enum import Enum
import threading


class RiskStatus(Enum):
    OK = "ok"
    WARNING = "warning"
    BLOCKED = "blocked"
    KILLED = "killed"


@dataclass
class RiskLimits:
    """Risk limit configuration."""
    # Daily limits
    max_daily_loss: float = 2000.0        # Stop trading after this loss
    max_daily_trades: int = 10            # Max trades per day
    max_consecutive_losses: int = 3       # Pause after N consecutive losses

    # Position limits
    max_open_trades: int = 2              # Max simultaneous trades
    max_contracts_per_trade: int = 3      # Max contracts per single trade
    max_total_contracts: int = 6          # Max total open contracts

    # Per-symbol limits
    max_contracts_per_symbol: int = 3     # Max contracts per symbol

    # Time filters (V10.2/V10.3)
    midday_cutoff_start: dt_time = dt_time(12, 0)   # No entries 12:00-14:00
    midday_cutoff_end: dt_time = dt_time(14, 0)
    pm_cutoff_nq: dt_time = dt_time(14, 0)          # No NQ after 14:00
    pm_cutoff_qqq: dt_time = dt_time(14, 0)         # No QQQ after 14:00
    rth_start: dt_time = dt_time(9, 30)             # RTH start
    rth_end: dt_time = dt_time(16, 0)               # RTH end

    # BOS risk caps (V10.3)
    max_bos_risk_es: float = 8.0          # Max risk for ES BOS entries
    max_bos_risk_nq: float = 20.0         # Max risk for NQ BOS entries

    # SPY INTRADAY filter (V10.3)
    disable_spy_intraday: bool = True     # Disable SPY INTRADAY entries


@dataclass
class RiskState:
    """Current risk state tracking."""
    daily_pnl: float = 0.0
    daily_trades: int = 0
    consecutive_losses: int = 0
    open_trades: int = 0
    open_contracts: int = 0
    contracts_by_symbol: Dict[str, int] = field(default_factory=dict)
    last_trade_result: Optional[str] = None  # 'win' or 'loss'
    kill_switch_active: bool = False
    blocked_reason: Optional[str] = None

    # Today's date for reset
    current_date: datetime = field(default_factory=lambda: datetime.now().date())


class RiskManager:
    """
    Risk manager for live trading.

    Enforces risk limits and provides entry validation.
    """

    def __init__(self, limits: Optional[RiskLimits] = None):
        """Initialize risk manager with limits."""
        self.limits = limits or RiskLimits()
        self.state = RiskState()
        self._lock = threading.RLock()  # Use RLock to allow reentrant locking

        # Callbacks for alerts
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
        """Reset daily counters if new day."""
        today = datetime.now().date()
        if self.state.current_date != today:
            self.state.daily_pnl = 0.0
            self.state.daily_trades = 0
            self.state.consecutive_losses = 0
            self.state.current_date = today
            self.state.blocked_reason = None
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

        Args:
            symbol: Contract symbol (ES, NQ, SPY, QQQ)
            direction: LONG or SHORT
            entry_type: CREATION, RETRACEMENT, BOS_RETRACE, INTRADAY
            contracts: Number of contracts
            risk_pts: Risk in points
            entry_time: Entry timestamp (default: now)

        Returns:
            (allowed: bool, reason: str)
        """
        self._check_daily_reset()
        entry_time = entry_time or datetime.now()
        current_time = entry_time.time()

        with self._lock:
            # Kill switch check
            if self.state.kill_switch_active:
                return False, "Kill switch active"

            # Daily loss limit
            if self.state.daily_pnl <= -self.limits.max_daily_loss:
                self.state.blocked_reason = "Daily loss limit reached"
                return False, self.state.blocked_reason

            # Daily trade limit
            if self.state.daily_trades >= self.limits.max_daily_trades:
                return False, "Max daily trades reached"

            # Consecutive losses
            if self.state.consecutive_losses >= self.limits.max_consecutive_losses:
                return False, f"Max consecutive losses ({self.limits.max_consecutive_losses}) reached"

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
            # Midday cutoff (12:00-14:00) - no entries
            if self.limits.midday_cutoff_start <= current_time < self.limits.midday_cutoff_end:
                return False, "Midday cutoff (12:00-14:00)"

            # PM cutoff for NQ
            if symbol in ['NQ', 'MNQ'] and current_time >= self.limits.pm_cutoff_nq:
                return False, "NQ PM cutoff (after 14:00)"

            # PM cutoff for QQQ
            if symbol == 'QQQ' and current_time >= self.limits.pm_cutoff_qqq:
                return False, "QQQ PM cutoff (after 14:00)"

            # BOS risk cap (V10.3)
            if entry_type == 'BOS_RETRACE':
                if symbol in ['ES', 'MES'] and risk_pts > self.limits.max_bos_risk_es:
                    return False, f"BOS risk {risk_pts:.1f}pts exceeds ES cap ({self.limits.max_bos_risk_es}pts)"
                if symbol in ['NQ', 'MNQ'] and risk_pts > self.limits.max_bos_risk_nq:
                    return False, f"BOS risk {risk_pts:.1f}pts exceeds NQ cap ({self.limits.max_bos_risk_nq}pts)"

            # SPY INTRADAY filter (V10.3)
            if symbol == 'SPY' and entry_type == 'INTRADAY' and self.limits.disable_spy_intraday:
                return False, "SPY INTRADAY disabled (V10.3)"

            return True, "OK"

    def record_trade_entry(self, symbol: str, contracts: int):
        """Record a new trade entry."""
        with self._lock:
            self.state.open_trades += 1
            self.state.open_contracts += contracts
            self.state.daily_trades += 1
            self.state.contracts_by_symbol[symbol] = self.state.contracts_by_symbol.get(symbol, 0) + contracts

    def record_trade_exit(self, symbol: str, contracts: int, pnl: float, is_win: bool):
        """Record a trade exit."""
        with self._lock:
            self.state.open_trades = max(0, self.state.open_trades - 1)
            self.state.open_contracts = max(0, self.state.open_contracts - contracts)
            self.state.contracts_by_symbol[symbol] = max(0, self.state.contracts_by_symbol.get(symbol, 0) - contracts)
            self.state.daily_pnl += pnl

            if is_win:
                self.state.consecutive_losses = 0
                self.state.last_trade_result = 'win'
            else:
                self.state.consecutive_losses += 1
                self.state.last_trade_result = 'loss'

                # Check for alerts
                if self.state.consecutive_losses >= self.limits.max_consecutive_losses:
                    self._send_alert(
                        f"Max consecutive losses reached ({self.state.consecutive_losses})",
                        "warning"
                    )

            # Daily loss alert
            if self.state.daily_pnl <= -self.limits.max_daily_loss * 0.8:
                self._send_alert(
                    f"Approaching daily loss limit: ${self.state.daily_pnl:,.2f}",
                    "warning"
                )

            if self.state.daily_pnl <= -self.limits.max_daily_loss:
                self._send_alert(
                    f"DAILY LOSS LIMIT REACHED: ${self.state.daily_pnl:,.2f}",
                    "critical"
                )

    def record_partial_exit(self, symbol: str, contracts: int, pnl: float):
        """Record a partial exit (T1, T2)."""
        with self._lock:
            self.state.open_contracts = max(0, self.state.open_contracts - contracts)
            self.state.contracts_by_symbol[symbol] = max(0, self.state.contracts_by_symbol.get(symbol, 0) - contracts)
            self.state.daily_pnl += pnl

    def get_status(self) -> RiskStatus:
        """Get current risk status."""
        self._check_daily_reset()

        with self._lock:
            if self.state.kill_switch_active:
                return RiskStatus.KILLED

            if self.state.daily_pnl <= -self.limits.max_daily_loss:
                return RiskStatus.BLOCKED

            if self.state.consecutive_losses >= self.limits.max_consecutive_losses:
                return RiskStatus.BLOCKED

            if self.state.daily_pnl <= -self.limits.max_daily_loss * 0.5:
                return RiskStatus.WARNING

            if self.state.consecutive_losses >= 2:
                return RiskStatus.WARNING

            return RiskStatus.OK

    def get_summary(self) -> Dict:
        """Get risk summary."""
        self._check_daily_reset()

        with self._lock:
            return {
                'status': self.get_status().value,
                'daily_pnl': self.state.daily_pnl,
                'daily_trades': self.state.daily_trades,
                'consecutive_losses': self.state.consecutive_losses,
                'open_trades': self.state.open_trades,
                'open_contracts': self.state.open_contracts,
                'kill_switch': self.state.kill_switch_active,
                'blocked_reason': self.state.blocked_reason,
                'limits': {
                    'max_daily_loss': self.limits.max_daily_loss,
                    'max_daily_trades': self.limits.max_daily_trades,
                    'max_open_trades': self.limits.max_open_trades,
                },
            }

    def is_trading_allowed(self) -> bool:
        """Quick check if trading is allowed."""
        status = self.get_status()
        return status in [RiskStatus.OK, RiskStatus.WARNING]


def create_default_risk_manager() -> RiskManager:
    """Create risk manager with default V10.3 limits."""
    limits = RiskLimits(
        max_daily_loss=2000.0,
        max_daily_trades=10,
        max_consecutive_losses=3,
        max_open_trades=2,
        max_contracts_per_trade=3,
        max_total_contracts=6,
        max_bos_risk_es=8.0,
        max_bos_risk_nq=20.0,
        disable_spy_intraday=True,
    )
    return RiskManager(limits)


if __name__ == '__main__':
    print("Risk Manager Test")
    print("=" * 50)

    # Create risk manager
    rm = create_default_risk_manager()

    # Add alert callback
    def alert_handler(message, level):
        print(f"[ALERT - {level.upper()}] {message}")

    rm.add_alert_callback(alert_handler)

    print("\nInitial status:", rm.get_summary())

    # Test entry checks
    print("\n--- Entry Checks ---")

    # Normal entry
    allowed, reason = rm.can_enter_trade('ES', 'LONG', 'CREATION', 3, 2.0)
    print(f"ES CREATION: {allowed} - {reason}")

    # BOS with high risk
    allowed, reason = rm.can_enter_trade('ES', 'LONG', 'BOS_RETRACE', 3, 10.0)
    print(f"ES BOS (10pt risk): {allowed} - {reason}")

    # NQ BOS with high risk
    allowed, reason = rm.can_enter_trade('NQ', 'LONG', 'BOS_RETRACE', 3, 25.0)
    print(f"NQ BOS (25pt risk): {allowed} - {reason}")

    # SPY INTRADAY
    allowed, reason = rm.can_enter_trade('SPY', 'LONG', 'INTRADAY', 100, 0.5)
    print(f"SPY INTRADAY: {allowed} - {reason}")

    # Record some trades
    print("\n--- Simulating Trades ---")

    rm.record_trade_entry('ES', 3)
    print(f"After entry: {rm.state.open_trades} open trades")

    # Check if another entry allowed
    allowed, reason = rm.can_enter_trade('NQ', 'LONG', 'CREATION', 3, 6.0)
    print(f"2nd entry allowed: {allowed} - {reason}")

    rm.record_trade_entry('NQ', 3)

    # Try 3rd entry (should be blocked)
    allowed, reason = rm.can_enter_trade('ES', 'SHORT', 'CREATION', 3, 2.0)
    print(f"3rd entry allowed: {allowed} - {reason}")

    # Record losses
    print("\n--- Simulating Losses ---")
    rm.record_trade_exit('ES', 3, -500, False)
    rm.record_trade_exit('NQ', 3, -500, False)

    print(f"After 2 losses: {rm.get_summary()}")

    # One more loss
    rm.record_trade_entry('ES', 3)
    rm.record_trade_exit('ES', 3, -500, False)

    print(f"After 3 losses: {rm.get_summary()}")

    # Check if entry allowed
    allowed, reason = rm.can_enter_trade('ES', 'LONG', 'CREATION', 3, 2.0)
    print(f"Entry after 3 losses: {allowed} - {reason}")

    # Test kill switch
    print("\n--- Kill Switch ---")
    rm.activate_kill_switch("Test emergency")
    allowed, reason = rm.can_enter_trade('ES', 'LONG', 'CREATION', 3, 2.0)
    print(f"Entry with kill switch: {allowed} - {reason}")
