"""
ICT Strategy State Machine

Manages the complete signal flow through each ICT concept:

    swingFound → liquidityDefined → sweepConfirmed → displacement
        → MSS → BOS → CISD → FVG → Entry

Each state must be achieved before progressing to the next.
The state machine tracks the current state and validates transitions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Literal

from core.types import Bar
from strategies.ict.signals.bos import BOSEvent
from strategies.ict.signals.cisd import CISDEvent
from strategies.ict.signals.displacement import DisplacementEvent
from strategies.ict.signals.fvg import FVGZone
from strategies.ict.signals.liquidity import LiquidityZone
from strategies.ict.signals.mss import MSSEvent
from strategies.ict.signals.sweep import SwingPoint


class SignalState(Enum):
    """States in the ICT signal flow."""
    IDLE = auto()              # Waiting for setup
    SWING_FOUND = auto()       # Swing points identified
    LIQUIDITY_DEFINED = auto() # Liquidity zones marked
    SWEEP_CONFIRMED = auto()   # Liquidity sweep detected
    DISPLACEMENT = auto()      # Displacement candle confirmed
    MSS = auto()               # Market Structure Shift
    BOS = auto()               # Break of Structure
    CISD = auto()              # Change in State of Delivery
    FVG_FORMED = auto()        # Fair Value Gap available
    READY_FOR_ENTRY = auto()   # All conditions met


@dataclass
class SetupContext:
    """
    Holds all the events/data for a developing trade setup.

    This context is built as we progress through states,
    accumulating the information needed to generate a signal.
    """
    # Current state
    state: SignalState = SignalState.IDLE

    # Direction bias (set after sweep)
    bias: Literal["BULLISH", "BEARISH"] | None = None

    # Events from each stage
    swing_highs: list[SwingPoint] = field(default_factory=list)
    swing_lows: list[SwingPoint] = field(default_factory=list)
    liquidity_zones: list[LiquidityZone] = field(default_factory=list)
    swept_zone: LiquidityZone | None = None
    displacement: DisplacementEvent | None = None
    mss: MSSEvent | None = None
    bos: BOSEvent | None = None
    cisd: CISDEvent | None = None
    entry_fvg: FVGZone | None = None

    # Timestamps
    setup_started_at: datetime | None = None
    setup_started_bar_index: int | None = None

    # Metadata
    metadata: dict = field(default_factory=dict)

    def reset(self):
        """Reset the context to IDLE state."""
        self.state = SignalState.IDLE
        self.bias = None
        self.swing_highs = []
        self.swing_lows = []
        self.liquidity_zones = []
        self.swept_zone = None
        self.displacement = None
        self.mss = None
        self.bos = None
        self.cisd = None
        self.entry_fvg = None
        self.setup_started_at = None
        self.setup_started_bar_index = None
        self.metadata = {}

    def advance_to(self, new_state: SignalState):
        """Advance to a new state."""
        self.state = new_state

    def is_at_least(self, state: SignalState) -> bool:
        """Check if we're at least at the given state."""
        return self.state.value >= state.value

    def get_state_name(self) -> str:
        """Get human-readable state name."""
        return self.state.name.replace("_", " ").title()


