"""
TTFM Risk Bucket Analysis - Break down trade performance by risk size.

Usage:
    python -m scripts.ttfm_risk_analysis ES 70
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_ttfm import run_session_ttfm_native, SYMBOL_CONFIG, _build_daily_bars
from strategies.ttfm.signals.bias import determine_bias


def analyze_risk_buckets(symbol='ES', days=70):
    cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG['ES'])
    tick_size = cfg['tick_size']
    tick_value = cfg['tick_value']
    min_risk = cfg['min_risk']

    print(f'Fetching {symbol} data...')
    bars_15m = fetch_futures_bars(symbol=symbol, interval='15m', n_bars=10000)
    bars_1h = fetch_futures_bars(symbol=symbol, interval='1h', n_bars=10000)
    bars_daily = fetch_futures_bars(symbol=symbol, interval='1d', n_bars=500)

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

    # Run with wide open risk (1.5 - 20pts) to capture everything
    all_trades = []
    for target_date in trading_dates:
        day_15m = [b for b in bars_15m if b.timestamp.date() == target_date
                   and premarket_start <= b.timestamp.time() <= rth_end]
        day_1h = [b for b in bars_1h if b.timestamp.date() == target_date
                  and premarket_start <= b.timestamp.time() <= rth_end]
        history_daily = [b for b in bars_daily if b.timestamp.date() < target_date]
        if len(day_15m) < 10 or len(history_daily) < 2:
            continue

        results = run_session_ttfm_native(
            day_15m, day_1h, history_daily,
            tick_size=tick_size, tick_value=tick_value,
            contracts=1,  # All 1-ct for apples-to-apples comparison
            min_risk_pts=min_risk, max_risk_pts=20.0,
            t1_r_target=1, trail_r_trigger=3,
            symbol=symbol,
        )
        for r in results:
            all_trades.append({**r, 'date': target_date})

    if not all_trades:
        print('No trades found')
        return

    # Risk buckets
    buckets = [
        ('0-3 pts', 0, 3),
        ('3-5 pts', 3, 5),
        ('5-7 pts', 5, 7),
        ('7-9 pts', 7, 9),
        ('9-12 pts', 9, 12),
        ('12-15 pts', 12, 15),
        ('15+ pts', 15, 100),
    ]

    print(f'\n{"="*80}')
    print(f'{symbol} TTFM TRADE PERFORMANCE BY RISK SIZE - {len(trading_dates)} Days')
    print(f'All trades at 1 contract, 1R/3R targets')
    print(f'{"="*80}\n')

    print(f'{"Risk Bucket":<12} {"Trades":>7} {"Wins":>5} {"Losses":>7} {"WR":>6} {"Avg W":>8} {"Avg L":>8} {"Net P/L":>10} {"Expect":>8}')
    print('-' * 80)

    for label, lo, hi in buckets:
        trades = [t for t in all_trades if lo <= t['risk'] < hi]
        if not trades:
            print(f'{label:<12} {"0":>7}')
            continue
        wins = [t for t in trades if t['total_dollars'] > 0]
        losses = [t for t in trades if t['total_dollars'] < 0]
        flat = [t for t in trades if t['total_dollars'] == 0]
        wr = len(wins) / len(trades) * 100 if trades else 0
        avg_win = sum(t['total_dollars'] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t['total_dollars'] for t in losses) / len(losses) if losses else 0
        net = sum(t['total_dollars'] for t in trades)
        expectancy = net / len(trades)

        print(f'{label:<12} {len(trades):>7} {len(wins):>5} {len(losses):>7} {wr:>5.1f}% ${avg_win:>+7,.0f} ${avg_loss:>+7,.0f} ${net:>+9,.0f} ${expectancy:>+7,.0f}')

    print('-' * 80)
    total_w = sum(1 for t in all_trades if t['total_dollars'] > 0)
    total_l = sum(1 for t in all_trades if t['total_dollars'] < 0)
    total_pnl = sum(t['total_dollars'] for t in all_trades)
    print(f'{"TOTAL":<12} {len(all_trades):>7} {total_w:>5} {total_l:>7} {total_w/len(all_trades)*100:>5.1f}%                    ${total_pnl:>+9,.0f} ${total_pnl/len(all_trades):>+7,.0f}')

    # Time-of-day analysis
    print(f'\n{"="*80}')
    print(f'PERFORMANCE BY TIME OF DAY')
    print(f'{"="*80}\n')

    time_buckets = [
        ('04:00-06:00', dt_time(4, 0), dt_time(6, 0)),
        ('06:00-08:00', dt_time(6, 0), dt_time(8, 0)),
        ('08:00-10:00', dt_time(8, 0), dt_time(10, 0)),
        ('10:00-12:00', dt_time(10, 0), dt_time(12, 0)),
        ('12:00-14:00', dt_time(12, 0), dt_time(14, 0)),
        ('14:00-16:00', dt_time(14, 0), dt_time(16, 0)),
    ]

    print(f'{"Time":<14} {"Trades":>7} {"Wins":>5} {"Losses":>7} {"WR":>6} {"Net P/L":>10} {"Expect":>8}')
    print('-' * 65)

    for label, lo, hi in time_buckets:
        trades = [t for t in all_trades if lo <= t['entry_time'].time() < hi]
        if not trades:
            print(f'{label:<14} {"0":>7}')
            continue
        wins = sum(1 for t in trades if t['total_dollars'] > 0)
        losses = sum(1 for t in trades if t['total_dollars'] < 0)
        wr = wins / len(trades) * 100
        net = sum(t['total_dollars'] for t in trades)
        expect = net / len(trades)
        print(f'{label:<14} {len(trades):>7} {wins:>5} {losses:>7} {wr:>5.1f}% ${net:>+9,.0f} ${expect:>+7,.0f}')

    # Direction analysis
    print(f'\n{"="*80}')
    print(f'PERFORMANCE BY DIRECTION')
    print(f'{"="*80}\n')

    for direction in ['BULLISH', 'BEARISH']:
        trades = [t for t in all_trades if t['direction'] == direction]
        if not trades:
            continue
        wins = sum(1 for t in trades if t['total_dollars'] > 0)
        losses = sum(1 for t in trades if t['total_dollars'] < 0)
        wr = wins / len(trades) * 100
        net = sum(t['total_dollars'] for t in trades)

        print(f'{direction}: {len(trades)} trades, {wins}W/{losses}L, {wr:.1f}% WR, ${net:+,.0f}')

        # By risk bucket within direction
        for label, lo, hi in buckets:
            dt = [t for t in trades if lo <= t['risk'] < hi]
            if not dt:
                continue
            dw = sum(1 for t in dt if t['total_dollars'] > 0)
            dl = sum(1 for t in dt if t['total_dollars'] < 0)
            dwr = dw / len(dt) * 100
            dpnl = sum(t['total_dollars'] for t in dt)
            print(f'  {label:<10}: {len(dt):>3} trades, {dw}W/{dl}L, {dwr:>5.1f}% WR, ${dpnl:>+7,.0f}')

    # Trade sequence analysis (1st trade of day vs subsequent)
    print(f'\n{"="*80}')
    print(f'1ST TRADE OF DAY vs SUBSEQUENT')
    print(f'{"="*80}\n')

    from collections import defaultdict
    by_date = defaultdict(list)
    for t in all_trades:
        by_date[t['date']].append(t)

    first_trades = []
    subsequent_trades = []
    for d in sorted(by_date):
        trades = sorted(by_date[d], key=lambda x: x['entry_time'])
        if trades:
            first_trades.append(trades[0])
            subsequent_trades.extend(trades[1:])

    for label, group in [('1st trade/day', first_trades), ('Subsequent', subsequent_trades)]:
        if not group:
            continue
        wins = sum(1 for t in group if t['total_dollars'] > 0)
        losses = sum(1 for t in group if t['total_dollars'] < 0)
        wr = wins / len(group) * 100
        net = sum(t['total_dollars'] for t in group)
        expect = net / len(group)
        print(f'{label:<16}: {len(group)} trades, {wins}W/{losses}L, {wr:.1f}% WR, ${net:+,.0f}, ${expect:+,.0f}/trade')

    # Exit type analysis
    print(f'\n{"="*80}')
    print(f'EXIT TYPE BREAKDOWN')
    print(f'{"="*80}\n')

    exit_types = defaultdict(lambda: {'count': 0, 'pnl': 0})
    for t in all_trades:
        exit_str = '+'.join(sorted(set(e['type'] for e in t['exits'])))
        exit_types[exit_str]['count'] += 1
        exit_types[exit_str]['pnl'] += t['total_dollars']

    print(f'{"Exit Type":<20} {"Count":>6} {"Net P/L":>10} {"Avg":>8}')
    print('-' * 50)
    for etype, data in sorted(exit_types.items(), key=lambda x: -x[1]['count']):
        avg = data['pnl'] / data['count']
        print(f'{etype:<20} {data["count"]:>6} ${data["pnl"]:>+9,.0f} ${avg:>+7,.0f}')


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 70
    analyze_risk_buckets(symbol, days)
