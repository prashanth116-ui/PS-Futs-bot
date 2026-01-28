"""
Plot comparison of Opposing FVG vs MSS vs EMA50.
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
import numpy as np

# Data from 27-day backtest
strategies = ['EMA50\n(Baseline)', 'Opposing\nFVG', 'Market\nStructure\nShift']
total_pnl = [19950, 25900, 24950]
runner_pnl = [13375, 19325, 18375]
long_pnl = [9231, 12931, 11744]
short_pnl = [10719, 12969, 13206]

# Trade details
ema50_trades = [
    ('12/29', 'L', 894), ('12/30', 'S', 1412), ('01/02', 'S', 2494), ('01/05', 'L', 1894),
    ('01/05', 'S', 450), ('01/08', 'L', 506), ('01/08', 'S', 350), ('01/12', 'L', 3462),
    ('01/12', 'S', 644), ('01/13', 'S', 969), ('01/15', 'S', 569), ('01/16', 'S', 1394),
    ('01/20', 'S', 2438), ('01/21', 'L', 1288), ('01/27', 'L', 1188)
]
opp_fvg_trades = [
    ('12/29', 'L', 1219), ('12/30', 'S', 1412), ('01/02', 'S', 1806), ('01/05', 'L', 2244),
    ('01/05', 'S', 625), ('01/08', 'L', 506), ('01/08', 'S', 350), ('01/12', 'L', 3600),
    ('01/12', 'S', 631), ('01/13', 'S', 1956), ('01/15', 'S', 1844), ('01/16', 'S', 1906),
    ('01/20', 'S', 2438), ('01/21', 'L', 4175), ('01/27', 'L', 1188)
]
mss_trades = [
    ('12/29', 'L', 1219), ('12/30', 'S', 1412), ('01/02', 'S', 2894), ('01/05', 'L', 1981),
    ('01/05', 'S', 812), ('01/08', 'L', 506), ('01/08', 'S', 350), ('01/12', 'L', 2938),
    ('01/12', 'S', 631), ('01/13', 'S', 1631), ('01/15', 'S', 1844), ('01/16', 'S', 1194),
    ('01/20', 'S', 2438), ('01/21', 'L', 3912), ('01/27', 'L', 1188)
]

# Create figure
fig = plt.figure(figsize=(16, 12))

# 1. Total P/L comparison
ax1 = fig.add_subplot(2, 2, 1)
colors = ['#607D8B', '#4CAF50', '#2196F3']
bars = ax1.bar(strategies, total_pnl, color=colors, edgecolor='black', linewidth=2)
ax1.set_ylabel('Total P/L ($)', fontsize=12)
ax1.set_title('Total P/L Comparison (27 Days)', fontsize=12, fontweight='bold')
ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
for bar, val in zip(bars, total_pnl):
    improvement = (val - total_pnl[0]) / total_pnl[0] * 100
    label = f'${val:,.0f}' if val == total_pnl[0] else f'${val:,.0f}\n(+{improvement:.1f}%)'
    ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 300,
             label, ha='center', va='bottom', fontsize=10, fontweight='bold')
ax1.set_ylim(0, max(total_pnl) * 1.15)

# 2. Runner P/L comparison
ax2 = fig.add_subplot(2, 2, 2)
bars2 = ax2.bar(strategies, runner_pnl, color=colors, edgecolor='black', linewidth=2)
ax2.set_ylabel('Runner P/L ($)', fontsize=12)
ax2.set_title('Runner Contract P/L Only', fontsize=12, fontweight='bold')
ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
for bar, val in zip(bars2, runner_pnl):
    ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 200,
             f'${val:,.0f}', ha='center', va='bottom', fontsize=10, fontweight='bold')
ax2.set_ylim(0, max(runner_pnl) * 1.15)

# 3. Long vs Short breakdown
ax3 = fig.add_subplot(2, 2, 3)
x = np.arange(len(strategies))
width = 0.35
bars3a = ax3.bar(x - width/2, long_pnl, width, label='Long', color='#4CAF50', edgecolor='black')
bars3b = ax3.bar(x + width/2, short_pnl, width, label='Short', color='#F44336', edgecolor='black')
ax3.set_ylabel('P/L ($)', fontsize=12)
ax3.set_title('Long vs Short Performance', fontsize=12, fontweight='bold')
ax3.set_xticks(x)
ax3.set_xticklabels(strategies)
ax3.legend()
ax3.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))

# 4. Cumulative P/L over trades
ax4 = fig.add_subplot(2, 2, 4)

# Calculate cumulative
def cumulative(trades):
    cum = []
    total = 0
    for t in trades:
        total += t[2]
        cum.append(total)
    return cum

cum_ema50 = cumulative(ema50_trades)
cum_opp_fvg = cumulative(opp_fvg_trades)
cum_mss = cumulative(mss_trades)

x_trades = range(1, len(ema50_trades) + 1)
ax4.plot(x_trades, cum_ema50, 'o-', color='#607D8B', linewidth=2, markersize=6, label='EMA50')
ax4.plot(x_trades, cum_opp_fvg, 's-', color='#4CAF50', linewidth=2, markersize=6, label='Opposing FVG')
ax4.plot(x_trades, cum_mss, '^-', color='#2196F3', linewidth=2, markersize=6, label='MSS')
ax4.set_xlabel('Trade #', fontsize=12)
ax4.set_ylabel('Cumulative P/L ($)', fontsize=12)
ax4.set_title('Equity Curve Comparison', fontsize=12, fontweight='bold')
ax4.legend(loc='upper left')
ax4.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
ax4.grid(True, alpha=0.3)

# Add final values
ax4.annotate(f'${cum_ema50[-1]:,.0f}', xy=(15, cum_ema50[-1]), xytext=(15.5, cum_ema50[-1]),
             fontsize=9, fontweight='bold', color='#607D8B')
ax4.annotate(f'${cum_opp_fvg[-1]:,.0f}', xy=(15, cum_opp_fvg[-1]), xytext=(15.5, cum_opp_fvg[-1]),
             fontsize=9, fontweight='bold', color='#4CAF50')
ax4.annotate(f'${cum_mss[-1]:,.0f}', xy=(15, cum_mss[-1]), xytext=(15.5, cum_mss[-1]),
             fontsize=9, fontweight='bold', color='#2196F3')

plt.suptitle('ES Runner Exit Strategy Comparison\n27 Days (Dec 28 - Jan 27) | 5-Minute Bars | 3 Contracts',
             fontsize=14, fontweight='bold')

# Summary box
summary = """
SUMMARY (27 Days)
=====================================
                EMA50    OPP_FVG   MSS
-------------------------------------
Total P/L:    $19,950   $25,900  $24,950
Runner P/L:   $13,375   $19,325  $18,375
vs Baseline:     --      +29.8%   +25.1%
=====================================
WINNER: Opposing FVG (+$5,950)

ICT Concept: Exit when a Fair Value
Gap forms in the opposite direction,
signaling potential trend reversal.
"""

props = dict(boxstyle='round', facecolor='#E8F5E9', edgecolor='#4CAF50', linewidth=2)
fig.text(0.5, -0.02, summary, ha='center', fontsize=10, family='monospace',
         bbox=props, verticalalignment='top')

plt.tight_layout(rect=[0, 0.12, 1, 0.95])
filename = 'backtest_fvg_mss_comparison.png'
plt.savefig(filename, dpi=150, bbox_inches='tight', facecolor='white')
print(f'Saved: {filename}')
plt.close()