class ICTStateMachine:
    """
    State machine for ICT signal flow.

    Manages state transitions and validates that each step
    of the ICT methodology is properly followed.
    """

    # Valid state transitions
    VALID_TRANSITIONS = {
        SignalState.IDLE: [SignalState.SWING_FOUND],
        SignalState.SWING_FOUND: [SignalState.LIQUIDITY_DEFINED, SignalState.IDLE],
        SignalState.LIQUIDITY_DEFINED: [SignalState.SWEEP_CONFIRMED, SignalState.IDLE],
        SignalState.SWEEP_CONFIRMED: [SignalState.DISPLACEMENT, SignalState.IDLE],
        SignalState.DISPLACEMENT: [SignalState.MSS, SignalState.IDLE],
        SignalState.MSS: [SignalState.BOS, SignalState.IDLE],
        SignalState.BOS: [SignalState.CISD, SignalState.IDLE],
        SignalState.CISD: [SignalState.FVG_FORMED, SignalState.IDLE],
        SignalState.FVG_FORMED: [SignalState.READY_FOR_ENTRY, SignalState.IDLE],
        SignalState.READY_FOR_ENTRY: [SignalState.IDLE],
    }

    def __init__(self, config: dict):
        """
        Initialize the state machine.

        Args:
            config: Strategy configuration
        """
        self.config = config
        self.context = SetupContext()

        # Timeouts (in bars)
        self.sweep_timeout = config.get("sweep_timeout_bars", 50)
        self.displacement_timeout = config.get("displacement_timeout_bars", 5)
        self.mss_timeout = config.get("mss_timeout_bars", 10)
        self.bos_timeout = config.get("bos_timeout_bars", 10)
        self.cisd_timeout = config.get("cisd_timeout_bars", 10)
        self.fvg_timeout = config.get("fvg_timeout_bars", 20)

    @property
    def current_state(self) -> SignalState:
        """Get current state."""
        return self.context.state

    def can_transition_to(self, new_state: SignalState) -> bool:
        """Check if transition to new_state is valid."""
        valid = self.VALID_TRANSITIONS.get(self.context.state, [])
        return new_state in valid

    def transition_to(self, new_state: SignalState) -> bool:
        """
        Attempt to transition to a new state.

        Returns True if transition was successful.
        """
        if not self.can_transition_to(new_state):
            return False

        self.context.advance_to(new_state)
        return True

    def reset(self):
        """Reset state machine to IDLE."""
        self.context.reset()

    # =========================================================================
    # State Handlers
    # =========================================================================

    def on_swings_found(
        self,
        swing_highs: list[SwingPoint],
        swing_lows: list[SwingPoint],
        bar_index: int,
        timestamp: datetime,
    ) -> bool:
        """
        Handle swing point detection.

        Called when swing points are identified in the price action.

        Args:
            swing_highs: Detected swing highs
            swing_lows: Detected swing lows
            bar_index: Current bar index
            timestamp: Current timestamp

        Returns:
            True if state advanced
        """
        if not swing_highs and not swing_lows:
            return False

        self.context.swing_highs = swing_highs
        self.context.swing_lows = swing_lows
        self.context.setup_started_at = timestamp
        self.context.setup_started_bar_index = bar_index

        return self.transition_to(SignalState.SWING_FOUND)

    def on_liquidity_defined(
        self,
        liquidity_zones: list[LiquidityZone],
    ) -> bool:
        """
        Handle liquidity zone definition.

        Called when swing points are converted to liquidity zones.

        Args:
            liquidity_zones: Defined liquidity zones

        Returns:
            True if state advanced
        """
        if self.context.state != SignalState.SWING_FOUND:
            return False

        if not liquidity_zones:
            return False

        self.context.liquidity_zones = liquidity_zones

        return self.transition_to(SignalState.LIQUIDITY_DEFINED)

    def on_sweep_confirmed(
        self,
        swept_zone: LiquidityZone,
        bar_index: int,
    ) -> bool:
        """
        Handle liquidity sweep confirmation.

        Called when a liquidity zone is swept.

        Args:
            swept_zone: The zone that was swept
            bar_index: Bar index where sweep occurred

        Returns:
            True if state advanced
        """
        if self.context.state != SignalState.LIQUIDITY_DEFINED:
            return False

        self.context.swept_zone = swept_zone

        # Set bias based on sweep type
        # SSL sweep (took lows) → BULLISH bias
        # BSL sweep (took highs) → BEARISH bias
        self.context.bias = "BULLISH" if swept_zone.zone_type == "SSL" else "BEARISH"

        self.context.metadata["sweep_bar_index"] = bar_index

        return self.transition_to(SignalState.SWEEP_CONFIRMED)

    def on_displacement(
        self,
        displacement: DisplacementEvent,
        bar_index: int,
    ) -> bool:
        """
        Handle displacement detection.

        Called when a displacement candle is detected after sweep.

        Args:
            displacement: The displacement event
            bar_index: Current bar index

        Returns:
            True if state advanced
        """
        if self.context.state != SignalState.SWEEP_CONFIRMED:
            return False

        # Validate displacement direction matches bias
        if displacement.direction != self.context.bias:
            return False

        # Check timeout
        sweep_bar = self.context.metadata.get("sweep_bar_index", 0)
        if bar_index - sweep_bar > self.displacement_timeout:
            self.reset()
            return False

        self.context.displacement = displacement

        return self.transition_to(SignalState.DISPLACEMENT)

    def on_mss(
        self,
        mss: MSSEvent,
        bar_index: int,
    ) -> bool:
        """
        Handle Market Structure Shift detection.

        Called when MSS is detected after displacement.

        Args:
            mss: The MSS event
            bar_index: Current bar index

        Returns:
            True if state advanced
        """
        if self.context.state != SignalState.DISPLACEMENT:
            return False

        # Validate MSS direction matches bias
        if mss.direction != self.context.bias:
            return False

        self.context.mss = mss

        return self.transition_to(SignalState.MSS)

    def on_bos(
        self,
        bos: BOSEvent,
        bar_index: int,
    ) -> bool:
        """
        Handle Break of Structure detection.

        Called when BOS is detected after MSS.

        Args:
            bos: The BOS event
            bar_index: Current bar index

        Returns:
            True if state advanced
        """
        if self.context.state != SignalState.MSS:
            return False

        # Validate BOS direction matches bias
        if bos.direction != self.context.bias:
            return False

        self.context.bos = bos

        return self.transition_to(SignalState.BOS)

    def on_cisd(
        self,
        cisd: CISDEvent,
        bar_index: int,
    ) -> bool:
        """
        Handle CISD detection.

        Called when Change in State of Delivery is detected.

        Args:
            cisd: The CISD event
            bar_index: Current bar index

        Returns:
            True if state advanced
        """
        if self.context.state != SignalState.BOS:
            return False

        # Validate CISD direction matches bias
        if cisd.direction != self.context.bias:
            return False

        self.context.cisd = cisd

        return self.transition_to(SignalState.CISD)

    def on_fvg_formed(
        self,
        fvg: FVGZone,
        bar_index: int,
    ) -> bool:
        """
        Handle FVG formation.

        Called when an FVG forms after CISD.

        Args:
            fvg: The FVG zone
            bar_index: Current bar index

        Returns:
            True if state advanced
        """
        if self.context.state != SignalState.CISD:
            return False

        # Validate FVG direction matches bias
        if fvg.direction != self.context.bias:
            return False

        self.context.entry_fvg = fvg

        return self.transition_to(SignalState.FVG_FORMED)

    def on_fvg_entry(
        self,
        bar: Bar,
        bar_index: int,
    ) -> bool:
        """
        Check if price has entered the FVG for a valid entry.

        Args:
            bar: Current bar
            bar_index: Current bar index

        Returns:
            True if entry condition met
        """
        if self.context.state != SignalState.FVG_FORMED:
            return False

        if self.context.entry_fvg is None:
            return False

        fvg = self.context.entry_fvg

        # Check if price reached FVG entry level
        entry_mode = self.config.get("fvg_entry_mode", "MIDPOINT")
        entry_price = fvg.get_entry_price(entry_mode)

        if fvg.direction == "BULLISH":
            # Price must retrace down to FVG
            if bar.low <= entry_price:
                return self.transition_to(SignalState.READY_FOR_ENTRY)
        else:
            # Price must retrace up to FVG
            if bar.high >= entry_price:
                return self.transition_to(SignalState.READY_FOR_ENTRY)

        return False

    def is_ready_for_entry(self) -> bool:
        """Check if setup is ready for entry."""
        return self.context.state == SignalState.READY_FOR_ENTRY

    def get_setup_summary(self) -> dict:
        """Get a summary of the current setup."""
        return {
            "state": self.context.get_state_name(),
            "bias": self.context.bias,
            "swept_zone": (
                f"{self.context.swept_zone.zone_type} @ {self.context.swept_zone.price}"
                if self.context.swept_zone else None
            ),
            "displacement": (
                f"{self.context.displacement.direction} {self.context.displacement.body_size_ticks:.1f} ticks"
                if self.context.displacement else None
            ),
            "mss": (
                f"{self.context.mss.direction} broke {self.context.mss.broken_level}"
                if self.context.mss else None
            ),
            "bos": (
                f"{self.context.bos.direction} @ {self.context.bos.broken_level}"
                if self.context.bos else None
            ),
            "cisd": (
                f"{self.context.cisd.direction} {self.context.cisd.displacement_size:.1f} ticks"
                if self.context.cisd else None
            ),
            "fvg": (
                f"{self.context.entry_fvg.direction} {self.context.entry_fvg.low}-{self.context.entry_fvg.high}"
                if self.context.entry_fvg else None
            ),
        }
