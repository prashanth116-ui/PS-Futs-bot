"""
ICT Liquidity Sweep Strategy - Live Scanner

Continuously monitors multiple symbols across HTF timeframes (15m, 1h) for
sweep setups, sending Telegram alerts when:
  1. Setup Detected: Sweep + displacement + FVG formed
  2. Entry Zone Active: Price retraces into the FVG (mitigation)

Uses 5m bars for FVG detection (MTF) and 15m/1h for sweep detection (HTF).

Usage:
    # Default: ES NQ on 15m + 1h, scan every 5 min
    python -m runners.scan_ict_sweep

    # Custom symbols
    python -m runners.scan_ict_sweep --symbols ES NQ SPY QQQ

    # Console only (no Telegram)
    python -m runners.scan_ict_sweep --symbols ES --no-telegram --debug

    # Custom interval
    python -m runners.scan_ict_sweep --symbols ES NQ --scan-interval 180
"""
import sys
sys.path.insert(0, '.')

import argparse
import time as _time
import traceback
from datetime import datetime, date, time as dt_time
from typing import Optional

from runners.tradingview_loader import fetch_futures_bars
from runners.notifier import TelegramNotifier
from strategies.ict_sweep.strategy import ICTSweepStrategy, TradeSetup, SetupState


# ---------------------------------------------------------------------------
# Symbol configs (reuse values from run_ict_sweep.py)
# ---------------------------------------------------------------------------

EQUITY_SYMBOLS = {
    'SPY', 'QQQ', 'IWM',
    'NVDA', 'TSLA', 'AAPL', 'AMZN', 'META', 'MSFT', 'AMD', 'GOOGL',
    'UNH', 'PLTR', 'COIN',
}

SYMBOL_CONFIGS = {
    # --- Futures ---
    'ES':  {'tick_size': 0.25, 'tick_value': 12.50, 'min_fvg': 3,  'max_risk': 40,  'max_sweep': 50,  'min_risk': 12},
    'NQ':  {'tick_size': 0.25, 'tick_value': 5.00,  'min_fvg': 8,  'max_risk': 80,  'max_sweep': 50,  'min_risk': 12},
    'MES': {'tick_size': 0.25, 'tick_value': 1.25,  'min_fvg': 3,  'max_risk': 40,  'max_sweep': 50,  'min_risk': 12},
    'MNQ': {'tick_size': 0.25, 'tick_value': 0.50,  'min_fvg': 8,  'max_risk': 80,  'max_sweep': 50,  'min_risk': 12},
    # --- ETFs ---
    'SPY':  {'tick_size': 0.01, 'tick_value': 0.01, 'min_fvg': 20, 'max_risk': 500, 'max_sweep': 200, 'min_risk': 30},
    'QQQ':  {'tick_size': 0.01, 'tick_value': 0.01, 'min_fvg': 40, 'max_risk': 500, 'max_sweep': 200, 'min_risk': 50},
    # --- Large-cap stocks ---
    'NVDA':  {'tick_size': 0.01, 'tick_value': 0.01, 'min_fvg': 15, 'max_risk': 400, 'max_sweep': 200, 'min_risk': 20},
    'TSLA':  {'tick_size': 0.01, 'tick_value': 0.01, 'min_fvg': 30, 'max_risk': 500, 'max_sweep': 300, 'min_risk': 40},
    'AAPL':  {'tick_size': 0.01, 'tick_value': 0.01, 'min_fvg': 15, 'max_risk': 400, 'max_sweep': 200, 'min_risk': 20},
    'AMZN':  {'tick_size': 0.01, 'tick_value': 0.01, 'min_fvg': 20, 'max_risk': 500, 'max_sweep': 200, 'min_risk': 25},
    'META':  {'tick_size': 0.01, 'tick_value': 0.01, 'min_fvg': 40, 'max_risk': 500, 'max_sweep': 300, 'min_risk': 50},
    'MSFT':  {'tick_size': 0.01, 'tick_value': 0.01, 'min_fvg': 25, 'max_risk': 500, 'max_sweep': 250, 'min_risk': 30},
    'AMD':   {'tick_size': 0.01, 'tick_value': 0.01, 'min_fvg': 15, 'max_risk': 400, 'max_sweep': 200, 'min_risk': 20},
    'GOOGL': {'tick_size': 0.01, 'tick_value': 0.01, 'min_fvg': 15, 'max_risk': 500, 'max_sweep': 200, 'min_risk': 20},
    'UNH':   {'tick_size': 0.01, 'tick_value': 0.01, 'min_fvg': 20, 'max_risk': 500, 'max_sweep': 200, 'min_risk': 30},
    'PLTR':  {'tick_size': 0.01, 'tick_value': 0.01, 'min_fvg': 10, 'max_risk': 300, 'max_sweep': 150, 'min_risk': 15},
    'COIN':  {'tick_size': 0.01, 'tick_value': 0.01, 'min_fvg': 30, 'max_risk': 500, 'max_sweep': 300, 'min_risk': 40},
}

