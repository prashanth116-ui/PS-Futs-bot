"""
Plot ES 27-day backtest results (5-minute bars).
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
import numpy as np

# Trade data from 27-day backtest (5m bars)
trades = [
    {'date': '2025-12-29', 'direction': 'LONG', 'time': '13:00', 'pnl': 893.75},
    {'date': '2025-12-30', 'direction': 'SHORT', 'time': '13:30', 'pnl': 1412.50},
    {'date': '2026-01-02', 'direction': 'SHORT', 'time': '09:50', 'pnl': 2493.75},
    {'date': '2026-01-05', 'direction': 'LONG', 'time': '08:40', 'pnl': 1893.75},
    {'date': '2026-01-05', 'direction': 'SHORT', 'time': '12:45', 'pnl': 450.00},
    {'date': '2026-01-08', 'direction': 'LONG', 'time': '15:40', 'pnl': 506.25},
    {'date': '2026-01-08', 'direction': 'SHORT', 'time': '15:35', 'pnl': 350.00},
    {'date': '2026-01-12', 'direction': 'LONG', 'time': '05:00', 'pnl': 3462.50},
    {'date': '2026-01-12', 'direction': 'SHORT', 'time': '15:50', 'pnl': 643.75},
    {'date': '2026-01-13', 'direction': 'SHORT', 'time': '09:35', 'pnl': 968.75},
    {'date': '2026-01-15', 'direction': 'SHORT', 'time': '13:35', 'pnl': 568.75},
    {'date': '2026-01-16', 'direction': 'SHORT', 'time': '09:20', 'pnl': 1393.75},
    {'date': '2026-01-20', 'direction': 'SHORT', 'time': '12:40', 'pnl': 2437.50},
    {'date': '2026-01-21', 'direction': 'LONG', 'time': '13:20', 'pnl': 1287.50},
    {'date': '2026-01-27', 'direction': 'LONG', 'time': '10:05', 'pnl': 1187.50},
]

# Calculate cumulative P/L
cumulative = []
running_total = 0
for t in trades:
    running_total += t['pnl']
    cumulative.append(running_total)

# Create figure
fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle('ES 27-Day Backtest Results\nICT FVG Strategy with Mitigation Stop | 5-Minute Bars | 3 Contracts',
             fontsize=14, fontweight='bold')

# 1. Cumulative P/L over time
ax1 = axes[0, 0]
dates = [datetime.strptime(t['date'], '%Y-%m-%d') for t in trades]
ax1.fill_between(range(len(cumulative)), cumulative, alpha=0.3, color='#4CAF50')
ax1.plot(range(len(cumulative)), cumulative, color='#4CAF50', linewidth=3, marker='o', markersize=8)
ax1.set_xlabel('Trade #', fontsize=11)
ax1.set_ylabel('Cumulative P/L ($)', fontsize=11)
ax1.set_title('Equity Curve', fontsize=12, fontweight='bold')
ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
ax1.grid(True, alpha=0.3)
ax1.axhline(y=0, color='black', linestyle='-', linewidth=0.5)

# Add final value annotation
ax1.annotate(f'${cumulative[-1]:,.0f}', xy=(len(cumulative)-1, cumulative[-1]),
             xytext=(len(cumulative)-1, cumulative[-1]+1500),
             fontsize=12, fontweight='bold', color='#4CAF50',
             ha='center')

# 2. Individual trade P/L
ax2 = axes[0, 1]
colors = ['#4CAF50' if t['direction'] == 'LONG' else '#F44336' for t in trades]
bars = ax2.bar(range(len(trades)), [t['pnl'] for t in trades], color=colors, edgecolor='black', linewidth=1)
ax2.set_xlabel('Trade #', fontsize=11)
ax2.set_ylabel('P/L ($)', fontsize=11)
ax2.set_title('Individual Trade P/L (Green=LONG, Red=SHORT)', fontsize=12, fontweight='bold')
ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
ax2.grid(True, alpha=0.3, axis='y')

# Add average line
avg_pnl = sum(t['pnl'] for t in trades) / len(trades)
ax2.axhline(y=avg_pnl, color='#2196F3', linestyle='--', linewidth=2, label=f'Avg: ${avg_pnl:,.0f}')
ax2.legend()

# 3. Long vs Short performance
ax3 = axes[1, 0]
long_trades = [t for t in trades if t['direction'] == 'LONG']
short_trades = [t for t in trades if t['direction'] == 'SHORT']
long_pnl = sum(t['pnl'] for t in long_trades)
short_pnl = sum(t['pnl'] for t in short_trades)

x = np.arange(2)
width = 0.6
bars3 = ax3.bar(['LONG', 'SHORT'], [long_pnl, short_pnl], width,
                color=['#4CAF50', '#F44336'], edgecolor='black', linewidth=2)
ax3.set_ylabel('Total P/L ($)', fontsize=11)
ax3.set_title('Long vs Short Performance', fontsize=12, fontweight='bold')
ax3.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))

for bar, val, count in zip(bars3, [long_pnl, short_pnl], [len(long_trades), len(short_trades)]):
    ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 300,
             f'${val:,.0f}\n({count} trades)', ha='center', va='bottom',
             fontsize=11, fontweight='bold')

# 4. P/L by date
ax4 = axes[1, 1]
daily_pnl = {}
for t in trades:
    if t['date'] not in daily_pnl:
        daily_pnl[t['date']] = 0
    daily_pnl[t['date']] += t['pnl']

dates_sorted = sorted(daily_pnl.keys())
pnl_values = [daily_pnl[d] for d in dates_sorted]
colors4 = ['#4CAF50' if p > 0 else '#F44336' for p in pnl_values]

bars4 = ax4.bar(range(len(dates_sorted)), pnl_values, color=colors4, edgecolor='black', linewidth=1)
ax4.set_xlabel('Date', fontsize=11)
ax4.set_ylabel('Daily P/L ($)', fontsize=11)
ax4.set_title('P/L by Trading Day', fontsize=12, fontweight='bold')
ax4.set_xticks(range(len(dates_sorted)))
ax4.set_xticklabels([d[5:] for d in dates_sorted], rotation=45, ha='right', fontsize=9)
ax4.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
ax4.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
ax4.grid(True, alpha=0.3, axis='y')

# Summary box
total_pnl = sum(t['pnl'] for t in trades)
summary = f"""
BACKTEST SUMMARY
════════════════════════════════
Period:       Dec 28 - Jan 27
Trading Days: 27
Total Trades: 15
Win Rate:     100% (15W / 0L)
────────────────────────────────
Total P/L:    ${total_pnl:+,.2f}
Avg/Trade:    ${total_pnl/len(trades):+,.2f}
Avg/Day:      ${total_pnl/27:+,.2f}
────────────────────────────────
Long P/L:     ${long_pnl:+,.2f} ({len(long_trades)} trades)
Short P/L:    ${short_pnl:+,.2f} ({len(short_trades)} trades)
────────────────────────────────
Profit Factor: ∞ (no losses)
════════════════════════════════
"""

props = dict(boxstyle='round', facecolor='#E8F5E9', edgecolor='#4CAF50', linewidth=2)
fig.text(0.5, -0.02, summary, ha='center', fontsize=10, family='monospace',
         bbox=props, verticalalignment='top')

plt.tight_layout(rect=[0, 0.12, 1, 0.95])
filename = 'backtest_ES_27day_5m.png'
plt.savefig(filename, dpi=150, bbox_inches='tight', facecolor='white')
print(f'Saved: {filename}')
plt.close()
