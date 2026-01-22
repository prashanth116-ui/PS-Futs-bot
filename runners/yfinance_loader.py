"""
YFinance data loader for ES/NQ futures.

Symbols:
- ES=F  : E-mini S&P 500 Futures
- NQ=F  : E-mini Nasdaq 100 Futures
- YM=F  : E-mini Dow Futures
- RTY=F : E-mini Russell 2000 Futures
"""
from __future__ import annotations
import yfinance as yf
from datetime import datetime, timedelta
from core.types import Bar


def fetch_futures_bars(
    symbol: str = "ES=F",
    period: str = "5d",
    interval: str = "1m"
) -> list[Bar]:
    """
    Fetch futures data from Yahoo Finance.

    Args:
        symbol: Futures symbol (ES=F, NQ=F, etc.)
        period: Data period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
        interval: Bar interval (1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo)

    Note: 1m data is only available for the last 7 days.

    Returns:
        List of Bar objects
    """
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)

    if df.empty:
        print(f"No data returned for {symbol}")
        return []

    bars = []
    # Map symbol to our format (ES=F -> ES)
    clean_symbol = symbol.replace("=F", "")

    # Determine timeframe from interval
    timeframe = interval

    for idx, row in df.iterrows():
        bar = Bar(
            timestamp=idx.to_pydatetime(),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=int(row["Volume"]),
            symbol=clean_symbol,
            timeframe=timeframe
        )
        bars.append(bar)

    return bars


def fetch_live_bars(
    symbol: str = "ES=F",
    interval: str = "1m",
    days: int = 1
) -> list[Bar]:
    """
    Fetch the most recent bars (as close to live as possible).

    Yahoo Finance has ~15 min delay for free data.

    Args:
        symbol: Futures symbol
        interval: Bar interval
        days: Number of days of data

    Returns:
        List of Bar objects
    """
    period = f"{days}d"
    return fetch_futures_bars(symbol=symbol, period=period, interval=interval)


if __name__ == "__main__":
    # Quick test
    print("Fetching ES futures data...")
    bars = fetch_futures_bars("ES=F", period="1d", interval="5m")
    print(f"Got {len(bars)} bars")
    if bars:
        print(f"First: {bars[0]}")
        print(f"Last:  {bars[-1]}")
