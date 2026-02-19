"""Compare V10 strategy with and without breakeven at 2R."""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10


def run_comparison(symbol='ES', days=30, contracts=3):
    """Run V10 backtest with and without breakeven at 2R."""

    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25
    min_risk_pts = 1.5 if symbol == 'ES' else 6.0 if symbol == 'NQ' else 1.5

    print(f'Fetching {symbol} 3m data for {days}-day comparison...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=10000)

    if not all_bars:
        print('No data available')
        return

    # Get unique trading dates
    all_dates = sorted(set(b.timestamp.date() for b in all_bars), reverse=True)

    # Filter to trading days only
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
    print(f'Date range: {trading_dates[0]} to {trading_dates[-1]}')
    print()

    # Track results for both modes
    results_no_be = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0, 'stops': 0, 'daily': []}
    results_with_be = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0, 'stops': 0, 'be_exits': 0, 'daily': []}

    print('='*100)
    print(f'{symbol} V10 BREAKEVEN COMPARISON - {len(trading_dates)} Days - {contracts} Contracts')
    print('='*100)
    print()
    print(f'{"Date":<12} {"NO BE P/L":>12} {"WITH BE P/L":>12} {"Diff":>10} {"NO BE Stops":>12} {"BE Stops":>10} {"BE Exits":>10}')
    print('-'*100)

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

        # Run WITH breakeven at 2R
        trades_with_be = run_session_v10(
            session_bars, all_bars,
            tick_size=tick_size, tick_value=tick_value, contracts=contracts,
            min_risk_pts=min_risk_pts,
            enable_creation_entry=True, enable_retracement_entry=True, enable_bos_entry=True,
            retracement_morning_only=True, t1_fixed_4r=True,
            breakeven_at_2r=True,
        )

        # Calculate daily stats - NO BE
        day_pnl_no_be = sum(r['total_dollars'] for r in trades_no_be)
        day_wins_no_be = sum(1 for r in trades_no_be if r['total_dollars'] > 0)
        day_losses_no_be = sum(1 for r in trades_no_be if r['total_dollars'] < 0)
        day_stops_no_be = sum(1 for r in trades_no_be if r['was_stopped'])

        results_no_be['trades'] += len(trades_no_be)
        results_no_be['wins'] += day_wins_no_be
        results_no_be['losses'] += day_losses_no_be
        results_no_be['pnl'] += day_pnl_no_be
        results_no_be['stops'] += day_stops_no_be
        results_no_be['daily'].append({'date': target_date, 'pnl': day_pnl_no_be})

        # Calculate daily stats - WITH BE
        day_pnl_with_be = sum(r['total_dollars'] for r in trades_with_be)
        day_wins_with_be = sum(1 for r in trades_with_be if r['total_dollars'] > 0)
        day_losses_with_be = sum(1 for r in trades_with_be if r['total_dollars'] < 0)
        day_stops_with_be = sum(1 for r in trades_with_be if r['was_stopped'])

        # Count BE exits (stop hit at entry price after 2R was touched)
        day_be_exits = 0
        for r in trades_with_be:
            for e in r['exits']:
                if e['type'] == 'STOP' and abs(e['price'] - r['entry_price']) < tick_size * 2:
                    day_be_exits += 1

        results_with_be['trades'] += len(trades_with_be)
        results_with_be['wins'] += day_wins_with_be
        results_with_be['losses'] += day_losses_with_be
        results_with_be['pnl'] += day_pnl_with_be
        results_with_be['stops'] += day_stops_with_be
        results_with_be['be_exits'] += day_be_exits
        results_with_be['daily'].append({'date': target_date, 'pnl': day_pnl_with_be})

        diff = day_pnl_with_be - day_pnl_no_be
        print(f'{target_date} ${day_pnl_no_be:>+10,.0f} ${day_pnl_with_be:>+10,.0f} ${diff:>+8,.0f} {day_stops_no_be:>12} {day_stops_with_be:>10} {day_be_exits:>10}')

    print('-'*100)
    print()

    # Summary
    print('='*100)
    print('SUMMARY COMPARISON')
    print('='*100)
    print()
    print(f'{"Metric":<30} {"WITHOUT BE":>20} {"WITH BE at 2R":>20} {"Difference":>15}')
    print('-'*85)

    print(f'{"Total Trades":<30} {results_no_be["trades"]:>20} {results_with_be["trades"]:>20}')
    print(f'{"Total Wins":<30} {results_no_be["wins"]:>20} {results_with_be["wins"]:>20} {results_with_be["wins"] - results_no_be["wins"]:>+15}')
    print(f'{"Total Losses":<30} {results_no_be["losses"]:>20} {results_with_be["losses"]:>20} {results_with_be["losses"] - results_no_be["losses"]:>+15}')

    wr_no_be = results_no_be['wins'] / results_no_be['trades'] * 100 if results_no_be['trades'] > 0 else 0
    wr_with_be = results_with_be['wins'] / results_with_be['trades'] * 100 if results_with_be['trades'] > 0 else 0
    print(f'{"Win Rate":<30} {wr_no_be:>19.1f}% {wr_with_be:>19.1f}% {wr_with_be - wr_no_be:>+14.1f}%')

    print()
    print(f'{"Total Stops Hit":<30} {results_no_be["stops"]:>20} {results_with_be["stops"]:>20} {results_with_be["stops"] - results_no_be["stops"]:>+15}')
    print(f'{"Breakeven Exits":<30} {"N/A":>20} {results_with_be["be_exits"]:>20}')
    print()

    print(f'{"Total P/L":<30} ${results_no_be["pnl"]:>+18,.0f} ${results_with_be["pnl"]:>+18,.0f} ${results_with_be["pnl"] - results_no_be["pnl"]:>+13,.0f}')

    # Daily stats
    winning_days_no_be = sum(1 for d in results_no_be['daily'] if d['pnl'] > 0)
    losing_days_no_be = sum(1 for d in results_no_be['daily'] if d['pnl'] < 0)
    winning_days_with_be = sum(1 for d in results_with_be['daily'] if d['pnl'] > 0)
    losing_days_with_be = sum(1 for d in results_with_be['daily'] if d['pnl'] < 0)

    print()
    print(f'{"Winning Days":<30} {winning_days_no_be:>20} {winning_days_with_be:>20} {winning_days_with_be - winning_days_no_be:>+15}')
    print(f'{"Losing Days":<30} {losing_days_no_be:>20} {losing_days_with_be:>20} {losing_days_with_be - losing_days_no_be:>+15}')

    day_wr_no_be = winning_days_no_be / len(results_no_be['daily']) * 100 if results_no_be['daily'] else 0
    day_wr_with_be = winning_days_with_be / len(results_with_be['daily']) * 100 if results_with_be['daily'] else 0
    print(f'{"Day Win Rate":<30} {day_wr_no_be:>19.1f}% {day_wr_with_be:>19.1f}% {day_wr_with_be - day_wr_no_be:>+14.1f}%')

    # Profit factor
    gp_no_be = sum(d['pnl'] for d in results_no_be['daily'] if d['pnl'] > 0)
    gl_no_be = abs(sum(d['pnl'] for d in results_no_be['daily'] if d['pnl'] < 0))
    pf_no_be = gp_no_be / gl_no_be if gl_no_be > 0 else float('inf')

    gp_with_be = sum(d['pnl'] for d in results_with_be['daily'] if d['pnl'] > 0)
    gl_with_be = abs(sum(d['pnl'] for d in results_with_be['daily'] if d['pnl'] < 0))
    pf_with_be = gp_with_be / gl_with_be if gl_with_be > 0 else float('inf')

    print()
    print(f'{"Gross Profit":<30} ${gp_no_be:>+18,.0f} ${gp_with_be:>+18,.0f} ${gp_with_be - gp_no_be:>+13,.0f}')
    print(f'{"Gross Loss":<30} ${gl_no_be:>+18,.0f} ${gl_with_be:>+18,.0f} ${gl_with_be - gl_no_be:>+13,.0f}')
    print(f'{"Profit Factor":<30} {pf_no_be:>20.2f} {pf_with_be:>20.2f} {pf_with_be - pf_no_be:>+15.2f}')

    # Max drawdown
    peak_no_be = 0
    dd_no_be = 0
    cum_no_be = 0
    for d in results_no_be['daily']:
        cum_no_be += d['pnl']
        if cum_no_be > peak_no_be:
            peak_no_be = cum_no_be
        dd = peak_no_be - cum_no_be
        if dd > dd_no_be:
            dd_no_be = dd

    peak_with_be = 0
    dd_with_be = 0
    cum_with_be = 0
    for d in results_with_be['daily']:
        cum_with_be += d['pnl']
        if cum_with_be > peak_with_be:
            peak_with_be = cum_with_be
        dd = peak_with_be - cum_with_be
        if dd > dd_with_be:
            dd_with_be = dd

    print()
    print(f'{"Max Drawdown":<30} ${dd_no_be:>18,.0f} ${dd_with_be:>18,.0f} ${dd_with_be - dd_no_be:>+13,.0f}')

    print()
    print('='*100)
    print('CONCLUSION')
    print('='*100)
    diff_pnl = results_with_be['pnl'] - results_no_be['pnl']
    diff_stops = results_with_be['stops'] - results_no_be['stops']
    if diff_pnl > 0:
        print(f'Breakeven at 2R IMPROVES results by ${diff_pnl:+,.0f}')
    else:
        print(f'Breakeven at 2R REDUCES results by ${diff_pnl:,.0f}')

    if diff_stops < 0:
        print(f'Breakeven at 2R converts {abs(diff_stops)} full stops into breakeven exits')
    print('='*100)


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    contracts = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    run_comparison(symbol=symbol, days=days, contracts=contracts)
