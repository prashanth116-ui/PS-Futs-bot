"""
V10.6 Refinement Comparison

V10.6 Changes:
1. Disable BOS_RETRACE entry type (25% win rate drag)
2. Reduced sizing 10:00-12:00 (50% position)
3. Consecutive loss cooldown (skip after 3 losses)
4. Tighten RETRACEMENT to morning only (before 10:00)
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_equity import run_session_v10_equity
from runners.run_v10_dual_entry import run_session_v10


def run_futures_backtest_v106(bars, symbol, days, tick_size, tick_value, contracts=3,
                               disable_bos_retrace=False,
                               reduced_sizing_window=False,
                               consecutive_loss_cooldown=0,
                               retracement_cutoff_hour=12):
    """Run futures backtest with V10.6 refinements."""
    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:] if len(all_dates) >= days else all_dates

    min_risk = 1.5 if symbol in ['ES', 'MES'] else 6.0
    max_bos_risk = 8.0 if symbol in ['ES', 'MES'] else 20.0

    results = {
        'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0,
        'stopped_out': 0, 'max_drawdown': 0, 'peak': 0, 'running_pnl': 0,
        'skipped_cooldown': 0, 'reduced_sizing_trades': 0
    }

    consecutive_losses = 0

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
            overnight_retrace_min_adx=22,
            midday_cutoff=True,
            pm_cutoff_nq=True,
            max_bos_risk_pts=max_bos_risk,
            high_displacement_override=3.0,
            symbol=symbol,
        )

        for r in day_results:
            entry_type = r.get('entry_type', '')
            entry_time = r.get('entry_time', dt_time(9, 30))
            entry_hour = entry_time.hour if hasattr(entry_time, 'hour') else entry_time.time().hour

            # V10.6 Filter 1: Disable BOS_RETRACE
            if disable_bos_retrace and entry_type == 'BOS_RETRACE':
                continue

            # V10.6 Filter 4: Tighten RETRACEMENT to before cutoff hour
            if entry_type == 'RETRACEMENT' and entry_hour >= retracement_cutoff_hour:
                continue

            # V10.6 Filter 3: Consecutive loss cooldown
            if consecutive_loss_cooldown > 0 and consecutive_losses >= consecutive_loss_cooldown:
                results['skipped_cooldown'] += 1
                # Reset cooldown after skipping one trade
                consecutive_losses = 0
                continue

            # V10.6 Filter 2: Reduced sizing during 10:00-12:00
            sizing_multiplier = 1.0
            if reduced_sizing_window and 10 <= entry_hour < 12:
                sizing_multiplier = 0.5
                results['reduced_sizing_trades'] += 1

            # Calculate P/L with sizing adjustment
            trade_pnl = r['total_dollars'] * sizing_multiplier

            results['trades'] += 1
            results['pnl'] += trade_pnl
            results['running_pnl'] += trade_pnl

            if trade_pnl > 0:
                results['wins'] += 1
                consecutive_losses = 0
            else:
                results['losses'] += 1
                consecutive_losses += 1

            if 'STOP' in str(r.get('exits', [])):
                results['stopped_out'] += 1

            if results['running_pnl'] > results['peak']:
                results['peak'] = results['running_pnl']
            dd = results['peak'] - results['running_pnl']
            if dd > results['max_drawdown']:
                results['max_drawdown'] = dd

    return results


def run_equity_backtest_v106(bars, symbol, days,
                              disable_bos_retrace=False,
                              reduced_sizing_window=False,
                              consecutive_loss_cooldown=0,
                              retracement_cutoff_hour=12):
    """Run equity backtest with V10.6 refinements."""
    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:] if len(all_dates) >= days else all_dates

    results = {
        'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0,
        'stopped_out': 0, 'max_drawdown': 0, 'peak': 0, 'running_pnl': 0,
        'skipped_cooldown': 0, 'reduced_sizing_trades': 0
    }

    consecutive_losses = 0

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
            overnight_retrace_min_adx=22,
            midday_cutoff=True,
            pm_cutoff_qqq=True,
            disable_intraday_spy=True,
            atr_buffer_multiplier=0.5,
            high_displacement_override=3.0,
        )

        for r in day_results:
            entry_type = r.get('entry_type', '')
            entry_time = r.get('entry_time', dt_time(9, 30))
            entry_hour = entry_time.hour if hasattr(entry_time, 'hour') else entry_time.time().hour

            # V10.6 Filter 1: Disable BOS_RETRACE
            if disable_bos_retrace and entry_type == 'BOS_RETRACE':
                continue

            # V10.6 Filter 4: Tighten RETRACEMENT to before cutoff hour
            if entry_type == 'RETRACEMENT' and entry_hour >= retracement_cutoff_hour:
                continue

            # V10.6 Filter 3: Consecutive loss cooldown
            if consecutive_loss_cooldown > 0 and consecutive_losses >= consecutive_loss_cooldown:
                results['skipped_cooldown'] += 1
                consecutive_losses = 0
                continue

            # V10.6 Filter 2: Reduced sizing during 10:00-12:00
            sizing_multiplier = 1.0
            if reduced_sizing_window and 10 <= entry_hour < 12:
                sizing_multiplier = 0.5
                results['reduced_sizing_trades'] += 1

            trade_pnl = r['total_dollars'] * sizing_multiplier

            results['trades'] += 1
            results['pnl'] += trade_pnl
            results['running_pnl'] += trade_pnl

            if trade_pnl > 0:
                results['wins'] += 1
                consecutive_losses = 0
            else:
                results['losses'] += 1
                consecutive_losses += 1

            if any(e['type'] == 'STOP' for e in r['exits']):
                results['stopped_out'] += 1

            if results['running_pnl'] > results['peak']:
                results['peak'] = results['running_pnl']
            dd = results['peak'] - results['running_pnl']
            if dd > results['max_drawdown']:
                results['max_drawdown'] = dd

    return results


# Version configurations
VERSIONS = {
    'V10.3': {
        # Baseline V10.3 (no V10.6 refinements)
        'disable_bos_retrace': False,
        'reduced_sizing_window': False,
        'consecutive_loss_cooldown': 0,
        'retracement_cutoff_hour': 24,  # No cutoff
    },
    'V10.5': {
        # Current V10.5 (no V10.6 refinements)
        'disable_bos_retrace': False,
        'reduced_sizing_window': False,
        'consecutive_loss_cooldown': 0,
        'retracement_cutoff_hour': 24,
    },
    'V10.6': {
        # All V10.6 refinements
        'disable_bos_retrace': True,       # 1. Disable BOS_RETRACE
        'reduced_sizing_window': True,     # 2. 50% sizing 10:00-12:00
        'consecutive_loss_cooldown': 3,    # 3. Skip after 3 losses
        'retracement_cutoff_hour': 10,     # 4. RETRACEMENT before 10:00 only
    },
    'V10.6a': {
        # Just disable BOS_RETRACE
        'disable_bos_retrace': True,
        'reduced_sizing_window': False,
        'consecutive_loss_cooldown': 0,
        'retracement_cutoff_hour': 24,
    },
    'V10.6b': {
        # BOS_RETRACE + reduced sizing
        'disable_bos_retrace': True,
        'reduced_sizing_window': True,
        'consecutive_loss_cooldown': 0,
        'retracement_cutoff_hour': 24,
    },
    'V10.6c': {
        # BOS_RETRACE + cooldown
        'disable_bos_retrace': True,
        'reduced_sizing_window': False,
        'consecutive_loss_cooldown': 3,
        'retracement_cutoff_hour': 24,
    },
    'V10.6d': {
        # BOS_RETRACE + RETRACEMENT cutoff
        'disable_bos_retrace': True,
        'reduced_sizing_window': False,
        'consecutive_loss_cooldown': 0,
        'retracement_cutoff_hour': 10,
    },
}


def main():
    days = 30

    print("=" * 90)
    print("V10.6 REFINEMENT COMPARISON - 30 DAY BACKTEST")
    print("=" * 90)
    print("\nV10.6 Changes:")
    print("  1. Disable BOS_RETRACE (25% win rate)")
    print("  2. Reduced sizing 10:00-12:00 (50%)")
    print("  3. Consecutive loss cooldown (skip after 3)")
    print("  4. RETRACEMENT before 10:00 only")
    print()

    print("Fetching data...")
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
            all_results[version]['SPY'] = run_equity_backtest_v106(
                spy_bars, 'SPY', days, **params
            )
        if qqq_bars:
            all_results[version]['QQQ'] = run_equity_backtest_v106(
                qqq_bars, 'QQQ', days, **params
            )

        # Futures
        if es_bars:
            all_results[version]['ES'] = run_futures_backtest_v106(
                es_bars, 'ES', days, 0.25, 12.50, **params
            )
        if nq_bars:
            all_results[version]['NQ'] = run_futures_backtest_v106(
                nq_bars, 'NQ', days, 0.25, 5.00, **params
            )

    # Print comparison
    print("\n" + "=" * 90)
    print("RESULTS BY VERSION")
    print("=" * 90)

    print(f"\n{'Version':<10} {'Trades':>7} {'Wins':>6} {'Losses':>7} {'Win%':>7} {'P/L':>14} {'Max DD':>12} {'DD Chg':>10}")
    print("-" * 85)

    v105_pnl = sum(all_results['V10.5'][s]['pnl'] for s in all_results['V10.5'])
    v105_dd = max(all_results['V10.5'][s]['max_drawdown'] for s in all_results['V10.5'])

    for version in VERSIONS.keys():
        total_trades = sum(all_results[version][s]['trades'] for s in all_results[version])
        total_wins = sum(all_results[version][s]['wins'] for s in all_results[version])
        total_losses = sum(all_results[version][s]['losses'] for s in all_results[version])
        total_pnl = sum(all_results[version][s]['pnl'] for s in all_results[version])
        max_dd = max(all_results[version][s]['max_drawdown'] for s in all_results[version])

        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        dd_change = max_dd - v105_dd

        print(f"{version:<10} {total_trades:>7} {total_wins:>6} {total_losses:>7} {win_rate:>6.1f}% ${total_pnl:>12,.0f} ${max_dd:>10,.0f} {dd_change:>+10,.0f}")

    # Detailed by symbol for key versions
    for symbol in ['ES', 'NQ', 'SPY', 'QQQ']:
        print(f"\n{'-' * 70}")
        print(f"{symbol} COMPARISON")
        print(f"{'-' * 70}")
        print(f"{'Version':<10} {'Trades':>7} {'Wins':>6} {'Win%':>7} {'P/L':>14} {'Max DD':>12}")
        print("-" * 60)

        for version in ['V10.5', 'V10.6']:
            if symbol in all_results[version]:
                r = all_results[version][symbol]
                win_rate = (r['wins'] / r['trades'] * 100) if r['trades'] > 0 else 0
                print(f"{version:<10} {r['trades']:>7} {r['wins']:>6} {win_rate:>6.1f}% ${r['pnl']:>12,.0f} ${r['max_drawdown']:>10,.0f}")

    # Show impact of each refinement
    print("\n" + "=" * 90)
    print("INCREMENTAL IMPACT OF EACH REFINEMENT")
    print("=" * 90)

    refinements = [
        ('V10.5 -> V10.6a', 'Disable BOS_RETRACE', 'V10.5', 'V10.6a'),
        ('V10.6a -> V10.6b', '+ Reduced sizing 10-12', 'V10.6a', 'V10.6b'),
        ('V10.6a -> V10.6c', '+ Consecutive loss cooldown', 'V10.6a', 'V10.6c'),
        ('V10.6a -> V10.6d', '+ RETRACEMENT < 10:00', 'V10.6a', 'V10.6d'),
        ('V10.5 -> V10.6', 'All refinements combined', 'V10.5', 'V10.6'),
    ]

    print(f"\n{'Change':<25} {'Description':<30} {'P/L Diff':>12} {'DD Diff':>12}")
    print("-" * 85)

    for label, desc, v_from, v_to in refinements:
        pnl_from = sum(all_results[v_from][s]['pnl'] for s in all_results[v_from])
        pnl_to = sum(all_results[v_to][s]['pnl'] for s in all_results[v_to])
        dd_from = max(all_results[v_from][s]['max_drawdown'] for s in all_results[v_from])
        dd_to = max(all_results[v_to][s]['max_drawdown'] for s in all_results[v_to])

        pnl_diff = pnl_to - pnl_from
        dd_diff = dd_to - dd_from

        print(f"{label:<25} {desc:<30} ${pnl_diff:>+10,.0f} ${dd_diff:>+10,.0f}")

    # Summary
    print("\n" + "=" * 90)
    print("SUMMARY")
    print("=" * 90)

    v106_pnl = sum(all_results['V10.6'][s]['pnl'] for s in all_results['V10.6'])
    v106_dd = max(all_results['V10.6'][s]['max_drawdown'] for s in all_results['V10.6'])
    v106_trades = sum(all_results['V10.6'][s]['trades'] for s in all_results['V10.6'])
    v105_trades = sum(all_results['V10.5'][s]['trades'] for s in all_results['V10.5'])

    print("\nV10.5 -> V10.6:")
    print(f"  P/L Change:      ${v106_pnl - v105_pnl:>+,.0f}")
    print(f"  Max DD Change:   ${v106_dd - v105_dd:>+,.0f}")
    print(f"  Trades:          {v105_trades} -> {v106_trades} ({v106_trades - v105_trades:+d})")

    if v106_dd < v105_dd:
        improvement = (v105_dd - v106_dd) / v105_dd * 100
        print(f"  DD Reduction:    {improvement:.1f}%")


if __name__ == "__main__":
    main()
