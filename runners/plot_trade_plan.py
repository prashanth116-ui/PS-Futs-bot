"""
Plot ICT trade plan with entry, stop, and R:R targets.
"""
from __future__ import annotations
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
from datetime import date, time as dt_time, timedelta

from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.sweep import find_swing_highs, find_swing_lows
from strategies.ict.signals.fvg import detect_fvgs, update_all_fvg_mitigations


def plot_trade_plan(
    symbol: str = "ES",
    session_date: date = None,
    interval: str = "3m",
    fvg_entry_num: int = 2,  # Which FVG to enter (1st, 2nd, etc.)
    rr_targets: list = [2.0, 3.0],  # R:R ratios for targets
    stop_buffer_ticks: int = 2,  # Buffer below FVG for stop
    tick_size: float = 0.25,
    contracts: int = 1,  # Number of contracts
    exit_plan: list = None,  # Custom exit plan: [(contracts, rr_or_condition), ...]
    require_ema_crossover: bool = False,  # Require EMA34 > EMA50 for entry
    require_price_above_cloud: bool = False,  # Require price above both EMAs
    require_ema_stack: bool = False,  # Require EMA9/12 above EMA34/50 for longs
    trade_direction: str = "LONG",  # "LONG", "SHORT", or "BOTH"
    runner_exit_ema: int = 50,  # EMA period for runner exit (12, 34, or 50)
    save_plot: bool = True,
):
    """Plot trade plan with entry at specified FVG and R:R targets."""
    if session_date is None:
        session_date = date.today()

    print(f"Fetching {interval} data for {symbol}...")
    all_bars = fetch_futures_bars(symbol=symbol, interval=interval, n_bars=2000)

    # Filter to session
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

    # Detect swings
    swing_left, swing_right = 12, 6
    swing_highs = find_swing_highs(session_bars, swing_left, swing_right)
    swing_lows = find_swing_lows(session_bars, swing_left, swing_right)

    # Detect FVGs
    fvg_config = {
        "min_fvg_ticks": 4,
        "tick_size": tick_size,
        "max_fvg_age_bars": 100,
        "invalidate_on_close_through": True,
    }
    all_fvgs = detect_fvgs(session_bars, fvg_config)
    update_all_fvg_mitigations(all_fvgs, session_bars, fvg_config)

    # Get active FVGs based on trade direction
    is_long = trade_direction == "LONG"
    fvg_direction = "BULLISH" if is_long else "BEARISH"
    active_fvgs = [f for f in all_fvgs if f.direction == fvg_direction and not f.mitigated]
    active_fvgs.sort(key=lambda f: f.created_bar_index)

    if len(active_fvgs) < fvg_entry_num:
        print(f"Not enough active {fvg_direction.lower()} FVGs. Found {len(active_fvgs)}, need {fvg_entry_num}")
        return

    # Get the entry FVG (2nd one by default)
    entry_fvg = active_fvgs[fvg_entry_num - 1]
    prior_fvg = active_fvgs[fvg_entry_num - 2] if fvg_entry_num > 1 else None

    print(f"\n{'='*70}")
    print(f"TRADE PLAN - {trade_direction}")
    print(f"{'='*70}")

    if prior_fvg:
        print(f"Prior FVG (1st): {prior_fvg.low:.2f} - {prior_fvg.high:.2f} at {prior_fvg.created_at.strftime('%H:%M')}")

    print(f"Entry FVG (2nd): {entry_fvg.low:.2f} - {entry_fvg.high:.2f} at {entry_fvg.created_at.strftime('%H:%M')}")

    # Calculate trade levels - different for LONG vs SHORT
    entry_price = entry_fvg.midpoint
    if is_long:
        stop_price = entry_fvg.low - (stop_buffer_ticks * tick_size)
        risk = entry_price - stop_price
    else:
        # SHORT: stop above FVG high
        stop_price = entry_fvg.high + (stop_buffer_ticks * tick_size)
        risk = stop_price - entry_price
    risk_ticks = risk / tick_size

    print(f"\nDirection: {trade_direction}")
    print(f"Entry (midpoint): {entry_price:.2f}")
    if is_long:
        print(f"Stop (FVG low - {stop_buffer_ticks} ticks): {stop_price:.2f}")
    else:
        print(f"Stop (FVG high + {stop_buffer_ticks} ticks): {stop_price:.2f}")
    print(f"Risk: {risk:.2f} pts ({risk_ticks:.0f} ticks)")

    # =========================================================================
    # CALCULATE EMAs (needed for exit logic)
    # =========================================================================
    def calculate_ema(closes: list, period: int) -> list:
        """Calculate EMA for a list of closes."""
        ema = []
        multiplier = 2 / (period + 1)

        for i, close in enumerate(closes):
            if i < period - 1:
                ema.append(None)  # Not enough data
            elif i == period - 1:
                # First EMA is SMA
                sma = sum(closes[:period]) / period
                ema.append(sma)
            else:
                # EMA = (close * mult) + (prev_ema * (1 - mult))
                ema.append((close * multiplier) + (ema[-1] * (1 - multiplier)))

        return ema

    closes = [b.close for b in session_bars]
    ema_9 = calculate_ema(closes, 9)
    ema_12 = calculate_ema(closes, 12)
    ema_34 = calculate_ema(closes, 34)
    ema_50 = calculate_ema(closes, 50)

    # Calculate targets - different for LONG vs SHORT
    targets = []
    for rr in rr_targets:
        if is_long:
            target = entry_price + (rr * risk)
            print(f"Target {rr}R: {target:.2f} (+{rr * risk:.2f} pts)")
        else:
            target = entry_price - (rr * risk)
            print(f"Target {rr}R: {target:.2f} (-{rr * risk:.2f} pts)")
        targets.append((rr, target))

    # Find when entry would trigger (price touches FVG midpoint)
    # With optional EMA filters
    entry_bar_idx = None
    entry_time = None
    entry_rejected_reason = None
    ema_crossover_bar = None
    price_above_cloud_bar = None

    for i in range(entry_fvg.created_bar_index + 1, len(session_bars)):
        bar = session_bars[i]
        bar_ema9 = ema_9[i] if i < len(ema_9) and ema_9[i] is not None else None
        bar_ema12 = ema_12[i] if i < len(ema_12) and ema_12[i] is not None else None
        bar_ema34 = ema_34[i] if i < len(ema_34) and ema_34[i] is not None else None
        bar_ema50 = ema_50[i] if i < len(ema_50) and ema_50[i] is not None else None

        # Check if price reaches entry level - LONG: price comes down, SHORT: price goes up
        price_at_entry = bar.low <= entry_price if is_long else bar.high >= entry_price
        if price_at_entry:
            # Check EMA filters
            ema_crossover_ok = True
            price_cloud_ok = True
            ema_stack_ok = True

            if require_ema_crossover and bar_ema34 is not None and bar_ema50 is not None:
                # LONG: EMA34 > EMA50, SHORT: EMA34 < EMA50
                ema_crossover_ok = bar_ema34 > bar_ema50 if is_long else bar_ema34 < bar_ema50
                if ema_crossover_ok and ema_crossover_bar is None:
                    ema_crossover_bar = i

            if require_price_above_cloud and bar_ema34 is not None and bar_ema50 is not None:
                # LONG: price above cloud, SHORT: price below cloud
                if is_long:
                    cloud_top = max(bar_ema34, bar_ema50)
                    price_cloud_ok = bar.close > cloud_top
                else:
                    cloud_bottom = min(bar_ema34, bar_ema50)
                    price_cloud_ok = bar.close < cloud_bottom
                if price_cloud_ok and price_above_cloud_bar is None:
                    price_above_cloud_bar = i

            # Check EMA stack: LONG: 9>12>34>50, SHORT: 9<12<34<50
            if require_ema_stack and all(v is not None for v in [bar_ema9, bar_ema12, bar_ema34, bar_ema50]):
                if is_long:
                    ema_stack_ok = (bar_ema9 > bar_ema12 > bar_ema34 > bar_ema50)
                else:
                    ema_stack_ok = (bar_ema9 < bar_ema12 < bar_ema34 < bar_ema50)

            # Entry valid only if all filters pass
            if ema_crossover_ok and price_cloud_ok and ema_stack_ok:
                entry_bar_idx = i
                entry_time = bar.timestamp
                break
            else:
                if not ema_crossover_ok:
                    entry_rejected_reason = f"EMA crossover not confirmed (need 34{'>' if is_long else '<'}50)"
                elif not price_cloud_ok:
                    entry_rejected_reason = f"Price not {'above' if is_long else 'below'} cloud"
                elif not ema_stack_ok:
                    stack_str = "9>12>34>50" if is_long else "9<12<34<50"
                    entry_rejected_reason = f"EMA stack not aligned (need {stack_str})"

    entry_triggered = entry_bar_idx is not None and entry_time is not None

    if entry_triggered:
        filter_str = ""
        if require_ema_crossover:
            filter_str += " [EMA crossover OK]"
        if require_price_above_cloud:
            filter_str += " [Above cloud OK]"
        if require_ema_stack:
            filter_str += " [EMA stack OK]"
        print(f"\nEntry triggered at: {entry_time.strftime('%H:%M')}{filter_str}")
    else:
        reason = f" ({entry_rejected_reason})" if entry_rejected_reason else ""
        print(f"\nEntry NOT triggered{reason}")
        print("NO TRADE TAKEN")
        entry_bar_idx = entry_fvg.created_bar_index + 5  # Default for plotting only

    # =========================================================================
    # MULTI-CONTRACT EXIT SIMULATION
    # =========================================================================
    # Exit plan: 1 contract @ 2R, 1 contract @ 4R, 1 contract @ EMA50 close below

    exits = []  # List of (time, price, contracts, exit_type, pnl)
    remaining_contracts = contracts
    stopped_out = False

    # Add 4R target to the list
    if is_long:
        target_4r = entry_price + (4.0 * risk)
    else:
        target_4r = entry_price - (4.0 * risk)

    if entry_triggered and entry_bar_idx:
        for i in range(entry_bar_idx + 1, len(session_bars)):
            if remaining_contracts <= 0:
                break

            bar = session_bars[i]
            bar_ema50 = ema_50[i] if i < len(ema_50) and ema_50[i] is not None else None

            # Check stop first (worst case) - applies to ALL remaining contracts
            # LONG: stop hit when price goes DOWN (bar.low <= stop)
            # SHORT: stop hit when price goes UP (bar.high >= stop)
            stop_hit = bar.low <= stop_price if is_long else bar.high >= stop_price
            if stop_hit:
                if is_long:
                    pnl = (stop_price - entry_price) * remaining_contracts
                else:
                    pnl = (entry_price - stop_price) * remaining_contracts
                exits.append({
                    'time': bar.timestamp,
                    'price': stop_price,
                    'contracts': remaining_contracts,
                    'type': 'STOP',
                    'pnl': pnl,
                    'bar_idx': i,
                })
                remaining_contracts = 0
                stopped_out = True
                break

            # Check 2R target - exit 1 contract
            # LONG: target hit when price goes UP (bar.high >= target)
            # SHORT: target hit when price goes DOWN (bar.low <= target)
            target_2r_hit = bar.high >= targets[0][1] if is_long else bar.low <= targets[0][1]
            if remaining_contracts >= 3 and target_2r_hit:
                if is_long:
                    pnl = (targets[0][1] - entry_price) * 1
                else:
                    pnl = (entry_price - targets[0][1]) * 1
                exits.append({
                    'time': bar.timestamp,
                    'price': targets[0][1],
                    'contracts': 1,
                    'type': 'TARGET_2R',
                    'pnl': pnl,
                    'bar_idx': i,
                })
                remaining_contracts -= 1

            # Check 4R target - exit 1 contract
            target_4r_hit = bar.high >= target_4r if is_long else bar.low <= target_4r
            if remaining_contracts >= 2 and target_4r_hit:
                if is_long:
                    pnl = (target_4r - entry_price) * 1
                else:
                    pnl = (entry_price - target_4r) * 1
                exits.append({
                    'time': bar.timestamp,
                    'price': target_4r,
                    'contracts': 1,
                    'type': 'TARGET_4R',
                    'pnl': pnl,
                    'bar_idx': i,
                })
                remaining_contracts -= 1

            # Check EMA exit - exit last contract (runner)
            # LONG: close below EMA, SHORT: close above EMA
            # Use configurable EMA period (12, 34, or 50)
            if runner_exit_ema == 12:
                bar_ema_exit = ema_12[i] if i < len(ema_12) and ema_12[i] is not None else None
            elif runner_exit_ema == 34:
                bar_ema_exit = ema_34[i] if i < len(ema_34) and ema_34[i] is not None else None
            else:
                bar_ema_exit = bar_ema50

            if remaining_contracts == 1 and bar_ema_exit is not None:
                ema_exit_triggered = bar.close < bar_ema_exit if is_long else bar.close > bar_ema_exit
                if ema_exit_triggered:
                    if is_long:
                        pnl = (bar.close - entry_price) * 1
                    else:
                        pnl = (entry_price - bar.close) * 1
                    exits.append({
                        'time': bar.timestamp,
                        'price': bar.close,
                        'contracts': 1,
                        'type': f'EMA{runner_exit_ema}_EXIT',
                        'pnl': pnl,
                        'bar_idx': i,
                    })
                    remaining_contracts -= 1

        # If still holding at EOD, close at last price
        if remaining_contracts > 0:
            last_bar = session_bars[-1]
            if is_long:
                pnl = (last_bar.close - entry_price) * remaining_contracts
            else:
                pnl = (entry_price - last_bar.close) * remaining_contracts
            exits.append({
                'time': last_bar.timestamp,
                'price': last_bar.close,
                'contracts': remaining_contracts,
                'type': 'EOD_CLOSE',
                'pnl': pnl,
                'bar_idx': len(session_bars) - 1,
            })

    # Print trade results
    total_pnl = 0
    total_pnl_dollars = 0
    tick_value = 12.50  # ES tick value

    if entry_triggered and exits:
        print(f"\n{'='*70}")
        print(f"TRADE RESULTS - {contracts} CONTRACTS")
        print(f"{'='*70}")

        for exit in exits:
            pnl_ticks = exit['pnl'] / tick_size
            pnl_dollars = pnl_ticks * tick_value
            total_pnl += exit['pnl']
            total_pnl_dollars += pnl_dollars
            print(f"  {exit['type']:12} | {exit['contracts']} ct @ {exit['price']:.2f} | "
                  f"{exit['time'].strftime('%H:%M')} | {exit['pnl']:+.2f} pts | ${pnl_dollars:+.2f}")

        print(f"\n  {'TOTAL':12} | {contracts} ct | {total_pnl:+.2f} pts | ${total_pnl_dollars:+.2f}")
    else:
        print(f"\n{'='*70}")
        print("NO TRADE - Entry conditions not met")
        print(f"{'='*70}")

    # For backward compatibility
    exit_type = exits[-1]['type'] if exits else None
    exit_price = exits[-1]['price'] if exits else None
    exit_time = exits[-1]['time'] if exits else None
    pnl = total_pnl

    # =========================================================================
    # PLOTTING
    # =========================================================================
    fig, ax = plt.subplots(figsize=(20, 12))

    times = [b.timestamp for b in session_bars]

    # Plot EMA cloud first (behind everything)
    valid_indices = [i for i in range(len(times)) if ema_34[i] is not None and ema_50[i] is not None]
    if valid_indices:
        cloud_times = [times[i] for i in valid_indices]
        cloud_ema34 = [ema_34[i] for i in valid_indices]
        cloud_ema50 = [ema_50[i] for i in valid_indices]

        # Fill between EMAs (cloud)
        ax.fill_between(
            cloud_times, cloud_ema34, cloud_ema50,
            where=[e34 >= e50 for e34, e50 in zip(cloud_ema34, cloud_ema50)],
            color='green', alpha=0.15, label='Bullish Cloud', zorder=0
        )
        ax.fill_between(
            cloud_times, cloud_ema34, cloud_ema50,
            where=[e34 < e50 for e34, e50 in zip(cloud_ema34, cloud_ema50)],
            color='red', alpha=0.15, label='Bearish Cloud', zorder=0
        )

        # Plot EMA lines
        ax.plot(cloud_times, cloud_ema34, color='#2196F3', linewidth=1.5,
                label=f'EMA 34', alpha=0.8, zorder=2)
        ax.plot(cloud_times, cloud_ema50, color='#FF9800', linewidth=1.5,
                label=f'EMA 50', alpha=0.8, zorder=2)

        # Plot EMA 9 and 12 if stack filter is enabled
        if require_ema_stack:
            cloud_ema9 = [ema_9[i] for i in valid_indices]
            cloud_ema12 = [ema_12[i] for i in valid_indices]
            ax.plot(cloud_times, cloud_ema9, color='#4CAF50', linewidth=1.2,
                    label=f'EMA 9', alpha=0.7, zorder=2, linestyle='-')
            ax.plot(cloud_times, cloud_ema12, color='#8BC34A', linewidth=1.2,
                    label=f'EMA 12', alpha=0.7, zorder=2, linestyle='-')

    # Plot candlesticks
    for i, bar in enumerate(session_bars):
        color = '#26a69a' if bar.close >= bar.open else '#ef5350'
        ax.plot([times[i], times[i]], [bar.low, bar.high], color=color, linewidth=0.7)
        ax.plot([times[i], times[i]], [bar.open, bar.close], color=color, linewidth=3)

    # Plot active FVGs
    for fvg in active_fvgs:
        fvg_time = session_bars[fvg.created_bar_index].timestamp
        end_time = times[-1]

        # Highlight entry FVG differently - green for bullish, red for bearish
        base_color = '#00ff00' if is_long else '#ff4444'
        light_color = '#90EE90' if is_long else '#ffaaaa'

        if fvg == entry_fvg:
            fvg_color = base_color
            alpha = 0.5
            linewidth = 2
        elif fvg == prior_fvg:
            fvg_color = light_color
            alpha = 0.3
            linewidth = 1
        else:
            fvg_color = base_color
            alpha = 0.2
            linewidth = 1

        rect = mpatches.Rectangle(
            (mdates.date2num(fvg_time), fvg.low),
            mdates.date2num(end_time) - mdates.date2num(fvg_time),
            fvg.high - fvg.low,
            linewidth=linewidth,
            edgecolor=fvg_color,
            facecolor=fvg_color,
            alpha=alpha,
            zorder=1,
        )
        ax.add_patch(rect)

    # Plot swing points
    for sh in swing_highs:
        sh_time = session_bars[sh.bar_index].timestamp
        ax.scatter([sh_time], [sh.price], marker='v', color='#ff5722', s=80,
                   edgecolors='#b71c1c', linewidths=1.5, zorder=4)

    for sl in swing_lows:
        sl_time = session_bars[sl.bar_index].timestamp
        ax.scatter([sl_time], [sl.price], marker='^', color='#4caf50', s=80,
                   edgecolors='#1b5e20', linewidths=1.5, zorder=4)

    # =========================================================================
    # TRADE VISUALIZATION
    # =========================================================================

    # Entry line - blue for long, orange for short
    entry_start = session_bars[entry_fvg.created_bar_index].timestamp
    entry_color = 'blue' if is_long else '#FF6600'
    ax.hlines(y=entry_price, xmin=entry_start, xmax=times[-1],
              color=entry_color, linestyle='-', linewidth=2, label=f'{trade_direction} Entry: {entry_price:.2f} (3 cts)')

    # Stop line
    ax.hlines(y=stop_price, xmin=entry_start, xmax=times[-1],
              color='red', linestyle='--', linewidth=2, label=f'Stop: {stop_price:.2f}')

    # Target lines - 2R and 4R
    ax.hlines(y=targets[0][1], xmin=entry_start, xmax=times[-1],
              color='#FFD700', linestyle='--', linewidth=2, label=f'T1 (2R): {targets[0][1]:.2f} - 1 ct')
    ax.hlines(y=target_4r, xmin=entry_start, xmax=times[-1],
              color='#FFA500', linestyle='--', linewidth=2, label=f'T2 (4R): {target_4r:.2f} - 1 ct')

    # Mark entry point
    if entry_time:
        edge_color = 'darkblue' if is_long else '#CC4400'
        ax.scatter([entry_time], [entry_price], marker='o', color=entry_color, s=250,
                   edgecolors=edge_color, linewidths=3, zorder=10)
        ax.annotate(
            f'{trade_direction} 3 CTS\n{entry_price:.2f}\n{entry_time.strftime("%H:%M")}',
            xy=(entry_time, entry_price),
            xytext=(-70, 40 if is_long else -50),
            textcoords='offset points',
            fontsize=10,
            fontweight='bold',
            color=entry_color,
            ha='center',
            arrowprops=dict(arrowstyle='->', color=entry_color, lw=2),
            bbox=dict(boxstyle='round', facecolor='white', edgecolor=entry_color, alpha=0.9),
            zorder=11,
        )

    # Mark each exit point
    exit_colors = {
        'TARGET_2R': '#FFD700',  # Gold
        'TARGET_4R': '#FFA500',  # Orange
        'EMA12_EXIT': '#E91E63',  # Pink
        'EMA34_EXIT': '#9C27B0',  # Purple
        'EMA50_EXIT': '#673AB7',  # Deep Purple
        'STOP': 'red',
        'EOD_CLOSE': 'gray',
    }

    exit_offsets = [
        (50, 25),   # First exit
        (50, -35),  # Second exit
        (50, 0),    # Third exit
    ]

    for i, exit in enumerate(exits):
        exit_color = exit_colors.get(exit['type'], 'green')
        marker = 'X' if 'TARGET' in exit['type'] or exit['type'] == 'EMA50_EXIT' else 's'

        ax.scatter([exit['time']], [exit['price']], marker=marker, color=exit_color, s=200,
                   edgecolors='black', linewidths=2, zorder=10)

        # Calculate P/L for this exit
        exit_pnl = exit['pnl']
        exit_pnl_ticks = exit_pnl / tick_size

        offset = exit_offsets[i % len(exit_offsets)]
        ax.annotate(
            f"{exit['type']}\n{exit['contracts']} ct @ {exit['price']:.2f}\n{exit['time'].strftime('%H:%M')}\n{exit_pnl:+.2f} pts",
            xy=(exit['time'], exit['price']),
            xytext=offset,
            textcoords='offset points',
            fontsize=9,
            fontweight='bold',
            color=exit_color,
            ha='center',
            arrowprops=dict(arrowstyle='->', color=exit_color, lw=1.5),
            bbox=dict(boxstyle='round', facecolor='white', edgecolor=exit_color, alpha=0.9),
            zorder=11,
        )

    # Shade risk zone (entry to stop) - different for long vs short
    if is_long:
        ax.axhspan(stop_price, entry_price, alpha=0.1, color='red', zorder=0)
        # Shade reward zones (above entry for longs)
        ax.axhspan(entry_price, targets[0][1], alpha=0.08, color='gold', zorder=0)
        ax.axhspan(targets[0][1], target_4r, alpha=0.08, color='orange', zorder=0)
    else:
        ax.axhspan(entry_price, stop_price, alpha=0.1, color='red', zorder=0)
        # Shade reward zones (below entry for shorts)
        ax.axhspan(targets[0][1], entry_price, alpha=0.08, color='gold', zorder=0)
        ax.axhspan(target_4r, targets[0][1], alpha=0.08, color='orange', zorder=0)

    # Mark LOD for longs, HOD for shorts
    if is_long:
        lod_bar_idx = min(range(len(session_bars)), key=lambda i: session_bars[i].low)
        lod = session_bars[lod_bar_idx].low
        lod_time = session_bars[lod_bar_idx].timestamp
        ax.axhline(y=lod, color='green', linestyle='-', linewidth=1.5, alpha=0.5)
        ax.annotate(f'SWEEP/LOD {lod:.2f}', xy=(lod_time, lod), xytext=(5, -15),
                   textcoords='offset points', fontsize=9, color='green', fontweight='bold')
    else:
        hod_bar_idx = max(range(len(session_bars)), key=lambda i: session_bars[i].high)
        hod = session_bars[hod_bar_idx].high
        hod_time = session_bars[hod_bar_idx].timestamp
        ax.axhline(y=hod, color='red', linestyle='-', linewidth=1.5, alpha=0.5)
        ax.annotate(f'SWEEP/HOD {hod:.2f}', xy=(hod_time, hod), xytext=(5, 10),
                   textcoords='offset points', fontsize=9, color='red', fontweight='bold')

    # RTH line
    rth_start = dt_time(9, 30)
    for bar in session_bars:
        if bar.timestamp.time() >= rth_start:
            ax.axvline(x=bar.timestamp, color='blue', linestyle='--', linewidth=1, alpha=0.5)
            break

    # Formatting
    ax.set_ylabel('Price', fontsize=12)
    ax.set_xlabel('Time (ET)', fontsize=12)

    result_str = f"Total P/L: {total_pnl:+.2f} pts (${total_pnl_dollars:+.2f})"
    filter_str = ""
    if require_ema_crossover:
        filter_str += f" | EMA34{'>' if is_long else '<'}50"
    if require_price_above_cloud:
        filter_str += f" | {'Above' if is_long else 'Below'} Cloud"
    if require_ema_stack:
        stack_str = "9>12>34>50" if is_long else "9<12<34<50"
        filter_str += f" | EMA Stack ({stack_str})"

    fvg_type = "Bullish" if is_long else "Bearish"
    ema_exit = "close below" if is_long else "close above"
    ax.set_title(
        f'{symbol} - {session_date} - {trade_direction} TRADE PLAN ({interval}) - {contracts} CONTRACTS{filter_str}\n'
        f'Entry: 2nd {fvg_type} FVG @ {entry_price:.2f} | Stop: {stop_price:.2f} | Risk: {risk:.2f} pts\n'
        f'Exits: 1ct@2R, 1ct@4R, 1ct@EMA{runner_exit_ema} {ema_exit} | {result_str}',
        fontsize=12
    )

    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    plt.xticks(rotation=45)

    plt.tight_layout()

    # Save
    filter_suffix = ""
    if require_ema_crossover:
        filter_suffix += "_ema"
    if require_price_above_cloud:
        filter_suffix += "_cloud"
    direction_suffix = "_long" if is_long else "_short"

    output_file = f"trade_plan_{symbol}_{session_date}_{interval}{direction_suffix}{filter_suffix}.png"
    if save_plot:
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        print(f"\nChart saved to: {output_file}")
    plt.close()

    # Return results dict for multi-day analysis
    return {
        'date': session_date,
        'symbol': symbol,
        'direction': trade_direction,
        'entry_triggered': entry_triggered,
        'entry_price': entry_price if entry_triggered else None,
        'entry_time': entry_time,
        'stop_price': stop_price,
        'risk': risk,
        'exits': exits,
        'total_pnl': total_pnl if entry_triggered else 0,
        'total_pnl_dollars': total_pnl_dollars if entry_triggered else 0,
        'output_file': output_file,
    }


