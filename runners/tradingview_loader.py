"""
TradingView Data Loader

Uses tradingview-ta library for real-time technical analysis data.
Note: Free API has limited symbol access (stocks/ETFs work, futures limited)
"""
from __future__ import annotations
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
from tradingview_ta import TA_Handler, Interval


@dataclass
class TVData:
    """TradingView real-time data."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    recommendation: str
    buy_signals: int
    sell_signals: int
    neutral_signals: int
    rsi: Optional[float] = None
    macd: Optional[float] = None
    ema20: Optional[float] = None
    ema50: Optional[float] = None
    ema200: Optional[float] = None


# Symbol mappings for futures to ETF proxies
FUTURES_TO_ETF = {
    "ES": ("SPY", "AMEX", "america"),      # S&P 500
    "NQ": ("QQQ", "NASDAQ", "america"),    # Nasdaq 100
    "YM": ("DIA", "AMEX", "america"),      # Dow Jones
    "RTY": ("IWM", "AMEX", "america"),     # Russell 2000
    "CL": ("USO", "AMEX", "america"),      # Crude Oil
    "GC": ("GLD", "AMEX", "america"),      # Gold
}

INTERVAL_MAP = {
    "1m": Interval.INTERVAL_1_MINUTE,
    "5m": Interval.INTERVAL_5_MINUTES,
    "15m": Interval.INTERVAL_15_MINUTES,
    "30m": Interval.INTERVAL_30_MINUTES,
    "1h": Interval.INTERVAL_1_HOUR,
    "4h": Interval.INTERVAL_4_HOURS,
    "1d": Interval.INTERVAL_1_DAY,
    "1w": Interval.INTERVAL_1_WEEK,
    "1M": Interval.INTERVAL_1_MONTH,
}


def get_tradingview_data(
    symbol: str = "ES",
    interval: str = "5m"
) -> Optional[TVData]:
    """
    Get real-time data from TradingView.

    Args:
        symbol: Futures symbol (ES, NQ, etc.) - will use ETF proxy
        interval: Timeframe (1m, 5m, 15m, 30m, 1h, 4h, 1d)

    Returns:
        TVData object or None if failed
    """
    # Map futures to ETF proxy
    if symbol.upper() in FUTURES_TO_ETF:
        etf_symbol, exchange, screener = FUTURES_TO_ETF[symbol.upper()]
    else:
        # Try using the symbol directly
        etf_symbol = symbol
        exchange = "AMEX"
        screener = "america"

    tv_interval = INTERVAL_MAP.get(interval, Interval.INTERVAL_5_MINUTES)

    try:
        handler = TA_Handler(
            symbol=etf_symbol,
            exchange=exchange,
            screener=screener,
            interval=tv_interval
        )

        analysis = handler.get_analysis()
        indicators = analysis.indicators
        summary = analysis.summary

        return TVData(
            symbol=symbol,
            timestamp=datetime.now(),
            open=float(indicators.get("open", 0)),
            high=float(indicators.get("high", 0)),
            low=float(indicators.get("low", 0)),
            close=float(indicators.get("close", 0)),
            volume=int(indicators.get("volume", 0)),
            recommendation=summary.get("RECOMMENDATION", "NEUTRAL"),
            buy_signals=summary.get("BUY", 0),
            sell_signals=summary.get("SELL", 0),
            neutral_signals=summary.get("NEUTRAL", 0),
            rsi=indicators.get("RSI"),
            macd=indicators.get("MACD.macd"),
            ema20=indicators.get("EMA20"),
            ema50=indicators.get("EMA50"),
            ema200=indicators.get("EMA200"),
        )

    except Exception as e:
        print(f"TradingView error for {symbol}: {e}")
        return None


def print_market_overview():
    """Print overview of major markets."""
    print("=" * 60)
    print("TradingView Market Overview")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)

    symbols = ["ES", "NQ", "YM", "RTY"]

    for symbol in symbols:
        data = get_tradingview_data(symbol, "5m")
        if data:
            etf = FUTURES_TO_ETF.get(symbol, (symbol,))[0]
            rsi_str = f"{data.rsi:.1f}" if data.rsi else "N/A"
            print(f"{symbol} ({etf}): ${data.close:.2f} | {data.recommendation} | RSI: {rsi_str}")
        else:
            print(f"{symbol}: Error fetching data")

    print("-" * 60)


if __name__ == "__main__":
    print_market_overview()

    print("\nDetailed ES data:")
    data = get_tradingview_data("ES", "5m")
    if data:
        print(f"  Open:  ${data.open:.2f}")
        print(f"  High:  ${data.high:.2f}")
        print(f"  Low:   ${data.low:.2f}")
        print(f"  Close: ${data.close:.2f}")
        print(f"  Vol:   {data.volume:,}")
        print(f"  RSI:   {data.rsi:.2f}" if data.rsi else "  RSI:   N/A")
        print(f"  MACD:  {data.macd:.4f}" if data.macd else "  MACD:  N/A")
        print(f"  Recommendation: {data.recommendation}")
        print(f"  Signals: {data.buy_signals} buy, {data.sell_signals} sell, {data.neutral_signals} neutral")
