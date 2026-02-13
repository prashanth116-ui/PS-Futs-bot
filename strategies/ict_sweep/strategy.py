"""
ICT Liquidity Sweep Strategy

Entry Logic:
1. Liquidity Sweep - Price sweeps swing high/low (stop hunt)
2. Displacement - Strong rejection candle after sweep
3. FVG Forms - Fair Value Gap created during displacement
4. FVG Mitigation - Price retraces into FVG zone
5. LTF MSS Confirms - Market Structure Shift on lower timeframe

Exit Logic:
- Stop: Beyond sweep point + buffer
- T1: 2R (partial)
- T2: 4R (partial)
- Runner: Opposing liquidity or EOD
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from strategies.ict_sweep.signals.liquidity import find_liquidity_levels, SwingPoint
from strategies.ict_sweep.signals.sweep import detect_sweep, Sweep
from strategies.ict_sweep.signals.fvg import detect_fvg, check_fvg_mitigation, is_price_in_fvg, FVG
from strategies.ict_sweep.signals.mss import detect_mss, MSS
from strategies.ict_sweep.filters.displacement import calculate_avg_body, check_displacement, get_displacement_ratio
from strategies.ict_sweep.filters.session import should_trade, get_session_name


@dataclass
class PendingSweep:
    """Tracks a sweep awaiting FVG formation."""
    sweep: Sweep
    displacement_ratio: float
    created_at_index: int
    max_fvg_wait_bars: int = 10  # Max bars to wait for FVG


@dataclass
class SetupState:
    """Tracks the state of a potential trade setup."""
    sweep: Optional[Sweep] = None
    fvg: Optional[FVG] = None
    displacement_bar_index: Optional[int] = None
    displacement_ratio: float = 0.0
    awaiting_mitigation: bool = False
    awaiting_mss: bool = False
    created_at_index: int = 0
    # MSS target level (locked in at mitigation)
    mss_break_level: Optional[float] = None


@dataclass
class TradeSetup:
    """A confirmed trade setup ready for entry."""
    direction: str  # 'LONG' or 'SHORT'
    entry_price: float
    stop_price: float
    t1_price: float  # 2R target
    t2_price: float  # 4R target
    runner_target: Optional[float]  # Opposing liquidity
    risk_ticks: float
    sweep: Sweep
    fvg: FVG
    mss: MSS
    bar_index: int
    timestamp: datetime


class ICTSweepStrategy:
    """
    ICT Liquidity Sweep Strategy Implementation.

    Uses HTF (5m) for setup detection and LTF (1m) for entry confirmation.
    """

    def __init__(self, config: dict):
        """
        Initialize strategy with configuration.

        Args:
            config: Strategy configuration dictionary
        """
        self.config = config

        # Instrument settings
        self.symbol = config.get('symbol', 'ES')
        self.tick_size = config.get('tick_size', 0.25)
        self.tick_value = config.get('tick_value', 12.50)

        # Liquidity detection
        self.swing_lookback = config.get('swing_lookback', 20)
        self.swing_strength = config.get('swing_strength', 3)

        # Sweep detection
        self.min_sweep_ticks = config.get('min_sweep_ticks', 2)
        self.max_sweep_ticks = config.get('max_sweep_ticks', 20)

        # Displacement
        self.displacement_multiplier = config.get('displacement_multiplier', 2.0)
        self.avg_body_lookback = config.get('avg_body_lookback', 20)

        # FVG
        self.min_fvg_ticks = config.get('min_fvg_ticks', 5)
        self.max_fvg_age_bars = config.get('max_fvg_age_bars', 50)

        # MSS (LTF)
        self.mss_lookback = config.get('mss_lookback', 10)
        self.mss_swing_strength = config.get('mss_swing_strength', 2)

        # Risk management
        self.stop_buffer_ticks = config.get('stop_buffer_ticks', 2)
        self.max_risk_ticks = config.get('max_risk_ticks', 40)

        # Session filters
        self.allow_lunch = config.get('allow_lunch', False)
        self.require_killzone = config.get('require_killzone', False)

        # State
        self.htf_bars = []      # 5m bars for sweep detection
        self.mtf_bars = []      # 3m bars for FVG detection (optional)
        self.ltf_bars = []      # 1m/3m bars for MSS confirmation
        self.avg_body = 0.0
        self.active_setup: Optional[SetupState] = None
        self.pending_sweeps: list[PendingSweep] = []  # Sweeps awaiting FVG
        self.pending_setups: list[SetupState] = []    # Setups awaiting mitigation
        self.daily_trades = 0
        self.daily_losses = 0
        self.max_daily_trades = config.get('max_daily_trades', 5)
        self.max_daily_losses = config.get('max_daily_losses', 2)
        self.use_mtf_for_fvg = config.get('use_mtf_for_fvg', False)  # Use 3m for FVG
        self.entry_on_mitigation = config.get('entry_on_mitigation', False)  # Enter on FVG tap
        self.stop_buffer_pts = config.get('stop_buffer_pts', 2.0)  # Stop buffer in points

        # Trend filter settings
        self.use_trend_filter = config.get('use_trend_filter', False)
        self.ema_fast_period = config.get('ema_fast_period', 20)
        self.ema_slow_period = config.get('ema_slow_period', 50)

    def reset_daily(self):
        """Reset state for a new trading day."""
        self.htf_bars = []
        self.mtf_bars = []
        self.ltf_bars = []
        self.avg_body = 0.0
        self.active_setup = None
        self.pending_sweeps = []
        self.pending_setups = []
        self.daily_trades = 0
        self.daily_losses = 0

    def update_mtf(self, bar):
        """
        Process a new MTF (3m) bar for FVG detection.

        Args:
            bar: New 3m price bar
        """
        self.mtf_bars.append(bar)

    def update_htf(self, bar) -> Optional[SetupState]:
        """
        Process a new HTF bar and check for setup conditions.

        Two-phase detection:
        1. Check pending sweeps for FVG formation
        2. Check for new sweeps with displacement

        Args:
            bar: New HTF price bar

        Returns:
            SetupState if a new setup is detected
        """
        self.htf_bars.append(bar)
        bar_index = len(self.htf_bars) - 1

        # Need minimum bars for analysis
        if len(self.htf_bars) < self.swing_lookback + self.swing_strength + 5:
            return None

        # Update average body
        self.avg_body = calculate_avg_body(self.htf_bars, self.avg_body_lookback)

        # Check session filter
        if not should_trade(bar.timestamp, self.allow_lunch, self.require_killzone):
            return None

        # Check daily limits
        if self.daily_trades >= self.max_daily_trades:
            return None
        if self.daily_losses >= self.max_daily_losses:
            return None

        # Phase 1: Check pending sweeps for FVG formation
        setup = self._check_pending_sweeps_for_fvg(bar_index)
        if setup:
            return setup

        # Phase 2: Check for new sweeps
        sweep = detect_sweep(
            self.htf_bars,
            self.tick_size,
            self.swing_strength,
            self.min_sweep_ticks,
            check_bars=3
        )

        if not sweep:
            return None

        # Validate sweep depth
        if sweep.sweep_depth_ticks > self.max_sweep_ticks:
            return None

        # Check for displacement on sweep bar or recent bars
        sweep_bar = self.htf_bars[sweep.bar_index]
        disp_ratio = get_displacement_ratio(sweep_bar, self.avg_body)

        if disp_ratio < self.displacement_multiplier:
            # Check previous bar too
            if sweep.bar_index > 0:
                prev_bar = self.htf_bars[sweep.bar_index - 1]
                disp_ratio = get_displacement_ratio(prev_bar, self.avg_body)

            if disp_ratio < self.displacement_multiplier:
                return None

        # Check if we already have a pending sweep for this direction
        existing = [ps for ps in self.pending_sweeps if ps.sweep.sweep_type == sweep.sweep_type]
        if existing:
            return None  # Already tracking a sweep for this direction

        # DEBUG
        # print(f'DEBUG: Sweep {sweep.sweep_type} found, checking FVG...')

        # Check for FVG immediately
        fvg = self._find_fvg_for_sweep(sweep)

        if fvg:
            # Create setup state - awaiting mitigation
            setup = SetupState(
                sweep=sweep,
                fvg=fvg,
                displacement_bar_index=sweep.bar_index,
                displacement_ratio=disp_ratio,
                awaiting_mitigation=True,
                awaiting_mss=False,
                created_at_index=bar_index
            )
            self.pending_setups.append(setup)
            return setup
        else:
            # No FVG yet - store sweep and wait
            pending = PendingSweep(
                sweep=sweep,
                displacement_ratio=disp_ratio,
                created_at_index=bar_index,
                max_fvg_wait_bars=10
            )
            self.pending_sweeps.append(pending)
            return None

    def _check_pending_sweeps_for_fvg(self, bar_index: int) -> Optional[SetupState]:
        """Check if any pending sweep now has an FVG."""
        for pending in self.pending_sweeps[:]:
            # Remove stale pending sweeps
            age = bar_index - pending.created_at_index
            if age > pending.max_fvg_wait_bars:
                self.pending_sweeps.remove(pending)
                continue

            # Check for FVG
            fvg = self._find_fvg_for_sweep(pending.sweep)
            if fvg:
                # FVG found! Create setup
                setup = SetupState(
                    sweep=pending.sweep,
                    fvg=fvg,
                    displacement_bar_index=pending.sweep.bar_index,
                    displacement_ratio=pending.displacement_ratio,
                    awaiting_mitigation=True,
                    awaiting_mss=False,
                    created_at_index=bar_index
                )
                self.pending_sweeps.remove(pending)
                self.pending_setups.append(setup)
                return setup

        return None

    def _find_fvg_for_sweep(self, sweep: Sweep) -> Optional[FVG]:
        """Find FVG for a sweep in the bars after it.

        Checks HTF (5m) bars first, then MTF (3m) if enabled.
        """
        expected_dir = sweep.sweep_type
        sweep_time = self.htf_bars[sweep.bar_index].timestamp

        # First check HTF (5m) bars
        for offset in range(0, 10):
            if sweep.bar_index + offset + 2 < len(self.htf_bars):
                window_start = sweep.bar_index + offset
                window = self.htf_bars[window_start:window_start + 3]
                if len(window) >= 3:
                    fvg = detect_fvg(window, self.tick_size, self.min_fvg_ticks, expected_dir)
                    if fvg:
                        fvg.bar_index = window_start + 1
                        return fvg

        # If MTF enabled, check 3m bars for FVG
        if self.use_mtf_for_fvg and len(self.mtf_bars) >= 3:
            # Find MTF bars after sweep time
            mtf_after_sweep = [i for i, b in enumerate(self.mtf_bars)
                              if b.timestamp >= sweep_time]

            if mtf_after_sweep:
                start_idx = mtf_after_sweep[0]
                # Check windows starting from sweep time
                for offset in range(0, 15):  # Check more bars on 3m
                    window_start = start_idx + offset
                    if window_start + 2 < len(self.mtf_bars):
                        window = self.mtf_bars[window_start:window_start + 3]
                        if len(window) >= 3:
                            fvg = detect_fvg(window, self.tick_size, self.min_fvg_ticks, expected_dir)
                            if fvg:
                                fvg.bar_index = window_start + 1
                                return fvg

        return None

    def check_htf_mitigation(self, bar):
        """
        Check if any pending setups have their FVG mitigated.

        Args:
            bar: Current HTF bar

        Returns:
            If entry_on_mitigation=True: TradeSetup or None
            If entry_on_mitigation=False: List of setups awaiting MSS
        """
        from strategies.ict_sweep.signals.mss import find_recent_swing_high, find_recent_swing_low

        ready_for_mss = []
        bar_index = len(self.htf_bars) - 1

        for setup in self.pending_setups[:]:
            if not setup.awaiting_mitigation:
                continue

            # Check if FVG is mitigated (price enters FVG zone)
            if check_fvg_mitigation(setup.fvg, bar, bar_index):
                setup.awaiting_mitigation = False

                # If entry_on_mitigation, create trade immediately
                if self.entry_on_mitigation:
                    trade = self._create_trade_on_mitigation(setup, bar)
                    if trade:
                        self.pending_setups.remove(setup)
                        self.daily_trades += 1
                        return trade
                else:
                    # Wait for MSS confirmation
                    setup.awaiting_mss = True

                    # Lock in the MSS break level at this moment
                    if setup.sweep.sweep_type == 'BEARISH':
                        swing = find_recent_swing_low(self.htf_bars, bar_index, 20, 2)
                        if swing:
                            setup.mss_break_level = swing[1]
                    else:
                        swing = find_recent_swing_high(self.htf_bars, bar_index, 20, 2)
                        if swing:
                            setup.mss_break_level = swing[1]

                    ready_for_mss.append(setup)

            # Remove stale setups
            age = bar_index - setup.created_at_index
            if age > self.max_fvg_age_bars:
                self.pending_setups.remove(setup)

        return ready_for_mss if not self.entry_on_mitigation else None

    def _create_trade_on_mitigation(self, setup: SetupState, bar) -> Optional[TradeSetup]:
        """Create trade on FVG mitigation (tap entry)."""
        direction = setup.sweep.sweep_type
        fvg = setup.fvg

        # Check trend filter - skip counter-trend trades
        if not self._check_trend_filter(direction):
            return None

        # Entry at FVG midpoint or current close
        entry_price = bar.close

        # Stop above/below FVG + buffer
        if direction == 'BEARISH':
            stop_price = fvg.top + self.stop_buffer_pts
            risk = stop_price - entry_price
        else:
            stop_price = fvg.bottom - self.stop_buffer_pts
            risk = entry_price - stop_price

        risk_ticks = risk / self.tick_size

        # Validate risk
        if risk_ticks <= 0 or risk_ticks > self.max_risk_ticks:
            return None

        # Calculate targets (4R)
        if direction == 'BEARISH':
            t1_price = entry_price - (risk * 2)
            t2_price = entry_price - (risk * 4)
        else:
            t1_price = entry_price + (risk * 2)
            t2_price = entry_price + (risk * 4)

        # Create MSS placeholder (not used for mitigation entry)
        mss = MSS(
            mss_type=direction,
            break_price=entry_price,
            confirmation_price=entry_price,
            bar_index=len(self.htf_bars) - 1,
            timestamp=bar.timestamp
        )

        return TradeSetup(
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            t1_price=t1_price,
            t2_price=t2_price,
            runner_target=None,
            risk_ticks=risk_ticks,
            sweep=setup.sweep,
            fvg=fvg,
            mss=mss,
            bar_index=len(self.htf_bars) - 1,
            timestamp=bar.timestamp
        )

    def update_ltf(self, bar) -> Optional[TradeSetup]:
        """
        Process a new LTF (1m) bar and check for entry confirmation.

        Args:
            bar: New LTF price bar

        Returns:
            TradeSetup if entry is confirmed
        """
        self.ltf_bars.append(bar)

        # Need minimum bars for MSS detection
        if len(self.ltf_bars) < self.mss_lookback + self.mss_swing_strength + 5:
            return None

        # Check session filter
        if not should_trade(bar.timestamp, self.allow_lunch, self.require_killzone):
            return None

        # Check each setup awaiting MSS confirmation
        for setup in self.pending_setups[:]:
            if not setup.awaiting_mss:
                continue

            # Check if price is still in FVG zone (or has been recently)
            current_price = bar.close
            fvg = setup.fvg

            # Check for MSS using locked-in break level
            mss = None
            if setup.mss_break_level is not None:
                # Simple MSS: price breaks the locked-in level
                if setup.sweep.sweep_type == 'BEARISH':
                    # For bearish, close must break below the swing low
                    if current_price < setup.mss_break_level:
                        mss = MSS(
                            mss_type='BEARISH',
                            break_price=setup.mss_break_level,
                            confirmation_price=current_price,
                            bar_index=len(self.ltf_bars) - 1,
                            timestamp=bar.timestamp
                        )
                else:
                    # For bullish, close must break above the swing high
                    if current_price > setup.mss_break_level:
                        mss = MSS(
                            mss_type='BULLISH',
                            break_price=setup.mss_break_level,
                            confirmation_price=current_price,
                            bar_index=len(self.ltf_bars) - 1,
                            timestamp=bar.timestamp
                        )

            if mss:
                # Entry confirmed!
                trade = self._create_trade_setup(setup, mss, bar)
                if trade:
                    self.pending_setups.remove(setup)
                    self.daily_trades += 1
                    return trade

            # Remove setup if too old or price moved too far
            if not is_price_in_fvg(fvg, current_price):
                # Give some buffer - if price moved significantly away, remove
                if setup.sweep.sweep_type == 'BULLISH':
                    if current_price > fvg.top + (fvg.top - fvg.bottom) * 2:
                        self.pending_setups.remove(setup)
                else:
                    if current_price < fvg.bottom - (fvg.top - fvg.bottom) * 2:
                        self.pending_setups.remove(setup)

        return None

    def _create_trade_setup(self, setup: SetupState, mss: MSS, bar) -> Optional[TradeSetup]:
        """
        Create a trade setup from confirmed signals.

        Args:
            setup: The setup state with sweep and FVG
            mss: The MSS confirmation
            bar: Current bar

        Returns:
            TradeSetup if valid, None if risk too high
        """
        direction = setup.sweep.sweep_type

        # Check trend filter - skip counter-trend trades
        if not self._check_trend_filter(direction):
            return None

        entry_price = bar.close

        # Calculate stop - use FVG boundary (more reasonable risk) with buffer
        # For BEARISH: stop above FVG top
        # For BULLISH: stop below FVG bottom
        if direction == 'BULLISH':
            stop_price = setup.fvg.bottom - (self.stop_buffer_ticks * self.tick_size)
            risk = entry_price - stop_price
        else:
            stop_price = setup.fvg.top + (self.stop_buffer_ticks * self.tick_size)
            risk = stop_price - entry_price

        risk_ticks = risk / self.tick_size

        # Validate risk
        if risk_ticks <= 0 or risk_ticks > self.max_risk_ticks:
            return None

        # Calculate targets
        if direction == 'BULLISH':
            t1_price = entry_price + (risk * 2)  # 2R
            t2_price = entry_price + (risk * 4)  # 4R
        else:
            t1_price = entry_price - (risk * 2)  # 2R
            t2_price = entry_price - (risk * 4)  # 4R

        # Find opposing liquidity for runner target
        runner_target = self._find_opposing_liquidity(direction)

        return TradeSetup(
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            t1_price=t1_price,
            t2_price=t2_price,
            runner_target=runner_target,
            risk_ticks=risk_ticks,
            sweep=setup.sweep,
            fvg=setup.fvg,
            mss=mss,
            bar_index=len(self.ltf_bars) - 1,
            timestamp=bar.timestamp
        )

    def _calculate_ema(self, bars, period: int) -> Optional[float]:
        """Calculate EMA for given period."""
        if len(bars) < period:
            return None
        closes = [b.close for b in bars]
        if len(closes) < period:
            return None
        # EMA calculation
        multiplier = 2 / (period + 1)
        ema = sum(closes[:period]) / period  # Start with SMA
        for price in closes[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return ema

    def _check_trend_filter(self, direction: str) -> bool:
        """
        Check if trade direction aligns with trend using MTF (3m) bars.

        Returns True if:
        - Trend filter disabled, OR
        - LONG and EMA20 > EMA50, OR
        - SHORT and EMA20 < EMA50
        """
        if not self.use_trend_filter:
            return True

        # Use MTF (3m) bars for trend filter if available, otherwise HTF
        bars = self.mtf_bars if len(self.mtf_bars) >= self.ema_slow_period else self.htf_bars

        ema_fast = self._calculate_ema(bars, self.ema_fast_period)
        ema_slow = self._calculate_ema(bars, self.ema_slow_period)

        if ema_fast is None or ema_slow is None:
            return True  # Not enough data, allow trade

        if direction == 'BULLISH':
            return ema_fast > ema_slow
        else:  # BEARISH
            return ema_fast < ema_slow

    def _find_opposing_liquidity(self, direction: str) -> Optional[float]:
        """Find the nearest opposing liquidity level."""
        if len(self.htf_bars) < self.swing_lookback:
            return None

        levels = find_liquidity_levels(self.htf_bars, self.swing_strength, max_levels=3)

        current_price = self.htf_bars[-1].close

        if direction == 'BULLISH':
            # Look for liquidity above (swing highs)
            for swing in levels['highs']:
                if swing.price > current_price:
                    return swing.price
        else:
            # Look for liquidity below (swing lows)
            for swing in levels['lows']:
                if swing.price < current_price:
                    return swing.price

        return None

    def on_trade_result(self, pnl: float):
        """
        Record trade result.

        Args:
            pnl: Trade P/L in dollars
        """
        if pnl < 0:
            self.daily_losses += 1

    def get_pending_count(self) -> int:
        """Get count of pending setups."""
        return len(self.pending_setups)

    def get_state_summary(self) -> dict:
        """Get a summary of current strategy state."""
        return {
            'htf_bars': len(self.htf_bars),
            'ltf_bars': len(self.ltf_bars),
            'avg_body': round(self.avg_body, 4),
            'pending_setups': len(self.pending_setups),
            'daily_trades': self.daily_trades,
            'daily_losses': self.daily_losses,
            'setups_awaiting_mitigation': sum(1 for s in self.pending_setups if s.awaiting_mitigation),
            'setups_awaiting_mss': sum(1 for s in self.pending_setups if s.awaiting_mss),
        }
