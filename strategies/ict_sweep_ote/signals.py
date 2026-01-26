"""
ICT_Sweep_OTE_MSS_FVG_Long_v1 - Signal Engine & Trade Builder

Implements:
- Trade signal generation
- Entry price calculation
- Stop loss placement
- Take profit targets
- Position sizing
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal
from enum import Enum

from core.types import Bar
from strategies.ict_sweep_ote.config import (
    StrategyConfig,
    StopLossConfig,
    TakeProfitConfig,
    RiskConfig,
    FVGConfig,
    OTEConfig,
)
from strategies.ict_sweep_ote.detectors import (
    SSLSweep,
    BSLSweep,
    MSSEvent,
    FVGZone,
    OTEZone,
    SwingPoint,
    SwingType,
    calculate_atr,
)
from typing import Union


class SignalDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class TradeStatus(Enum):
    PENDING = "PENDING"       # Signal generated, waiting for fill
    OPEN = "OPEN"             # Position is open
    PARTIAL = "PARTIAL"       # Partial exit taken
    CLOSED = "CLOSED"         # Fully closed
    CANCELLED = "CANCELLED"   # Signal cancelled before fill


@dataclass
class TradeSignal:
    """A generated trade signal."""
    signal_id: str
    timestamp: datetime
    symbol: str
    direction: SignalDirection
    entry_price: float
    stop_price: float
    targets: list[float]  # TP1, TP2, TP3
    position_size: int  # Number of contracts
    risk_amount: float  # Dollar risk for this trade

    # Context
    sweep: Union[SSLSweep, BSLSweep]  # SSL for longs, BSL for shorts
    mss: Optional[MSSEvent]
    fvg: FVGZone
    ote: Optional[OTEZone]

    # Metadata
    reason: dict = field(default_factory=dict)


@dataclass
class OpenTrade:
    """An open trade being managed."""
    signal: TradeSignal
    status: TradeStatus = TradeStatus.OPEN
    entry_bar_index: int = 0
    entry_fill_price: float = 0.0

    # Position tracking
    initial_contracts: int = 0  # Original position size
    remaining_contracts: int = 0
    realized_pnl: float = 0.0

    # Point value for PnL calculation (ES=$50, NQ=$20)
    point_value: float = 50.0

    # Current stop/targets
    current_stop: float = 0.0
    current_targets: list[float] = field(default_factory=list)

    # Partial exit tracking
    tp1_hit: bool = False
    tp2_hit: bool = False
    tp3_hit: bool = False

    # Trailing stop
    trailing_active: bool = False
    highest_since_entry: float = 0.0
    lowest_since_entry: float = 0.0


# =============================================================================
# ENTRY PRICE CALCULATION
# =============================================================================

def calculate_entry_price(
    fvg: FVGZone,
    ote: Optional[OTEZone],
    current_bar: Bar,
    config: FVGConfig,
    ote_config: OTEConfig,
) -> Optional[float]:
    """
    Calculate entry price based on FVG and OTE zones.

    Priority:
    1. If FVG overlaps OTE and require_ote_entry is True, use OTE-FVG intersection
    2. Otherwise, use FVG entry mode (FIRST_TOUCH, MIDPOINT, LOWER_EDGE)

    Args:
        fvg: The FVG zone for entry
        ote: OTE zone if calculated
        current_bar: Current price bar
        config: FVG config
        ote_config: OTE config

    Returns:
        Entry price or None if entry not valid
    """
    if fvg.mitigated:
        return None

    # For LONG entries (bullish FVG)
    if fvg.direction == "BULLISH":
        # Check if price has entered FVG
        if current_bar.low > fvg.top:
            return None  # Price hasn't reached FVG yet

        # Calculate base entry from FVG
        if config.entry_mode == "FIRST_TOUCH":
            entry = fvg.top
        elif config.entry_mode == "MIDPOINT":
            entry = (fvg.top + fvg.bottom) / 2
        else:  # LOWER_EDGE
            entry = fvg.bottom

        # Adjust for OTE if required
        if ote and ote_config.require_ote_entry:
            if not ote.price_in_ote(entry):
                # Entry not in OTE, try to find overlap
                if ote.fib_79 <= entry <= ote.fib_62:
                    pass  # Already in OTE
                elif entry > ote.fib_62:
                    entry = ote.fib_62  # Use top of OTE
                elif entry < ote.fib_79:
                    return None  # Below OTE, skip entry

        return entry

    # For SHORT entries (bearish FVG)
    elif fvg.direction == "BEARISH":
        if current_bar.high < fvg.bottom:
            return None

        if config.entry_mode == "FIRST_TOUCH":
            entry = fvg.bottom
        elif config.entry_mode == "MIDPOINT":
            entry = (fvg.top + fvg.bottom) / 2
        else:
            entry = fvg.top

        return entry

    return None


# =============================================================================
# STOP LOSS CALCULATION
# =============================================================================

def calculate_stop_loss(
    sweep: Union[SSLSweep, BSLSweep],
    entry_price: float,
    direction: SignalDirection,
    config: StopLossConfig,
    atr: float,
) -> tuple[float, bool]:
    """
    Calculate stop loss price.

    For LONG (SSL sweep):
    - SL = sweep_low - buffer

    For SHORT (BSL sweep):
    - SL = sweep_high + buffer

    Args:
        sweep: The SSL or BSL sweep that triggered setup
        entry_price: Entry price
        direction: LONG or SHORT
        config: StopLossConfig
        atr: Current ATR

    Returns:
        Tuple of (stop_price, is_valid)
        is_valid is False if SL distance exceeds max_sl_atr_mult
    """
    # Calculate buffer
    if config.sl_buffer_fixed > 0:
        buffer = config.sl_buffer_fixed
    else:
        buffer = atr * config.sl_buffer_atr_mult

    if direction == SignalDirection.LONG:
        # For longs, SL below sweep low
        stop_price = sweep.sweep_low - buffer
        sl_distance = entry_price - stop_price
    else:
        # For shorts, SL above sweep high
        stop_price = sweep.sweep_high + buffer
        sl_distance = stop_price - entry_price

    # Validate SL distance
    max_distance = atr * config.max_sl_atr_mult
    is_valid = sl_distance <= max_distance

    return stop_price, is_valid


# =============================================================================
# TAKE PROFIT CALCULATION
# =============================================================================

def calculate_take_profits(
    entry_price: float,
    stop_price: float,
    sweep: Union[SSLSweep, BSLSweep],
    swings: list[SwingPoint],
    direction: SignalDirection,
    config: TakeProfitConfig,
) -> list[float]:
    """
    Calculate take profit targets with minimum R:R requirements.

    For LONG: TP1 < TP2 < TP3 (ascending)
    For SHORT: TP1 > TP2 > TP3 (descending)

    Ensures minimum R-multiples from config are respected.

    Returns:
        List of [TP1, TP2, TP3] prices in proper order
    """
    risk = abs(entry_price - stop_price)

    # Calculate minimum targets based on R-multiples
    min_tp1_r = getattr(config, 'min_tp1_r_mult', 1.0)
    min_tp2_r = getattr(config, 'min_tp2_r_mult', 2.0)
    min_tp3_r = getattr(config, 'min_tp3_r_mult', 3.0)

    if direction == SignalDirection.LONG:
        # Minimum targets (entry + R * risk)
        min_tp1 = entry_price + (risk * min_tp1_r)
        min_tp2 = entry_price + (risk * min_tp2_r)
        min_tp3 = entry_price + (risk * min_tp3_r)

        # Get swing highs above entry, sorted by distance (nearest first)
        swing_targets = sorted(
            [s for s in swings if s.swing_type == SwingType.HIGH and s.price > entry_price],
            key=lambda s: s.price
        )

        # TP1: Nearest swing high that meets minimum R:R, or use min
        tp1 = min_tp1
        for s in swing_targets:
            if s.price >= min_tp1:
                tp1 = s.price
                break

        # TP2: Next swing high beyond TP1, or use min
        tp2 = min_tp2
        for s in swing_targets:
            if s.price > tp1 and s.price >= min_tp2:
                tp2 = s.price
                break
        tp2 = max(tp2, tp1 + risk)  # Ensure TP2 > TP1

        # TP3: Fib extension or min
        tp3 = max(entry_price + (risk * config.tp3_fib_ext), min_tp3)
        tp3 = max(tp3, tp2 + risk)  # Ensure TP3 > TP2

        return [tp1, tp2, tp3]

    else:  # SHORT
        # Minimum targets (entry - R * risk)
        min_tp1 = entry_price - (risk * min_tp1_r)
        min_tp2 = entry_price - (risk * min_tp2_r)
        min_tp3 = entry_price - (risk * min_tp3_r)

        # Get swing lows below entry, sorted by distance (nearest first = highest price)
        swing_targets = sorted(
            [s for s in swings if s.swing_type == SwingType.LOW and s.price < entry_price],
            key=lambda s: s.price,
            reverse=True  # Nearest (highest) first
        )

        # TP1: Nearest swing low that meets minimum R:R, or use min
        tp1 = min_tp1
        for s in swing_targets:
            if s.price <= min_tp1:
                tp1 = s.price
                break

        # TP2: Next swing low beyond TP1, or use min
        tp2 = min_tp2
        for s in swing_targets:
            if s.price < tp1 and s.price <= min_tp2:
                tp2 = s.price
                break
        tp2 = min(tp2, tp1 - risk)  # Ensure TP2 < TP1

        # TP3: Fib extension or min
        tp3 = min(entry_price - (risk * config.tp3_fib_ext), min_tp3)
        tp3 = min(tp3, tp2 - risk)  # Ensure TP3 < TP2

        return [tp1, tp2, tp3]


# =============================================================================
# POSITION SIZING
# =============================================================================

def calculate_position_size(
    equity: float,
    entry_price: float,
    stop_price: float,
    config: RiskConfig,
    tick_value: float = 12.50,  # ES futures: $12.50 per tick
    tick_size: float = 0.25,    # ES futures: 0.25 tick size
) -> tuple[int, float]:
    """
    Calculate position size based on risk percentage.

    Formula:
    - Risk amount = equity * risk_per_trade_pct
    - SL distance in ticks = (entry - stop) / tick_size
    - Dollar risk per contract = SL ticks * tick_value
    - Position size = Risk amount / Dollar risk per contract

    Args:
        equity: Account equity
        entry_price: Entry price
        stop_price: Stop loss price
        config: RiskConfig
        tick_value: Dollar value per tick (ES = $12.50)
        tick_size: Minimum price increment (ES = 0.25)

    Returns:
        Tuple of (contracts, risk_amount)
    """
    risk_amount = equity * config.risk_per_trade_pct

    sl_distance = abs(entry_price - stop_price)
    sl_ticks = sl_distance / tick_size
    dollar_risk_per_contract = sl_ticks * tick_value

    if dollar_risk_per_contract <= 0:
        return 0, 0.0

    contracts = int(risk_amount / dollar_risk_per_contract)

    # Enforce minimum 1 contract
    contracts = max(1, contracts)

    # Enforce maximum positions
    contracts = min(contracts, config.max_positions)

    # Calculate actual risk with this position size
    actual_risk = contracts * dollar_risk_per_contract

    return contracts, actual_risk


# =============================================================================
# SIGNAL BUILDER
# =============================================================================

def build_trade_signal(
    timestamp: datetime,
    symbol: str,
    sweep: Union[SSLSweep, BSLSweep],
    mss: Optional[MSSEvent],
    fvg: FVGZone,
    ote: Optional[OTEZone],
    current_bar: Bar,
    swings: list[SwingPoint],
    atr: float,
    equity: float,
    config: StrategyConfig,
) -> Optional[TradeSignal]:
    """
    Build complete trade signal with entry, SL, TPs, and position size.

    Args:
        timestamp: Signal timestamp
        symbol: Trading symbol
        sweep: Confirmed SSL sweep (for longs) or BSL sweep (for shorts)
        mss: MSS event (optional)
        fvg: FVG zone for entry
        ote: OTE zone (optional)
        current_bar: Current price bar
        swings: All swing points
        atr: Current ATR
        equity: Account equity
        config: Full strategy config

    Returns:
        TradeSignal if valid, None if filters fail
    """
    # Determine direction based on FVG
    if fvg.direction == "BULLISH":
        direction = SignalDirection.LONG
    else:
        direction = SignalDirection.SHORT

    # Calculate entry price
    entry_price = calculate_entry_price(
        fvg=fvg,
        ote=ote,
        current_bar=current_bar,
        config=config.fvg,
        ote_config=config.ote,
    )

    if entry_price is None:
        return None

    # Calculate stop loss
    stop_price, sl_valid = calculate_stop_loss(
        sweep=sweep,
        entry_price=entry_price,
        direction=direction,
        config=config.stop_loss,
        atr=atr,
    )

    if not sl_valid:
        return None  # SL too far, skip trade

    # Calculate take profits
    targets = calculate_take_profits(
        entry_price=entry_price,
        stop_price=stop_price,
        sweep=sweep,
        swings=swings,
        direction=direction,
        config=config.take_profit,
    )

    # Calculate position size
    # For futures: ES tick_value=$12.50, tick_size=0.25
    # For NQ: tick_value=$5.00, tick_size=0.25
    tick_value = 12.50 if symbol.upper() in ["ES", "ES1!"] else 5.00
    tick_size = 0.25

    contracts, risk_amount = calculate_position_size(
        equity=equity,
        entry_price=entry_price,
        stop_price=stop_price,
        config=config.risk,
        tick_value=tick_value,
        tick_size=tick_size,
    )

    if contracts == 0:
        return None

    # Generate signal ID
    signal_id = f"{symbol}_{timestamp.strftime('%Y%m%d_%H%M%S')}_{direction.value}"

    # Build reason/context
    if direction == SignalDirection.LONG:
        sweep_price = sweep.sweep_low
        setup_name = "ICT_Sweep_OTE_MSS_FVG_Long"
    else:
        sweep_price = sweep.sweep_high
        setup_name = "ICT_Sweep_OTE_MSS_FVG_Short"

    reason = {
        "setup": setup_name,
        "sweep_time": sweep.sweep_bar_timestamp.isoformat(),
        "sweep_price": sweep_price,
        "mss_confirmed": mss is not None,
        "fvg_direction": fvg.direction,
        "fvg_size": fvg.size,
        "in_ote": ote.price_in_ote(entry_price) if ote else False,
        "in_discount": ote.price_in_discount(entry_price) if ote else False,
        "atr": atr,
    }

    return TradeSignal(
        signal_id=signal_id,
        timestamp=timestamp,
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        stop_price=stop_price,
        targets=targets,
        position_size=contracts,
        risk_amount=risk_amount,
        sweep=sweep,
        mss=mss,
        fvg=fvg,
        ote=ote,
        reason=reason,
    )


# =============================================================================
# TRADE MANAGEMENT
# =============================================================================

def calculate_exit_pnl(
    entry_price: float,
    exit_price: float,
    contracts: int,
    direction: SignalDirection,
    point_value: float = 50.0,
) -> float:
    """
    Calculate PnL for an exit.

    Args:
        entry_price: Entry price
        exit_price: Exit price
        contracts: Number of contracts exited
        direction: Trade direction
        point_value: Dollar value per point (ES=$50, NQ=$20)

    Returns:
        PnL in dollars (positive = profit, negative = loss)
    """
    if direction == SignalDirection.LONG:
        points = exit_price - entry_price
    else:  # SHORT
        points = entry_price - exit_price

    return points * contracts * point_value


def update_trade(
    trade: OpenTrade,
    current_bar: Bar,
    atr: float,
    sl_config: StopLossConfig,
    tp_config: TakeProfitConfig,
) -> list[str]:
    """
    Update trade state based on current price action.

    Checks for:
    - Stop loss hit
    - Take profit hits (TP1, TP2, TP3)
    - Trailing stop updates

    Args:
        trade: The open trade
        current_bar: Current price bar
        atr: Current ATR
        sl_config: Stop loss config
        tp_config: Take profit config

    Returns:
        List of events that occurred (e.g., ["TP1_HIT", "MOVE_TO_BE"])
    """
    events = []

    if trade.status in [TradeStatus.CLOSED, TradeStatus.CANCELLED]:
        return events

    # Track high/low since entry
    if trade.signal.direction == SignalDirection.LONG:
        trade.highest_since_entry = max(trade.highest_since_entry, current_bar.high)

        # Check stop loss
        if current_bar.low <= trade.current_stop:
            # Calculate PnL for remaining contracts at stop price
            pnl = calculate_exit_pnl(
                trade.entry_fill_price, trade.current_stop,
                trade.remaining_contracts, trade.signal.direction, trade.point_value
            )
            trade.realized_pnl += pnl
            trade.remaining_contracts = 0
            trade.status = TradeStatus.CLOSED
            events.append("STOP_LOSS_HIT")
            return events

        # Check TP1
        if not trade.tp1_hit and current_bar.high >= trade.current_targets[0]:
            trade.tp1_hit = True
            # Calculate partial exit
            exit_contracts = int(trade.remaining_contracts * tp_config.tp1_exit_pct)
            if exit_contracts < 1:
                exit_contracts = 1  # At least 1 contract
            # Calculate PnL for TP1 exit
            pnl = calculate_exit_pnl(
                trade.entry_fill_price, trade.current_targets[0],
                exit_contracts, trade.signal.direction, trade.point_value
            )
            trade.realized_pnl += pnl
            trade.remaining_contracts -= exit_contracts
            events.append("TP1_HIT")

            # Move to breakeven
            if tp_config.move_to_be_after_tp1:
                trade.current_stop = trade.entry_fill_price
                events.append("MOVE_TO_BE")

            # Activate trailing stop
            if sl_config.trail_after_tp1:
                trade.trailing_active = True
                events.append("TRAILING_ACTIVE")

        # Check TP2
        if not trade.tp2_hit and trade.tp1_hit and len(trade.current_targets) > 1:
            if current_bar.high >= trade.current_targets[1]:
                trade.tp2_hit = True
                exit_contracts = int(trade.remaining_contracts * tp_config.tp2_exit_pct)
                if exit_contracts < 1 and trade.remaining_contracts > 0:
                    exit_contracts = 1
                pnl = calculate_exit_pnl(
                    trade.entry_fill_price, trade.current_targets[1],
                    exit_contracts, trade.signal.direction, trade.point_value
                )
                trade.realized_pnl += pnl
                trade.remaining_contracts -= exit_contracts
                events.append("TP2_HIT")

        # Check TP3
        if not trade.tp3_hit and trade.tp2_hit and len(trade.current_targets) > 2:
            if current_bar.high >= trade.current_targets[2]:
                trade.tp3_hit = True
                pnl = calculate_exit_pnl(
                    trade.entry_fill_price, trade.current_targets[2],
                    trade.remaining_contracts, trade.signal.direction, trade.point_value
                )
                trade.realized_pnl += pnl
                trade.remaining_contracts = 0
                trade.status = TradeStatus.CLOSED
                events.append("TP3_HIT")
                events.append("TRADE_CLOSED")

        # Update trailing stop
        if trade.trailing_active and trade.remaining_contracts > 0:
            trail_stop = trade.highest_since_entry - (atr * sl_config.trail_atr_mult)
            if trail_stop > trade.current_stop:
                trade.current_stop = trail_stop
                events.append("TRAILING_STOP_UPDATED")

    else:  # SHORT direction (mirror logic)
        trade.lowest_since_entry = min(
            trade.lowest_since_entry if trade.lowest_since_entry > 0 else current_bar.low,
            current_bar.low
        )

        # Check stop loss
        if current_bar.high >= trade.current_stop:
            # Calculate PnL for remaining contracts at stop price
            pnl = calculate_exit_pnl(
                trade.entry_fill_price, trade.current_stop,
                trade.remaining_contracts, trade.signal.direction, trade.point_value
            )
            trade.realized_pnl += pnl
            trade.remaining_contracts = 0
            trade.status = TradeStatus.CLOSED
            events.append("STOP_LOSS_HIT")
            return events

        # Check TP1
        if not trade.tp1_hit and current_bar.low <= trade.current_targets[0]:
            trade.tp1_hit = True
            exit_contracts = int(trade.remaining_contracts * tp_config.tp1_exit_pct)
            if exit_contracts < 1:
                exit_contracts = 1  # At least 1 contract
            # Calculate PnL for TP1 exit
            pnl = calculate_exit_pnl(
                trade.entry_fill_price, trade.current_targets[0],
                exit_contracts, trade.signal.direction, trade.point_value
            )
            trade.realized_pnl += pnl
            trade.remaining_contracts -= exit_contracts
            events.append("TP1_HIT")

            # Move to breakeven
            if tp_config.move_to_be_after_tp1:
                trade.current_stop = trade.entry_fill_price
                events.append("MOVE_TO_BE")

            # Activate trailing stop
            if sl_config.trail_after_tp1:
                trade.trailing_active = True
                events.append("TRAILING_ACTIVE")

        # Check TP2
        if not trade.tp2_hit and trade.tp1_hit and len(trade.current_targets) > 1:
            if current_bar.low <= trade.current_targets[1]:
                trade.tp2_hit = True
                exit_contracts = int(trade.remaining_contracts * tp_config.tp2_exit_pct)
                if exit_contracts < 1 and trade.remaining_contracts > 0:
                    exit_contracts = 1
                pnl = calculate_exit_pnl(
                    trade.entry_fill_price, trade.current_targets[1],
                    exit_contracts, trade.signal.direction, trade.point_value
                )
                trade.realized_pnl += pnl
                trade.remaining_contracts -= exit_contracts
                events.append("TP2_HIT")

        # Check TP3
        if not trade.tp3_hit and trade.tp2_hit and len(trade.current_targets) > 2:
            if current_bar.low <= trade.current_targets[2]:
                trade.tp3_hit = True
                pnl = calculate_exit_pnl(
                    trade.entry_fill_price, trade.current_targets[2],
                    trade.remaining_contracts, trade.signal.direction, trade.point_value
                )
                trade.realized_pnl += pnl
                trade.remaining_contracts = 0
                trade.status = TradeStatus.CLOSED
                events.append("TP3_HIT")
                events.append("TRADE_CLOSED")

        # Update trailing stop (move down as price falls)
        if trade.trailing_active and trade.remaining_contracts > 0:
            trail_stop = trade.lowest_since_entry + (atr * sl_config.trail_atr_mult)
            if trail_stop < trade.current_stop:
                trade.current_stop = trail_stop
                events.append("TRAILING_STOP_UPDATED")

    # Check if no remaining contracts
    if trade.remaining_contracts <= 0:
        trade.status = TradeStatus.CLOSED
        if "TRADE_CLOSED" not in events:
            events.append("TRADE_CLOSED")

    return events
