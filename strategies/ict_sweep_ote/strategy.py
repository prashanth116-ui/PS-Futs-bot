"""
ICT_Sweep_OTE_MSS_FVG Strategy - Main Strategy (Long & Short)

State machine-based strategy that detects:

LONG Setup (SSL Sweep):
1. Swing lows (sell-side liquidity pools)
2. SSL sweep (price dips below swing low then recovers)
3. Bullish MSS (break above lower-high)
4. Bullish displacement + FVG
5. OTE zone overlap (50-79% retracement)
6. Entry on FVG retrace

SHORT Setup (BSL Sweep):
1. Swing highs (buy-side liquidity pools)
2. BSL sweep (price spikes above swing high then reverses)
3. Bearish MSS (break below higher-low)
4. Bearish displacement + FVG
5. OTE zone overlap (50-79% retracement from low)
6. Entry on FVG retrace

Flow: IDLE → SCANNING → SWEEP_DETECTED → MSS_PENDING → AWAITING_FVG → AWAITING_ENTRY → IN_TRADE
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal
from enum import Enum
import logging

from core.types import Bar
from strategies.ict_sweep_ote.config import StrategyConfig
from strategies.ict_sweep_ote.detectors import (
    SwingPoint,
    SSLSweep,
    BSLSweep,
    MSSEvent,
    FVGZone,
    OTEZone,
    DisplacementCandle,
    detect_swings,
    detect_ssl_sweep,
    confirm_ssl_sweep,
    detect_bsl_sweep,
    confirm_bsl_sweep,
    detect_mss,
    detect_bearish_mss,
    detect_displacement_fvg,
    calculate_ote_zone,
    calculate_atr,
    check_fvg_entry,
    check_fvg_mitigation,
    get_recent_swing_highs,
    get_recent_swing_lows,
)
from strategies.ict_sweep_ote.signals import (
    TradeSignal,
    OpenTrade,
    TradeStatus,
    SignalDirection,
    build_trade_signal,
    update_trade,
)


class StrategyState(Enum):
    IDLE = "IDLE"                       # Initial state
    SCANNING = "SCANNING"               # Looking for swing lows
    SWEEP_DETECTED = "SWEEP_DETECTED"   # SSL sweep found, awaiting confirmation
    MSS_PENDING = "MSS_PENDING"         # Sweep confirmed, looking for MSS
    AWAITING_FVG = "AWAITING_FVG"       # MSS confirmed, looking for displacement FVG
    AWAITING_ENTRY = "AWAITING_ENTRY"   # FVG formed, waiting for retrace entry
    IN_TRADE = "IN_TRADE"               # Position is open
    COOLDOWN = "COOLDOWN"               # Post-trade cooldown period


@dataclass
class SetupContext:
    """Tracks the current setup being built."""
    sweep: Optional[SSLSweep | BSLSweep] = None  # SSL for longs, BSL for shorts
    mss: Optional[MSSEvent] = None
    displacement: Optional[DisplacementCandle] = None
    fvg: Optional[FVGZone] = None
    ote: Optional[OTEZone] = None
    direction: Optional[Literal["LONG", "SHORT"]] = None  # Setup direction

    # Tracking
    bars_since_sweep: int = 0
    bars_since_mss: int = 0
    bars_since_fvg: int = 0

    def reset(self):
        """Reset context for new setup."""
        self.sweep = None
        self.mss = None
        self.displacement = None
        self.fvg = None
        self.ote = None
        self.direction = None
        self.bars_since_sweep = 0
        self.bars_since_mss = 0
        self.bars_since_fvg = 0


class ICTSweepOTEStrategy:
    """
    ICT Sweep + OTE + MSS + FVG Strategy (Long & Short)

    State machine-based approach for clean signal generation.
    Supports both long setups (SSL sweeps) and short setups (BSL sweeps).
    """

    def __init__(self, config: StrategyConfig, equity: float = 100000.0):
        self.config = config
        self.equity = equity

        # State
        self.state = StrategyState.SCANNING
        self.context = SetupContext()

        # Data storage
        self.bars: list[Bar] = []
        self.swings: list[SwingPoint] = []
        self.active_fvgs: list[FVGZone] = []

        # Trade management
        self.open_trades: list[OpenTrade] = []
        self.closed_trades: list[OpenTrade] = []
        self.signals_generated: list[TradeSignal] = []

        # Cooldown tracking
        self.cooldown_bars_remaining: int = 0

        # Daily tracking
        self.daily_pnl: float = 0.0
        self.trades_today: int = 0

        # Logging
        self.logger = logging.getLogger(f"ICT.{config.symbol}")
        if config.log_level:
            self.logger.setLevel(getattr(logging, config.log_level))

    def reset(self):
        """Reset strategy state for new session."""
        self.state = StrategyState.SCANNING
        self.context.reset()
        self.bars.clear()
        self.swings.clear()
        self.active_fvgs.clear()
        self.open_trades.clear()
        self.cooldown_bars_remaining = 0
        self.daily_pnl = 0.0
        self.trades_today = 0

    @property
    def atr(self) -> float:
        """Current ATR value."""
        return calculate_atr(self.bars, self.config.displacement.atr_period)

    def on_bar(self, bar: Bar) -> Optional[TradeSignal]:
        """
        Process new bar and return signal if generated.

        This is the main entry point called for each new bar.
        """
        self.bars.append(bar)
        current_idx = len(self.bars) - 1

        # Update existing trades
        self._manage_open_trades(bar)

        # Check filters
        if not self._passes_filters(bar):
            return None

        # Handle cooldown
        if self.state == StrategyState.COOLDOWN:
            self.cooldown_bars_remaining -= 1
            if self.cooldown_bars_remaining <= 0:
                self.state = StrategyState.SCANNING
                self.context.reset()
            return None

        # State machine
        signal = self._process_state(bar, current_idx)

        if signal:
            self.signals_generated.append(signal)
            if self.config.log_signals:
                self.logger.info(
                    f"SIGNAL: {signal.direction.value} @ {signal.entry_price:.2f} "
                    f"SL={signal.stop_price:.2f} TP1={signal.targets[0]:.2f}"
                )

        return signal

    def _process_state(self, bar: Bar, current_idx: int) -> Optional[TradeSignal]:
        """Process current state and transition as needed."""

        # Always update swings
        self.swings = detect_swings(self.bars, self.config.swing, self.swings)

        # State transitions
        if self.state == StrategyState.SCANNING:
            return self._state_scanning(bar, current_idx)

        elif self.state == StrategyState.SWEEP_DETECTED:
            return self._state_sweep_detected(bar, current_idx)

        elif self.state == StrategyState.MSS_PENDING:
            return self._state_mss_pending(bar, current_idx)

        elif self.state == StrategyState.AWAITING_FVG:
            return self._state_awaiting_fvg(bar, current_idx)

        elif self.state == StrategyState.AWAITING_ENTRY:
            return self._state_awaiting_entry(bar, current_idx)

        elif self.state == StrategyState.IN_TRADE:
            return self._state_in_trade(bar, current_idx)

        return None

    def _state_scanning(self, bar: Bar, current_idx: int) -> Optional[TradeSignal]:
        """SCANNING: Look for SSL sweep (long) or BSL sweep (short)."""

        # Check for SSL sweep (for long setup)
        ssl_sweep = detect_ssl_sweep(
            bars=self.bars,
            swings=self.swings,
            current_bar_index=current_idx,
            config=self.config.sweep,
            atr=self.atr,
        )

        if ssl_sweep:
            self.context.sweep = ssl_sweep
            self.context.direction = "LONG"
            self.context.bars_since_sweep = 0

            if ssl_sweep.confirmed:
                self.state = StrategyState.MSS_PENDING
                if self.config.alert_on_sweep:
                    self.logger.info(
                        f"SSL SWEEP CONFIRMED: {bar.timestamp} | "
                        f"Swept {ssl_sweep.swept_swing.price:.2f} -> {ssl_sweep.sweep_low:.2f}"
                    )
            else:
                self.state = StrategyState.SWEEP_DETECTED
            return None

        # Check for BSL sweep (for short setup)
        bsl_sweep = detect_bsl_sweep(
            bars=self.bars,
            swings=self.swings,
            current_bar_index=current_idx,
            config=self.config.sweep,
            atr=self.atr,
        )

        if bsl_sweep:
            self.context.sweep = bsl_sweep
            self.context.direction = "SHORT"
            self.context.bars_since_sweep = 0

            if bsl_sweep.confirmed:
                self.state = StrategyState.MSS_PENDING
                if self.config.alert_on_sweep:
                    self.logger.info(
                        f"BSL SWEEP CONFIRMED: {bar.timestamp} | "
                        f"Swept {bsl_sweep.swept_swing.price:.2f} -> {bsl_sweep.sweep_high:.2f}"
                    )
            else:
                self.state = StrategyState.SWEEP_DETECTED

        return None

    def _state_sweep_detected(self, bar: Bar, current_idx: int) -> Optional[TradeSignal]:
        """SWEEP_DETECTED: Await sweep confirmation."""

        self.context.bars_since_sweep += 1

        # Check for confirmation based on direction
        if self.context.direction == "LONG":
            confirmed = confirm_ssl_sweep(
                sweep=self.context.sweep,
                bars=self.bars,
                current_bar_index=current_idx,
                config=self.config.sweep,
            )
        else:  # SHORT
            confirmed = confirm_bsl_sweep(
                sweep=self.context.sweep,
                bars=self.bars,
                current_bar_index=current_idx,
                config=self.config.sweep,
            )

        if confirmed:
            self.state = StrategyState.MSS_PENDING
            if self.config.alert_on_sweep:
                sweep_type = "SSL" if self.context.direction == "LONG" else "BSL"
                self.logger.info(
                    f"{sweep_type} SWEEP CONFIRMED: {bar.timestamp} | "
                    f"Swept {self.context.sweep.swept_swing.price:.2f}"
                )
        elif self.context.bars_since_sweep > self.config.sweep.max_bars_for_confirm:
            # Timeout - reset to scanning
            self.state = StrategyState.SCANNING
            self.context.reset()

        return None

    def _state_mss_pending(self, bar: Bar, current_idx: int) -> Optional[TradeSignal]:
        """MSS_PENDING: Look for Market Structure Shift."""

        self.context.bars_since_sweep += 1

        # Check for MSS based on direction
        if self.context.direction == "LONG":
            mss = detect_mss(
                bars=self.bars,
                sweep=self.context.sweep,
                swings=self.swings,
                current_bar_index=current_idx,
                config=self.config.mss,
            )
        else:  # SHORT
            mss = detect_bearish_mss(
                bars=self.bars,
                sweep=self.context.sweep,
                swings=self.swings,
                current_bar_index=current_idx,
                config=self.config.mss,
            )

        if mss:
            self.context.mss = mss
            self.context.bars_since_mss = 0
            self.state = StrategyState.AWAITING_FVG

            if self.config.alert_on_mss:
                mss_type = "Bullish" if self.context.direction == "LONG" else "Bearish"
                pivot_type = "LH" if self.context.direction == "LONG" else "HL"
                self.logger.info(
                    f"{mss_type} MSS CONFIRMED: {bar.timestamp} | "
                    f"Broke {pivot_type} at {mss.lh_pivot.price:.2f}"
                )

            # Calculate OTE zone
            if self.context.direction == "LONG":
                # For longs: sweep_low as anchor, recent high as target
                swing_highs = get_recent_swing_highs(self.swings, max_count=3)
                if swing_highs:
                    recent_high = max(s.price for s in swing_highs)
                else:
                    recent_high = bar.high

                self.context.ote = calculate_ote_zone(
                    sweep_low=self.context.sweep.sweep_low,
                    swing_high=recent_high,
                    config=self.config.ote,
                )
            else:  # SHORT
                # For shorts: sweep_high as anchor, recent low as target
                swing_lows = get_recent_swing_lows(self.swings, max_count=3)
                if swing_lows:
                    recent_low = min(s.price for s in swing_lows)
                else:
                    recent_low = bar.low

                # For shorts, OTE zone is inverted - retracement from low toward high
                range_size = self.context.sweep.sweep_high - recent_low
                fib_62 = recent_low + (range_size * self.config.ote.ote_fib_lower)
                fib_79 = recent_low + (range_size * self.config.ote.ote_fib_upper)
                discount_50 = recent_low + (range_size * self.config.ote.discount_fib_max)

                self.context.ote = OTEZone(
                    swing_low=recent_low,
                    swing_high=self.context.sweep.sweep_high,
                    fib_62=fib_62,
                    fib_79=fib_79,
                    discount_50=discount_50
                )

        elif self.context.bars_since_sweep > self.config.mss.max_bars_after_sweep:
            # Timeout - reset
            self.state = StrategyState.SCANNING
            self.context.reset()

        return None

    def _state_awaiting_fvg(self, bar: Bar, current_idx: int) -> Optional[TradeSignal]:
        """AWAITING_FVG: Look for displacement + FVG."""

        self.context.bars_since_mss += 1

        # Check for displacement FVG
        displacement, fvg = detect_displacement_fvg(
            bars=self.bars,
            current_bar_index=current_idx,
            displacement_config=self.config.displacement,
            fvg_config=self.config.fvg,
            atr=self.atr,
        )

        # Match FVG direction to setup direction
        expected_fvg_dir = "BULLISH" if self.context.direction == "LONG" else "BEARISH"

        if fvg and fvg.direction == expected_fvg_dir:
            self.context.displacement = displacement
            self.context.fvg = fvg
            self.context.bars_since_fvg = 0
            self.active_fvgs.append(fvg)
            self.state = StrategyState.AWAITING_ENTRY

            self.logger.debug(
                f"{fvg.direction} FVG FORMED: {bar.timestamp} | "
                f"{fvg.bottom:.2f} - {fvg.top:.2f}"
            )

        # Timeout check
        if self.context.bars_since_mss > 30:  # Configurable
            self.state = StrategyState.SCANNING
            self.context.reset()

        return None

    def _state_awaiting_entry(self, bar: Bar, current_idx: int) -> Optional[TradeSignal]:
        """AWAITING_ENTRY: Wait for price to retrace into FVG."""

        self.context.bars_since_fvg += 1

        # Check if FVG is still valid
        if self.context.fvg.mitigated:
            self.state = StrategyState.SCANNING
            self.context.reset()
            return None

        # Check for entry
        entry_price = check_fvg_entry(
            fvg=self.context.fvg,
            current_bar=bar,
            config=self.config.fvg,
        )

        if entry_price:
            # Build trade signal
            signal = build_trade_signal(
                timestamp=bar.timestamp,
                symbol=self.config.symbol,
                sweep=self.context.sweep,
                mss=self.context.mss,
                fvg=self.context.fvg,
                ote=self.context.ote,
                current_bar=bar,
                swings=self.swings,
                atr=self.atr,
                equity=self.equity,
                config=self.config,
            )

            if signal:
                # Determine point value based on symbol (ES=$50, NQ=$20)
                point_value = 50.0 if self.config.symbol.upper() in ["ES", "ES1!"] else 20.0

                # Create open trade with proper tracking based on direction
                trade = OpenTrade(
                    signal=signal,
                    status=TradeStatus.OPEN,
                    entry_bar_index=current_idx,
                    entry_fill_price=signal.entry_price,
                    initial_contracts=signal.position_size,
                    remaining_contracts=signal.position_size,
                    current_stop=signal.stop_price,
                    current_targets=list(signal.targets),
                    highest_since_entry=bar.high if self.context.direction == "LONG" else 0.0,
                    lowest_since_entry=bar.low if self.context.direction == "SHORT" else 0.0,
                    point_value=point_value,
                )
                self.open_trades.append(trade)

                # Transition to IN_TRADE
                self.state = StrategyState.IN_TRADE
                self.trades_today += 1

                if self.config.alert_on_entry:
                    self.logger.info(
                        f"ENTRY: {signal.direction.value} {signal.position_size} @ "
                        f"{signal.entry_price:.2f} | SL={signal.stop_price:.2f}"
                    )

                # Mark FVG as used
                self.context.fvg.mitigated = True

                return signal

        # Timeout check
        if self.context.bars_since_fvg > self.config.fvg.max_bars_for_retrace:
            # FVG expired without entry
            check_fvg_mitigation(
                fvg=self.context.fvg,
                bars=self.bars,
                start_index=self.context.fvg.bar_index,
                current_index=current_idx,
            )
            self.state = StrategyState.SCANNING
            self.context.reset()

        return None

    def _state_in_trade(self, bar: Bar, current_idx: int) -> Optional[TradeSignal]:
        """IN_TRADE: Manage open position."""

        # Trade management is done in _manage_open_trades
        # Check if all trades are closed
        if not self.open_trades:
            self.state = StrategyState.COOLDOWN
            self.cooldown_bars_remaining = self.config.risk.cooldown_bars

        return None

    def _manage_open_trades(self, bar: Bar):
        """Update all open trades with current bar."""

        for trade in self.open_trades[:]:  # Copy list for safe removal
            events = update_trade(
                trade=trade,
                current_bar=bar,
                atr=self.atr,
                sl_config=self.config.stop_loss,
                tp_config=self.config.take_profit,
            )

            for event in events:
                self.logger.info(f"TRADE EVENT: {trade.signal.signal_id} - {event}")

            if trade.status == TradeStatus.CLOSED:
                self.open_trades.remove(trade)
                self.closed_trades.append(trade)

    def _passes_filters(self, bar: Bar) -> bool:
        """Check if current bar passes all filters."""

        # ATR volatility filter
        if len(self.bars) > 50:
            median_atr = self._calculate_median_atr()
            current_atr = self.atr

            if current_atr > median_atr * self.config.filters.max_atr_mult:
                return False  # Too volatile
            if current_atr < median_atr * self.config.filters.min_atr_mult:
                return False  # Too quiet

        # Daily loss limit
        if abs(self.daily_pnl) >= self.equity * self.config.risk.max_daily_loss_pct:
            return False

        return True

    def _calculate_median_atr(self) -> float:
        """Calculate median ATR over last 50 bars."""
        if len(self.bars) < 50:
            return self.atr

        atrs = []
        period = self.config.displacement.atr_period
        for i in range(max(0, len(self.bars) - 50), len(self.bars)):
            if i >= period:
                atr = calculate_atr(self.bars[:i+1], period)
                atrs.append(atr)

        if not atrs:
            return self.atr

        atrs.sort()
        n = len(atrs)
        if n % 2 == 0:
            return (atrs[n//2 - 1] + atrs[n//2]) / 2
        return atrs[n//2]


# =============================================================================
# FACTORY FUNCTION
# =============================================================================

def create_strategy(config_path: str = None, config: StrategyConfig = None, equity: float = 100000.0) -> ICTSweepOTEStrategy:
    """
    Create strategy instance from config.

    Args:
        config_path: Path to YAML config file
        config: StrategyConfig object (alternative to path)
        equity: Starting equity

    Returns:
        Configured ICTSweepOTEStrategy instance
    """
    if config is None:
        if config_path:
            from strategies.ict_sweep_ote.config import load_config_from_yaml
            config = load_config_from_yaml(config_path)
        else:
            config = StrategyConfig()

    return ICTSweepOTEStrategy(config=config, equity=equity)
