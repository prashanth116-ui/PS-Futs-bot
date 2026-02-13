"""
Test BOS disable by symbol to find optimal combination.
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from itertools import product
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10
from runners.run_v10_equity import run_session_v10_equity

days = 30


def run_futures(bars, symbol, tick_size, tick_value, disable_bos):
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


def run_equity(bars, symbol, disable_bos):
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

    # Pre-compute results for each symbol with BOS on and off
    print('\nPre-computing results for each symbol...')

    results_cache = {}

    # ES
    print('  ES...')
    results_cache[('ES', False)] = run_futures(es_bars, 'ES', 0.25, 12.50, False)
    results_cache[('ES', True)] = run_futures(es_bars, 'ES', 0.25, 12.50, True)

    # NQ
    print('  NQ...')
    results_cache[('NQ', False)] = run_futures(nq_bars, 'NQ', 0.25, 5.00, False)
    results_cache[('NQ', True)] = run_futures(nq_bars, 'NQ', 0.25, 5.00, True)

    # SPY
    print('  SPY...')
    results_cache[('SPY', False)] = run_equity(spy_bars, 'SPY', False)
    results_cache[('SPY', True)] = run_equity(spy_bars, 'SPY', True)

    # QQQ
    print('  QQQ...')
    results_cache[('QQQ', False)] = run_equity(qqq_bars, 'QQQ', False)
    results_cache[('QQQ', True)] = run_equity(qqq_bars, 'QQQ', True)

    # Show individual symbol impact
    print('\n' + '=' * 70)
    print('INDIVIDUAL SYMBOL BOS IMPACT')
    print('=' * 70)

    print(f"\n{'Symbol':<8} {'BOS ON P/L':>14} {'BOS OFF P/L':>14} {'Change':>12} {'Recommend':>12}")
    print('-' * 65)

    for symbol in ['ES', 'NQ', 'SPY', 'QQQ']:
        on_pnl = results_cache[(symbol, False)]['pnl']
        off_pnl = results_cache[(symbol, True)]['pnl']
        diff = off_pnl - on_pnl
        recommend = 'OFF' if diff > 0 else 'ON'
        print(f"{symbol:<8} ${on_pnl:>12,.0f} ${off_pnl:>12,.0f} ${diff:>+10,.0f} {recommend:>12}")

    # Test all 16 combinations
    print('\n' + '=' * 70)
    print('ALL COMBINATIONS (BOS OFF = True, BOS ON = False)')
    print('=' * 70)

    combinations = []

    for es_off, nq_off, spy_off, qqq_off in product([False, True], repeat=4):
        total_pnl = (
            results_cache[('ES', es_off)]['pnl'] +
            results_cache[('NQ', nq_off)]['pnl'] +
            results_cache[('SPY', spy_off)]['pnl'] +
            results_cache[('QQQ', qqq_off)]['pnl']
        )
        total_trades = (
            results_cache[('ES', es_off)]['trades'] +
            results_cache[('NQ', nq_off)]['trades'] +
            results_cache[('SPY', spy_off)]['trades'] +
            results_cache[('QQQ', qqq_off)]['trades']
        )
        total_wins = (
            results_cache[('ES', es_off)]['wins'] +
            results_cache[('NQ', nq_off)]['wins'] +
            results_cache[('SPY', spy_off)]['wins'] +
            results_cache[('QQQ', qqq_off)]['wins']
        )
        max_dd = max(
            results_cache[('ES', es_off)]['max_dd'],
            results_cache[('NQ', nq_off)]['max_dd'],
            results_cache[('SPY', spy_off)]['max_dd'],
            results_cache[('QQQ', qqq_off)]['max_dd']
        )

        config = {
            'ES': 'OFF' if es_off else 'ON',
            'NQ': 'OFF' if nq_off else 'ON',
            'SPY': 'OFF' if spy_off else 'ON',
            'QQQ': 'OFF' if qqq_off else 'ON',
        }

        combinations.append({
            'config': config,
            'pnl': total_pnl,
            'trades': total_trades,
            'wins': total_wins,
            'max_dd': max_dd,
            'win_rate': total_wins / total_trades * 100 if total_trades else 0
        })

    # Sort by P/L descending
    combinations.sort(key=lambda x: x['pnl'], reverse=True)

    print(f"\n{'Rank':<5} {'ES':<5} {'NQ':<5} {'SPY':<5} {'QQQ':<5} {'Trades':>7} {'Win%':>7} {'P/L':>14} {'Max DD':>12}")
    print('-' * 75)

    for i, combo in enumerate(combinations[:10], 1):
        c = combo['config']
        print(f"{i:<5} {c['ES']:<5} {c['NQ']:<5} {c['SPY']:<5} {c['QQQ']:<5} {combo['trades']:>7} {combo['win_rate']:>6.1f}% ${combo['pnl']:>12,.0f} ${combo['max_dd']:>10,.0f}")

    # Show best vs baseline
    baseline = [c for c in combinations if all(v == 'ON' for v in c['config'].values())][0]
    best = combinations[0]

    print('\n' + '=' * 70)
    print('RECOMMENDATION')
    print('=' * 70)

    print(f"\nBaseline (all BOS ON): ${baseline['pnl']:,.0f}")
    print(f"Best combination:      ${best['pnl']:,.0f}")
    print(f"Improvement:           ${best['pnl'] - baseline['pnl']:+,.0f}")

    print(f"\nOptimal BOS settings:")
    for symbol, setting in best['config'].items():
        print(f"  {symbol}: BOS {setting}")

    print(f"\nStats:")
    print(f"  Trades:   {best['trades']} (vs {baseline['trades']} baseline)")
    print(f"  Win Rate: {best['win_rate']:.1f}% (vs {baseline['win_rate']:.1f}% baseline)")
    print(f"  Max DD:   ${best['max_dd']:,.0f} (vs ${baseline['max_dd']:,.0f} baseline)")


if __name__ == '__main__':
    main()
