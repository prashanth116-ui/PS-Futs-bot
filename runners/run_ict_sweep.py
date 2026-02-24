"""
ICT Liquidity Sweep Strategy — Backtest Runner

YAML-driven, multi-symbol, single-timeframe architecture.

Usage:
    python -m runners.run_ict_sweep ES 14
    python -m runners.run_ict_sweep ES NQ 14
    python -m runners.run_ict_sweep ES 14 --t1-r=4 --trail-r=8 --disp=1.5
    python -m runners.run_ict_sweep ES 14 --debug
    python -m runners.run_ict_sweep ES 14 --config=path/to/custom.yaml
"""
import sys
sys.path.insert(0, '.')

import argparse
import pickle
from pathlib import Path
from datetime import time as dt_time, timedelta

import yaml

from runners.tradingview_loader import fetch_futures_bars
from strategies.ict_sweep.strategy import ICTSweepStrategy, TradeEntry
from strategies.ict_sweep.trade_sim import simulate_trade
from strategies.ict_sweep.filters.session import get_session_name

CACHE_DIR = Path('.cache')
CACHE_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = Path('config/strategies/ict_sweep.yaml')


def load_config(config_path: Path = DEFAULT_CONFIG) -> dict:
    """Load YAML config."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def merge_symbol_config(base: dict, symbol: str) -> dict:
    """Merge per-symbol overrides into base config."""
    merged = {}
    for k, v in base.items():
        if k == 'symbols':
            continue
        merged[k] = v

    sym_overrides = base.get('symbols', {}).get(symbol, {})
    for k, v in sym_overrides.items():
        merged[k] = v

    return merged


def apply_cli_overrides(config: dict, args) -> dict:
    """Apply CLI argument overrides to config."""
    if args.t1_r is not None:
        config['t1_r'] = args.t1_r
    if args.trail_r is not None:
        config['trail_r'] = args.trail_r
    if args.disp is not None:
        config['displacement_multiplier'] = args.disp
    if args.max_trades is not None:
        config['max_daily_trades'] = args.max_trades
    if args.max_losses is not None:
        config['max_daily_losses'] = args.max_losses
    if args.debug:
        config['debug'] = True
    return config


def format_et(ts):
    """Format timestamp as ET time string."""
    return ts.strftime('%H:%M')


def run_symbol(symbol: str, days: int, config: dict, debug: bool = False):
    """Run backtest for a single symbol. Returns list of trade results."""
    tick_size = config.get('tick_size', 0.25)
    tick_value = config.get('tick_value', 12.50)
    contracts_first = config.get('contracts', 3)
    contracts_sub = config.get('contracts_subsequent', 2)
    t1_r = config.get('t1_r', 3)
    trail_r = config.get('trail_r', 6)
    t2_buffer = config.get('t2_buffer_ticks', 4)
    runner_buffer = config.get('runner_buffer_ticks', 6)
    timeframe = config.get('timeframe', '5m')

    use_mtf_fvg = config.get('use_mtf_fvg', False)
    mtf_timeframe = config.get('mtf_timeframe', '3m')

    # Fetch bars
    bars_per_day = 78 if timeframe == '5m' else 130
    n_bars = days * bars_per_day + 1500
    print(f"Fetching {symbol} {timeframe} data ({n_bars} bars)...")
    all_bars = fetch_futures_bars(symbol=symbol, interval=timeframe, n_bars=n_bars)

    if not all_bars:
        print(f"No data available for {symbol}")
        return []

    # Fetch MTF bars for dual-TF FVG detection
    all_mtf_bars = []
    if use_mtf_fvg:
        mtf_bars_per_day = 130 if mtf_timeframe == '3m' else 78
        mtf_n_bars = days * mtf_bars_per_day + 1500
        print(f"Fetching {symbol} {mtf_timeframe} data ({mtf_n_bars} bars) for FVG...")
        all_mtf_bars = fetch_futures_bars(symbol=symbol, interval=mtf_timeframe, n_bars=mtf_n_bars)
        if not all_mtf_bars:
            print(f"Warning: No MTF data, falling back to single-TF")
            all_mtf_bars = []

    # Group by date
    dates = sorted(set(b.timestamp.date() for b in all_bars))
    run_dates = dates[-days:]

    mtf_label = f" + {mtf_timeframe} FVG" if use_mtf_fvg and all_mtf_bars else ""
    print(f"\n{'='*110}")
    print(f"{symbol} ICT LIQUIDITY SWEEP STRATEGY BACKTEST")
    print(f"TF: {timeframe}{mtf_label} | Days: {len(run_dates)} | Contracts: {contracts_first}/{contracts_sub} | "
          f"T1={t1_r}R Trail={trail_r}R | Disp={config.get('displacement_multiplier', 1.35)}x | "
          f"Retry={config.get('mitigation_retry_bars', 3)}bars")
    print(f"{'='*110}\n")
    print(f"{'Date':<12} | {'Time':<5} | {'Dir':<5} | {'Entry':>10} | {'Stop':>10} | "
          f"{'Risk':>6} | {'Result':<6} | {'P/L':>12} | {'Session':<10} | Filters")
    print("-" * 130)

    all_trades = []
    total_wins = 0
    total_losses = 0
    total_pnl = 0.0

    for day in run_dates:
        # Build session bars: overnight (prev day 18:00+) + current day through 16:00
        overnight_start = dt_time(18, 0)
        session_end = dt_time(16, 0)
        prev_day = day - timedelta(days=1)
        if prev_day.weekday() == 5:  # Saturday -> Friday
            prev_day = prev_day - timedelta(days=1)

        day_bars = [b for b in all_bars
                    if (b.timestamp.date() == prev_day and b.timestamp.time() >= overnight_start)
                    or (b.timestamp.date() == day and b.timestamp.time() <= session_end)]

        if len(day_bars) < 50:
            print(f"  [{day}] Skipping - insufficient bars ({len(day_bars)})")
            continue

        # Print overnight info
        overnight_only = [b for b in day_bars if b.timestamp.date() == prev_day]
        if overnight_only:
            ovn_high = max(b.high for b in overnight_only)
            ovn_low = min(b.low for b in overnight_only)
            print(f"  [{day}] Overnight: High={ovn_high:.2f} Low={ovn_low:.2f} (bars: {len(overnight_only)})")

        # Build MTF day bars (same time window as 5m)
        day_mtf_bars = []
        if use_mtf_fvg and all_mtf_bars:
            session_start_mtf = dt_time(8, 0)
            day_mtf_bars = [b for b in all_mtf_bars
                            if b.timestamp.date() == day
                            and session_start_mtf <= b.timestamp.time() <= session_end]

        # Initialize strategy
        strategy = ICTSweepStrategy(config)

        # Warm up with lookback bars (before this day's window)
        lookback_bars = [b for b in all_bars if b.timestamp.date() < prev_day][-50:]
        for bar in lookback_bars:
            strategy.bars.append(bar)

        # MTF lookback
        if use_mtf_fvg and all_mtf_bars:
            mtf_lookback = [b for b in all_mtf_bars if b.timestamp.date() < day][-100:]
            for bar in mtf_lookback:
                strategy.mtf_bars.append(bar)

        # Track per-direction trade count for dynamic sizing
        dir_trades = {'LONG': 0, 'SHORT': 0}

        # Process bars
        bar_idx = 0
        mtf_idx = 0
        day_trade_count = 0

        while bar_idx < len(day_bars):
            bar = day_bars[bar_idx]

            # Feed MTF bars up to this 5m bar's time
            while mtf_idx < len(day_mtf_bars) and day_mtf_bars[mtf_idx].timestamp <= bar.timestamp:
                strategy.process_mtf_bar(day_mtf_bars[mtf_idx])
                mtf_idx += 1

            entries = strategy.process_bar(bar)

            for entry in entries:
                # Dynamic sizing: 1st trade of direction = contracts_first, subsequent = contracts_sub
                dir_count = dir_trades.get(entry.direction, 0)
                trade_contracts = contracts_first if dir_count == 0 else contracts_sub

                # Simulate from remaining bars
                remaining_bars = day_bars[bar_idx:]
                result = simulate_trade(
                    remaining_bars, entry, tick_size, tick_value,
                    trade_contracts, t1_r=t1_r, trail_r=trail_r,
                    t2_buffer_ticks=t2_buffer, runner_buffer_ticks=runner_buffer,
                    debug=debug,
                )

                if result:
                    dir_trades[entry.direction] = dir_count + 1
                    day_trade_count += 1
                    is_win = result['pnl_dollars'] > 0
                    is_loss = result['pnl_dollars'] < 0

                    exit_bar_idx = min(bar_idx + result.get('bars_held', 1), len(day_bars) - 1)
                    exit_time = day_bars[exit_bar_idx].timestamp

                    if is_win:
                        total_wins += 1
                        result_str = 'WIN'
                    elif is_loss:
                        total_losses += 1
                        strategy.on_trade_result(result['pnl_dollars'], entry.direction, exit_time)
                        result_str = 'LOSS'
                    else:
                        result_str = 'BE'

                    total_pnl += result['pnl_dollars']
                    result['entry_obj'] = entry
                    result['date'] = day
                    all_trades.append(result)

                    session = get_session_name(entry.timestamp)
                    est_time = format_et(entry.timestamp)

                    print(f"{day} | {est_time:<5} | {entry.direction:<5} | "
                          f"{entry.entry_price:>10.2f} | {entry.stop_price:>10.2f} | "
                          f"{entry.risk_ticks:>6.1f} | {result_str:<6} | "
                          f"${result['pnl_dollars']:>+10,.2f} | {session:<10} | "
                          f"{entry.filter_summary}")

            bar_idx += 1

        # Day summary
        day_trades_list = [t for t in all_trades if t.get('date') == day]
        day_pnl = sum(t['pnl_dollars'] for t in day_trades_list)
        print(f"  [{day}] Trades: {day_trade_count}, Day P/L: ${day_pnl:+,.2f}")

        # Cache day results for plotter
        day_cache = CACHE_DIR / f'ict_sweep_{symbol}_{day}.pkl'
        with open(day_cache, 'wb') as f:
            pickle.dump({
                'trades': day_trades_list,
                'day_bars': day_bars,
                'config': config,
            }, f)

    # Print symbol summary
    print("-" * 130)
    print()
    _print_summary(symbol, all_trades, total_wins, total_losses, total_pnl)

    return all_trades


def _print_summary(symbol: str, all_trades: list, wins: int, losses: int, total_pnl: float):
    """Print backtest summary."""
    total = wins + losses
    wr = (wins / total * 100) if total > 0 else 0

    win_trades = [t for t in all_trades if t['pnl_dollars'] > 0]
    loss_trades = [t for t in all_trades if t['pnl_dollars'] < 0]
    avg_win = sum(t['pnl_dollars'] for t in win_trades) / len(win_trades) if win_trades else 0
    avg_loss = sum(t['pnl_dollars'] for t in loss_trades) / len(loss_trades) if loss_trades else 0

    print(f"{'='*60}")
    print(f"  {symbol} SUMMARY")
    print(f"{'='*60}")
    print(f"  Total Trades:  {total}")
    print(f"  Wins:          {wins}")
    print(f"  Losses:        {losses}")
    print(f"  Win Rate:      {wr:.1f}%")
    print(f"  Avg Win:       ${avg_win:+,.2f}")
    print(f"  Avg Loss:      ${avg_loss:+,.2f}")

    if loss_trades and sum(t['pnl_dollars'] for t in loss_trades) != 0:
        pf = abs(sum(t['pnl_dollars'] for t in win_trades) / sum(t['pnl_dollars'] for t in loss_trades))
        print(f"  Profit Factor: {pf:.2f}")

    print(f"\n  TOTAL P/L:     ${total_pnl:+,.2f}")
    print(f"{'='*60}\n")


def parse_args():
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description='ICT Sweep Strategy Backtest')
    parser.add_argument('args', nargs='+', help='SYMBOL [SYMBOL2...] DAYS')
    parser.add_argument('--t1-r', type=int, default=None, help='T1 R-multiple (default: from config)')
    parser.add_argument('--trail-r', type=int, default=None, help='Trail R-multiple (default: from config)')
    parser.add_argument('--disp', type=float, default=None, help='Displacement multiplier')
    parser.add_argument('--max-trades', type=int, default=None, help='Max daily trades')
    parser.add_argument('--max-losses', type=int, default=None, help='Max daily losses per direction')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--config', type=str, default=None, help='Path to custom YAML config')

    return parser.parse_args()


def main():
    args = parse_args()

    # Parse positional: symbols + days (last numeric arg is days)
    symbols = []
    days = 14
    for a in args.args:
        try:
            days = int(a)
        except ValueError:
            symbols.append(a.upper())

    if not symbols:
        symbols = ['ES']

    # Load config
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG
    base_config = load_config(config_path)

    # Run each symbol
    grand_trades = []
    grand_pnl = 0.0
    grand_wins = 0
    grand_losses = 0

    for symbol in symbols:
        config = merge_symbol_config(base_config, symbol)
        config = apply_cli_overrides(config, args)

        trades = run_symbol(symbol, days, config, debug=args.debug)
        grand_trades.extend(trades)

        for t in trades:
            if t['pnl_dollars'] > 0:
                grand_wins += 1
            elif t['pnl_dollars'] < 0:
                grand_losses += 1
        grand_pnl += sum(t['pnl_dollars'] for t in trades)

    # Grand summary (multi-symbol)
    if len(symbols) > 1:
        print(f"\n{'='*60}")
        print(f"  GRAND TOTAL ({', '.join(symbols)})")
        print(f"{'='*60}")
        total = grand_wins + grand_losses
        wr = (grand_wins / total * 100) if total > 0 else 0
        print(f"  Total Trades:  {total}")
        print(f"  Win Rate:      {wr:.1f}%")
        print(f"  TOTAL P/L:     ${grand_pnl:+,.2f}")
        print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
