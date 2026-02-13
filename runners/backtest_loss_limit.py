"""
Full 30-day Backtest: LOSS_LIMIT Strategy

Strategy: Stop taking BOS entries after 1 BOS loss per day per symbol
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from collections import defaultdict
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10
from runners.run_v10_equity import run_session_v10_equity

days = 30


def run_day_with_loss_limit(session_bars, all_bars, symbol, tick_size, tick_value, is_equity, daily_bos_losses):
    """Run single day with BOS loss limit applied."""
    if len(session_bars) < 50:
        return [], daily_bos_losses

    # Run session to get all potential trades
    if is_equity:
        trades = run_session_v10_equity(
            session_bars, all_bars, symbol=symbol, risk_per_trade=500,
            t1_fixed_4r=True, overnight_retrace_min_adx=22,
            midday_cutoff=True, pm_cutoff_qqq=True,
            disable_intraday_spy=True, atr_buffer_multiplier=0.5,
            high_displacement_override=3.0, disable_bos_retrace=False,
        )
    else:
        min_risk = 1.5 if symbol in ['ES', 'MES'] else 6.0
        max_bos = 8.0 if symbol in ['ES', 'MES'] else 20.0
        trades = run_session_v10(
            session_bars, all_bars, tick_size=tick_size, tick_value=tick_value,
            contracts=3, min_risk_pts=min_risk, t1_fixed_4r=True,
            overnight_retrace_min_adx=22, midday_cutoff=True,
            pm_cutoff_nq=True, max_bos_risk_pts=max_bos,
            high_displacement_override=3.0, disable_bos_retrace=False,
            symbol=symbol,
        )

    # Apply loss limit filter
    filtered_trades = []
    for t in trades:
        entry_type = t.get('entry_type', '')
        is_bos = 'BOS' in entry_type
        pnl = t['total_dollars']

        # If BOS and we've already had a BOS loss today, skip
        if is_bos and daily_bos_losses >= 1:
            continue

        filtered_trades.append(t)

        # Track BOS losses
        if is_bos and pnl <= 0:
            daily_bos_losses += 1

    return filtered_trades, daily_bos_losses


def main():
    print('Fetching data...')
    es_bars = fetch_futures_bars('ES', interval='3m', n_bars=15000)
    nq_bars = fetch_futures_bars('NQ', interval='3m', n_bars=15000)
    spy_bars = fetch_futures_bars('SPY', interval='3m', n_bars=15000)
    qqq_bars = fetch_futures_bars('QQQ', interval='3m', n_bars=15000)

    all_dates = sorted(set(b.timestamp.date() for b in es_bars))
    recent_dates = all_dates[-days:]

    print(f'\nBacktesting {len(recent_dates)} trading days...\n')

    # Store results
    daily_results = []
    symbol_totals = defaultdict(lambda: {
        'trades': 0, 'wins': 0, 'pnl': 0,
        'bos_trades': 0, 'bos_wins': 0, 'bos_pnl': 0,
        'bos_skipped': 0
    })

    total_results = {
        'trades': 0, 'wins': 0, 'pnl': 0,
        'bos_trades': 0, 'bos_wins': 0, 'bos_pnl': 0,
        'bos_skipped': 0,
        'max_dd': 0, 'peak': 0, 'running': 0
    }

    print('=' * 100)
    print('DAILY BREAKDOWN')
    print('=' * 100)
    print(f"\n{'Date':<12} {'ES':>12} {'NQ':>12} {'SPY':>12} {'QQQ':>12} {'Total':>14} {'Running':>14}")
    print('-' * 90)

    for target_date in recent_dates:
        day_pnl = {'ES': 0, 'NQ': 0, 'SPY': 0, 'QQQ': 0}
        day_trades = []

        for symbol, bars, tick_size, tick_value, is_equity in [
            ('ES', es_bars, 0.25, 12.50, False),
            ('NQ', nq_bars, 0.25, 5.00, False),
            ('SPY', spy_bars, 0.01, 1.00, True),
            ('QQQ', qqq_bars, 0.01, 1.00, True),
        ]:
            day_bars = [b for b in bars if b.timestamp.date() == target_date]
            session_bars = [b for b in day_bars if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]

            # Track BOS losses for this symbol today
            daily_bos_losses = 0

            trades, daily_bos_losses = run_day_with_loss_limit(
                session_bars, bars, symbol, tick_size, tick_value, is_equity, daily_bos_losses
            )

            for t in trades:
                entry_type = t.get('entry_type', '')
                is_bos = 'BOS' in entry_type
                pnl = t['total_dollars']

                day_pnl[symbol] += pnl
                symbol_totals[symbol]['trades'] += 1
                symbol_totals[symbol]['pnl'] += pnl

                total_results['trades'] += 1
                total_results['pnl'] += pnl
                total_results['running'] += pnl

                if pnl > 0:
                    symbol_totals[symbol]['wins'] += 1
                    total_results['wins'] += 1

                if is_bos:
                    symbol_totals[symbol]['bos_trades'] += 1
                    symbol_totals[symbol]['bos_pnl'] += pnl
                    total_results['bos_trades'] += 1
                    total_results['bos_pnl'] += pnl

                    if pnl > 0:
                        symbol_totals[symbol]['bos_wins'] += 1
                        total_results['bos_wins'] += 1

                day_trades.append({
                    'symbol': symbol,
                    'entry_type': entry_type,
                    'pnl': pnl,
                    'is_bos': is_bos
                })

                # Track drawdown
                if total_results['running'] > total_results['peak']:
                    total_results['peak'] = total_results['running']
                dd = total_results['peak'] - total_results['running']
                if dd > total_results['max_dd']:
                    total_results['max_dd'] = dd

        total_day = sum(day_pnl.values())

        daily_results.append({
            'date': target_date,
            'pnl': day_pnl,
            'total': total_day,
            'trades': day_trades
        })

        # Print daily row
        print(f"{str(target_date):<12} ${day_pnl['ES']:>10,.0f} ${day_pnl['NQ']:>10,.0f} ${day_pnl['SPY']:>10,.0f} ${day_pnl['QQQ']:>10,.0f} ${total_day:>12,.0f} ${total_results['running']:>12,.0f}")

    # Summary
    print('\n' + '=' * 100)
    print('SUMMARY BY SYMBOL')
    print('=' * 100)

    print(f"\n{'Symbol':<8} {'Trades':>8} {'Wins':>6} {'Win%':>7} {'P/L':>14} {'BOS Trades':>12} {'BOS Win%':>10} {'BOS P/L':>12}")
    print('-' * 85)

    for symbol in ['ES', 'NQ', 'SPY', 'QQQ']:
        s = symbol_totals[symbol]
        wr = s['wins'] / s['trades'] * 100 if s['trades'] else 0
        bos_wr = s['bos_wins'] / s['bos_trades'] * 100 if s['bos_trades'] else 0
        print(f"{symbol:<8} {s['trades']:>8} {s['wins']:>6} {wr:>6.1f}% ${s['pnl']:>12,.0f} {s['bos_trades']:>12} {bos_wr:>9.1f}% ${s['bos_pnl']:>10,.0f}")

    # Totals
    print('-' * 85)
    total_wr = total_results['wins'] / total_results['trades'] * 100 if total_results['trades'] else 0
    total_bos_wr = total_results['bos_wins'] / total_results['bos_trades'] * 100 if total_results['bos_trades'] else 0
    print(f"{'TOTAL':<8} {total_results['trades']:>8} {total_results['wins']:>6} {total_wr:>6.1f}% ${total_results['pnl']:>12,.0f} {total_results['bos_trades']:>12} {total_bos_wr:>9.1f}% ${total_results['bos_pnl']:>10,.0f}")

    # Best and worst days
    print('\n' + '=' * 100)
    print('BEST 5 DAYS')
    print('=' * 100)

    sorted_days = sorted(daily_results, key=lambda x: x['total'], reverse=True)

    print(f"\n{'Rank':<6} {'Date':<12} {'ES':>12} {'NQ':>12} {'SPY':>12} {'QQQ':>12} {'Total':>14}")
    print('-' * 80)

    for i, d in enumerate(sorted_days[:5], 1):
        print(f"{i:<6} {str(d['date']):<12} ${d['pnl']['ES']:>10,.0f} ${d['pnl']['NQ']:>10,.0f} ${d['pnl']['SPY']:>10,.0f} ${d['pnl']['QQQ']:>10,.0f} ${d['total']:>12,.0f}")

    print('\n' + '=' * 100)
    print('WORST 5 DAYS')
    print('=' * 100)

    print(f"\n{'Rank':<6} {'Date':<12} {'ES':>12} {'NQ':>12} {'SPY':>12} {'QQQ':>12} {'Total':>14}")
    print('-' * 80)

    for i, d in enumerate(sorted_days[-5:][::-1], 1):
        print(f"{i:<6} {str(d['date']):<12} ${d['pnl']['ES']:>10,.0f} ${d['pnl']['NQ']:>10,.0f} ${d['pnl']['SPY']:>10,.0f} ${d['pnl']['QQQ']:>10,.0f} ${d['total']:>12,.0f}")

    # Performance metrics
    print('\n' + '=' * 100)
    print('PERFORMANCE METRICS')
    print('=' * 100)

    winning_days = sum(1 for d in daily_results if d['total'] > 0)
    losing_days = sum(1 for d in daily_results if d['total'] < 0)
    flat_days = sum(1 for d in daily_results if d['total'] == 0)

    avg_win_day = sum(d['total'] for d in daily_results if d['total'] > 0) / max(1, winning_days)
    avg_lose_day = sum(d['total'] for d in daily_results if d['total'] < 0) / max(1, losing_days)

    print(f"\nTotal P/L:           ${total_results['pnl']:>12,.0f}")
    print(f"Total Trades:        {total_results['trades']:>12}")
    print(f"Win Rate:            {total_wr:>11.1f}%")
    print(f"Max Drawdown:        ${total_results['max_dd']:>12,.0f}")
    print(f"Peak Equity:         ${total_results['peak']:>12,.0f}")
    print(f"\nWinning Days:        {winning_days:>12} ({winning_days/len(recent_dates)*100:.1f}%)")
    print(f"Losing Days:         {losing_days:>12} ({losing_days/len(recent_dates)*100:.1f}%)")
    print(f"Flat Days:           {flat_days:>12}")
    print(f"\nAvg Winning Day:     ${avg_win_day:>12,.0f}")
    print(f"Avg Losing Day:      ${avg_lose_day:>12,.0f}")
    print(f"Profit Factor:       {abs(sum(d['total'] for d in daily_results if d['total'] > 0) / min(-1, sum(d['total'] for d in daily_results if d['total'] < 0))):>12.2f}")

    # BOS specific
    print('\n' + '=' * 100)
    print('BOS ANALYSIS (LOSS_LIMIT APPLIED)')
    print('=' * 100)

    print(f"\nBOS Trades Taken:    {total_results['bos_trades']:>12}")
    print(f"BOS Wins:            {total_results['bos_wins']:>12}")
    print(f"BOS Win Rate:        {total_bos_wr:>11.1f}%")
    print(f"BOS P/L:             ${total_results['bos_pnl']:>12,.0f}")
    print(f"Avg BOS Trade:       ${total_results['bos_pnl']/max(1,total_results['bos_trades']):>12,.0f}")


if __name__ == '__main__':
    main()
