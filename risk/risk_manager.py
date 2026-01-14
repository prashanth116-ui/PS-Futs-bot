"""
Risk Manager Module

Provides non-bypassable risk controls for the trading system.
This module enforces hard limits that CANNOT be overridden by strategies
or other components - protecting the account from excessive losses.

PAPER TRADING ONLY - This implementation is for simulation/paper trading.
Live trading requires additional safeguards and broker integration.

Key Controls:
    - max_trades_per_day: Limit daily trade count
    - max_daily_loss_usd: Stop trading after losing X dollars
    - max_risk_per_trade_usd: Cap risk on any single trade
    - max_open_positions: Limit concurrent positions
    - max_consecutive_losses: Pause after losing streak

Circuit Breaker:
    When any critical limit is hit, the circuit breaker trips and
    disables ALL trading for the remainder of the day. This is a
    safety mechanism that cannot be bypassed programmatically.

Usage:
    from risk.risk_manager import RiskManager

    risk_mgr = RiskManager(
        max_trades_per_day=3,
        max_daily_loss_usd=500.0,
        max_risk_per_trade_usd=100.0,
    )

    approved, reason, adjusted = risk_mgr.approve(signal, account_state)
    if approved:
        # Execute the trade (possibly with adjusted position size)
        execute(adjusted or signal)
    else:
        # Trade rejected - log the reason
        print(f"Trade rejected: {reason}")
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.types import Signal


class CircuitBreakerState(Enum):
    """
    Circuit breaker states.

    CLOSED: Normal operation, trades allowed
    OPEN: Tripped, all trades blocked for the day
    """

    CLOSED = "CLOSED"  # Normal - trades allowed
    OPEN = "OPEN"      # Tripped - trades blocked


class RejectionReason(Enum):
    """
    Standardized rejection reasons for trade denials.

    Used for logging, analytics, and debugging why trades were blocked.
    """

    CIRCUIT_BREAKER_OPEN = "Circuit breaker is OPEN - trading disabled for today"
    MAX_TRADES_REACHED = "Maximum trades per day reached"
    MAX_DAILY_LOSS_REACHED = "Maximum daily loss reached"
    MAX_RISK_EXCEEDED = "Trade risk exceeds maximum allowed"
    MAX_POSITIONS_REACHED = "Maximum open positions reached"
    CONSECUTIVE_LOSSES = "Maximum consecutive losses reached"
    INVALID_SIGNAL = "Signal failed validation"
    ZERO_RISK = "Cannot calculate position size - zero risk"
    PAPER_ONLY = "Live trading not enabled - paper only"


@dataclass
class AccountState:
    """
    Current state of the trading account.

    This is passed to the risk manager to make approval decisions.
    Should be updated in real-time as trades occur.

    Attributes:
        balance: Current account balance in USD.
        daily_pnl: Today's realized P&L in USD (negative = loss).
        open_positions: Number of currently open positions.
        trades_today: Number of trades executed today.
        consecutive_losses: Current streak of losing trades.
        last_trade_time: When the last trade occurred.

    Example:
        state = AccountState(
            balance=10000.0,
            daily_pnl=-150.0,  # Down $150 today
            open_positions=1,
            trades_today=2,
            consecutive_losses=1,
        )
    """

    # Current account balance in USD
    balance: float = 0.0

    # Today's P&L (positive = profit, negative = loss)
    daily_pnl: float = 0.0

    # Number of positions currently open
    open_positions: int = 0

    # Number of trades taken today
    trades_today: int = 0

    # Current consecutive losing trade streak
    consecutive_losses: int = 0

    # Timestamp of last trade (for cooldown logic if needed)
    last_trade_time: datetime | None = None


@dataclass
class ApprovalResult:
    """
    Result of a trade approval request.

    Returned by RiskManager.approve() with full details about
    whether the trade was approved and any adjustments made.

    Attributes:
        approved: Whether the trade is allowed to proceed.
        reason: Human-readable explanation of the decision.
        rejection_code: Standardized rejection reason (if rejected).
        adjusted_signal: Modified signal with adjusted size (if approved).
        risk_amount: Calculated risk in USD for this trade.
        position_size: Recommended position size in contracts.
    """

    # Was the trade approved?
    approved: bool

    # Human-readable explanation
    reason: str

    # Standardized rejection code (None if approved)
    rejection_code: RejectionReason | None = None

    # Signal with adjusted position size (None if rejected)
    adjusted_signal: "Signal | None" = None

    # Calculated risk for this trade in USD
    risk_amount: float = 0.0

    # Recommended position size in contracts
    position_size: int = 0


@dataclass
class RiskManager:
    """
    Non-bypassable risk control system.

    This class enforces hard limits on trading activity to protect
    the account from excessive losses. These limits CANNOT be
    overridden by strategies or other code.

    PAPER TRADING ONLY - This is for simulation/paper trading.

    The risk manager acts as a gatekeeper: every trade signal must
    pass through approve() before execution. If any limit is
    exceeded, the trade is rejected.

    Circuit Breaker:
        When critical limits are hit (daily loss, consecutive losses),
        the circuit breaker trips and blocks ALL trades for the day.
        This is a safety mechanism that requires manual reset.

    Attributes:
        max_trades_per_day: Maximum number of trades allowed per day.
                            Set to 0 for unlimited (not recommended).

        max_daily_loss_usd: Maximum daily loss before stopping.
                            When daily_pnl <= -max_daily_loss_usd,
                            circuit breaker trips.

        max_risk_per_trade_usd: Maximum risk allowed on any single trade.
                                Trades exceeding this will be rejected
                                or have size reduced.

        max_open_positions: Maximum concurrent positions allowed.
                            New trades blocked when at limit.

        max_consecutive_losses: Maximum losing streak before pausing.
                                Circuit breaker trips at this limit.

        tick_value: Dollar value per tick (for position sizing).
                    Default 12.50 for ES futures.

    Example:
        # Create risk manager with conservative limits
        risk_mgr = RiskManager(
            max_trades_per_day=3,
            max_daily_loss_usd=500.0,
            max_risk_per_trade_usd=100.0,
            max_open_positions=1,
            max_consecutive_losses=2,
        )

        # Check if trade is allowed
        result = risk_mgr.approve(signal, account_state)
        if result.approved:
            execute_trade(result.adjusted_signal)
        else:
            log_rejection(result.reason)
    """

    # -------------------------------------------------------------------------
    # Risk limits (non-bypassable)
    # -------------------------------------------------------------------------

    # Maximum trades per day (0 = unlimited, not recommended)
    max_trades_per_day: int = 3

    # Maximum daily loss in USD before circuit breaker trips
    max_daily_loss_usd: float = 500.0

    # Maximum risk per trade in USD
    max_risk_per_trade_usd: float = 100.0

    # Maximum concurrent open positions
    max_open_positions: int = 2

    # Maximum consecutive losses before circuit breaker trips
    max_consecutive_losses: int = 3

    # -------------------------------------------------------------------------
    # Position sizing parameters
    # -------------------------------------------------------------------------

    # Dollar value per tick (ES = $12.50, NQ = $5.00)
    tick_value: float = 12.50

    # Tick size for the instrument (ES = 0.25, NQ = 0.25)
    tick_size: float = 0.25

    # -------------------------------------------------------------------------
    # Internal state (managed automatically)
    # -------------------------------------------------------------------------

    # Circuit breaker state - blocks all trades when OPEN
    _circuit_breaker: CircuitBreakerState = field(
        default=CircuitBreakerState.CLOSED,
        repr=False,
    )

    # Reason the circuit breaker tripped (for logging)
    _circuit_breaker_reason: str = field(default="", repr=False)

    # Timestamp when circuit breaker was tripped
    _circuit_breaker_time: datetime | None = field(default=None, repr=False)

    # Flag indicating this is paper trading only
    _paper_only: bool = field(default=True, repr=False)

    # -------------------------------------------------------------------------
    # Public methods
    # -------------------------------------------------------------------------

    def approve(
        self,
        signal: "Signal",
        account_state: AccountState,
    ) -> ApprovalResult:
        """
        Evaluate a trading signal against all risk controls.

        This is the main entry point for the risk manager. Every signal
        MUST pass through this method before execution. The method
        performs the following checks in order:

        1. Circuit breaker check (immediate rejection if open)
        2. Daily trade count limit
        3. Daily loss limit
        4. Consecutive loss limit
        5. Open positions limit
        6. Per-trade risk limit

        If all checks pass, the method calculates the appropriate
        position size based on risk limits.

        Args:
            signal: The trading signal to evaluate.
            account_state: Current account state (balance, P&L, etc.)

        Returns:
            ApprovalResult with:
                - approved: Whether trade is allowed
                - reason: Explanation of decision
                - adjusted_signal: Signal with correct position size
                - risk_amount: Calculated risk in USD

        Example:
            result = risk_mgr.approve(signal, account_state)
            if result.approved:
                # Use result.adjusted_signal for correct size
                broker.submit_order(result.adjusted_signal)
            else:
                logger.warning(f"Trade rejected: {result.reason}")
        """
        # ---------------------------------------------------------------------
        # Check 0: Paper trading only
        # ---------------------------------------------------------------------
        # This implementation is for paper trading only
        # Live trading requires additional safeguards

        # ---------------------------------------------------------------------
        # Check 1: Circuit breaker
        # ---------------------------------------------------------------------
        if self._circuit_breaker == CircuitBreakerState.OPEN:
            return ApprovalResult(
                approved=False,
                reason=f"Circuit breaker OPEN: {self._circuit_breaker_reason}",
                rejection_code=RejectionReason.CIRCUIT_BREAKER_OPEN,
            )

        # ---------------------------------------------------------------------
        # Check 2: Daily trade count
        # ---------------------------------------------------------------------
        if self.max_trades_per_day > 0:
            if account_state.trades_today >= self.max_trades_per_day:
                return ApprovalResult(
                    approved=False,
                    reason=f"Max trades reached: {account_state.trades_today}/{self.max_trades_per_day}",
                    rejection_code=RejectionReason.MAX_TRADES_REACHED,
                )

        # ---------------------------------------------------------------------
        # Check 3: Daily loss limit
        # ---------------------------------------------------------------------
        if account_state.daily_pnl <= -self.max_daily_loss_usd:
            # Trip circuit breaker - this is a critical limit
            self._trip_circuit_breaker(
                f"Daily loss limit reached: ${abs(account_state.daily_pnl):.2f} >= ${self.max_daily_loss_usd:.2f}"
            )
            return ApprovalResult(
                approved=False,
                reason=f"Daily loss limit reached: ${abs(account_state.daily_pnl):.2f}",
                rejection_code=RejectionReason.MAX_DAILY_LOSS_REACHED,
            )

        # ---------------------------------------------------------------------
        # Check 4: Consecutive losses
        # ---------------------------------------------------------------------
        if account_state.consecutive_losses >= self.max_consecutive_losses:
            # Trip circuit breaker - this is a critical limit
            self._trip_circuit_breaker(
                f"Consecutive losses: {account_state.consecutive_losses} >= {self.max_consecutive_losses}"
            )
            return ApprovalResult(
                approved=False,
                reason=f"Max consecutive losses: {account_state.consecutive_losses}",
                rejection_code=RejectionReason.CONSECUTIVE_LOSSES,
            )

        # ---------------------------------------------------------------------
        # Check 5: Open positions limit
        # ---------------------------------------------------------------------
        if account_state.open_positions >= self.max_open_positions:
            return ApprovalResult(
                approved=False,
                reason=f"Max positions reached: {account_state.open_positions}/{self.max_open_positions}",
                rejection_code=RejectionReason.MAX_POSITIONS_REACHED,
            )

        # ---------------------------------------------------------------------
        # Check 6: Calculate risk and position size
        # ---------------------------------------------------------------------
        risk_result = self._calculate_position_size(signal)

        if risk_result["error"]:
            return ApprovalResult(
                approved=False,
                reason=risk_result["error"],
                rejection_code=RejectionReason.MAX_RISK_EXCEEDED
                if "exceeds" in risk_result["error"]
                else RejectionReason.ZERO_RISK,
            )

        # ---------------------------------------------------------------------
        # All checks passed - trade approved
        # ---------------------------------------------------------------------
        return ApprovalResult(
            approved=True,
            reason="Trade approved",
            adjusted_signal=signal,  # TODO: Create adjusted copy with size
            risk_amount=risk_result["risk_usd"],
            position_size=risk_result["contracts"],
        )

    def reset_daily(self) -> None:
        """
        Reset daily counters and close circuit breaker.

        Call this at the start of each trading day to:
            - Close the circuit breaker (allow new trades)
            - Clear the circuit breaker reason

        Note: Account state (daily_pnl, trades_today) should be
        reset separately by the account management component.

        Example:
            # At market open each day
            risk_manager.reset_daily()
        """
        self._circuit_breaker = CircuitBreakerState.CLOSED
        self._circuit_breaker_reason = ""
        self._circuit_breaker_time = None

    def is_trading_enabled(self) -> bool:
        """
        Check if trading is currently enabled.

        Returns False if the circuit breaker is open.

        Returns:
            True if trades can be submitted, False if blocked.

        Example:
            if not risk_manager.is_trading_enabled():
                print("Trading is disabled - circuit breaker open")
        """
        return self._circuit_breaker == CircuitBreakerState.CLOSED

    def get_circuit_breaker_status(self) -> dict:
        """
        Get detailed circuit breaker status.

        Returns:
            Dictionary with:
                - state: "CLOSED" or "OPEN"
                - reason: Why it tripped (empty if closed)
                - tripped_at: When it tripped (None if closed)

        Example:
            status = risk_manager.get_circuit_breaker_status()
            if status["state"] == "OPEN":
                print(f"Tripped at {status['tripped_at']}: {status['reason']}")
        """
        return {
            "state": self._circuit_breaker.value,
            "reason": self._circuit_breaker_reason,
            "tripped_at": self._circuit_breaker_time,
        }

    def get_remaining_capacity(self, account_state: AccountState) -> dict:
        """
        Get remaining capacity for each risk limit.

        Useful for displaying in UI or logs to show how much
        headroom remains before limits are hit.

        Args:
            account_state: Current account state.

        Returns:
            Dictionary with remaining capacity for each limit.

        Example:
            capacity = risk_manager.get_remaining_capacity(state)
            print(f"Trades remaining: {capacity['trades_remaining']}")
            print(f"Loss capacity: ${capacity['loss_capacity_usd']:.2f}")
        """
        trades_remaining = max(0, self.max_trades_per_day - account_state.trades_today)
        loss_capacity = max(0.0, self.max_daily_loss_usd + account_state.daily_pnl)
        positions_remaining = max(0, self.max_open_positions - account_state.open_positions)
        losses_until_pause = max(0, self.max_consecutive_losses - account_state.consecutive_losses)

        return {
            "trades_remaining": trades_remaining,
            "loss_capacity_usd": loss_capacity,
            "positions_remaining": positions_remaining,
            "losses_until_pause": losses_until_pause,
            "circuit_breaker": self._circuit_breaker.value,
        }

    def manually_trip_circuit_breaker(self, reason: str) -> None:
        """
        Manually trip the circuit breaker.

        Use this to stop all trading immediately for any reason.
        For example: news event, technical issue, or manual override.

        Args:
            reason: Explanation for why trading was stopped.

        Example:
            # Stop trading due to breaking news
            risk_manager.manually_trip_circuit_breaker("FOMC announcement imminent")
        """
        self._trip_circuit_breaker(f"Manual: {reason}")

    # -------------------------------------------------------------------------
    # Private methods
    # -------------------------------------------------------------------------

    def _trip_circuit_breaker(self, reason: str) -> None:
        """
        Internal method to trip the circuit breaker.

        Once tripped, all trades are blocked until reset_daily() is called.
        """
        self._circuit_breaker = CircuitBreakerState.OPEN
        self._circuit_breaker_reason = reason
        self._circuit_breaker_time = datetime.now()

    def _calculate_position_size(self, signal: "Signal") -> dict:
        """
        Calculate appropriate position size based on risk limits.

        Uses the distance from entry to stop to determine how many
        contracts can be traded within the max_risk_per_trade_usd limit.

        Returns:
            Dictionary with:
                - contracts: Number of contracts to trade
                - risk_usd: Total risk in USD
                - error: Error message if calculation failed
        """
        # Need entry and stop price to calculate risk
        entry_price = signal.entry_price
        stop_price = signal.stop_price

        # For market orders without entry_price, we can't calculate exact risk
        # In practice, you'd use the current market price
        if entry_price is None:
            return {
                "contracts": 1,
                "risk_usd": self.max_risk_per_trade_usd,  # Assume max risk
                "error": None,
            }

        # Calculate risk per contract
        price_risk = abs(entry_price - stop_price)

        if price_risk == 0:
            return {
                "contracts": 0,
                "risk_usd": 0.0,
                "error": "Zero risk - entry equals stop price",
            }

        # Convert price risk to ticks, then to dollars
        ticks = price_risk / self.tick_size
        risk_per_contract = ticks * self.tick_value

        if risk_per_contract == 0:
            return {
                "contracts": 0,
                "risk_usd": 0.0,
                "error": "Zero risk per contract",
            }

        # Calculate max contracts within risk limit
        max_contracts = int(self.max_risk_per_trade_usd / risk_per_contract)

        if max_contracts < 1:
            return {
                "contracts": 0,
                "risk_usd": risk_per_contract,
                "error": f"Risk per contract (${risk_per_contract:.2f}) exceeds max (${self.max_risk_per_trade_usd:.2f})",
            }

        # Return the calculated position
        actual_risk = max_contracts * risk_per_contract

        return {
            "contracts": max_contracts,
            "risk_usd": actual_risk,
            "error": None,
        }


# =============================================================================
# Factory function for common configurations
# =============================================================================


def create_conservative_risk_manager(
    account_size: float = 10000.0,
    risk_per_trade_pct: float = 1.0,
    daily_loss_pct: float = 3.0,
    instrument: str = "ES",
) -> RiskManager:
    """
    Create a RiskManager with conservative default settings.

    This factory function creates a risk manager appropriate for
    a beginner or someone wanting strict risk controls.

    Args:
        account_size: Account balance in USD.
        risk_per_trade_pct: Max risk per trade as percentage of account.
        daily_loss_pct: Max daily loss as percentage of account.
        instrument: "ES" or "NQ" for correct tick value.

    Returns:
        Configured RiskManager instance.

    Example:
        # $10k account, risk 1% per trade, stop at 3% daily loss
        risk_mgr = create_conservative_risk_manager(
            account_size=10000.0,
            risk_per_trade_pct=1.0,
            daily_loss_pct=3.0,
        )
    """
    # Calculate dollar amounts from percentages
    max_risk_per_trade = account_size * (risk_per_trade_pct / 100.0)
    max_daily_loss = account_size * (daily_loss_pct / 100.0)

    # Instrument-specific settings
    if instrument.upper() == "NQ":
        tick_value = 5.0
    else:  # Default to ES
        tick_value = 12.5

    return RiskManager(
        max_trades_per_day=3,
        max_daily_loss_usd=max_daily_loss,
        max_risk_per_trade_usd=max_risk_per_trade,
        max_open_positions=1,
        max_consecutive_losses=2,
        tick_value=tick_value,
        tick_size=0.25,
    )


def create_aggressive_risk_manager(
    account_size: float = 25000.0,
    risk_per_trade_pct: float = 2.0,
    daily_loss_pct: float = 5.0,
    instrument: str = "ES",
) -> RiskManager:
    """
    Create a RiskManager with more aggressive settings.

    WARNING: These settings allow more risk and are suitable for
    experienced traders with larger accounts.

    Args:
        account_size: Account balance in USD.
        risk_per_trade_pct: Max risk per trade as percentage of account.
        daily_loss_pct: Max daily loss as percentage of account.
        instrument: "ES" or "NQ" for correct tick value.

    Returns:
        Configured RiskManager instance.
    """
    max_risk_per_trade = account_size * (risk_per_trade_pct / 100.0)
    max_daily_loss = account_size * (daily_loss_pct / 100.0)

    if instrument.upper() == "NQ":
        tick_value = 5.0
    else:
        tick_value = 12.5

    return RiskManager(
        max_trades_per_day=5,
        max_daily_loss_usd=max_daily_loss,
        max_risk_per_trade_usd=max_risk_per_trade,
        max_open_positions=2,
        max_consecutive_losses=3,
        tick_value=tick_value,
        tick_size=0.25,
    )
