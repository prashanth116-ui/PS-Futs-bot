"""
Compare BOS disable options:
- V10.5: All BOS enabled
- V10.6a: Only BOS_RETRACE disabled (keep regular BOS)
- V10.6b: All BOS disabled
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10
from runners.run_v10_equity import run_session_v10_equity

days = 30


def run_futures(bars, symbol, tick_size, tick_value, disable_bos, filter_bos_retrace_only=False):
    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:]
    min_risk = 1.5 if symbol in ['ES', 'MES'] else 6.0
    max_bos = 8.0 if symbol in ['ES', 'MES'] else 20.0

    results = {'trades': 0, 'wins': 0, 'pnl': 0, 'max_dd': 0, 'peak': 0, 'running': 0}
    for d in recent_dates:
        day_bars = [b for b in bars if b.timestamp.date() == d]
        session = [b for b in day_bars if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]
        if len(session) < 50:
            continue
        trades = run_session_v10(session, bars, tick_size=tick_size, tick_value=tick_value,
                                  contracts=3, min_risk_pts=min_risk, t1_fixed_4r=True,
                                  overnight_retrace_min_adx=22, midday_cutoff=True,
                                  pm_cutoff_nq=True, max_bos_risk_pts=max_bos,
                                  high_displacement_override=3.0, disable_bos_retrace=disable_bos,
                                  symbol=symbol)

        for t in trades:
            # If filter_bos_retrace_only, skip only BOS_RETRACE (keep BOS)
            if filter_bos_retrace_only and t.get('entry_type') == 'BOS_RETRACE':
                continue

            results['trades'] += 1
            results['pnl'] += t['total_dollars']
            results['running'] += t['total_dollars']
            if t['total_dollars'] > 0:
                results['wins'] += 1
            if results['running'] > results['peak']:
                results['peak'] = results['running']
            dd = results['peak'] - results['running']
            if dd > results['max_dd']:
                results['max_dd'] = dd
    return results


def run_equity(bars, symbol, disable_bos, filter_bos_retrace_only=False):
    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:]

    results = {'trades': 0, 'wins': 0, 'pnl': 0, 'max_dd': 0, 'peak': 0, 'running': 0}
    for d in recent_dates:
        day_bars = [b for b in bars if b.timestamp.date() == d]
        session = [b for b in day_bars if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]
        if len(session) < 50:
            continue
        trades = run_session_v10_equity(session, bars, symbol=symbol, risk_per_trade=500,
                                         t1_fixed_4r=True, overnight_retrace_min_adx=22,
                                         midday_cutoff=True, pm_cutoff_qqq=True,
                                         disable_intraday_spy=True, atr_buffer_multiplier=0.5,
                                         high_displacement_override=3.0,
                                         disable_bos_retrace=disable_bos)

        for t in trades:
            # Note: Equity uses 'BOS' not 'BOS_RETRACE', so filter won't affect it
            if filter_bos_retrace_only and t.get('entry_type') == 'BOS_RETRACE':
                continue

            results['trades'] += 1
            results['pnl'] += t['total_dollars']
            results['running'] += t['total_dollars']
            if t['total_dollars'] > 0:
                results['wins'] += 1
            if results['running'] > results['peak']:
                results['peak'] = results['running']
            dd = results['peak'] - results['running']
            if dd > results['max_dd']:
                results['max_dd'] = dd
    return results


def main():
    print('Fetching data...')
    es_bars = fetch_futures_bars('ES', interval='3m', n_bars=15000)
    nq_bars = fetch_futures_bars('NQ', interval='3m', n_bars=15000)
    spy_bars = fetch_futures_bars('SPY', interval='3m', n_bars=15000)
    qqq_bars = fetch_futures_bars('QQQ', interval='3m', n_bars=15000)

    print('\nRunning 3-way comparison...')
    print('  - V10.5: All BOS enabled')
    print('  - V10.6a: Only BOS_RETRACE disabled (keep BOS)')
    print('  - V10.6b: All BOS disabled')

    # V10.5 (all BOS enabled)
    v105 = {}
    v105['ES'] = run_futures(es_bars, 'ES', 0.25, 12.50, False, False)
    v105['NQ'] = run_futures(nq_bars, 'NQ', 0.25, 5.00, False, False)
    v105['SPY'] = run_equity(spy_bars, 'SPY', False, False)
    v105['QQQ'] = run_equity(qqq_bars, 'QQQ', False, False)

    # V10.6a (only BOS_RETRACE disabled via post-filter, keep BOS)
    v106a = {}
    v106a['ES'] = run_futures(es_bars, 'ES', 0.25, 12.50, False, True)
    v106a['NQ'] = run_futures(nq_bars, 'NQ', 0.25, 5.00, False, True)
    v106a['SPY'] = run_equity(spy_bars, 'SPY', False, True)
    v106a['QQQ'] = run_equity(qqq_bars, 'QQQ', False, True)

    # V10.6b (all BOS disabled)
    v106b = {}
    v106b['ES'] = run_futures(es_bars, 'ES', 0.25, 12.50, True, False)
    v106b['NQ'] = run_futures(nq_bars, 'NQ', 0.25, 5.00, True, False)
    v106b['SPY'] = run_equity(spy_bars, 'SPY', True, False)
    v106b['QQQ'] = run_equity(qqq_bars, 'QQQ', True, False)

    def calc_totals(v):
        return {
            'trades': sum(v[s]['trades'] for s in v),
            'wins': sum(v[s]['wins'] for s in v),
            'pnl': sum(v[s]['pnl'] for s in v),
            'max_dd': max(v[s]['max_dd'] for s in v)
        }

    t105 = calc_totals(v105)
    t106a = calc_totals(v106a)
    t106b = calc_totals(v106b)

    print('\n' + '=' * 80)
    print('COMPARISON: V10.5 vs V10.6a (BOS_RETRACE only) vs V10.6b (All BOS)')
    print('=' * 80)

    print(f"\n{'Version':<25} {'Trades':>8} {'Wins':>6} {'Win%':>7} {'P/L':>14} {'Max DD':>12}")
    print('-' * 75)
    wr105 = t105['wins'] / t105['trades'] * 100 if t105['trades'] else 0
    wr106a = t106a['wins'] / t106a['trades'] * 100 if t106a['trades'] else 0
    wr106b = t106b['wins'] / t106b['trades'] * 100 if t106b['trades'] else 0

    print(f"{'V10.5 (All BOS on)':<25} {t105['trades']:>8} {t105['wins']:>6} {wr105:>6.1f}% ${t105['pnl']:>12,.0f} ${t105['max_dd']:>10,.0f}")
    print(f"{'V10.6a (BOS_RETRACE off)':<25} {t106a['trades']:>8} {t106a['wins']:>6} {wr106a:>6.1f}% ${t106a['pnl']:>12,.0f} ${t106a['max_dd']:>10,.0f}")
    print(f"{'V10.6b (All BOS off)':<25} {t106b['trades']:>8} {t106b['wins']:>6} {wr106b:>6.1f}% ${t106b['pnl']:>12,.0f} ${t106b['max_dd']:>10,.0f}")

    print('\n' + '-' * 75)
    print('CHANGE FROM V10.5')
    print('-' * 75)
    diff_a = t106a['pnl'] - t105['pnl']
    diff_b = t106b['pnl'] - t105['pnl']
    dd_a = t106a['max_dd'] - t105['max_dd']
    dd_b = t106b['max_dd'] - t105['max_dd']

    print(f"{'V10.6a (BOS_RETRACE off)':<25} {t106a['trades']-t105['trades']:>+8} {t106a['wins']-t105['wins']:>+6} {wr106a-wr105:>+6.1f}% ${diff_a:>+12,.0f} ${dd_a:>+10,.0f}")
    print(f"{'V10.6b (All BOS off)':<25} {t106b['trades']-t105['trades']:>+8} {t106b['wins']-t105['wins']:>+6} {wr106b-wr105:>+6.1f}% ${diff_b:>+12,.0f} ${dd_b:>+10,.0f}")

    print('\n' + '=' * 80)
    print('BY SYMBOL')
    print('=' * 80)

    for symbol in ['ES', 'NQ', 'SPY', 'QQQ']:
        print(f'\n{symbol}:')
        for label, v in [('V10.5', v105), ('V10.6a', v106a), ('V10.6b', v106b)]:
            r = v[symbol]
            wr = r['wins'] / r['trades'] * 100 if r['trades'] else 0
            print(f"  {label}: {r['trades']:>3} trades, {r['wins']:>3} wins ({wr:>5.1f}%), P/L: ${r['pnl']:>10,.0f}, DD: ${r['max_dd']:>8,.0f}")

    print('\n' + '=' * 80)
    print('RECOMMENDATION')
    print('=' * 80)

    best = max([(t105['pnl'], 'V10.5 (Keep all BOS)'),
                (t106a['pnl'], 'V10.6a (Only BOS_RETRACE disabled)'),
                (t106b['pnl'], 'V10.6b (All BOS disabled)')],
               key=lambda x: x[0])

    print(f'\n>>> {best[1]} is BEST with ${best[0]:,.0f} P/L')

    if best[1] == 'V10.5 (Keep all BOS)':
        print('    Recommendation: Revert to V10.5 - keep all BOS entries')
    elif best[1] == 'V10.6a (Only BOS_RETRACE disabled)':
        print('    Recommendation: Update V10.6 to only disable BOS_RETRACE')
    else:
        print('    Recommendation: Keep current V10.6b - all BOS disabled')


if __name__ == '__main__':
    main()
