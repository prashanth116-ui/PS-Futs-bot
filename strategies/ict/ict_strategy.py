"""
ICT Strategy Implementation

Main strategy class that orchestrates ICT-based trading signals.
Combines multiple ICT concepts (liquidity sweeps, BOS, FVG, etc.)
to generate high-probability trade setups during optimal sessions.

Signal Flow:
    1. Session Filter - Only trade during killzones
    2. Sweep Detection - Identify liquidity grabs
    3. BOS Confirmation - Confirm direction after sweep
    4. FVG Entry - Enter at optimal price level
    5. Risk Approval - Validate with risk manager
    6. Signal Emission - Return approved signal

This file orchestrates the pipeline but does NOT implement
detection logic - that lives in sweep.py, bos.py, and fvg.py.
"""

import logging
from typing import TYPE_CHECKING

from core.types import Direction, EntryType, Signal
from strategies.base import Strategy
from strategies.ict.filters.session import (
    KillzoneWindow,
    current_session_label,
    is_in_killzone,
    parse_killzones,
)

# -----------------------------------------------------------------------------
# Import signal detection modules
# -----------------------------------------------------------------------------
from strategies.ict.signals.bos import (
    BOSEvent,
    detect_bos,
)
from strategies.ict.signals.fvg import (
    FVGZone,
    check_fvg_entry,
    detect_fvg_on_bar,
    get_active_fvgs,
    update_fvg_mitigation,
)
from strategies.ict.signals.sweep import (
    SessionLevels,
    SweepEvent,
    SwingPoint,
    detect_sweep_on_bar,
    find_swing_highs,
    find_swing_lows,
    get_most_significant_sweep,
    get_prior_session_levels,
)

if TYPE_CHECKING:
    from typing import Any

    from core.types import Bar
    from risk.risk_manager import AccountState, RiskManager

# Set up logging
logger = logging.getLogger(__name__)


