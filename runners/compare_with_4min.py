"""
Compare 3-min, 4-min (synthetic), 5-min timeframes
4-min is created by aggregating 1-min bars
"""
import sys
sys.path.insert(0, '.')
from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10
from collections import namedtuple

Bar = namedtuple('Bar', ['timestamp', 'open', 'high', 'low', 'close', 'volume'])


def aggregate_to_interval(bars_1m, interval_minutes):
    """Aggregate 1-minute bars into larger intervals."""
    if not bars_1m:
        return []

    aggregated = []
    current_group = []

    for bar in bars_1m:
        # Determine which interval this bar belongs to
        minutes = bar.timestamp.hour * 60 + bar.timestamp.minute
        interval_start = (minutes // interval_minutes) * interval_minutes

        if current_group:
            first_bar_minutes = current_group[0].timestamp.hour * 60 + current_group[0].timestamp.minute
            first_interval = (first_bar_minutes // interval_minutes) * interval_minutes

            # Check if same date and same interval
            if (bar.timestamp.date() == current_group[0].timestamp.date() and
                interval_start == first_interval):
                current_group.append(bar)
            else:
                # Close current group and start new one
                if current_group:
                    agg_bar = Bar(
                        timestamp=current_group[0].timestamp,
                        open=current_group[0].open,
                        high=max(b.high for b in current_group),
                        low=min(b.low for b in current_group),
                        close=current_group[-1].close,
                        volume=sum(getattr(b, 'volume', 0) for b in current_group)
                    )
                    aggregated.append(agg_bar)
                current_group = [bar]
        else:
            current_group = [bar]

    # Don't forget the last group
    if current_group:
        agg_bar = Bar(
            timestamp=current_group[0].timestamp,
            open=current_group[0].open,
            high=max(b.high for b in current_group),
            low=min(b.low for b in current_group),
            close=current_group[-1].close,
            volume=sum(getattr(b, 'volume', 0) for b in current_group)
        )
        aggregated.append(agg_bar)

    return aggregated


def backtest_multiday(symbol, interval, days=30):
    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00
    min_risk_pts = 1.5 if symbol == 'ES' else 6.0
    max_bos_risk_pts = 8.0 if symbol == 'ES' else 20.0

    print(f'  Fetching {symbol} {interval} data...')

    # For 4m, fetch 1m and aggregate
    if interval == '4m':
        bars_1m = fetch_futures_bars(symbol=symbol, interval='1m', n_bars=15000)
        if not bars_1m:
            return None
        all_bars = aggregate_to_interval(bars_1m, 4)
        print(f'    Aggregated {len(bars_1m)} 1m bars into {len(all_bars)} 4m bars')
    else:
        all_bars = fetch_futures_bars(symbol=symbol, interval=interval, n_bars=10000)

    if not all_bars:
        return None

    all_dates = sorted(set(b.timestamp.date() for b in all_bars), reverse=True)
    trading_dates = []
    for d in all_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == d]
        rth_bars = [b for b in day_bars if dt_time(9, 30) <= b.timestamp.time() <= dt_time(16, 0)]
        if len(rth_bars) >= 20:
            trading_dates.append(d)
        if len(trading_dates) >= days:
            break
    trading_dates = sorted(trading_dates)

    results_by_day = {}
    all_trades = []

    for target_date in trading_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == target_date]
        session_bars = [b for b in day_bars if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]

        if len(session_bars) < 20:
            continue

        results = run_session_v10(
            session_bars, all_bars,
            tick_size=tick_size, tick_value=tick_value, contracts=3,
            min_risk_pts=min_risk_pts,
            enable_creation_entry=True, enable_retracement_entry=True, enable_bos_entry=True,
            retracement_morning_only=True, t1_fixed_4r=True,
            midday_cutoff=True, pm_cutoff_nq=(symbol == 'NQ'),
            max_bos_risk_pts=max_bos_risk_pts, symbol=symbol,
        )

        day_pnl = sum(r['total_dollars'] for r in results)
        results_by_day[target_date] = {'pnl': day_pnl, 'trades': len(results)}

        for r in results:
            r['date'] = target_date
            all_trades.append(r)

    return {
        'symbol': symbol,
        'interval': interval,
        'days': trading_dates,
        'by_day': results_by_day,
        'trades': all_trades,
        'total_pnl': sum(d['pnl'] for d in results_by_day.values()),
        'total_trades': len(all_trades),
        'wins': sum(1 for t in all_trades if t['total_dollars'] > 0),
        'losses': [t for t in all_trades if t['total_dollars'] < 0],
    }


