"""
TradingView data loader for ES/NQ futures.

Uses tvDatafeed library to fetch historical data from TradingView.

Symbols:
- ES1! : E-mini S&P 500 Futures (continuous)
- NQ1! : E-mini Nasdaq 100 Futures (continuous)
- YM1! : E-mini Dow Futures (continuous)
- RTY1! : E-mini Russell 2000 Futures (continuous)

Exchange: CME_MINI
"""
from __future__ import annotations

import os
import sys
import warnings
import threading
from datetime import datetime, date, time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from tvDatafeed import TvDatafeed, Interval

# Load environment variables from config/.env
_env_path = Path(__file__).parent.parent / "config" / ".env"
load_dotenv(_env_path)

from core.types import Bar

warnings.filterwarnings('ignore')

# Interval mapping
INTERVAL_MAP = {
    "1m": Interval.in_1_minute,
    "2m": Interval.in_1_minute,  # Will aggregate 1m to 2m
    "3m": Interval.in_3_minute,
    "5m": Interval.in_5_minute,
    "15m": Interval.in_15_minute,
    "30m": Interval.in_30_minute,
    "1h": Interval.in_1_hour,
    "4h": Interval.in_4_hour,
    "1d": Interval.in_daily,
}

# Symbol mapping (clean name -> TradingView symbol)
SYMBOL_MAP = {
    "ES": "ES1!",
    "NQ": "NQ1!",
    "MES": "MES1!",
    "MNQ": "MNQ1!",
    "YM": "YM1!",
    "RTY": "RTY1!",
}

# Exchange mapping for stocks
STOCK_EXCHANGES = {
    "TSLA": "NASDAQ",
    "AAPL": "NASDAQ",
    "MSFT": "NASDAQ",
    "GOOGL": "NASDAQ",
    "AMZN": "NASDAQ",
    "META": "NASDAQ",
    "NVDA": "NASDAQ",
    "AMD": "NASDAQ",
    "SPY": "AMEX",
    "QQQ": "NASDAQ",
    "IWM": "AMEX",
}

def get_exchange(symbol: str) -> str:
    """Get exchange for a symbol."""
    sym = symbol.upper().replace("1!", "")
    if sym in STOCK_EXCHANGES:
        return STOCK_EXCHANGES[sym]
    if sym in SYMBOL_MAP or symbol.endswith("!"):
        return "CME_MINI"
    # Default to NASDAQ for unknown symbols
    return "NASDAQ"


def _get_auth_token_from_cookies() -> str | None:
    """Extract auth token using saved browser cookies."""
    import json
    import re
    import requests

    cookie_file = Path.home() / ".tvdatafeed" / "cookies.json"
    if not cookie_file.exists():
        return None

    try:
        with open(cookie_file) as f:
            cookies = json.load(f)

        session = requests.Session()
        for cookie in cookies:
            session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain", ".tradingview.com"),
                path=cookie.get("path", "/"),
            )

        # Fetch TradingView to get auth_token from page
        resp = session.get("https://www.tradingview.com/")
        if resp.status_code == 200:
            match = re.search(r'"auth_token":"([^"]+)"', resp.text)
            if match:
                return match.group(1)
    except Exception:
        pass

    return None


class TvDatafeedAuth(TvDatafeed):
    """TvDatafeed with pre-set auth token (bypasses login)."""

    def __init__(self, auth_token: str):
        self.ws_debug = False
        self.token = auth_token
        self.ws = None
        self.session = self._TvDatafeed__generate_session()
        self.chart_session = self._TvDatafeed__generate_chart_session()


# Global client singleton with thread lock
_tv_client = None
_tv_client_lock = threading.Lock()
_tv_client_created_at = None
_TV_CLIENT_MAX_AGE = 300  # Recreate client every 5 minutes


def _get_tv_client(force_new: bool = False) -> TvDatafeed:
    """
    Get TvDatafeed client with saved session cookies.

    Uses a singleton pattern with automatic refresh to avoid connection issues.
    Tries to load session from browser login first, falls back to credentials.
    """
    global _tv_client, _tv_client_created_at

    with _tv_client_lock:
        now = datetime.now()

        # Check if we need a new client
        need_new = (
            force_new
            or _tv_client is None
            or _tv_client_created_at is None
            or (now - _tv_client_created_at).total_seconds() > _TV_CLIENT_MAX_AGE
        )

        if need_new:
            # Close existing websocket if any
            if _tv_client is not None:
                try:
                    if hasattr(_tv_client, 'ws') and _tv_client.ws:
                        _tv_client.ws.close()
                except Exception:
                    pass

            # Try saved browser session first
            auth_token = _get_auth_token_from_cookies()
            if auth_token:
                _tv_client = TvDatafeedAuth(auth_token)
            else:
                # Fall back to username/password (may fail due to CAPTCHA)
                tv_user = os.getenv("TV_USERNAME")
                tv_pass = os.getenv("TV_PASSWORD")
                if tv_user and tv_pass:
                    _tv_client = TvDatafeed(username=tv_user, password=tv_pass)
                else:
                    _tv_client = TvDatafeed()

            _tv_client_created_at = now

        return _tv_client


def _fetch_with_timeout(tv: TvDatafeed, symbol: str, exchange: str,
                         interval: Interval, n_bars: int, timeout: int = 30):
    """
    Fetch data with a timeout to prevent hanging.

    Returns DataFrame or None if timeout/error.
    """
    result = [None]
    error = [None]

    def fetch():
        try:
            result[0] = tv.get_hist(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                n_bars=n_bars,
            )
        except Exception as e:
            error[0] = e

    thread = threading.Thread(target=fetch)
    thread.daemon = True
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        # Timeout - thread still running
        print(f"  Timeout fetching {symbol} after {timeout}s", flush=True)
        return None

    if error[0]:
        raise error[0]

    return result[0]


