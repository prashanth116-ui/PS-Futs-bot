"""
Market Maker Model (MMXM) Phase Tracker

Tracks the 4-phase MMXM cycle:
1. ACCUMULATION - Tight range, low volatility (smart money building position)
2. MANIPULATION - Liquidity sweep (stop hunt to trigger retail stops)
3. DISTRIBUTION - Displacement + FVG in opposite direction to sweep
4. EXPANSION - Continued move past distribution in the intended direction

A valid BUY model: sweep lows -> bullish displacement -> long OTE
A valid SELL model: sweep highs -> bearish displacement -> short OTE
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from strategies.ict_sweep.signals.sweep import Sweep, detect_sweep
from strategies.ict_ote.signals.fvg import FVG, detect_fvg


class MMXMPhase(Enum):
    NONE = 'NONE'
    ACCUMULATION = 'ACCUMULATION'
    MANIPULATION = 'MANIPULATION'
    DISTRIBUTION = 'DISTRIBUTION'
    EXPANSION = 'EXPANSION'


class MMXMModel(Enum):
    BUY = 'BUY'     # Sweep lows -> bullish displacement -> long OTE
    SELL = 'SELL'    # Sweep highs -> bearish displacement -> short OTE


@dataclass
class MMXMState:
    """Current state of the MMXM tracker."""
    phase: MMXMPhase = MMXMPhase.NONE
    model: Optional[MMXMModel] = None
    accumulation_high: Optional[float] = None
    accumulation_low: Optional[float] = None
    accumulation_bars: int = 0
    manipulation_sweep: Optional[Sweep] = None
    distribution_fvg: Optional[FVG] = None
    is_valid_sequence: bool = False
    last_update_index: int = 0


class MMXMTracker:
    """
    Tracks the MMXM cycle progression.

    Phases advance sequentially: ACCUMULATION -> MANIPULATION -> DISTRIBUTION -> EXPANSION.
    The tracker resets when a phase fails to materialize or conditions invalidate.
    """

    def __init__(self, config: dict):
        self.min_accumulation_bars = config.get('min_accumulation_bars', 10)
        self.accumulation_atr_ratio = config.get('accumulation_atr_ratio', 0.6)
        self.tick_size = config.get('tick_size', 0.25)
        self.state = MMXMState()
        self._accum_count = 0

    def reset(self):
        """Reset tracker to initial state."""
        self.state = MMXMState()
        self._accum_count = 0

    def update(self, bars, bar_index: int, avg_body: float) -> MMXMState:
        """
        Update MMXM state with a new bar.

        Args:
            bars: All HTF bars up to current
            bar_index: Index of current bar
            avg_body: Current average candle body

        Returns:
            Current MMXMState
        """
        if len(bars) < 25:
            return self.state

        self.state.last_update_index = bar_index

        phase = self.state.phase

        if phase == MMXMPhase.NONE:
            if self._check_accumulation(bars, bar_index):
                self.state.phase = MMXMPhase.ACCUMULATION
            return self.state

        if phase == MMXMPhase.ACCUMULATION:
            if self._check_accumulation(bars, bar_index):
                # Still in accumulation — keep counting
                return self.state
            # Accumulation ended — check for manipulation
            sweep = self._check_manipulation(bars, bar_index)
            if sweep:
                self.state.phase = MMXMPhase.MANIPULATION
                self.state.manipulation_sweep = sweep
                # Determine model from sweep direction
                if sweep.sweep_type == 'BULLISH':
                    self.state.model = MMXMModel.BUY
                else:
                    self.state.model = MMXMModel.SELL
            else:
                # No manipulation after accumulation — reset
                self.reset()
            return self.state

        if phase == MMXMPhase.MANIPULATION:
            if self._check_distribution(bars, bar_index, avg_body):
                self.state.phase = MMXMPhase.DISTRIBUTION
                self.state.is_valid_sequence = True
            elif bar_index - self.state.last_update_index > 15:
                # Too long since manipulation — reset
                self.reset()
            return self.state

        if phase == MMXMPhase.DISTRIBUTION:
            if self._check_expansion(bars, bar_index):
                self.state.phase = MMXMPhase.EXPANSION
            return self.state

        return self.state

    def _check_accumulation(self, bars, bar_index: int) -> bool:
        """
        Check if recent bars form a tight range (accumulation).

        Low ATR relative to recent average = institutional accumulation.
        """
        lookback = min(20, len(bars) - 1)
        if lookback < 5:
            return False

        recent = bars[-lookback:]

        # Calculate ATR for recent bars
        atr_sum = 0.0
        for i in range(1, len(recent)):
            tr = max(
                recent[i].high - recent[i].low,
                abs(recent[i].high - recent[i - 1].close),
                abs(recent[i].low - recent[i - 1].close),
            )
            atr_sum += tr
        recent_atr = atr_sum / (len(recent) - 1)

        # Calculate longer ATR for comparison
        long_lookback = min(50, len(bars) - 1)
        long_bars = bars[-long_lookback:]
        long_atr_sum = 0.0
        for i in range(1, len(long_bars)):
            tr = max(
                long_bars[i].high - long_bars[i].low,
                abs(long_bars[i].high - long_bars[i - 1].close),
                abs(long_bars[i].low - long_bars[i - 1].close),
            )
            long_atr_sum += tr
        long_atr = long_atr_sum / (len(long_bars) - 1) if len(long_bars) > 1 else recent_atr

        if long_atr <= 0:
            return False

        ratio = recent_atr / long_atr

        if ratio <= self.accumulation_atr_ratio:
            self._accum_count += 1
            if self._accum_count >= self.min_accumulation_bars:
                # Record the accumulation range
                accum_bars = bars[-self.min_accumulation_bars:]
                self.state.accumulation_high = max(b.high for b in accum_bars)
                self.state.accumulation_low = min(b.low for b in accum_bars)
                self.state.accumulation_bars = self._accum_count
                return True
        else:
            self._accum_count = 0

        return False

    def _check_manipulation(self, bars, bar_index: int) -> Optional[Sweep]:
        """Check for a liquidity sweep (manipulation phase)."""
        return detect_sweep(
            bars,
            tick_size=self.tick_size,
            swing_lookback=3,
            min_sweep_ticks=2,
            check_bars=3,
        )

    def _check_distribution(self, bars, bar_index: int, avg_body: float) -> bool:
        """
        Check for displacement + FVG after manipulation (distribution).

        The displacement should be in the opposite direction to the sweep:
        - BUY model (swept lows): expect bullish displacement
        - SELL model (swept highs): expect bearish displacement
        """
        if avg_body <= 0 or len(bars) < 3:
            return False

        bar = bars[-1]
        body = abs(bar.close - bar.open)
        ratio = body / avg_body

        # Need displacement candle (2x avg body)
        if ratio < 2.0:
            return False

        is_bullish_candle = bar.close > bar.open

        # Verify direction matches model
        if self.state.model == MMXMModel.BUY and not is_bullish_candle:
            return False
        if self.state.model == MMXMModel.SELL and is_bullish_candle:
            return False

        # Check for FVG formation
        expected_dir = 'BULLISH' if self.state.model == MMXMModel.BUY else 'BEARISH'
        fvg = detect_fvg(bars, tick_size=self.tick_size, min_size_ticks=3, direction=expected_dir)

        if fvg:
            self.state.distribution_fvg = fvg
            return True

        return False

    def _check_expansion(self, bars, bar_index: int) -> bool:
        """
        Check if price continues past distribution in the model direction.
        """
        if len(bars) < 2 or self.state.distribution_fvg is None:
            return False

        fvg = self.state.distribution_fvg
        current = bars[-1]

        if self.state.model == MMXMModel.BUY:
            return current.close > fvg.top
        else:
            return current.close < fvg.bottom

    def get_phase(self) -> MMXMPhase:
        """Get the current MMXM phase."""
        return self.state.phase

    def is_valid_for_entry(self) -> bool:
        """Check if a valid MMXM sequence has been detected."""
        return self.state.is_valid_sequence
