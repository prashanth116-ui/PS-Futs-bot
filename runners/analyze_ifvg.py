"""
IFVG Recovery Analysis

Analyzes how often stopped-out FVG entries reverse and reach T1,
to determine if Inverse FVG (IFVG) re-entries would be profitable.

For each entry:
1. Did price hit T1 (win) or close through FVG (loss)?
2. For losses: did price move away, come back to inverted FVG zone, then reach T1?
3. Calculate recovery rate and potential P/L.

Usage:
    python -m runners.analyze_ifvg
"""
import sys
sys.path.insert(0, '.')

from datetime import timedelta, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict_sweep.strategy import ICTSweepStrategy, TradeSetup, SetupState
from strategies.ict_sweep.filters.displacement import calculate_avg_body
from runners.scan_ict_sweep import SYMBOL_CONFIGS, EQUITY_SYMBOLS


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
        'use_trend_filter': False, 'stop_buffer_pts': 0.10,
        't1_r': 3, 'trail_r': 6, 'debug': False,
    }


def analyze_ifvg_potential(symbol):
    """
    For each entry:
    1. Track if it wins or loses (price closes through FVG = stop)
    2. For losses: check if price later comes back through the inverted FVG zone
       AND then continues to where T1 would have been
    3. Calculate potential recovery
    """
    cfg = SYMBOL_CONFIGS[symbol]
    tick_size = cfg['tick_size']
    config = make_config(symbol)

    print(f'  Fetching {symbol}...', flush=True)
    bars_5m = fetch_futures_bars(symbol, interval='5m', n_bars=500)
    bars_15m = fetch_futures_bars(symbol, interval='15m', n_bars=500)

    if not bars_5m or not bars_15m:
        return None

    dates = sorted(set(b.timestamp.date() for b in bars_15m))

    results = {
        'symbol': symbol,
        'total_entries': 0,
        'wins': 0,
        'losses': 0,
        'loss_then_reverse': 0,
        'loss_no_reverse': 0,
        'potential_recovery_trades': [],
    }

    is_equity = symbol in EQUITY_SYMBOLS
    session_start = dt_time(9, 30) if is_equity else dt_time(8, 0)
    session_end = dt_time(16, 0)

    for day in dates:
        day_15m = [b for b in bars_15m if b.timestamp.date() == day
                   and session_start <= b.timestamp.time() <= session_end]
        day_5m = [b for b in bars_5m if b.timestamp.date() == day
                  and session_start <= b.timestamp.time() <= session_end]

        if len(day_15m) < 10 or len(day_5m) < 20:
            continue

        # Init strategy
        strategy = ICTSweepStrategy(config)
        lookback = [b for b in bars_15m if b.timestamp.date() < day][-50:]
        for b in lookback:
            strategy.htf_bars.append(b)
        lookback_5m = [b for b in bars_5m if b.timestamp.date() < day][-100:]
        for b in lookback_5m:
            strategy.mtf_bars.append(b)
        if strategy.htf_bars:
            strategy.avg_body = calculate_avg_body(
                strategy.htf_bars, strategy.avg_body_lookback)

        strategy.daily_trades = 0
        strategy.daily_losses = 0
        strategy.pending_sweeps.clear()
        strategy.pending_setups.clear()

        # Collect entries for this day
        day_entries = []
        mtf_cursor = 0

        for bar in day_15m:
            while mtf_cursor < len(day_5m) and day_5m[mtf_cursor].timestamp <= bar.timestamp:
                strategy.update_mtf(day_5m[mtf_cursor])
                mtf_cursor += 1
            strategy.update_htf(bar)
            result = strategy.check_htf_mitigation(bar)
            if isinstance(result, TradeSetup):
                day_entries.append((bar, result))

        # Analyze each entry using 5m bars
        for entry_bar, trade in day_entries:
            results['total_entries'] += 1
            is_long = trade.direction in ('LONG', 'BULLISH')
            fvg = trade.fvg
            entry = trade.entry_price
            stop = trade.stop_price
            risk = abs(entry - stop)
            t1 = trade.t1_price

            # FVG boundary for close-based stop
            fvg_stop_level = fvg.top if trade.direction == 'BEARISH' else fvg.bottom

            # Find entry bar in 5m data
            entry_idx = None
            for i, b in enumerate(day_5m):
                if b.timestamp >= entry_bar.timestamp:
                    entry_idx = i
                    break
            if entry_idx is None:
                continue

            remaining = day_5m[entry_idx + 1:]
            if not remaining:
                continue

            # Phase 1: did it hit T1 first or stop first?
            hit_t1 = False
            hit_stop = False
            stop_bar_idx = None

            for i, bar in enumerate(remaining):
                if is_long:
                    if bar.high >= t1:
                        hit_t1 = True
                        break
                    if bar.close < fvg_stop_level:
                        hit_stop = True
                        stop_bar_idx = entry_idx + 1 + i
                        break
                else:
                    if bar.low <= t1:
                        hit_t1 = True
                        break
                    if bar.close > fvg_stop_level:
                        hit_stop = True
                        stop_bar_idx = entry_idx + 1 + i
                        break

            if hit_t1:
                results['wins'] += 1
            elif hit_stop:
                results['losses'] += 1

                # Phase 2: IFVG analysis after stop-out
                # After stop, check if price:
                #   a) Moves away from FVG (confirms inversion)
                #   b) Comes back to FVG zone (IFVG retest)
                #   c) Then reaches original T1

                post_stop = day_5m[stop_bar_idx + 1:]

                moved_away = False
                retested_ifvg = False
                ifvg_retest_price = None
                reached_t1 = False

                for bar in post_stop:
                    if not moved_away:
                        # Price should move away from FVG first (at least 0.5R)
                        if is_long and bar.low < fvg.bottom - risk * 0.5:
                            moved_away = True
                        elif not is_long and bar.high > fvg.top + risk * 0.5:
                            moved_away = True
                    elif not retested_ifvg:
                        # Price comes back to inverted FVG zone
                        if is_long:
                            if bar.low <= fvg.top and bar.close > fvg.bottom:
                                retested_ifvg = True
                                ifvg_retest_price = bar.close
                        else:
                            if bar.high >= fvg.bottom and bar.close < fvg.top:
                                retested_ifvg = True
                                ifvg_retest_price = bar.close
                    else:
                        # Check if price reached original T1
                        if is_long and bar.high >= t1:
                            reached_t1 = True
                            break
                        elif not is_long and bar.low <= t1:
                            reached_t1 = True
                            break

                if retested_ifvg and reached_t1:
                    results['loss_then_reverse'] += 1
                    recovery_r = (
                        abs(t1 - ifvg_retest_price) / risk if risk > 0 else 0)
                    results['potential_recovery_trades'].append({
                        'date': day,
                        'time': entry_bar.timestamp.strftime('%H:%M'),
                        'direction': trade.direction,
                        'entry': entry,
                        'fvg': f'{fvg.bottom:.2f}-{fvg.top:.2f}',
                        'ifvg_retest': ifvg_retest_price,
                        't1': t1,
                        'recovery_r': recovery_r,
                    })
                else:
                    results['loss_no_reverse'] += 1
            # else: neither T1 nor stop (EOD exit) — skip

    return results


