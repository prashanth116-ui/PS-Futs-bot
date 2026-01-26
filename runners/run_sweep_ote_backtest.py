"""
Backtest ICT_Sweep_OTE_MSS_FVG Strategy.

Uses TradingView data via tvDatafeed.
"""
from __future__ import annotations
import logging
from datetime import datetime, date, timedelta
from runners.tradingview_loader import fetch_rth_bars
from strategies.ict_sweep_ote import ICTSweepOTEStrategy, StrategyConfig

# Enable logging
logging.basicConfig(level=logging.INFO, format='%(name)s: %(message)s')


def run_backtest(symbols: list[str], session_date: date, interval: str = "3m"):
    """Run backtest for given symbols on a specific date."""
    print("=" * 70)
    print(f"ICT Sweep+OTE+MSS+FVG Strategy Backtest - {session_date}")
    print("=" * 70)

    all_results = []

    for symbol in symbols:
        print(f"\n{'='*70}")
        print(f"SYMBOL: {symbol}")
        print(f"{'='*70}")

        # Fetch RTH data from TradingView
        print(f"Fetching {interval} data for {symbol} from TradingView...")
        session_bars = fetch_rth_bars(
            symbol=symbol,
            interval=interval,
            n_bars=1000,
            target_date=session_date,
        )

        if not session_bars:
            print(f"  No data for {symbol}")
            continue

        print(f"  RTH bars: {len(session_bars)}")

        if session_bars:
            print(f"  Time range: {session_bars[0].timestamp} to {session_bars[-1].timestamp}")
            print(f"  Open: {session_bars[0].open:.2f} | Close: {session_bars[-1].close:.2f}")

            # Calculate session stats
            session_high = max(b.high for b in session_bars)
            session_low = min(b.low for b in session_bars)
            session_range = session_high - session_low
            print(f"  High: {session_high:.2f} | Low: {session_low:.2f} | Range: {session_range:.2f} pts")

        # Create strategy with config for this symbol
        config = StrategyConfig(
            symbol=symbol,
            timeframe=interval,
        )
        # Increase MSS lookback window for more opportunities
        config.mss.max_bars_after_sweep = 20
        config.mss.lh_lookback_bars = 30
        strategy = ICTSweepOTEStrategy(config=config, equity=100000)

        # Run strategy
        print(f"\n  Processing {len(session_bars)} bars through ICT Sweep+OTE strategy...")
        signals = []

        for bar in session_bars:
            signal = strategy.on_bar(bar)
            if signal:
                signals.append((bar.timestamp, signal))

        # Results
        print(f"\n  {'-'*60}")
        print(f"  SIGNALS: {len(signals)}")
        print(f"  {'-'*60}")

        if signals:
            for i, (ts, sig) in enumerate(signals, 1):
                print(f"\n  Signal {i}: {ts.strftime('%H:%M:%S')}")
                print(f"    Direction: {sig.direction.value}")
                print(f"    Entry:     {sig.entry_price:.2f}")
                print(f"    Stop:      {sig.stop_price:.2f}")
                print(f"    Targets:   {[f'{t:.2f}' for t in sig.targets]}")
                print(f"    Size:      {sig.position_size} contracts")

                # Calculate R:R for first target
                if sig.targets:
                    risk = abs(sig.entry_price - sig.stop_price)
                    reward = abs(sig.targets[0] - sig.entry_price)
                    rr = reward / risk if risk > 0 else 0
                    print(f"    Risk:      {risk:.2f} pts")
                    print(f"    R:R (T1):  {rr:.2f}")

                if sig.reason:
                    print(f"    Setup:     {sig.reason.get('setup', 'N/A')}")
                    print(f"    In OTE:    {sig.reason.get('in_ote', False)}")
                    print(f"    In Discount: {sig.reason.get('in_discount', False)}")
        else:
            print("  No signals generated.")

        # Show strategy state info
        print(f"\n  Strategy State: {strategy.state.value}")
        print(f"  Swings detected: {len(strategy.swings)}")
        print(f"  Active FVGs: {len(strategy.active_fvgs)}")

        # Show context if in middle of setup
        if strategy.context.sweep:
            print(f"  Last sweep: {strategy.context.sweep.sweep_bar_timestamp.strftime('%H:%M')} "
                  f"@ {strategy.context.sweep.sweep_low:.2f}")
        if strategy.context.mss:
            print(f"  MSS confirmed: {strategy.context.mss.break_bar_timestamp.strftime('%H:%M')}")
        if strategy.context.fvg:
            print(f"  FVG: {strategy.context.fvg.bottom:.2f} - {strategy.context.fvg.top:.2f}")

        all_results.append({
            "symbol": symbol,
            "bars": len(session_bars),
            "signals": signals,
            "high": session_high if session_bars else 0,
            "low": session_low if session_bars else 0,
        })

    # Summary
    print("\n" + "=" * 70)
    print("BACKTEST SUMMARY")
    print("=" * 70)

    total_signals = sum(len(r["signals"]) for r in all_results)
    print(f"Date: {session_date}")
    print(f"Symbols: {', '.join(symbols)}")
    print(f"Total Signals: {total_signals}")

    for r in all_results:
        sig_count = len(r["signals"])
        print(f"  {r['symbol']}: {r['bars']} bars, {sig_count} signals")

    return all_results


if __name__ == "__main__":
    # Backtest today's session
    today = date.today()
    yesterday = today - timedelta(days=1)
    symbols = ["ES", "NQ"]

    # Use 3-minute bars (TradingView native)
    print("\n>>> RUNNING TODAY'S BACKTEST <<<\n")
    run_backtest(symbols, today, interval="3m")

    print("\n\n>>> RUNNING YESTERDAY'S BACKTEST <<<\n")
    run_backtest(symbols, yesterday, interval="3m")
