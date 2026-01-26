"""
ICT_Sweep_OTE_MSS_FVG_Long_v1 - Configuration

All parameters for the ICT Sweep + OTE + MSS + FVG strategy.
Configurable via YAML or direct instantiation.
"""
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class SwingConfig:
    """Swing point detection parameters."""
    # Fractal pivot lookback: swing low if low[i] is min of [i-L, i+L]
    left_bars: int = 2
    right_bars: int = 2
    # Minimum bars between swing points
    min_swing_distance: int = 3


@dataclass
class SweepConfig:
    """Sell-side liquidity sweep parameters."""
    # Minimum penetration below swing low to qualify as sweep
    # Can be percentage of price or ATR multiple
    sweep_buffer_pct: float = 0.0005  # 0.05% of price
    sweep_buffer_atr_mult: float = 0.1  # OR 0.1 * ATR
    use_atr_buffer: bool = True  # If True, use ATR; else use pct

    # Sweep confirmation: price must close back above swept level
    require_close_above: bool = True
    # Allow next candle to confirm (close above)
    allow_next_bar_confirm: bool = True

    # Maximum bars to wait for sweep confirmation
    max_bars_for_confirm: int = 2


@dataclass
class MSSConfig:
    """Market Structure Shift parameters."""
    # Lookback for finding lower-high pivot before sweep
    lh_lookback_bars: int = 20

    # MSS confirmation: require close above LH (not just wick)
    require_close_above: bool = True

    # Maximum bars after sweep to detect MSS
    max_bars_after_sweep: int = 10


@dataclass
class DisplacementConfig:
    """Displacement candle parameters."""
    # Minimum body size as multiple of ATR(14)
    min_body_atr_mult: float = 0.8

    # OR minimum body as multiple of median body (last 20 bars)
    min_body_median_mult: float = 1.5

    # Use ATR method (True) or median body method (False)
    use_atr_method: bool = True

    # ATR period for calculations
    atr_period: int = 14

    # Median body lookback
    median_body_period: int = 20


@dataclass
class FVGConfig:
    """Fair Value Gap parameters."""
    # Minimum FVG size in ATR multiple
    min_fvg_atr_mult: float = 0.2

    # Minimum FVG size in price (absolute)
    min_fvg_price: float = 0.0

    # Maximum age of FVG before it expires (bars)
    max_fvg_age_bars: int = 50

    # Entry mode: FIRST_TOUCH, MIDPOINT, or LOWER_EDGE
    entry_mode: Literal["FIRST_TOUCH", "MIDPOINT", "LOWER_EDGE"] = "MIDPOINT"

    # Require bullish rejection candle on FVG touch
    require_rejection_candle: bool = True

    # Maximum bars to wait for FVG retrace after displacement
    max_bars_for_retrace: int = 20


@dataclass
class OTEConfig:
    """Optimal Trade Entry (Fibonacci) parameters."""
    # OTE zone boundaries (fib retracement from sweep_low to swing_high)
    ote_fib_lower: float = 0.50  # 50% retrace
    ote_fib_upper: float = 0.79  # 79% retrace

    # Discount zone boundary (max fib level for "discount")
    discount_fib_max: float = 0.50  # Must be in discount (<= 50%)

    # Require entry in OTE zone
    require_ote_entry: bool = False

    # Bonus priority if FVG overlaps OTE
    fvg_ote_overlap_bonus: bool = True


@dataclass
class StopLossConfig:
    """Stop loss parameters."""
    # SL buffer below sweep low
    sl_buffer_atr_mult: float = 0.2
    sl_buffer_fixed: float = 0.0  # Fixed price buffer (if > 0, use this)

    # Maximum SL distance in ATR (skip trade if exceeded)
    max_sl_atr_mult: float = 3.0

    # Trail stop after TP1
    trail_after_tp1: bool = True
    trail_atr_mult: float = 1.5


