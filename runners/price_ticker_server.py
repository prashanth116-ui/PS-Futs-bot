"""
TradingView Price Ticker Server.

Fetches real-time prices from TradingView Pro and serves them via HTTP.
Runs on the droplet as a lightweight always-on service (port 8080).

Endpoints:
  GET /prices.json  — current prices for ES, NQ, GC, CL, DXY
  GET /bars          — historical OHLCV bars (daily/weekly) for ES, NQ, VIX, SPY, RSP
  GET /health       — service health check

Usage:
  python -m runners.price_ticker_server
  python -m runners.price_ticker_server --port 8080
"""
from __future__ import annotations

import json
import os
import sys
import time
import threading
import argparse
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from runners.tradingview_loader import _get_tv_client, _fetch_with_timeout
from tvDatafeed import Interval

# ── Symbol config ──────────────────────────────────────────────────────
TICKER_SYMBOLS = {
    "ES": {"tv_symbol": "ES1!", "exchange": "CME_MINI"},
    "NQ": {"tv_symbol": "NQ1!", "exchange": "CME_MINI"},
    "GC": {"tv_symbol": "GC1!", "exchange": "COMEX"},
    "CL": {"tv_symbol": "CL1!", "exchange": "NYMEX"},
    "DXY": {"tv_symbol": "DXY", "exchange": "TVC"},
}

# ── Bar datasets config ───────────────────────────────────────────────
BAR_DATASETS = {
    "ES_daily":   {"tv_symbol": "ES1!", "exchange": "CME_MINI", "interval": Interval.in_daily,  "n_bars": 260, "refresh": 1800},
    "NQ_daily":   {"tv_symbol": "NQ1!", "exchange": "CME_MINI", "interval": Interval.in_daily,  "n_bars": 260, "refresh": 1800},
    "ES_weekly":  {"tv_symbol": "ES1!", "exchange": "CME_MINI", "interval": Interval.in_weekly, "n_bars": 110, "refresh": 7200},
    "NQ_weekly":  {"tv_symbol": "NQ1!", "exchange": "CME_MINI", "interval": Interval.in_weekly, "n_bars": 110, "refresh": 7200},
    "VIX_daily":  {"tv_symbol": "VIX",  "exchange": "TVC",      "interval": Interval.in_daily,  "n_bars": 260, "refresh": 1800},
    "SPY_daily":  {"tv_symbol": "SPY",  "exchange": "AMEX",     "interval": Interval.in_daily,  "n_bars": 260, "refresh": 1800},
    "RSP_daily":  {"tv_symbol": "RSP",  "exchange": "AMEX",     "interval": Interval.in_daily,  "n_bars": 260, "refresh": 1800},
    # Intraday bars for HTF bias (4H, 1H, 15M)
    "ES_4h":      {"tv_symbol": "ES1!", "exchange": "CME_MINI", "interval": Interval.in_4_hour,    "n_bars": 100, "refresh": 1800},
    "ES_1h":      {"tv_symbol": "ES1!", "exchange": "CME_MINI", "interval": Interval.in_1_hour,    "n_bars": 100, "refresh": 900},
    "ES_15m":     {"tv_symbol": "ES1!", "exchange": "CME_MINI", "interval": Interval.in_15_minute, "n_bars": 100, "refresh": 600},
    "NQ_4h":      {"tv_symbol": "NQ1!", "exchange": "CME_MINI", "interval": Interval.in_4_hour,    "n_bars": 100, "refresh": 1800},
    "NQ_1h":      {"tv_symbol": "NQ1!", "exchange": "CME_MINI", "interval": Interval.in_1_hour,    "n_bars": 100, "refresh": 900},
    "NQ_15m":     {"tv_symbol": "NQ1!", "exchange": "CME_MINI", "interval": Interval.in_15_minute, "n_bars": 100, "refresh": 600},
}

# Map request params to dataset key: (symbol, interval) -> dataset key
_BAR_KEY_MAP = {}
for _key, _cfg in BAR_DATASETS.items():
    _sym, _intv = _key.split("_")
    _BAR_KEY_MAP[(_sym.upper(), _intv)] = _key

# ── Shared state ───────────────────────────────────────────────────────
_prices = {}
_prices_lock = threading.Lock()
_last_fetch_time = 0
_last_daily_fetch_time = 0
_daily_closes = {}  # symbol -> previous close price

# Bar data shared state
_bar_data = {}          # dataset_key -> list of bar dicts
_bar_lock = threading.Lock()
_bar_fetch_times = {}   # dataset_key -> last fetch timestamp

