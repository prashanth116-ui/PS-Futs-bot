"""
Compare ES vs NQ 30-day backtest results.
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
import numpy as np

# ES Results (15 days - Jan 11-27, 2026)
es_data = {
    'trades': 12,
    'wins': 12,
    'losses': 0,
    'win_rate': 100.0,
    'long_pnl': 9693.75,
    'short_pnl': 11150.00,
    'total_pnl': 20843.75,
    'avg_per_trade': 1736.98,
    'avg_per_day': 1389.58,
    'profit_factor': float('inf'),
    'reentries': 0,
    'tick_value': 12.50,
}

# NQ Results (15 days - Jan 11-27, 2026)
nq_data = {
    'trades': 3,
    'wins': 3,
    'losses': 0,
    'win_rate': 100.0,
    'long_pnl': 2307.50,
    'short_pnl': 920.00,
    'total_pnl': 3227.50,
    'avg_per_trade': 1075.83,
    'avg_per_day': 215.17,
    'profit_factor': float('inf'),
    'reentries': 0,
    'tick_value': 5.00,
}

# Create figure with subplots
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('ES vs NQ 15-Day Backtest Comparison\nICT FVG Strategy with Mitigation Stop | 3 Contracts | 4R/8R Exits',
             fontsize=14, fontweight='bold')

# 1. Total P/L Comparison
ax1 = axes[0, 0]
instruments = ['ES', 'NQ']
pnl_values = [es_data['total_pnl'], nq_data['total_pnl']]
colors = ['#2196F3', '#FF9800']
bars1 = ax1.bar(instruments, pnl_values, color=colors, edgecolor='black', linewidth=2)
ax1.set_ylabel('Total P/L ($)', fontsize=12)
ax1.set_title('Total Profit/Loss', fontsize=12, fontweight='bold')
ax1.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
for bar, val in zip(bars1, pnl_values):
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 500,
             f'${val:,.0f}', ha='center', va='bottom', fontsize=11, fontweight='bold')
ax1.set_ylim(0, max(pnl_values) * 1.15)
ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))

# 2. Trade Count & Win Rate
ax2 = axes[0, 1]
x = np.arange(2)
width = 0.35
trades = [es_data['trades'], nq_data['trades']]
wins = [es_data['wins'], nq_data['wins']]
bars2a = ax2.bar(x - width/2, trades, width, label='Total Trades', color='#607D8B', edgecolor='black')
bars2b = ax2.bar(x + width/2, wins, width, label='Wins', color='#4CAF50', edgecolor='black')
ax2.set_ylabel('Count', fontsize=12)
ax2.set_title('Trade Count & Wins', fontsize=12, fontweight='bold')
ax2.set_xticks(x)
ax2.set_xticklabels(instruments)
ax2.legend()
for bar, val in zip(bars2a, trades):
    ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
             str(val), ha='center', va='bottom', fontsize=10, fontweight='bold')
for bar, val in zip(bars2b, wins):
    ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
             str(val), ha='center', va='bottom', fontsize=10, fontweight='bold')

# 3. Avg P/L per Trade & per Day
ax3 = axes[1, 0]
x = np.arange(2)
width = 0.35
avg_trade = [es_data['avg_per_trade'], nq_data['avg_per_trade']]
avg_day = [es_data['avg_per_day'], nq_data['avg_per_day']]
bars3a = ax3.bar(x - width/2, avg_trade, width, label='Per Trade', color='#9C27B0', edgecolor='black')
bars3b = ax3.bar(x + width/2, avg_day, width, label='Per Day', color='#00BCD4', edgecolor='black')
ax3.set_ylabel('Average P/L ($)', fontsize=12)
ax3.set_title('Average P/L', fontsize=12, fontweight='bold')
ax3.set_xticks(x)
ax3.set_xticklabels(instruments)
ax3.legend()
ax3.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
for bar, val in zip(bars3a, avg_trade):
    ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 30,
             f'${val:,.0f}', ha='center', va='bottom', fontsize=9, fontweight='bold')
for bar, val in zip(bars3b, avg_day):
    ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 30,
             f'${val:,.0f}', ha='center', va='bottom', fontsize=9, fontweight='bold')

# 4. Long vs Short P/L
ax4 = axes[1, 1]
x = np.arange(2)
width = 0.35
long_pnl = [es_data['long_pnl'], nq_data['long_pnl']]
short_pnl = [es_data['short_pnl'], nq_data['short_pnl']]
bars4a = ax4.bar(x - width/2, long_pnl, width, label='Long', color='#4CAF50', edgecolor='black')
bars4b = ax4.bar(x + width/2, short_pnl, width, label='Short', color='#F44336', edgecolor='black')
ax4.set_ylabel('P/L ($)', fontsize=12)
ax4.set_title('Long vs Short Performance', fontsize=12, fontweight='bold')
ax4.set_xticks(x)
ax4.set_xticklabels(instruments)
ax4.legend()
ax4.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
for bar, val in zip(bars4a, long_pnl):
    ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 200,
             f'${val:,.0f}', ha='center', va='bottom', fontsize=9, fontweight='bold')
for bar, val in zip(bars4b, short_pnl):
    ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 200,
             f'${val:,.0f}', ha='center', va='bottom', fontsize=9, fontweight='bold')

# Add summary table
summary_text = """
COMPARISON SUMMARY (15 Days: Jan 11-27, 2026)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

                        ES                  NQ
───────────────────────────────────────────────────────────
Total Trades            12                  3
Win Rate               100%               100%
Total P/L          $20,844             $3,228
Avg per Trade       $1,737             $1,076
Avg per Day         $1,390               $215
Profit Factor          ∞                   ∞

WINNER: ES (6.5x more P/L, 4x more trades)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

plt.figtext(0.5, -0.02, summary_text, ha='center', fontsize=10, family='monospace',
            bbox=dict(boxstyle='round', facecolor='#E3F2FD', edgecolor='#2196F3', linewidth=2))

plt.tight_layout(rect=[0, 0.15, 1, 0.95])
filename = 'backtest_es_nq_15day_comparison.png'
plt.savefig(filename, dpi=150, bbox_inches='tight', facecolor='white')
print(f'Saved: {filename}')
plt.close()
