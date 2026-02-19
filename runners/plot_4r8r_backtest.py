"""
Plot 4R/8R backtest results.
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
from datetime import date

def plot_4r8r_backtest():
    """Create comprehensive 4R/8R backtest results plot."""

    # Results from 15-day backtest with 4R/8R targets, 10 contracts
    results = [
        {'date': date(2026, 1, 12), 'direction': 'LONG', 'entry': '05:00', 'pnl': -687.50, 'result': 'LOSS'},
        {'date': date(2026, 1, 12), 'direction': 'SHORT', 'entry': '15:51', 'pnl': 2437.50, 'result': 'WIN'},
        {'date': date(2026, 1, 13), 'direction': 'SHORT', 'entry': '09:21', 'pnl': 7950.00, 'result': 'WIN'},
        {'date': date(2026, 1, 14), 'direction': 'LONG', 'entry': '15:45', 'pnl': -500.00, 'result': 'LOSS'},
        {'date': date(2026, 1, 15), 'direction': 'SHORT', 'entry': '14:09', 'pnl': 7400.00, 'result': 'WIN'},
        {'date': date(2026, 1, 16), 'direction': 'SHORT', 'entry': '09:21', 'pnl': 437.50, 'result': 'WIN'},
        {'date': date(2026, 1, 20), 'direction': 'SHORT', 'entry': '12:36', 'pnl': -1250.00, 'result': 'LOSS'},
        {'date': date(2026, 1, 21), 'direction': 'LONG', 'entry': '08:57', 'pnl': -750.00, 'result': 'LOSS'},
        {'date': date(2026, 1, 22), 'direction': 'SHORT', 'entry': '13:30', 'pnl': 375.00, 'result': 'WIN'},
        {'date': date(2026, 1, 23), 'direction': 'SHORT', 'entry': '12:12', 'pnl': 5400.00, 'result': 'WIN'},
        {'date': date(2026, 1, 26), 'direction': 'LONG', 'entry': '05:18', 'pnl': -687.50, 'result': 'LOSS', 'stopped': True},
        {'date': date(2026, 1, 26), 'direction': 'LONG', 'entry': '07:24', 'pnl': 14050.00, 'result': 'WIN', 'reentry': True},
        {'date': date(2026, 1, 27), 'direction': 'LONG', 'entry': '10:03', 'pnl': 4750.00, 'result': 'WIN'},
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

    # Plot equity line
    ax1.plot(range(len(equity)), equity, color='#2196F3', linewidth=3, zorder=3)
    ax1.fill_between(range(len(equity)), 0, equity, alpha=0.2, color='#2196F3')

    # Color markers by win/loss
    for i, r in enumerate(results):
        color = '#4CAF50' if r['pnl'] > 0 else '#F44336'
        marker = '*' if r.get('reentry') else 'o'
        size = 200 if r.get('reentry') else 100
        ax1.scatter([i+1], [equity[i+1]], color=color, s=size, zorder=5, edgecolors='black', linewidths=1.5, marker=marker)

    ax1.axhline(y=0, color='gray', linestyle='--', linewidth=1)
    ax1.set_xlabel('Trade Number', fontsize=12)
    ax1.set_ylabel('Cumulative P/L ($)', fontsize=12)
    ax1.set_title('Equity Curve - 4R/8R Strategy (10 Contracts)', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)

    # Add annotations for key trades
    ax1.annotate('Re-entry\n+$14,050', xy=(12, equity[12]), xytext=(9, equity[12] + 3000),
                 fontsize=10, fontweight='bold', color='#4CAF50',
                 arrowprops=dict(arrowstyle='->', color='#4CAF50', lw=2))

    ax1.annotate(f'Final: ${equity[-1]:+,.0f}', xy=(13, equity[-1]), xytext=(13, equity[-1] + 2000),
                 fontsize=11, fontweight='bold', color='#2196F3', ha='center')

    # ==========================================================================
    # Plot 2: Trade-by-Trade P/L
    # ==========================================================================
    ax2 = axes[0, 1]

    pnls = [r['pnl'] for r in results]
    colors = ['#4CAF50' if p > 0 else '#F44336' for p in pnls]

    # Add pattern for re-entry trade
    bars = ax2.bar(range(len(pnls)), pnls, color=colors, edgecolor='black', linewidth=1.5)

    # Highlight re-entry bar
    bars[11].set_hatch('///')
    bars[11].set_edgecolor('#FFD700')
    bars[11].set_linewidth(2)

    ax2.axhline(y=0, color='black', linewidth=1)
    ax2.set_xlabel('Trade Number', fontsize=12)
    ax2.set_ylabel('P/L ($)', fontsize=12)
    ax2.set_title('Trade-by-Trade P/L', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3, axis='y')

    # Add value labels
    for i, (bar, pnl) in enumerate(zip(bars, pnls)):
        va = 'bottom' if pnl > 0 else 'top'
        offset = 300 if pnl > 0 else -300
        label = f'${pnl/1000:+.1f}K' if abs(pnl) >= 1000 else f'${pnl:+,.0f}'
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + offset,
                 label, ha='center', va=va, fontsize=9, fontweight='bold')

    # ==========================================================================
    # Plot 3: Statistics Table
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
        ['Strategy', '4R / 8R / EMA50 Runner'],
        ['Contracts', '10 (3 @ 4R, 3 @ 8R, 4 @ Runner)'],
        ['Period', 'Jan 11-27, 2026 (15 days)'],
        ['Total Trades', f'{len(results)} (1 re-entry)'],
        ['Win / Loss', f'{wins}W / {losses}L'],
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
                      colWidths=[0.45, 0.45])
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.2, 1.6)

    # Style header row
    table[(0, 0)].set_facecolor('#1565C0')
    table[(0, 0)].set_text_props(color='white', fontweight='bold')
    table[(0, 1)].set_facecolor('#1565C0')
    table[(0, 1)].set_text_props(color='white', fontweight='bold')

    # Highlight key metrics
    for i in [7, 8, 9, 14]:  # Total, Long, Short P/L, Profit Factor
        if '+' in str(table_data[i][1]):
            table[(i, 1)].set_facecolor('#C8E6C9')
        table[(i, 0)].set_facecolor('#E3F2FD')
        table[(i, 1)].set_text_props(fontweight='bold')

    ax3.set_title('Performance Statistics', fontsize=14, fontweight='bold', pad=20)

    # ==========================================================================
    # Plot 4: Long vs Short + Daily P/L
    # ==========================================================================
    ax4 = axes[1, 1]

    # Group by date for daily P/L
    daily_pnl = {}
    for r in results:
        d = r['date']
        if d not in daily_pnl:
            daily_pnl[d] = 0
        daily_pnl[d] += r['pnl']

    dates = sorted(daily_pnl.keys())
    pnl_values = [daily_pnl[d] for d in dates]
    colors = ['#4CAF50' if p > 0 else '#F44336' if p < 0 else '#9E9E9E' for p in pnl_values]

    bars = ax4.bar(range(len(dates)), pnl_values, color=colors, edgecolor='black', linewidth=1)

    ax4.axhline(y=0, color='black', linewidth=1)
    ax4.set_xlabel('Trading Day', fontsize=12)
    ax4.set_ylabel('Daily P/L ($)', fontsize=12)
    ax4.set_title('Daily P/L by Date', fontsize=14, fontweight='bold')
    ax4.set_xticks(range(len(dates)))
    ax4.set_xticklabels([d.strftime('%m/%d') for d in dates], rotation=45, fontsize=9)
    ax4.grid(True, alpha=0.3, axis='y')

    # Add value labels
    for bar, pnl in zip(bars, pnl_values):
        va = 'bottom' if pnl > 0 else 'top'
        offset = 200 if pnl > 0 else -200
        label = f'${pnl/1000:+.1f}K' if abs(pnl) >= 1000 else f'${pnl:+,.0f}'
        ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + offset,
                 label, ha='center', va=va, fontsize=8, fontweight='bold')

    # Add summary box
    textstr = f'Long: ${long_pnl:+,.0f}\nShort: ${short_pnl:+,.0f}'
    props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
    ax4.text(0.02, 0.98, textstr, transform=ax4.transAxes, fontsize=11,
             verticalalignment='top', fontweight='bold', bbox=props)

    plt.suptitle('ICT Re-entry Strategy: 4R/8R Targets\n'
                 'ES 3-Minute | 10 Contracts | Jan 11-27, 2026 | Profit Factor: 10.05',
                 fontsize=16, fontweight='bold', y=1.02)

    plt.tight_layout()
    plt.savefig('backtest_4r8r_results.png', dpi=150, bbox_inches='tight')
    print('Saved: backtest_4r8r_results.png')
    plt.close()


if __name__ == '__main__':
    plot_4r8r_backtest()
