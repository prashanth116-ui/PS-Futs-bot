"""
Plot ES vs NQ comparison for 4R/8R strategy with 3 contracts.
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
from datetime import date

def plot_es_nq_comparison():
    """Create ES vs NQ comparison plot for 4R/8R strategy."""

    # ES Results (3 contracts, 4R/8R)
    es_results = [
        {'date': date(2026, 1, 12), 'direction': 'LONG', 'entry': '05:00', 'pnl': -206.25},
        {'date': date(2026, 1, 12), 'direction': 'SHORT', 'entry': '15:51', 'pnl': 725.00},
        {'date': date(2026, 1, 13), 'direction': 'SHORT', 'entry': '09:21', 'pnl': 2287.50},
        {'date': date(2026, 1, 14), 'direction': 'LONG', 'entry': '15:45', 'pnl': -150.00},
        {'date': date(2026, 1, 15), 'direction': 'SHORT', 'entry': '14:09', 'pnl': 2075.00},
        {'date': date(2026, 1, 16), 'direction': 'SHORT', 'entry': '09:21', 'pnl': 175.00},
        {'date': date(2026, 1, 20), 'direction': 'SHORT', 'entry': '12:36', 'pnl': -375.00},
        {'date': date(2026, 1, 21), 'direction': 'LONG', 'entry': '08:57', 'pnl': -225.00},
        {'date': date(2026, 1, 22), 'direction': 'SHORT', 'entry': '13:30', 'pnl': 150.00},
        {'date': date(2026, 1, 23), 'direction': 'SHORT', 'entry': '12:12', 'pnl': 1612.50},
        {'date': date(2026, 1, 26), 'direction': 'LONG', 'entry': '05:18', 'pnl': -206.25, 'stopped': True},
        {'date': date(2026, 1, 26), 'direction': 'LONG', 'entry': '07:24', 'pnl': 3868.75, 'reentry': True},
        {'date': date(2026, 1, 27), 'direction': 'LONG', 'entry': '10:03', 'pnl': 1431.25},
    ]

    # NQ Results (3 contracts, 4R/8R)
    nq_results = [
        {'date': date(2026, 1, 14), 'direction': 'LONG', 'entry': '13:48', 'pnl': 3337.50},
        {'date': date(2026, 1, 22), 'direction': 'SHORT', 'entry': '13:21', 'pnl': 2600.00},
        {'date': date(2026, 1, 23), 'direction': 'LONG', 'entry': '08:51', 'pnl': -543.75},
    ]

    # Create figure
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # ==========================================================================
    # Plot 1: Equity Curves Comparison
    # ==========================================================================
    ax1 = axes[0, 0]

    # ES equity curve
    es_equity = [0]
    es_cumulative = 0
    for r in es_results:
        es_cumulative += r['pnl']
        es_equity.append(es_cumulative)

    # NQ equity curve
    nq_equity = [0]
    nq_cumulative = 0
    for r in nq_results:
        nq_cumulative += r['pnl']
        nq_equity.append(nq_cumulative)

    ax1.plot(range(len(es_equity)), es_equity, color='#2196F3', marker='o', linewidth=2.5,
             markersize=8, label=f'ES: ${es_cumulative:+,.2f}')
    ax1.fill_between(range(len(es_equity)), 0, es_equity, alpha=0.15, color='#2196F3')

    ax1.plot(range(len(nq_equity)), nq_equity, color='#FF9800', marker='s', linewidth=2.5,
             markersize=8, label=f'NQ: ${nq_cumulative:+,.2f}')
    ax1.fill_between(range(len(nq_equity)), 0, nq_equity, alpha=0.15, color='#FF9800')

    ax1.axhline(y=0, color='gray', linestyle='--', linewidth=1)
    ax1.set_xlabel('Trade Number', fontsize=12)
    ax1.set_ylabel('Cumulative P/L ($)', fontsize=12)
    ax1.set_title('Equity Curves - ES vs NQ (3 Contracts, 4R/8R)', fontsize=14, fontweight='bold')
    ax1.legend(fontsize=12, loc='upper left')
    ax1.grid(True, alpha=0.3)

    # ==========================================================================
    # Plot 2: Summary Statistics Comparison
    # ==========================================================================
    ax2 = axes[0, 1]
    ax2.axis('off')

    # Calculate stats
    es_wins = len([r for r in es_results if r['pnl'] > 0])
    es_losses = len([r for r in es_results if r['pnl'] < 0])
    es_total = sum(r['pnl'] for r in es_results)
    es_long = sum(r['pnl'] for r in es_results if r['direction'] == 'LONG')
    es_short = sum(r['pnl'] for r in es_results if r['direction'] == 'SHORT')
    es_win_rate = es_wins / (es_wins + es_losses) * 100
    es_avg_win = sum(r['pnl'] for r in es_results if r['pnl'] > 0) / es_wins
    es_avg_loss = sum(r['pnl'] for r in es_results if r['pnl'] < 0) / es_losses
    es_pf = abs(sum(r['pnl'] for r in es_results if r['pnl'] > 0) / sum(r['pnl'] for r in es_results if r['pnl'] < 0))

    nq_wins = len([r for r in nq_results if r['pnl'] > 0])
    nq_losses = len([r for r in nq_results if r['pnl'] < 0])
    nq_total = sum(r['pnl'] for r in nq_results)
    nq_long = sum(r['pnl'] for r in nq_results if r['direction'] == 'LONG')
    nq_short = sum(r['pnl'] for r in nq_results if r['direction'] == 'SHORT')
    nq_win_rate = nq_wins / (nq_wins + nq_losses) * 100
    nq_avg_win = sum(r['pnl'] for r in nq_results if r['pnl'] > 0) / nq_wins
    nq_avg_loss = sum(r['pnl'] for r in nq_results if r['pnl'] < 0) / nq_losses
    nq_pf = abs(sum(r['pnl'] for r in nq_results if r['pnl'] > 0) / sum(r['pnl'] for r in nq_results if r['pnl'] < 0))

    table_data = [
        ['Metric', 'ES', 'NQ', 'Winner'],
        ['Total Trades', f'{len(es_results)}', f'{len(nq_results)}', 'ES' if len(es_results) > len(nq_results) else 'NQ'],
        ['Win / Loss', f'{es_wins}W / {es_losses}L', f'{nq_wins}W / {nq_losses}L', '-'],
        ['Win Rate', f'{es_win_rate:.1f}%', f'{nq_win_rate:.1f}%', 'ES' if es_win_rate > nq_win_rate else 'NQ'],
        ['Total P/L', f'${es_total:+,.2f}', f'${nq_total:+,.2f}', 'ES' if es_total > nq_total else 'NQ'],
        ['Long P/L', f'${es_long:+,.2f}', f'${nq_long:+,.2f}', 'ES' if es_long > nq_long else 'NQ'],
        ['Short P/L', f'${es_short:+,.2f}', f'${nq_short:+,.2f}', 'ES' if es_short > nq_short else 'NQ'],
        ['Avg Win', f'${es_avg_win:+,.2f}', f'${nq_avg_win:+,.2f}', 'ES' if es_avg_win > nq_avg_win else 'NQ'],
        ['Avg Loss', f'${es_avg_loss:+,.2f}', f'${nq_avg_loss:+,.2f}', 'ES' if abs(es_avg_loss) < abs(nq_avg_loss) else 'NQ'],
        ['Profit Factor', f'{es_pf:.2f}', f'{nq_pf:.2f}', 'ES' if es_pf > nq_pf else 'NQ'],
        ['Avg per Day', f'${es_total/15:+,.2f}', f'${nq_total/15:+,.2f}', 'ES' if es_total > nq_total else 'NQ'],
    ]

    table = ax2.table(cellText=table_data, loc='center', cellLoc='center',
                      colWidths=[0.28, 0.28, 0.28, 0.16])
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.2, 1.8)

    # Style header row
    for j in range(4):
        table[(0, j)].set_facecolor('#1565C0')
        table[(0, j)].set_text_props(color='white', fontweight='bold')

    # Color winner column
    for i in range(1, len(table_data)):
        winner = table_data[i][3]
        if winner == 'ES':
            table[(i, 1)].set_facecolor('#BBDEFB')
            table[(i, 3)].set_facecolor('#BBDEFB')
        elif winner == 'NQ':
            table[(i, 2)].set_facecolor('#FFE0B2')
            table[(i, 3)].set_facecolor('#FFE0B2')

    ax2.set_title('Performance Comparison', fontsize=14, fontweight='bold', pad=20)

    # ==========================================================================
    # Plot 3: Trade-by-Trade P/L - ES
    # ==========================================================================
    ax3 = axes[1, 0]

    es_pnls = [r['pnl'] for r in es_results]
    es_colors = ['#4CAF50' if p > 0 else '#F44336' for p in es_pnls]
    bars = ax3.bar(range(len(es_pnls)), es_pnls, color=es_colors, edgecolor='black', linewidth=1)

    # Highlight re-entry
    for i, r in enumerate(es_results):
        if r.get('reentry'):
            bars[i].set_hatch('///')
            bars[i].set_edgecolor('#FFD700')
            bars[i].set_linewidth(2)

    ax3.axhline(y=0, color='black', linewidth=1)
    ax3.set_xlabel('Trade Number', fontsize=12)
    ax3.set_ylabel('P/L ($)', fontsize=12)
    ax3.set_title(f'ES Trade-by-Trade P/L (Total: ${es_total:+,.2f})', fontsize=14, fontweight='bold')
    ax3.grid(True, alpha=0.3, axis='y')

    # Add value labels
    for bar, pnl in zip(bars, es_pnls):
        va = 'bottom' if pnl > 0 else 'top'
        offset = 100 if pnl > 0 else -100
        label = f'${pnl/1000:+.1f}K' if abs(pnl) >= 1000 else f'${pnl:+,.0f}'
        ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height() + offset,
                 label, ha='center', va=va, fontsize=8, fontweight='bold')

    # ==========================================================================
    # Plot 4: Trade-by-Trade P/L - NQ
    # ==========================================================================
    ax4 = axes[1, 1]

    nq_pnls = [r['pnl'] for r in nq_results]
    nq_colors = ['#4CAF50' if p > 0 else '#F44336' for p in nq_pnls]
    bars = ax4.bar(range(len(nq_pnls)), nq_pnls, color=nq_colors, edgecolor='black', linewidth=1)

    ax4.axhline(y=0, color='black', linewidth=1)
    ax4.set_xlabel('Trade Number', fontsize=12)
    ax4.set_ylabel('P/L ($)', fontsize=12)
    ax4.set_title(f'NQ Trade-by-Trade P/L (Total: ${nq_total:+,.2f})', fontsize=14, fontweight='bold')
    ax4.grid(True, alpha=0.3, axis='y')

    # Add value labels
    for bar, pnl in zip(bars, nq_pnls):
        va = 'bottom' if pnl > 0 else 'top'
        offset = 100 if pnl > 0 else -100
        label = f'${pnl/1000:+.1f}K' if abs(pnl) >= 1000 else f'${pnl:+,.0f}'
        ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + offset,
                 label, ha='center', va=va, fontsize=9, fontweight='bold')

    # Match y-axis scale for fair comparison
    max_pnl = max(max(es_pnls), max(nq_pnls))
    min_pnl = min(min(es_pnls), min(nq_pnls))
    margin = (max_pnl - min_pnl) * 0.2
    ax3.set_ylim(min_pnl - margin, max_pnl + margin)
    ax4.set_ylim(min_pnl - margin, max_pnl + margin)

    plt.suptitle('ICT Re-entry Strategy: ES vs NQ Comparison\n'
                 '3 Contracts | 4R/8R Targets | EMA50 Runner | Jan 11-27, 2026',
                 fontsize=16, fontweight='bold', y=1.02)

    plt.tight_layout()
    plt.savefig('backtest_es_nq_4r8r_comparison.png', dpi=150, bbox_inches='tight')
    print('Saved: backtest_es_nq_4r8r_comparison.png')
    plt.close()


if __name__ == '__main__':
    plot_es_nq_comparison()
