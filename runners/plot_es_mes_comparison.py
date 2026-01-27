"""
Plot ES vs MES comparison for 15-day backtest with 3 contracts and 4R/8R targets.
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
from datetime import date

def plot_es_mes_comparison():
    """Create ES vs MES comparison plot."""

    # ES Results (3 contracts, 4R/8R) - from earlier backtest
    es_results = [
        {'date': date(2026, 1, 12), 'direction': 'LONG', 'pnl': -206.25},
        {'date': date(2026, 1, 12), 'direction': 'SHORT', 'pnl': 725.00},
        {'date': date(2026, 1, 13), 'direction': 'SHORT', 'pnl': 2287.50},
        {'date': date(2026, 1, 14), 'direction': 'LONG', 'pnl': -150.00},
        {'date': date(2026, 1, 15), 'direction': 'SHORT', 'pnl': 2075.00},
        {'date': date(2026, 1, 16), 'direction': 'SHORT', 'pnl': 175.00},
        {'date': date(2026, 1, 20), 'direction': 'SHORT', 'pnl': -375.00},
        {'date': date(2026, 1, 21), 'direction': 'LONG', 'pnl': -225.00},
        {'date': date(2026, 1, 22), 'direction': 'SHORT', 'pnl': 150.00},
        {'date': date(2026, 1, 23), 'direction': 'SHORT', 'pnl': 1612.50},
        {'date': date(2026, 1, 26), 'direction': 'LONG', 'pnl': -206.25, 'stopped': True},
        {'date': date(2026, 1, 26), 'direction': 'LONG', 'pnl': 3868.75, 'reentry': True},
        {'date': date(2026, 1, 27), 'direction': 'LONG', 'pnl': 1431.25},
    ]

    # MES Results (3 contracts, 4R/8R) - from backtest just run
    mes_results = [
        {'date': date(2026, 1, 12), 'direction': 'LONG', 'pnl': -18.75},
        {'date': date(2026, 1, 12), 'direction': 'SHORT', 'pnl': 72.50},
        {'date': date(2026, 1, 13), 'direction': 'SHORT', 'pnl': 213.75},
        {'date': date(2026, 1, 14), 'direction': 'LONG', 'pnl': -15.00},
        {'date': date(2026, 1, 15), 'direction': 'SHORT', 'pnl': 200.62},
        {'date': date(2026, 1, 16), 'direction': 'SHORT', 'pnl': -24.38},
        {'date': date(2026, 1, 19), 'direction': 'SHORT', 'pnl': 54.38},
        {'date': date(2026, 1, 20), 'direction': 'SHORT', 'pnl': -37.50},
        {'date': date(2026, 1, 20), 'direction': 'SHORT', 'pnl': 301.88, 'reentry': True},
        {'date': date(2026, 1, 21), 'direction': 'LONG', 'pnl': -24.38},
        {'date': date(2026, 1, 22), 'direction': 'SHORT', 'pnl': 13.75},
        {'date': date(2026, 1, 23), 'direction': 'LONG', 'pnl': -18.75},
        {'date': date(2026, 1, 23), 'direction': 'SHORT', 'pnl': -24.38},
        {'date': date(2026, 1, 26), 'direction': 'LONG', 'pnl': 121.88},
        {'date': date(2026, 1, 27), 'direction': 'LONG', 'pnl': 143.12},
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

    # MES equity curve
    mes_equity = [0]
    mes_cumulative = 0
    for r in mes_results:
        mes_cumulative += r['pnl']
        mes_equity.append(mes_cumulative)

    # MES scaled to ES equivalent (10x)
    mes_equity_scaled = [x * 10 for x in mes_equity]

    ax1.plot(range(len(es_equity)), es_equity, color='#2196F3', marker='o', linewidth=2.5,
             markersize=8, label=f'ES: ${es_cumulative:+,.2f}')
    ax1.fill_between(range(len(es_equity)), 0, es_equity, alpha=0.15, color='#2196F3')

    ax1.plot(range(len(mes_equity_scaled)), mes_equity_scaled, color='#FF9800', marker='s', linewidth=2.5,
             markersize=8, label=f'MES (10x): ${mes_cumulative*10:+,.2f}', linestyle='--')
    ax1.fill_between(range(len(mes_equity_scaled)), 0, mes_equity_scaled, alpha=0.15, color='#FF9800')

    ax1.axhline(y=0, color='gray', linestyle='--', linewidth=1)
    ax1.set_xlabel('Trade Number', fontsize=12)
    ax1.set_ylabel('Cumulative P/L ($)', fontsize=12)
    ax1.set_title('Equity Curves - ES vs MES (Scaled to ES)', fontsize=14, fontweight='bold')
    ax1.legend(fontsize=11, loc='upper left')
    ax1.grid(True, alpha=0.3)

    # ==========================================================================
    # Plot 2: Summary Statistics Comparison
    # ==========================================================================
    ax2 = axes[0, 1]
    ax2.axis('off')

    # Calculate ES stats
    es_wins = len([r for r in es_results if r['pnl'] > 0])
    es_losses = len([r for r in es_results if r['pnl'] < 0])
    es_total = sum(r['pnl'] for r in es_results)
    es_long = sum(r['pnl'] for r in es_results if r['direction'] == 'LONG')
    es_short = sum(r['pnl'] for r in es_results if r['direction'] == 'SHORT')
    es_win_rate = es_wins / (es_wins + es_losses) * 100
    es_avg_win = sum(r['pnl'] for r in es_results if r['pnl'] > 0) / es_wins
    es_avg_loss = sum(r['pnl'] for r in es_results if r['pnl'] < 0) / es_losses
    es_pf = abs(sum(r['pnl'] for r in es_results if r['pnl'] > 0) / sum(r['pnl'] for r in es_results if r['pnl'] < 0))

    # Calculate MES stats
    mes_wins = len([r for r in mes_results if r['pnl'] > 0])
    mes_losses = len([r for r in mes_results if r['pnl'] < 0])
    mes_total = sum(r['pnl'] for r in mes_results)
    mes_long = sum(r['pnl'] for r in mes_results if r['direction'] == 'LONG')
    mes_short = sum(r['pnl'] for r in mes_results if r['direction'] == 'SHORT')
    mes_win_rate = mes_wins / (mes_wins + mes_losses) * 100
    mes_avg_win = sum(r['pnl'] for r in mes_results if r['pnl'] > 0) / mes_wins
    mes_avg_loss = sum(r['pnl'] for r in mes_results if r['pnl'] < 0) / mes_losses
    mes_pf = abs(sum(r['pnl'] for r in mes_results if r['pnl'] > 0) / sum(r['pnl'] for r in mes_results if r['pnl'] < 0))

    table_data = [
        ['Metric', 'ES', 'MES', 'MES (10x)'],
        ['Tick Value', '$12.50', '$1.25', '-'],
        ['Total Trades', f'{len(es_results)}', f'{len(mes_results)}', '-'],
        ['Win / Loss', f'{es_wins}W / {es_losses}L', f'{mes_wins}W / {mes_losses}L', '-'],
        ['Win Rate', f'{es_win_rate:.1f}%', f'{mes_win_rate:.1f}%', '-'],
        ['Total P/L', f'${es_total:+,.2f}', f'${mes_total:+,.2f}', f'${mes_total*10:+,.2f}'],
        ['Long P/L', f'${es_long:+,.2f}', f'${mes_long:+,.2f}', f'${mes_long*10:+,.2f}'],
        ['Short P/L', f'${es_short:+,.2f}', f'${mes_short:+,.2f}', f'${mes_short*10:+,.2f}'],
        ['Avg Win', f'${es_avg_win:+,.2f}', f'${mes_avg_win:+,.2f}', f'${mes_avg_win*10:+,.2f}'],
        ['Avg Loss', f'${es_avg_loss:+,.2f}', f'${mes_avg_loss:+,.2f}', f'${mes_avg_loss*10:+,.2f}'],
        ['Profit Factor', f'{es_pf:.2f}', f'{mes_pf:.2f}', '-'],
        ['Avg per Day', f'${es_total/15:+,.2f}', f'${mes_total/15:+,.2f}', f'${mes_total*10/15:+,.2f}'],
    ]

    table = ax2.table(cellText=table_data, loc='center', cellLoc='center',
                      colWidths=[0.25, 0.25, 0.25, 0.25])
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 1.7)

    # Style header row
    for j in range(4):
        table[(0, j)].set_facecolor('#1565C0')
        table[(0, j)].set_text_props(color='white', fontweight='bold')

    # Highlight P/L rows
    for i in [5, 6, 7]:
        table[(i, 1)].set_facecolor('#BBDEFB')
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
                 label, ha='center', va=va, fontsize=7, fontweight='bold')

    # ==========================================================================
    # Plot 4: Trade-by-Trade P/L - MES
    # ==========================================================================
    ax4 = axes[1, 1]

    mes_pnls = [r['pnl'] for r in mes_results]
    mes_colors = ['#4CAF50' if p > 0 else '#F44336' for p in mes_pnls]
    bars = ax4.bar(range(len(mes_pnls)), mes_pnls, color=mes_colors, edgecolor='black', linewidth=1)

    # Highlight re-entry
    for i, r in enumerate(mes_results):
        if r.get('reentry'):
            bars[i].set_hatch('///')
            bars[i].set_edgecolor('#FFD700')
            bars[i].set_linewidth(2)

    ax4.axhline(y=0, color='black', linewidth=1)
    ax4.set_xlabel('Trade Number', fontsize=12)
    ax4.set_ylabel('P/L ($)', fontsize=12)
    ax4.set_title(f'MES Trade-by-Trade P/L (Total: ${mes_total:+,.2f})', fontsize=14, fontweight='bold')
    ax4.grid(True, alpha=0.3, axis='y')

    # Add value labels
    for bar, pnl in zip(bars, mes_pnls):
        va = 'bottom' if pnl > 0 else 'top'
        offset = 10 if pnl > 0 else -10
        ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + offset,
                 f'${pnl:+,.0f}', ha='center', va=va, fontsize=7, fontweight='bold')

    plt.suptitle('ES vs MES Comparison | 15-Day Backtest | 3 Contracts | 4R/8R Targets\n'
                 'Same Strategy - Different Contract Size (MES = 1/10 ES)',
                 fontsize=16, fontweight='bold', y=1.02)

    plt.tight_layout()
    plt.savefig('backtest_es_mes_comparison.png', dpi=150, bbox_inches='tight')
    print('Saved: backtest_es_mes_comparison.png')
    plt.close()


if __name__ == '__main__':
    plot_es_mes_comparison()