DISK_PATH = Path("/opt/tradovate-bot/data/ticker/prices.json")
TRADE_STATE_PATH = Path("/opt/tradovate-bot/data/ticker/trade_state.json")
SIGNAL_STATE_PATH = Path("/opt/tradovate-bot/data/ticker/signal_state.json")
BAR_DISK_DIR = Path("/opt/tradovate-bot/data/ticker/bars")
FETCH_INTERVAL = 30  # seconds between price fetches
DAILY_REFRESH_INTERVAL = 3600  # refresh daily bars every hour


def _load_from_disk():
    """Load cached prices from disk on startup."""
    global _prices, _last_fetch_time
    try:
        if DISK_PATH.exists():
            data = json.loads(DISK_PATH.read_text())
            with _prices_lock:
                _prices = data.get("data", {})
                _last_fetch_time = data.get("ts", 0) / 1000  # stored as ms
            age = time.time() - _last_fetch_time
            print(f"[ticker] Loaded cached prices from disk (age: {age:.0f}s)", flush=True)
    except Exception as e:
        print(f"[ticker] Could not load disk cache: {e}", flush=True)


def _save_to_disk():
    """Save current prices to disk for persistence across restarts."""
    try:
        DISK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _prices_lock:
            payload = {
                "ts": int(_last_fetch_time * 1000),
                "data": dict(_prices),
            }
        DISK_PATH.write_text(json.dumps(payload))
    except Exception as e:
        print(f"[ticker] Could not save to disk: {e}", flush=True)


def _load_bars_from_disk():
    """Load cached bar data from disk on startup."""
    global _bar_data, _bar_fetch_times
    try:
        BAR_DISK_DIR.mkdir(parents=True, exist_ok=True)
        for key in BAR_DATASETS:
            fpath = BAR_DISK_DIR / f"{key}.json"
            if fpath.exists():
                data = json.loads(fpath.read_text())
                bars = data.get("bars", [])
                ts = data.get("ts", 0)
                with _bar_lock:
                    _bar_data[key] = bars
                    _bar_fetch_times[key] = ts
                age = time.time() - ts
                print(f"[bars] Loaded {key}: {len(bars)} bars (age: {age:.0f}s)", flush=True)
    except Exception as e:
        print(f"[bars] Could not load disk cache: {e}", flush=True)


def _save_bars_to_disk(key, bars):
    """Save bar dataset to disk for persistence."""
    try:
        BAR_DISK_DIR.mkdir(parents=True, exist_ok=True)
        fpath = BAR_DISK_DIR / f"{key}.json"
        payload = {"ts": time.time(), "count": len(bars), "bars": bars}
        fpath.write_text(json.dumps(payload))
    except Exception as e:
        print(f"[bars] Could not save {key} to disk: {e}", flush=True)


def _fetch_bar_dataset(tv, key, cfg):
    """Fetch a single bar dataset from TradingView."""
    try:
        df = _fetch_with_timeout(
            tv=tv,
            symbol=cfg["tv_symbol"],
            exchange=cfg["exchange"],
            interval=cfg["interval"],
            n_bars=cfg["n_bars"],
            timeout=30,
        )
        if df is None or df.empty:
            print(f"[bars] {key}: no data returned", flush=True)
            return None

        bars = []
        for idx, row in df.iterrows():
            # idx is a datetime index from tvDatafeed
            dt = idx
            bar = {
                "date": dt.strftime("%Y-%m-%d"),
                "ts": int(dt.timestamp()),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]) if row.get("volume") else 0,
            }
            # Include datetime for intraday bars
            if cfg["interval"] not in (Interval.in_daily, Interval.in_weekly):
                bar["datetime"] = dt.strftime("%Y-%m-%d %H:%M:%S")
            bars.append(bar)

        with _bar_lock:
            _bar_data[key] = bars
            _bar_fetch_times[key] = time.time()

        _save_bars_to_disk(key, bars)
        print(f"[bars] {key}: fetched {len(bars)} bars", flush=True)
        return bars
    except Exception as e:
        print(f"[bars] {key}: fetch error: {e}", flush=True)
        return None


def _bar_fetcher_loop():
    """Background thread: fetch bar datasets on their individual refresh schedules."""
    # Initial fetch of all datasets
    print("[bars] Starting initial bar fetch for all datasets...", flush=True)
    tv = _get_tv_client()
    for key, cfg in BAR_DATASETS.items():
        # Skip if loaded from disk and still fresh
        with _bar_lock:
            last_ts = _bar_fetch_times.get(key, 0)
        age = time.time() - last_ts
        if age < cfg["refresh"] and key in _bar_data:
            print(f"[bars] {key}: disk cache still fresh ({age:.0f}s old), skipping", flush=True)
            continue
        _fetch_bar_dataset(tv, key, cfg)
        time.sleep(2)  # small delay between fetches to avoid rate limiting

    print("[bars] Initial bar fetch complete", flush=True)

    while True:
        time.sleep(60)  # check every minute
        try:
            now = time.time()
            for key, cfg in BAR_DATASETS.items():
                with _bar_lock:
                    last_ts = _bar_fetch_times.get(key, 0)
                if now - last_ts >= cfg["refresh"]:
                    tv = _get_tv_client()
                    _fetch_bar_dataset(tv, key, cfg)
                    time.sleep(2)
        except Exception as e:
            print(f"[bars] Fetcher loop error: {e}", flush=True)


