"""
Plot backtest summary with equity curve.
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import date

def plot_backtest_summary():
    """Create summary plot of backtest results."""

    # Results from 2nd FVG entry (conservative) - 5 days with data
    results_2nd_fvg = {
        'name': '2nd FVG + EMA Filters (Conservative)',
        'dates': [
            date(2026, 1, 21),
            date(2026, 1, 22),
            date(2026, 1, 23),
            date(2026, 1, 26),
            date(2026, 1, 27),
        ],
        'trades': [
            {'date': date(2026, 1, 21), 'pnl': 0, 'result': 'NO TRADE', 'reason': 'Filters rejected'},
            {'date': date(2026, 1, 22), 'pnl': 0, 'result': 'NO TRADE', 'reason': 'Not enough FVGs'},
            {'date': date(2026, 1, 23), 'pnl': 0, 'result': 'NO TRADE', 'reason': 'Bearish day'},
            {'date': date(2026, 1, 26), 'pnl': 3156.25, 'result': 'WIN', 'entry': '07:24'},
            {'date': date(2026, 1, 27), 'pnl': 0, 'result': 'NO TRADE', 'reason': 'No retrace'},
        ],
    }

    # Results from 1st FVG entry (aggressive) - 5 days with data
    results_1st_fvg = {
        'name': '1st FVG + EMA Filters (Aggressive)',
        'dates': [
            date(2026, 1, 21),
            date(2026, 1, 22),
            date(2026, 1, 23),
            date(2026, 1, 26),
            date(2026, 1, 27),
        ],
        'trades': [
            {'date': date(2026, 1, 21), 'pnl': 0, 'result': 'NO TRADE', 'reason': 'EMA not confirmed'},
            {'date': date(2026, 1, 22), 'pnl': 0, 'result': 'NO TRADE', 'reason': 'No retrace'},
            {'date': date(2026, 1, 23), 'pnl': 0, 'result': 'NO TRADE', 'reason': 'No bullish FVGs'},
            {'date': date(2026, 1, 26), 'pnl': -206.25, 'result': 'LOSS', 'entry': '05:18'},
            {'date': date(2026, 1, 27), 'pnl': 1418.75, 'result': 'WIN', 'entry': '10:03'},
        ],
    }

    # Create figure with subplots
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))

    # ==========================================================================
    # Plot 1: Equity Curves
    # ==========================================================================
    ax1 = axes[0, 0]

    for results, color, marker in [
        (results_2nd_fvg, 'blue', 'o'),
        (results_1st_fvg, 'orange', 's'),
    ]:
        dates = results['dates']
        equity = [0]
        cumulative = 0
        for trade in results['trades']:
            cumulative += trade['pnl']
            equity.append(cumulative)

        # Plot equity curve
        plot_dates = [dates[0]] + dates
        ax1.plot(plot_dates, equity, color=color, marker=marker, linewidth=2,
                 markersize=8, label=f"{results['name']}: ${cumulative:+,.2f}")
        ax1.fill_between(plot_dates, 0, equity, alpha=0.1, color=color)

    ax1.axhline(y=0, color='gray', linestyle='--', linewidth=1)
    ax1.set_xlabel('Date', fontsize=11)
    ax1.set_ylabel('Cumulative P/L ($)', fontsize=11)
    ax1.set_title('Equity Curve Comparison', fontsize=13, fontweight='bold')
    ax1.legend(loc='upper left', fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))

    # ==========================================================================
    # Plot 2: Daily P/L Bars
    # ==========================================================================
    ax2 = axes[0, 1]

    dates = results_2nd_fvg['dates']
    x = range(len(dates))
    width = 0.35

    pnl_2nd = [t['pnl'] for t in results_2nd_fvg['trades']]
    pnl_1st = [t['pnl'] for t in results_1st_fvg['trades']]

    ax2.bar([i - width/2 for i in x], pnl_2nd, width, label='2nd FVG',
                    color=['green' if p > 0 else 'red' if p < 0 else 'gray' for p in pnl_2nd])
    ax2.bar([i + width/2 for i in x], pnl_1st, width, label='1st FVG',
                    color=['lime' if p > 0 else 'salmon' if p < 0 else 'lightgray' for p in pnl_1st])

    ax2.axhline(y=0, color='black', linewidth=1)
    ax2.set_xlabel('Date', fontsize=11)
    ax2.set_ylabel('P/L ($)', fontsize=11)
    ax2.set_title('Daily P/L by Strategy', fontsize=13, fontweight='bold')
    ax2.set_xticks(x)
    ax2.set_xticklabels([d.strftime('%m/%d') for d in dates], rotation=45)
    ax2.legend(loc='upper left', fontsize=10)
    ax2.grid(True, alpha=0.3, axis='y')

    # ==========================================================================
    # Plot 3: Trade Statistics Table
    # ==========================================================================
    ax3 = axes[1, 0]
    ax3.axis('off')

    # Calculate stats
    def calc_stats(results):
        trades = [t for t in results['trades'] if t['pnl'] != 0]
        wins = [t for t in trades if t['pnl'] > 0]
        losses = [t for t in trades if t['pnl'] < 0]
        total_pnl = sum(t['pnl'] for t in trades)
        win_rate = len(wins) / len(trades) * 100 if trades else 0
        avg_win = sum(t['pnl'] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t['pnl'] for t in losses) / len(losses) if losses else 0
        profit_factor = abs(sum(t['pnl'] for t in wins) / sum(t['pnl'] for t in losses)) if losses else float('inf')

        return {
            'total_trades': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
        }

    stats_2nd = calc_stats(results_2nd_fvg)
    stats_1st = calc_stats(results_1st_fvg)

    table_data = [
        ['Metric', '2nd FVG (Conservative)', '1st FVG (Aggressive)'],
        ['Total Trades', str(stats_2nd['total_trades']), str(stats_1st['total_trades'])],
        ['Wins', str(stats_2nd['wins']), str(stats_1st['wins'])],
        ['Losses', str(stats_2nd['losses']), str(stats_1st['losses'])],
        ['Win Rate', f"{stats_2nd['win_rate']:.0f}%", f"{stats_1st['win_rate']:.0f}%"],
        ['Total P/L', f"${stats_2nd['total_pnl']:+,.2f}", f"${stats_1st['total_pnl']:+,.2f}"],
        ['Avg Win', f"${stats_2nd['avg_win']:+,.2f}", f"${stats_1st['avg_win']:+,.2f}"],
        ['Avg Loss', f"${stats_2nd['avg_loss']:+,.2f}" if stats_2nd['avg_loss'] else 'N/A',
                     f"${stats_1st['avg_loss']:+,.2f}" if stats_1st['avg_loss'] else 'N/A'],
        ['Profit Factor', f"{stats_2nd['profit_factor']:.2f}" if stats_2nd['profit_factor'] != float('inf') else 'Inf',
                          f"{stats_1st['profit_factor']:.2f}" if stats_1st['profit_factor'] != float('inf') else 'Inf'],
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
    for i, row in enumerate(table_data[1:], 1):
        if 'P/L' in row[0] or 'Win' in row[0] and 'Rate' not in row[0]:
            for j in [1, 2]:
                if '+' in row[j]:
                    table[(i, j)].set_facecolor('#C6EFCE')
                elif '-' in row[j]:
                    table[(i, j)].set_facecolor('#FFC7CE')

    ax3.set_title('Strategy Comparison Statistics', fontsize=13, fontweight='bold', pad=20)

    # ==========================================================================
    # Plot 4: Trade Details
    # ==========================================================================
    ax4 = axes[1, 1]
    ax4.axis('off')

    detail_text = """
    TRADE DETAILS (2nd FVG + EMA Filters - Recommended)
    ════════════════════════════════════════════════════

    1/21 (Tue): NO TRADE - EMA filters rejected (bearish cloud)
    1/22 (Wed): NO TRADE - Only 1 bullish FVG formed
    1/23 (Thu): NO TRADE - Bearish day, no bullish FVGs
    1/26 (Sun): WIN +$3,156.25
                Entry: 07:24 @ 6939.38 (2nd FVG after sweep)
                T1 (2R): 08:06 @ 6944.12 (+$237.50)
                T2 (4R): 08:48 @ 6948.88 (+$475.00)
                Runner:  15:15 @ 6988.25 (+$2,443.75)
    1/27 (Mon): NO TRADE - Price didn't retrace to FVG

    ════════════════════════════════════════════════════
    STRATEGY RULES:
    • Entry: 2nd Bullish FVG midpoint after sweep
    • Filters: EMA34 > EMA50 AND Price > Cloud
    • Stop: FVG low - 2 ticks
    • Exits: 1ct@2R, 1ct@4R, 1ct@EMA50 close below
    ════════════════════════════════════════════════════
    """

    ax4.text(0.05, 0.95, detail_text, transform=ax4.transAxes, fontsize=10,
             verticalalignment='top', fontfamily='monospace',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    plt.suptitle('ICT Strategy Backtest Summary - ES 3min\n'
                 'Period: Jan 21-27, 2026 (5 trading days)',
                 fontsize=14, fontweight='bold', y=1.02)

    plt.tight_layout()
    plt.savefig('backtest_summary.png', dpi=150, bbox_inches='tight')
    print('Summary saved to: backtest_summary.png')
    plt.close()


if __name__ == '__main__':
    plot_backtest_summary()
