"""
Surgical Fixes Comparison - Optimize P/L while limiting drawdown

Tests targeted fixes instead of blunt V10.6 changes:
1. Delay overnight retrace to 10:00 (avoid 09:45 gap-and-rally)
2. Max risk cap on overnight retrace (prevent oversized NQ entries)
3. Entry distance limit from FVG (reject if price too far from zone)
4. BOS loss limit per symbol (already in V10.6)
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10


def run_backtest_with_filters(
    bars, symbol, days,
    tick_size, tick_value, contracts=3,
    # Surgical fix parameters
    overnight_retrace_start_hour=9,  # Hour to start allowing overnight retrace
    overnight_retrace_start_minute=30,  # Minute to start (e.g., 9:45 = hour=9, minute=45)
    max_overnight_risk_pts=None,     # Max risk for overnight retrace entries
    max_entry_distance_pts=None,     # Max distance from FVG for entry
    disable_bos_es=True,             # Disable BOS for ES
    bos_loss_limit=1,                # BOS loss limit per day
):
    """Run backtest with surgical filters applied post-hoc."""

    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:] if len(all_dates) >= days else all_dates

    min_risk = 1.5 if symbol in ['ES', 'MES'] else 6.0
    max_bos_risk = 8.0 if symbol in ['ES', 'MES'] else 20.0

    # Determine if BOS should be disabled for this symbol
    disable_bos = disable_bos_es and symbol in ['ES', 'MES']

    results = {
        'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0,
        'max_drawdown': 0, 'peak': 0, 'running_pnl': 0,
        'filtered_overnight_time': 0,
        'filtered_overnight_risk': 0,
        'filtered_entry_distance': 0,
        'by_type': {'CREATION': [], 'RETRACEMENT': [], 'INTRADAY_RETRACE': [], 'BOS_RETRACE': []}
    }

    bos_losses_today = 0
    current_date = None

    for target_date in recent_dates:
        day_bars = [b for b in bars if b.timestamp.date() == target_date]
        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Reset daily BOS loss counter
        if target_date != current_date:
            bos_losses_today = 0
            current_date = target_date

        day_results = run_session_v10(
            session_bars, bars,
            tick_size=tick_size,
            tick_value=tick_value,
            contracts=contracts,
            min_risk_pts=min_risk,
            enable_creation_entry=True,
            enable_retracement_entry=True,
            enable_bos_entry=not disable_bos,
            retracement_morning_only=False,
            t1_fixed_4r=True,
            overnight_retrace_min_adx=22,
            midday_cutoff=True,
            pm_cutoff_nq=(symbol in ['NQ', 'MNQ']),
            max_bos_risk_pts=max_bos_risk,
            high_displacement_override=3.0,
            symbol=symbol,
            bos_daily_loss_limit=bos_loss_limit,
        )

        for r in day_results:
            entry_type = r.get('entry_type', '')
            entry_time = r.get('entry_time')
            if entry_time:
                entry_hour = entry_time.hour if hasattr(entry_time, 'hour') else entry_time.time().hour
                entry_minute = entry_time.minute if hasattr(entry_time, 'minute') else entry_time.time().minute
            else:
                entry_hour, entry_minute = 9, 30
            risk_pts = r.get('risk', 0)
            fvg_low = r.get('fvg_low', 0)
            fvg_high = r.get('fvg_high', 0)
            fvg_mid = (fvg_low + fvg_high) / 2 if fvg_low and fvg_high else 0
            entry_price = r.get('entry_price', 0)

            # Surgical Fix 1: Delay overnight retrace start time
            if entry_type == 'RETRACEMENT':
                entry_time_mins = entry_hour * 60 + entry_minute
                start_time_mins = overnight_retrace_start_hour * 60 + overnight_retrace_start_minute
                if entry_time_mins < start_time_mins:
                    results['filtered_overnight_time'] += 1
                    continue

            # Surgical Fix 2: Max risk cap on overnight retrace
            if entry_type == 'RETRACEMENT' and max_overnight_risk_pts:
                if risk_pts > max_overnight_risk_pts:
                    results['filtered_overnight_risk'] += 1
                    continue

            # Surgical Fix 3: Entry distance limit from FVG
            if max_entry_distance_pts and fvg_mid > 0 and entry_price > 0:
                distance = abs(entry_price - fvg_mid)
                if distance > max_entry_distance_pts:
                    results['filtered_entry_distance'] += 1
                    continue

            # Track trade
            trade_pnl = r['total_dollars']
            results['trades'] += 1
            results['pnl'] += trade_pnl
            results['running_pnl'] += trade_pnl

            if entry_type in results['by_type']:
                results['by_type'][entry_type].append(trade_pnl)

            if trade_pnl > 0:
                results['wins'] += 1
            else:
                results['losses'] += 1
                if entry_type == 'BOS_RETRACE':
                    bos_losses_today += 1

            # Track drawdown
            if results['running_pnl'] > results['peak']:
                results['peak'] = results['running_pnl']
            dd = results['peak'] - results['running_pnl']
            if dd > results['max_drawdown']:
                results['max_drawdown'] = dd

    return results


# Test scenarios
SCENARIOS = {
    'V10.5 Baseline': {
        'overnight_retrace_start_hour': 9,
        'overnight_retrace_start_minute': 30,
        'max_overnight_risk_pts': None,
        'max_entry_distance_pts': None,
        'disable_bos_es': False,
        'bos_loss_limit': 0,
    },
    'V10.6 Current': {
        'overnight_retrace_start_hour': 9,
        'overnight_retrace_start_minute': 30,
        'max_overnight_risk_pts': None,
        'max_entry_distance_pts': None,
        'disable_bos_es': True,
        'bos_loss_limit': 1,
    },
    'Fix 1a: Retrace 9:45': {
        'overnight_retrace_start_hour': 9,
        'overnight_retrace_start_minute': 45,
        'max_overnight_risk_pts': None,
        'max_entry_distance_pts': None,
        'disable_bos_es': False,
        'bos_loss_limit': 0,
    },
    'Fix 1b: Retrace 10:00': {
        'overnight_retrace_start_hour': 10,
        'overnight_retrace_start_minute': 0,
        'max_overnight_risk_pts': None,
        'max_entry_distance_pts': None,
        'disable_bos_es': False,
        'bos_loss_limit': 0,
    },
    'Fix 2: Max Risk 15': {
        'overnight_retrace_start_hour': 9,
        'overnight_retrace_start_minute': 30,
        'max_overnight_risk_pts': 15,
        'max_entry_distance_pts': None,
        'disable_bos_es': False,
        'bos_loss_limit': 0,
    },
    'Fix 3: Entry Dist 20': {
        'overnight_retrace_start_hour': 9,
        'overnight_retrace_start_minute': 30,
        'max_overnight_risk_pts': None,
        'max_entry_distance_pts': 20,
        'disable_bos_es': False,
        'bos_loss_limit': 0,
    },
    'Fix 4: BOS Limit': {
        'overnight_retrace_start_hour': 9,
        'overnight_retrace_start_minute': 30,
        'max_overnight_risk_pts': None,
        'max_entry_distance_pts': None,
        'disable_bos_es': True,
        'bos_loss_limit': 1,
    },
    '9:45 + BOS Limit': {
        'overnight_retrace_start_hour': 9,
        'overnight_retrace_start_minute': 45,
        'max_overnight_risk_pts': None,
        'max_entry_distance_pts': None,
        'disable_bos_es': True,
        'bos_loss_limit': 1,
    },
    '9:45 + Risk 15': {
        'overnight_retrace_start_hour': 9,
        'overnight_retrace_start_minute': 45,
        'max_overnight_risk_pts': 15,
        'max_entry_distance_pts': None,
        'disable_bos_es': False,
        'bos_loss_limit': 0,
    },
    '9:45 + Risk 15 + BOS': {
        'overnight_retrace_start_hour': 9,
        'overnight_retrace_start_minute': 45,
        'max_overnight_risk_pts': 15,
        'max_entry_distance_pts': None,
        'disable_bos_es': True,
        'bos_loss_limit': 1,
    },
    '10:00 + BOS Limit': {
        'overnight_retrace_start_hour': 10,
        'overnight_retrace_start_minute': 0,
        'max_overnight_risk_pts': None,
        'max_entry_distance_pts': None,
        'disable_bos_es': True,
        'bos_loss_limit': 1,
    },
}


def main():
    days = 30

    print("=" * 100)
    print("SURGICAL FIXES COMPARISON - 30 DAY BACKTEST")
    print("=" * 100)
    print("\nFixes being tested:")
    print("  1. Delay overnight retrace to 10:00 (avoid 09:45 gap-and-rally)")
    print("  2. Max risk 15 pts on overnight retrace (prevent oversized entries)")
    print("  3. Max entry distance 20 pts from FVG (reject distant entries)")
    print("  4. BOS loss limit + ES BOS disabled (per-symbol control)")
    print()

    print("Fetching data...")
    es_bars = fetch_futures_bars('ES', interval='3m', n_bars=15000)
    nq_bars = fetch_futures_bars('NQ', interval='3m', n_bars=15000)

    if not es_bars or not nq_bars:
        print("Failed to fetch data!")
        return

    all_results = {}

    for scenario_name, params in SCENARIOS.items():
        print(f"Running {scenario_name}...")
        all_results[scenario_name] = {}

        all_results[scenario_name]['ES'] = run_backtest_with_filters(
            es_bars, 'ES', days, 0.25, 12.50, **params
        )
        all_results[scenario_name]['NQ'] = run_backtest_with_filters(
            nq_bars, 'NQ', days, 0.25, 5.00, **params
        )

    # Print comparison table
    print("\n" + "=" * 100)
    print("RESULTS COMPARISON")
    print("=" * 100)

    baseline_pnl = sum(all_results['V10.5 Baseline'][s]['pnl'] for s in ['ES', 'NQ'])
    baseline_dd = max(all_results['V10.5 Baseline'][s]['max_drawdown'] for s in ['ES', 'NQ'])

    print(f"\n{'Scenario':<25} {'Trades':>7} {'Wins':>6} {'Win%':>7} {'P/L':>14} {'vs Base':>12} {'Max DD':>10} {'DD Chg':>10}")
    print("-" * 100)

    for scenario_name in SCENARIOS.keys():
        total_trades = sum(all_results[scenario_name][s]['trades'] for s in ['ES', 'NQ'])
        total_wins = sum(all_results[scenario_name][s]['wins'] for s in ['ES', 'NQ'])
        total_pnl = sum(all_results[scenario_name][s]['pnl'] for s in ['ES', 'NQ'])
        max_dd = max(all_results[scenario_name][s]['max_drawdown'] for s in ['ES', 'NQ'])

        win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
        pnl_diff = total_pnl - baseline_pnl
        dd_diff = max_dd - baseline_dd

        print(f"{scenario_name:<25} {total_trades:>7} {total_wins:>6} {win_rate:>6.1f}% ${total_pnl:>12,.0f} ${pnl_diff:>+10,.0f} ${max_dd:>8,.0f} ${dd_diff:>+8,.0f}")

    # Detailed breakdown by symbol
    for symbol in ['ES', 'NQ']:
        print(f"\n{'-' * 80}")
        print(f"{symbol} BREAKDOWN")
        print(f"{'-' * 80}")
        print(f"{'Scenario':<25} {'Trades':>7} {'Win%':>7} {'P/L':>14} {'Max DD':>10} {'Filtered':>10}")
        print("-" * 80)

        for scenario_name in SCENARIOS.keys():
            r = all_results[scenario_name][symbol]
            win_rate = (r['wins'] / r['trades'] * 100) if r['trades'] > 0 else 0
            filtered = r['filtered_overnight_time'] + r['filtered_overnight_risk'] + r['filtered_entry_distance']
            print(f"{scenario_name:<25} {r['trades']:>7} {win_rate:>6.1f}% ${r['pnl']:>12,.0f} ${r['max_drawdown']:>8,.0f} {filtered:>10}")

    # Filter effectiveness
    print(f"\n{'-' * 80}")
    print("FILTER EFFECTIVENESS (Trades Filtered)")
    print(f"{'-' * 80}")
    print(f"{'Scenario':<25} {'Time Filter':>12} {'Risk Cap':>12} {'Distance':>12} {'Total':>12}")
    print("-" * 80)

    for scenario_name in SCENARIOS.keys():
        time_f = sum(all_results[scenario_name][s]['filtered_overnight_time'] for s in ['ES', 'NQ'])
        risk_f = sum(all_results[scenario_name][s]['filtered_overnight_risk'] for s in ['ES', 'NQ'])
        dist_f = sum(all_results[scenario_name][s]['filtered_entry_distance'] for s in ['ES', 'NQ'])
        total_f = time_f + risk_f + dist_f
        if total_f > 0:
            print(f"{scenario_name:<25} {time_f:>12} {risk_f:>12} {dist_f:>12} {total_f:>12}")

    # Recommendation
    print("\n" + "=" * 100)
    print("RECOMMENDATION")
    print("=" * 100)

    # Find best scenario (highest P/L with DD <= baseline or minimal DD increase)
    best_scenario = None
    best_score = -float('inf')

    for scenario_name in SCENARIOS.keys():
        total_pnl = sum(all_results[scenario_name][s]['pnl'] for s in ['ES', 'NQ'])
        max_dd = max(all_results[scenario_name][s]['max_drawdown'] for s in ['ES', 'NQ'])

        # Score: P/L bonus for keeping profits, penalty for increased DD
        pnl_score = total_pnl / 1000
        dd_penalty = max(0, (max_dd - baseline_dd)) / 100
        score = pnl_score - dd_penalty * 5  # Heavy penalty for DD increase

        if score > best_score:
            best_score = score
            best_scenario = scenario_name

    print(f"\nBest scenario: {best_scenario}")

    best_pnl = sum(all_results[best_scenario][s]['pnl'] for s in ['ES', 'NQ'])
    best_dd = max(all_results[best_scenario][s]['max_drawdown'] for s in ['ES', 'NQ'])

    print(f"  P/L: ${best_pnl:,.0f} (vs baseline ${baseline_pnl:,.0f}, diff: ${best_pnl - baseline_pnl:+,.0f})")
    print(f"  Max DD: ${best_dd:,.0f} (vs baseline ${baseline_dd:,.0f}, diff: ${best_dd - baseline_dd:+,.0f})")

    if best_dd < baseline_dd:
        dd_reduction = (baseline_dd - best_dd) / baseline_dd * 100
        print(f"  DD Reduction: {dd_reduction:.1f}%")


if __name__ == "__main__":
    main()
