"""
Live ICT Strategy Monitor using Yahoo Finance Data

Uses yfinance to get real-time ES/NQ futures data as a backup
when TradingView connection is unavailable.
"""
from __future__ import annotations
import sys
sys.path.insert(0, '.')

import time
from datetime import datetime
import yfinance as yf

from core.types import Bar
from runners.run_today import calculate_ema, calculate_adx, is_in_killzone

# Configuration
SYMBOLS = [
    {"yf_symbol": "ES=F", "name": "ES"},
    {"yf_symbol": "NQ=F", "name": "NQ"},
]
LOOP_INTERVAL_SECONDS = 180  # 3 minutes


def fetch_bars(yf_symbol: str, name: str) -> list[Bar]:
    """Fetch bars from Yahoo Finance."""
    ticker = yf.Ticker(yf_symbol)
    df = ticker.history(period='2d', interval='5m')

    if df is None or len(df) == 0:
        return []

    bars = []
    for idx, row in df.iterrows():
        bar = Bar(
            timestamp=idx.to_pydatetime().replace(tzinfo=None),
            open=float(row['Open']),
            high=float(row['High']),
            low=float(row['Low']),
            close=float(row['Close']),
            volume=int(row['Volume']),
            symbol=name,
            timeframe='5m'
        )
        bars.append(bar)

    return bars


def analyze_market(bars: list[Bar], name: str) -> dict:
    """Analyze current market conditions."""
    if not bars:
        return None

    today = datetime.now().date()
    today_bars = [b for b in bars if b.timestamp.date() == today]

    if len(today_bars) < 10:
        return None

    last_bar = today_bars[-1]

    # Calculate indicators
    ema20 = calculate_ema(today_bars, 20)
    ema50 = calculate_ema(today_bars, 50)
    adx = calculate_adx(today_bars, 14)

    # Determine bias
    if ema20 and ema50:
        bias = "BULLISH" if ema20 > ema50 else "BEARISH"
    else:
        bias = "NEUTRAL"

    # Check if in killzone
    in_kz = is_in_killzone(last_bar.timestamp)

    # Today's range
    day_high = max(b.high for b in today_bars)
    day_low = min(b.low for b in today_bars)
    day_range = day_high - day_low

    return {
        'name': name,
        'price': last_bar.close,
        'time': last_bar.timestamp,
        'bias': bias,
        'ema20': ema20,
        'ema50': ema50,
        'adx': adx,
        'in_killzone': in_kz,
        'day_high': day_high,
        'day_low': day_low,
        'day_range': day_range,
        'bars_today': len(today_bars),
    }


def print_analysis(analysis: dict):
    """Print market analysis."""
    if not analysis:
        return

    name = analysis['name']
    price = analysis['price']
    bias = analysis['bias']
    adx = analysis['adx']
    in_kz = analysis['in_killzone']

    # ADX status
    if adx is None:
        adx_str = "N/A"
        adx_status = ""
    elif adx >= 25:
        adx_str = f"{adx:.1f}"
        adx_status = "STRONG TREND"
    elif adx >= 20:
        adx_str = f"{adx:.1f}"
        adx_status = "TRENDING"
    else:
        adx_str = f"{adx:.1f}"
        adx_status = "CHOPPY - NO TRADE"

    # Killzone status
    kz_str = "IN KILLZONE" if in_kz else "Outside KZ"

    print(f"\n{name}: {price:.2f}")
    print(f"  Bias: {bias} | ADX: {adx_str} {adx_status}")
    print(f"  Killzone: {kz_str}")
    print(f"  Day Range: {analysis['day_low']:.2f} - {analysis['day_high']:.2f} ({analysis['day_range']:.2f} pts)")

    # Trade recommendation
    if adx and adx >= 20 and in_kz:
        print(f"  >> TRADEABLE: Look for {bias} FVG setups")
    elif adx and adx < 20:
        print("  >> AVOID: Market is choppy (ADX < 20)")
    elif not in_kz:
        print("  >> WAIT: Outside killzone hours")


def run_scan():
    """Run one scan cycle."""
    print("\n" + "=" * 60)
    print(f"Scan @ {datetime.now().strftime('%H:%M:%S')}")
    print("-" * 60)

    for sym in SYMBOLS:
        try:
            bars = fetch_bars(sym['yf_symbol'], sym['name'])
            if bars:
                analysis = analyze_market(bars, sym['name'])
                if analysis:
                    print_analysis(analysis)
                else:
                    print(f"\n{sym['name']}: Not enough data")
            else:
                print(f"\n{sym['name']}: No data")
        except Exception as e:
            print(f"\n{sym['name']}: Error - {e}")

    print(f"\nNext scan in {LOOP_INTERVAL_SECONDS // 60} minutes...")


def main():
    print("=" * 60)
    print("ICT Strategy - Live Monitor (Yahoo Finance)")
    print("=" * 60)
    print("Connecting to Yahoo Finance...")

    # Test connection
    try:
        test = yf.Ticker("ES=F")
        data = test.history(period='1d', interval='5m')
        if data is not None and len(data) > 0:
            print(f"Connected! ES: {data['Close'].iloc[-1]:.2f}")
        else:
            print("Warning: No data received")
    except Exception as e:
        print(f"Connection error: {e}")
        return

    print("Starting continuous monitoring (Ctrl+C to stop)...")

    try:
        while True:
            run_scan()
            time.sleep(LOOP_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n\nStopped by user.")
        print("=" * 60)


if __name__ == "__main__":
    main()
