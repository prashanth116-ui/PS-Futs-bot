"""
Plot ICT market structure: Swings, Sweeps, and FVGs.

Clean visualization for manual analysis.
"""
from __future__ import annotations
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
from datetime import date, time as dt_time

from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.sweep import find_swing_highs, find_swing_lows
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations


def plot_ict_structure(
    symbol: str = "ES",
    session_date: date = None,
    interval: str = "3m",
    swing_left: int = 5,
    swing_right: int = 3,
    min_fvg_ticks: int = 2,
):
    """Plot ICT structure: swings, sweeps, FVGs."""
    if session_date is None:
        session_date = date.today()

    print(f"Fetching {interval} data for {symbol}...")
    all_bars = fetch_futures_bars(symbol=symbol, interval=interval, n_bars=2000)

    # Filter to session (premarket 4:00 to RTH close 16:00)
    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)

    session_bars = [
        b for b in all_bars
        if b.timestamp.date() == session_date
        and premarket_start <= b.timestamp.time() <= rth_end
    ]

    if not session_bars:
        print(f"No data for {session_date}")
        return

    print(f"Got {len(session_bars)} bars")

    # =========================================================================
    # DETECT SWING POINTS
    # =========================================================================
    swing_highs = find_swing_highs(session_bars, swing_left, swing_right)
    swing_lows = find_swing_lows(session_bars, swing_left, swing_right)
    print(f"Swings: {len(swing_highs)} highs, {len(swing_lows)} lows")

    # =========================================================================
    # DETECT FVGs
    # =========================================================================
    fvg_config = {
        "min_fvg_ticks": min_fvg_ticks,
        "tick_size": 0.25,
        "max_fvg_age_bars": 100,
        "invalidate_on_close_through": True,
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)
    update_all_fvg_mitigations(all_fvgs, session_bars, fvg_config)

    bullish_fvgs = [f for f in all_fvgs if f.direction == "BULLISH"]
    bearish_fvgs = [f for f in all_fvgs if f.direction == "BEARISH"]
    print(f"FVGs: {len(bullish_fvgs)} bullish, {len(bearish_fvgs)} bearish")

    # =========================================================================
    # IDENTIFY KEY LEVELS & SWEEPS
    # =========================================================================
    # Find LOD and HOD
    lod_bar_idx = min(range(len(session_bars)), key=lambda i: session_bars[i].low)
    hod_bar_idx = max(range(len(session_bars)), key=lambda i: session_bars[i].high)
    lod = session_bars[lod_bar_idx].low
    hod = session_bars[hod_bar_idx].high
    lod_time = session_bars[lod_bar_idx].timestamp
    hod_time = session_bars[hod_bar_idx].timestamp

    print(f"LOD: {lod} at {lod_time.strftime('%H:%M')}")
    print(f"HOD: {hod} at {hod_time.strftime('%H:%M')}")

    # Check for sweep at LOD (price wicked below then closed back)
    lod_bar = session_bars[lod_bar_idx]
    sweep_at_lod = lod_bar.close > lod + 0.25  # Closed at least 1 tick above low

    # =========================================================================
    # PLOTTING
    # =========================================================================
    fig, ax = plt.subplots(figsize=(20, 12))

    times = [b.timestamp for b in session_bars]

    # --- Plot candlesticks ---
    for i, bar in enumerate(session_bars):
        color = '#26a69a' if bar.close >= bar.open else '#ef5350'  # Green/Red
        # Wick
        ax.plot([times[i], times[i]], [bar.low, bar.high], color=color, linewidth=0.7)
        # Body
        ax.plot([times[i], times[i]], [bar.open, bar.close], color=color, linewidth=3)

    # --- Plot FVG zones as rectangles (only active/non-mitigated) ---
    active_fvgs = [f for f in all_fvgs if not f.mitigated]
    active_bullish = [f for f in active_fvgs if f.direction == "BULLISH"]
    active_bearish = [f for f in active_fvgs if f.direction == "BEARISH"]
    print(f"Active FVGs: {len(active_bullish)} bullish, {len(active_bearish)} bearish")

    for fvg in active_fvgs:
        fvg_time = session_bars[fvg.created_bar_index].timestamp
        end_time = times[-1]  # Extend to end of session

        # FVG color: green for bullish, red for bearish
        fvg_color = '#00ff00' if fvg.direction == "BULLISH" else '#ff0000'

        # Calculate width in data coordinates
        rect = mpatches.Rectangle(
            (mdates.date2num(fvg_time), fvg.low),
            mdates.date2num(end_time) - mdates.date2num(fvg_time),
            fvg.high - fvg.low,
            linewidth=1.5,
            edgecolor=fvg_color,
            facecolor=fvg_color,
            alpha=0.35,
            zorder=1,
        )
        ax.add_patch(rect)

        # Label the FVG with price range
        mid_time = session_bars[min(fvg.created_bar_index + 5, len(session_bars)-1)].timestamp
        ax.annotate(
            f'{fvg.low:.2f}-{fvg.high:.2f}',
            xy=(mid_time, fvg.midpoint),
            fontsize=7,
            color='darkgreen' if fvg.direction == "BULLISH" else 'darkred',
            alpha=0.8,
            ha='left',
        )

    # --- Plot swing highs with labels ---
    for i, sh in enumerate(swing_highs):
        sh_time = session_bars[sh.bar_index].timestamp
        ax.scatter([sh_time], [sh.price], marker='v', color='#ff5722', s=120,
                   edgecolors='#b71c1c', linewidths=2, zorder=5)
        # Label each swing high
        ax.annotate(
            f'SH{i+1}\n{sh.price:.2f}',
            xy=(sh_time, sh.price),
            xytext=(0, 12),
            textcoords='offset points',
            fontsize=8,
            fontweight='bold',
            color='#b71c1c',
            ha='center',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='white', edgecolor='#ff5722', alpha=0.8),
            zorder=6,
        )

    # --- Plot swing lows with labels ---
    for i, sl in enumerate(swing_lows):
        sl_time = session_bars[sl.bar_index].timestamp
        ax.scatter([sl_time], [sl.price], marker='^', color='#4caf50', s=120,
                   edgecolors='#1b5e20', linewidths=2, zorder=5)
        # Label each swing low
        ax.annotate(
            f'SL{i+1}\n{sl.price:.2f}',
            xy=(sl_time, sl.price),
            xytext=(0, -18),
            textcoords='offset points',
            fontsize=8,
            fontweight='bold',
            color='#1b5e20',
            ha='center',
            bbox=dict(boxstyle='round,pad=0.2', facecolor='white', edgecolor='#4caf50', alpha=0.8),
            zorder=6,
        )

    # --- Mark LOD with sweep annotation ---
    ax.axhline(y=lod, color='green', linestyle='-', linewidth=2, alpha=0.7)
    sweep_label = "SWEEP + LOD" if sweep_at_lod else "LOD"
    ax.annotate(
        f'{sweep_label}\n{lod:.2f}',
        xy=(lod_time, lod),
        xytext=(lod_time, lod - 8),
        fontsize=11,
        fontweight='bold',
        color='green',
        ha='center',
        arrowprops=dict(arrowstyle='->', color='green', lw=2),
        bbox=dict(boxstyle='round', facecolor='white', edgecolor='green', alpha=0.9),
        zorder=10,
    )

    # --- Mark HOD ---
    ax.axhline(y=hod, color='red', linestyle='-', linewidth=2, alpha=0.7)
    ax.annotate(
        f'HOD\n{hod:.2f}',
        xy=(hod_time, hod),
        xytext=(hod_time, hod + 8),
        fontsize=11,
        fontweight='bold',
        color='red',
        ha='center',
        arrowprops=dict(arrowstyle='->', color='red', lw=2),
        bbox=dict(boxstyle='round', facecolor='white', edgecolor='red', alpha=0.9),
        zorder=10,
    )

    # --- Mark RTH Open ---
    rth_start = dt_time(9, 30)
    for bar in session_bars:
        if bar.timestamp.time() >= rth_start:
            ax.axvline(x=bar.timestamp, color='blue', linestyle='--', linewidth=1.5, alpha=0.7)
            ax.annotate('RTH 9:30', xy=(bar.timestamp, ax.get_ylim()[1]),
                       xytext=(5, -20), textcoords='offset points',
                       fontsize=10, color='blue', fontweight='bold')
            break

    # --- Structure flow line (connect swings) ---
    all_swings = [(sh.bar_index, sh.price, 'H') for sh in swing_highs]
    all_swings += [(sl.bar_index, sl.price, 'L') for sl in swing_lows]
    all_swings.sort(key=lambda x: x[0])

    if len(all_swings) >= 2:
        for i in range(len(all_swings) - 1):
            idx1, price1, _ = all_swings[i]
            idx2, price2, _ = all_swings[i + 1]
            t1 = session_bars[idx1].timestamp
            t2 = session_bars[idx2].timestamp
            ax.plot([t1, t2], [price1, price2], color='gray', linewidth=1.2, alpha=0.5, zorder=2)

    # =========================================================================
    # FORMATTING
    # =========================================================================
    ax.set_ylabel('Price', fontsize=12)
    ax.set_xlabel('Time (ET)', fontsize=12)
    ax.set_title(
        f'{symbol} - {session_date} - ICT Structure ({interval}) - ACTIVE FVGs ONLY\n'
        f'Swings: L={swing_left} R={swing_right} | FVGs: min {min_fvg_ticks} ticks | '
        f'{len(swing_highs)} SH, {len(swing_lows)} SL | Active: {len(active_bullish)} Bull FVG, {len(active_bearish)} Bear FVG',
        fontsize=13
    )

    # Legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='v', color='w', markerfacecolor='#ff5722',
               markeredgecolor='#b71c1c', markersize=10, label='Swing High'),
        Line2D([0], [0], marker='^', color='w', markerfacecolor='#4caf50',
               markeredgecolor='#1b5e20', markersize=10, label='Swing Low'),
        mpatches.Patch(facecolor='#00ff00', alpha=0.3, edgecolor='#00ff00', label='Bullish FVG'),
        mpatches.Patch(facecolor='#ff0000', alpha=0.3, edgecolor='#ff0000', label='Bearish FVG'),
        Line2D([0], [0], color='green', linewidth=2, label='LOD'),
        Line2D([0], [0], color='red', linewidth=2, label='HOD'),
    ]
    ax.legend(handles=legend_elements, loc='upper left', fontsize=9)

    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    plt.xticks(rotation=45)

    plt.tight_layout()

    # Save
    output_file = f"ict_structure_{symbol}_{session_date}_{interval}.png"
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"\nChart saved to: {output_file}")
    plt.close()

    # =========================================================================
    # PRINT SUMMARY
    # =========================================================================
    print(f"\n{'='*70}")
    print("ICT STRUCTURE SUMMARY")
    print(f"{'='*70}")
    print(f"Session: {session_date} | Symbol: {symbol} | Interval: {interval}")
    print(f"Range: {lod:.2f} - {hod:.2f} ({hod-lod:.2f} pts)")
    print(f"\nLOD: {lod:.2f} at {lod_time.strftime('%H:%M')} {'<-- SWEEP (wick below, close above)' if sweep_at_lod else ''}")
    print(f"HOD: {hod:.2f} at {hod_time.strftime('%H:%M')}")

    print(f"\n{'='*70}")
    print("SWING HIGHS (SH) - Resistance / Liquidity Above")
    print(f"{'='*70}")
    for i, sh in enumerate(swing_highs):
        t = session_bars[sh.bar_index].timestamp.strftime('%H:%M')
        print(f"  SH{i+1}: {sh.price:.2f} at {t}")

    print(f"\n{'='*70}")
    print("SWING LOWS (SL) - Support / Liquidity Below")
    print(f"{'='*70}")
    for i, sl in enumerate(swing_lows):
        t = session_bars[sl.bar_index].timestamp.strftime('%H:%M')
        print(f"  SL{i+1}: {sl.price:.2f} at {t}")

    print(f"\n{'='*70}")
    print("ACTIVE BULLISH FVGs (entry zones for LONG)")
    print(f"{'='*70}")
    if active_bullish:
        for fvg in active_bullish:
            t = fvg.created_at.strftime('%H:%M')
            size = fvg.metadata.get('gap_size_ticks', 0)
            print(f"  {t} | {fvg.low:.2f} - {fvg.high:.2f} | {size:.0f} ticks")
    else:
        print("  None")

    print(f"\n{'='*70}")
    print("ACTIVE BEARISH FVGs (entry zones for SHORT)")
    print(f"{'='*70}")
    if active_bearish:
        for fvg in active_bearish:
            t = fvg.created_at.strftime('%H:%M')
            size = fvg.metadata.get('gap_size_ticks', 0)
            print(f"  {t} | {fvg.low:.2f} - {fvg.high:.2f} | {size:.0f} ticks")
    else:
        print("  None")

    return output_file


if __name__ == "__main__":
    target_date = date(2026, 1, 26)

    symbol = sys.argv[1] if len(sys.argv) > 1 else "ES"
    interval = sys.argv[2] if len(sys.argv) > 2 else "3m"
    swing_left = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    swing_right = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    min_fvg = int(sys.argv[5]) if len(sys.argv) > 5 else 2

    plot_ict_structure(symbol, target_date, interval, swing_left, swing_right, min_fvg)
