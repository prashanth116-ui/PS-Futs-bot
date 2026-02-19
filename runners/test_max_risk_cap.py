"""Test Max Risk Cap - Skip trades where risk > threshold"""
import sys
sys.path.insert(0, '.')

MAX_RISK = 5.0  # Max risk cap in points

# All overnight retrace trades from both days (from actual backtest results)
all_trades = [
    # Feb 3
    {'date': '2026-02-03', 'time': '09:30', 'dir': 'SHORT', 'entry': 7007.75, 'stop': 7017.50, 'current_pnl': 11637.50},
    {'date': '2026-02-03', 'time': '09:39', 'dir': 'SHORT', 'entry': 7007.00, 'stop': 7011.00, 'current_pnl': 10412.50},
    {'date': '2026-02-03', 'time': '15:36', 'dir': 'LONG', 'entry': 6938.00, 'stop': 6931.25, 'current_pnl': -1012.50},
    # Feb 4
    {'date': '2026-02-04', 'time': '09:36', 'dir': 'SHORT', 'entry': 6949.50, 'stop': 6957.00, 'current_pnl': -1125.00},
]

def main():
    print('=' * 70)
    print(f'MAX RISK CAP TEST: {MAX_RISK} pts')
    print('=' * 70)

    total_current = 0
    total_capped = 0
    trades_taken_current = 0
    trades_taken_capped = 0
    skipped_trades = []

    for t in all_trades:
        is_long = t['dir'] == 'LONG'

        # Calculate risk
        if is_long:
            risk = t['entry'] - t['stop']
        else:
            risk = t['stop'] - t['entry']

        # Would this trade be taken with max risk cap?
        take_trade = risk <= MAX_RISK

        status = 'TAKEN' if take_trade else f'SKIPPED (risk {risk:.2f} > {MAX_RISK} pts)'

        print(f"\n{t['date']} {t['dir']} @ {t['time']}")
        print(f"  Entry: {t['entry']:.2f}, Stop: {t['stop']:.2f}")
        print(f"  Risk: {risk:.2f} pts")
        print(f"  Status: {status}")
        print(f"  Current P/L: ${t['current_pnl']:+,.2f}")

        total_current += t['current_pnl']
        trades_taken_current += 1

        if take_trade:
            total_capped += t['current_pnl']
            trades_taken_capped += 1
            print(f"  Capped P/L:  ${t['current_pnl']:+,.2f}")
        else:
            skipped_trades.append(t)
            print("  Capped P/L:  $0.00 (trade skipped)")

    print(f"\n{'=' * 70}")
    print(f"SUMMARY: MAX RISK CAP {MAX_RISK} pts")
    print(f"{'=' * 70}")
    print(f"Trades Taken:  Current: {trades_taken_current} | Capped: {trades_taken_capped}")
    print(f"Total P/L:     Current: ${total_current:+,.2f} | Capped: ${total_capped:+,.2f}")
    print(f"Difference:    ${total_capped - total_current:+,.2f}")
    print()

    # Show which trades were filtered
    if skipped_trades:
        print('Trades SKIPPED by max risk cap:')
        skipped_pnl = 0
        for t in skipped_trades:
            is_long = t['dir'] == 'LONG'
            if is_long:
                risk = t['entry'] - t['stop']
            else:
                risk = t['stop'] - t['entry']
            skipped_pnl += t['current_pnl']
            result = 'WIN' if t['current_pnl'] > 0 else 'LOSS'
            print(f"  {t['date']} {t['dir']} @ {t['time']} - Risk: {risk:.2f} pts - {result}: ${t['current_pnl']:+,.2f}")
        print(f"\nTotal P/L from skipped trades: ${skipped_pnl:+,.2f}")
        if skipped_pnl > 0:
            print("WARNING: Skipped trades were NET PROFITABLE!")
        else:
            print("GOOD: Skipped trades were NET LOSING!")


if __name__ == "__main__":
    main()
