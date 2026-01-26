"""
ICT_Sweep_OTE_MSS_FVG_Long_v1 - Risk Manager

Handles:
- Position sizing based on risk percentage
- Daily loss limits
- Maximum concurrent positions
- Cooldown periods
- Trade validation
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional
import logging

from strategies.ict_sweep_ote.config import RiskConfig
from strategies.ict_sweep_ote.signals import TradeSignal, OpenTrade, TradeStatus


@dataclass
class DailyStats:
    """Daily trading statistics."""
    date: date
    trades_taken: int = 0
    trades_won: int = 0
    trades_lost: int = 0
    gross_pnl: float = 0.0
    commissions: float = 0.0
    net_pnl: float = 0.0
    max_drawdown: float = 0.0
    peak_equity: float = 0.0


@dataclass
class RiskState:
    """Current risk management state."""
    current_equity: float
    starting_equity: float
    daily_pnl: float = 0.0
    daily_trades: int = 0
    open_positions: int = 0
    max_open_reached: bool = False
    daily_limit_reached: bool = False
    in_cooldown: bool = False
    cooldown_bars: int = 0


class RiskManager:
    """
    Manages trading risk and position sizing.

    Enforces:
    - Maximum risk per trade
    - Maximum daily loss
    - Maximum concurrent positions
    - Post-trade cooldown
    """

    def __init__(
        self,
        config: RiskConfig,
        starting_equity: float = 100000.0,
        commission_per_contract: float = 2.25,  # Round-trip for futures
    ):
        self.config = config
        self.starting_equity = starting_equity
        self.current_equity = starting_equity
        self.commission_per_contract = commission_per_contract

        # State
        self.state = RiskState(
            current_equity=starting_equity,
            starting_equity=starting_equity,
        )

        # Daily tracking
        self.daily_stats: dict[date, DailyStats] = {}
        self.current_date: Optional[date] = None

        # Open trades
        self.open_trades: list[OpenTrade] = []

        # Logging
        self.logger = logging.getLogger("RiskManager")

    def reset_daily(self, new_date: date):
        """Reset daily statistics for new trading day."""
        if self.current_date and self.current_date in self.daily_stats:
            # Store previous day's stats
            pass

        self.current_date = new_date
        self.daily_stats[new_date] = DailyStats(
            date=new_date,
            peak_equity=self.current_equity,
        )

        self.state.daily_pnl = 0.0
        self.state.daily_trades = 0
        self.state.daily_limit_reached = False
        self.state.in_cooldown = False
        self.state.cooldown_bars = 0

    def can_take_trade(self, signal: TradeSignal) -> tuple[bool, str]:
        """
        Check if we can take a new trade.

        Returns:
            Tuple of (allowed, reason)
        """
        # Check daily loss limit
        if self.state.daily_limit_reached:
            return False, "Daily loss limit reached"

        max_daily_loss = self.starting_equity * self.config.max_daily_loss_pct
        if abs(self.state.daily_pnl) >= max_daily_loss:
            self.state.daily_limit_reached = True
            return False, f"Daily loss limit ({self.config.max_daily_loss_pct*100}%) reached"

        # Check max positions
        if self.state.open_positions >= self.config.max_positions:
            self.state.max_open_reached = True
            return False, f"Max positions ({self.config.max_positions}) reached"

        # Check cooldown
        if self.state.in_cooldown and self.state.cooldown_bars > 0:
            return False, f"In cooldown ({self.state.cooldown_bars} bars remaining)"

        # Check trade risk
        if signal.risk_amount > self.current_equity * self.config.risk_per_trade_pct * 1.5:
            return False, "Trade risk exceeds maximum"

        return True, "OK"

    def register_trade_open(self, trade: OpenTrade):
        """Register a new trade opening."""
        self.open_trades.append(trade)
        self.state.open_positions += 1
        self.state.daily_trades += 1

        if self.current_date and self.current_date in self.daily_stats:
            self.daily_stats[self.current_date].trades_taken += 1

        self.logger.info(
            f"Trade opened: {trade.signal.signal_id} | "
            f"Size: {trade.signal.position_size} | "
            f"Risk: ${trade.signal.risk_amount:.2f}"
        )

    def register_trade_close(
        self,
        trade: OpenTrade,
        exit_price: float,
        exit_bar_index: int,
    ):
        """Register a trade closing."""
        if trade in self.open_trades:
            self.open_trades.remove(trade)

        self.state.open_positions = max(0, self.state.open_positions - 1)

        # Calculate P&L
        if trade.signal.direction.value == "LONG":
            pnl_points = exit_price - trade.entry_fill_price
        else:
            pnl_points = trade.entry_fill_price - exit_price

        # ES: $50/point, NQ: $20/point
        point_value = 50.0 if trade.signal.symbol.upper() in ["ES", "ES1!"] else 20.0
        gross_pnl = pnl_points * point_value * trade.signal.position_size
        commission = self.commission_per_contract * trade.signal.position_size * 2  # Round-trip
        net_pnl = gross_pnl - commission

        # Update equity
        self.current_equity += net_pnl
        self.state.current_equity = self.current_equity
        self.state.daily_pnl += net_pnl

        # Update daily stats
        if self.current_date and self.current_date in self.daily_stats:
            stats = self.daily_stats[self.current_date]
            stats.gross_pnl += gross_pnl
            stats.commissions += commission
            stats.net_pnl += net_pnl

            if net_pnl > 0:
                stats.trades_won += 1
            else:
                stats.trades_lost += 1

            # Update peak and drawdown
            if self.current_equity > stats.peak_equity:
                stats.peak_equity = self.current_equity
            drawdown = stats.peak_equity - self.current_equity
            if drawdown > stats.max_drawdown:
                stats.max_drawdown = drawdown

        # Start cooldown
        self.state.in_cooldown = True
        self.state.cooldown_bars = self.config.cooldown_bars

        self.logger.info(
            f"Trade closed: {trade.signal.signal_id} | "
            f"P&L: ${net_pnl:.2f} ({'+' if net_pnl > 0 else ''}{pnl_points:.2f} pts)"
        )

    def update_bar(self):
        """Called on each new bar to update cooldown etc."""
        if self.state.in_cooldown:
            self.state.cooldown_bars -= 1
            if self.state.cooldown_bars <= 0:
                self.state.in_cooldown = False
                self.state.cooldown_bars = 0

    def calculate_position_size(
        self,
        entry_price: float,
        stop_price: float,
        symbol: str = "ES",
    ) -> tuple[int, float]:
        """
        Calculate position size based on risk parameters.

        Args:
            entry_price: Entry price
            stop_price: Stop loss price
            symbol: Trading symbol

        Returns:
            Tuple of (contracts, risk_amount)
        """
        risk_amount = self.current_equity * self.config.risk_per_trade_pct

        # Symbol-specific tick values
        if symbol.upper() in ["ES", "ES1!"]:
            tick_value = 12.50
            tick_size = 0.25
        elif symbol.upper() in ["NQ", "NQ1!"]:
            tick_value = 5.00
            tick_size = 0.25
        elif symbol.upper() in ["YM", "YM1!"]:
            tick_value = 5.00
            tick_size = 1.0
        elif symbol.upper() in ["RTY", "RTY1!"]:
            tick_value = 5.00
            tick_size = 0.10
        else:
            tick_value = 12.50
            tick_size = 0.25

        sl_distance = abs(entry_price - stop_price)
        sl_ticks = sl_distance / tick_size
        dollar_risk_per_contract = sl_ticks * tick_value

        if dollar_risk_per_contract <= 0:
            return 0, 0.0

        contracts = int(risk_amount / dollar_risk_per_contract)
        contracts = max(1, min(contracts, self.config.max_positions))

        actual_risk = contracts * dollar_risk_per_contract + (contracts * self.commission_per_contract * 2)

        return contracts, actual_risk

    def get_daily_summary(self) -> dict:
        """Get summary of today's trading."""
        if not self.current_date or self.current_date not in self.daily_stats:
            return {}

        stats = self.daily_stats[self.current_date]
        total_trades = stats.trades_won + stats.trades_lost

        return {
            "date": stats.date.isoformat(),
            "trades_taken": stats.trades_taken,
            "trades_won": stats.trades_won,
            "trades_lost": stats.trades_lost,
            "win_rate": stats.trades_won / total_trades if total_trades > 0 else 0,
            "gross_pnl": stats.gross_pnl,
            "commissions": stats.commissions,
            "net_pnl": stats.net_pnl,
            "max_drawdown": stats.max_drawdown,
            "current_equity": self.current_equity,
            "return_pct": (self.current_equity - self.starting_equity) / self.starting_equity * 100,
        }
