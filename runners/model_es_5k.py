"""
Model ES trading with $5,000 capital.
"""

def model_es_5k():
    capital = 5000

    print('='*70)
    print('ES TRADING WITH $5,000 CAPITAL')
    print('='*70)

    print()
    print('1. POSITION SIZING ANALYSIS')
    print('-'*70)
    print()
    print('   ES Contract Specs:')
    print('   - Tick size: $0.25')
    print('   - Tick value: $12.50')
    print('   - Intraday margin: ~$500/contract')
    print('   - Avg risk (8 ticks): $100/contract')
    print()

    print('   Position Options:')
    print('   ' + '-'*60)
    print(f'   {"Contracts":<12} {"Risk":<12} {"% Account":<12} {"Margin":<12} {"Status"}')
    print('   ' + '-'*60)

    for contracts in [1, 2, 3]:
        risk = 100 * contracts
        risk_pct = (risk / capital) * 100
        margin = 500 * contracts
        margin_pct = (margin / capital) * 100

        if risk_pct <= 2:
            status = 'ACCEPTABLE'
        elif risk_pct <= 3:
            status = 'AGGRESSIVE'
        else:
            status = 'HIGH RISK'

        print(f'   {contracts:<12} ${risk:<11} {risk_pct:.1f}%{"":<8} ${margin:<11} {status}')

    print()
    print('='*70)
    print('SCENARIO: 1 ES CONTRACT (Recommended for $5K)')
    print('='*70)
    print()

    contracts = 1

    # Risk metrics
    risk_per_trade = 100  # ~8 ticks avg
    risk_pct = (risk_per_trade / capital) * 100
    margin = 500
    margin_pct = (margin / capital) * 100

    print('   RISK METRICS:')
    print(f'   - Risk per trade:     ${risk_per_trade} ({risk_pct:.1f}% of account)')
    print(f'   - Margin required:    ${margin} ({margin_pct:.0f}% of account)')
    print(f'   - Max drawdown (5L):  ${risk_per_trade * 5} ({risk_pct * 5:.0f}% of account)')
    print()

    # From ES backtest: 3 contracts = $11,162.50 over 15 days
    # Scale to 1 contract
    base_pnl_3ct = 11162.50
    scaled_pnl = base_pnl_3ct / 3  # 1 contract

    daily_pnl = scaled_pnl / 15
    weekly_pnl = daily_pnl * 5
    monthly_pnl = daily_pnl * 20

    print('   EXPECTED RETURNS (based on 15-day backtest):')
    print(f'   - 15-day P/L:         ${scaled_pnl:+,.2f}')
    print(f'   - Daily avg:          ${daily_pnl:+,.2f}')
    print(f'   - Weekly avg:         ${weekly_pnl:+,.2f}')
    print(f'   - Monthly avg:        ${monthly_pnl:+,.2f}')
    print(f'   - Monthly ROI:        {(monthly_pnl/capital)*100:+.1f}%')
    print()

    # Win/Loss from backtest
    print('   TRADE STATISTICS (from backtest):')
    print('   - Win rate:           61.5% (8W / 5L)')
    print('   - Profit factor:      10.60')
    print('   - Avg win:            $513.54 (1 contract)')
    print('   - Avg loss:           -$77.50 (1 contract)')
    print()

    # Account growth projection
    print('   6-MONTH GROWTH PROJECTION:')
    print('   ' + '-'*50)
    print(f'   {"Month":<10} {"Balance":<15} {"Gain":<15} {"ROI"}')
    print('   ' + '-'*50)

    balance = capital
    for month in range(1, 7):
        balance += monthly_pnl
        gain = balance - capital
        roi = (gain / capital) * 100
        print(f'   {month:<10} ${balance:,.2f}{"":<5} ${gain:+,.2f}{"":<5} {roi:+.1f}%')

    print()
    print('='*70)
    print('SCENARIO: 2 ES CONTRACTS (Aggressive)')
    print('='*70)
    print()

    contracts = 2

    risk_per_trade = 100 * contracts
    risk_pct = (risk_per_trade / capital) * 100
    margin = 500 * contracts

    print('   RISK METRICS:')
    print(f'   - Risk per trade:     ${risk_per_trade} ({risk_pct:.1f}% of account) - HIGH!')
    print(f'   - Margin required:    ${margin} ({margin/capital*100:.0f}% of account)')
    print(f'   - Max drawdown (5L):  ${risk_per_trade * 5} ({risk_pct * 5:.0f}% of account) - DANGER!')
    print()

    scaled_pnl_2ct = (base_pnl_3ct / 3) * 2
    daily_pnl_2ct = scaled_pnl_2ct / 15
    monthly_pnl_2ct = daily_pnl_2ct * 20

    print('   EXPECTED RETURNS:')
    print(f'   - Monthly avg:        ${monthly_pnl_2ct:+,.2f}')
    print(f'   - Monthly ROI:        {(monthly_pnl_2ct/capital)*100:+.1f}%')
    print()

    print('   6-MONTH GROWTH PROJECTION:')
    print('   ' + '-'*50)

    balance = capital
    for month in range(1, 7):
        balance += monthly_pnl_2ct
        gain = balance - capital
        roi = (gain / capital) * 100
        print(f'   Month {month}: ${balance:,.2f} ({roi:+.1f}%)')

    print()
    print('='*70)
    print('RISK WARNING - DRAWDOWN SCENARIOS')
    print('='*70)
    print()

    print('   What happens with losing streaks:')
    print()
    print('   1 CONTRACT:')
    print('   ' + '-'*50)
    for losses in [3, 5, 7]:
        dd = 100 * losses
        remaining = capital - dd
        dd_pct = (dd / capital) * 100
        print(f'   {losses} consecutive losses: -${dd} ({dd_pct:.0f}%) | Balance: ${remaining}')

    print()
    print('   2 CONTRACTS:')
    print('   ' + '-'*50)
    for losses in [3, 5, 7]:
        dd = 200 * losses
        remaining = capital - dd
        dd_pct = (dd / capital) * 100
        status = ' <- MARGIN CALL!' if remaining < 1000 else ''
        print(f'   {losses} consecutive losses: -${dd} ({dd_pct:.0f}%) | Balance: ${remaining}{status}')

    print()
    print('='*70)
    print('RECOMMENDATION FOR $5,000 ES TRADING')
    print('='*70)
    print()
    print('   BEST APPROACH: 1 ES Contract')
    print()
    print('   Pros:')
    print('   + 2% risk per trade (acceptable)')
    print('   + Can survive 5+ losing streak')
    print('   + Expected +$4,970/month (+99% ROI)')
    print('   + Transitions naturally as account grows')
    print()
    print('   Cons:')
    print('   - Smaller absolute returns vs more contracts')
    print('   - Less room for error than larger accounts')
    print()
    print('   SCALING PLAN:')
    print('   - $5,000 - $10,000:   Trade 1 ES contract')
    print('   - $10,000 - $15,000:  Trade 2 ES contracts')
    print('   - $15,000 - $20,000:  Trade 3 ES contracts')
    print('   - $20,000+:           Scale further')
    print()
    print('   ALTERNATIVE: Trade 10 MES contracts instead')
    print('   - Same exposure as 1 ES')
    print('   - More flexibility (can scale in/out)')
    print('   - Same P/L potential')
    print('='*70)


if __name__ == '__main__':
    model_es_5k()
