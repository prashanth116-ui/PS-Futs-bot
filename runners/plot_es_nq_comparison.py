"""
Compare ES vs NQ backtest results.
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import date

def plot_comparison():
    """Create ES vs NQ comparison plot with re-entry strategy."""

    # ES Results (Re-entry Strategy: 1st FVG, if stopped -> 2nd FVG)
    es_results = {
        'symbol': 'ES',
        'name': 'E-mini S&P 500',
        'tick_value': 12.50,
        'point_value': 50.00,
        'dates': [
            date(2026, 1, 21),
            date(2026, 1, 22),
            date(2026, 1, 23),
            date(2026, 1, 26),
            date(2026, 1, 27),
        ],
        'trades': [
            {'date': date(2026, 1, 21), 'pnl': -225.00, 'result': 'LOSS', 'direction': 'LONG', 'entry': '08:57', 'type': 'STOP'},
            {'date': date(2026, 1, 22), 'pnl': 662.50, 'result': 'WIN', 'direction': 'SHORT', 'entry': '13:30'},
            {'date': date(2026, 1, 23), 'pnl': 1087.50, 'result': 'WIN', 'direction': 'SHORT', 'entry': '12:12'},
            {'date': date(2026, 1, 26), 'pnl': -206.25, 'result': 'LOSS', 'direction': 'LONG', 'entry': '05:18', 'type': 'STOP'},
            {'date': date(2026, 1, 26), 'pnl': 3156.25, 'result': 'WIN', 'direction': 'LONG', 'entry': '07:24', 'type': 'RE-ENTRY'},
            {'date': date(2026, 1, 27), 'pnl': 943.75, 'result': 'WIN', 'direction': 'LONG', 'entry': '10:03'},
            {'date': date(2026, 1, 27), 'pnl': 0, 'result': 'BREAKEVEN', 'direction': 'SHORT', 'entry': '12:21'},
        ],
    }

    # NQ Results (Re-entry Strategy)
    nq_results = {
        'symbol': 'NQ',
        'name': 'E-mini Nasdaq 100',
        'tick_value': 5.00,
        'point_value': 20.00,
        'dates': [
            date(2026, 1, 21),
            date(2026, 1, 22),
            date(2026, 1, 23),
            date(2026, 1, 26),
            date(2026, 1, 27),
        ],
        'trades': [
            {'date': date(2026, 1, 22), 'pnl': 1262.50, 'result': 'WIN', 'direction': 'SHORT', 'entry': '13:21'},
            {'date': date(2026, 1, 23), 'pnl': -543.75, 'result': 'LOSS', 'direction': 'LONG', 'entry': '08:51', 'type': 'STOP'},
        ],
    }

    # Create figure
    fig, axes = plt.subplots(2, 2, figsize=(18, 14))

    # ==========================================================================
    # Plot 1: Equity Curves
    # ==========================================================================
    ax1 = axes[0, 0]

    for results, color in [(es_results, '#2196F3'), (nq_results, '#FF9800')]:
        # Build equity curve from trades
        equity = [0]
        cumulative = 0
        trade_dates = [results['dates'][0]]  # Start date

        for trade in results['trades']:
            cumulative += trade['pnl']
            equity.append(cumulative)
            trade_dates.append(trade['date'])

        ax1.plot(range(len(equity)), equity, color=color, marker='o', linewidth=2.5,
                 markersize=8, label=f"{results['symbol']}: ${cumulative:+,.2f}")
        ax1.fill_between(range(len(equity)), 0, equity, alpha=0.15, color=color)

    ax1.axhline(y=0, color='gray', linestyle='--', linewidth=1)
    ax1.set_xlabel('Trade Number', fontsize=11)
    ax1.set_ylabel('Cumulative P/L ($)', fontsize=11)
    ax1.set_title('Equity Curve: ES vs NQ (Re-entry Strategy)', fontsize=13, fontweight='bold')
    ax1.legend(loc='upper left', fontsize=11)
    ax1.grid(True, alpha=0.3)

    # ==========================================================================
    # Plot 2: Trade-by-Trade P/L Comparison
    # ==========================================================================
    ax2 = axes[0, 1]

    # ES trades
    es_pnls = [t['pnl'] for t in es_results['trades']]
    es_colors = ['#4CAF50' if p > 0 else '#F44336' if p < 0 else '#9E9E9E' for p in es_pnls]
    es_x = range(len(es_pnls))

    bars1 = ax2.bar([x - 0.2 for x in es_x], es_pnls, 0.4, label='ES', color=es_colors,
                    edgecolor='#1565C0', linewidth=1.5)

    # NQ trades (offset on x-axis)
    nq_pnls = [t['pnl'] for t in nq_results['trades']]
    nq_colors = ['#81C784' if p > 0 else '#E57373' if p < 0 else '#BDBDBD' for p in nq_pnls]
    nq_x = range(len(es_pnls), len(es_pnls) + len(nq_pnls))

    bars2 = ax2.bar([x - 0.2 for x in nq_x], nq_pnls, 0.4, label='NQ', color=nq_colors,
                    edgecolor='#E65100', linewidth=1.5)

    ax2.axhline(y=0, color='black', linewidth=1)
    ax2.set_xlabel('Trade #', fontsize=11)
    ax2.set_ylabel('P/L ($)', fontsize=11)
    ax2.set_title('Trade-by-Trade P/L', fontsize=13, fontweight='bold')

    # X-axis labels
    all_labels = [f"ES{i+1}" for i in range(len(es_pnls))] + [f"NQ{i+1}" for i in range(len(nq_pnls))]
    ax2.set_xticks(range(len(all_labels)))
    ax2.set_xticklabels(all_labels, rotation=45, fontsize=9)
    ax2.grid(True, alpha=0.3, axis='y')

    # Add value labels on bars
    for bar, pnl in zip(bars1, es_pnls):
        if pnl != 0:
            va = 'bottom' if pnl > 0 else 'top'
            offset = 50 if pnl > 0 else -50
            ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + offset,
                     f'${pnl:+,.0f}', ha='center', va=va, fontsize=8, fontweight='bold')

    for bar, pnl in zip(bars2, nq_pnls):
        if pnl != 0:
            va = 'bottom' if pnl > 0 else 'top'
            offset = 50 if pnl > 0 else -50
            ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + offset,
                     f'${pnl:+,.0f}', ha='center', va=va, fontsize=8, fontweight='bold')

    # ==========================================================================
    # Plot 3: Statistics Comparison Table
    # ==========================================================================
    ax3 = axes[1, 0]
    ax3.axis('off')

    def calc_stats(results):
        trades = results['trades']
        wins = [t for t in trades if t['pnl'] > 0]
        losses = [t for t in trades if t['pnl'] < 0]
        breakeven = [t for t in trades if t['pnl'] == 0]
        total_pnl = sum(t['pnl'] for t in trades)
        win_rate = len(wins) / (len(wins) + len(losses)) * 100 if (wins or losses) else 0
        long_pnl = sum(t['pnl'] for t in trades if t.get('direction') == 'LONG')
        short_pnl = sum(t['pnl'] for t in trades if t.get('direction') == 'SHORT')
        reentries = len([t for t in trades if t.get('type') == 'RE-ENTRY'])

        return {
            'total_trades': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'breakeven': len(breakeven),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'long_pnl': long_pnl,
            'short_pnl': short_pnl,
            'reentries': reentries,
        }

    stats_es = calc_stats(es_results)
    stats_nq = calc_stats(nq_results)

    table_data = [
        ['Metric', 'ES (S&P 500)', 'NQ (Nasdaq 100)'],
        ['Contract Value', '$50/pt', '$20/pt'],
        ['Tick Value', '$12.50', '$5.00'],
        ['Total Trades', str(stats_es['total_trades']), str(stats_nq['total_trades'])],
        ['Wins', str(stats_es['wins']), str(stats_nq['wins'])],
        ['Losses', str(stats_es['losses']), str(stats_nq['losses'])],
        ['Win Rate', f"{stats_es['win_rate']:.0f}%", f"{stats_nq['win_rate']:.0f}%"],
        ['Re-entries', str(stats_es['reentries']), str(stats_nq['reentries'])],
        ['Long P/L', f"${stats_es['long_pnl']:+,.2f}", f"${stats_nq['long_pnl']:+,.2f}"],
        ['Short P/L', f"${stats_es['short_pnl']:+,.2f}", f"${stats_nq['short_pnl']:+,.2f}"],
        ['Total P/L', f"${stats_es['total_pnl']:+,.2f}", f"${stats_nq['total_pnl']:+,.2f}"],
    ]

    table = ax3.table(cellText=table_data, loc='center', cellLoc='center',
                      colWidths=[0.35, 0.35, 0.35])
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.2, 1.8)

    # Style header row
    for j in range(3):
        table[(0, j)].set_facecolor('#4472C4')
        table[(0, j)].set_text_props(color='white', fontweight='bold')

    # Color P/L cells
    for i in [8, 9, 10]:  # Long, Short, Total P/L rows
        for j in [1, 2]:
            val = table_data[i][j]
            if '+' in val:
                table[(i, j)].set_facecolor('#C6EFCE')
            elif '-' in val:
                table[(i, j)].set_facecolor('#FFC7CE')

    ax3.set_title('Strategy Statistics Comparison', fontsize=13, fontweight='bold', pad=20)

    # ==========================================================================
    # Plot 4: Trade Details
    # ==========================================================================
    ax4 = axes[1, 1]
    ax4.axis('off')

    detail_text = """
    RE-ENTRY STRATEGY RESULTS - Jan 21-27, 2026
    ════════════════════════════════════════════════════════════════

    ES (E-mini S&P 500) - 7 Trades
    ──────────────────────────────────────────────────────────────
    1/21 LONG   08:57  STOP        -$225.00   (1st FVG stopped)
    1/22 SHORT  13:30  WIN         +$662.50
    1/23 SHORT  12:12  WIN       +$1,087.50
    1/26 LONG   05:18  STOP        -$206.25   (1st FVG stopped)
    1/26 LONG   07:24  WIN       +$3,156.25   [RE-ENTRY on 2nd FVG]
    1/27 LONG   10:03  WIN         +$943.75
    1/27 SHORT  12:21  B/E           $0.00
    ──────────────────────────────────────────────────────────────
    ES TOTAL: 4W / 3L (57%)                  +$5,418.75

    NQ (E-mini Nasdaq 100) - 2 Trades
    ──────────────────────────────────────────────────────────────
    1/22 SHORT  13:21  WIN       +$1,262.50
    1/23 LONG   08:51  STOP        -$543.75   (no 2nd FVG for re-entry)
    ──────────────────────────────────────────────────────────────
    NQ TOTAL: 1W / 1L (50%)                    +$718.75

    ════════════════════════════════════════════════════════════════
    COMBINED TOTAL: 9 Trades | 5W / 4L (56%)  +$6,137.50
    ════════════════════════════════════════════════════════════════
    KEY: Re-entry on 1/26 turned -$206 loss into +$2,950 net gain!
    """

    ax4.text(0.02, 0.98, detail_text, transform=ax4.transAxes, fontsize=9.5,
             verticalalignment='top', fontfamily='monospace',
             bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))

    plt.suptitle('ICT Strategy: ES vs NQ Comparison\n'
                 'Re-entry Strategy (1st FVG → if stopped → 2nd FVG) | 3-Minute | Jan 21-27, 2026',
                 fontsize=14, fontweight='bold', y=1.02)

    plt.tight_layout()
    plt.savefig('es_nq_comparison.png', dpi=150, bbox_inches='tight')
    print('Comparison saved to: es_nq_comparison.png')
    plt.close()


if __name__ == '__main__':
    plot_comparison()