def _fetch_daily_closes():
    """Fetch daily bars to get previous close for % change calculation."""
    global _daily_closes, _last_daily_fetch_time
    print("[ticker] Fetching daily bars for previous close...", flush=True)

    tv = _get_tv_client()
    closes = {}

    for sym_id, cfg in TICKER_SYMBOLS.items():
        try:
            df = _fetch_with_timeout(
                tv=tv,
                symbol=cfg["tv_symbol"],
                exchange=cfg["exchange"],
                interval=Interval.in_daily,
                n_bars=5,
                timeout=15,
            )
            if df is not None and len(df) >= 2:
                # Second-to-last row is previous day's close
                prev_close = float(df.iloc[-2]["close"])
                closes[sym_id] = prev_close
                print(f"  {sym_id}: prev close = {prev_close}", flush=True)
            else:
                print(f"  {sym_id}: not enough daily bars", flush=True)
        except Exception as e:
            print(f"  {sym_id}: daily fetch error: {e}", flush=True)

    _daily_closes = closes
    _last_daily_fetch_time = time.time()
    print(f"[ticker] Daily closes loaded for {len(closes)} symbols", flush=True)


def _fetch_prices():
    """Fetch current prices from TradingView using 1-min bars."""
    global _prices, _last_fetch_time

    tv = _get_tv_client()
    new_prices = {}

    for sym_id, cfg in TICKER_SYMBOLS.items():
        try:
            df = _fetch_with_timeout(
                tv=tv,
                symbol=cfg["tv_symbol"],
                exchange=cfg["exchange"],
                interval=Interval.in_1_minute,
                n_bars=3,
                timeout=15,
            )
            if df is not None and not df.empty:
                price = float(df.iloc[-1]["close"])
                prev_close = _daily_closes.get(sym_id)
                if prev_close and prev_close != 0:
                    chg = price - prev_close
                    pct = (chg / prev_close) * 100
                else:
                    chg = 0
                    pct = 0
                new_prices[sym_id] = {
                    "price": price,
                    "pct": round(pct, 3),
                    "up": chg >= 0,
                }
        except Exception as e:
            print(f"[ticker] Error fetching {sym_id}: {e}", flush=True)

    if new_prices:
        now = time.time()
        with _prices_lock:
            _prices.update(new_prices)
            _last_fetch_time = now
        _save_to_disk()
        ts = datetime.now().strftime("%H:%M:%S")
        symbols_str = " ".join(
            f"{s}={d['price']}" for s, d in new_prices.items()
        )
        print(f"[ticker] {ts} Updated {len(new_prices)} symbols: {symbols_str}", flush=True)
    else:
        print(f"[ticker] No prices fetched this cycle", flush=True)


def _fetcher_loop():
    """Background thread: fetch prices every FETCH_INTERVAL seconds."""
    global _last_daily_fetch_time

    # Initial daily close fetch
    _fetch_daily_closes()

    while True:
        try:
            # Refresh daily closes periodically
            if time.time() - _last_daily_fetch_time > DAILY_REFRESH_INTERVAL:
                _fetch_daily_closes()

            _fetch_prices()
        except Exception as e:
            print(f"[ticker] Fetcher error: {e}", flush=True)

        time.sleep(FETCH_INTERVAL)