@dataclass
class TakeProfitConfig:
    """Take profit parameters."""
    # TP1: Internal high after MSS or nearest swing high
    # TP2: Most recent swing high before sweep (buy-side liquidity)
    # TP3: Fib extension

    tp1_type: Literal["INTERNAL_HIGH", "NEAREST_SWING_HIGH"] = "NEAREST_SWING_HIGH"
    tp2_type: Literal["BSL", "SWING_HIGH"] = "BSL"  # Buy-side liquidity
    tp3_fib_ext: float = 1.618  # 161.8% extension

    # Minimum R:R requirements (use R-multiples if swings are too close)
    min_tp1_r_mult: float = 1.0   # TP1 must be at least 1R
    min_tp2_r_mult: float = 2.0   # TP2 must be at least 2R
    min_tp3_r_mult: float = 3.0   # TP3 must be at least 3R

    # Partial exit percentages
    tp1_exit_pct: float = 0.50  # Exit 50% at TP1
    tp2_exit_pct: float = 0.30  # Exit 30% at TP2
    tp3_exit_pct: float = 0.20  # Exit 20% at TP3 (runner)

    # Move SL to breakeven after TP1
    move_to_be_after_tp1: bool = True


@dataclass
class RiskConfig:
    """Risk management parameters."""
    # Risk per trade as percentage of equity
    risk_per_trade_pct: float = 0.01  # 1%

    # Maximum concurrent positions
    max_positions: int = 1

    # Maximum daily loss before stopping
    max_daily_loss_pct: float = 0.03  # 3%

    # Cooldown bars after trade (before new sweep)
    cooldown_bars: int = 5

    # Maximum spread as percentage of ATR
    max_spread_atr_pct: float = 0.5


@dataclass
class FilterConfig:
    """No-trade filters."""
    # Skip if volatility too high (ATR > X * median ATR)
    max_atr_mult: float = 2.0

    # Skip if volatility too low (ATR < X * median ATR)
    min_atr_mult: float = 0.3

    # Skip if buy-side liquidity already taken
    skip_if_bsl_taken: bool = True

    # Higher timeframe trend filter (optional)
    use_htf_filter: bool = False
    htf_timeframe: str = "1h"
    htf_trend_method: Literal["EMA", "SWING"] = "EMA"
    htf_ema_period: int = 50


@dataclass
class StrategyConfig:
    """
    Master configuration for ICT_Sweep_OTE_MSS_FVG_Long_v1.

    Combines all sub-configurations into one object.
    """
    # Strategy identification
    name: str = "ICT_Sweep_OTE_MSS_FVG_Long_v1"
    version: str = "1.0.0"

    # Primary timeframe
    timeframe: str = "15m"

    # Symbol (can be futures, stocks, crypto)
    symbol: str = "ES"

    # Sub-configurations
    swing: SwingConfig = field(default_factory=SwingConfig)
    sweep: SweepConfig = field(default_factory=SweepConfig)
    mss: MSSConfig = field(default_factory=MSSConfig)
    displacement: DisplacementConfig = field(default_factory=DisplacementConfig)
    fvg: FVGConfig = field(default_factory=FVGConfig)
    ote: OTEConfig = field(default_factory=OTEConfig)
    stop_loss: StopLossConfig = field(default_factory=StopLossConfig)
    take_profit: TakeProfitConfig = field(default_factory=TakeProfitConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)

    # Logging
    log_level: str = "INFO"
    log_trades: bool = True
    log_signals: bool = True

    # Alerts
    enable_alerts: bool = True
    alert_on_sweep: bool = True
    alert_on_mss: bool = True
    alert_on_entry: bool = True


def load_config_from_yaml(path: str) -> StrategyConfig:
    """Load configuration from YAML file."""
    import yaml

    with open(path, 'r') as f:
        data = yaml.safe_load(f)

    config = StrategyConfig()

    # Map YAML sections to config objects
    if 'swing' in data:
        config.swing = SwingConfig(**data['swing'])
    if 'sweep' in data:
        config.sweep = SweepConfig(**data['sweep'])
    if 'mss' in data:
        config.mss = MSSConfig(**data['mss'])
    if 'displacement' in data:
        config.displacement = DisplacementConfig(**data['displacement'])
    if 'fvg' in data:
        config.fvg = FVGConfig(**data['fvg'])
    if 'ote' in data:
        config.ote = OTEConfig(**data['ote'])
    if 'stop_loss' in data:
        config.stop_loss = StopLossConfig(**data['stop_loss'])
    if 'take_profit' in data:
        config.take_profit = TakeProfitConfig(**data['take_profit'])
    if 'risk' in data:
        config.risk = RiskConfig(**data['risk'])
    if 'filters' in data:
        config.filters = FilterConfig(**data['filters'])

    # Top-level params
    for key in ['name', 'version', 'timeframe', 'symbol', 'log_level']:
        if key in data:
            setattr(config, key, data[key])

    return config