def main():
    symbols = [
        'ES', 'NQ',
        'NVDA', 'TSLA', 'AAPL', 'META', 'AMD',
        'PLTR', 'COIN', 'UNH', 'GOOGL', 'MSFT', 'AMZN',
    ]

    print('=' * 100)
    print('IFVG RECOVERY ANALYSIS')
    print('How often do stopped-out FVG entries later reverse and reach T1?')
    print('=' * 100)
    print()

    all_results = []
    for sym in symbols:
        r = analyze_ifvg_potential(sym)
        if r:
            all_results.append(r)

    # Summary table
    print()
    print('=' * 105)
    header = (f'{"Symbol":<7} {"Entries":>8} {"Wins":>6} {"Losses":>7} '
              f'{"Win%":>6} | {"Reverse":>8} {"No Rev":>7} {"Rev%":>6} | '
              f'{"Verdict":>10}')
    print(header)
    print('-' * 105)

    total_entries = 0
    total_wins = 0
    total_losses = 0
    total_reverse = 0
    total_no_reverse = 0

    for r in all_results:
        total_entries += r['total_entries']
        total_wins += r['wins']
        total_losses += r['losses']
        total_reverse += r['loss_then_reverse']
        total_no_reverse += r['loss_no_reverse']

        wr = (r['wins'] / r['total_entries'] * 100
              ) if r['total_entries'] > 0 else 0
        rev_rate = (r['loss_then_reverse'] / r['losses'] * 100
                    ) if r['losses'] > 0 else 0

        if rev_rate >= 40:
            verdict = 'WORTH IT'
        elif rev_rate >= 25:
            verdict = 'MARGINAL'
        else:
            verdict = 'SKIP'

        print(f'{r["symbol"]:<7} {r["total_entries"]:>8} {r["wins"]:>6} '
              f'{r["losses"]:>7} {wr:>5.1f}% | {r["loss_then_reverse"]:>8} '
              f'{r["loss_no_reverse"]:>7} {rev_rate:>5.1f}% | {verdict:>10}')

    print('-' * 105)
    wr_total = (total_wins / total_entries * 100
                ) if total_entries > 0 else 0
    rev_total = (total_reverse / total_losses * 100
                 ) if total_losses > 0 else 0
    print(f'{"TOTAL":<7} {total_entries:>8} {total_wins:>6} {total_losses:>7} '
          f'{wr_total:>5.1f}% | {total_reverse:>8} {total_no_reverse:>7} '
          f'{rev_total:>5.1f}%')

    # Show recoverable trade details
    print()
    print('=' * 105)
    print('RECOVERABLE TRADES (stopped out -> IFVG retest -> reached T1)')
    print('=' * 105)
    recovery_count = 0
    for r in all_results:
        for t in r['potential_recovery_trades']:
            recovery_count += 1
            print(f'  {r["symbol"]:<6} {t["date"]} {t["time"]} | '
                  f'{t["direction"]:<8} | Entry={t["entry"]:.2f} -> Stopped | '
                  f'FVG={t["fvg"]} | IFVG retest={t["ifvg_retest"]:.2f} -> '
                  f'T1={t["t1"]:.2f} ({t["recovery_r"]:.1f}R)')

    print(f'\nTotal recoverable: {recovery_count} trades')
    print(f'Recovery rate: {rev_total:.1f}% of all losses')

    # Verdict
    print()
    print('=' * 105)
    print('VERDICT')
    print('=' * 105)
    if rev_total >= 30:
        print('  IFVG WORTH IMPLEMENTING')
        print(f'  {rev_total:.0f}% of losses are recoverable — enough to justify '
              'the added complexity.')
        print('  Recommendation: Add IFVG as a new entry type (re-entry after stop).')
    elif rev_total >= 20:
        print('  IFVG MARGINAL')
        print(f'  {rev_total:.0f}% recovery rate — borderline. May help specific '
              'symbols but not universally.')
        print('  Recommendation: Consider per-symbol IFVG enable (like BOS loss limit).')
    else:
        print('  IFVG NOT RECOMMENDED')
        print(f'  Only {rev_total:.0f}% of losses reverse through IFVG — too few '
              'to justify the complexity.')
        print('  Recommendation: Keep current strategy. Focus on other improvements.')


if __name__ == '__main__':
    main()