def filter_to_dates(data, dates):
    pnl = sum(data['by_day'][d]['pnl'] for d in dates if d in data['by_day'])
    trades = [t for t in data['trades'] if t['date'] in dates]
    losses = [t for t in trades if t['total_dollars'] < 0]
    wins = [t for t in trades if t['total_dollars'] > 0]
    return {'pnl': pnl, 'trades': len(trades), 'wins': len(wins), 'losses': losses}


def main():
    print('Loading data for all timeframes...')
    es_3m = backtest_multiday('ES', '3m', 30)
    es_4m = backtest_multiday('ES', '4m', 30)
    es_5m = backtest_multiday('ES', '5m', 30)

    nq_3m = backtest_multiday('NQ', '3m', 30)
    nq_4m = backtest_multiday('NQ', '4m', 30)
    nq_5m = backtest_multiday('NQ', '5m', 30)

    # Find common dates
    common_dates = set(es_3m['days']) & set(es_4m['days']) & set(es_5m['days'])
    common_dates = common_dates & set(nq_3m['days']) & set(nq_4m['days']) & set(nq_5m['days'])
    common_dates = sorted(common_dates)
    print(f'\nCommon trading days: {len(common_dates)}')
    print(f'Date range: {common_dates[0]} to {common_dates[-1]}')

    # Filter to common dates
    es_3m_f = filter_to_dates(es_3m, common_dates)
    es_4m_f = filter_to_dates(es_4m, common_dates)
    es_5m_f = filter_to_dates(es_5m, common_dates)

    nq_3m_f = filter_to_dates(nq_3m, common_dates)
    nq_4m_f = filter_to_dates(nq_4m, common_dates)
    nq_5m_f = filter_to_dates(nq_5m, common_dates)

    print()
    print('='*100)
    print('ES COMPARISON BY TIMEFRAME')
    print('='*100)

    print(f"{'Metric':<20} {'3-MIN':>15} {'4-MIN':>15} {'5-MIN':>15}")
    print('-'*70)
    print(f"{'Total P/L':<20} ${es_3m_f['pnl']:>13,.0f} ${es_4m_f['pnl']:>13,.0f} ${es_5m_f['pnl']:>13,.0f}")
    print(f"{'Trades':<20} {es_3m_f['trades']:>15} {es_4m_f['trades']:>15} {es_5m_f['trades']:>15}")
    print(f"{'Wins':<20} {es_3m_f['wins']:>15} {es_4m_f['wins']:>15} {es_5m_f['wins']:>15}")
    print(f"{'Losses':<20} {len(es_3m_f['losses']):>15} {len(es_4m_f['losses']):>15} {len(es_5m_f['losses']):>15}")

    wr_3 = es_3m_f['wins']/es_3m_f['trades']*100 if es_3m_f['trades'] else 0
    wr_4 = es_4m_f['wins']/es_4m_f['trades']*100 if es_4m_f['trades'] else 0
    wr_5 = es_5m_f['wins']/es_5m_f['trades']*100 if es_5m_f['trades'] else 0
    print(f"{'Win Rate':<20} {wr_3:>14.1f}% {wr_4:>14.1f}% {wr_5:>14.1f}%")

    loss_pnl_3 = sum(t['total_dollars'] for t in es_3m_f['losses'])
    loss_pnl_4 = sum(t['total_dollars'] for t in es_4m_f['losses'])
    loss_pnl_5 = sum(t['total_dollars'] for t in es_5m_f['losses'])
    print(f"{'Total Loss $':<20} ${loss_pnl_3:>13,.0f} ${loss_pnl_4:>13,.0f} ${loss_pnl_5:>13,.0f}")

    print()
    print('='*100)
    print('NQ COMPARISON BY TIMEFRAME')
    print('='*100)

    print(f"{'Metric':<20} {'3-MIN':>15} {'4-MIN':>15} {'5-MIN':>15}")
    print('-'*70)
    print(f"{'Total P/L':<20} ${nq_3m_f['pnl']:>13,.0f} ${nq_4m_f['pnl']:>13,.0f} ${nq_5m_f['pnl']:>13,.0f}")
    print(f"{'Trades':<20} {nq_3m_f['trades']:>15} {nq_4m_f['trades']:>15} {nq_5m_f['trades']:>15}")
    print(f"{'Wins':<20} {nq_3m_f['wins']:>15} {nq_4m_f['wins']:>15} {nq_5m_f['wins']:>15}")
    print(f"{'Losses':<20} {len(nq_3m_f['losses']):>15} {len(nq_4m_f['losses']):>15} {len(nq_5m_f['losses']):>15}")

    wr_3 = nq_3m_f['wins']/nq_3m_f['trades']*100 if nq_3m_f['trades'] else 0
    wr_4 = nq_4m_f['wins']/nq_4m_f['trades']*100 if nq_4m_f['trades'] else 0
    wr_5 = nq_5m_f['wins']/nq_5m_f['trades']*100 if nq_5m_f['trades'] else 0
    print(f"{'Win Rate':<20} {wr_3:>14.1f}% {wr_4:>14.1f}% {wr_5:>14.1f}%")

    loss_pnl_3 = sum(t['total_dollars'] for t in nq_3m_f['losses'])
    loss_pnl_4 = sum(t['total_dollars'] for t in nq_4m_f['losses'])
    loss_pnl_5 = sum(t['total_dollars'] for t in nq_5m_f['losses'])
    print(f"{'Total Loss $':<20} ${loss_pnl_3:>13,.0f} ${loss_pnl_4:>13,.0f} ${loss_pnl_5:>13,.0f}")

    print()
    print('='*100)
    print('COMBINED TOTALS')
    print('='*100)
    total_3 = es_3m_f['pnl'] + nq_3m_f['pnl']
    total_4 = es_4m_f['pnl'] + nq_4m_f['pnl']
    total_5 = es_5m_f['pnl'] + nq_5m_f['pnl']
    print(f"{'Metric':<20} {'3-MIN':>15} {'4-MIN':>15} {'5-MIN':>15}")
    print('-'*70)
    print(f"{'ES + NQ P/L':<20} ${total_3:>13,.0f} ${total_4:>13,.0f} ${total_5:>13,.0f}")

    trades_3 = es_3m_f['trades'] + nq_3m_f['trades']
    trades_4 = es_4m_f['trades'] + nq_4m_f['trades']
    trades_5 = es_5m_f['trades'] + nq_5m_f['trades']
    print(f"{'Total Trades':<20} {trades_3:>15} {trades_4:>15} {trades_5:>15}")

    wins_3 = es_3m_f['wins'] + nq_3m_f['wins']
    wins_4 = es_4m_f['wins'] + nq_4m_f['wins']
    wins_5 = es_5m_f['wins'] + nq_5m_f['wins']
    wr_3 = wins_3/trades_3*100 if trades_3 else 0
    wr_4 = wins_4/trades_4*100 if trades_4 else 0
    wr_5 = wins_5/trades_5*100 if trades_5 else 0
    print(f"{'Win Rate':<20} {wr_3:>14.1f}% {wr_4:>14.1f}% {wr_5:>14.1f}%")

    losses_3 = len(es_3m_f['losses']) + len(nq_3m_f['losses'])
    losses_4 = len(es_4m_f['losses']) + len(nq_4m_f['losses'])
    losses_5 = len(es_5m_f['losses']) + len(nq_5m_f['losses'])
    print(f"{'Total Losses':<20} {losses_3:>15} {losses_4:>15} {losses_5:>15}")

    loss_total_3 = sum(t['total_dollars'] for t in es_3m_f['losses']) + sum(t['total_dollars'] for t in nq_3m_f['losses'])
    loss_total_4 = sum(t['total_dollars'] for t in es_4m_f['losses']) + sum(t['total_dollars'] for t in nq_4m_f['losses'])
    loss_total_5 = sum(t['total_dollars'] for t in es_5m_f['losses']) + sum(t['total_dollars'] for t in nq_5m_f['losses'])
    print(f"{'Total Loss $':<20} ${loss_total_3:>13,.0f} ${loss_total_4:>13,.0f} ${loss_total_5:>13,.0f}")

    print()
    print('='*100)
    print('ES LOSING TRADES - SIDE BY SIDE')
    print('='*100)
    print(f"{'Date':<12} {'3-MIN':<30} {'4-MIN':<30} {'5-MIN':<30}")
    print('-'*100)

    for d in common_dates:
        losses_3 = [t for t in es_3m_f['losses'] if t['date'] == d]
        losses_4 = [t for t in es_4m_f['losses'] if t['date'] == d]
        losses_5 = [t for t in es_5m_f['losses'] if t['date'] == d]

        max_len = max(len(losses_3), len(losses_4), len(losses_5))
        if max_len == 0:
            continue

        for i in range(max_len):
            date_str = str(d) if i == 0 else ''

            l3 = losses_3[i] if i < len(losses_3) else None
            l4 = losses_4[i] if i < len(losses_4) else None
            l5 = losses_5[i] if i < len(losses_5) else None

            s3 = f"{l3['entry_time'].strftime('%H:%M')} {l3['entry_type'][:4]} ${l3['total_dollars']:+,.0f}" if l3 else ''
            s4 = f"{l4['entry_time'].strftime('%H:%M')} {l4['entry_type'][:4]} ${l4['total_dollars']:+,.0f}" if l4 else ''
            s5 = f"{l5['entry_time'].strftime('%H:%M')} {l5['entry_type'][:4]} ${l5['total_dollars']:+,.0f}" if l5 else ''

            print(f"{date_str:<12} {s3:<30} {s4:<30} {s5:<30}")

    print()
    print('='*100)
    print('NQ LOSING TRADES - SIDE BY SIDE')
    print('='*100)
    print(f"{'Date':<12} {'3-MIN':<30} {'4-MIN':<30} {'5-MIN':<30}")
    print('-'*100)

    for d in common_dates:
        losses_3 = [t for t in nq_3m_f['losses'] if t['date'] == d]
        losses_4 = [t for t in nq_4m_f['losses'] if t['date'] == d]
        losses_5 = [t for t in nq_5m_f['losses'] if t['date'] == d]

        max_len = max(len(losses_3), len(losses_4), len(losses_5))
        if max_len == 0:
            continue

        for i in range(max_len):
            date_str = str(d) if i == 0 else ''

            l3 = losses_3[i] if i < len(losses_3) else None
            l4 = losses_4[i] if i < len(losses_4) else None
            l5 = losses_5[i] if i < len(losses_5) else None

            s3 = f"{l3['entry_time'].strftime('%H:%M')} {l3['entry_type'][:4]} ${l3['total_dollars']:+,.0f}" if l3 else ''
            s4 = f"{l4['entry_time'].strftime('%H:%M')} {l4['entry_type'][:4]} ${l4['total_dollars']:+,.0f}" if l4 else ''
            s5 = f"{l5['entry_time'].strftime('%H:%M')} {l5['entry_type'][:4]} ${l5['total_dollars']:+,.0f}" if l5 else ''

            print(f"{date_str:<12} {s3:<30} {s4:<30} {s5:<30}")

    # Biggest losses comparison
    print()
    print('='*100)
    print('TOP 5 BIGGEST LOSSES BY TIMEFRAME')
    print('='*100)

    all_losses_3 = sorted(es_3m_f['losses'] + nq_3m_f['losses'], key=lambda x: x['total_dollars'])[:5]
    all_losses_4 = sorted(es_4m_f['losses'] + nq_4m_f['losses'], key=lambda x: x['total_dollars'])[:5]
    all_losses_5 = sorted(es_5m_f['losses'] + nq_5m_f['losses'], key=lambda x: x['total_dollars'])[:5]

    print('\n3-MIN Biggest Losses:')
    for l in all_losses_3:
        sym = 'ES' if l in es_3m_f['losses'] else 'NQ'
        print(f"  {l['date']} {l['entry_time'].strftime('%H:%M')} {sym} {l['entry_type']}: ${l['total_dollars']:+,.0f} (Risk: {l['risk']:.1f} pts)")

    print('\n4-MIN Biggest Losses:')
    for l in all_losses_4:
        sym = 'ES' if l in es_4m_f['losses'] else 'NQ'
        print(f"  {l['date']} {l['entry_time'].strftime('%H:%M')} {sym} {l['entry_type']}: ${l['total_dollars']:+,.0f} (Risk: {l['risk']:.1f} pts)")

    print('\n5-MIN Biggest Losses:')
    for l in all_losses_5:
        sym = 'ES' if l in es_5m_f['losses'] else 'NQ'
        print(f"  {l['date']} {l['entry_time'].strftime('%H:%M')} {sym} {l['entry_type']}: ${l['total_dollars']:+,.0f} (Risk: {l['risk']:.1f} pts)")


if __name__ == "__main__":
    main()
