"""
Plot full backtest results.
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
from datetime import date

def plot_full_backtest():
    """Create comprehensive backtest results plot."""

    # Results from 15-day backtest
    results = [
        {'date': date(2026, 1, 12), 'direction': 'LONG', 'entry': '05:00', 'pnl': -206.25, 'result': 'LOSS'},
        {'date': date(2026, 1, 12), 'direction': 'SHORT', 'entry': '15:51', 'pnl': 450.00, 'result': 'WIN'},
        {'date': date(2026, 1, 13), 'direction': 'SHORT', 'entry': '09:21', 'pnl': 1000.00, 'result': 'WIN'},
        {'date': date(2026, 1, 14), 'direction': 'LONG', 'entry': '15:45', 'pnl': -150.00, 'result': 'LOSS'},
        {'date': date(2026, 1, 15), 'direction': 'SHORT', 'entry': '14:09', 'pnl': 1625.00, 'result': 'WIN'},
        {'date': date(2026, 1, 16), 'direction': 'SHORT', 'entry': '09:21', 'pnl': 650.00, 'result': 'WIN'},
        {'date': date(2026, 1, 20), 'direction': 'SHORT', 'entry': '12:36', 'pnl': -375.00, 'result': 'LOSS'},
        {'date': date(2026, 1, 21), 'direction': 'LONG', 'entry': '08:57', 'pnl': -225.00, 'result': 'LOSS'},
        {'date': date(2026, 1, 22), 'direction': 'SHORT', 'entry': '13:30', 'pnl': 662.50, 'result': 'WIN'},
        {'date': date(2026, 1, 23), 'direction': 'SHORT', 'entry': '12:12', 'pnl': 1087.50, 'result': 'WIN'},
        {'date': date(2026, 1, 26), 'direction': 'LONG', 'entry': '05:18', 'pnl': -206.25, 'result': 'LOSS', 'stopped': True},
        {'date': date(2026, 1, 26), 'direction': 'LONG', 'entry': '07:24', 'pnl': 3156.25, 'result': 'WIN', 'reentry': True},
        {'date': date(2026, 1, 27), 'direction': 'LONG', 'entry': '10:03', 'pnl': 943.75, 'result': 'WIN'},
    ]

    # Create figure
    fig, axes = plt.subplots(2, 2, figsize=(18, 14))

    # ==========================================================================
    # Plot 1: Equity Curve
    # ==========================================================================
    ax1 = axes[0, 0]

    equity = [0]
    cumulative = 0
    for r in results:
        cumulative += r['pnl']
        equity.append(cumulative)

    ax1.plot(range(len(equity)), equity, color='#2196F3', marker='o', linewidth=2.5,
             markersize=8, label=f'Equity: ${cumulative:+,.2f}')
    ax1.fill_between(range(len(equity)), 0, equity, alpha=0.2, color='#2196F3')

    # Color markers by win/loss
    for i, r in enumerate(results):
        color = '#4CAF50' if r['pnl'] > 0 else '#F44336'
        ax1.scatter([i+1], [equity[i+1]], color=color, s=100, zorder=5, edgecolors='black')

    ax1.axhline(y=0, color='gray', linestyle='--', linewidth=1)
    ax1.set_xlabel('Trade Number', fontsize=12)
    ax1.set_ylabel('Cumulative P/L ($)', fontsize=12)
    ax1.set_title('Equity Curve - 15 Day Backtest', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)

    # Add annotations for key trades
    ax1.annotate('Re-entry\n+$3,156', xy=(12, equity[12]), xytext=(10, equity[12] + 1000),
                 fontsize=10, fontweight='bold', color='#4CAF50',
                 arrowprops=dict(arrowstyle='->', color='#4CAF50'))

    # ==========================================================================
    # Plot 2: Trade-by-Trade P/L
    # ==========================================================================
    ax2 = axes[0, 1]

    pnls = [r['pnl'] for r in results]
    colors = ['#4CAF50' if p > 0 else '#F44336' for p in pnls]
    bars = ax2.bar(range(len(pnls)), pnls, color=colors, edgecolor='black', linewidth=1)

    ax2.axhline(y=0, color='black', linewidth=1)
    ax2.set_xlabel('Trade Number', fontsize=12)
    ax2.set_ylabel('P/L ($)', fontsize=12)
    ax2.set_title('Trade-by-Trade P/L', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='y')

    # Add value labels
    for i, (bar, pnl) in enumerate(zip(bars, pnls)):
        va = 'bottom' if pnl > 0 else 'top'
        offset = 50 if pnl > 0 else -50
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + offset,
                 f'${pnl:+,.0f}', ha='center', va=va, fontsize=8, fontweight='bold')

    # Mark re-entry trade
    ax2.annotate('RE-ENTRY', xy=(11, 3156), xytext=(11, 3500),
                 fontsize=9, fontweight='bold', ha='center', color='#4CAF50')

    # ==========================================================================
    # Plot 3: Statistics and Breakdown
    # ==========================================================================
    ax3 = axes[1, 0]
    ax3.axis('off')

    # Calculate stats
    wins = len([r for r in results if r['pnl'] > 0])
    losses = len([r for r in results if r['pnl'] < 0])
    win_rate = wins / (wins + losses) * 100
    total_pnl = sum(r['pnl'] for r in results)
    long_pnl = sum(r['pnl'] for r in results if r['direction'] == 'LONG')
    short_pnl = sum(r['pnl'] for r in results if r['direction'] == 'SHORT')
    avg_win = sum(r['pnl'] for r in results if r['pnl'] > 0) / wins
    avg_loss = sum(r['pnl'] for r in results if r['pnl'] < 0) / losses
    profit_factor = abs(sum(r['pnl'] for r in results if r['pnl'] > 0) / sum(r['pnl'] for r in results if r['pnl'] < 0))
    max_win = max(r['pnl'] for r in results)
    max_loss = min(r['pnl'] for r in results)

    table_data = [
        ['Metric', 'Value'],
        ['Period', 'Jan 11-27, 2026 (15 days)'],
        ['Total Trades', f'{len(results)} (1 re-entry)'],
        ['Wins / Losses', f'{wins}W / {losses}L'],
        ['Win Rate', f'{win_rate:.1f}%'],
        ['Total P/L', f'${total_pnl:+,.2f}'],
        ['Long P/L', f'${long_pnl:+,.2f}'],
        ['Short P/L', f'${short_pnl:+,.2f}'],
        ['Avg Win', f'${avg_win:+,.2f}'],
        ['Avg Loss', f'${avg_loss:+,.2f}'],
        ['Max Win', f'${max_win:+,.2f}'],
        ['Max Loss', f'${max_loss:+,.2f}'],
        ['Profit Factor', f'{profit_factor:.2f}'],
        ['Avg P/L per Trade', f'${total_pnl/len(results):+,.2f}'],
        ['Avg P/L per Day', f'${total_pnl/15:+,.2f}'],
    ]

    table = ax3.table(cellText=table_data, loc='center', cellLoc='center',
                      colWidths=[0.4, 0.4])
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.2, 1.8)

    # Style header row
    table[(0, 0)].set_facecolor('#4472C4')
    table[(0, 0)].set_text_props(color='white', fontweight='bold')
    table[(0, 1)].set_facecolor('#4472C4')
    table[(0, 1)].set_text_props(color='white', fontweight='bold')

    # Color P/L cells
    for i in [5, 6, 7]:  # Total, Long, Short P/L
        if '+' in table_data[i][1]:
            table[(i, 1)].set_facecolor('#C6EFCE')
        elif '-' in table_data[i][1]:
            table[(i, 1)].set_facecolor('#FFC7CE')

    ax3.set_title('Performance Statistics', fontsize=14, fontweight='bold', pad=20)

    # ==========================================================================
    # Plot 4: Long vs Short Breakdown
    # ==========================================================================
    ax4 = axes[1, 1]

    # Pie chart for direction breakdown
    long_wins = len([r for r in results if r['direction'] == 'LONG' and r['pnl'] > 0])
    long_losses = len([r for r in results if r['direction'] == 'LONG' and r['pnl'] < 0])
    short_wins = len([r for r in results if r['direction'] == 'SHORT' and r['pnl'] > 0])
    short_losses = len([r for r in results if r['direction'] == 'SHORT' and r['pnl'] < 0])

    # Create grouped bar chart
    categories = ['LONG', 'SHORT']
    wins_data = [long_wins, short_wins]
    losses_data = [long_losses, short_losses]
    pnl_data = [long_pnl, short_pnl]

    x = range(len(categories))
    width = 0.35

    bars1 = ax4.bar([i - width/2 for i in x], wins_data, width, label='Wins', color='#4CAF50')
    bars2 = ax4.bar([i + width/2 for i in x], losses_data, width, label='Losses', color='#F44336')

    ax4.set_ylabel('Number of Trades', fontsize=12)
    ax4.set_title('Long vs Short Performance', fontsize=14, fontweight='bold')
    ax4.set_xticks(x)
    ax4.set_xticklabels([f'{cat}\n${pnl:+,.0f}' for cat, pnl in zip(categories, pnl_data)], fontsize=11)
    ax4.legend(fontsize=11)
    ax4.grid(True, alpha=0.3, axis='y')

    # Add count labels
    for bar in bars1:
        ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                 f'{int(bar.get_height())}', ha='center', fontsize=11, fontweight='bold')
    for bar in bars2:
        ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                 f'{int(bar.get_height())}', ha='center', fontsize=11, fontweight='bold')

    plt.suptitle('ICT Re-entry Strategy Backtest Results\n'
                 'ES 3-Minute | Jan 11-27, 2026 | 15 Trading Days',
                 fontsize=16, fontweight='bold', y=1.02)

    plt.tight_layout()
    plt.savefig('full_backtest_results.png', dpi=150, bbox_inches='tight')
    print('Saved: full_backtest_results.png')
    plt.close()


if __name__ == '__main__':
    plot_full_backtest()
