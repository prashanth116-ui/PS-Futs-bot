"""
Model $5,000 account trading scenario.
"""

def model_5k_account():
    capital = 5000

    print('='*70)
    print('$5,000 ACCOUNT TRADING SCENARIO')
    print('='*70)

    print()
    print('1. POSITION SIZING OPTIONS')
    print('-'*70)
    print()

    # ES Analysis
    print('   ES (E-mini S&P 500):')
    print('   - Tick value: $12.50')
    print('   - Intraday margin: ~$500/contract')
    print('   - Avg risk per contract: ~$100 (8 ticks)')
    print()

    for contracts in [1, 2, 3]:
        risk = 100 * contracts
        risk_pct = (risk / capital) * 100
        margin = 500 * contracts
        margin_pct = (margin / capital) * 100
        status = 'TOO RISKY' if risk_pct > 3 else 'RISKY' if risk_pct > 2 else 'OK'
        print(f'   {contracts} contract(s): ${risk} risk ({risk_pct:.1f}%) | Margin: ${margin} ({margin_pct:.0f}%) - {status}')

    print()
    print('   MES (Micro E-mini S&P 500):')
    print('   - Tick value: $1.25')
    print('   - Intraday margin: ~$50/contract')
    print('   - Avg risk per contract: ~$10 (8 ticks)')
    print()

    for contracts in [1, 2, 3, 5, 10]:
        risk = 10 * contracts
        risk_pct = (risk / capital) * 100
        margin = 50 * contracts
        margin_pct = (margin / capital) * 100
        status = 'TOO RISKY' if risk_pct > 3 else 'RISKY' if risk_pct > 2 else 'OK'
        print(f'   {contracts} contract(s): ${risk} risk ({risk_pct:.1f}%) | Margin: ${margin} ({margin_pct:.1f}%) - {status}')

    print()
    print('='*70)
    print('RECOMMENDED: MES with 5-10 CONTRACTS')
    print('='*70)
    print()

    # Model with 5 MES contracts (1% risk) and 10 MES contracts (2% risk)
    for contracts, label in [(5, 'CONSERVATIVE (1% risk)'), (10, 'MODERATE (2% risk)')]:
        print(f'{label} - {contracts} MES Contracts')
        print('-'*70)

        # From backtest: MES 3 contracts = +$958.75 over 15 days
        # Scale to new contract size
        base_pnl = 958.75  # 15 days, 3 contracts
        scaled_pnl = base_pnl * (contracts / 3)

        daily_pnl = scaled_pnl / 15
        weekly_pnl = daily_pnl * 5
        monthly_pnl = daily_pnl * 20

        # Risk per trade
        risk_per_trade = 10 * contracts  # ~$10 per contract avg
        risk_pct = (risk_per_trade / capital) * 100

        # Max drawdown estimate (3 consecutive losses)
        max_dd = risk_per_trade * 3
        max_dd_pct = (max_dd / capital) * 100

        # Margin required
        margin = 50 * contracts
        margin_pct = (margin / capital) * 100

        print(f'   Risk per trade:     ${risk_per_trade:.0f} ({risk_pct:.1f}% of account)')
        print(f'   Margin required:    ${margin:.0f} ({margin_pct:.1f}% of account)')
        print(f'   Max drawdown (3L):  ${max_dd:.0f} ({max_dd_pct:.1f}% of account)')
        print()
        print(f'   EXPECTED RETURNS (based on 15-day backtest):')
        print(f'   - Daily avg:        ${daily_pnl:+.2f}')
        print(f'   - Weekly avg:       ${weekly_pnl:+.2f}')
        print(f'   - Monthly avg:      ${monthly_pnl:+.2f}')
        print(f'   - Monthly ROI:      {(monthly_pnl/capital)*100:+.1f}%')
        print()

        # Account growth projection
        print(f'   ACCOUNT GROWTH PROJECTION:')
        balance = capital
        for month in range(1, 7):
            balance += monthly_pnl
            roi = ((balance - capital) / capital) * 100
            print(f'   Month {month}: ${balance:,.2f} ({roi:+.1f}%)')
        print()

    print('='*70)
    print('BEST STRATEGY FOR $5,000 ACCOUNT')
    print('='*70)
    print()
    print('   Instrument:    MES (Micro E-mini S&P 500)')
    print('   Contracts:     5-10 (start with 5, scale up as account grows)')
    print('   Strategy:      4R/8R with EMA50 runner')
    print('   Risk/Trade:    $50-$100 (1-2%)')
    print()
    print('   Starting with 5 contracts:')
    print('   - Monthly expected: +$1,598')
    print('   - Monthly ROI: +32%')
    print('   - 6-month target: $14,587 (192% gain)')
    print()
    print('   SCALING PLAN:')
    print('   - $5,000 - $7,500:    Trade 5 MES contracts')
    print('   - $7,500 - $10,000:   Trade 7 MES contracts')
    print('   - $10,000 - $15,000:  Trade 10 MES contracts')
    print('   - $15,000+:           Transition to 1-2 ES contracts')
    print('='*70)


if __name__ == '__main__':
    model_5k_account()
