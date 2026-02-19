"""
ICT Strategy Implementation

Main strategy class that orchestrates ICT-based trading signals.
Combines multiple ICT concepts (liquidity sweeps, BOS, FVG, etc.)
to generate high-probability trade setups during optimal sessions.

Complete Signal Flow:
    swingFound → liquidityDefined → sweepConfirmed → displacement
        → MSS → BOS → CISD → FVG → Entry

Each step must be validated before progressing to the next.
This file orchestrates the pipeline using the state machine.
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
    DisplacementFVG,
    check_fvg_entry,
    check_retest_eligible,
    check_retest_entry,
    detect_displacement_fvg,
    detect_fvg_on_bar,
    get_active_fvgs,
    update_fvg_mitigation,
)
from strategies.ict.signals.sweep import (
    KeyLiquidityLevels,
    SessionLevels,
    SweepEvent,
    SwingPoint,
    calculate_key_levels,
    detect_sweep_at_key_levels,
    detect_sweep_on_bar,
    find_swing_highs,
    find_swing_lows,
    get_most_significant_sweep,
    get_prior_session_levels,
)
from strategies.ict.signals.cisd import (
    CISDEvent,
    detect_cisd,
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
        stops_config = config.get("stops", {})
        self._min_stop_ticks: int = stops_config.get("min_stop_ticks", 10)
        self._cooldown_zone_ticks: int = stops_config.get("cooldown_zone_ticks", 20)
        self._rr_targets: list[float] = config.get("rr_targets", [1.0, 2.0, 3.0])

        # Risk parameters
        risk_config = config.get("risk", {})
        self._min_risk_reward: float = risk_config.get("min_risk_reward", 2.0)
        self._max_trades_per_day: int = risk_config.get("max_trades_per_day", 3)

        # Feature toggles
        self._enable_session_filter: bool = config.get("enable_session_filter", True)
        self._require_sweep: bool = config.get("require_sweep", True)
        self._require_bos: bool = config.get("require_bos", True)
        self._require_cisd: bool = config.get("require_cisd", False)
        self._require_fvg_after_cisd: bool = config.get("require_fvg_after_cisd", False)
        self._min_displacement_ticks: float = config.get("min_displacement_ticks", 4)

        # FVG Retest parameters
        self._enable_fvg_retest: bool = config.get("enable_fvg_retest", False)
        self._retest_min_displacement_ticks: float = config.get("retest_min_displacement_ticks", 8)
        self._retest_fvg_max_age_bars: int = config.get("retest_fvg_max_age_bars", 60)
        self._retest_min_move_away_ticks: float = config.get("retest_min_move_away_ticks", 8)
        self._retest_min_move_away_pct: float = config.get("retest_min_move_away_pct", 50)

        # Proactive liquidity detection parameters
        self._use_proactive_levels: bool = config.get("use_proactive_levels", True)
        self._enable_pdh_pdl: bool = config.get("enable_pdh_pdl", True)
        self._enable_overnight_levels: bool = config.get("enable_overnight_levels", True)
        self._enable_opening_range: bool = config.get("enable_opening_range", True)
        self._opening_range_minutes: int = config.get("opening_range_minutes", 15)

        # Trend filter parameters (EMA-based - can be disabled)
        self._enable_trend_filter: bool = config.get("enable_trend_filter", False)
        self._trend_ema_period: int = config.get("trend_ema_period", 20)
        self._trend_filter_mode: str = config.get("trend_filter_mode", "crossover")
        self._crossover_lookback_bars: int = config.get("crossover_lookback_bars", 10)
        self._current_ema: float | None = None
        self._ema_history: list[float] = []  # Track EMA values for crossover detection

        # ICT Premium/Discount filter parameters
        self._enable_pd_filter: bool = config.get("enable_premium_discount_filter", False)
        self._pd_lookback_bars: int = config.get("pd_lookback_bars", 100)
        self._pd_buffer_pct: float = config.get("pd_buffer_pct", 5)

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
        self.pending_cisd: CISDEvent | None = None

        # -----------------------------------------------------------------
        # Tracked zones
        # -----------------------------------------------------------------

        # All detected FVG zones (updated each bar)
        self._all_fvgs: list[FVGZone] = []

        # Displacement FVGs eligible for retest entries
        self._displacement_fvgs: list[DisplacementFVG] = []

        # Pre-computed swing points (updated each bar)
        self._swing_highs: list[SwingPoint] = []
        self._swing_lows: list[SwingPoint] = []

        # Prior session levels
        self._prior_session: SessionLevels | None = None

        # Proactive key liquidity levels (calculated at session start)
        self._key_levels: KeyLiquidityLevels | None = None
        self._key_levels_calculated: bool = False

        # Track last bar date for day change detection
        self._last_bar_date = None

        # Track recent entry zones to prevent re-entry in same area
        # List of (price, direction, bar_index) tuples
        self._recent_entries: list[tuple[float, str, int]] = []

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
        self.pending_cisd = None

        # -----------------------------------------------------------------
        # Clear zones and history
        # -----------------------------------------------------------------
        self._all_fvgs = []
        self._displacement_fvgs = []
        self._bars = []
        self._swing_highs = []
        self._swing_lows = []
        self._prior_session = None

        # Reset proactive key levels
        self._key_levels = None
        self._key_levels_calculated = False

        # Reset session tracking
        self.current_session = "OFF"
        self._last_bar_date = None

        # Clear recent entries
        self._recent_entries = []

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

    def _calculate_ema(self) -> float | None:
        """
        Calculate Exponential Moving Average from bar history.

        Returns:
            Current EMA value, or None if not enough bars.
        """
        if len(self._bars) < self._trend_ema_period:
            return None

        closes = [b.close for b in self._bars]

        # Calculate EMA using the standard formula
        multiplier = 2 / (self._trend_ema_period + 1)

        # Start with SMA for initial EMA
        ema = sum(closes[:self._trend_ema_period]) / self._trend_ema_period

        # Calculate EMA for remaining bars
        for close in closes[self._trend_ema_period:]:
            ema = (close * multiplier) + (ema * (1 - multiplier))

        return ema

    def _check_trend_filter(self, direction: "Direction", current_price: float) -> bool:
        """
        Check if trade direction aligns with trend using EMA crossover.

        Crossover mode: Only allow entry after price crosses EMA in signal direction.
        - LONG: Price must have crossed ABOVE EMA recently (bullish crossover)
        - SHORT: Price must have crossed BELOW EMA recently (bearish crossover)

        Args:
            direction: Proposed trade direction (LONG or SHORT).
            current_price: Current price to compare against EMA.

        Returns:
            True if trade is allowed, False if filtered out.
        """
        if not self._enable_trend_filter:
            return True

        if self._current_ema is None or len(self._bars) < self._crossover_lookback_bars:
            return True  # Not enough data yet, allow trade

        if self._trend_filter_mode == "crossover":
            # Check for EMA crossover in recent bars
            lookback = min(self._crossover_lookback_bars, len(self._bars) - 1, len(self._ema_history) - 1)

            if lookback < 2:
                return True  # Not enough history

            # Look for crossover in recent bars
            bullish_crossover = False
            bearish_crossover = False

            for i in range(1, lookback + 1):
                if i >= len(self._bars) or i >= len(self._ema_history):
                    break

                bar_idx = -i
                ema_idx = -i
                prev_bar_idx = -(i + 1)
                prev_ema_idx = -(i + 1)

                if abs(prev_ema_idx) > len(self._ema_history):
                    break

                curr_close = self._bars[bar_idx].close
                prev_close = self._bars[prev_bar_idx].close
                curr_ema = self._ema_history[ema_idx]
                prev_ema = self._ema_history[prev_ema_idx]

                # Bullish crossover: price was below EMA, now above
                if prev_close <= prev_ema and curr_close > curr_ema:
                    bullish_crossover = True

                # Bearish crossover: price was above EMA, now below
                if prev_close >= prev_ema and curr_close < curr_ema:
                    bearish_crossover = True

            if direction == Direction.LONG:
                if not bullish_crossover:
                    logger.debug(
                        f"ICTStrategy: LONG filtered - no bullish EMA crossover "
                        f"in last {lookback} bars"
                    )
                    return False
            else:
                if not bearish_crossover:
                    logger.debug(
                        f"ICTStrategy: SHORT filtered - no bearish EMA crossover "
                        f"in last {lookback} bars"
                    )
                    return False

            return True
        else:
            # Simple mode: just check price vs EMA
            if direction == Direction.LONG:
                if current_price < self._current_ema:
                    logger.debug(
                        f"ICTStrategy: LONG filtered - price {current_price:.2f} "
                        f"below EMA {self._current_ema:.2f}"
                    )
                    return False
            else:
                if current_price > self._current_ema:
                    logger.debug(
                        f"ICTStrategy: SHORT filtered - price {current_price:.2f} "
                        f"above EMA {self._current_ema:.2f}"
                    )
                    return False

            return True

    def _check_premium_discount_filter(self, direction: "Direction", current_price: float) -> bool:
        """
        Check if trade aligns with ICT Premium/Discount zones.

        Uses Prior Day High/Low (PDH/PDL) or Overnight levels as reference.
        This is the proper ICT approach - fixed levels, not rolling.

        ICT Rule:
        - Only LONG in Discount zone (below 50% of range) - buy low
        - Only SHORT in Premium zone (above 50% of range) - sell high

        Args:
            direction: Proposed trade direction (LONG or SHORT).
            current_price: Current price to check zone.

        Returns:
            True if trade is allowed, False if filtered out.
        """
        if not self._enable_pd_filter:
            return True

        # Use key levels (PDH/PDL or Overnight) as the range reference
        # This is the proper ICT approach - fixed levels from prior session
        if self._key_levels is None:
            return True  # No key levels yet, allow trade

        # Prefer PDH/PDL, fallback to Overnight levels
        range_high = self._key_levels.pdh or self._key_levels.overnight_high
        range_low = self._key_levels.pdl or self._key_levels.overnight_low

        if range_high is None or range_low is None:
            return True  # No reference levels, allow trade

        range_size = range_high - range_low

        if range_size < self._tick_size * 4:
            return True  # Range too small, allow trade

        # Calculate midpoint (equilibrium)
        midpoint = range_low + (range_size / 2)

        # Calculate buffer zone around midpoint
        buffer = range_size * (self._pd_buffer_pct / 100)
        premium_start = midpoint + buffer
        discount_end = midpoint - buffer

        # Check zone alignment
        if direction == Direction.LONG:
            # LONG only allowed in Discount (below midpoint - buffer)
            if current_price > discount_end:
                logger.debug(
                    f"ICTStrategy: LONG filtered - price {current_price:.2f} "
                    f"not in Discount (< {discount_end:.2f}) | Range: {range_low:.2f}-{range_high:.2f}"
                )
                return False
        else:
            # SHORT only allowed in Premium (above midpoint + buffer)
            if current_price < premium_start:
                logger.debug(
                    f"ICTStrategy: SHORT filtered - price {current_price:.2f} "
                    f"not in Premium (> {premium_start:.2f}) | Range: {range_low:.2f}-{range_high:.2f}"
                )
                return False

        return True

    def _check_cooldown_zone(self, direction: "Direction", entry_price: float, current_bar_index: int) -> bool:
        """
        Check if entry is in a cooldown zone from a recent trade.

        Prevents re-entering the same price area after being stopped out,
        which causes repeated losses in choppy conditions.

        Args:
            direction: Proposed trade direction.
            entry_price: Entry price to check.
            current_bar_index: Current bar index for age filtering.

        Returns:
            True if entry is allowed, False if in cooldown zone.
        """
        if not self._cooldown_zone_ticks:
            return True

        cooldown_distance = self._cooldown_zone_ticks * self._tick_size

        # Check against recent entries (same direction only)
        direction_str = direction.value
        for prev_price, prev_dir, prev_bar_idx in self._recent_entries:
            # Only compare same direction
            if prev_dir != direction_str:
                continue

            # Check if within cooldown zone
            if abs(entry_price - prev_price) < cooldown_distance:
                logger.debug(
                    f"ICTStrategy: Entry blocked - {direction_str} at {entry_price:.2f} "
                    f"in cooldown zone of {prev_dir} at {prev_price:.2f} "
                    f"(within {self._cooldown_zone_ticks} ticks)"
                )
                return False

        return True

    def _record_entry(self, entry_price: float, direction: "Direction", bar_index: int) -> None:
        """Record an entry for cooldown zone tracking."""
        self._recent_entries.append((entry_price, direction.value, bar_index))

        # Keep only recent entries (last 50)
        if len(self._recent_entries) > 50:
            self._recent_entries = self._recent_entries[-50:]

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
        entry_price: float | None = None,
        swept_level: float | None = None,
    ) -> float:
        """
        Calculate stop price for a trade.

        ICT approach: Place stop beyond the swept level (where liquidity was taken).
        Fallback to FVG boundary + buffer, with minimum distance enforcement.

        Args:
            direction: Trade direction (LONG or SHORT).
            fvg: The FVG zone being entered.
            entry_price: Optional entry price for minimum stop calculation.
            swept_level: Optional swept level (PDL/PDH/etc) to place stop beyond.

        Returns:
            Stop price level.
        """
        buffer = self._stop_buffer_ticks * self._tick_size
        min_stop_distance = self._min_stop_ticks * self._tick_size

        if direction == Direction.LONG:
            # ICT approach: Stop below the swept level (where liquidity was taken)
            if swept_level is not None:
                sweep_stop = swept_level - buffer
            else:
                sweep_stop = fvg.low - buffer

            # FVG-based stop (fallback)
            fvg_stop = fvg.low - buffer

            # Minimum distance stop
            min_stop = (entry_price - min_stop_distance) if entry_price else fvg_stop

            # Use the furthest (lowest) stop of all options
            return min(sweep_stop, fvg_stop, min_stop)
        else:
            # ICT approach: Stop above the swept level
            if swept_level is not None:
                sweep_stop = swept_level + buffer
            else:
                sweep_stop = fvg.high + buffer

            # FVG-based stop (fallback)
            fvg_stop = fvg.high + buffer

            # Minimum distance stop
            min_stop = (entry_price + min_stop_distance) if entry_price else fvg_stop

            # Use the furthest (highest) stop of all options
            return max(sweep_stop, fvg_stop, min_stop)

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
        if self.pending_sweep or self.pending_bos or self.pending_cisd:
            logger.debug(f"ICTStrategy: Setup invalidated - {reason}")

        self.pending_sweep = None
        self.pending_bos = None
        self.pending_cisd = None
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
        # STEP 0: CHECK FOR NEW DAY AND RESET DAILY STATE
        # -----------------------------------------------------------------
        # Detect when we move to a new trading day and reset daily counters.
        # This is important when processing historical data across multiple days.
        # -----------------------------------------------------------------

        current_date = bar.timestamp.date()
        if self._last_bar_date is not None and current_date != self._last_bar_date:
            # New day - reset daily state (but keep bar history and key levels)
            logger.debug(f"ICTStrategy: New day detected ({current_date}), resetting daily state")
            self.trades_today = 0
            self.has_traded_session = False
            self.pending_sweep = None
            self.pending_bos = None
            self.pending_cisd = None
            self.current_bias = None
            # Reset key levels for new day calculation
            self._key_levels = None
            self._key_levels_calculated = False

        self._last_bar_date = current_date

        # -----------------------------------------------------------------
        # STEP 0.5: UPDATE BAR HISTORY (always, even if trade limit reached)
        # -----------------------------------------------------------------
        # Store the bar for swing detection and other lookback calculations.
        # This must happen BEFORE trade limit check so history stays accurate.
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
        # STEP 1: CALCULATE KEY LEVELS (always, even if trade limit reached)
        # -----------------------------------------------------------------
        # Key levels must be calculated at RTH start for sweep detection.
        # This must happen BEFORE trade limit check.
        # -----------------------------------------------------------------

        from datetime import time as dt_time
        premarket_start = dt_time(4, 0)
        dt_time(9, 30)
        bar_time = bar.timestamp.time()

        if self._use_proactive_levels and not self._key_levels_calculated:
            # Calculate at premarket start (4:00 AM) to use key levels in premarket
            if len(self._bars) >= 50 and bar_time >= premarket_start:
                self._key_levels = calculate_key_levels(
                    bars=self._bars,
                    current_bar=bar,
                    opening_range_minutes=self._opening_range_minutes,
                )

                # Filter out disabled level types
                if self._key_levels:
                    if not self._enable_pdh_pdl:
                        self._key_levels.pdh = None
                        self._key_levels.pdl = None
                    if not self._enable_overnight_levels:
                        self._key_levels.overnight_high = None
                        self._key_levels.overnight_low = None
                    if not self._enable_opening_range:
                        self._key_levels.opening_range_high = None
                        self._key_levels.opening_range_low = None

                self._key_levels_calculated = True

                # Log the key levels
                if self._key_levels:
                    logger.info(
                        f"ICTStrategy: Key levels calculated - "
                        f"PDH={self._key_levels.pdh}, PDL={self._key_levels.pdl}, "
                        f"ON_H={self._key_levels.overnight_high}, ON_L={self._key_levels.overnight_low}"
                    )

        # -----------------------------------------------------------------
        # STEP 2: CHECK DAILY TRADE LIMIT (RTH trades only)
        # -----------------------------------------------------------------
        # Enforce max_trades_per_day from config to avoid overtrading.
        # Only apply during RTH (09:30-16:00) to avoid pre-market signals
        # blocking RTH trades.
        # Reset trades_today when RTH begins to count only RTH trades.
        # Note: Bar history and key levels were already updated above.
        # -----------------------------------------------------------------

        rth_end = dt_time(16, 0)
        is_session = premarket_start <= bar_time <= rth_end

        # Reset trade counter at session start (first premarket bar of the day)
        if is_session and not getattr(self, "_session_started_today", False):
            logger.debug(f"ICTStrategy: Session started, resetting trade counter (was {self.trades_today})")
            self.trades_today = 0
            self._session_started_today = True
        elif not is_session:
            self._session_started_today = False

        if is_session and self.trades_today >= self._max_trades_per_day:
            logger.debug(
                f"ICTStrategy: Daily trade limit reached ({self.trades_today}/{self._max_trades_per_day})"
            )
            return signals

        # -----------------------------------------------------------------
        # STEP 3: SESSION FILTER
        # -----------------------------------------------------------------
        # Check if we're in a valid trading session (killzone).
        # ICT methodology only trades during specific high-probability
        # windows: London Open, NY Open, etc.
        # -----------------------------------------------------------------

        # Update current session label (for logging and signal metadata)
        self.current_session = current_session_label(bar.timestamp, self._killzones)

        # If outside all killzones, skip processing (if session filter enabled)
        if self._enable_session_filter:
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

        # Update EMA for trend filter
        if self._enable_trend_filter:
            self._current_ema = self._calculate_ema()
            if self._current_ema is not None:
                self._ema_history.append(self._current_ema)
                # Keep history limited
                max_ema_history = self._crossover_lookback_bars + 10
                if len(self._ema_history) > max_ema_history:
                    self._ema_history = self._ema_history[-max_ema_history:]

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
        # STEP 3.5: DISPLACEMENT FVG DETECTION (for retest entries)
        # -----------------------------------------------------------------
        # Track FVGs created by strong displacement candles.
        # These are eligible for "return to origin" retest entries.
        # -----------------------------------------------------------------

        if self._enable_fvg_retest and len(self._bars) >= 3:
            # Check if previous bar was a displacement candle
            prev_bar = self._bars[-2]
            prev_bar_index = current_bar_index - 1
            body_size = abs(prev_bar.close - prev_bar.open)
            body_ticks = body_size / self._tick_size

            if body_ticks >= self._retest_min_displacement_ticks:
                # Strong displacement - check if it created an FVG
                retest_config = {
                    **config,
                    "retest_min_move_away_ticks": self._retest_min_move_away_ticks,
                    "retest_min_move_away_pct": self._retest_min_move_away_pct,
                    "retest_fvg_max_age_bars": self._retest_fvg_max_age_bars,
                }
                disp_fvg = detect_displacement_fvg(self._bars, prev_bar_index, retest_config)

                if disp_fvg:
                    self._displacement_fvgs.append(disp_fvg)
                    logger.info(
                        f"ICTStrategy: Displacement FVG detected - "
                        f"{disp_fvg.displacement_direction} at "
                        f"{disp_fvg.fvg.low:.2f} - {disp_fvg.fvg.high:.2f} "
                        f"(displacement: {disp_fvg.displacement_body_ticks:.1f} ticks)"
                    )

        # Update displacement FVGs - track price movement and eligibility
        for disp_fvg in self._displacement_fvgs:
            if not disp_fvg.fvg.mitigated:
                disp_fvg.update_price_extremes(bar, current_bar_index)
                retest_config = {
                    "tick_size": self._tick_size,
                    "retest_min_move_away_ticks": self._retest_min_move_away_ticks,
                    "retest_min_move_away_pct": self._retest_min_move_away_pct,
                    "retest_fvg_max_age_bars": self._retest_fvg_max_age_bars,
                }
                disp_fvg.retest_eligible = check_retest_eligible(disp_fvg, retest_config)

        # -----------------------------------------------------------------
        # STEP 4: LIQUIDITY SWEEP DETECTION (if enabled)
        # -----------------------------------------------------------------
        # Look for liquidity sweeps (stop hunts) at key levels.
        # A sweep occurs when price takes out a swing high/low and reverses.
        #
        # PROACTIVE approach: Pre-identify key levels (PDH, PDL, ON H/L)
        # at session start and watch for sweeps at those levels.
        #
        # If sweep detected -> Store as pending_sweep for BOS confirmation.
        # -----------------------------------------------------------------

        if self._require_sweep:
            sweeps: list[SweepEvent] = []

            # PROACTIVE: Check sweeps at pre-identified key levels first
            # (Key levels are calculated earlier in on_bar, before trade limit check)
            if self._use_proactive_levels and self._key_levels:
                key_sweeps = detect_sweep_at_key_levels(
                    bar=bar,
                    bar_index=current_bar_index,
                    key_levels=self._key_levels,
                    config=config,
                )
                sweeps.extend(key_sweeps)

            # REACTIVE: Also check swing-based sweeps as backup
            swing_sweeps = detect_sweep_on_bar(
                current_bar=bar,
                current_bar_index=current_bar_index,
                swing_highs=self._swing_highs,
                swing_lows=self._swing_lows,
                prior_session=self._prior_session,
                config=config,
            )
            sweeps.extend(swing_sweeps)

            if sweeps:
                # Take the most significant sweep if multiple detected
                most_significant = get_most_significant_sweep(sweeps)
                if most_significant:
                    # Key level sweeps (PRIOR_SESSION) should take priority over swing sweeps
                    # - Key level sweeps ALWAYS overwrite swing sweeps
                    # - Swing sweeps NEVER overwrite key level sweeps
                    should_update = True

                    if self.pending_sweep:
                        current_is_key_level = self.pending_sweep.sweep_type == "PRIOR_SESSION"
                        new_is_key_level = most_significant.sweep_type == "PRIOR_SESSION"

                        if new_is_key_level and not current_is_key_level:
                            # Key level sweep should overwrite swing sweep
                            logger.info(
                                f"ICTStrategy: Key level sweep {most_significant.swept_level:.2f} "
                                f"overwriting swing sweep {self.pending_sweep.swept_level:.2f}"
                            )
                            should_update = True
                        elif current_is_key_level and not new_is_key_level:
                            # Don't overwrite key level sweep with swing sweep
                            should_update = False
                            logger.debug(
                                f"ICTStrategy: Ignoring swing sweep {most_significant.swept_level:.2f}, "
                                f"keeping key level sweep {self.pending_sweep.swept_level:.2f}"
                            )

                    if should_update:
                        # Check if this is a new sweep (different level or direction)
                        is_new_sweep = (
                            self.pending_sweep is None
                            or self.pending_sweep.swept_level != most_significant.swept_level
                            or self.pending_sweep.direction != most_significant.direction
                        )

                        if is_new_sweep:
                            # Reset BOS/CISD for new sweep - we need fresh confirmations
                            if self.pending_bos:
                                logger.debug(
                                    f"ICTStrategy: New sweep detected, resetting pending BOS "
                                    f"(old: {self.pending_sweep.swept_level if self.pending_sweep else 'None'})"
                                )
                            self.pending_bos = None
                            self.pending_cisd = None

                        self.pending_sweep = most_significant
                        level_name = most_significant.metadata.get("level_name", most_significant.sweep_type)
                        logger.info(
                            f"ICTStrategy: Sweep detected - {most_significant.direction} "
                            f"at {most_significant.swept_level:.2f} "
                            f"({level_name})"
                        )

        # -----------------------------------------------------------------
        # STEP 5: BOS (BREAK OF STRUCTURE) CONFIRMATION (if sweep required)
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

        if self._require_sweep and self.pending_sweep and not self.pending_bos:
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
        # STEP 5.5: CISD (CHANGE IN STATE OF DELIVERY) DETECTION
        # -----------------------------------------------------------------
        # CISD confirms the market has shifted direction with displacement.
        # More stringent than BOS - requires a strong momentum candle.
        #
        # If CISD detected -> Store as pending_cisd
        # CISD may also create an FVG that we can use for entry.
        # -----------------------------------------------------------------

        if self._require_cisd and self.pending_sweep and not self.pending_cisd:
            cisd = detect_cisd(
                bars=self._bars,
                config=config,
                sweep_event=self.pending_sweep,
            )

            if cisd and cisd.confirmed:
                self.pending_cisd = cisd
                self.current_bias = cisd.direction
                logger.info(
                    f"ICTStrategy: CISD confirmed - {cisd.direction} "
                    f"displacement {cisd.displacement_size:.1f} ticks "
                    f"broke {cisd.broken_level:.2f}"
                )

                # If CISD created an FVG, add it to our FVG list
                if cisd.fvg_zone:
                    from strategies.ict.signals.fvg import FVGZone
                    cisd_fvg = FVGZone(
                        direction=cisd.direction,
                        low=cisd.fvg_zone[0],
                        high=cisd.fvg_zone[1],
                        midpoint=(cisd.fvg_zone[0] + cisd.fvg_zone[1]) / 2,
                        created_at=cisd.timestamp,
                        created_bar_index=cisd.displacement_bar_index,
                        metadata={"source": "CISD"},
                    )
                    self._all_fvgs.append(cisd_fvg)
                    logger.info(
                        f"ICTStrategy: CISD created FVG - "
                        f"{cisd_fvg.low:.2f} to {cisd_fvg.high:.2f}"
                    )

        # -----------------------------------------------------------------
        # STEP 5.8: FVG RETEST ENTRY CHECK
        # -----------------------------------------------------------------
        # Check for "return to origin" retest entries on displacement FVGs.
        # This catches setups where:
        #   1. Strong displacement created an FVG
        #   2. Price moved away (retraced against the displacement)
        #   3. Price now returns to the FVG zone
        #   4. Entry in the direction of original displacement
        # -----------------------------------------------------------------

        if self._enable_fvg_retest:
            for disp_fvg in self._displacement_fvgs:
                # Skip if already triggered or FVG already used
                if disp_fvg.retest_triggered or disp_fvg.fvg.mitigated:
                    continue
                if disp_fvg.retest_eligible:
                    if check_retest_entry(bar, disp_fvg, self._fvg_entry_mode):
                        disp_fvg.retest_triggered = True

                        # Set bias from displacement direction
                        self.current_bias = disp_fvg.displacement_direction

                        direction = (
                            Direction.LONG if self.current_bias == "BULLISH"
                            else Direction.SHORT
                        )

                        entry_fvg = disp_fvg.fvg
                        entry_price = entry_fvg.get_entry_price(self._fvg_entry_mode)
                        # Use swept level for stop if available
                        swept_level = self.pending_sweep.swept_level if self.pending_sweep else None
                        stop_price = self._calculate_stop_price(direction, entry_fvg, entry_price, swept_level)
                        targets = self._calculate_targets(entry_price, stop_price, direction)

                        reason = {
                            "session": self.current_session,
                            "setup_type": "FVG_RETEST",
                            "displacement": (
                                f"{disp_fvg.displacement_direction} displacement "
                                f"{disp_fvg.displacement_body_ticks:.1f} ticks"
                            ),
                            "fvg": (
                                f"{entry_fvg.direction} FVG "
                                f"{entry_fvg.low:.2f} - {entry_fvg.high:.2f}"
                            ),
                            "retest": (
                                f"Price retraced {disp_fvg.bars_since_displacement} bars, "
                                f"now returning to FVG"
                            ),
                        }

                        tags = ["ICT", "FVG_RETEST", self.current_session]

                        # Check trend filter - only trade with the trend
                        if not self._check_trend_filter(direction, bar.close):
                            continue

                        # Check ICT Premium/Discount filter
                        if not self._check_premium_discount_filter(direction, bar.close):
                            continue

                        # Check cooldown zone - prevent re-entry in same price area
                        if not self._check_cooldown_zone(direction, entry_price, current_bar_index):
                            continue

                        # Check minimum R:R requirement (use second target as primary)
                        risk = abs(entry_price - stop_price)
                        # Use second target if available, else first target
                        primary_target = targets[1] if len(targets) > 1 else targets[0] if targets else entry_price
                        reward = abs(primary_target - entry_price)
                        actual_rr = reward / risk if risk > 0 else 0

                        if actual_rr < self._min_risk_reward:
                            logger.debug(
                                f"ICTStrategy: FVG RETEST skipped - R:R {actual_rr:.2f} "
                                f"below minimum {self._min_risk_reward}"
                            )
                            continue

                        signal = Signal(
                            symbol=self._symbol,
                            direction=direction,
                            entry_type=EntryType.LIMIT,
                            entry_price=entry_price,
                            stop_price=stop_price,
                            targets=targets,
                            time_in_force="DAY",
                            reason=reason,
                            tags=tags,
                        )

                        logger.info(
                            f"ICTStrategy: FVG RETEST entry (R:R={actual_rr:.2f}) - {direction.value} "
                            f"at {entry_price:.2f}, stop={stop_price:.2f} "
                            f"(displacement FVG from bar {disp_fvg.displacement_bar_index})"
                        )

                        signals.append(signal)
                        self.has_traded_session = True
                        self.trades_today += 1

                        # Record entry for cooldown zone tracking
                        self._record_entry(entry_price, direction, current_bar_index)

                        # Mark FVG as used
                        entry_fvg.mitigated = True
                        entry_fvg.mitigation_bar_index = current_bar_index

                        # Mark all overlapping displacement FVGs as triggered
                        for other_fvg in self._displacement_fvgs:
                            if not other_fvg.retest_triggered:
                                # Check if FVGs overlap (within 2 ticks)
                                overlap_threshold = 2 * self._tick_size
                                if (abs(other_fvg.fvg.midpoint - entry_fvg.midpoint) < overlap_threshold
                                    and other_fvg.displacement_direction == disp_fvg.displacement_direction):
                                    other_fvg.retest_triggered = True
                                    other_fvg.fvg.mitigated = True

                        # Only take one retest entry per bar
                        break

        # If we got a retest signal, return early
        if signals:
            return signals

        # -----------------------------------------------------------------
        # STEP 6: FVG ENTRY CHECK
        # -----------------------------------------------------------------
        # If sweep/BOS required: After BOS confirmation, look for FVG entry.
        # If sweep not required: Look for any FVG entry directly.
        #
        # The FVG must align with the current bias (direction).
        #
        # For BULLISH bias -> Look for entry in BULLISH FVG (price retracing down)
        # For BEARISH bias -> Look for entry in BEARISH FVG (price retracing up)
        #
        # If entry triggered -> Construct Signal.
        # -----------------------------------------------------------------

        # Determine if we should check for FVG entry
        check_fvg = False
        if self._require_sweep:
            if self._require_cisd:
                # Need sweep + CISD confirmation
                if self.pending_cisd and self.current_bias:
                    check_fvg = True
            else:
                # Need sweep + BOS confirmation first
                if self.pending_bos and self.current_bias:
                    check_fvg = True
        else:
            # No sweep required - check FVG directly (both directions)
            check_fvg = True

        if check_fvg:
            # Get active (unmitigated, not expired) FVGs
            active_fvgs = get_active_fvgs(self._all_fvgs, current_bar_index, config)

            # Filter to FVGs matching our bias direction (if we have a bias)
            if self.current_bias:
                matching_fvgs = [
                    fvg for fvg in active_fvgs
                    if fvg.direction == self.current_bias
                ]
            else:
                # No bias set (sweep not required) - check all active FVGs
                matching_fvgs = active_fvgs

            # If require_fvg_after_cisd, only consider FVGs formed after CISD
            if self._require_fvg_after_cisd and self.pending_cisd:
                cisd_bar_index = self.pending_cisd.displacement_bar_index
                matching_fvgs = [
                    fvg for fvg in matching_fvgs
                    if fvg.created_bar_index >= cisd_bar_index
                ]

            # Check each matching FVG for entry
            entry_fvg: FVGZone | None = None
            for fvg in matching_fvgs:
                if check_fvg_entry(bar, fvg, self._fvg_entry_mode):
                    entry_fvg = fvg
                    # Set bias from FVG direction if not already set
                    if not self.current_bias:
                        self.current_bias = fvg.direction
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

                # Calculate stop price - ICT approach: beyond swept level
                swept_level = self.pending_sweep.swept_level if self.pending_sweep else None
                stop_price = self._calculate_stop_price(direction, entry_fvg, entry_price, swept_level)

                # Calculate targets based on R:R ratios
                targets = self._calculate_targets(entry_price, stop_price, direction)

                # Check trend filter - only trade with the trend
                if not self._check_trend_filter(direction, bar.close):
                    ema_str = f"{self._current_ema:.2f}" if self._current_ema else "N/A"
                    logger.debug(
                        f"ICTStrategy: FVG entry skipped - {direction.value} "
                        f"against trend (EMA={ema_str})"
                    )
                    # Mark FVG as used to prevent repeated checks
                    entry_fvg.mitigated = True
                    entry_fvg.mitigation_bar_index = current_bar_index
                    return signals

                # Check ICT Premium/Discount filter
                if not self._check_premium_discount_filter(direction, bar.close):
                    logger.debug(
                        f"ICTStrategy: FVG entry skipped - {direction.value} "
                        f"not in correct zone (Premium/Discount)"
                    )
                    # Mark FVG as used to prevent repeated checks
                    entry_fvg.mitigated = True
                    entry_fvg.mitigation_bar_index = current_bar_index
                    return signals

                # Check cooldown zone - prevent re-entry in same price area
                if not self._check_cooldown_zone(direction, entry_price, current_bar_index):
                    logger.debug(
                        f"ICTStrategy: FVG entry skipped - {direction.value} "
                        f"at {entry_price:.2f} in cooldown zone"
                    )
                    # Mark FVG as used to prevent repeated checks
                    entry_fvg.mitigated = True
                    entry_fvg.mitigation_bar_index = current_bar_index
                    return signals

                # Check minimum R:R requirement (use second target as primary)
                risk = abs(entry_price - stop_price)
                # Use second target if available, else first target
                primary_target = targets[1] if len(targets) > 1 else targets[0] if targets else entry_price
                reward = abs(primary_target - entry_price)
                actual_rr = reward / risk if risk > 0 else 0

                if actual_rr < self._min_risk_reward:
                    logger.debug(
                        f"ICTStrategy: FVG entry skipped - R:R {actual_rr:.2f} "
                        f"below minimum {self._min_risk_reward}"
                    )
                    # Mark FVG as used to prevent repeated checks
                    entry_fvg.mitigated = True
                    entry_fvg.mitigation_bar_index = current_bar_index
                    return signals

                # Build reason dict with all contributing factors
                # Includes: session, sweep, bos, cisd, fvg, liquidity, sdv
                reason = {
                    "session": self.current_session,
                    "sweep": (
                        f"{self.pending_sweep.direction} sweep at "
                        f"{self.pending_sweep.swept_level:.2f} "
                        f"({self.pending_sweep.sweep_type})"
                    ) if self.pending_sweep else "N/A (disabled)",
                    "bos": (
                        f"{self.pending_bos.direction} BOS at "
                        f"{self.pending_bos.broken_level:.2f}"
                    ) if self.pending_bos else "N/A (disabled)",
                    "cisd": (
                        f"{self.pending_cisd.direction} CISD "
                        f"{self.pending_cisd.displacement_size:.1f} ticks "
                        f"at {self.pending_cisd.broken_level:.2f}"
                    ) if self.pending_cisd else "N/A (disabled)",
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

                # Build tags
                tags = ["ICT", self.current_session]
                if self.pending_sweep:
                    tags.append(self.pending_sweep.sweep_type)
                else:
                    tags.append("FVG_ONLY")

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
                    tags=tags,
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

                # Record entry for cooldown zone tracking
                self._record_entry(entry_price, direction, current_bar_index)

                logger.info(
                    f"ICTStrategy: Signal emitted - {direction.value} "
                    f"entry={entry_price:.2f}, stop={stop_price:.2f}, "
                    f"targets={[f'{t:.2f}' for t in targets]}"
                )

                # Mark the FVG as used (mitigated) to prevent duplicate signals
                entry_fvg.mitigated = True
                entry_fvg.mitigation_bar_index = current_bar_index

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
