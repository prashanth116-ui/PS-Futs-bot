"""
Backtest ICT Strategy for a specific trading session.

Uses Yahoo Finance data (15-min delayed but free).
"""
from __future__ import annotations
from datetime import datetime, date
from runners.yfinance_loader import fetch_futures_bars
from strategies.factory import build_ict_from_yaml


def run_backtest(symbols: list[str], session_date: date, interval: str = "5m"):
    """Run backtest for given symbols on a specific date."""
    print("=" * 70)
    print(f"ICT Strategy Backtest - {session_date}")
    print("=" * 70)

    config_path = "config/strategies/ict_es.yaml"
    strategy = build_ict_from_yaml(config_path)

    all_results = []

    for symbol in symbols:
        yf_symbol = f"{symbol}=F"
        print(f"\n{'='*70}")
        print(f"SYMBOL: {symbol}")
        print(f"{'='*70}")

        # Fetch data (1d gets today's session)
        print(f"Fetching {interval} data for {symbol}...")
        bars = fetch_futures_bars(yf_symbol, period="1d", interval=interval)

        if not bars:
            print(f"  No data for {symbol}")
            continue

        # Filter to session date only
        session_bars = [b for b in bars if b.timestamp.date() == session_date]

        if not session_bars:
            # Try using all bars if date filter returns nothing
            session_bars = bars
            print(f"  Using all available bars: {len(session_bars)}")
        else:
            print(f"  Session bars: {len(session_bars)}")

        if session_bars:
            print(f"  Time range: {session_bars[0].timestamp} to {session_bars[-1].timestamp}")
            print(f"  Open: {session_bars[0].open:.2f} | Close: {session_bars[-1].close:.2f}")

            # Calculate session stats
            session_high = max(b.high for b in session_bars)
            session_low = min(b.low for b in session_bars)
            session_range = session_high - session_low
            print(f"  High: {session_high:.2f} | Low: {session_low:.2f} | Range: {session_range:.2f} pts")

        # Reset strategy state for clean run
        strategy = build_ict_from_yaml(config_path)

        # Run strategy
        print(f"\n  Processing {len(session_bars)} bars through ICT strategy...")
        signals = []

        for bar in session_bars:
            signal = strategy.on_bar(bar)
            if signal:
                # Handle list signals
                if isinstance(signal, list):
                    for s in signal:
                        if s:
                            signals.append((bar.timestamp, s))
                else:
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
                print(f"    Targets:   {sig.targets}")

                # Calculate R:R for first target
                if sig.targets:
                    risk = abs(sig.entry_price - sig.stop_price)
                    reward = abs(sig.targets[0] - sig.entry_price)
                    rr = reward / risk if risk > 0 else 0
                    print(f"    Risk:      {risk:.2f} pts")
                    print(f"    R:R (T1):  {rr:.2f}")

                if isinstance(sig.reason, dict):
                    print(f"    Session:   {sig.reason.get('session', 'N/A')}")
                    print(f"    Setup:     {sig.reason.get('setup', 'N/A')}")
        else:
            print("  No signals generated.")

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
    symbols = ["ES", "NQ"]

    # Use 2-minute bars for more granular entries
    run_backtest(symbols, today, interval="2m")
