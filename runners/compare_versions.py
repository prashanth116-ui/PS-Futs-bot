"""
Strategy Version Comparison - V10 through V10.5

Compares all strategy versions across 30 days to show:
- Performance differences
- Downsides of each version
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_equity import run_session_v10_equity
from runners.run_v10_dual_entry import run_session_v10


def run_equity_backtest(bars, symbol, days, version_params):
    """Run equity backtest with specific version parameters."""
    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:] if len(all_dates) >= days else all_dates

    results = {
        'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0,
        'stopped_out': 0, 'max_drawdown': 0, 'peak': 0, 'running_pnl': 0
    }

    for target_date in recent_dates:
        day_bars = [b for b in bars if b.timestamp.date() == target_date]
        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        day_results = run_session_v10_equity(
            session_bars, bars, symbol=symbol,
            risk_per_trade=500,
            max_open_trades=2,
            t1_fixed_4r=True,
            overnight_retrace_min_adx=version_params.get('overnight_adx', 22),
            midday_cutoff=version_params.get('midday_cutoff', True),
            pm_cutoff_qqq=version_params.get('pm_cutoff_qqq', True),
            disable_intraday_spy=version_params.get('disable_intraday_spy', True),
            atr_buffer_multiplier=version_params.get('atr_buffer', 0.5),
            high_displacement_override=version_params.get('high_disp_override', 3.0),
        )

        for r in day_results:
            results['trades'] += 1
            results['pnl'] += r['total_dollars']
            results['running_pnl'] += r['total_dollars']

            if r['total_dollars'] > 0:
                results['wins'] += 1
            else:
                results['losses'] += 1

            if any(e['type'] == 'STOP' for e in r['exits']):
                results['stopped_out'] += 1

            # Track drawdown
            if results['running_pnl'] > results['peak']:
                results['peak'] = results['running_pnl']
            dd = results['peak'] - results['running_pnl']
            if dd > results['max_drawdown']:
                results['max_drawdown'] = dd

    return results


def run_futures_backtest(bars, symbol, days, version_params, tick_size, tick_value, contracts=3):
    """Run futures backtest with specific version parameters."""
    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:] if len(all_dates) >= days else all_dates

    min_risk = 1.5 if symbol in ['ES', 'MES'] else 6.0
    max_bos_risk = version_params.get('max_bos_risk', 8.0 if symbol in ['ES', 'MES'] else 20.0)

    results = {
        'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0,
        'stopped_out': 0, 'max_drawdown': 0, 'peak': 0, 'running_pnl': 0
    }

    for target_date in recent_dates:
        day_bars = [b for b in bars if b.timestamp.date() == target_date]
        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        day_results = run_session_v10(
            session_bars, bars,
            tick_size=tick_size,
            tick_value=tick_value,
            contracts=contracts,
            min_risk_pts=min_risk,
            enable_creation_entry=True,
            enable_retracement_entry=True,
            enable_bos_entry=True,
            retracement_morning_only=False,
            t1_fixed_4r=True,
            overnight_retrace_min_adx=version_params.get('overnight_adx', 22),
            midday_cutoff=version_params.get('midday_cutoff', True),
            pm_cutoff_nq=version_params.get('pm_cutoff_nq', True),
            max_bos_risk_pts=max_bos_risk if version_params.get('bos_risk_cap', True) else 999,
            high_displacement_override=version_params.get('high_disp_override', 3.0),
            symbol=symbol,
        )

        for r in day_results:
            results['trades'] += 1
            results['pnl'] += r['total_dollars']
            results['running_pnl'] += r['total_dollars']

            if r['total_dollars'] > 0:
                results['wins'] += 1
            else:
                results['losses'] += 1

            if 'STOP' in str(r.get('exits', [])):
                results['stopped_out'] += 1

            if results['running_pnl'] > results['peak']:
                results['peak'] = results['running_pnl']
            dd = results['peak'] - results['running_pnl']
            if dd > results['max_drawdown']:
                results['max_drawdown'] = dd

    return results


# Version configurations
VERSIONS = {
    'V10.0': {
        'overnight_adx': 17,      # No special ADX for overnight
        'midday_cutoff': False,   # No midday cutoff
        'pm_cutoff_nq': False,    # No PM cutoff
        'pm_cutoff_qqq': False,
        'bos_risk_cap': False,    # No BOS risk cap
        'disable_intraday_spy': False,
        'atr_buffer': 0,          # Fixed $0.02 buffer
        'high_disp_override': 0,  # No displacement override
    },
    'V10.1': {
        'overnight_adx': 22,      # ADX >= 22 for overnight
        'midday_cutoff': False,
        'pm_cutoff_nq': False,
        'pm_cutoff_qqq': False,
        'bos_risk_cap': False,
        'disable_intraday_spy': False,
        'atr_buffer': 0,
        'high_disp_override': 0,
    },
    'V10.2': {
        'overnight_adx': 22,
        'midday_cutoff': True,    # Midday cutoff 12-14
        'pm_cutoff_nq': True,     # NQ PM cutoff
        'pm_cutoff_qqq': True,    # QQQ PM cutoff
        'bos_risk_cap': False,
        'disable_intraday_spy': False,
        'atr_buffer': 0,
        'high_disp_override': 0,
    },
    'V10.3': {
        'overnight_adx': 22,
        'midday_cutoff': True,
        'pm_cutoff_nq': True,
        'pm_cutoff_qqq': True,
        'bos_risk_cap': True,     # BOS risk cap
        'disable_intraday_spy': True,  # Disable SPY INTRADAY
        'atr_buffer': 0,
        'high_disp_override': 0,
    },
    'V10.4': {
        'overnight_adx': 22,
        'midday_cutoff': True,
        'pm_cutoff_nq': True,
        'pm_cutoff_qqq': True,
        'bos_risk_cap': True,
        'disable_intraday_spy': True,
        'atr_buffer': 0.5,        # ATR buffer for equities
        'high_disp_override': 0,
    },
    'V10.5': {
        'overnight_adx': 22,
        'midday_cutoff': True,
        'pm_cutoff_nq': True,
        'pm_cutoff_qqq': True,
        'bos_risk_cap': True,
        'disable_intraday_spy': True,
        'atr_buffer': 0.5,
        'high_disp_override': 3.0,  # High displacement override
    },
}


def main():
    days = 30

    print("=" * 90)
    print("STRATEGY VERSION COMPARISON - 30 DAY BACKTEST")
    print("=" * 90)

    # Fetch all data first
    print("\nFetching data...")
    spy_bars = fetch_futures_bars('SPY', interval='3m', n_bars=15000)
    qqq_bars = fetch_futures_bars('QQQ', interval='3m', n_bars=15000)
    es_bars = fetch_futures_bars('ES', interval='3m', n_bars=15000)
    nq_bars = fetch_futures_bars('NQ', interval='3m', n_bars=15000)

    all_results = {}

    for version, params in VERSIONS.items():
        print(f"\nRunning {version}...")
        all_results[version] = {}

        # Equities
        if spy_bars:
            all_results[version]['SPY'] = run_equity_backtest(spy_bars, 'SPY', days, params)
        if qqq_bars:
            all_results[version]['QQQ'] = run_equity_backtest(qqq_bars, 'QQQ', days, params)

        # Futures
        if es_bars:
            all_results[version]['ES'] = run_futures_backtest(es_bars, 'ES', days, params, 0.25, 12.50)
        if nq_bars:
            all_results[version]['NQ'] = run_futures_backtest(nq_bars, 'NQ', days, params, 0.25, 5.00)

    # Print comparison tables
    print("\n" + "=" * 90)
    print("RESULTS BY VERSION")
    print("=" * 90)

    # Summary table
    print(f"\n{'Version':<8} {'Trades':>8} {'Wins':>6} {'Losses':>7} {'Win%':>7} {'P/L':>14} {'Max DD':>12}")
    print("-" * 70)

    for version in VERSIONS.keys():
        total_trades = sum(all_results[version][s]['trades'] for s in all_results[version])
        total_wins = sum(all_results[version][s]['wins'] for s in all_results[version])
        total_losses = sum(all_results[version][s]['losses'] for s in all_results[version])
        total_pnl = sum(all_results[version][s]['pnl'] for s in all_results[version])
        max_dd = max(all_results[version][s]['max_drawdown'] for s in all_results[version])

        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

        print(f"{version:<8} {total_trades:>8} {total_wins:>6} {total_losses:>7} {win_rate:>6.1f}% ${total_pnl:>12,.0f} ${max_dd:>10,.0f}")

    # Detailed by symbol
    for symbol in ['ES', 'NQ', 'SPY', 'QQQ']:
        print(f"\n{'=' * 70}")
        print(f"{symbol} COMPARISON")
        print(f"{'=' * 70}")
        print(f"{'Version':<8} {'Trades':>8} {'Wins':>6} {'Win%':>7} {'Stops':>7} {'P/L':>14} {'Max DD':>12}")
        print("-" * 70)

        for version in VERSIONS.keys():
            if symbol in all_results[version]:
                r = all_results[version][symbol]
                win_rate = (r['wins'] / r['trades'] * 100) if r['trades'] > 0 else 0
                print(f"{version:<8} {r['trades']:>8} {r['wins']:>6} {win_rate:>6.1f}% {r['stopped_out']:>7} ${r['pnl']:>12,.0f} ${r['max_drawdown']:>10,.0f}")

    # Version changelog with downsides
    print("\n" + "=" * 90)
    print("VERSION CHANGES & DOWNSIDES")
    print("=" * 90)

    changes = {
        'V10.0': {
            'added': 'Base quad entry (Creation, Overnight, Intraday, BOS)',
            'downside': 'Takes trades during lunch lull, no ADX filter for overnight, oversized BOS entries'
        },
        'V10.1': {
            'added': 'ADX >= 22 for overnight retrace entries',
            'downside': 'Misses some valid overnight setups in mild trends'
        },
        'V10.2': {
            'added': 'Midday cutoff (12-14), NQ/QQQ PM cutoff after 14:00',
            'downside': 'Misses afternoon breakout trades, fewer total setups'
        },
        'V10.3': {
            'added': 'BOS risk cap (ES:8, NQ:20 pts), Disable SPY INTRADAY',
            'downside': 'Skips large BOS setups that could be winners, fewer SPY trades'
        },
        'V10.4': {
            'added': 'ATR buffer for equities (ATR × 0.5 vs $0.02)',
            'downside': 'Wider stops = larger risk per trade = fewer shares, lower win rate'
        },
        'V10.5': {
            'added': 'High displacement override (3x body skips ADX >= 17, needs >= 10)',
            'downside': 'May take trades in choppy markets with one big candle'
        },
    }

    for version, info in changes.items():
        v_pnl = sum(all_results[version][s]['pnl'] for s in all_results[version])
        print(f"\n{version}: ${v_pnl:+,.0f}")
        print(f"  Added: {info['added']}")
        print(f"  Downside: {info['downside']}")

    # Incremental improvement
    print("\n" + "=" * 90)
    print("INCREMENTAL IMPROVEMENT")
    print("=" * 90)

    versions_list = list(VERSIONS.keys())
    for i in range(1, len(versions_list)):
        curr = versions_list[i]
        prev = versions_list[i-1]
        curr_pnl = sum(all_results[curr][s]['pnl'] for s in all_results[curr])
        prev_pnl = sum(all_results[prev][s]['pnl'] for s in all_results[prev])
        diff = curr_pnl - prev_pnl
        print(f"{prev} -> {curr}: ${diff:+,.0f}")


if __name__ == "__main__":
    main()
