"""
Compare Baseline (5/5 filters) vs Hybrid (2 mandatory + 2/3 optional) filter modes.

MANDATORY: DI Direction + FVG Size >= 5 ticks
OPTIONAL (2/3): Displacement >= 1x | ADX >= 11 | EMA Trend
"""
import sys
sys.path.insert(0, '.')
from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_fvg_mitigation
from runners.run_v10_dual_entry import calculate_adx, calculate_ema

def backtest_filter_modes(symbol, days=30):
    """Compare baseline (5/5) vs hybrid (mandatory + 2/3 optional)."""
    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25 if symbol == 'MES' else 0.50
    min_fvg_ticks = 5
    min_risk_pts = 1.5 if symbol in ['ES', 'MES'] else 6.0

    print(f'Fetching {symbol} data...')
    all_bars = fetch_futures_bars(symbol, interval='3m', n_bars=8000)
    if not all_bars:
        return None, None

    dates = sorted(set(b.timestamp.date() for b in all_bars))[-days:]

    # Track results for both modes
    baseline = {'trades': 0, 'wins': 0, 'pnl': 0, 'max_dd': 0, 'peak_pnl': 0, 'daily_pnl': {}}
    hybrid = {'trades': 0, 'wins': 0, 'pnl': 0, 'max_dd': 0, 'peak_pnl': 0, 'daily_pnl': {}}

    for target_date in dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == target_date]
        session_bars = [b for b in day_bars if dt_time(4,0) <= b.timestamp.time() <= dt_time(16,0)]

        if len(session_bars) < 50:
            continue

        body_sizes = [abs(b.close - b.open) for b in session_bars[:50]]
        avg_body = sum(body_sizes) / len(body_sizes) if body_sizes else tick_size * 4

        fvg_config = {'min_fvg_ticks': 2, 'tick_size': tick_size, 'max_fvg_age_bars': 200, 'invalidate_on_close_through': True}
        day_fvgs = detect_fvgs(day_bars, fvg_config)

        baseline['daily_pnl'][target_date] = 0
        hybrid['daily_pnl'][target_date] = 0

        for fvg in day_fvgs:
            creating_bar = day_bars[fvg.created_bar_index]
            bar_time = creating_bar.timestamp.time()

            if bar_time < dt_time(9, 30) or bar_time > dt_time(15, 45):
                continue

            entry_hour = creating_bar.timestamp.hour
            if 12 <= entry_hour < 14:
                continue
            if symbol in ['NQ', 'MNQ'] and entry_hour >= 14:
                continue

            direction = 'LONG' if fvg.direction == 'BULLISH' else 'SHORT'
            is_long = direction == 'LONG'

            bars_to_entry = day_bars[:fvg.created_bar_index + 1]
            body = abs(creating_bar.close - creating_bar.open)
            fvg_size_ticks = (fvg.high - fvg.low) / tick_size
            disp_ratio = body / avg_body if avg_body > 0 else 0
            adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)
            ema20 = calculate_ema(bars_to_entry, 20)
            ema50 = calculate_ema(bars_to_entry, 50)

            # MANDATORY filters (must both pass)
            mandatory_1_di = adx is None or (plus_di > minus_di if is_long else minus_di > plus_di)
            mandatory_2_size = fvg_size_ticks >= min_fvg_ticks

            # OPTIONAL filters (2/3 must pass)
            optional_1_disp = disp_ratio >= 1.0
            optional_2_adx = adx is None or adx >= 11
            optional_3_ema = ema20 is None or ema50 is None or (ema20 > ema50 if is_long else ema20 < ema50)

            optional_passed = sum([optional_1_disp, optional_2_adx, optional_3_ema])

            # Check both filter modes
            baseline_pass = mandatory_1_di and mandatory_2_size and optional_1_disp and optional_2_adx and optional_3_ema
            hybrid_pass = mandatory_1_di and mandatory_2_size and optional_passed >= 2

            # Entry setup
            entry_price = fvg.midpoint
            stop_price = fvg.low - (2 * tick_size) if is_long else fvg.high + (2 * tick_size)
            risk = abs(entry_price - stop_price)

            if risk < min_risk_pts:
                continue

            target_4r = entry_price + (4 * risk) if is_long else entry_price - (4 * risk)

            # Simulate trade
            hit_target = False
            hit_stop = False

            for i in range(fvg.created_bar_index + 1, len(day_bars)):
                bar = day_bars[i]
                if is_long:
                    if bar.low <= stop_price:
                        hit_stop = True
                        break
                    if bar.high >= target_4r:
                        hit_target = True
                        break
                else:
                    if bar.high >= stop_price:
                        hit_stop = True
                        break
                    if bar.low <= target_4r:
                        hit_target = True
                        break

            # Calculate P/L
            if hit_target:
                pnl = (4 * risk / tick_size) * tick_value * 3
                is_win = True
            elif hit_stop:
                pnl = -(risk / tick_size) * tick_value * 3
                is_win = False
            else:
                pnl = 0
                is_win = True

            # Record for baseline
            if baseline_pass:
                baseline['trades'] += 1
                baseline['pnl'] += pnl
                baseline['daily_pnl'][target_date] += pnl
                if is_win:
                    baseline['wins'] += 1
                if baseline['pnl'] > baseline['peak_pnl']:
                    baseline['peak_pnl'] = baseline['pnl']
                dd = baseline['peak_pnl'] - baseline['pnl']
                if dd > baseline['max_dd']:
                    baseline['max_dd'] = dd

            # Record for hybrid
            if hybrid_pass:
                hybrid['trades'] += 1
                hybrid['pnl'] += pnl
                hybrid['daily_pnl'][target_date] += pnl
                if is_win:
                    hybrid['wins'] += 1
                if hybrid['pnl'] > hybrid['peak_pnl']:
                    hybrid['peak_pnl'] = hybrid['pnl']
                dd = hybrid['peak_pnl'] - hybrid['pnl']
                if dd > hybrid['max_dd']:
                    hybrid['max_dd'] = dd

    # Calculate losing days
    baseline['losing_days'] = sum(1 for d, p in baseline['daily_pnl'].items() if p < 0)
    hybrid['losing_days'] = sum(1 for d, p in hybrid['daily_pnl'].items() if p < 0)
    baseline['total_days'] = len([d for d in baseline['daily_pnl'] if baseline['daily_pnl'][d] != 0])
    hybrid['total_days'] = len([d for d in hybrid['daily_pnl'] if hybrid['daily_pnl'][d] != 0])

    return baseline, hybrid


