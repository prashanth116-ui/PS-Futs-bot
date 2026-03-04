"""
Standalone CLI for Live vs Backtest Divergence Comparison.

Usage:
    # Compare single symbol for specific date
    python -m runners.compare_divergence ES 2026-02-25

    # Compare multiple symbols
    python -m runners.compare_divergence ES NQ 2026-02-25

    # Compare last N days
    python -m runners.compare_divergence ES --last 5
"""
import sys
sys.path.insert(0, '.')

import argparse
from datetime import date, timedelta

from runners.divergence_tracker import (
    compare_day,
    format_console_report,
    load_live_trades,
)


def main():
    parser = argparse.ArgumentParser(
        description='Compare live paper trades vs backtest for divergence tracking'
    )
    parser.add_argument('args', nargs='*', help='Symbols and/or date (YYYY-MM-DD)')
    parser.add_argument('--last', type=int, default=0,
                        help='Compare last N days (looks for saved JSON)')
    parser.add_argument('--contracts', type=int, default=3,
                        help='Contract count for backtest (default: 3)')
    args = parser.parse_args()

    # Parse positional args: symbols + optional date
    symbols = []
    trade_date = None
    for arg in args.args:
        if arg.upper() in ('ES', 'NQ', 'MES', 'MNQ'):
            symbols.append(arg.upper())
        else:
            try:
                trade_date = date.fromisoformat(arg)
            except ValueError:
                print(f"Unknown argument: {arg}")
                print("Expected symbol (ES/NQ/MES/MNQ) or date (YYYY-MM-DD)")
                return

    if not symbols:
        symbols = ['ES']

    if args.last > 0:
        # Compare last N days for each symbol
        today = date.today()
        dates = []
        for i in range(args.last * 2):  # Check extra days to skip weekends
            d = today - timedelta(days=i)
            if d.weekday() < 5:  # Mon-Fri
                dates.append(d)
            if len(dates) >= args.last:
                break

        for d in sorted(dates):
            reports = []
            has_data = False
            for sym in symbols:
                saved = load_live_trades(sym, d)
                if saved is not None:
                    has_data = True
                    report = compare_day(sym, d, contracts=args.contracts)
                    reports.append(report)

            if has_data:
                print(f'\n--- {d.isoformat()} ---')
                print(format_console_report(reports))
            else:
                print(f'\n--- {d.isoformat()} --- No saved live trades')

    else:
        # Single date comparison
        if trade_date is None:
            trade_date = date.today()

        print(f'Comparing {", ".join(symbols)} for {trade_date.isoformat()}...')

        reports = []
        for sym in symbols:
            report = compare_day(sym, trade_date, contracts=args.contracts)
            reports.append(report)

        print(format_console_report(reports))


if __name__ == '__main__':
    main()
