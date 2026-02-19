"""
Drawdown Analysis - Identify sources of losses for strategy refinement
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from collections import defaultdict
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_equity import run_session_v10_equity
from runners.run_v10_dual_entry import run_session_v10


def analyze_futures(bars, symbol, days, tick_size, tick_value, contracts=3):
    """Analyze futures trades for drawdown sources."""
    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:] if len(all_dates) >= days else all_dates

    min_risk = 1.5 if symbol in ['ES', 'MES'] else 6.0
    max_bos_risk = 8.0 if symbol in ['ES', 'MES'] else 20.0

    all_trades = []

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
            r['date'] = target_date
            r['symbol'] = symbol
            all_trades.append(r)

    return all_trades


def analyze_equity(bars, symbol, days):
    """Analyze equity trades for drawdown sources."""
    all_dates = sorted(set(b.timestamp.date() for b in bars))
    recent_dates = all_dates[-days:] if len(all_dates) >= days else all_dates

    all_trades = []

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
            r['date'] = target_date
            r['symbol'] = symbol
            all_trades.append(r)

    return all_trades


def main():
    days = 30

    print("=" * 80)
    print("DRAWDOWN SOURCE ANALYSIS - V10.5")
    print("=" * 80)

    print("\nFetching data...")
    es_bars = fetch_futures_bars('ES', interval='3m', n_bars=15000)
    nq_bars = fetch_futures_bars('NQ', interval='3m', n_bars=15000)
    spy_bars = fetch_futures_bars('SPY', interval='3m', n_bars=15000)
    qqq_bars = fetch_futures_bars('QQQ', interval='3m', n_bars=15000)

    all_trades = []

    print("Analyzing ES...")
    if es_bars:
        all_trades.extend(analyze_futures(es_bars, 'ES', days, 0.25, 12.50))

    print("Analyzing NQ...")
    if nq_bars:
        all_trades.extend(analyze_futures(nq_bars, 'NQ', days, 0.25, 5.00))

    print("Analyzing SPY...")
    if spy_bars:
        all_trades.extend(analyze_equity(spy_bars, 'SPY', days))

    print("Analyzing QQQ...")
    if qqq_bars:
        all_trades.extend(analyze_equity(qqq_bars, 'QQQ', days))

    # Separate winners and losers
    winners = [t for t in all_trades if t['total_dollars'] > 0]
    losers = [t for t in all_trades if t['total_dollars'] <= 0]

    print(f"\nTotal trades: {len(all_trades)}")
    print(f"Winners: {len(winners)} ({len(winners)/len(all_trades)*100:.1f}%)")
    print(f"Losers: {len(losers)} ({len(losers)/len(all_trades)*100:.1f}%)")

    # 1. ANALYSIS BY ENTRY TYPE
    print("\n" + "=" * 80)
    print("1. LOSS ANALYSIS BY ENTRY TYPE")
    print("=" * 80)

    entry_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'win_pnl': 0, 'loss_pnl': 0})
    for t in all_trades:
        entry_type = t.get('entry_type', 'UNKNOWN')
        if t['total_dollars'] > 0:
            entry_stats[entry_type]['wins'] += 1
            entry_stats[entry_type]['win_pnl'] += t['total_dollars']
        else:
            entry_stats[entry_type]['losses'] += 1
            entry_stats[entry_type]['loss_pnl'] += t['total_dollars']

    print(f"\n{'Entry Type':<20} {'Wins':>6} {'Losses':>7} {'Win%':>7} {'Win P/L':>12} {'Loss P/L':>12} {'Net':>12}")
    print("-" * 80)
    for etype, stats in sorted(entry_stats.items()):
        total = stats['wins'] + stats['losses']
        win_rate = stats['wins'] / total * 100 if total > 0 else 0
        net = stats['win_pnl'] + stats['loss_pnl']
        print(f"{etype:<20} {stats['wins']:>6} {stats['losses']:>7} {win_rate:>6.1f}% ${stats['win_pnl']:>10,.0f} ${stats['loss_pnl']:>10,.0f} ${net:>10,.0f}")

    # 2. ANALYSIS BY TIME OF DAY
    print("\n" + "=" * 80)
    print("2. LOSS ANALYSIS BY TIME OF DAY")
    print("=" * 80)

    time_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'win_pnl': 0, 'loss_pnl': 0})
    for t in all_trades:
        hour = t.get('entry_time', dt_time(9, 30)).hour
        time_bucket = f"{hour:02d}:00-{hour:02d}:59"
        if t['total_dollars'] > 0:
            time_stats[time_bucket]['wins'] += 1
            time_stats[time_bucket]['win_pnl'] += t['total_dollars']
        else:
            time_stats[time_bucket]['losses'] += 1
            time_stats[time_bucket]['loss_pnl'] += t['total_dollars']

    print(f"\n{'Time Window':<15} {'Wins':>6} {'Losses':>7} {'Win%':>7} {'Win P/L':>12} {'Loss P/L':>12} {'Net':>12}")
    print("-" * 80)
    for twindow in sorted(time_stats.keys()):
        stats = time_stats[twindow]
        total = stats['wins'] + stats['losses']
        win_rate = stats['wins'] / total * 100 if total > 0 else 0
        net = stats['win_pnl'] + stats['loss_pnl']
        print(f"{twindow:<15} {stats['wins']:>6} {stats['losses']:>7} {win_rate:>6.1f}% ${stats['win_pnl']:>10,.0f} ${stats['loss_pnl']:>10,.0f} ${net:>10,.0f}")

    # 3. ANALYSIS BY DAY OF WEEK
    print("\n" + "=" * 80)
    print("3. LOSS ANALYSIS BY DAY OF WEEK")
    print("=" * 80)

    dow_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    dow_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'win_pnl': 0, 'loss_pnl': 0})
    for t in all_trades:
        dow = t['date'].weekday()
        dow_name = dow_names[dow] if dow < 5 else 'Weekend'
        if t['total_dollars'] > 0:
            dow_stats[dow_name]['wins'] += 1
            dow_stats[dow_name]['win_pnl'] += t['total_dollars']
        else:
            dow_stats[dow_name]['losses'] += 1
            dow_stats[dow_name]['loss_pnl'] += t['total_dollars']

    print(f"\n{'Day':<12} {'Wins':>6} {'Losses':>7} {'Win%':>7} {'Win P/L':>12} {'Loss P/L':>12} {'Net':>12}")
    print("-" * 80)
    for day in dow_names:
        if day in dow_stats:
            stats = dow_stats[day]
            total = stats['wins'] + stats['losses']
            win_rate = stats['wins'] / total * 100 if total > 0 else 0
            net = stats['win_pnl'] + stats['loss_pnl']
            print(f"{day:<12} {stats['wins']:>6} {stats['losses']:>7} {win_rate:>6.1f}% ${stats['win_pnl']:>10,.0f} ${stats['loss_pnl']:>10,.0f} ${net:>10,.0f}")

    # 4. ANALYSIS BY SYMBOL
    print("\n" + "=" * 80)
    print("4. LOSS ANALYSIS BY SYMBOL")
    print("=" * 80)

    symbol_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'win_pnl': 0, 'loss_pnl': 0, 'max_loss': 0})
    for t in all_trades:
        symbol = t['symbol']
        if t['total_dollars'] > 0:
            symbol_stats[symbol]['wins'] += 1
            symbol_stats[symbol]['win_pnl'] += t['total_dollars']
        else:
            symbol_stats[symbol]['losses'] += 1
            symbol_stats[symbol]['loss_pnl'] += t['total_dollars']
            if t['total_dollars'] < symbol_stats[symbol]['max_loss']:
                symbol_stats[symbol]['max_loss'] = t['total_dollars']

    print(f"\n{'Symbol':<8} {'Wins':>6} {'Losses':>7} {'Win%':>7} {'Avg Win':>10} {'Avg Loss':>10} {'Max Loss':>10}")
    print("-" * 80)
    for symbol in ['ES', 'NQ', 'SPY', 'QQQ']:
        if symbol in symbol_stats:
            stats = symbol_stats[symbol]
            total = stats['wins'] + stats['losses']
            win_rate = stats['wins'] / total * 100 if total > 0 else 0
            avg_win = stats['win_pnl'] / stats['wins'] if stats['wins'] > 0 else 0
            avg_loss = stats['loss_pnl'] / stats['losses'] if stats['losses'] > 0 else 0
            print(f"{symbol:<8} {stats['wins']:>6} {stats['losses']:>7} {win_rate:>6.1f}% ${avg_win:>8,.0f} ${avg_loss:>8,.0f} ${stats['max_loss']:>8,.0f}")

    # 5. CONSECUTIVE LOSSES
    print("\n" + "=" * 80)
    print("5. CONSECUTIVE LOSS PATTERNS")
    print("=" * 80)

    # Sort by date and time
    sorted_trades = sorted(all_trades, key=lambda x: (x['date'], x.get('entry_time', dt_time(9, 30))))

    consec_losses = 0
    max_consec = 0
    consec_loss_pnl = 0
    max_consec_pnl = 0

    for t in sorted_trades:
        if t['total_dollars'] <= 0:
            consec_losses += 1
            consec_loss_pnl += t['total_dollars']
            if consec_losses > max_consec:
                max_consec = consec_losses
            if consec_loss_pnl < max_consec_pnl:
                max_consec_pnl = consec_loss_pnl
        else:
            consec_losses = 0
            consec_loss_pnl = 0

    print(f"\nMax consecutive losses: {max_consec}")
    print(f"Max consecutive loss P/L: ${max_consec_pnl:,.0f}")

    # 6. LOSS SIZE DISTRIBUTION
    print("\n" + "=" * 80)
    print("6. LOSS SIZE DISTRIBUTION")
    print("=" * 80)

    loss_buckets = {
        '$0-500': 0,
        '$500-1000': 0,
        '$1000-2000': 0,
        '$2000-3000': 0,
        '$3000+': 0,
    }

    for t in losers:
        loss = abs(t['total_dollars'])
        if loss < 500:
            loss_buckets['$0-500'] += 1
        elif loss < 1000:
            loss_buckets['$500-1000'] += 1
        elif loss < 2000:
            loss_buckets['$1000-2000'] += 1
        elif loss < 3000:
            loss_buckets['$2000-3000'] += 1
        else:
            loss_buckets['$3000+'] += 1

    print(f"\n{'Loss Size':<15} {'Count':>8} {'% of Losses':>12}")
    print("-" * 40)
    for bucket, count in loss_buckets.items():
        pct = count / len(losers) * 100 if losers else 0
        print(f"{bucket:<15} {count:>8} {pct:>11.1f}%")

    # 7. LARGEST INDIVIDUAL LOSSES
    print("\n" + "=" * 80)
    print("7. TOP 10 LARGEST LOSSES")
    print("=" * 80)

    sorted_losers = sorted(losers, key=lambda x: x['total_dollars'])[:10]
    print(f"\n{'Date':<12} {'Symbol':<6} {'Entry Type':<15} {'Time':>8} {'Loss':>12}")
    print("-" * 60)
    for t in sorted_losers:
        entry_time = t.get('entry_time', dt_time(9, 30))
        print(f"{t['date']} {t['symbol']:<6} {t.get('entry_type', 'UNK'):<15} {entry_time.strftime('%H:%M'):>8} ${t['total_dollars']:>10,.0f}")

    # 8. RECOMMENDATIONS
    print("\n" + "=" * 80)
    print("8. REFINEMENT RECOMMENDATIONS")
    print("=" * 80)

    recommendations = []

    # Check worst entry type
    worst_entry = min(entry_stats.items(), key=lambda x: (x[1]['win_pnl'] + x[1]['loss_pnl']) / (x[1]['wins'] + x[1]['losses']) if (x[1]['wins'] + x[1]['losses']) > 5 else float('inf'))
    if worst_entry[1]['wins'] + worst_entry[1]['losses'] > 5:
        total = worst_entry[1]['wins'] + worst_entry[1]['losses']
        win_rate = worst_entry[1]['wins'] / total * 100
        if win_rate < 50:
            recommendations.append(f"Consider disabling or tightening {worst_entry[0]} entry type (win rate: {win_rate:.1f}%)")

    # Check worst time window
    for twindow, stats in time_stats.items():
        total = stats['wins'] + stats['losses']
        if total >= 5:
            win_rate = stats['wins'] / total * 100
            net = stats['win_pnl'] + stats['loss_pnl']
            if win_rate < 45 and net < 0:
                recommendations.append(f"Consider avoiding trades during {twindow} (win rate: {win_rate:.1f}%, net: ${net:,.0f})")

    # Check worst day
    for day, stats in dow_stats.items():
        total = stats['wins'] + stats['losses']
        if total >= 5:
            win_rate = stats['wins'] / total * 100
            net = stats['win_pnl'] + stats['loss_pnl']
            if win_rate < 45:
                recommendations.append(f"Consider reducing position size on {day} (win rate: {win_rate:.1f}%)")

    # Check for large losses
    large_losses = [t for t in losers if abs(t['total_dollars']) > 2000]
    if large_losses:
        recommendations.append(f"Consider tighter risk cap - {len(large_losses)} trades lost >$2000")

    # Check consecutive loss pattern
    if max_consec >= 4:
        recommendations.append(f"Add cooldown after 3 consecutive losses (max streak: {max_consec})")

    print()
    for i, rec in enumerate(recommendations, 1):
        print(f"{i}. {rec}")

    if not recommendations:
        print("No major issues found. Strategy is well-optimized.")


if __name__ == "__main__":
    main()
