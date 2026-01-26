"""
ICT_Sweep_OTE_MSS_FVG Strategy Package (Long & Short)

A complete ICT (Inner Circle Trader) strategy implementation for ES/NQ futures.

Signal Flow (Long):
    swing_low → ssl_sweep → bullish_mss → bullish_fvg → long_entry

Signal Flow (Short):
    swing_high → bsl_sweep → bearish_mss → bearish_fvg → short_entry

Modules:
    - config: Strategy configuration dataclasses
    - detectors: Signal detection functions (swings, sweep, MSS, FVG, OTE)
    - signals: Trade signal and position management
    - strategy: Main strategy state machine
    - risk_manager: Position sizing and risk limits
    - broker_adapter: Abstract broker interface
    - alerts: Notification system
    - tests: Unit tests with synthetic data

Usage:
    from strategies.ict_sweep_ote import ICTSweepOTEStrategy, StrategyConfig

    config = StrategyConfig(symbol="ES", timeframe="3m")
    strategy = ICTSweepOTEStrategy(config=config, equity=100000)

    for bar in bars:
        signal = strategy.on_bar(bar)
        if signal:
            print(f"SIGNAL: {signal.direction} @ {signal.entry_price}")
"""

from strategies.ict_sweep_ote.config import (
    StrategyConfig,
    SwingConfig,
    SweepConfig,
    MSSConfig,
    DisplacementConfig,
    FVGConfig,
    OTEConfig,
    StopLossConfig,
    TakeProfitConfig,
    RiskConfig,
    FilterConfig,
    load_config_from_yaml,
)

from strategies.ict_sweep_ote.detectors import (
    SwingPoint,
    SwingType,
    SSLSweep,
    BSLSweep,
    LowerHigh,
    HigherLow,
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
)

from strategies.ict_sweep_ote.signals import (
    TradeSignal,
    OpenTrade,
    SignalDirection,
    TradeStatus,
    build_trade_signal,
)

from strategies.ict_sweep_ote.strategy import (
    ICTSweepOTEStrategy,
    StrategyState,
    create_strategy,
)

from strategies.ict_sweep_ote.risk_manager import (
    RiskManager,
    RiskState,
    DailyStats,
)

from strategies.ict_sweep_ote.broker_adapter import (
    BrokerAdapter,
    PaperBroker,
    Order,
    OrderType,
    OrderStatus,
    OrderSide,
    Position,
    AccountInfo,
)

from strategies.ict_sweep_ote.alerts import (
    AlertManager,
    Alert,
    AlertLevel,
    ConsoleAlertHandler,
    FileAlertHandler,
    WebhookAlertHandler,
    setup_logging,
)

__all__ = [
    # Config
    "StrategyConfig",
    "SwingConfig",
    "SweepConfig",
    "MSSConfig",
    "DisplacementConfig",
    "FVGConfig",
    "OTEConfig",
    "StopLossConfig",
    "TakeProfitConfig",
    "RiskConfig",
    "FilterConfig",
    "load_config_from_yaml",
    # Detectors
    "SwingPoint",
    "SwingType",
    "SSLSweep",
    "BSLSweep",
    "LowerHigh",
    "HigherLow",
    "MSSEvent",
    "FVGZone",
    "OTEZone",
    "DisplacementCandle",
    "detect_swings",
    "detect_ssl_sweep",
    "confirm_ssl_sweep",
    "detect_bsl_sweep",
    "confirm_bsl_sweep",
    "detect_mss",
    "detect_bearish_mss",
    "detect_displacement_fvg",
    "calculate_ote_zone",
    "calculate_atr",
    # Signals
    "TradeSignal",
    "OpenTrade",
    "SignalDirection",
    "TradeStatus",
    "build_trade_signal",
    # Strategy
    "ICTSweepOTEStrategy",
    "StrategyState",
    "create_strategy",
    # Risk
    "RiskManager",
    "RiskState",
    "DailyStats",
    # Broker
    "BrokerAdapter",
    "PaperBroker",
    "Order",
    "OrderType",
    "OrderStatus",
    "OrderSide",
    "Position",
    "AccountInfo",
    # Alerts
    "AlertManager",
    "Alert",
    "AlertLevel",
    "ConsoleAlertHandler",
    "FileAlertHandler",
    "WebhookAlertHandler",
    "setup_logging",
]

__version__ = "1.0.0"
__author__ = "ICT Strategy Team"