# ── HTTP Server ────────────────────────────────────────────────────────
class TickerHandler(BaseHTTPRequestHandler):
    """Serves /prices.json and /health endpoints."""

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/prices.json":
            self._serve_prices()
        elif path == "/bars":
            self._serve_bars(parsed)
        elif path == "/trade-state":
            self._serve_trade_state()
        elif path == "/signal-state":
            self._serve_signal_state()
        elif path == "/health":
            self._serve_health()
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _serve_prices(self):
        with _prices_lock:
            data = dict(_prices)
            ts = int(_last_fetch_time * 1000)

        payload = json.dumps({
            "ok": True,
            "source": "tradingview",
            "ts": ts,
            "data": data,
        })

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "public, max-age=10, stale-while-revalidate=30")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(payload.encode())

    def _serve_bars(self, parsed):
        params = parse_qs(parsed.query)
        symbol = params.get("symbol", [None])[0]
        interval = params.get("interval", [None])[0]
        limit_str = params.get("limit", [None])[0]

        if not symbol or not interval:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": False,
                "error": "Missing required params: symbol, interval",
                "example": "/bars?symbol=ES&interval=daily&limit=260",
            }).encode())
            return

        dataset_key = _BAR_KEY_MAP.get((symbol.upper(), interval.lower()))
        if not dataset_key:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self._cors_headers()
            self.end_headers()
            valid = [f"{s}/{i}" for (s, i) in _BAR_KEY_MAP.keys()]
            self.wfile.write(json.dumps({
                "ok": False,
                "error": f"Unknown symbol/interval combo. Valid: {valid}",
            }).encode())
            return

        with _bar_lock:
            bars = list(_bar_data.get(dataset_key, []))
            fetch_ts = _bar_fetch_times.get(dataset_key, 0)

        if not bars:
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self._cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": False,
                "error": f"No bar data available for {dataset_key}. Try again shortly.",
            }).encode())
            return

        # Apply limit
        if limit_str:
            try:
                limit = int(limit_str)
                if limit > 0:
                    bars = bars[-limit:]
            except ValueError:
                pass

        payload = json.dumps({
            "ok": True,
            "source": "tradingview",
            "symbol": symbol.upper(),
            "interval": interval.lower(),
            "count": len(bars),
            "fetchedAt": int(fetch_ts * 1000),
            "bars": bars,
        })

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "public, max-age=60, stale-while-revalidate=300")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(payload.encode())

    def _serve_trade_state(self):
        """Serve trade state JSON written by run_live.py."""
        try:
            if TRADE_STATE_PATH.exists():
                data = json.loads(TRADE_STATE_PATH.read_text())
                payload = json.dumps({"ok": True, **data})
                self.send_response(200)
            else:
                payload = json.dumps({"ok": False, "error": "no data"})
                self.send_response(200)
        except Exception as e:
            payload = json.dumps({"ok": False, "error": str(e)})
            self.send_response(500)

        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "public, max-age=5")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(payload.encode())

    def _serve_signal_state(self):
        """Serve ICT signal state JSON written by run_live.py."""
        try:
            if SIGNAL_STATE_PATH.exists():
                data = json.loads(SIGNAL_STATE_PATH.read_text())
                payload = json.dumps({"ok": True, **data})
                self.send_response(200)
            else:
                payload = json.dumps({"ok": False, "error": "no data"})
                self.send_response(200)
        except Exception as e:
            payload = json.dumps({"ok": False, "error": str(e)})
            self.send_response(500)

        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "public, max-age=10")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(payload.encode())

    def _serve_health(self):
        with _prices_lock:
            n_symbols = len(_prices)
            ts = _last_fetch_time

        age = time.time() - ts if ts else float("inf")
        healthy = n_symbols > 0 and age < 120  # stale if >2 min

        # Bar data status
        with _bar_lock:
            bar_datasets = {k: len(v) for k, v in _bar_data.items()}
            bar_ages = {k: round(time.time() - v, 1) for k, v in _bar_fetch_times.items()}

        payload = json.dumps({
            "healthy": healthy,
            "symbols": n_symbols,
            "last_fetch_age_s": round(age, 1) if ts else None,
            "uptime_s": round(time.time() - _start_time, 1),
            "bar_datasets": bar_datasets,
            "bar_ages_s": bar_ages,
        })

        self.send_response(200 if healthy else 503)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(payload.encode())

    def log_message(self, format, *args):
        """Suppress default request logging (too noisy)."""
        pass


_start_time = time.time()


def main():
    parser = argparse.ArgumentParser(description="TradingView Price Ticker Server")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port (default: 8080)")
    args = parser.parse_args()

    print(f"[ticker] Starting TradingView Price Ticker Server on port {args.port}", flush=True)
    print(f"[ticker] Price symbols: {', '.join(TICKER_SYMBOLS.keys())}", flush=True)
    print(f"[ticker] Bar datasets: {', '.join(BAR_DATASETS.keys())}", flush=True)

    # Load cached data from disk so HTTP serves immediately
    _load_from_disk()
    _load_bars_from_disk()

    # Start fetcher threads
    fetcher = threading.Thread(target=_fetcher_loop, daemon=True)
    fetcher.start()

    bar_fetcher = threading.Thread(target=_bar_fetcher_loop, daemon=True)
    bar_fetcher.start()

    # Start HTTP server (blocks main thread)
    server = HTTPServer(("0.0.0.0", args.port), TickerHandler)
    print(f"[ticker] HTTP server listening on 0.0.0.0:{args.port}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[ticker] Shutting down...", flush=True)
        server.shutdown()


if __name__ == "__main__":
    main()