if __name__ == '__main__':
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    print('='*90)
    print(f'{days}-DAY BACKTEST: BASELINE (5/5) vs HYBRID (2 mandatory + 2/3 optional)')
    print('='*90)
    print()
    print('MANDATORY: DI Direction + FVG Size >= 5 ticks')
    print('OPTIONAL (2/3): Displacement >= 1x | ADX >= 11 | EMA Trend')
    print()

    results = {}
    for symbol in ['ES', 'NQ', 'MES', 'MNQ']:
        baseline, hybrid = backtest_filter_modes(symbol, days=days)
        if baseline and hybrid:
            results[symbol] = {'baseline': baseline, 'hybrid': hybrid}

    print()
    print('='*90)
    print(f'{"Symbol":<8} {"Mode":<10} {"Trades":>7} {"Wins":>6} {"Win%":>7} {"P/L":>12} {"Max DD":>10} {"Loss Days":>10}')
    print('='*90)

    totals = {'baseline': {'trades': 0, 'wins': 0, 'pnl': 0, 'max_dd': 0},
              'hybrid': {'trades': 0, 'wins': 0, 'pnl': 0, 'max_dd': 0}}

    for symbol in ['ES', 'NQ', 'MES', 'MNQ']:
        if symbol in results:
            b = results[symbol]['baseline']
            h = results[symbol]['hybrid']

            b_wr = b['wins'] / b['trades'] * 100 if b['trades'] > 0 else 0
            h_wr = h['wins'] / h['trades'] * 100 if h['trades'] > 0 else 0

            print(f'{symbol:<8} {"Baseline":<10} {b["trades"]:>7} {b["wins"]:>6} {b_wr:>6.1f}% {b["pnl"]:>+11,.0f} {-b["max_dd"]:>+10,.0f} {b["losing_days"]:>10}')
            print(f'{"":<8} {"Hybrid":<10} {h["trades"]:>7} {h["wins"]:>6} {h_wr:>6.1f}% {h["pnl"]:>+11,.0f} {-h["max_dd"]:>+10,.0f} {h["losing_days"]:>10}')

            # Delta
            delta_trades = h['trades'] - b['trades']
            delta_pnl = h['pnl'] - b['pnl']
            delta_dd = h['max_dd'] - b['max_dd']
            print(f'{"":<8} {"Delta":<10} {delta_trades:>+7} {"":>6} {"":>7} {delta_pnl:>+11,.0f} {-delta_dd:>+10,.0f}')
            print('-'*90)

            totals['baseline']['trades'] += b['trades']
            totals['baseline']['wins'] += b['wins']
            totals['baseline']['pnl'] += b['pnl']
            totals['baseline']['max_dd'] += b['max_dd']
            totals['hybrid']['trades'] += h['trades']
            totals['hybrid']['wins'] += h['wins']
            totals['hybrid']['pnl'] += h['pnl']
            totals['hybrid']['max_dd'] += h['max_dd']

    # Print totals
    print()
    b_wr = totals['baseline']['wins'] / totals['baseline']['trades'] * 100 if totals['baseline']['trades'] > 0 else 0
    h_wr = totals['hybrid']['wins'] / totals['hybrid']['trades'] * 100 if totals['hybrid']['trades'] > 0 else 0
    print(f'{"TOTAL":<8} {"Baseline":<10} {totals["baseline"]["trades"]:>7} {totals["baseline"]["wins"]:>6} {b_wr:>6.1f}% {totals["baseline"]["pnl"]:>+11,.0f} {-totals["baseline"]["max_dd"]:>+10,.0f}')
    print(f'{"":<8} {"Hybrid":<10} {totals["hybrid"]["trades"]:>7} {totals["hybrid"]["wins"]:>6} {h_wr:>6.1f}% {totals["hybrid"]["pnl"]:>+11,.0f} {-totals["hybrid"]["max_dd"]:>+10,.0f}')
    delta_pnl = totals['hybrid']['pnl'] - totals['baseline']['pnl']
    delta_trades = totals['hybrid']['trades'] - totals['baseline']['trades']
    print(f'{"":<8} {"Delta":<10} {delta_trades:>+7} {"":>6} {"":>7} {delta_pnl:>+11,.0f}')
    print('='*90)
