"""
Test BOS Risk Control Strategies

Goal: Keep baseline profit potential but reduce drawdown

Strategies:
1. Reduced BOS position size (50%)
2. Higher ADX filter for BOS (>= 25)
3. Daily BOS loss limit (stop after 1 BOS loss)
4. Time filter (BOS only before 11:00)
5. Profit protection (disable BOS after $10k daily profit)
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from collections import defaultdict
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10
from runners.run_v10_equity import run_session_v10_equity

days = 30


def run_with_bos_controls(es_bars, nq_bars, spy_bars, qqq_bars, strategy='BASELINE'):
    """
    Run backtest with different BOS control strategies.

    Strategies:
    - BASELINE: All BOS enabled, full size
    - OPTIMAL: ES/SPY BOS off, NQ/QQQ BOS on
    - HALF_SIZE: All BOS enabled but 50% position
    - HIGH_ADX: BOS only when ADX >= 25
    - LOSS_LIMIT: Disable BOS after 1 BOS loss per day
    - MORNING_ONLY: BOS only before 11:00
    - PROFIT_PROTECT: Disable BOS after $10k daily profit
    - COMBINED: HIGH_ADX + LOSS_LIMIT + MORNING_ONLY
    """

    all_dates = sorted(set(b.timestamp.date() for b in es_bars))
    recent_dates = all_dates[-days:]

    results = {
        'total_pnl': 0,
        'trades': 0,
        'wins': 0,
        'bos_trades': 0,
        'bos_wins': 0,
        'bos_pnl': 0,
        'max_dd': 0,
        'peak': 0,
        'running': 0,
        'daily_pnl': []
    }

    for target_date in recent_dates:
        daily_pnl = 0
        daily_bos_losses = 0

        for symbol, bars, tick_size, tick_value, is_equity in [
            ('ES', es_bars, 0.25, 12.50, False),
            ('NQ', nq_bars, 0.25, 5.00, False),
            ('SPY', spy_bars, 0.01, 1.00, True),
            ('QQQ', qqq_bars, 0.01, 1.00, True),
        ]:
            day_bars = [b for b in bars if b.timestamp.date() == target_date]
            session_bars = [b for b in day_bars if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]

            if len(session_bars) < 50:
                continue

            # Determine BOS setting based on strategy
            if strategy == 'OPTIMAL':
                disable_bos = symbol in ['ES', 'SPY']
            else:
                disable_bos = False  # All other strategies keep BOS enabled

            # Run the session
            if is_equity:
                trades = run_session_v10_equity(
                    session_bars, bars, symbol=symbol, risk_per_trade=500,
                    t1_fixed_4r=True, overnight_retrace_min_adx=22,
                    midday_cutoff=True, pm_cutoff_qqq=True,
                    disable_intraday_spy=True, atr_buffer_multiplier=0.5,
                    high_displacement_override=3.0, disable_bos_retrace=disable_bos,
                )
            else:
                min_risk = 1.5 if symbol == 'ES' else 6.0
                max_bos = 8.0 if symbol == 'ES' else 20.0
                trades = run_session_v10(
                    session_bars, bars, tick_size=tick_size, tick_value=tick_value,
                    contracts=3, min_risk_pts=min_risk, t1_fixed_4r=True,
                    overnight_retrace_min_adx=22, midday_cutoff=True,
                    pm_cutoff_nq=True, max_bos_risk_pts=max_bos,
                    high_displacement_override=3.0, disable_bos_retrace=disable_bos,
                    symbol=symbol,
                )

            for t in trades:
                entry_type = t.get('entry_type', '')
                is_bos = 'BOS' in entry_type
                pnl = t['total_dollars']
                entry_time = t.get('entry_time')
                entry_hour = entry_time.hour if hasattr(entry_time, 'hour') else 9

                # Apply strategy-specific filters
                include_trade = True
                size_multiplier = 1.0

                if is_bos and strategy != 'BASELINE' and strategy != 'OPTIMAL':
                    if strategy == 'HALF_SIZE':
                        size_multiplier = 0.5

                    elif strategy == 'HIGH_ADX':
                        # Would need ADX value - approximate by only taking on big move days
                        # Skip BOS if daily range is small (proxy for low ADX)
                        day_range = max(b.high for b in session_bars) - min(b.low for b in session_bars)
                        avg_range = sum(abs(b.high - b.low) for b in session_bars) / len(session_bars)
                        if day_range < avg_range * 15:  # Low volatility day
                            include_trade = False

                    elif strategy == 'LOSS_LIMIT':
                        if daily_bos_losses >= 1:
                            include_trade = False

                    elif strategy == 'MORNING_ONLY':
                        if entry_hour >= 11:
                            include_trade = False

                    elif strategy == 'PROFIT_PROTECT':
                        if daily_pnl >= 10000:
                            include_trade = False

                    elif strategy == 'COMBINED':
                        # Apply all filters
                        if daily_bos_losses >= 1:
                            include_trade = False
                        elif entry_hour >= 11:
                            include_trade = False
                        elif daily_pnl >= 15000:
                            include_trade = False

                if include_trade:
                    adjusted_pnl = pnl * size_multiplier

                    results['trades'] += 1
                    results['total_pnl'] += adjusted_pnl
                    results['running'] += adjusted_pnl
                    daily_pnl += adjusted_pnl

                    if adjusted_pnl > 0:
                        results['wins'] += 1

                    if is_bos:
                        results['bos_trades'] += 1
                        results['bos_pnl'] += adjusted_pnl
                        if adjusted_pnl > 0:
                            results['bos_wins'] += 1
                        else:
                            daily_bos_losses += 1

                    # Track drawdown
                    if results['running'] > results['peak']:
                        results['peak'] = results['running']
                    dd = results['peak'] - results['running']
                    if dd > results['max_dd']:
                        results['max_dd'] = dd

        results['daily_pnl'].append(daily_pnl)

    return results


def main():
    print('Fetching data...')
    es_bars = fetch_futures_bars('ES', interval='3m', n_bars=15000)
    nq_bars = fetch_futures_bars('NQ', interval='3m', n_bars=15000)
    spy_bars = fetch_futures_bars('SPY', interval='3m', n_bars=15000)
    qqq_bars = fetch_futures_bars('QQQ', interval='3m', n_bars=15000)

    strategies = [
        'BASELINE',
        'OPTIMAL',
        'HALF_SIZE',
        'LOSS_LIMIT',
        'MORNING_ONLY',
        'PROFIT_PROTECT',
        'COMBINED',
    ]

    print('\n' + '=' * 100)
    print('BOS RISK CONTROL STRATEGIES COMPARISON (30 days)')
    print('=' * 100)

    all_results = {}

    for strategy in strategies:
        print(f'\nTesting {strategy}...')
        all_results[strategy] = run_with_bos_controls(es_bars, nq_bars, spy_bars, qqq_bars, strategy)

    # Print comparison
    print('\n' + '=' * 100)
    print('RESULTS COMPARISON')
    print('=' * 100)

    baseline = all_results['BASELINE']

    print(f"\n{'Strategy':<18} {'Trades':>8} {'Win%':>7} {'P/L':>14} {'Max DD':>12} {'DD Chg':>10} {'P/L vs Base':>12}")
    print('-' * 85)

    for strategy in strategies:
        r = all_results[strategy]
        wr = r['wins'] / r['trades'] * 100 if r['trades'] else 0
        dd_change = r['max_dd'] - baseline['max_dd']
        pnl_change = r['total_pnl'] - baseline['total_pnl']

        print(f"{strategy:<18} {r['trades']:>8} {wr:>6.1f}% ${r['total_pnl']:>12,.0f} ${r['max_dd']:>10,.0f} ${dd_change:>+8,.0f} ${pnl_change:>+10,.0f}")

    # BOS specific stats
    print('\n' + '=' * 100)
    print('BOS TRADE DETAILS')
    print('=' * 100)

    print(f"\n{'Strategy':<18} {'BOS Trades':>12} {'BOS Wins':>10} {'BOS Win%':>10} {'BOS P/L':>14}")
    print('-' * 70)

    for strategy in strategies:
        r = all_results[strategy]
        bos_wr = r['bos_wins'] / r['bos_trades'] * 100 if r['bos_trades'] else 0
        print(f"{strategy:<18} {r['bos_trades']:>12} {r['bos_wins']:>10} {bos_wr:>9.1f}% ${r['bos_pnl']:>12,.0f}")

    # Find best strategy
    print('\n' + '=' * 100)
    print('ANALYSIS')
    print('=' * 100)

    # Best P/L
    best_pnl = max(all_results.items(), key=lambda x: x[1]['total_pnl'])
    print(f"\nHighest P/L: {best_pnl[0]} (${best_pnl[1]['total_pnl']:,.0f})")

    # Lowest DD
    best_dd = min(all_results.items(), key=lambda x: x[1]['max_dd'])
    print(f"Lowest Drawdown: {best_dd[0]} (${best_dd[1]['max_dd']:,.0f})")

    # Best risk-adjusted (P/L / DD ratio)
    risk_adjusted = [(k, v['total_pnl'] / max(1, v['max_dd'])) for k, v in all_results.items()]
    best_ratio = max(risk_adjusted, key=lambda x: x[1])
    print(f"Best Risk-Adjusted: {best_ratio[0]} (ratio: {best_ratio[1]:.1f})")

    # Recommendation
    print('\n' + '=' * 100)
    print('RECOMMENDATION')
    print('=' * 100)

    # Find strategies that improve DD without losing too much P/L
    print('\nStrategies that reduce DD while maintaining most profits:')
    for strategy in strategies:
        r = all_results[strategy]
        dd_reduction = baseline['max_dd'] - r['max_dd']
        pnl_loss = baseline['total_pnl'] - r['total_pnl']

        if dd_reduction > 0:  # DD improved
            efficiency = dd_reduction / max(1, pnl_loss) if pnl_loss > 0 else float('inf')
            print(f"  {strategy}: DD reduced ${dd_reduction:,.0f}, P/L cost ${pnl_loss:,.0f} (efficiency: {efficiency:.2f})")


if __name__ == '__main__':
    main()
