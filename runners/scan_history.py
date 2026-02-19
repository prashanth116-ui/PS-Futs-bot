"""
Historical ICT Sweep Scanner — check all symbols for alerts over N days.

Usage:
    python -m runners.scan_history
    python -m runners.scan_history --days 30 --htf 15m 1h
"""
import sys
sys.path.insert(0, '.')

import argparse
from datetime import timedelta, time as dt_time
from collections import defaultdict

from runners.tradingview_loader import fetch_futures_bars
from strategies.ict_sweep.strategy import ICTSweepStrategy, TradeSetup
from strategies.ict_sweep.filters.displacement import calculate_avg_body
from runners.scan_ict_sweep import SYMBOL_CONFIGS, EQUITY_SYMBOLS


ALL_SYMBOLS = [
    'ES', 'NQ',
    'SPY', 'QQQ',
    'NVDA', 'TSLA', 'AAPL', 'AMZN', 'META', 'MSFT', 'AMD', 'GOOGL',
    'UNH', 'PLTR', 'COIN',
]


def make_config(symbol):
    cfg = SYMBOL_CONFIGS[symbol]
    return {
        'symbol': symbol, 'tick_size': cfg['tick_size'], 'tick_value': cfg['tick_value'],
        'swing_lookback': 20, 'swing_strength': 3,
        'min_sweep_ticks': 2, 'max_sweep_ticks': cfg['max_sweep'],
        'displacement_multiplier': 2.0, 'avg_body_lookback': 20,
        'min_fvg_ticks': cfg['min_fvg'], 'max_fvg_age_bars': 50,
        'mss_lookback': 20, 'mss_swing_strength': 1,
        'stop_buffer_ticks': 2, 'min_risk_ticks': cfg['min_risk'],
        'max_risk_ticks': cfg['max_risk'],
        'loss_cooldown_minutes': 0, 'allow_lunch': True, 'require_killzone': False,
        'max_daily_trades': 10, 'max_daily_losses': 10,
        'use_mtf_for_fvg': True, 'entry_on_mitigation': True,
        'use_trend_filter': False, 'stop_buffer_pts': 2.0 if symbol not in EQUITY_SYMBOLS else 0.10,
        't1_r': 3, 'trail_r': 6, 'debug': False,
    }


def scan_symbol(symbol, htf_tf, n_bars_htf=500):
    """Scan one symbol on one HTF timeframe, return all setups and entries."""
    SYMBOL_CONFIGS[symbol]
    is_equity = symbol in EQUITY_SYMBOLS
    session_start = dt_time(9, 30) if is_equity else dt_time(8, 0)
    session_end = dt_time(16, 0)

    print(f'  Fetching {symbol} ({htf_tf})...', end='', flush=True)
    bars_5m = fetch_futures_bars(symbol, interval='5m', n_bars=500)
    bars_htf = fetch_futures_bars(symbol, interval=htf_tf, n_bars=n_bars_htf)

    if not bars_5m or not bars_htf:
        print(' no data')
        return [], []

    dates = sorted(set(b.timestamp.date() for b in bars_htf))
    print(f' {len(dates)} days, {len(bars_htf)} HTF bars, {len(bars_5m)} 5m bars')

    all_setups = []
    all_entries = []

    for day in dates:
        day_htf = [b for b in bars_htf if b.timestamp.date() == day
                   and session_start <= b.timestamp.time() <= session_end]
        day_5m = [b for b in bars_5m if b.timestamp.date() == day
                  and session_start <= b.timestamp.time() <= session_end]

        if len(day_htf) < 5 or len(day_5m) < 10:
            continue

        config = make_config(symbol)
        strategy = ICTSweepStrategy(config)

        lookback_htf = [b for b in bars_htf if b.timestamp.date() < day][-50:]
        for b in lookback_htf:
            strategy.htf_bars.append(b)
        lookback_5m = [b for b in bars_5m if b.timestamp.date() < day][-100:]
        for b in lookback_5m:
            strategy.mtf_bars.append(b)
        if strategy.htf_bars:
            strategy.avg_body = calculate_avg_body(strategy.htf_bars, strategy.avg_body_lookback)

        strategy.daily_trades = 0
        strategy.daily_losses = 0
        strategy.pending_sweeps.clear()
        strategy.pending_setups.clear()

        mtf_cursor = 0
        for bar in day_htf:
            while mtf_cursor < len(day_5m) and day_5m[mtf_cursor].timestamp <= bar.timestamp:
                strategy.update_mtf(day_5m[mtf_cursor])
                mtf_cursor += 1

            setup = strategy.update_htf(bar)
            if setup:
                all_setups.append({
                    'symbol': symbol,
                    'htf': htf_tf,
                    'date': day,
                    'time': bar.timestamp.strftime('%H:%M'),
                    'direction': setup.sweep.sweep_type,
                    'sweep_price': setup.sweep.sweep_price,
                    'fvg_bottom': setup.fvg.bottom,
                    'fvg_top': setup.fvg.top,
                    'displacement': setup.displacement_ratio,
                })

            result = strategy.check_htf_mitigation(bar)
            if isinstance(result, TradeSetup):
                all_entries.append({
                    'symbol': symbol,
                    'htf': htf_tf,
                    'date': day,
                    'time': bar.timestamp.strftime('%H:%M'),
                    'direction': result.direction,
                    'entry': result.entry_price,
                    'stop': result.stop_price,
                    't1': result.t1_price,
                    'risk_ticks': result.risk_ticks,
                    'fvg': f'{result.fvg.bottom:.2f}-{result.fvg.top:.2f}',
                })

    return all_setups, all_entries


