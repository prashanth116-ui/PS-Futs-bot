"""
ICT Optimal Trade Entry (OTE) Strategy

Entry Logic:
1. Impulse Leg - Detect strong directional move with displacement
2. OTE Zone - Calculate 62-79% Fibonacci retracement zone
3. FVG Confluence - Optional: check if FVG overlaps OTE zone
4. Retracement - Price retraces into OTE zone
5. Rejection - Candle shows rejection from zone (wick + close)

MMXM Enhancements:
- Premium/Discount filter: Only long in discount, short in premium
- Dealing Range: Swing-based range with liquidity targets
- MMXM Phase Tracker: Accumulation -> Manipulation -> Distribution -> Expansion
- SMT Divergence: Confirm entries with correlated symbol divergence

Exit Logic:
- Stop: Below impulse low (longs) / above impulse high (shorts) + buffer
- T1: Fixed exit at configurable R (default 3R, 1 contract)
- T2: Structure trail after configurable R (default 6R, 4-tick buffer)
- Runner: Structure trail (6-tick buffer, 1st trade only)
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from strategies.ict_ote.signals.impulse import detect_impulse, ImpulseLeg
from strategies.ict_ote.signals.fibonacci import (
    calculate_ote_zone, is_price_in_ote, check_ote_tap, check_rejection,
    fvg_overlaps_ote, OTEZone
)
from strategies.ict_ote.signals.fvg import FVG, detect_fvg, detect_fvg_in_range
from strategies.ict_ote.signals.dealing_range import (
    DealingRange, LiquidityTargets, find_dealing_range, find_liquidity_targets, get_runner_target
)
from strategies.ict_ote.signals.mmxm import MMXMPhase, MMXMModel, MMXMState, MMXMTracker
from strategies.ict_ote.signals.smt import SMTDivergence, detect_smt_divergence
from strategies.ict_ote.filters.premium_discount import (
    DealingRangeZone, calculate_dealing_range, check_premium_discount_filter
)
from strategies.ict_sweep.filters.displacement import calculate_avg_body, get_displacement_ratio
from strategies.ict_sweep.filters.session import should_trade, get_session_name
from strategies.ict_sweep.signals.liquidity import find_liquidity_levels


@dataclass
class OTESetup:
    """Tracks the state of a potential OTE trade setup."""
    impulse: ImpulseLeg
    ote_zone: OTEZone
    fvg: Optional[FVG] = None  # FVG in confluence (optional)
    has_fvg_confluence: bool = False
    awaiting_tap: bool = True
    awaiting_rejection: bool = False
    created_at_index: int = 0
    tap_bar_index: Optional[int] = None
    # MMXM enhancements
    mmxm_phase: Optional[str] = None
    mmxm_model: Optional[str] = None
    mmxm_valid_sequence: bool = False


@dataclass
class TradeSetup:
    """A confirmed OTE trade setup ready for entry."""
    direction: str  # 'BULLISH' or 'BEARISH'
    entry_price: float
    stop_price: float
    t1_price: float
    t2_price: float
    runner_target: Optional[float]
    risk_ticks: float
    impulse: ImpulseLeg
    ote_zone: OTEZone
    fvg: Optional[FVG]
    bar_index: int
    timestamp: datetime
    # MMXM enhancements
    pd_zone: Optional[str] = None               # 'PREMIUM' or 'DISCOUNT'
    dealing_range: Optional[DealingRange] = None
    liquidity_targets: Optional[LiquidityTargets] = None
    mmxm_phase: Optional[str] = None
    mmxm_model: Optional[str] = None
    mmxm_valid_sequence: bool = False
    smt_divergence: Optional[SMTDivergence] = None


class ICTOTEStrategy:
    """
    ICT Optimal Trade Entry Strategy Implementation.

    Uses HTF (5m) for impulse detection and OTE zone calculation,
    LTF (3m) for retracement entry with rejection confirmation.
    """

    def __init__(self, config: dict):
        self.config = config

        # Instrument settings
        self.symbol = config.get('symbol', 'ES')
        self.tick_size = config.get('tick_size', 0.25)
        self.tick_value = config.get('tick_value', 12.50)

        # Impulse detection
        self.impulse_body_multiplier = config.get('impulse_body_multiplier', 2.0)
        self.avg_body_lookback = config.get('avg_body_lookback', 20)
        self.min_impulse_ticks = config.get('min_impulse_ticks', 10)
        self.swing_lookback = config.get('swing_lookback', 3)
        self.impulse_max_bars_back = config.get('impulse_max_bars_back', 30)

        # FVG confluence
        self.require_fvg_confluence = config.get('require_fvg_confluence', False)
        self.min_fvg_ticks = config.get('min_fvg_ticks', 5)

        # Risk management
        self.stop_buffer_ticks = config.get('stop_buffer_ticks', 2)
        self.min_risk_ticks = config.get('min_risk_ticks', 0)
        self.max_risk_ticks = config.get('max_risk_ticks', 40)

        # Session filters
        self.allow_lunch = config.get('allow_lunch', False)
        self.require_killzone = config.get('require_killzone', False)

        # Daily limits
        self.max_daily_trades = config.get('max_daily_trades', 5)
        self.max_daily_losses = config.get('max_daily_losses', 2)

        # Loss cooldown
        self.loss_cooldown_minutes = config.get('loss_cooldown_minutes', 0)

        # Max OTE zone age
        self.max_ote_age_bars = config.get('max_ote_age_bars', 50)

        # Trend filter
        self.use_trend_filter = config.get('use_trend_filter', False)
        self.ema_fast_period = config.get('ema_fast_period', 20)
        self.ema_slow_period = config.get('ema_slow_period', 50)

        # DI direction filter
        self.use_di_filter = config.get('use_di_filter', False)
        self.di_period = config.get('di_period', 14)

        # --- MMXM Enhancement configs ---

        # Premium/Discount filter
        pd_config = config.get('premium_discount', {})
        self.use_premium_discount = pd_config.get('enabled', False)
        self.pd_method = pd_config.get('method', 'session')

        # Dealing Range
        dr_config = config.get('dealing_range', {})
        self.use_dealing_range = dr_config.get('enabled', False)
        self.dr_swing_lookback = dr_config.get('swing_lookback', 3)
        self.dr_max_bars_back = dr_config.get('max_bars_back', 100)

        # MMXM Phase Tracker
        mmxm_config = config.get('mmxm', {})
        self.use_mmxm = mmxm_config.get('enabled', False)
        self.require_mmxm_sequence = mmxm_config.get('require_valid_sequence', False)
        self.mmxm_tracker: Optional[MMXMTracker] = None
        if self.use_mmxm:
            self.mmxm_tracker = MMXMTracker({
                'min_accumulation_bars': mmxm_config.get('min_accumulation_bars', 10),
                'accumulation_atr_ratio': mmxm_config.get('accumulation_atr_ratio', 0.6),
                'tick_size': self.tick_size,
            })

        # SMT Divergence
        smt_config = config.get('smt', {})
        self.use_smt = smt_config.get('enabled', False)
        self.require_smt = smt_config.get('require_confirmation', False)
        self.smt_lookback = smt_config.get('lookback', 20)

        # State
        self.htf_bars = []
        self.ltf_bars = []
        self.trend_bars = []
        self.correlated_bars = []
        self.avg_body = 0.0
        self.pending_setups: list[OTESetup] = []
        self.active_impulses: list[ImpulseLeg] = []
        self.daily_trades = 0
        self.daily_losses = 0
        self.last_loss_time: Optional[datetime] = None

        # MMXM state
        self.dealing_range: Optional[DealingRange] = None
        self.liquidity_targets: Optional[LiquidityTargets] = None
        self.pd_zone: Optional[DealingRangeZone] = None
        self.last_smt: Optional[SMTDivergence] = None

        # Debug
        self._debug = config.get('debug', False)

    def reset_daily(self):
        """Reset state for a new trading day."""
        self.htf_bars = []
        self.ltf_bars = []
        self.trend_bars = []
        self.correlated_bars = []
        self.avg_body = 0.0
        self.pending_setups = []
        self.active_impulses = []
        self.daily_trades = 0
        self.daily_losses = 0
        self.last_loss_time = None
        self.dealing_range = None
        self.liquidity_targets = None
        self.pd_zone = None
        self.last_smt = None
        if self.mmxm_tracker:
            self.mmxm_tracker.reset()

    def update_trend(self, bar):
        """Process a new trend timeframe bar for EMA calculation."""
        self.trend_bars.append(bar)

    def update_correlated(self, bar):
        """Process a new correlated symbol bar for SMT divergence."""
        self.correlated_bars.append(bar)

    def update_htf(self, bar) -> Optional[OTESetup]:
        """
        Process a new HTF bar and check for impulse legs / OTE setups.

        Args:
            bar: New HTF (5m) price bar

        Returns:
            OTESetup if a new setup is detected
        """
        self.htf_bars.append(bar)
        bar_index = len(self.htf_bars) - 1

        # Need minimum bars for analysis
        if len(self.htf_bars) < self.swing_lookback * 2 + 10:
            return None

        # Update average body
        self.avg_body = calculate_avg_body(self.htf_bars, self.avg_body_lookback)

        # --- MMXM: Update dealing range ---
        if self.use_dealing_range:
            self.dealing_range = find_dealing_range(
                self.htf_bars, self.dr_swing_lookback, self.dr_max_bars_back
            )
            if self.dealing_range:
                current_price = bar.close
                self.liquidity_targets = find_liquidity_targets(
                    self.htf_bars, current_price, self.dr_swing_lookback, self.dr_max_bars_back
                )

        # --- MMXM: Update premium/discount zone ---
        if self.use_premium_discount:
            self.pd_zone = calculate_dealing_range(self.htf_bars, method=self.pd_method)

        # --- MMXM: Update phase tracker ---
        if self.mmxm_tracker:
            self.mmxm_tracker.update(self.htf_bars, bar_index, self.avg_body)

        # --- MMXM: Check SMT divergence ---
        if self.use_smt and self.correlated_bars:
            self.last_smt = detect_smt_divergence(
                self.htf_bars, self.correlated_bars,
                primary_symbol=self.symbol,
                correlated_symbol=self.config.get('correlated_symbol', ''),
                lookback=self.smt_lookback,
            )

        # Check session filter
        if not should_trade(bar.timestamp, self.allow_lunch, self.require_killzone):
            return None

        # Check daily limits
        if self.daily_trades >= self.max_daily_trades:
            return None
        if self.daily_losses >= self.max_daily_losses:
            return None

        # Remove stale setups
        self.pending_setups = [
            s for s in self.pending_setups
            if bar_index - s.created_at_index <= self.max_ote_age_bars
        ]

        # Detect impulse leg
        impulse = detect_impulse(
            self.htf_bars,
            tick_size=self.tick_size,
            avg_body=self.avg_body,
            min_body_multiplier=self.impulse_body_multiplier,
            swing_lookback=self.swing_lookback,
            min_leg_ticks=self.min_impulse_ticks,
            max_bars_back=self.impulse_max_bars_back,
        )

        if not impulse:
            if self._debug:
                print(f'  DBG {bar.timestamp.strftime("%H:%M")} | No impulse detected')
            return None

        # Check if we already have a setup for this direction
        existing = [s for s in self.pending_setups if s.impulse.direction == impulse.direction]
        if existing:
            # Check if this is a newer, larger impulse
            if impulse.size_ticks <= existing[-1].impulse.size_ticks:
                if self._debug:
                    print(f'  DBG {bar.timestamp.strftime("%H:%M")} | Already tracking {impulse.direction} impulse')
                return None
            # Replace with newer impulse
            self.pending_setups = [s for s in self.pending_setups
                                   if s.impulse.direction != impulse.direction]

        if self._debug:
            print(f'  DBG {bar.timestamp.strftime("%H:%M")} | IMPULSE {impulse.direction} '
                  f'{impulse.start_price:.2f}->{impulse.end_price:.2f} '
                  f'({impulse.size_ticks:.0f} ticks, disp={impulse.displacement_ratio:.2f}x)')

        # Calculate OTE zone
        ote_zone = calculate_ote_zone(impulse)

        if self._debug:
            print(f'  DBG {bar.timestamp.strftime("%H:%M")} | OTE Zone: '
                  f'{ote_zone.bottom:.2f}-{ote_zone.top:.2f} (mid={ote_zone.midpoint:.2f})')

        # Check for FVG confluence
        fvg = None
        has_confluence = False
        if impulse.start_index < len(self.htf_bars) - 2:
            fvgs = detect_fvg_in_range(
                self.htf_bars,
                start_index=impulse.start_index,
                end_index=min(bar_index, impulse.end_index + 5),
                tick_size=self.tick_size,
                min_size_ticks=self.min_fvg_ticks,
                direction=impulse.direction,
            )
            # Find FVG that overlaps with OTE zone
            for f in fvgs:
                if fvg_overlaps_ote(f.top, f.bottom, ote_zone):
                    fvg = f
                    has_confluence = True
                    if self._debug:
                        print(f'  DBG {bar.timestamp.strftime("%H:%M")} | FVG CONFLUENCE: '
                              f'{f.fvg_type} {f.bottom:.2f}-{f.top:.2f}')
                    break

        # If we require FVG confluence and don't have it, skip
        if self.require_fvg_confluence and not has_confluence:
            if self._debug:
                print(f'  DBG {bar.timestamp.strftime("%H:%M")} | REJECTED: no FVG confluence')
            return None

        # Capture MMXM state for the setup
        mmxm_phase = None
        mmxm_model = None
        mmxm_valid = False
        if self.mmxm_tracker:
            state = self.mmxm_tracker.state
            mmxm_phase = state.phase.value
            mmxm_model = state.model.value if state.model else None
            mmxm_valid = state.is_valid_sequence

        # Create OTE setup
        setup = OTESetup(
            impulse=impulse,
            ote_zone=ote_zone,
            fvg=fvg,
            has_fvg_confluence=has_confluence,
            awaiting_tap=True,
            created_at_index=bar_index,
            mmxm_phase=mmxm_phase,
            mmxm_model=mmxm_model,
            mmxm_valid_sequence=mmxm_valid,
        )
        self.pending_setups.append(setup)
        self.active_impulses.append(impulse)

        return setup

    def update_ltf(self, bar) -> Optional[TradeSetup]:
        """
        Process a new LTF bar and check for OTE entry.

        Checks if price retraces into an OTE zone with rejection.

        Args:
            bar: New LTF (3m) price bar

        Returns:
            TradeSetup if entry is confirmed
        """
        self.ltf_bars.append(bar)

        if len(self.ltf_bars) < 5:
            return None

        # Check session filter
        if not should_trade(bar.timestamp, self.allow_lunch, self.require_killzone):
            return None

        # Check daily limits
        if self.daily_trades >= self.max_daily_trades:
            return None
        if self.daily_losses >= self.max_daily_losses:
            return None

        # Check loss cooldown
        if self._is_in_cooldown(bar.timestamp):
            return None

        bar_index = len(self.ltf_bars) - 1

        for setup in self.pending_setups[:]:
            zone = setup.ote_zone

            # Check if price taps the OTE zone
            if setup.awaiting_tap:
                if check_ote_tap(zone, bar, bar_index):
                    setup.awaiting_tap = False
                    setup.awaiting_rejection = True
                    setup.tap_bar_index = bar_index

                    if self._debug:
                        print(f'  DBG {bar.timestamp.strftime("%H:%M")} | OTE TAP: '
                              f'{zone.direction} zone {zone.bottom:.2f}-{zone.top:.2f}')
                continue

            # Check for rejection from OTE zone
            if setup.awaiting_rejection:
                if check_rejection(zone, bar):
                    # Entry confirmed!
                    trade = self._create_trade_setup(setup, bar)
                    if trade:
                        self.pending_setups.remove(setup)
                        self.daily_trades += 1
                        return trade

                # Check if price has moved too far past the zone (invalidation)
                if zone.direction == 'BULLISH':
                    # If price closes well below OTE zone, invalidate
                    if bar.close < zone.bottom - (zone.top - zone.bottom):
                        if self._debug:
                            print(f'  DBG {bar.timestamp.strftime("%H:%M")} | OTE INVALIDATED: '
                                  f'price {bar.close:.2f} below zone {zone.bottom:.2f}')
                        self.pending_setups.remove(setup)
                else:  # BEARISH
                    if bar.close > zone.top + (zone.top - zone.bottom):
                        if self._debug:
                            print(f'  DBG {bar.timestamp.strftime("%H:%M")} | OTE INVALIDATED: '
                                  f'price {bar.close:.2f} above zone {zone.top:.2f}')
                        self.pending_setups.remove(setup)

        return None

    def _create_trade_setup(self, setup: OTESetup, bar) -> Optional[TradeSetup]:
        """Create a trade from OTE zone rejection with hybrid filter chain.

        If di_mandatory=True: DI is a hard gate, then N/4 remaining must pass.
        Otherwise: all 5 filters scored as optional, N/5 must pass.
        """
        direction = setup.impulse.direction
        di_mandatory = self.config.get('di_mandatory', False)

        # MANDATORY DI gate (if enabled)
        if di_mandatory and self.use_di_filter:
            if not self._check_di_direction(direction):
                if self._debug:
                    print(f'  DBG {bar.timestamp.strftime("%H:%M")} | REJECTED: DI mandatory ({direction})')
                return None

        # HYBRID scoring of remaining filters
        optional_passes = 0
        total_filters = 5

        if di_mandatory:
            # DI already passed as mandatory — skip it, score 4 remaining
            total_filters = 4
        else:
            # Filter 1: DI direction alignment (scored as optional)
            if self.use_di_filter:
                if self._check_di_direction(direction):
                    optional_passes += 1
            else:
                optional_passes += 1  # auto-pass if disabled

        # Filter 2: Premium/Discount zone alignment
        if self.use_premium_discount:
            if check_premium_discount_filter(self.pd_zone, direction):
                optional_passes += 1
        else:
            optional_passes += 1  # auto-pass if disabled

        # Filter 3: EMA trend alignment
        if self._check_trend_filter(direction):
            optional_passes += 1

        # Filter 4: Strong displacement (>= 2x avg body)
        if setup.impulse.displacement_ratio >= 2.0:
            optional_passes += 1

        # Filter 5: FVG overlaps OTE zone
        if setup.has_fvg_confluence:
            optional_passes += 1

        min_optional = self.config.get('min_hybrid_passes', 3)
        if optional_passes < min_optional:
            if self._debug:
                print(f'  DBG {bar.timestamp.strftime("%H:%M")} | REJECTED: hybrid filter ({optional_passes}/{total_filters} optional, need {min_optional})')
            return None

        # MMXM sequence filter (optional hard filter)
        if self.use_mmxm and self.require_mmxm_sequence:
            if self.mmxm_tracker and not self.mmxm_tracker.is_valid_for_entry():
                if self._debug:
                    phase = self.mmxm_tracker.get_phase().value
                    print(f'  DBG {bar.timestamp.strftime("%H:%M")} | REJECTED: no valid MMXM sequence (phase={phase})')
                return None

        entry_price = bar.close
        impulse = setup.impulse

        # Stop beyond OTE zone boundary + buffer
        # Tighter stop = smaller risk = more achievable R-targets
        buffer = self.stop_buffer_ticks * self.tick_size
        zone = setup.ote_zone
        if direction == 'BULLISH':
            stop_price = zone.bottom - buffer
            risk = entry_price - stop_price
        else:  # BEARISH
            stop_price = zone.top + buffer
            risk = stop_price - entry_price

        risk_ticks = risk / self.tick_size

        # 5. Validate risk (existing)
        if risk_ticks < self.min_risk_ticks or risk_ticks > self.max_risk_ticks:
            if self._debug:
                print(f'  DBG {bar.timestamp.strftime("%H:%M")} | REJECTED: risk {risk_ticks:.1f} ticks')
            return None

        # 6. SMT divergence (soft confirmation or hard filter)
        smt_div = None
        if self.use_smt and self.last_smt:
            # Check if SMT direction matches trade direction
            if self.last_smt.divergence_type == direction:
                smt_div = self.last_smt
            elif self.require_smt:
                if self._debug:
                    print(f'  DBG {bar.timestamp.strftime("%H:%M")} | REJECTED: no SMT confirmation for {direction}')
                return None

        # Calculate targets (configurable R-multiples)
        t1_r = self.config.get('t1_r', 3)
        trail_r = self.config.get('trail_r', 6)
        if direction == 'BULLISH':
            t1_price = entry_price + (risk * t1_r)
            t2_price = entry_price + (risk * trail_r)
        else:
            t1_price = entry_price - (risk * t1_r)
            t2_price = entry_price - (risk * trail_r)

        # Find opposing liquidity for runner target
        # Use dealing range module if enabled, otherwise fallback to original
        if self.use_dealing_range and self.liquidity_targets:
            runner_target = get_runner_target(self.liquidity_targets, direction)
        else:
            runner_target = self._find_opposing_liquidity(direction)

        if self._debug:
            extras = []
            if self.pd_zone:
                extras.append(f'PD={self.pd_zone.zone}')
            if self.mmxm_tracker:
                extras.append(f'MMXM={self.mmxm_tracker.get_phase().value}')
            if smt_div:
                extras.append(f'SMT={smt_div.divergence_type}')
            extra_str = f' [{", ".join(extras)}]' if extras else ''
            print(f'  DBG {bar.timestamp.strftime("%H:%M")} | ENTRY: {direction} @ {entry_price:.2f}, '
                  f'stop={stop_price:.2f}, risk={risk_ticks:.1f} ticks, T1={t1_price:.2f}{extra_str}')

        return TradeSetup(
            direction=direction,
            entry_price=entry_price,
            stop_price=stop_price,
            t1_price=t1_price,
            t2_price=t2_price,
            runner_target=runner_target,
            risk_ticks=risk_ticks,
            impulse=setup.impulse,
            ote_zone=setup.ote_zone,
            fvg=setup.fvg,
            bar_index=len(self.ltf_bars) - 1,
            timestamp=bar.timestamp,
            # MMXM enhancements
            pd_zone=self.pd_zone.zone if self.pd_zone else None,
            dealing_range=self.dealing_range,
            liquidity_targets=self.liquidity_targets,
            mmxm_phase=setup.mmxm_phase,
            mmxm_model=setup.mmxm_model,
            mmxm_valid_sequence=setup.mmxm_valid_sequence,
            smt_divergence=smt_div,
        )

    def _is_in_cooldown(self, current_time: datetime) -> bool:
        """Check if we're in post-loss cooldown period."""
        if self.loss_cooldown_minutes <= 0 or self.last_loss_time is None:
            return False
        from datetime import timedelta
        elapsed = (current_time - self.last_loss_time).total_seconds() / 60
        return elapsed < self.loss_cooldown_minutes

    def _calculate_ema(self, bars, period: int) -> Optional[float]:
        """Calculate EMA for given period."""
        if len(bars) < period:
            return None
        closes = [b.close for b in bars]
        multiplier = 2 / (period + 1)
        ema = sum(closes[:period]) / period
        for price in closes[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return ema

    def _check_trend_filter(self, direction: str) -> bool:
        """Check if trade direction aligns with EMA trend."""
        if not self.use_trend_filter:
            return True

        if len(self.trend_bars) >= self.ema_slow_period:
            bars = self.trend_bars
        else:
            bars = self.htf_bars

        ema_fast = self._calculate_ema(bars, self.ema_fast_period)
        ema_slow = self._calculate_ema(bars, self.ema_slow_period)

        if ema_fast is None or ema_slow is None:
            return True

        if direction == 'BULLISH':
            return ema_fast > ema_slow
        else:
            return ema_fast < ema_slow

    def _calculate_adx(self, bars, period: int = 14):
        """Calculate ADX and DI values."""
        if len(bars) < period * 2:
            return None, None, None

        tr_list = []
        plus_dm_list = []
        minus_dm_list = []

        for i in range(1, len(bars)):
            high = bars[i].high
            low = bars[i].low
            close_prev = bars[i - 1].close
            high_prev = bars[i - 1].high
            low_prev = bars[i - 1].low

            tr = max(high - low, abs(high - close_prev), abs(low - close_prev))
            tr_list.append(tr)

            up_move = high - high_prev
            down_move = low_prev - low

            plus_dm = up_move if up_move > down_move and up_move > 0 else 0
            minus_dm = down_move if down_move > up_move and down_move > 0 else 0

            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        if len(tr_list) < period:
            return None, None, None

        def wilder_smooth(data, p):
            smoothed = [sum(data[:p])]
            for i in range(p, len(data)):
                smoothed.append(smoothed[-1] - (smoothed[-1] / p) + data[i])
            return smoothed

        atr = wilder_smooth(tr_list, period)
        plus_dm_smooth = wilder_smooth(plus_dm_list, period)
        minus_dm_smooth = wilder_smooth(minus_dm_list, period)

        dx_list = []
        plus_di = 0
        minus_di = 0
        for i in range(len(atr)):
            if atr[i] == 0:
                continue
            plus_di = 100 * plus_dm_smooth[i] / atr[i]
            minus_di = 100 * minus_dm_smooth[i] / atr[i]

            di_sum = plus_di + minus_di
            if di_sum == 0:
                continue
            dx = 100 * abs(plus_di - minus_di) / di_sum
            dx_list.append(dx)

        if len(dx_list) < period:
            return None, None, None

        adx = sum(dx_list[-period:]) / period
        return adx, plus_di, minus_di

    def _check_di_direction(self, direction: str) -> bool:
        """Check if DI direction aligns with trade direction."""
        bars = self.htf_bars
        if len(bars) < self.di_period * 3:
            return True  # Pass if insufficient data

        adx, plus_di, minus_di = self._calculate_adx(bars, self.di_period)
        if adx is None:
            return True

        if direction == 'BULLISH':
            return plus_di > minus_di
        else:
            return minus_di > plus_di

    def _find_opposing_liquidity(self, direction: str) -> Optional[float]:
        """Find nearest opposing liquidity level (original fallback)."""
        if len(self.htf_bars) < self.swing_lookback * 2:
            return None

        levels = find_liquidity_levels(self.htf_bars, self.swing_lookback, max_levels=3)
        current_price = self.htf_bars[-1].close

        if direction == 'BULLISH':
            for swing in levels['highs']:
                if swing.price > current_price:
                    return swing.price
        else:
            for swing in levels['lows']:
                if swing.price < current_price:
                    return swing.price

        return None

    def on_trade_result(self, pnl: float, exit_time: Optional[datetime] = None):
        """Record trade result."""
        if pnl < 0:
            self.daily_losses += 1
            if exit_time:
                self.last_loss_time = exit_time

    def get_pending_count(self) -> int:
        """Get count of pending OTE setups."""
        return len(self.pending_setups)

    def get_state_summary(self) -> dict:
        """Get a summary of current strategy state."""
        summary = {
            'htf_bars': len(self.htf_bars),
            'ltf_bars': len(self.ltf_bars),
            'avg_body': round(self.avg_body, 4),
            'pending_setups': len(self.pending_setups),
            'active_impulses': len(self.active_impulses),
            'daily_trades': self.daily_trades,
            'daily_losses': self.daily_losses,
            'setups_awaiting_tap': sum(1 for s in self.pending_setups if s.awaiting_tap),
            'setups_awaiting_rejection': sum(1 for s in self.pending_setups if s.awaiting_rejection),
        }
        # MMXM state
        if self.mmxm_tracker:
            summary['mmxm_phase'] = self.mmxm_tracker.get_phase().value
            summary['mmxm_valid'] = self.mmxm_tracker.is_valid_for_entry()
        if self.pd_zone:
            summary['pd_zone'] = self.pd_zone.zone
        if self.dealing_range:
            summary['dealing_range'] = f'{self.dealing_range.low:.2f}-{self.dealing_range.high:.2f}'
        if self.last_smt:
            summary['smt'] = self.last_smt.divergence_type
        return summary
