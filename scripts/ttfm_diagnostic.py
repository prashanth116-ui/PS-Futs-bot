"""
TTFM Signal Funnel Diagnostic - Count signals at each filter stage.

Measures exactly where signals die in the pipeline to identify
the highest-impact changes for increasing trade frequency.

Usage:
    python -m scripts.ttfm_diagnostic ES 70
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_ttfm import SYMBOL_CONFIG, _build_daily_bars
from strategies.ttfm.signals.swing import find_swings
from strategies.ttfm.signals.bias import determine_bias
from strategies.ttfm.signals.cisd import detect_cisd
from strategies.ttfm.signals.candles import label_candles
from strategies.ttfm.filters.session import in_session


def run_diagnostic(symbol='ES', days=70):
    cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG['ES'])
    min_risk = cfg['min_risk']
    max_risk = cfg['max_risk']

    print(f'Fetching {symbol} data from TradingView...')
    bars_15m = fetch_futures_bars(symbol=symbol, interval='15m', n_bars=10000)
    bars_daily = fetch_futures_bars(symbol=symbol, interval='1d', n_bars=500)

    if not bars_15m or not bars_daily:
        print('Failed to fetch data')
        return

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)

    all_dates = sorted(set(b.timestamp.date() for b in bars_15m), reverse=True)
    trading_dates = []
    for d in all_dates:
        day_15m = [b for b in bars_15m if b.timestamp.date() == d
                   and premarket_start <= b.timestamp.time() <= rth_end]
        if len(day_15m) >= 20:
            trading_dates.append(d)
        if len(trading_dates) >= days:
            break
    trading_dates = sorted(trading_dates)

    # Counters
    total_swings = 0
    total_swings_l1r1 = 0  # looser swing detection
    total_c2 = 0
    total_c3 = 0
    total_c4 = 0
    total_c3_in_session = 0
    total_c3_killed_lunch = 0
    total_c3_bias_match = 0
    total_c3_bias_mismatch = 0
    total_c3_cisd_match = 0
    total_c3_cisd_miss = 0
    total_c3_risk_pass = 0
    total_c3_risk_too_big = 0
    total_c3_risk_too_small = 0
    total_c4_in_session = 0
    total_c4_bias_match = 0
    total_c4_cisd_match = 0
    total_c4_risk_pass = 0

    print(f'\nAnalyzing {len(trading_dates)} trading days...\n')

    for target_date in trading_dates:
        day_15m = [b for b in bars_15m if b.timestamp.date() == target_date
                   and premarket_start <= b.timestamp.time() <= rth_end]

        if len(day_15m) < 10:
            continue

        history_daily = [b for b in bars_daily if b.timestamp.date() < target_date]
        if len(history_daily) < 2:
            continue

        htf_bias = determine_bias(history_daily)

        # Standard swings (left=2, right=2)
        swings = find_swings(day_15m, left=2, right=2, timeframe="15m")
        total_swings += len(swings)

        # Looser swings (left=1, right=1)
        swings_l1r1 = find_swings(day_15m, left=1, right=1, timeframe="15m")
        total_swings_l1r1 += len(swings_l1r1)

        # Standard candle labels
        cisds = detect_cisd(day_15m, swings, lookback=10)
        labels = label_candles(day_15m, swings)

        # Looser candle labels
        cisds_l1r1 = detect_cisd(day_15m, swings_l1r1, lookback=10)
        labels_l1r1 = label_candles(day_15m, swings_l1r1)

        cisd_by_idx = {}
        for c in cisds:
            cisd_by_idx[c.bar_index] = c

        for lbl in labels:
            if lbl.label == "C2":
                total_c2 += 1
            elif lbl.label == "C3":
                total_c3 += 1
                bar = day_15m[lbl.bar_index] if lbl.bar_index < len(day_15m) else None
                if bar is None:
                    continue

                # Session filter
                if in_session(bar.timestamp):
                    total_c3_in_session += 1
                else:
                    # Check if killed by lunch specifically
                    t = bar.timestamp.time()
                    if dt_time(12, 0) <= t < dt_time(14, 0):
                        total_c3_killed_lunch += 1
                    continue

                # Bias filter
                if htf_bias.direction != "NEUTRAL" and lbl.direction == htf_bias.direction:
                    total_c3_bias_match += 1
                else:
                    total_c3_bias_mismatch += 1
                    continue

                # CISD filter
                found_cisd = False
                for ci in range(max(0, lbl.bar_index - 5), lbl.bar_index + 1):
                    if ci in cisd_by_idx and cisd_by_idx[ci].direction == lbl.direction:
                        found_cisd = True
                        break
                if found_cisd:
                    total_c3_cisd_match += 1
                else:
                    total_c3_cisd_miss += 1
                    continue

                # Risk filter
                if lbl.direction == "BULLISH":
                    entry_price = bar.close
                    c2_price = lbl.swing_point.price if lbl.swing_point else bar.low
                    risk = entry_price - (c2_price - 0.5)
                else:
                    entry_price = bar.close
                    c2_price = lbl.swing_point.price if lbl.swing_point else bar.high
                    risk = (c2_price + 0.5) - entry_price

                if risk <= 0:
                    total_c3_risk_too_small += 1
                elif risk < min_risk:
                    total_c3_risk_too_small += 1
                elif risk > max_risk:
                    total_c3_risk_too_big += 1
                else:
                    total_c3_risk_pass += 1

            elif lbl.label == "C4":
                total_c4 += 1
                bar = day_15m[lbl.bar_index] if lbl.bar_index < len(day_15m) else None
                if bar and in_session(bar.timestamp):
                    total_c4_in_session += 1
                    if htf_bias.direction != "NEUTRAL" and lbl.direction == htf_bias.direction:
                        total_c4_bias_match += 1
                        # Check CISD for C4 too
                        found = False
                        for ci in range(max(0, lbl.bar_index - 8), lbl.bar_index + 1):
                            if ci in cisd_by_idx and cisd_by_idx[ci].direction == lbl.direction:
                                found = True
                                break
                        if found:
                            total_c4_cisd_match += 1
                            # Risk check
                            if lbl.direction == "BULLISH":
                                entry_price = bar.close
                                c2_price = lbl.swing_point.price if lbl.swing_point else bar.low
                                risk = entry_price - (c2_price - 0.5)
                            else:
                                entry_price = bar.close
                                c2_price = lbl.swing_point.price if lbl.swing_point else bar.high
                                risk = (c2_price + 0.5) - entry_price
                            if 0 < risk and min_risk <= risk <= max_risk:
                                total_c4_risk_pass += 1

    # Print results
    print('=' * 70)
    print(f'{symbol} TTFM SIGNAL FUNNEL - {len(trading_dates)} Days')
    print('=' * 70)

    print(f'\n-- Swing Detection --')
    print(f'  Swings (left=2, right=2):  {total_swings:>5}  ({total_swings/len(trading_dates):.1f}/day)')
    print(f'  Swings (left=1, right=1):  {total_swings_l1r1:>5}  ({total_swings_l1r1/len(trading_dates):.1f}/day)  [+{total_swings_l1r1 - total_swings} more]')

    print(f'\n-- Candle Labels (standard swings) --')
    print(f'  C2 (swing points):         {total_c2:>5}  ({total_c2/len(trading_dates):.1f}/day)')
    print(f'  C3 (continuation):         {total_c3:>5}  ({total_c3/len(trading_dates):.1f}/day)')
    print(f'  C4 (expansion):            {total_c4:>5}  ({total_c4/len(trading_dates):.1f}/day)')

    print(f'\n-- C3 Filter Funnel --')
    print(f'  C3 total:                  {total_c3:>5}')
    print(f'  -> In session:             {total_c3_in_session:>5}  (killed by lunch: {total_c3_killed_lunch})')
    print(f'  -> Bias match:             {total_c3_bias_match:>5}  (mismatch: {total_c3_bias_mismatch})')
    print(f'  -> CISD confirmed:         {total_c3_cisd_match:>5}  (no CISD: {total_c3_cisd_miss})')
    print(f'  -> Risk in range:          {total_c3_risk_pass:>5}  (too big: {total_c3_risk_too_big}, too small: {total_c3_risk_too_small})')

    print(f'\n-- C4 Opportunity (if C4 entries were enabled) --')
    print(f'  C4 total:                  {total_c4:>5}')
    print(f'  -> In session:             {total_c4_in_session:>5}')
    print(f'  -> Bias match:             {total_c4_bias_match:>5}')
    print(f'  -> CISD confirmed:         {total_c4_cisd_match:>5}')
    print(f'  -> Risk in range:          {total_c4_risk_pass:>5}')

    # Impact estimates
    print(f'\n-- Estimated Frequency Impact --')
    print(f'  Current trades (C3 only):        ~{total_c3_risk_pass}')
    print(f'  +C4 entries:                     +{total_c4_risk_pass} -> ~{total_c3_risk_pass + total_c4_risk_pass}')
    c3_lunch_recovered = total_c3_killed_lunch  # rough upper bound
    print(f'  +Open lunch window:              +~{total_c3_killed_lunch} C3s to test')
    swing_ratio = total_swings_l1r1 / total_swings if total_swings > 0 else 1
    print(f'  +Looser swings (l1/r1):          ~{swing_ratio:.1f}x more swings -> ~{swing_ratio:.1f}x more C3/C4')
    if total_c3_cisd_match > 0:
        cisd_kill_rate = total_c3_cisd_miss / (total_c3_cisd_match + total_c3_cisd_miss) * 100
    else:
        cisd_kill_rate = 0
    print(f'  CISD kill rate:                  {cisd_kill_rate:.0f}% of bias-matched C3s blocked')
    print(f'  +Drop CISD (C3+Bias only):       ~{total_c3_bias_match} signals (vs {total_c3_cisd_match} with CISD)')

    print('=' * 70)


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 70
    run_diagnostic(symbol, days)
