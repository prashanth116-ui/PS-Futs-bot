"""Analyze if breakeven at 2R helps specifically on losing days."""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10


def analyze_be_losing_days(symbol='ES', days=30, contracts=3):
    """Analyze breakeven impact on losing days only."""

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25
    min_risk_pts = 1.5 if symbol == 'ES' else 6.0 if symbol == 'NQ' else 1.5

    print(f'Fetching {symbol} 3m data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=10000)

    if not all_bars:
        print('No data available')
        return

    # Get trading dates
    all_dates = sorted(set(b.timestamp.date() for b in all_bars), reverse=True)
    trading_dates = []
    for d in all_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == d]
        rth_bars = [b for b in day_bars if dt_time(9, 30) <= b.timestamp.time() <= dt_time(16, 0)]
        if len(rth_bars) >= 50:
            trading_dates.append(d)
        if len(trading_dates) >= days:
            break

    trading_dates = sorted(trading_dates)

    print(f'Found {len(trading_dates)} trading days')
    print()

    # First pass: identify losing days (without breakeven)
    day_results = []

    for target_date in trading_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == target_date]
        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Run WITHOUT breakeven
        trades_no_be = run_session_v10(
            session_bars, all_bars,
            tick_size=tick_size, tick_value=tick_value, contracts=contracts,
            min_risk_pts=min_risk_pts,
            enable_creation_entry=True, enable_retracement_entry=True, enable_bos_entry=True,
            retracement_morning_only=True, t1_fixed_4r=True,
            breakeven_at_2r=False,
        )

        # Run WITH breakeven
        trades_with_be = run_session_v10(
            session_bars, all_bars,
            tick_size=tick_size, tick_value=tick_value, contracts=contracts,
            min_risk_pts=min_risk_pts,
            enable_creation_entry=True, enable_retracement_entry=True, enable_bos_entry=True,
            retracement_morning_only=True, t1_fixed_4r=True,
            breakeven_at_2r=True,
        )

        pnl_no_be = sum(r['total_dollars'] for r in trades_no_be)
        pnl_with_be = sum(r['total_dollars'] for r in trades_with_be)
        stops_no_be = sum(1 for r in trades_no_be if r['was_stopped'])
        stops_with_be = sum(1 for r in trades_with_be if r['was_stopped'])

        day_results.append({
            'date': target_date,
            'pnl_no_be': pnl_no_be,
            'pnl_with_be': pnl_with_be,
            'is_losing': pnl_no_be < 0,
            'stops_no_be': stops_no_be,
            'stops_with_be': stops_with_be,
        })

    # Analyze by day type
    print('='*100)
    print(f'{symbol} BREAKEVEN ANALYSIS BY DAY TYPE')
    print('='*100)
    print()

    # Losing days analysis
    losing_days = [d for d in day_results if d['is_losing']]
    winning_days = [d for d in day_results if not d['is_losing']]

    print('LOSING DAYS (without BE):')
    print('-'*100)
    print(f'{"Date":<12} {"NO BE P/L":>12} {"WITH BE P/L":>12} {"Diff":>10} {"BE Helps?":>12}')
    print('-'*100)

    total_no_be_losing = 0
    total_with_be_losing = 0

    for d in losing_days:
        diff = d['pnl_with_be'] - d['pnl_no_be']
        helps = 'YES' if diff > 0 else 'NO'
        print(f'{d["date"]} ${d["pnl_no_be"]:>+10,.0f} ${d["pnl_with_be"]:>+10,.0f} ${diff:>+8,.0f} {helps:>12}')
        total_no_be_losing += d['pnl_no_be']
        total_with_be_losing += d['pnl_with_be']

    print('-'*100)
    diff_losing = total_with_be_losing - total_no_be_losing
    print(f'{"TOTAL":<12} ${total_no_be_losing:>+10,.0f} ${total_with_be_losing:>+10,.0f} ${diff_losing:>+8,.0f}')
    print()

    # Winning days analysis
    print('WINNING DAYS (without BE):')
    print('-'*100)
    print(f'{"Date":<12} {"NO BE P/L":>12} {"WITH BE P/L":>12} {"Diff":>10} {"BE Helps?":>12}')
    print('-'*100)

    total_no_be_winning = 0
    total_with_be_winning = 0

    for d in winning_days:
        diff = d['pnl_with_be'] - d['pnl_no_be']
        helps = 'YES' if diff > 0 else 'NO'
        print(f'{d["date"]} ${d["pnl_no_be"]:>+10,.0f} ${d["pnl_with_be"]:>+10,.0f} ${diff:>+8,.0f} {helps:>12}')
        total_no_be_winning += d['pnl_no_be']
        total_with_be_winning += d['pnl_with_be']

    print('-'*100)
    diff_winning = total_with_be_winning - total_no_be_winning
    print(f'{"TOTAL":<12} ${total_no_be_winning:>+10,.0f} ${total_with_be_winning:>+10,.0f} ${diff_winning:>+8,.0f}')
    print()

    # Summary
    print('='*100)
    print('SUMMARY')
    print('='*100)
    print()
    print(f'{"Day Type":<20} {"Days":>6} {"NO BE Total":>15} {"WITH BE Total":>15} {"BE Impact":>12}')
    print('-'*70)
    print(f'{"Losing Days":<20} {len(losing_days):>6} ${total_no_be_losing:>+13,.0f} ${total_with_be_losing:>+13,.0f} ${diff_losing:>+10,.0f}')
    print(f'{"Winning Days":<20} {len(winning_days):>6} ${total_no_be_winning:>+13,.0f} ${total_with_be_winning:>+13,.0f} ${diff_winning:>+10,.0f}')
    print('-'*70)

    total_no_be = total_no_be_losing + total_no_be_winning
    total_with_be = total_with_be_losing + total_with_be_winning
    total_diff = total_with_be - total_no_be
    print(f'{"ALL DAYS":<20} {len(day_results):>6} ${total_no_be:>+13,.0f} ${total_with_be:>+13,.0f} ${total_diff:>+10,.0f}')
    print()

    # Hypothetical: BE only on losing days
    hypothetical_pnl = total_with_be_losing + total_no_be_winning
    hypothetical_diff = hypothetical_pnl - total_no_be

    print('='*100)
    print('HYPOTHETICAL: If we could apply BE only on losing days')
    print('='*100)
    print(f'  Losing days with BE:    ${total_with_be_losing:>+13,.0f}')
    print(f'  Winning days without BE: ${total_no_be_winning:>+13,.0f}')
    print(f'  HYPOTHETICAL TOTAL:     ${hypothetical_pnl:>+13,.0f}')
    print(f'  vs Original (no BE):    ${total_no_be:>+13,.0f}')
    print(f'  IMPROVEMENT:            ${hypothetical_diff:>+13,.0f}')
    print()

    # Does BE help on losing days?
    be_helps_losing = sum(1 for d in losing_days if d['pnl_with_be'] > d['pnl_no_be'])
    print(f'BE helps on {be_helps_losing}/{len(losing_days)} losing days ({be_helps_losing/len(losing_days)*100:.0f}%)')
    print('='*100)


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    analyze_be_losing_days(symbol=symbol, days=days)
