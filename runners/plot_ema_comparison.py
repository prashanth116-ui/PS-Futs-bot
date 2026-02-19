"""
Compare EMA12 vs EMA50 runner exit strategies.
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
from datetime import date

def plot_ema_comparison():
    """Create EMA12 vs EMA50 runner exit comparison plot."""

    # EMA50 Results
    ema50_results = {
        'name': 'EMA50 Runner Exit',
        'color': '#673AB7',  # Deep Purple
        'trades': [
            {'date': date(2026, 1, 21), 'direction': 'LONG', 'pnl': -225.00, 'result': 'STOP', 'runner_exit': None, 'runner_price': None},
            {'date': date(2026, 1, 22), 'direction': 'SHORT', 'pnl': 662.50, 'result': 'WIN', 'runner_exit': '14:00', 'runner_price': 6960.75, 'runner_pnl': 212.50},
            {'date': date(2026, 1, 23), 'direction': 'SHORT', 'pnl': 1087.50, 'result': 'WIN', 'runner_exit': '14:00', 'runner_price': 6945.25, 'runner_pnl': 562.50},
            {'date': date(2026, 1, 26), 'direction': 'LONG', 'pnl': -206.25, 'result': 'STOP', 'runner_exit': None, 'runner_price': None},
            {'date': date(2026, 1, 26), 'direction': 'LONG', 'pnl': 3156.25, 'result': 'WIN', 'runner_exit': '15:15', 'runner_price': 6988.25, 'runner_pnl': 2443.75, 'reentry': True},
            {'date': date(2026, 1, 27), 'direction': 'LONG', 'pnl': 943.75, 'result': 'WIN', 'runner_exit': '12:15', 'runner_price': 7007.75, 'runner_pnl': 456.25},
        ],
    }

    # EMA12 Results
    ema12_results = {
        'name': 'EMA12 Runner Exit',
        'color': '#E91E63',  # Pink
        'trades': [
            {'date': date(2026, 1, 21), 'direction': 'LONG', 'pnl': -225.00, 'result': 'STOP', 'runner_exit': None, 'runner_price': None},
            {'date': date(2026, 1, 22), 'direction': 'SHORT', 'pnl': 525.00, 'result': 'WIN', 'runner_exit': '14:03', 'runner_price': 6963.50, 'runner_pnl': 75.00},
            {'date': date(2026, 1, 23), 'direction': 'SHORT', 'pnl': 1287.50, 'result': 'WIN', 'runner_exit': '13:06', 'runner_price': 6941.25, 'runner_pnl': 762.50},
            {'date': date(2026, 1, 26), 'direction': 'LONG', 'pnl': -206.25, 'result': 'STOP', 'runner_exit': None, 'runner_price': None},
            {'date': date(2026, 1, 26), 'direction': 'LONG', 'pnl': 2706.25, 'result': 'WIN', 'runner_exit': '10:27', 'runner_price': 6979.25, 'runner_pnl': 1993.75, 'reentry': True},
            {'date': date(2026, 1, 27), 'direction': 'LONG', 'pnl': 593.75, 'result': 'WIN', 'runner_exit': '10:27', 'runner_price': 7000.75, 'runner_pnl': 106.25},
        ],
    }

    # Create figure
    fig, axes = plt.subplots(2, 2, figsize=(18, 14))

    # ==========================================================================
    # Plot 1: Equity Curves
    # ==========================================================================
    ax1 = axes[0, 0]

    for results in [ema50_results, ema12_results]:
        equity = [0]
        cumulative = 0
        for trade in results['trades']:
            cumulative += trade['pnl']
            equity.append(cumulative)

        ax1.plot(range(len(equity)), equity, color=results['color'], marker='o', linewidth=2.5,
                 markersize=10, label=f"{results['name']}: ${cumulative:+,.2f}")
        ax1.fill_between(range(len(equity)), 0, equity, alpha=0.15, color=results['color'])

    ax1.axhline(y=0, color='gray', linestyle='--', linewidth=1)
    ax1.set_xlabel('Trade Number', fontsize=12)
    ax1.set_ylabel('Cumulative P/L ($)', fontsize=12)
    ax1.set_title('Equity Curve: EMA50 vs EMA12 Runner Exit', fontsize=14, fontweight='bold')
    ax1.legend(loc='upper left', fontsize=11)
    ax1.grid(True, alpha=0.3)

    # ==========================================================================
    # Plot 2: Trade-by-Trade P/L Comparison (Side by Side)
    # ==========================================================================
    ax2 = axes[0, 1]

    # Get trades that had runners (exclude stopped trades for runner comparison)
    trade_labels = ['1/21 L', '1/22 S', '1/23 S', '1/26 L', '1/26 L*', '1/27 L']
    x = range(len(trade_labels))
    width = 0.35

    pnl_ema50 = [t['pnl'] for t in ema50_results['trades']]
    pnl_ema12 = [t['pnl'] for t in ema12_results['trades']]

    colors_ema50 = ['#4CAF50' if p > 0 else '#F44336' for p in pnl_ema50]
    colors_ema12 = ['#81C784' if p > 0 else '#E57373' for p in pnl_ema12]

    bars1 = ax2.bar([i - width/2 for i in x], pnl_ema50, width, label='EMA50',
                    color=colors_ema50, edgecolor='#673AB7', linewidth=2)
    bars2 = ax2.bar([i + width/2 for i in x], pnl_ema12, width, label='EMA12',
                    color=colors_ema12, edgecolor='#E91E63', linewidth=2)

    ax2.axhline(y=0, color='black', linewidth=1)
    ax2.set_xlabel('Trade', fontsize=12)
    ax2.set_ylabel('P/L ($)', fontsize=12)
    ax2.set_title('Trade-by-Trade P/L Comparison', fontsize=14, fontweight='bold')
    ax2.set_xticks(x)
    ax2.set_xticklabels(trade_labels, fontsize=10)
    ax2.legend(loc='upper left', fontsize=11)
    ax2.grid(True, alpha=0.3, axis='y')

    # Add value labels
    for bar, pnl in zip(bars1, pnl_ema50):
        if abs(pnl) > 100:
            va = 'bottom' if pnl > 0 else 'top'
            offset = 80 if pnl > 0 else -80
            ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + offset,
                     f'${pnl:+,.0f}', ha='center', va=va, fontsize=8, fontweight='bold', color='#673AB7')

    for bar, pnl in zip(bars2, pnl_ema12):
        if abs(pnl) > 100:
            va = 'bottom' if pnl > 0 else 'top'
            offset = 80 if pnl > 0 else -80
            ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + offset,
                     f'${pnl:+,.0f}', ha='center', va=va, fontsize=8, fontweight='bold', color='#E91E63')

    # ==========================================================================
    # Plot 3: Runner P/L Only (Where applicable)
    # ==========================================================================
    ax3 = axes[1, 0]

    # Only trades with runners
    runner_labels = ['1/22 S', '1/23 S', '1/26 L*', '1/27 L']
    runner_ema50 = [212.50, 562.50, 2443.75, 456.25]
    runner_ema12 = [75.00, 762.50, 1993.75, 106.25]
    runner_diff = [e50 - e12 for e50, e12 in zip(runner_ema50, runner_ema12)]

    x_runner = range(len(runner_labels))

    ax3.bar([i - width/2 for i in x_runner], runner_ema50, width, label='EMA50 Runner',
                      color='#673AB7', alpha=0.8)
    ax3.bar([i + width/2 for i in x_runner], runner_ema12, width, label='EMA12 Runner',
                      color='#E91E63', alpha=0.8)

    ax3.set_xlabel('Trade', fontsize=12)
    ax3.set_ylabel('Runner P/L ($)', fontsize=12)
    ax3.set_title('Runner Contract P/L Only (1 contract)', fontsize=14, fontweight='bold')
    ax3.set_xticks(x_runner)
    ax3.set_xticklabels(runner_labels, fontsize=10)
    ax3.legend(loc='upper left', fontsize=11)
    ax3.grid(True, alpha=0.3, axis='y')

    # Add difference annotations
    for i, (e50, e12, diff) in enumerate(zip(runner_ema50, runner_ema12, runner_diff)):
        color = '#4CAF50' if diff > 0 else '#F44336'
        winner = 'EMA50' if diff > 0 else 'EMA12'
        ax3.annotate(f'{winner}\n${abs(diff):+,.0f}', xy=(i, max(e50, e12) + 100),
                     ha='center', fontsize=9, fontweight='bold', color=color)

    # ==========================================================================
    # Plot 4: Summary Table and Details
    # ==========================================================================
    ax4 = axes[1, 1]
    ax4.axis('off')

    detail_text = """
    EMA12 vs EMA50 RUNNER EXIT COMPARISON
    ══════════════════════════════════════════════════════════════════

    SUMMARY
    ────────────────────────────────────────────────────────────────
    Metric                    EMA50           EMA12         Winner
    ────────────────────────────────────────────────────────────────
    Total P/L                $+5,418.75      $+4,681.25     EMA50
    Runner P/L (4 trades)    $+3,675.00      $+2,937.50     EMA50
    Avg Hold Time            ~3+ hours       ~30-60 min     -
    ────────────────────────────────────────────────────────────────
    Difference: EMA50 wins by $737.50

    TRADE-BY-TRADE RUNNER COMPARISON
    ────────────────────────────────────────────────────────────────
    Date      Dir   EMA50 Exit   EMA50 $    EMA12 Exit   EMA12 $
    ────────────────────────────────────────────────────────────────
    1/22      S     14:00        $+212      14:03        $+75
    1/23      S     14:00        $+562      13:06        $+762  *
    1/26*     L     15:15        $+2,443    10:27        $+1,993
    1/27      L     12:15        $+456      10:27        $+106
    ────────────────────────────────────────────────────────────────
    * EMA12 won on 1/23 (+$200 better)
    * 1/26 re-entry trade

    KEY INSIGHT
    ════════════════════════════════════════════════════════════════
    On trending days (1/26), EMA50 captured 5 EXTRA HOURS of trend,
    resulting in $450 more profit on that single trade.

    EMA12 exits too early on normal pullbacks.

    RECOMMENDATION: Use EMA50 for runner exit
    ════════════════════════════════════════════════════════════════
    """

    ax4.text(0.02, 0.98, detail_text, transform=ax4.transAxes, fontsize=10,
             verticalalignment='top', fontfamily='monospace',
             bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.9))

    plt.suptitle('Runner Exit Strategy Comparison: EMA12 vs EMA50\n'
                 'ES 3-Minute | Re-entry Strategy | Jan 21-27, 2026',
                 fontsize=15, fontweight='bold', y=1.02)

    plt.tight_layout()
    plt.savefig('ema12_vs_ema50_comparison.png', dpi=150, bbox_inches='tight')
    print('Comparison saved to: ema12_vs_ema50_comparison.png')
    plt.close()


if __name__ == '__main__':
    plot_ema_comparison()