def run_multi_day_test(
    symbol: str = "ES",
    dates: list = None,
    interval: str = "3m",
    require_ema_crossover: bool = True,
    require_price_above_cloud: bool = True,
    require_ema_stack: bool = False,
    fvg_entry_num: int = 1,  # Use 1st FVG for more trades
    trade_direction: str = "BOTH",  # "LONG", "SHORT", or "BOTH"
):
    """Run trade plan across multiple days and compare results."""
    if dates is None:
        # Default to last few trading days
        dates = [
            date(2026, 1, 22),
            date(2026, 1, 23),
            date(2026, 1, 24),
            date(2026, 1, 26),
        ]

    print("=" * 80)
    print(f"MULTI-DAY BACKTEST - {symbol} {interval} - {trade_direction}")
    print(f"Entry: FVG #{fvg_entry_num} | Filters: EMA Crossover={require_ema_crossover}, Above Cloud={require_price_above_cloud}, EMA Stack={require_ema_stack}")
    print("=" * 80)

    results = []

    # Determine which directions to test
    directions = ["LONG", "SHORT"] if trade_direction == "BOTH" else [trade_direction]

    for d in dates:
        print(f"\n{'='*80}")
        print(f"DATE: {d}")
        print(f"{'='*80}")

        for direction in directions:
            try:
                result = plot_trade_plan(
                    symbol=symbol,
                    session_date=d,
                    interval=interval,
                    fvg_entry_num=fvg_entry_num,
                    rr_targets=[2.0, 3.0],
                    contracts=3,
                    require_ema_crossover=require_ema_crossover,
                    require_price_above_cloud=require_price_above_cloud,
                    require_ema_stack=require_ema_stack,
                    trade_direction=direction,
                    save_plot=True,
                )
                if result:
                    results.append(result)
            except Exception as e:
                print(f"Error on {d} ({direction}): {e}")

    # Print summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")

    total_pnl = 0
    total_dollars = 0
    wins = 0
    losses = 0
    long_pnl = 0
    short_pnl = 0

    trades_taken = 0
    for r in results:
        if r and 'total_pnl' in r:
            if r.get('entry_triggered', False):
                trades_taken += 1
                total_pnl += r['total_pnl']
                total_dollars += r['total_pnl_dollars']
                if r['direction'] == 'LONG':
                    long_pnl += r['total_pnl']
                else:
                    short_pnl += r['total_pnl']
                if r['total_pnl'] > 0:
                    wins += 1
                else:
                    losses += 1
                print(f"  {r['date']} | {r['direction']:5} | Entry: {r['entry_time'].strftime('%H:%M')} | P/L: {r['total_pnl']:+.2f} pts (${r['total_pnl_dollars']:+.2f})")
            else:
                print(f"  {r['date']} | {r['direction']:5} | NO TRADE (filters not met)")

    print(f"\n  TOTAL: {trades_taken} trades | {wins}W / {losses}L | {total_pnl:+.2f} pts | ${total_dollars:+.2f}")
    if trade_direction == "BOTH":
        print(f"  LONG P/L:  {long_pnl:+.2f} pts")
        print(f"  SHORT P/L: {short_pnl:+.2f} pts")

    return results


