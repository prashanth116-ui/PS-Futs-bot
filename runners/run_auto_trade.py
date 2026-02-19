"""
Automated Trading Runner

Monitors for FVG signals and automatically executes trades via webhook.

Usage:
    # Paper mode (no real orders)
    python -m runners.run_auto_trade --paper

    # Live mode (sends real orders)
    python -m runners.run_auto_trade --live

    # Single symbol
    python -m runners.run_auto_trade --symbol ES --paper
"""
import sys
sys.path.insert(0, '.')

import time
from datetime import datetime, time as dt_time
from typing import Optional
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations
from broker.webhook.tradovate_webhook import TradovateWebhook


class AutoTrader:
    """Automated trading based on FVG signals."""

    def __init__(
        self,
        symbols: list[str] = None,
        contracts: int = 3,
        paper_mode: bool = True,
        webhook_url: Optional[str] = None,
    ):
        self.symbols = symbols or ['ES', 'NQ']
        self.contracts = contracts
        self.paper_mode = paper_mode
        self.webhook = TradovateWebhook(webhook_url=webhook_url, paper_mode=paper_mode)

        # Track active positions
        self.positions = {}  # symbol -> position info
        self.daily_pnl = 0
        self.daily_trades = 0
        self.max_daily_loss = -1500  # Stop trading if down this much

        # Track signals to avoid duplicate entries
        self.active_signals = {}  # symbol -> signal info

    def check_for_entry(self, symbol: str, tick_size: float = 0.25) -> Optional[dict]:
        """Check if there's a valid entry signal."""
        tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25

        # Fetch latest data
        all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=500)
        if not all_bars:
            return None

        today = all_bars[-1].timestamp.date()
        today_bars = [b for b in all_bars if b.timestamp.date() == today]

        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 20:
            return None

        current_bar = session_bars[-1]
        current_price = current_bar.close
        current_time = current_bar.timestamp

        # Killzone filter (disabled for testing)
        # Uncomment to only trade during killzones:
        # if not (dt_time(9, 30) <= current_time.time() <= dt_time(11, 0)):
        #     if not (dt_time(3, 0) <= current_time.time() <= dt_time(5, 0)):
        #         return None

        # Detect FVGs
        fvg_config = {
            'min_fvg_ticks': 4,
            'tick_size': tick_size,
            'max_fvg_age_bars': 100,
            'invalidate_on_close_through': True
        }
        all_fvgs = detect_fvgs(session_bars, fvg_config)
        update_all_fvg_mitigations(all_fvgs, session_bars, fvg_config)

        # Check both directions
        for direction in ['LONG', 'SHORT']:
            is_long = direction == 'LONG'
            fvg_dir = 'BULLISH' if is_long else 'BEARISH'

            active_fvgs = [f for f in all_fvgs if f.direction == fvg_dir and not f.mitigated]
            active_fvgs.sort(key=lambda f: f.created_bar_index)

            if not active_fvgs:
                continue

            entry_fvg = active_fvgs[0]

            # Check if price is in entry zone
            in_zone = entry_fvg.low <= current_price <= entry_fvg.high

            if not in_zone:
                continue

            # Calculate entry levels (partial fill)
            edge_price = entry_fvg.high if is_long else entry_fvg.low
            midpoint_price = entry_fvg.midpoint
            avg_entry = (edge_price * 1 + midpoint_price * 2) / 3

            # Stop and targets
            if is_long:
                stop_price = entry_fvg.low
                risk = avg_entry - stop_price
            else:
                stop_price = entry_fvg.high
                risk = stop_price - avg_entry

            if risk <= 0:
                continue

            target_4r = avg_entry + (4 * risk) if is_long else avg_entry - (4 * risk)
            target_8r = avg_entry + (8 * risk) if is_long else avg_entry - (8 * risk)

            return {
                'symbol': symbol,
                'direction': direction,
                'current_price': current_price,
                'avg_entry': avg_entry,
                'edge_price': edge_price,
                'midpoint_price': midpoint_price,
                'stop_price': stop_price,
                'target_4r': target_4r,
                'target_8r': target_8r,
                'risk': risk,
                'risk_dollars': (risk / tick_size) * tick_value * self.contracts,
                'fvg': entry_fvg,
                'time': current_time,
            }

        return None

    def execute_entry(self, signal: dict) -> bool:
        """Execute an entry signal."""
        symbol = signal['symbol']
        direction = signal['direction']

        # Check if we already have a position
        if symbol in self.positions:
            print(f"[SKIP] Already have position in {symbol}")
            return False

        # Check daily loss limit
        if self.daily_pnl <= self.max_daily_loss:
            print(f"[SKIP] Daily loss limit reached: ${self.daily_pnl:.2f}")
            return False

        # Check if we already signaled this setup (avoid duplicate entries)
        signal_key = f"{symbol}_{direction}_{signal['fvg'].created_bar_index}"
        if signal_key in self.active_signals:
            print("[SKIP] Already signaled this setup")
            return False

        print(f"\n{'='*60}")
        print(f"EXECUTING {direction} on {symbol}")
        print(f"{'='*60}")
        print(f"Entry: {signal['current_price']:.2f}")
        print(f"Stop: {signal['stop_price']:.2f}")
        print(f"Target 4R: {signal['target_4r']:.2f}")
        print(f"Target 8R: {signal['target_8r']:.2f}")
        print(f"Risk: ${signal['risk_dollars']:.2f}")
        print(f"{'='*60}")

        # Send order
        action = "BUY" if direction == "LONG" else "SELL"
        result = self.webhook.send_bracket_order(
            symbol=symbol,
            action=action,
            qty=self.contracts,
            entry_price=signal['current_price'],
            stop_price=signal['stop_price'],
            target_prices=[signal['target_4r'], signal['target_8r']]
        )

        if result.get('success'):
            # Track position
            self.positions[symbol] = {
                'direction': direction,
                'entry_price': signal['current_price'],
                'stop_price': signal['stop_price'],
                'target_4r': signal['target_4r'],
                'target_8r': signal['target_8r'],
                'qty': self.contracts,
                'entry_time': signal['time'],
            }
            self.active_signals[signal_key] = signal
            self.daily_trades += 1
            print("[SUCCESS] Order sent")
            return True
        else:
            print(f"[FAILED] Order failed: {result.get('error')}")
            return False

    def check_for_exit(self, symbol: str) -> Optional[str]:
        """Check if we should exit a position."""
        if symbol not in self.positions:
            return None

        position = self.positions[symbol]

        # Fetch current price
        all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=10)
        if not all_bars:
            return None

        current_price = all_bars[-1].close
        direction = position['direction']
        is_long = direction == 'LONG'

        # Check stop hit
        if is_long:
            if current_price <= position['stop_price']:
                return 'STOP'
        else:
            if current_price >= position['stop_price']:
                return 'STOP'

        # Check targets (simplified - in reality would track partial exits)
        if is_long:
            if current_price >= position['target_8r']:
                return 'TARGET_8R'
            elif current_price >= position['target_4r']:
                return 'TARGET_4R'
        else:
            if current_price <= position['target_8r']:
                return 'TARGET_8R'
            elif current_price <= position['target_4r']:
                return 'TARGET_4R'

        return None

    def run_cycle(self):
        """Run one monitoring cycle."""
        print(f"\n{'='*60}")
        print(f"AUTO TRADER | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Mode: {'PAPER' if self.paper_mode else 'LIVE'}")
        print(f"Positions: {len(self.positions)} | Trades Today: {self.daily_trades}")
        print(f"{'='*60}")

        for symbol in self.symbols:
            tick_size = 0.25 if symbol in ['ES', 'NQ'] else 0.01

            # Check for exits first
            exit_reason = self.check_for_exit(symbol)
            if exit_reason:
                print(f"\n[EXIT] {symbol} - {exit_reason}")
                position = self.positions[symbol]
                close_action = "SELL" if position['direction'] == "LONG" else "BUY"
                self.webhook.send_market_order(symbol, close_action, position['qty'])
                del self.positions[symbol]
                continue

            # Check for new entries
            signal = self.check_for_entry(symbol, tick_size)

            if signal:
                print(f"\n[SIGNAL] {symbol} {signal['direction']} @ {signal['current_price']:.2f}")
                print(f"  FVG Zone: {signal['fvg'].low:.2f} - {signal['fvg'].high:.2f}")
                print(f"  Stop: {signal['stop_price']:.2f} | Risk: ${signal['risk_dollars']:.2f}")

                self.execute_entry(signal)
            else:
                # Fetch current price for display
                bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=5)
                if bars:
                    print(f"\n{symbol}: {bars[-1].close:.2f} - No signal")

    def run(self, interval_seconds: int = 180):
        """Run continuous automated trading."""
        print("=" * 60)
        print("ICT FVG AutoTrader")
        print("=" * 60)
        print(f"Symbols: {', '.join(self.symbols)}")
        print(f"Contracts: {self.contracts}")
        print(f"Mode: {'PAPER (no real orders)' if self.paper_mode else 'LIVE'}")
        print(f"Interval: {interval_seconds // 60} minutes")
        print(f"Max Daily Loss: ${abs(self.max_daily_loss)}")
        print("=" * 60)

        if not self.paper_mode:
            print("\n*** WARNING: LIVE MODE - Real orders will be sent! ***")
            print("Press Ctrl+C within 10 seconds to cancel...")
            time.sleep(10)

        print("\nStarting auto trader... (Ctrl+C to stop)")

        try:
            while True:
                self.run_cycle()
                print(f"\nNext check in {interval_seconds // 60} minutes...")
                time.sleep(interval_seconds)

        except KeyboardInterrupt:
            print("\n\nStopped by user.")

        # Print summary
        print("\n" + "=" * 60)
        print("SESSION SUMMARY")
        print("=" * 60)
        print(f"Trades executed: {self.daily_trades}")
        print(f"Open positions: {len(self.positions)}")
        print(f"Orders logged: {len(self.webhook.get_order_log())}")
        print("=" * 60)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='ICT FVG AutoTrader')
    parser.add_argument('--symbol', default='ES,NQ', help='Symbols to trade (comma-separated)')
    parser.add_argument('--contracts', type=int, default=3, help='Contracts per trade')
    parser.add_argument('--interval', type=int, default=180, help='Check interval in seconds')
    parser.add_argument('--paper', action='store_true', help='Paper trading mode (default)')
    parser.add_argument('--live', action='store_true', help='Live trading mode')

    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbol.split(',')]
    paper_mode = not args.live  # Default to paper mode

    trader = AutoTrader(
        symbols=symbols,
        contracts=args.contracts,
        paper_mode=paper_mode,
    )

    trader.run(interval_seconds=args.interval)


if __name__ == '__main__':
    main()