class ICTStrategy(Strategy):
    """
    ICT (Inner Circle Trader) Strategy Implementation.

    This strategy combines multiple ICT concepts to identify high-probability
    trade setups:
        1. Session timing (London/NY opens, killzones)
        2. Liquidity sweeps (stop hunts above/below key levels)
        3. Break of Structure (BOS) for trend confirmation
        4. Fair Value Gaps (FVG) for optimal entry zones

    The strategy only trades during defined sessions and requires
    multiple confirmations before generating a signal.

    Signal Flow:
        Sweep Detected -> Store pending_sweep
        BOS Confirmed (after sweep) -> Store pending_bos, set bias
        FVG Entry Triggered (after BOS) -> Construct Signal
        Risk Approved -> Emit Signal

    Attributes:
        config: Strategy configuration loaded from YAML.
        instrument: Instrument specifications (tick_size, symbol, etc.).
        risk_manager: Reference to the risk manager for trade approval.
    """

    def __init__(
        self,
        config: dict,
        instrument: dict,
        risk_manager: "RiskManager | None" = None,
        account_state: "AccountState | None" = None,
    ) -> None:
        """
        Initialize the ICT Strategy.

        Args:
            config: Strategy configuration dictionary (typically from YAML).
            instrument: Instrument specifications dictionary.
            risk_manager: Optional risk manager for position sizing and approval.
            account_state: Optional account state for risk checks.
        """
        # Initialize base Strategy with name from config or default
        strategy_name = config.get("name", "ICT_Strategy")
        super().__init__(name=strategy_name, params=config)

        # Store configuration and dependencies
        self.config: dict = config
        self.instrument: dict = instrument
        self.risk_manager: "RiskManager | None" = risk_manager
        self.account_state: "AccountState | None" = account_state

        # -----------------------------------------------------------------
        # Parse and store killzones from config
        # -----------------------------------------------------------------
        self._killzones: list[KillzoneWindow] = self._build_killzones()

        # -----------------------------------------------------------------
        # Extract commonly used config values
        # -----------------------------------------------------------------
        self._tick_size: float = instrument.get("tick_size", 0.25)
        self._tick_value: float = instrument.get("tick_value", 12.50)
        self._symbol: str = instrument.get("symbol", "ES")

        # Swing detection parameters
        self._swing_left_bars: int = config.get("swing_left_bars", 3)
        self._swing_right_bars: int = config.get("swing_right_bars", 1)
        self._lookback_bars: int = config.get("lookback_bars", 20)

        # FVG parameters
        self._min_fvg_ticks: int = config.get("min_fvg_ticks", 2)
        self._max_fvg_age_bars: int = config.get("max_fvg_age_bars", 50)
        self._fvg_entry_mode: str = config.get("fvg_entry_mode", "MIDPOINT")

        # Stop/Target parameters
        self._stop_buffer_ticks: int = config.get("stop_buffer_ticks", 2)
        self._rr_targets: list[float] = config.get("rr_targets", [1.0, 2.0, 3.0])

        # -----------------------------------------------------------------
        # State variables
        # -----------------------------------------------------------------

        # Bar history for swing/level detection
        self._bars: list["Bar"] = []

        # Current session label (e.g., "NY_OPEN", "LONDON", "OFF")
        self.current_session: str = "OFF"

        # Track if we've already taken a trade this session
        self.has_traded_session: bool = False

        # Count of trades taken today
        self.trades_today: int = 0

        # Current detected bias (from BOS confirmation)
        self.current_bias: str | None = None

        # -----------------------------------------------------------------
        # Pending setup state (the ICT signal chain)
        # -----------------------------------------------------------------

        # Pending sweep waiting for BOS confirmation
        self.pending_sweep: SweepEvent | None = None

        # Confirmed BOS event (after sweep)
        self.pending_bos: BOSEvent | None = None

        # -----------------------------------------------------------------
        # Tracked zones
        # -----------------------------------------------------------------

        # All detected FVG zones (updated each bar)
        self._all_fvgs: list[FVGZone] = []

        # Pre-computed swing points (updated each bar)
        self._swing_highs: list[SwingPoint] = []
        self._swing_lows: list[SwingPoint] = []

        # Prior session levels
        self._prior_session: SessionLevels | None = None

    def reset_daily(self) -> None:
        """
        Reset all daily state at the start of a new trading day.

        Called automatically by the engine at the start of each session.
        Clears all accumulated state so each day starts fresh.
        """
        # -----------------------------------------------------------------
        # Reset trade tracking
        # -----------------------------------------------------------------
        self.has_traded_session = False
        self.trades_today = 0

        # -----------------------------------------------------------------
        # Reset market structure state
        # -----------------------------------------------------------------
        self.current_bias = None
        self.pending_sweep = None
        self.pending_bos = None

        # -----------------------------------------------------------------
        # Clear zones and history
        # -----------------------------------------------------------------
        self._all_fvgs = []
        self._bars = []
        self._swing_highs = []
        self._swing_lows = []
        self._prior_session = None

        # Reset session tracking
        self.current_session = "OFF"

        logger.info("ICTStrategy: Daily reset complete")

    def _build_killzones(self) -> list[KillzoneWindow]:
        """
        Build the list of killzone windows from config.

        Returns:
            List of parsed KillzoneWindow objects.
        """
        killzones_config = self.config.get("killzones", {})

        if not killzones_config:
            return []

        windows = parse_killzones(killzones_config)

        # Apply master toggle for London
        enable_london = self.config.get("enable_london_killzone", True)
        if not enable_london:
            for window in windows:
                if window.name == "LONDON":
                    window.enabled = False

        return windows

    def _build_detection_config(self) -> dict:
        """
        Build the config dict passed to detection functions.

        Returns:
            Configuration dictionary for sweep/bos/fvg detection.
        """
        return {
            # Common
            "tick_size": self._tick_size,
            # Swing detection
            "swing_left_bars": self._swing_left_bars,
            "swing_right_bars": self._swing_right_bars,
            "lookback_bars": self._lookback_bars,
            # Sweep detection
            "min_sweep_ticks": self.config.get("min_sweep_ticks", 2),
            "require_close_back_inside": self.config.get("require_close_back_inside", True),
            # BOS detection
            "allow_wick_break": False,  # Close-based only
            "min_displacement_ticks": self.config.get("min_displacement_ticks", 0),
            # FVG detection
            "min_fvg_ticks": self._min_fvg_ticks,
            "max_fvg_age_bars": self._max_fvg_age_bars,
            "entry_mode": self._fvg_entry_mode,
            "invalidate_on_close_through": self.config.get("invalidate_on_close_through", True),
        }

    def _update_swing_points(self) -> None:
        """
        Update swing highs and lows from bar history.

        Called each bar to keep swing points current for sweep detection.
        """
        if len(self._bars) < self._swing_left_bars + self._swing_right_bars + 1:
            return

        # Use lookback window for swing detection
        lookback_start = max(0, len(self._bars) - self._lookback_bars)
        lookback_bars = self._bars[lookback_start:]

        self._swing_highs = find_swing_highs(
            lookback_bars, self._swing_left_bars, self._swing_right_bars
        )
        self._swing_lows = find_swing_lows(
            lookback_bars, self._swing_left_bars, self._swing_right_bars
        )

    def _update_fvg_mitigations(self, bar: "Bar", bar_index: int) -> None:
        """
        Update mitigation status for all tracked FVGs.

        Args:
            bar: Current bar to check against.
            bar_index: Index of current bar.
        """
        config = self._build_detection_config()
        for fvg in self._all_fvgs:
            if not fvg.mitigated:
                update_fvg_mitigation(fvg, bar, bar_index, config)

    def _calculate_stop_price(
        self,
        direction: Direction,
        fvg: FVGZone,
    ) -> float:
        """
        Calculate stop price for a trade.

        Stop is placed behind the FVG zone with a buffer.

        Args:
            direction: Trade direction (LONG or SHORT).
            fvg: The FVG zone being entered.

        Returns:
            Stop price level.
        """
        buffer = self._stop_buffer_ticks * self._tick_size

        if direction == Direction.LONG:
            # For longs, stop below the FVG low
            return fvg.low - buffer
        else:
            # For shorts, stop above the FVG high
            return fvg.high + buffer

    def _calculate_targets(
        self,
        entry_price: float,
        stop_price: float,
        direction: Direction,
    ) -> list[float]:
        """
        Calculate take-profit targets based on R:R ratios.

        Formula: target = entry + direction * rr * (entry - stop)
        Where direction is +1 for LONG, -1 for SHORT.

        Args:
            entry_price: Entry price for the trade.
            stop_price: Stop loss price.
            direction: Trade direction.

        Returns:
            List of target prices rounded to tick size.
        """
        # Risk is the distance from entry to stop
        risk = abs(entry_price - stop_price)
        targets: list[float] = []

        # Direction multiplier: +1 for LONG (targets above entry), -1 for SHORT (targets below)
        dir_mult = 1.0 if direction == Direction.LONG else -1.0

        for rr in self._rr_targets:
            # target = entry + direction * rr * risk
            target = entry_price + dir_mult * rr * risk
            # Round to tick size
            targets.append(round(target / self._tick_size) * self._tick_size)

        return targets

    def _invalidate_pending_setup(self, reason: str) -> None:
        """
        Invalidate the current pending setup and reset state.

        Called when:
        - Setup times out (too many bars since sweep)
        - Price action invalidates the setup
        - After a signal is emitted

        Args:
            reason: Why the setup was invalidated (for logging).
        """
        if self.pending_sweep or self.pending_bos:
            logger.debug(f"ICTStrategy: Setup invalidated - {reason}")

        self.pending_sweep = None
        self.pending_bos = None
        self.current_bias = None

    def on_bar(self, bar: "Bar") -> list[Signal]:
        """
        Process a new price bar and check for ICT trade setups.

        This is the main entry point called for each new bar.
        It orchestrates the ICT signal chain:
            Sweep -> BOS -> FVG -> Signal

        Args:
            bar: The latest price bar with OHLCV data.

        Returns:
            List of Signal objects. Usually empty or contains one signal.
        """
        signals: list[Signal] = []

        # -----------------------------------------------------------------
        # STEP 0: UPDATE BAR HISTORY
        # -----------------------------------------------------------------
        # Store the bar for swing detection and other lookback calculations.
        # Limit history to avoid memory issues.
        # -----------------------------------------------------------------

        self._bars.append(bar)
        current_bar_index = len(self._bars) - 1

        # Trim history to max lookback + buffer
        max_history = self._lookback_bars * 3
        if len(self._bars) > max_history:
            trim_count = len(self._bars) - max_history
            self._bars = self._bars[trim_count:]
            current_bar_index = len(self._bars) - 1

        # -----------------------------------------------------------------
        # STEP 1: SESSION FILTER
        # -----------------------------------------------------------------
        # Check if we're in a valid trading session (killzone).
        # ICT methodology only trades during specific high-probability
        # windows: London Open, NY Open, etc.
        # -----------------------------------------------------------------

        # Update current session label (for logging and signal metadata)
        self.current_session = current_session_label(bar.timestamp, self._killzones)

        # If outside all killzones, skip processing
        if not is_in_killzone(bar.timestamp, self._killzones):
            # Optionally invalidate stale setups when session ends
            if self.pending_sweep:
                self._invalidate_pending_setup("Session ended")
            return signals

        # Skip if we've already traded this session (optional, configurable)
        max_trades_per_session = self.config.get("max_trades_per_session", 1)
        if self.has_traded_session and max_trades_per_session == 1:
            return signals

        # -----------------------------------------------------------------
        # STEP 2: UPDATE MARKET STRUCTURE
        # -----------------------------------------------------------------
        # Compute swing points and prior session levels for sweep detection.
        # These are pre-computed once per bar for efficiency.
        # -----------------------------------------------------------------

        self._update_swing_points()

        # Update prior session levels if we have enough history
        if len(self._bars) >= 2:
            self._prior_session = get_prior_session_levels(
                self._bars[:-1],  # Exclude current bar
                bar,
            )

        # Build detection config
        config = self._build_detection_config()

        # -----------------------------------------------------------------
        # STEP 3: UPDATE FVG ZONES
        # -----------------------------------------------------------------
        # Detect new FVGs and update mitigation status for existing ones.
        # -----------------------------------------------------------------

        # Check for new FVG on this bar
        new_fvg = detect_fvg_on_bar(self._bars, config)
        if new_fvg:
            self._all_fvgs.append(new_fvg)
            logger.debug(
                f"ICTStrategy: New {new_fvg.direction} FVG detected: "
                f"{new_fvg.low:.2f} - {new_fvg.high:.2f}"
            )

        # Update mitigation status for all FVGs
        self._update_fvg_mitigations(bar, current_bar_index)

        # -----------------------------------------------------------------
        # STEP 4: LIQUIDITY SWEEP DETECTION
        # -----------------------------------------------------------------
        # Look for liquidity sweeps (stop hunts) at key levels.
        # A sweep occurs when price takes out a swing high/low and reverses.
        #
        # If sweep detected -> Store as pending_sweep for BOS confirmation.
        # -----------------------------------------------------------------

        sweeps = detect_sweep_on_bar(
            current_bar=bar,
            current_bar_index=current_bar_index,
            swing_highs=self._swing_highs,
            swing_lows=self._swing_lows,
            prior_session=self._prior_session,
            config=config,
        )

        if sweeps:
            # Take the most significant sweep if multiple detected
            most_significant = get_most_significant_sweep(sweeps)
            if most_significant:
                self.pending_sweep = most_significant
                logger.info(
                    f"ICTStrategy: Sweep detected - {most_significant.direction} "
                    f"at {most_significant.swept_level:.2f} "
                    f"({most_significant.sweep_type})"
                )

        # -----------------------------------------------------------------
        # STEP 5: BOS (BREAK OF STRUCTURE) CONFIRMATION
        # -----------------------------------------------------------------
        # After a sweep, wait for Break of Structure to confirm reversal.
        # BOS occurs when price breaks a swing in the direction
        # OPPOSITE to the sweep direction.
        #
        # Sweep DOWN (bullish) -> Look for BULLISH BOS (break above swing high)
        # Sweep UP (bearish) -> Look for BEARISH BOS (break below swing low)
        #
        # If BOS confirmed -> Store as pending_bos, set current_bias.
        # -----------------------------------------------------------------

        if self.pending_sweep and not self.pending_bos:
            # Check for BOS that confirms the sweep
            bos = detect_bos(
                bars=self._bars,
                config=config,
                sweep_event=self.pending_sweep,
            )

            if bos and bos.confirms_sweep:
                self.pending_bos = bos
                self.current_bias = bos.direction  # "BULLISH" or "BEARISH"
                logger.info(
                    f"ICTStrategy: BOS confirmed - {bos.direction} "
                    f"broke {bos.broken_level:.2f} "
                    f"(displacement_ok={bos.displacement_ok})"
                )

            # Check for sweep timeout (invalidate if too many bars passed)
            max_bars_to_bos = self.config.get("max_bars_sweep_to_bos", 10)
            bars_since_sweep = current_bar_index - self.pending_sweep.bar_index
            if bars_since_sweep > max_bars_to_bos:
                self._invalidate_pending_setup(
                    f"Sweep timed out after {bars_since_sweep} bars"
                )
                return signals

        # -----------------------------------------------------------------
        # STEP 6: FVG ENTRY CHECK
        # -----------------------------------------------------------------
        # After BOS confirmation, look for price to enter an FVG zone.
        # The FVG must align with the current bias (direction).
        #
        # For BULLISH bias -> Look for entry in BULLISH FVG (price retracing down)
        # For BEARISH bias -> Look for entry in BEARISH FVG (price retracing up)
        #
        # If entry triggered -> Construct Signal.
        # -----------------------------------------------------------------

        if self.pending_bos and self.current_bias:
            # Get active (unmitigated, not expired) FVGs matching our bias
            active_fvgs = get_active_fvgs(self._all_fvgs, current_bar_index, config)

            # Filter to FVGs matching our bias direction
            matching_fvgs = [
                fvg for fvg in active_fvgs
                if fvg.direction == self.current_bias
            ]

            # Check each matching FVG for entry
            entry_fvg: FVGZone | None = None
            for fvg in matching_fvgs:
                if check_fvg_entry(bar, fvg, self._fvg_entry_mode):
                    entry_fvg = fvg
                    break  # Take the first valid entry

            if entry_fvg:
                logger.info(
                    f"ICTStrategy: FVG entry triggered - {entry_fvg.direction} FVG "
                    f"{entry_fvg.low:.2f} - {entry_fvg.high:.2f}"
                )

                # ---------------------------------------------------------
                # STEP 7: CONSTRUCT SIGNAL
                # ---------------------------------------------------------
                # Build the Signal object with all trade parameters.
                # ---------------------------------------------------------

                # Determine direction
                direction = (
                    Direction.LONG if self.current_bias == "BULLISH"
                    else Direction.SHORT
                )

                # Calculate entry price based on entry mode
                entry_price = entry_fvg.get_entry_price(self._fvg_entry_mode)

                # Calculate stop price (behind the FVG with buffer)
                stop_price = self._calculate_stop_price(direction, entry_fvg)

                # Calculate targets based on R:R ratios
                targets = self._calculate_targets(entry_price, stop_price, direction)

                # Build reason dict with all contributing factors
                # Includes: session, sweep, bos, fvg, liquidity, sdv
                reason = {
                    "session": self.current_session,
                    "sweep": (
                        f"{self.pending_sweep.direction} sweep at "
                        f"{self.pending_sweep.swept_level:.2f} "
                        f"({self.pending_sweep.sweep_type})"
                    ),
                    "bos": (
                        f"{self.pending_bos.direction} BOS at "
                        f"{self.pending_bos.broken_level:.2f}"
                    ),
                    "fvg": (
                        f"{entry_fvg.direction} FVG "
                        f"{entry_fvg.low:.2f} - {entry_fvg.high:.2f}, "
                        f"entry at {entry_price:.2f}"
                    ),
                    # Liquidity zone info (TODO: implement liquidity.py)
                    "liquidity": None,
                    # Standard deviation / volatility info (TODO: implement sdv.py)
                    "sdv": None,
                }

                # Create the Signal
                signal = Signal(
                    symbol=self._symbol,
                    direction=direction,
                    entry_type=EntryType.LIMIT,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    targets=targets,
                    time_in_force="DAY",
                    reason=reason,
                    tags=["ICT", self.current_session, self.pending_sweep.sweep_type],
                )

                # ---------------------------------------------------------
                # STEP 8: RISK APPROVAL
                # ---------------------------------------------------------
                # Before emitting, validate with risk manager.
                # Risk manager checks position limits, daily loss limits,
                # and calculates appropriate position size.
                # ---------------------------------------------------------

                if self.risk_manager and self.account_state:
                    approval = self.risk_manager.approve(signal, self.account_state)

                    if not approval.approved:
                        # Trade rejected by risk manager
                        logger.warning(
                            f"ICTStrategy: Signal rejected by risk manager - "
                            f"{approval.reason}"
                        )
                        # Invalidate setup after rejection
                        self._invalidate_pending_setup("Risk manager rejected")
                        return signals

                    # Use adjusted signal if provided
                    if approval.adjusted_signal:
                        signal = approval.adjusted_signal

                    logger.info(
                        f"ICTStrategy: Signal approved - "
                        f"risk=${approval.risk_amount:.2f}, "
                        f"contracts={approval.position_size}"
                    )

                # ---------------------------------------------------------
                # STEP 9: EMIT SIGNAL
                # ---------------------------------------------------------
                # All checks passed - add signal to return list.
                # Update internal state to prevent duplicate signals.
                # ---------------------------------------------------------

                signals.append(signal)

                # Update trade tracking
                self.has_traded_session = True
                self.trades_today += 1

                logger.info(
                    f"ICTStrategy: Signal emitted - {direction.value} "
                    f"entry={entry_price:.2f}, stop={stop_price:.2f}, "
                    f"targets={[f'{t:.2f}' for t in targets]}"
                )

                # Reset pending setup after signal emission
                self._invalidate_pending_setup("Signal emitted")

        return signals

    def on_fill(self, fill_event: "Any") -> None:
        """
        Handle order fill notifications.

        Called by the execution engine when our order is filled.
        Update internal state to track position and performance.

        Args:
            fill_event: Fill information from the execution engine.
        """
        # Log the fill
        logger.info(
            f"ICTStrategy: Fill received - {fill_event.side} "
            f"{fill_event.fill_qty} @ {fill_event.fill_price}"
        )

        # Note: Position tracking and P&L calculation would be
        # handled by a separate position manager or the execution engine.
        # This strategy focuses on signal generation only.

    def get_state_summary(self) -> dict:
        """
        Get a summary of current strategy state.

        Useful for debugging and monitoring.

        Returns:
            Dictionary with current state information.
        """
        return {
            "session": self.current_session,
            "has_traded_session": self.has_traded_session,
            "trades_today": self.trades_today,
            "current_bias": self.current_bias,
            "pending_sweep": (
                f"{self.pending_sweep.direction} at {self.pending_sweep.swept_level}"
                if self.pending_sweep else None
            ),
            "pending_bos": (
                f"{self.pending_bos.direction} at {self.pending_bos.broken_level}"
                if self.pending_bos else None
            ),
            "active_fvgs": len([f for f in self._all_fvgs if not f.mitigated]),
            "bars_in_history": len(self._bars),
            "swing_highs": len(self._swing_highs),
            "swing_lows": len(self._swing_lows),
        }