def run_reentry_backtest(
    symbol: str = "ES",
    dates: list = None,
    interval: str = "3m",
    require_ema_crossover: bool = False,
    require_price_above_cloud: bool = False,
    require_ema_stack: bool = False,
    trade_direction: str = "BOTH",
):
    """
    Run backtest with re-entry logic:
    - Enter on 1st FVG
    - If stopped out, re-enter on 2nd FVG
    """
    if dates is None:
        dates = [
            date(2026, 1, 21),
            date(2026, 1, 22),
            date(2026, 1, 23),
            date(2026, 1, 26),
            date(2026, 1, 27),
        ]

    print("=" * 80)
    print(f"RE-ENTRY BACKTEST - {symbol} {interval} - {trade_direction}")
    print("Strategy: Enter 1st FVG, if stopped re-enter on 2nd FVG")
    print("=" * 80)

    all_results = []
    directions = ["LONG", "SHORT"] if trade_direction == "BOTH" else [trade_direction]

    for d in dates:
        print(f"\n{'='*80}")
        print(f"DATE: {d}")
        print(f"{'='*80}")

        for direction in directions:
            day_results = []

            # Try 1st FVG entry
            try:
                result1 = plot_trade_plan(
                    symbol=symbol,
                    session_date=d,
                    interval=interval,
                    fvg_entry_num=1,
                    rr_targets=[2.0, 3.0],
                    contracts=3,
                    require_ema_crossover=require_ema_crossover,
                    require_price_above_cloud=require_price_above_cloud,
                    require_ema_stack=require_ema_stack,
                    trade_direction=direction,
                    save_plot=True,
                )

                if result1:
                    day_results.append(result1)

                    # If stopped out on 1st FVG, try 2nd FVG
                    if result1.get('entry_triggered') and result1.get('exits'):
                        was_stopped = any(e['type'] == 'STOP' for e in result1['exits'])
                        if was_stopped:
                            print(f"\n>>> STOPPED on 1st FVG, trying 2nd FVG re-entry...")
                            try:
                                result2 = plot_trade_plan(
                                    symbol=symbol,
                                    session_date=d,
                                    interval=interval,
                                    fvg_entry_num=2,
                                    rr_targets=[2.0, 3.0],
                                    contracts=3,
                                    require_ema_crossover=require_ema_crossover,
                                    require_price_above_cloud=require_price_above_cloud,
                                    require_ema_stack=require_ema_stack,
                                    trade_direction=direction,
                                    save_plot=True,
                                )
                                if result2:
                                    result2['is_reentry'] = True
                                    day_results.append(result2)
                            except Exception as e:
                                print(f"No 2nd FVG available for re-entry: {e}")

            except Exception as e:
                print(f"Error on {d} ({direction}): {e}")

            all_results.extend(day_results)

    # Print summary
    print(f"\n{'='*80}")
    print("SUMMARY - RE-ENTRY STRATEGY")
    print(f"{'='*80}")

    total_pnl = 0
    total_dollars = 0
    wins = 0
    losses = 0
    long_pnl = 0
    short_pnl = 0
    reentry_count = 0

    for r in all_results:
        if r and r.get('entry_triggered', False):
            total_pnl += r['total_pnl']
            total_dollars += r['total_pnl_dollars']

            if r['direction'] == 'LONG':
                long_pnl += r['total_pnl']
            else:
                short_pnl += r['total_pnl']

            if r['total_pnl'] > 0:
                wins += 1
            else:
                losses += 1

            reentry_tag = " [RE-ENTRY]" if r.get('is_reentry') else ""
            print(f"  {r['date']} | {r['direction']:5} | Entry: {r['entry_time'].strftime('%H:%M')} | "
                  f"P/L: {r['total_pnl']:+.2f} pts (${r['total_pnl_dollars']:+.2f}){reentry_tag}")

            if r.get('is_reentry'):
                reentry_count += 1
        elif r:
            print(f"  {r['date']} | {r['direction']:5} | NO TRADE")

    total_trades = wins + losses
    print(f"\n  TOTAL: {total_trades} trades ({reentry_count} re-entries) | {wins}W / {losses}L | "
          f"{total_pnl:+.2f} pts | ${total_dollars:+.2f}")
    if trade_direction == "BOTH":
        print(f"  LONG P/L:  {long_pnl:+.2f} pts")
        print(f"  SHORT P/L: {short_pnl:+.2f} pts")

    return all_results


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "reentry":
        # Run re-entry backtest
        dates = [
            date(2026, 1, 21),
            date(2026, 1, 22),
            date(2026, 1, 23),
            date(2026, 1, 26),
            date(2026, 1, 27),
        ]
        run_reentry_backtest(
            symbol="ES",
            dates=dates,
            trade_direction="BOTH",
        )
    elif len(sys.argv) > 1 and sys.argv[1] == "multi":
        # Run multi-day test with EMA filters - both directions
        dates = [
            date(2026, 1, 21),
            date(2026, 1, 22),
            date(2026, 1, 23),
            date(2026, 1, 26),
            date(2026, 1, 27),
        ]
        run_multi_day_test(
            symbol="ES",
            dates=dates,
            require_ema_crossover=True,
            require_price_above_cloud=True,
            fvg_entry_num=2,  # 2nd FVG for confirmation
            trade_direction="BOTH",  # Test both long and short
        )
    elif len(sys.argv) > 1 and sys.argv[1] == "short":
        # Test short on a bearish day
        target_date = date(2026, 1, 21)
        plot_trade_plan(
            "ES", target_date, "3m",
            fvg_entry_num=2,
            rr_targets=[2.0, 3.0],
            contracts=3,
            require_ema_crossover=True,
            require_price_above_cloud=True,
            trade_direction="SHORT",
        )
    else:
        # Single day test - LONG
        target_date = date(2026, 1, 26)
        plot_trade_plan(
            "ES", target_date, "3m",
            fvg_entry_num=2,
            rr_targets=[2.0, 3.0],
            contracts=3,
            require_ema_crossover=True,
            require_price_above_cloud=True,
            trade_direction="LONG",
        )