def _aggregate_bars(bars: list[Bar], target_minutes: int) -> list[Bar]:
    """Aggregate bars to a larger timeframe."""
    if not bars or target_minutes <= 1:
        return bars

    aggregated = []
    chunk_size = target_minutes

    for i in range(0, len(bars), chunk_size):
        chunk = bars[i:i + chunk_size]
        if not chunk:
            continue

        agg_bar = Bar(
            timestamp=chunk[0].timestamp,
            open=chunk[0].open,
            high=max(b.high for b in chunk),
            low=min(b.low for b in chunk),
            close=chunk[-1].close,
            volume=sum(b.volume for b in chunk),
            symbol=chunk[0].symbol,
            timeframe=f"{target_minutes}m",
        )
        aggregated.append(agg_bar)

    return aggregated


def fetch_futures_bars(
    symbol: str,
    interval: str = "3m",
    n_bars: int = 500,
    exchange: str = None,
    timeout: int = 30,
) -> list[Bar]:
    """
    Fetch historical bars from TradingView.

    Args:
        symbol: Symbol to fetch (ES, NQ, TSLA, AAPL, etc.)
        interval: Bar interval (1m, 2m, 3m, 5m, 15m, 30m, 1h, 4h, 1d)
        n_bars: Number of bars to fetch (max ~5000)
        exchange: Exchange name (auto-detected if None)
        timeout: Timeout in seconds for each fetch attempt (default 30)

    Returns:
        List of Bar objects in chronological order
    """
    # Auto-detect exchange if not provided
    if exchange is None:
        exchange = get_exchange(symbol)

    # Map clean symbol to TradingView symbol (for futures)
    tv_symbol = SYMBOL_MAP.get(symbol.upper(), symbol.upper())

    clean_symbol = symbol.upper().replace("1!", "").replace("=F", "")

    # Handle 2m by fetching 1m and aggregating
    aggregate_to = None
    if interval == "2m":
        tv_interval = Interval.in_1_minute
        n_bars = n_bars * 2  # Fetch more 1m bars
        aggregate_to = 2
    else:
        tv_interval = INTERVAL_MAP.get(interval)
        if tv_interval is None:
            raise ValueError(f"Invalid interval: {interval}. Valid: {list(INTERVAL_MAP.keys())}")

    # Connect using saved session cookies (from browser login) or fall back to credentials
    df = None
    for attempt in range(3):
        try:
            # Get client (force new on retry after first failure)
            tv = _get_tv_client(force_new=(attempt > 0))

            # Fetch with timeout
            df = _fetch_with_timeout(
                tv=tv,
                symbol=tv_symbol,
                exchange=exchange,
                interval=tv_interval,
                n_bars=n_bars,
                timeout=timeout,
            )
            if df is not None and not df.empty:
                break
        except Exception as e:
            print(f"  Attempt {attempt + 1} failed: {e}", flush=True)
            import time
            time.sleep(1)

    if df is None or df.empty:
        print(f"  No data returned for {tv_symbol}", flush=True)
        return []

    # Convert to Bar objects
    bars: list[Bar] = []
    for idx, row in df.iterrows():
        bar = Bar(
            timestamp=idx.to_pydatetime(),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=int(row["volume"]) if row["volume"] else 0,
            symbol=clean_symbol,
            timeframe=interval,
        )
        bars.append(bar)

    # Aggregate if needed (for 2m)
    if aggregate_to:
        bars = _aggregate_bars(bars, aggregate_to)

    return bars


def fetch_rth_bars(
    symbol: str,
    interval: str = "3m",
    n_bars: int = 500,
    rth_start: time = time(9, 30),
    rth_end: time = time(16, 0),
    target_date: date | datetime | None = None,
) -> list[Bar]:
    """
    Fetch bars filtered to Regular Trading Hours (RTH).

    Args:
        symbol: Symbol to fetch
        interval: Bar interval
        n_bars: Number of bars to fetch before filtering
        rth_start: RTH start time (default 9:30 AM ET)
        rth_end: RTH end time (default 4:00 PM ET)
        target_date: If provided, only return bars from this date

    Returns:
        List of Bar objects during RTH
    """
    bars = fetch_futures_bars(symbol, interval, n_bars)

    # Filter to RTH
    rth_bars = [
        b for b in bars
        if rth_start <= b.timestamp.time() <= rth_end
    ]

    # Filter to specific date if provided
    if target_date:
        if isinstance(target_date, datetime):
            target = target_date.date()
        else:
            target = target_date
        rth_bars = [b for b in rth_bars if b.timestamp.date() == target]

    return rth_bars


if __name__ == "__main__":
    # Test the loader
    print("Testing TradingView loader...")

    bars = fetch_futures_bars("ES", interval="3m", n_bars=100)
    print(f"\nFetched {len(bars)} ES 3-min bars")
    if bars:
        print(f"First: {bars[0].timestamp} O={bars[0].open} H={bars[0].high} L={bars[0].low} C={bars[0].close}")
        print(f"Last:  {bars[-1].timestamp} O={bars[-1].open} H={bars[-1].high} L={bars[-1].low} C={bars[-1].close}")

    # Test RTH filter
    from datetime import date
    today = date.today()
    rth_bars = fetch_rth_bars("ES", interval="3m", target_date=today)
    print(f"\nRTH bars for {today}: {len(rth_bars)}")