def main():
    parser = argparse.ArgumentParser(description='Historical ICT Sweep Scanner')
    parser.add_argument('--symbols', nargs='+', default=None,
                        help='Symbols to scan (default: all)')
    parser.add_argument('--htf', nargs='+', default=['15m', '1h'],
                        help='HTF timeframes (default: 15m 1h)')
    args = parser.parse_args()

    symbols = [s.upper() for s in args.symbols] if args.symbols else ALL_SYMBOLS

    print('=' * 110)
    print('ICT SWEEP SCANNER — HISTORICAL ALERT ANALYSIS')
    print(f'Symbols: {", ".join(symbols)}')
    print(f'HTF: {", ".join(args.htf)}')
    print('=' * 110)
    print()

    grand_setups = []
    grand_entries = []

    for sym in symbols:
        for htf_tf in args.htf:
            n_bars = 500 if htf_tf == '15m' else 200
            setups, entries = scan_symbol(sym, htf_tf, n_bars)
            grand_setups.extend(setups)
            grand_entries.extend(entries)

    # --- Summary by symbol ---
    print()
    print('=' * 110)
    print(f'{"Symbol":<8} {"HTF":<5} {"Setups":>7} {"Entries":>8} {"Days":>5} | {"Directions":<30} | Recent Entry')
    print('-' * 110)

    sym_htf_stats = defaultdict(lambda: {'setups': 0, 'entries': 0, 'days': set(), 'dirs': defaultdict(int), 'last': None})
    for s in grand_setups:
        k = (s['symbol'], s['htf'])
        sym_htf_stats[k]['setups'] += 1
        sym_htf_stats[k]['days'].add(s['date'])
    for e in grand_entries:
        k = (e['symbol'], e['htf'])
        sym_htf_stats[k]['entries'] += 1
        sym_htf_stats[k]['days'].add(e['date'])
        sym_htf_stats[k]['dirs'][e['direction']] += 1
        if sym_htf_stats[k]['last'] is None or e['date'] > sym_htf_stats[k]['last']['date']:
            sym_htf_stats[k]['last'] = e

    total_setups = 0
    total_entries = 0
    for sym in symbols:
        for htf_tf in args.htf:
            k = (sym, htf_tf)
            st = sym_htf_stats[k]
            total_setups += st['setups']
            total_entries += st['entries']
            dirs_str = ', '.join(f'{d}:{c}' for d, c in sorted(st['dirs'].items()))
            last_str = ''
            if st['last']:
                l = st['last']
                last_str = f'{l["date"]} {l["time"]} {l["direction"]} @{l["entry"]:.2f}'
            print(f'{sym:<8} {htf_tf:<5} {st["setups"]:>7} {st["entries"]:>8} {len(st["days"]):>5} | {dirs_str:<30} | {last_str}')

    print('-' * 110)
    print(f'{"TOTAL":<8} {"":5} {total_setups:>7} {total_entries:>8}')

    # --- Recent entry alerts (last 10 days) ---
    print()
    print('=' * 110)
    print('RECENT ENTRY ALERTS (last 10 trading days)')
    print('=' * 110)

    recent = sorted(grand_entries, key=lambda x: (x['date'], x['time']), reverse=True)
    if recent:
        cutoff = recent[0]['date'] - timedelta(days=14)
        recent = [e for e in recent if e['date'] >= cutoff]

    if not recent:
        print('  No entry alerts found.')
    else:
        current_date = None
        for e in recent:
            if e['date'] != current_date:
                current_date = e['date']
                print(f'\n  --- {current_date} ({current_date.strftime("%A")}) ---')
            print(f'    {e["symbol"]:<7} {e["htf"]:<4} {e["time"]} | {e["direction"]:<8} | '
                  f'Entry={e["entry"]:.2f} Stop={e["stop"]:.2f} T1={e["t1"]:.2f} | '
                  f'Risk={e["risk_ticks"]:.0f}t | FVG={e["fvg"]}')

    print(f'\nTotal: {len(grand_entries)} entry alerts, {len(grand_setups)} setups across {len(symbols)} symbols')


if __name__ == '__main__':
    main()