# Minutes per HTF timeframe (for partial bar stripping)
HTF_MINUTES = {
    '5m': 5,
    '15m': 15,
    '1h': 60,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_et() -> datetime:
    """Get current time as naive datetime assumed ET (matches TV data)."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo('America/New_York')).replace(tzinfo=None)


def _is_futures_symbol(symbol: str) -> bool:
    return symbol.upper() not in EQUITY_SYMBOLS


def _is_scanning_hours(now: datetime, symbols: list[str]) -> bool:
    """Check if we should be scanning right now."""
    t = now.time()
    has_futures = any(_is_futures_symbol(s) for s in symbols)
    has_equities = any(not _is_futures_symbol(s) for s in symbols)

    # Futures: 4:00 AM - 4:30 PM ET
    # Equities: 9:00 AM - 4:30 PM ET
    futures_ok = has_futures and dt_time(4, 0) <= t <= dt_time(16, 30)
    equities_ok = has_equities and dt_time(9, 0) <= t <= dt_time(16, 30)

    return futures_ok or equities_ok


def _should_scan_symbol(symbol: str, now: datetime) -> bool:
    """Check if a specific symbol should be scanned right now."""
    t = now.time()
    if _is_futures_symbol(symbol):
        return dt_time(4, 0) <= t <= dt_time(16, 30)
    else:
        return dt_time(9, 0) <= t <= dt_time(16, 30)


def _strip_partial_bar(bars: list, period_minutes: int, now: datetime) -> list:
    """Remove the most recent bar if it's less than half complete."""
    if not bars:
        return bars
    last = bars[-1]
    age_seconds = (now - last.timestamp).total_seconds()
    half_period = period_minutes * 60 / 2
    if age_seconds < half_period:
        return bars[:-1]
    return bars


def _format_price(price: float, tick_size: float) -> str:
    """Format price with appropriate decimal places."""
    if tick_size >= 0.25:
        return f'{price:.2f}'
    return f'{price:.2f}'


def _dedup_key_setup(symbol: str, htf_tf: str, setup: SetupState) -> str:
    """Create dedup key for a setup alert."""
    direction = setup.sweep.sweep_type
    return f'{symbol}_{htf_tf}_{direction}_{setup.fvg.bottom:.2f}_{setup.fvg.top:.2f}'


def _dedup_key_entry(symbol: str, htf_tf: str, trade: TradeSetup) -> str:
    """Create dedup key for an entry alert."""
    return f'{symbol}_{htf_tf}_{trade.direction}_{trade.fvg.bottom:.2f}_{trade.fvg.top:.2f}'


# ---------------------------------------------------------------------------
# SweepScanner
# ---------------------------------------------------------------------------

class SweepScanner:
    """Live ICT Sweep setup scanner with Telegram alerts."""

    def __init__(
        self,
        symbols: list[str],
        htf_timeframes: list[str] = None,
        scan_interval: int = 300,
        no_telegram: bool = False,
        debug: bool = False,
    ):
        self.symbols = [s.upper() for s in symbols]
        self.htf_timeframes = htf_timeframes or ['15m', '1h']
        self.scan_interval = scan_interval
        self.debug = debug
        self.running = True

        # Persistent strategy instances keyed by (symbol, htf_tf)
        self.strategies: dict[tuple, ICTSweepStrategy] = {}
        # Bar feed cursors
        self.last_fed_htf: dict[tuple, int] = {}
        self.last_fed_5m: dict[tuple, int] = {}

        # Alert dedup sets (cleared daily)
        self.setup_alerts_sent: set[str] = set()
        self.entry_alerts_sent: set[str] = set()
        # Suppress alerts on first cycle per key (after seeding)
        self._first_cycle_done: set[tuple] = set()

        # Session tracking
        self.current_session_date: Optional[date] = None
        self.alerts_sent_count = 0
        self.active_setup_count = 0

        # Heartbeat tracking
        self.last_heartbeat: Optional[datetime] = None
        self.last_prices: dict[str, float] = {}

        # Telegram
        if no_telegram:
            self.telegram = None
            print('[SCANNER] Telegram disabled')
        else:
            self.telegram = TelegramNotifier()
            if not self.telegram.enabled:
                self.telegram = None
                print('[SCANNER] Telegram not configured — console only')

    # -------------------------------------------------------------------
    # Strategy creation
    # -------------------------------------------------------------------

    def _make_strategy_config(self, symbol: str) -> dict:
        """Create strategy config for a symbol (scanner-tuned)."""
        cfg = SYMBOL_CONFIGS.get(symbol, SYMBOL_CONFIGS['ES'])
        return {
            'symbol': symbol,
            'tick_size': cfg['tick_size'],
            'tick_value': cfg['tick_value'],
            'swing_lookback': 20,
            'swing_strength': 3,
            'min_sweep_ticks': 2,
            'max_sweep_ticks': cfg['max_sweep'],
            'displacement_multiplier': 2.0,
            'avg_body_lookback': 20,
            'min_fvg_ticks': cfg['min_fvg'],
            'max_fvg_age_bars': 50,
            'mss_lookback': 20,
            'mss_swing_strength': 1,
            'stop_buffer_ticks': 2,
            'min_risk_ticks': cfg['min_risk'],
            'max_risk_ticks': cfg['max_risk'],
            'loss_cooldown_minutes': 0,
            'allow_lunch': True,       # Alert during lunch too
            'require_killzone': False,
            'max_daily_trades': 10,    # Scanner alerts, doesn't trade
            'max_daily_losses': 10,
            'use_mtf_for_fvg': True,   # Use 5m for FVG detection
            'entry_on_mitigation': True,
            'use_trend_filter': False,  # Alert all setups, user decides
            'stop_buffer_pts': 2.0 if _is_futures_symbol(symbol) else 0.10,
            't1_r': 3,
            'trail_r': 6,
            'debug': self.debug,
        }

    def _init_strategy(self, key: tuple, bars_htf: list, bars_5m: list):
        """Initialize and seed a strategy instance (first cycle)."""
        symbol, htf_tf = key
        config = self._make_strategy_config(symbol)
        strategy = ICTSweepStrategy(config)

        # Seed HTF bars (all but the last few to avoid stale alerts)
        for bar in bars_htf:
            strategy.htf_bars.append(bar)

        # Seed 5m/MTF bars
        for bar in bars_5m:
            strategy.mtf_bars.append(bar)

        # Calculate avg_body from seeded bars
        if strategy.htf_bars:
            from strategies.ict_sweep.filters.displacement import calculate_avg_body
            strategy.avg_body = calculate_avg_body(strategy.htf_bars, strategy.avg_body_lookback)

        self.strategies[key] = strategy
        self.last_fed_htf[key] = len(bars_htf)
        self.last_fed_5m[key] = len(bars_5m)

        if self.debug:
            print(f'  [INIT] {symbol}/{htf_tf}: seeded {len(bars_htf)} HTF bars, {len(bars_5m)} 5m bars, avg_body={strategy.avg_body:.4f}')

    # -------------------------------------------------------------------
    # Scanning
    # -------------------------------------------------------------------

    def _scan_symbol_htf(self, symbol: str, htf_tf: str, bars_5m: list, now: datetime):
        """Scan one symbol on one HTF timeframe."""
        key = (symbol, htf_tf)

        # Fetch HTF bars
        n_htf = 500 if htf_tf == '15m' else 200
        try:
            bars_htf = fetch_futures_bars(symbol, interval=htf_tf, n_bars=n_htf)
        except Exception as e:
            print(f'  [ERROR] Fetch {symbol} {htf_tf}: {e}')
            return

        if not bars_htf:
            if self.debug:
                print(f'  [WARN] No {htf_tf} bars for {symbol}')
            return

        # Strip partial bar
        bars_htf = _strip_partial_bar(bars_htf, HTF_MINUTES[htf_tf], now)

        if not bars_htf:
            return

        # First time: seed strategy and skip alerting
        if key not in self.strategies:
            self._init_strategy(key, bars_htf, bars_5m)
            return

        strategy = self.strategies[key]

        # Feed only NEW 5m bars
        prev_5m = self.last_fed_5m.get(key, 0)
        new_5m = bars_5m[prev_5m:]
        for bar in new_5m:
            strategy.update_mtf(bar)

        # Feed only NEW HTF bars
        prev_htf = self.last_fed_htf.get(key, 0)
        new_htf = bars_htf[prev_htf:]

        if self.debug and new_htf:
            print(f'  [{symbol}/{htf_tf}] Feeding {len(new_htf)} new HTF bars, {len(new_5m)} new 5m bars')

        for bar in new_htf:
            # Check for new setups
            setup = strategy.update_htf(bar)
            if setup:
                self.active_setup_count += 1
                self._alert_setup(symbol, htf_tf, setup, bar, now)

            # Check for FVG mitigation
            result = strategy.check_htf_mitigation(bar)
            if isinstance(result, TradeSetup):
                self._alert_entry(symbol, htf_tf, result, now)

        # Update cursors
        self.last_fed_htf[key] = len(bars_htf)
        self.last_fed_5m[key] = len(bars_5m)

    # -------------------------------------------------------------------
    # Alerts
    # -------------------------------------------------------------------

    def _alert_setup(self, symbol: str, htf_tf: str, setup: SetupState, bar, now: datetime):
        """Send setup detected alert."""
        dedup = _dedup_key_setup(symbol, htf_tf, setup)
        if dedup in self.setup_alerts_sent:
            return

        # Stale guard: if bar is too old, silently deduplicate
        bar_age = (now - bar.timestamp).total_seconds()
        if bar_age > self.scan_interval * 2:
            self.setup_alerts_sent.add(dedup)
            if self.debug:
                print(f'  [STALE] Skipping old setup alert for {symbol}/{htf_tf} (age={bar_age:.0f}s)')
            return

        self.setup_alerts_sent.add(dedup)
        self.alerts_sent_count += 1

        cfg = SYMBOL_CONFIGS.get(symbol, SYMBOL_CONFIGS['ES'])
        tick_size = cfg['tick_size']
        fvg = setup.fvg
        sweep = setup.sweep
        direction = 'BEARISH' if sweep.sweep_type == 'BEARISH' else 'BULLISH'
        fvg_ticks = (fvg.top - fvg.bottom) / tick_size

        time_str = bar.timestamp.strftime('%H:%M') + ' ET'
        def price_fmt(p):
            return _format_price(p, tick_size)

        msg = (
            f'<b>SWEEP SETUP \u2014 {symbol} ({htf_tf})</b>\n'
            f'\n'
            f'<b>Direction:</b> {direction}\n'
            f'<b>Sweep:</b> {price_fmt(sweep.sweep_price)} (depth: {sweep.sweep_depth_ticks:.1f} ticks)\n'
            f'<b>FVG Zone:</b> {price_fmt(fvg.bottom)} \u2014 {price_fmt(fvg.top)} ({fvg_ticks:.0f} ticks)\n'
            f'<b>Displacement:</b> {setup.displacement_ratio:.1f}x avg body\n'
            f'\n'
            f'Watch for price to retrace into FVG zone.\n'
            f'{time_str}'
        )

        print(f'  [SETUP] {symbol} ({htf_tf}) {direction} | Sweep={price_fmt(sweep.sweep_price)} FVG={price_fmt(fvg.bottom)}-{price_fmt(fvg.top)}')

        if self.telegram:
            try:
                self.telegram.send(msg)
            except Exception as e:
                print(f'  [TELEGRAM ERROR] {e}')

    def _alert_entry(self, symbol: str, htf_tf: str, trade: TradeSetup, now: datetime):
        """Send entry zone alert."""
        dedup = _dedup_key_entry(symbol, htf_tf, trade)
        if dedup in self.entry_alerts_sent:
            return

        # Stale guard
        bar_age = (now - trade.timestamp).total_seconds()
        if bar_age > self.scan_interval * 2:
            self.entry_alerts_sent.add(dedup)
            if self.debug:
                print(f'  [STALE] Skipping old entry alert for {symbol}/{htf_tf} (age={bar_age:.0f}s)')
            return

        self.entry_alerts_sent.add(dedup)
        self.alerts_sent_count += 1

        cfg = SYMBOL_CONFIGS.get(symbol, SYMBOL_CONFIGS['ES'])
        tick_size = cfg['tick_size']
        fvg = trade.fvg
        def price_fmt(p):
            return _format_price(p, tick_size)

        time_str = trade.timestamp.strftime('%H:%M') + ' ET'

        msg = (
            f'<b>ENTRY ZONE \u2014 {symbol} ({htf_tf})</b>\n'
            f'\n'
            f'<b>Direction:</b> {trade.direction}\n'
            f'<b>FVG:</b> {price_fmt(fvg.bottom)} \u2014 {price_fmt(fvg.top)}\n'
            f'<b>Entry ~</b> {price_fmt(trade.entry_price)}\n'
            f'<b>Stop:</b> {price_fmt(trade.stop_price)} (risk: {trade.risk_ticks:.0f} ticks)\n'
            f'<b>T1:</b> {price_fmt(trade.t1_price)} (3R)\n'
            f'\n'
            f'Price entered the FVG. Consider entry with confirmation.\n'
            f'{time_str}'
        )

        print(f'  [ENTRY] {symbol} ({htf_tf}) {trade.direction} | Entry={price_fmt(trade.entry_price)} Stop={price_fmt(trade.stop_price)} Risk={trade.risk_ticks:.0f}t')

        if self.telegram:
            try:
                self.telegram.send(msg)
            except Exception as e:
                print(f'  [TELEGRAM ERROR] {e}')

    # -------------------------------------------------------------------
    # Session management
    # -------------------------------------------------------------------

    def _reset_session(self, today: date):
        """Reset all state for a new trading day."""
        print(f'\n{"=" * 70}')
        print(f'[SCANNER] New session: {today}')
        print(f'{"=" * 70}')

        self.current_session_date = today
        self.strategies.clear()
        self.last_fed_htf.clear()
        self.last_fed_5m.clear()
        self.setup_alerts_sent.clear()
        self.entry_alerts_sent.clear()
        self._first_cycle_done.clear()
        self.alerts_sent_count = 0
        self.active_setup_count = 0
        self.last_heartbeat = None
        self.last_prices.clear()

    # -------------------------------------------------------------------
    # Heartbeat
    # -------------------------------------------------------------------

    def _maybe_heartbeat(self, now: datetime):
        """Send heartbeat every 1 hour."""
        if self.last_heartbeat and (now - self.last_heartbeat).total_seconds() < 3600:
            return

        self.last_heartbeat = now
        time_str = now.strftime('%H:%M') + ' ET'

        # Build price line
        price_parts = []
        for symbol in self.symbols:
            price = self.last_prices.get(symbol)
            if price is not None:
                cfg = SYMBOL_CONFIGS.get(symbol, SYMBOL_CONFIGS['ES'])
                price_parts.append(f'{symbol}={_format_price(price, cfg["tick_size"])}')

        prices_line = ' | '.join(price_parts) if price_parts else 'No data yet'

        # Count active setups
        total_setups = sum(
            s.get_pending_count() for s in self.strategies.values()
        )

        msg = (
            f'[SWEEP SCANNER] {time_str}\n'
            f'{prices_line}\n'
            f'Active setups: {total_setups} | Alerts sent: {self.alerts_sent_count}'
        )

        print(f'\n  [HEARTBEAT] {msg}')

        if self.telegram:
            try:
                self.telegram.send(msg)
            except Exception:
                pass

    # -------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------

    def _interruptible_sleep(self, seconds: int):
        """Sleep in small chunks so we can stop quickly."""
        chunk = 30
        remaining = seconds
        while remaining > 0 and self.running:
            _time.sleep(min(chunk, remaining))
            remaining -= chunk

    def run(self):
        """Main scan loop."""
        print('[SCANNER] Starting ICT Sweep Scanner')
        print(f'  Symbols: {", ".join(self.symbols)}')
        print(f'  HTF timeframes: {", ".join(self.htf_timeframes)}')
        print(f'  Scan interval: {self.scan_interval}s')
        print(f'  Telegram: {"ON" if self.telegram else "OFF"}')
        print(f'  Debug: {"ON" if self.debug else "OFF"}')
        print()

        if self.telegram:
            try:
                self.telegram.send(
                    f'[SWEEP SCANNER] Started\n'
                    f'Symbols: {", ".join(self.symbols)}\n'
                    f'HTF: {", ".join(self.htf_timeframes)}\n'
                    f'Interval: {self.scan_interval}s'
                )
            except Exception:
                pass

        while self.running:
            try:
                now = _now_et()
                today = now.date()

                # Skip weekends
                if today.weekday() >= 5:
                    print('[SCANNER] Weekend — sleeping 60s')
                    self._interruptible_sleep(60)
                    continue

                # Check scanning hours
                if not _is_scanning_hours(now, self.symbols):
                    if self.debug:
                        print(f'[SCANNER] Outside scanning hours ({now.strftime("%H:%M")} ET) — sleeping 60s')
                    self._interruptible_sleep(60)
                    continue

                # Daily reset
                if today != self.current_session_date:
                    self._reset_session(today)

                # Scan each symbol
                print(f'\n[SCAN] {now.strftime("%H:%M:%S")} ET — scanning {len(self.symbols)} symbols')

                for symbol in self.symbols:
                    if not self.running:
                        break
                    if not _should_scan_symbol(symbol, now):
                        if self.debug:
                            print(f'  [{symbol}] Outside hours, skipping')
                        continue

                    try:
                        self._scan_symbol(symbol, now)
                    except Exception as e:
                        print(f'  [ERROR] {symbol}: {e}')
                        if self.debug:
                            traceback.print_exc()

                # Heartbeat
                self._maybe_heartbeat(now)

                # Sleep until next cycle
                print(f'[SCAN] Done — sleeping {self.scan_interval}s')
                self._interruptible_sleep(self.scan_interval)

            except KeyboardInterrupt:
                print('\n[SCANNER] Interrupted by user')
                self.running = False
            except Exception as e:
                print(f'[SCANNER] Unhandled error: {e}')
                traceback.print_exc()
                _time.sleep(30)

        print('[SCANNER] Stopped')
        if self.telegram:
            try:
                self.telegram.send('[SWEEP SCANNER] Stopped')
            except Exception:
                pass

    def _scan_symbol(self, symbol: str, now: datetime):
        """Scan one symbol across all HTF timeframes."""
        # Fetch 5m bars once (shared across HTF scans)
        try:
            bars_5m = fetch_futures_bars(symbol, interval='5m', n_bars=500)
        except Exception as e:
            print(f'  [ERROR] Fetch {symbol} 5m: {e}')
            return

        if not bars_5m:
            print(f'  [WARN] No 5m bars for {symbol}')
            return

        bars_5m = _strip_partial_bar(bars_5m, 5, now)

        # Track last price for heartbeat
        if bars_5m:
            self.last_prices[symbol] = bars_5m[-1].close

        if self.debug:
            print(f'  [{symbol}] Fetched {len(bars_5m)} 5m bars (last: {bars_5m[-1].timestamp.strftime("%H:%M") if bars_5m else "N/A"})')

        # Scan each HTF timeframe
        for htf_tf in self.htf_timeframes:
            try:
                self._scan_symbol_htf(symbol, htf_tf, bars_5m, now)
            except Exception as e:
                print(f'  [ERROR] {symbol}/{htf_tf}: {e}')
                if self.debug:
                    traceback.print_exc()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='ICT Liquidity Sweep Live Scanner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m runners.scan_ict_sweep
  python -m runners.scan_ict_sweep --symbols ES NQ SPY QQQ
  python -m runners.scan_ict_sweep --symbols ES --no-telegram --debug
  python -m runners.scan_ict_sweep --symbols ES NQ --scan-interval 180
        """
    )
    parser.add_argument(
        '--symbols', nargs='+', default=['ES', 'NQ'],
        help='Symbols to scan (default: ES NQ)',
    )
    parser.add_argument(
        '--htf-timeframes', nargs='+', default=['15m', '1h'],
        help='HTF timeframes for sweep detection (default: 15m 1h)',
    )
    parser.add_argument(
        '--scan-interval', type=int, default=300,
        help='Seconds between scan cycles (default: 300)',
    )
    parser.add_argument(
        '--no-telegram', action='store_true',
        help='Disable Telegram alerts (console only)',
    )
    parser.add_argument(
        '--debug', action='store_true',
        help='Enable debug output',
    )

    args = parser.parse_args()

    # Validate symbols
    for s in args.symbols:
        if s.upper() not in SYMBOL_CONFIGS:
            print(f'[ERROR] Unknown symbol: {s}. Valid: {list(SYMBOL_CONFIGS.keys())}')
            sys.exit(1)

    # Validate timeframes
    valid_htf = {'5m', '15m', '1h'}
    for tf in args.htf_timeframes:
        if tf not in valid_htf:
            print(f'[ERROR] Invalid HTF timeframe: {tf}. Valid: {sorted(valid_htf)}')
            sys.exit(1)

    scanner = SweepScanner(
        symbols=args.symbols,
        htf_timeframes=args.htf_timeframes,
        scan_interval=args.scan_interval,
        no_telegram=args.no_telegram,
        debug=args.debug,
    )

    scanner.run()


if __name__ == '__main__':
    main()
