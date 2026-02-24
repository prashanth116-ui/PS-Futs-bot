"""
ICT Liquidity Sweep Strategy

Entry Logic:
1. Liquidity Sweep — Price sweeps swing high/low (stop hunt)
2. Displacement — Strong rejection candle after sweep
3. FVG Forms — Fair Value Gap created during/after displacement (5m or 3m)
4. FVG Mitigation — Price retraces into FVG zone (retry window, then consumed)

Exit Logic:
- Stop: FVG-close stop (candle close past FVG boundary) with safety cap
- T1: Fixed exit at configurable R (default 3R, 1 contract)
- T2: Structure trail after configurable R (default 6R, 4-tick buffer)
- Runner: Structure trail (6-tick buffer, 1st trade only)
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from strategies.ict_sweep.signals.liquidity import find_liquidity_levels
from strategies.ict_sweep.signals.sweep import detect_sweep, Sweep
from strategies.ict_sweep.signals.fvg import detect_fvg, FVG
from strategies.ict_sweep.filters.displacement import calculate_avg_body, get_displacement_ratio
from strategies.ict_sweep.filters.session import should_trade, is_midday_cutoff


def calculate_adx(bars, period=14):
    """Calculate ADX and DI values."""
    if len(bars) < period * 2:
        return None, None, None

    tr_list = []
    plus_dm_list = []
    minus_dm_list = []

    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        close_prev = bars[i-1].close
        high_prev = bars[i-1].high
        low_prev = bars[i-1].low

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


@dataclass
class SweepSetup:
    """Single state tracking a sweep through its lifecycle."""
    sweep: Sweep
    displacement_ratio: float
    created_bar_index: int
    fvg: Optional[FVG] = None
    consumed: bool = False
    first_touch_bar_index: Optional[int] = None  # Bar when FVG first touched
    retry_window: int = 3  # Bars to retry after first touch before consuming
    tried_fvg_zones: list = field(default_factory=list)  # List of (bottom, top) already tried
    fvg_assigned_bar: Optional[int] = None  # Bar index when current FVG was assigned

    @property
    def phase(self) -> str:
        if self.consumed:
            return 'consumed'
        if self.fvg is None:
            return 'waiting_for_fvg'
        return 'waiting_for_mitigation'

    def cycle_fvg(self):
        """Mark current FVG as tried and reset to waiting_for_fvg."""
        if self.fvg is not None:
            self.tried_fvg_zones.append((self.fvg.bottom, self.fvg.top))
        self.fvg = None
        self.first_touch_bar_index = None
        self.fvg_assigned_bar = None


@dataclass
class TradeEntry:
    """Entry signal for the runner to execute."""
    direction: str              # 'LONG' or 'SHORT'
    entry_price: float
    stop_price: float
    risk_pts: float
    risk_ticks: float
    sweep: Sweep
    fvg: FVG
    bar_index: int
    timestamp: datetime
    displacement_ratio: float
    filter_summary: str


class ICTSweepStrategy:
    """
    ICT Liquidity Sweep Strategy — dual-TF FVG detection, retry-window mitigation.

    process_bar() is the single entry point. Returns 0 or more TradeEntry per bar.
    Optional: call process_mtf_bar() to feed 3m bars for dual-TF FVG detection.
    """

    def __init__(self, config: dict):
        self.config = config

        # Instrument
        self.tick_size = config.get('tick_size', 0.25)
        self.tick_value = config.get('tick_value', 12.50)

        # Liquidity / Sweep
        self.swing_lookback = config.get('swing_lookback', 20)
        self.swing_strength = config.get('swing_strength', 3)
        self.min_sweep_ticks = config.get('min_sweep_ticks', 2)
        self.max_sweep_ticks = config.get('max_sweep_ticks', 50)
        self.sweep_check_bars = config.get('sweep_check_bars', 3)

        # Displacement
        self.displacement_multiplier = config.get('displacement_multiplier', 1.35)
        self.avg_body_lookback = config.get('avg_body_lookback', 20)
        self.high_displacement_override = config.get('high_displacement_override', 3.0)

        # FVG
        self.min_fvg_ticks = config.get('min_fvg_ticks', 5)
        self.min_fvg_ticks_mtf = config.get('min_fvg_ticks_mtf', self.min_fvg_ticks)
        self.max_fvg_age_bars = config.get('max_fvg_age_bars', 20)
        self.max_fvg_wait_bars = config.get('max_fvg_wait_bars', 15)
        self.use_mtf_fvg = config.get('use_mtf_fvg', False)

        # Mitigation retry window
        self.mitigation_retry_bars = config.get('mitigation_retry_bars', 3)

        # Stop / Risk
        self.stop_buffer_ticks = config.get('stop_buffer_ticks', 2)
        self.min_risk_ticks = config.get('min_risk_ticks', 12)
        self.max_risk_ticks = config.get('max_risk_ticks', 40)

        # Session
        self.allow_lunch = config.get('allow_lunch', False)

        # Risk management
        self.max_daily_trades = config.get('max_daily_trades', 5)
        self.max_daily_losses = config.get('max_daily_losses', 3)
        self.loss_cooldown_minutes = config.get('loss_cooldown_minutes', 0)

        # Hybrid filters
        filters = config.get('filters', {})
        self.use_hybrid = filters.get('use_hybrid', True)
        self.use_di_filter = filters.get('use_di_filter', True)
        self.min_adx = filters.get('min_adx', 11)
        self.ema_fast_period = filters.get('ema_fast', 20)
        self.ema_slow_period = filters.get('ema_slow', 50)

        # State
        self.bars = []
        self.mtf_bars = []  # Optional 3m bars for dual-TF FVG detection
        self.setups: list[SweepSetup] = []
        self.losses_per_dir = {'LONG': 0, 'SHORT': 0}
        self.trades_today = 0
        self.last_loss_time: Optional[datetime] = None
        self.avg_body = 0.0

        # Cached indicator values
        self._last_adx = None
        self._last_plus_di = None
        self._last_minus_di = None

        # Debug
        self._debug = config.get('debug', False)

    def reset_daily(self):
        """Reset state for a new trading day."""
        self.bars = []
        self.mtf_bars = []
        self.setups = []
        self.losses_per_dir = {'LONG': 0, 'SHORT': 0}
        self.trades_today = 0
        self.last_loss_time = None
        self.avg_body = 0.0
        self._last_adx = None
        self._last_plus_di = None
        self._last_minus_di = None

    def process_mtf_bar(self, bar):
        """Ingest a 3m bar for dual-TF FVG detection. Call before process_bar()."""
        self.mtf_bars.append(bar)

    def process_bar(self, bar) -> list[TradeEntry]:
        """
        Single entry point. Returns 0 or more entries per bar.

        Flow:
        1. Append bar, update avg_body + indicators
        2. Session filter
        3. Expire stale/consumed setups
        4. Phase 1 setups: search for FVG formation
        5. Phase 2 setups: check FVG mitigation -> filters -> entry (ONE-SHOT)
        6. Detect new sweeps -> create SweepSetup
        """
        self.bars.append(bar)
        bar_index = len(self.bars) - 1
        entries = []


        # Need minimum bars for analysis
        if len(self.bars) < self.swing_lookback + self.swing_strength + 5:
            return entries

        # Update avg body
        self.avg_body = calculate_avg_body(self.bars, self.avg_body_lookback)

        # Update ADX/DI
        self._update_indicators()

        # Session filter
        if not should_trade(bar.timestamp, self.allow_lunch):
            return entries

        # Midday cutoff (12:00-14:00)
        if is_midday_cutoff(bar.timestamp):
            return entries

        # Daily trade limit
        if self.trades_today >= self.max_daily_trades:
            return entries

        # Both directions maxed out
        if (self.losses_per_dir['LONG'] >= self.max_daily_losses and
                self.losses_per_dir['SHORT'] >= self.max_daily_losses):
            return entries

        # 3. Expire stale/consumed setups
        self._expire_setups(bar_index)

        # 4. Phase 1: check waiting_for_fvg setups for FVG formation
        self._check_fvg_formation(bar_index)

        # 5. Phase 2: check waiting_for_mitigation setups for entry
        entries = self._check_mitigation(bar, bar_index)

        # 6. Detect new sweeps
        self._detect_new_sweeps(bar_index)

        return entries

    def on_trade_result(self, pnl: float, direction: str, exit_time: Optional[datetime] = None):
        """Record trade result for circuit breaker."""
        if pnl < 0:
            self.losses_per_dir[direction] = self.losses_per_dir.get(direction, 0) + 1
            if exit_time:
                self.last_loss_time = exit_time

    # ---- Internal methods ----

    def _expire_setups(self, bar_index: int):
        """Remove consumed and stale setups."""
        active = []
        for setup in self.setups:
            if setup.consumed:
                continue
            age = bar_index - setup.created_bar_index
            ts = self.bars[bar_index].timestamp.strftime("%H:%M")
            if setup.fvg is None and age > self.max_fvg_wait_bars:
                if self._debug:
                    print(f'  DBG {ts} | EXPIRED waiting_for_fvg setup (age={age})')
                continue
            if setup.fvg is not None and age > self.max_fvg_age_bars:
                if self._debug:
                    print(f'  DBG {ts} | EXPIRED waiting_for_mitigation setup (age={age})')
                continue
            # Untouched FVG — cycle to next FVG instead of expiring
            if (setup.fvg is not None and setup.first_touch_bar_index is None
                    and setup.fvg_assigned_bar is not None
                    and bar_index - setup.fvg_assigned_bar > self.max_fvg_wait_bars):
                if self._debug:
                    fvg = setup.fvg
                    print(f'  DBG {ts} | FVG CYCLE: untouched {fvg.bottom:.2f}-{fvg.top:.2f}, trying next')
                setup.cycle_fvg()
            # Touched but retry window expired (price moved away) — cycle to next FVG
            if (setup.fvg is not None and setup.first_touch_bar_index is not None
                    and bar_index - setup.first_touch_bar_index > self.mitigation_retry_bars):
                if self._debug:
                    fvg = setup.fvg
                    print(f'  DBG {ts} | FVG CYCLE: retry expired {fvg.bottom:.2f}-{fvg.top:.2f}, trying next')
                setup.cycle_fvg()
            active.append(setup)
        self.setups = active

    def _check_fvg_formation(self, bar_index: int):
        """Check if any waiting_for_fvg setups now have an FVG."""
        for setup in self.setups:
            if setup.phase != 'waiting_for_fvg':
                continue

            fvg = self._find_fvg_for_sweep(setup.sweep, skip_zones=setup.tried_fvg_zones)
            if fvg:
                setup.fvg = fvg
                setup.fvg_assigned_bar = bar_index
                if self._debug:
                    ts = self.bars[bar_index].timestamp.strftime("%H:%M")
                    tried = f' (tried {len(setup.tried_fvg_zones)} prior)' if setup.tried_fvg_zones else ''
                    print(f'  DBG {ts} | FVG found for {setup.sweep.sweep_type} sweep: '
                          f'{fvg.fvg_type} {fvg.bottom:.2f}-{fvg.top:.2f} '
                          f'({fvg.size_ticks:.0f} ticks){tried}')

    def _check_mitigation(self, bar, bar_index: int) -> list[TradeEntry]:
        """Check waiting_for_mitigation setups with retry window.

        On first FVG touch: try filters. If they fail, allow retries for
        mitigation_retry_bars more bars. After window expires, mark consumed.
        """
        entries = []

        for setup in self.setups:
            if setup.phase != 'waiting_for_mitigation':
                continue

            fvg = setup.fvg

            # Check if price touches FVG zone
            touched = False
            if fvg.fvg_type == 'BULLISH' and bar.low <= fvg.top:
                touched = True
            elif fvg.fvg_type == 'BEARISH' and bar.high >= fvg.bottom:
                touched = True

            if not touched:
                continue

            # Track first touch
            if setup.first_touch_bar_index is None:
                setup.first_touch_bar_index = bar_index
                if self._debug:
                    ts = bar.timestamp.strftime("%H:%M")
                    print(f'  DBG {ts} | FVG TOUCHED: {fvg.fvg_type} '
                          f'{fvg.bottom:.2f}-{fvg.top:.2f} (retry window={self.mitigation_retry_bars})')

            # Check if retry window expired
            bars_since_touch = bar_index - setup.first_touch_bar_index
            if bars_since_touch > self.mitigation_retry_bars:
                setup.consumed = True
                fvg.consumed = True
                if self._debug:
                    ts = bar.timestamp.strftime("%H:%M")
                    print(f'  DBG {ts} | CONSUMED (retry window expired after {bars_since_touch} bars)')
                continue

            # Map sweep direction to trade direction
            direction = 'LONG' if setup.sweep.sweep_type == 'BULLISH' else 'SHORT'

            # Per-direction loss limit — consume immediately (won't change)
            if self.losses_per_dir.get(direction, 0) >= self.max_daily_losses:
                setup.consumed = True
                fvg.consumed = True
                if self._debug:
                    ts = bar.timestamp.strftime("%H:%M")
                    print(f'  DBG {ts} | CONSUMED (loss limit): {direction}')
                continue

            # Cooldown — consume immediately
            if self._is_in_cooldown(bar.timestamp):
                setup.consumed = True
                fvg.consumed = True
                if self._debug:
                    ts = bar.timestamp.strftime("%H:%M")
                    print(f'  DBG {ts} | CONSUMED (cooldown)')
                continue

            # Opposing displacement check — don't enter into a bar displacing against you
            bar_body = bar.close - bar.open  # positive = bullish, negative = bearish
            if self.avg_body > 0:
                if direction == 'LONG' and bar_body < 0 and abs(bar_body) >= self.avg_body:
                    if self._debug:
                        ts = bar.timestamp.strftime("%H:%M")
                        ratio = abs(bar_body) / self.avg_body
                        print(f'  DBG {ts} | OPPOSING DISP: LONG blocked by bearish bar ({ratio:.1f}x)')
                    continue
                if direction == 'SHORT' and bar_body > 0 and bar_body >= self.avg_body:
                    if self._debug:
                        ts = bar.timestamp.strftime("%H:%M")
                        ratio = bar_body / self.avg_body
                        print(f'  DBG {ts} | OPPOSING DISP: SHORT blocked by bullish bar ({ratio:.1f}x)')
                    continue

            # Hybrid filters — may change on next bar, allow retry
            passed, summary = self._check_hybrid_filters(direction, setup.displacement_ratio)
            if not passed:
                if self._debug:
                    ts = bar.timestamp.strftime("%H:%M")
                    print(f'  DBG {ts} | FILTER FAIL (retry {bars_since_touch}/{self.mitigation_retry_bars}): {summary}')
                continue

            # Calculate entry and stop — enter at FVG edge (limit order at zone boundary)
            # LONG: price retraces DOWN into bullish FVG → enter at fvg.top
            # SHORT: price retraces UP into bearish FVG → enter at fvg.bottom
            buffer = self.stop_buffer_ticks * self.tick_size
            if direction == 'LONG':
                entry_price = fvg.top
                stop_price = fvg.bottom - buffer
                risk_pts = entry_price - stop_price
            else:
                entry_price = fvg.bottom
                stop_price = fvg.top + buffer
                risk_pts = stop_price - entry_price

            risk_ticks = risk_pts / self.tick_size

            # Validate risk
            if risk_ticks > self.max_risk_ticks:
                # FVG is structurally too wide — cycle to next FVG
                if self._debug:
                    ts = bar.timestamp.strftime("%H:%M")
                    print(f'  DBG {ts} | FVG CYCLE (risk too wide): '
                          f'{risk_ticks:.1f}t > max {self.max_risk_ticks}t, trying next')
                setup.cycle_fvg()
                continue
            if risk_ticks < self.min_risk_ticks:
                # Risk too small — may increase as price moves, allow retry
                if self._debug:
                    ts = bar.timestamp.strftime("%H:%M")
                    print(f'  DBG {ts} | RISK FAIL (retry {bars_since_touch}/{self.mitigation_retry_bars}): '
                          f'{risk_ticks:.1f}t < min {self.min_risk_ticks}t')
                continue

            # Entry accepted — consume setup
            setup.consumed = True
            fvg.consumed = True

            if self._debug:
                ts = bar.timestamp.strftime("%H:%M")
                print(f'  DBG {ts} | ENTRY: {direction} @ {entry_price:.2f} '
                      f'stop={stop_price:.2f} risk={risk_ticks:.1f}t {summary}')

            self.trades_today += 1

            entry = TradeEntry(
                direction=direction,
                entry_price=entry_price,
                stop_price=stop_price,
                risk_pts=risk_pts,
                risk_ticks=risk_ticks,
                sweep=setup.sweep,
                fvg=fvg,
                bar_index=bar_index,
                timestamp=bar.timestamp,
                displacement_ratio=setup.displacement_ratio,
                filter_summary=summary,
            )
            entries.append(entry)

        return entries

    def _detect_new_sweeps(self, bar_index: int):
        """Detect new sweeps on the current bar."""
        sweep = detect_sweep(
            self.bars,
            self.tick_size,
            self.swing_strength,
            self.min_sweep_ticks,
            check_bars=self.sweep_check_bars,
        )

        if not sweep:
            return

        # Validate sweep depth
        if sweep.sweep_depth_ticks > self.max_sweep_ticks:
            if self._debug:
                ts = self.bars[bar_index].timestamp.strftime("%H:%M")
                print(f'  DBG {ts} | SWEEP too deep: {sweep.sweep_depth_ticks:.1f}t > {self.max_sweep_ticks}')
            return

        # Check if we already have an active setup for this direction
        direction = sweep.sweep_type
        existing = [s for s in self.setups if s.sweep.sweep_type == direction and not s.consumed]
        if existing:
            if self._debug:
                ts = self.bars[bar_index].timestamp.strftime("%H:%M")
                print(f'  DBG {ts} | SWEEP skipped: already tracking {direction}')
            return

        # Check displacement on sweep bar and nearby bars
        disp_ratio = self._get_best_displacement(sweep)

        if disp_ratio < self.displacement_multiplier:
            if self._debug:
                ts = self.bars[bar_index].timestamp.strftime("%H:%M")
                print(f'  DBG {ts} | SWEEP no displacement: {disp_ratio:.2f}x < {self.displacement_multiplier}x')
            return

        if self._debug:
            ts = self.bars[bar_index].timestamp.strftime("%H:%M")
            print(f'  DBG {ts} | SWEEP {direction} @ {sweep.sweep_price:.2f} '
                  f'(depth={sweep.sweep_depth_ticks:.1f}t, disp={disp_ratio:.2f}x)')

        # New sweep invalidates opposite-direction setups (market reversed)
        opposite = 'BEARISH' if direction == 'BULLISH' else 'BULLISH'
        for s in self.setups:
            if s.sweep.sweep_type == opposite and not s.consumed:
                s.consumed = True
                if self._debug:
                    ts = self.bars[bar_index].timestamp.strftime("%H:%M")
                    print(f'  DBG {ts} | INVALIDATED {opposite} setup (opposing sweep)')

        # Check for FVG immediately
        fvg = self._find_fvg_for_sweep(sweep)

        setup = SweepSetup(
            sweep=sweep,
            displacement_ratio=disp_ratio,
            created_bar_index=bar_index,
            fvg=fvg,
            fvg_assigned_bar=bar_index if fvg else None,
        )
        self.setups.append(setup)

        if self._debug and fvg:
            ts = self.bars[bar_index].timestamp.strftime("%H:%M")
            print(f'  DBG {ts} | FVG immediate: {fvg.fvg_type} {fvg.bottom:.2f}-{fvg.top:.2f}')

    def _get_best_displacement(self, sweep: Sweep) -> float:
        """Get best displacement ratio from sweep bar and nearby bars."""
        best = 0.0
        for offset in range(-1, 3):
            idx = sweep.bar_index + offset
            if 0 <= idx < len(self.bars):
                ratio = get_displacement_ratio(self.bars[idx], self.avg_body)
                best = max(best, ratio)
        return best

    def _find_fvg_for_sweep(self, sweep: Sweep, skip_zones: list = None) -> Optional[FVG]:
        """Find FVG closest to current price after the sweep.

        Collects all candidate FVGs from 5m and 3m bars, then returns the one
        closest to current price (most likely to be mitigated).
        For BEARISH FVGs: closest = highest bottom (easiest for price to reach UP).
        For BULLISH FVGs: closest = lowest top (easiest for price to reach DOWN).
        """
        expected_dir = sweep.sweep_type
        skip = skip_zones or []
        candidates = []

        def _is_skipped(fvg):
            for (b, t) in skip:
                if abs(fvg.bottom - b) < self.tick_size and abs(fvg.top - t) < self.tick_size:
                    return True
            return False

        # Collect from 5m bars
        for offset in range(0, 10):
            idx = sweep.bar_index + offset
            if idx + 2 < len(self.bars):
                window = self.bars[idx:idx + 3]
                fvg = detect_fvg(window, self.tick_size, self.min_fvg_ticks, expected_dir)
                if fvg and not _is_skipped(fvg):
                    fvg.bar_index = idx + 1
                    candidates.append(fvg)

        # Collect from 3m bars if MTF enabled
        if self.use_mtf_fvg and len(self.mtf_bars) >= 3:
            sweep_time = self.bars[sweep.bar_index].timestamp
            mtf_start = None
            for i, b in enumerate(self.mtf_bars):
                if b.timestamp >= sweep_time:
                    mtf_start = max(0, i - 2)
                    break
            if mtf_start is not None:
                for offset in range(0, 17):
                    idx = mtf_start + offset
                    if idx + 2 < len(self.mtf_bars):
                        window = self.mtf_bars[idx:idx + 3]
                        if window[2].timestamp >= sweep_time:
                            fvg = detect_fvg(window, self.tick_size, self.min_fvg_ticks_mtf, expected_dir)
                            if fvg and not _is_skipped(fvg):
                                fvg.bar_index = idx + 1
                                candidates.append(fvg)

        if not candidates:
            return None

        # Pick closest to current price
        current_price = self.bars[-1].close
        if expected_dir == 'BEARISH':
            # SHORT entry: price retraces UP into FVG — prefer lowest bottom (easiest to reach)
            candidates.sort(key=lambda f: f.bottom)
            return candidates[0]
        else:
            # LONG entry: price retraces DOWN into FVG — prefer highest top (easiest to reach)
            candidates.sort(key=lambda f: -f.top)
            return candidates[0]

    def _is_in_cooldown(self, current_time: datetime) -> bool:
        """Check if we're in post-loss cooldown period."""
        if self.loss_cooldown_minutes <= 0 or self.last_loss_time is None:
            return False
        elapsed = (current_time - self.last_loss_time).total_seconds() / 60
        return elapsed < self.loss_cooldown_minutes

    def _update_indicators(self):
        """Update cached ADX/DI values."""
        adx, plus_di, minus_di = calculate_adx(self.bars)
        if adx is not None:
            self._last_adx = adx
            self._last_plus_di = plus_di
            self._last_minus_di = minus_di

    def _calculate_ema(self, period: int) -> Optional[float]:
        """Calculate EMA for given period from self.bars."""
        if len(self.bars) < period:
            return None
        closes = [b.close for b in self.bars]
        multiplier = 2 / (period + 1)
        ema = sum(closes[:period]) / period
        for price in closes[period:]:
            ema = (price * multiplier) + (ema * (1 - multiplier))
        return ema

    def _check_hybrid_filters(self, direction: str, displacement_ratio: float) -> tuple[bool, str]:
        """
        Hybrid filter system: DI mandatory + 2/3 optional (displacement, ADX, EMA).

        Returns (passed, summary_string).
        """
        parts = []

        # High displacement override — bypass ALL filters (DI is lagging on fast reversals)
        if self.high_displacement_override > 0 and displacement_ratio >= self.high_displacement_override:
            parts.append(f'disp={displacement_ratio:.1f}x(HIGH)')
            return True, ' '.join(parts)

        # MANDATORY: DI Direction
        if self.use_di_filter:
            if self._last_plus_di is None or self._last_minus_di is None:
                di_ok = True
                parts.append('DI=N/A')
            else:
                if direction == 'LONG':
                    di_ok = self._last_plus_di > self._last_minus_di
                else:
                    di_ok = self._last_minus_di > self._last_plus_di
                pdi = f'{self._last_plus_di:.1f}'
                mdi = f'{self._last_minus_di:.1f}'
                parts.append(f'DI={"OK" if di_ok else "FAIL"}({pdi}/{mdi})')

            if not di_ok:
                return False, ' '.join(parts)

        if not self.use_hybrid:
            return True, ' '.join(parts)

        # OPTIONAL: need 2/3
        opt_passed = 0
        opt_total = 3

        # 1. Displacement
        disp_ok = displacement_ratio >= self.displacement_multiplier
        opt_passed += int(disp_ok)
        parts.append(f'disp={displacement_ratio:.2f}x{"OK" if disp_ok else ""}')

        # 2. ADX
        adx_val = self._last_adx
        adx_ok = adx_val is not None and adx_val >= self.min_adx
        opt_passed += int(adx_ok)
        adx_str = f'{adx_val:.1f}' if adx_val is not None else 'N/A'
        parts.append(f'ADX={adx_str}{"OK" if adx_ok else ""}')

        # 3. EMA Trend
        ema_fast = self._calculate_ema(self.ema_fast_period)
        ema_slow = self._calculate_ema(self.ema_slow_period)
        if ema_fast is None or ema_slow is None:
            ema_ok = True  # Not enough data, pass
        elif direction == 'LONG':
            ema_ok = ema_fast > ema_slow
        else:
            ema_ok = ema_fast < ema_slow
        opt_passed += int(ema_ok)
        parts.append(f'EMA={"OK" if ema_ok else "FAIL"}')

        min_needed = 2  # 2 of 3
        passed = opt_passed >= min_needed
        parts.append(f'({opt_passed}/{opt_total})')

        return passed, ' '.join(parts)
