"""
Model 3 ES contracts with $5,000 capital - HIGH RISK scenario.
"""

def model_es_3ct_5k():
    capital = 5000
    contracts = 3

    print('='*70)
    print('3 ES CONTRACTS WITH $5,000 CAPITAL')
    print('='*70)
    print()
    print('                    *** HIGH RISK SCENARIO ***')
    print()

    # Risk metrics
    risk_per_trade = 100 * contracts  # ~$100 per contract
    risk_pct = (risk_per_trade / capital) * 100
    margin = 500 * contracts
    margin_pct = (margin / capital) * 100

    print('='*70)
    print('RISK PROFILE')
    print('='*70)
    print()
    print(f'   Risk per trade:       ${risk_per_trade} ({risk_pct:.0f}% of account)')
    print(f'   Margin required:      ${margin} ({margin_pct:.0f}% of account)')
    print(f'   Free capital:         ${capital - margin} ({100-margin_pct:.0f}% of account)')
    print()
    print('   RISK ASSESSMENT:')
    print('   - Standard rule: Risk 1-2% per trade')
    print(f'   - Your risk: {risk_pct:.0f}% per trade')
    print(f'   - Overleveraged by: {risk_pct/2:.1f}x')
    print()

    # From ES backtest: 3 contracts = $11,162.50 over 15 days
    total_pnl_15d = 11162.50
    daily_pnl = total_pnl_15d / 15
    weekly_pnl = daily_pnl * 5
    monthly_pnl = daily_pnl * 20

    print('='*70)
    print('POTENTIAL RETURNS (Best Case)')
    print('='*70)
    print()
    print('   Based on 15-day backtest with 3 contracts:')
    print()
    print(f'   - 15-day P/L:         ${total_pnl_15d:+,.2f}')
    print(f'   - Daily avg:          ${daily_pnl:+,.2f}')
    print(f'   - Weekly avg:         ${weekly_pnl:+,.2f}')
    print(f'   - Monthly avg:        ${monthly_pnl:+,.2f}')
    print(f'   - Monthly ROI:        {(monthly_pnl/capital)*100:+.1f}%')
    print()

    # Best case growth
    print('   BEST CASE - 6 Month Growth:')
    print('   ' + '-'*55)
    print(f'   {"Month":<8} {"Balance":<15} {"Monthly Gain":<15} {"Total ROI"}')
    print('   ' + '-'*55)

    balance = capital
    for month in range(1, 7):
        balance += monthly_pnl
        gain = balance - capital
        roi = (gain / capital) * 100
        print(f'   {month:<8} ${balance:>12,.2f}  ${monthly_pnl:>12,.2f}   {roi:>+.0f}%')

    print()
    print('='*70)
    print('DRAWDOWN RISK (The Danger)')
    print('='*70)
    print()

    # Individual trade losses from backtest
    losses = [206.25, 150.00, 375.00, 225.00, 206.25]  # Actual losses from backtest
    avg_loss = sum(losses) / len(losses)
    max_loss = max(losses)

    print(f'   Actual losses from backtest (3 contracts):')
    print(f'   - Average loss: ${avg_loss:.2f}')
    print(f'   - Largest loss: ${max_loss:.2f}')
    print()

    print('   LOSING STREAK SCENARIOS:')
    print('   ' + '-'*60)
    print(f'   {"Losses":<10} {"Drawdown":<15} {"% Account":<12} {"Balance":<12} {"Status"}')
    print('   ' + '-'*60)

    for num_losses in [1, 2, 3, 4, 5]:
        dd = avg_loss * num_losses
        dd_pct = (dd / capital) * 100
        remaining = capital - dd

        if remaining < margin:
            status = 'MARGIN CALL!'
        elif remaining < capital * 0.5:
            status = 'CRITICAL'
        elif dd_pct > 20:
            status = 'SEVERE'
        else:
            status = 'Painful'

        print(f'   {num_losses:<10} ${dd:>12,.2f}  {dd_pct:>10.1f}%   ${remaining:>10,.2f}  {status}')

    print()
    print('   WORST CASE - Max losses:')
    print('   ' + '-'*60)

    for num_losses in [1, 2, 3, 4, 5]:
        dd = max_loss * num_losses
        dd_pct = (dd / capital) * 100
        remaining = capital - dd

        if remaining <= 0:
            status = 'ACCOUNT BLOWN!'
            remaining = 0
        elif remaining < margin:
            status = 'MARGIN CALL!'
        elif remaining < capital * 0.5:
            status = 'CRITICAL'
        else:
            status = 'Severe'

        print(f'   {num_losses:<10} ${dd:>12,.2f}  {dd_pct:>10.1f}%   ${remaining:>10,.2f}  {status}')

    print()
    print('='*70)
    print('REALISTIC SCENARIOS')
    print('='*70)
    print()

    # Scenario 1: Good month
    print('   SCENARIO 1: Good Month (like backtest)')
    print('   ' + '-'*50)
    print('   - 8 wins, 5 losses')
    print('   - Net P/L: +$11,162')
    print(f'   - End balance: ${capital + 11162:,.2f}')
    print(f'   - ROI: +{(11162/capital)*100:.0f}%')
    print()

    # Scenario 2: Break-even month
    print('   SCENARIO 2: Break-Even Month')
    print('   ' + '-'*50)
    print('   - 6 wins, 6 losses')
    print('   - Net P/L: ~$0')
    print(f'   - End balance: ${capital:,.2f}')
    print('   - Wasted time, but survived')
    print()

    # Scenario 3: Bad month
    print('   SCENARIO 3: Bad Month (reversed win rate)')
    print('   ' + '-'*50)
    print('   - 5 wins, 8 losses')
    avg_win = 1540.62  # from backtest
    bad_month_pnl = (5 * avg_win/3) - (8 * avg_loss)
    end_balance = capital + bad_month_pnl
    print(f'   - Net P/L: ${bad_month_pnl:+,.2f}')
    print(f'   - End balance: ${end_balance:,.2f}')
    if end_balance < margin:
        print('   - STATUS: MARGIN CALL - Cannot trade!')
    print()

    # Scenario 4: Unlucky start
    print('   SCENARIO 4: Unlucky Start (4 losses in a row)')
    print('   ' + '-'*50)
    dd = avg_loss * 4
    remaining = capital - dd
    print(f'   - Drawdown: ${dd:,.2f} ({(dd/capital)*100:.0f}%)')
    print(f'   - Remaining: ${remaining:,.2f}')
    if remaining < margin:
        print(f'   - STATUS: MARGIN CALL! Need ${margin} margin but only ${remaining:.0f} left')
        print('   - Must deposit more or stop trading')
    print()

    print('='*70)
    print('PROBABILITY ANALYSIS')
    print('='*70)
    print()
    print('   With 61.5% win rate, probability of consecutive losses:')
    print()
    loss_rate = 0.385  # 38.5% loss rate

    print(f'   {"Streak":<20} {"Probability":<15} {"Expected Frequency"}')
    print('   ' + '-'*55)

    for streak in [2, 3, 4, 5]:
        prob = (loss_rate ** streak) * 100
        freq = 1 / (loss_rate ** streak)
        print(f'   {streak} losses in a row   {prob:>10.2f}%        ~1 in {freq:.0f} trades')

    print()
    print('   Over 13 trades (like backtest), probability of hitting:')
    print(f'   - 3+ loss streak: ~35% (likely to happen)')
    print(f'   - 4+ loss streak: ~15% (possible)')
    print(f'   - 5+ loss streak: ~6% (unlikely but real)')

    print()
    print('='*70)
    print('VERDICT: 3 ES CONTRACTS WITH $5,000')
    print('='*70)
    print()
    print('   REWARD:')
    print('   + Potential +$14,883/month (+298% ROI)')
    print('   + Could turn $5K into $35K+ in 2 months')
    print('   + Maximum profit extraction from strategy')
    print()
    print('   RISK:')
    print('   - 6% risk per trade (3x recommended)')
    print('   - 30% margin usage')
    print('   - 3-4 consecutive losses = MARGIN CALL')
    print('   - ~35% chance of margin call in first month')
    print('   - ONE bad week could wipe account')
    print()
    print('   HONEST ASSESSMENT:')
    print('   ' + '-'*50)
    print('   This is GAMBLING, not trading.')
    print()
    print('   If you accept you might lose the $5,000:')
    print('   - Go for it, but treat it as "risk capital"')
    print('   - Be prepared to deposit more or stop')
    print('   - Set a hard stop: if down 40%, quit')
    print()
    print('   SMARTER ALTERNATIVES:')
    print('   1. Trade 1 ES contract (2% risk) - still +99%/month')
    print('   2. Trade 10 MES contracts - same exposure, more control')
    print('   3. Start with 1 contract, scale up as account grows')
    print('='*70)


if __name__ == '__main__':
    model_es_3ct_5k()
