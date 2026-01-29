"""
Compare Stop Loss configurations: Structure-based vs ATR-based.

Current: Stop at swing high/low + buffer (can be far)
Test: Tighter ATR-based stops (1.5x, 2x, 2.5x ATR)
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
    max_sl_atr: float
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
    max_sl_atr_mult: float,
    config_name: str,
) -> BacktestResult:
    """Run backtest with specific stop loss configuration."""

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

    # Create strategy with custom SL config
    config = StrategyConfig(
        symbol=symbol,
        timeframe=interval,
    )

    # Apply OTE settings (require entry in OTE zone)
    config.ote.require_ote_entry = True

    # Apply stop loss settings - this is the key parameter
    config.stop_loss.max_sl_atr_mult = max_sl_atr_mult

    # Adjust MSS lookback for higher timeframes
    if interval in ["15m", "30m", "1h"]:
        config.mss.max_bars_after_sweep = 15
        config.mss.lh_lookback_bars = 25

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
        max_sl_atr=max_sl_atr_mult,
        total_bars=len(bars),
        total_days=total_days,
        signals=len(signals),
        trades=len(completed_trades),
        wins=wins,
        losses=losses,
        total_pnl=total_pnl,
    )


def compare_stop_loss(symbol: str, interval: str, n_bars: int = 5000):
    """Compare different stop loss ATR multipliers."""

    print("=" * 70)
    print(f"STOP LOSS COMPARISON: {symbol} {interval}")
    print("=" * 70)

    # Test different max SL ATR multipliers
    # Lower = tighter stops (more trades filtered out, but smaller losses)
    # Higher = wider stops (more trades allowed, but larger potential losses)

    configs = [
        (2.0, "Tight (2x ATR)"),
        (3.0, "Medium (3x ATR)"),
        (4.0, "Standard (4x ATR)"),
        (6.0, "Wide (6x ATR)"),
    ]

    results = []
    for max_atr, name in configs:
        print(f"Running {name}...")
        result = run_backtest_with_config(
            symbol=symbol,
            interval=interval,
            n_bars=n_bars,
            max_sl_atr_mult=max_atr,
            config_name=name,
        )
        if result:
            results.append(result)

    # Display comparison
    print("\n" + "=" * 70)
    print("RESULTS COMPARISON")
    print("=" * 70)

    if results:
        print(f"\nData: {results[0].total_bars} bars over {results[0].total_days} days")
        print()

        header = f"{'Config':<20} | {'MaxATR':>6} | {'Sigs':>5} | {'Trades':>6} | {'W/L':>7} | {'Win%':>6} | {'PnL':>12} | {'Avg':>10}"
        print(header)
        print("-" * len(header))

        for result in results:
            wl = f"{result.wins}/{result.losses}"
            print(f"{result.config_name:<20} | {result.max_sl_atr:>6.1f} | {result.signals:>5} | {result.trades:>6} | {wl:>7} | {result.win_rate:>5.1f}% | ${result.total_pnl:>10.2f} | ${result.avg_pnl_per_trade:>9.2f}")

        # Find best config
        print("\n" + "-" * 70)
        print("ANALYSIS")
        print("-" * 70)

        best_wr = max(results, key=lambda r: r.win_rate)
        best_pnl = max(results, key=lambda r: r.total_pnl)
        best_avg = max(results, key=lambda r: r.avg_pnl_per_trade)

        print(f"  Best Win Rate:     {best_wr.config_name} ({best_wr.win_rate:.1f}%)")
        print(f"  Best Total PnL:    {best_pnl.config_name} (${best_pnl.total_pnl:.2f})")
        print(f"  Best Avg/Trade:    {best_avg.config_name} (${best_avg.avg_pnl_per_trade:.2f})")

    return results


if __name__ == "__main__":
    # Test on MSFT 1h - good sample from previous test
    print("\n>>> TEST 1: MSFT 1h <<<\n")
    compare_stop_loss("MSFT", "1h", n_bars=5000)

    # Test on ES 1h - futures
    print("\n\n>>> TEST 2: ES 1h <<<\n")
    compare_stop_loss("ES", "1h", n_bars=5000)

    # Test on AMD 15m
    print("\n\n>>> TEST 3: AMD 15m <<<\n")
    compare_stop_loss("AMD", "15m", n_bars=5000)
