"""
Compare OTE Zone configurations: 50-79% vs 62-79% (golden pocket).

Tests on a single symbol to measure impact of tighter entry zone.
"""
from __future__ import annotations
import logging
from datetime import datetime
from dataclasses import dataclass
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict_sweep_ote import ICTSweepOTEStrategy, StrategyConfig
from strategies.ict_sweep_ote.signals import TradeStatus

logging.basicConfig(level=logging.WARNING, format='%(name)s: %(message)s')


@dataclass
class BacktestResult:
    """Backtest result summary."""
    config_name: str
    ote_lower: float
    ote_upper: float
    total_bars: int
    total_days: int
    signals: int
    trades: int
    wins: int
    losses: int
    total_pnl: float

    @property
    def win_rate(self) -> float:
        return (self.wins / self.trades * 100) if self.trades > 0 else 0

    @property
    def avg_pnl_per_trade(self) -> float:
        return self.total_pnl / self.trades if self.trades > 0 else 0


def run_backtest_with_config(
    symbol: str,
    interval: str,
    n_bars: int,
    ote_lower: float,
    ote_upper: float,
    config_name: str,
) -> BacktestResult:
    """Run backtest with specific OTE zone configuration."""

    # Fetch data
    bars = fetch_futures_bars(
        symbol=symbol,
        interval=interval,
        n_bars=n_bars,
    )

    if not bars:
        print(f"No data for {symbol}")
        return None

    # Calculate days
    first_date = bars[0].timestamp.date()
    last_date = bars[-1].timestamp.date()
    total_days = (last_date - first_date).days

    # Create strategy with custom OTE config
    config = StrategyConfig(
        symbol=symbol,
        timeframe=interval,
    )
    # Apply OTE zone settings
    config.ote.ote_fib_lower = ote_lower
    config.ote.ote_fib_upper = ote_upper
    config.ote.require_ote_entry = True  # REQUIRE entry in OTE zone

    # Adjust MSS lookback for higher timeframes
    if interval in ["15m", "30m", "1h"]:
        config.mss.max_bars_after_sweep = 15
        config.mss.lh_lookback_bars = 25

    # Increase max SL ATR multiple to allow more trades
    config.stop_loss.max_sl_atr_mult = 6.0

    # Point value for equities
    point_value = 1.0  # $1 per point for stocks

    strategy = ICTSweepOTEStrategy(config=config, equity=100000)

    # Run strategy
    signals = []
    completed_trades = []

    for bar in bars:
        signal = strategy.on_bar(bar)
        if signal:
            signals.append(signal)

    # Get completed trades from strategy
    completed_trades = [t for t in strategy.closed_trades]

    # Calculate results
    wins = sum(1 for t in completed_trades if t.realized_pnl > 0)
    losses = sum(1 for t in completed_trades if t.realized_pnl <= 0)
    total_pnl = sum(t.realized_pnl for t in completed_trades)

    return BacktestResult(
        config_name=config_name,
        ote_lower=ote_lower,
        ote_upper=ote_upper,
        total_bars=len(bars),
        total_days=total_days,
        signals=len(signals),
        trades=len(completed_trades),
        wins=wins,
        losses=losses,
        total_pnl=total_pnl,
    )


def compare_ote_zones(symbol: str, interval: str, n_bars: int = 5000):
    """Compare baseline vs golden pocket OTE zones."""

    print("=" * 70)
    print(f"OTE ZONE COMPARISON: {symbol} {interval}")
    print("=" * 70)

    # Configuration A: Baseline (50-79%)
    print("\nRunning Baseline (50-79% OTE)...")
    baseline = run_backtest_with_config(
        symbol=symbol,
        interval=interval,
        n_bars=n_bars,
        ote_lower=0.50,
        ote_upper=0.79,
        config_name="Baseline (50-79%)",
    )

    # Configuration B: Golden Pocket (62-79%)
    print("Running Golden Pocket (62-79% OTE)...")
    golden = run_backtest_with_config(
        symbol=symbol,
        interval=interval,
        n_bars=n_bars,
        ote_lower=0.62,
        ote_upper=0.79,
        config_name="Golden Pocket (62-79%)",
    )

    # Display comparison
    print("\n" + "=" * 70)
    print("RESULTS COMPARISON")
    print("=" * 70)

    print(f"\nData: {baseline.total_bars} bars over {baseline.total_days} days")
    print()

    header = f"{'Config':<25} | {'Signals':>7} | {'Trades':>6} | {'W/L':>7} | {'Win%':>6} | {'PnL':>12}"
    print(header)
    print("-" * len(header))

    for result in [baseline, golden]:
        wl = f"{result.wins}/{result.losses}"
        print(f"{result.config_name:<25} | {result.signals:>7} | {result.trades:>6} | {wl:>7} | {result.win_rate:>5.1f}% | ${result.total_pnl:>10.2f}")

    # Delta analysis
    print("\n" + "-" * 70)
    print("DELTA (Golden Pocket vs Baseline)")
    print("-" * 70)

    if baseline.trades > 0 and golden.trades > 0:
        signal_delta = golden.signals - baseline.signals
        trade_delta = golden.trades - baseline.trades
        wr_delta = golden.win_rate - baseline.win_rate
        pnl_delta = golden.total_pnl - baseline.total_pnl

        print(f"  Signals:  {signal_delta:+d} ({signal_delta/baseline.signals*100:+.1f}%)")
        print(f"  Trades:   {trade_delta:+d} ({trade_delta/baseline.trades*100:+.1f}%)")
        print(f"  Win Rate: {wr_delta:+.1f}%")
        print(f"  PnL:      ${pnl_delta:+.2f}")

        if golden.trades > 0 and baseline.trades > 0:
            avg_baseline = baseline.total_pnl / baseline.trades
            avg_golden = golden.total_pnl / golden.trades
            print(f"\n  Avg PnL/Trade (Baseline): ${avg_baseline:.2f}")
            print(f"  Avg PnL/Trade (Golden):   ${avg_golden:.2f}")

    return baseline, golden


if __name__ == "__main__":
    # Test on MSFT 1h - had 77% win rate, good sample size
    print("\n>>> TEST 1: MSFT 1h <<<\n")
    compare_ote_zones("MSFT", "1h", n_bars=5000)

    # Also test on AMD 15m - had lower win rate, might benefit more
    print("\n\n>>> TEST 2: AMD 15m <<<\n")
    compare_ote_zones("AMD", "15m", n_bars=5000)

    # Test on ES futures
    print("\n\n>>> TEST 3: ES 1h <<<\n")
    compare_ote_zones("ES", "1h", n_bars=5000)
