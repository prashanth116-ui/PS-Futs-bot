"""
Plot ICT Liquidity Sweep Strategy trades.

Usage:
    python -m runners.plot_ict_sweep ES 2026 2 12
    python -m runners.plot_ict_sweep ES  # Today
"""
import sys
sys.path.insert(0, '.')

import matplotlib.pyplot as plt
from datetime import date, time as dt_time, datetime, timedelta
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict_sweep.strategy import ICTSweepStrategy, TradeSetup


def to_est(utc_dt):
    """Convert UTC datetime to EST (UTC-5)."""
    return utc_dt - timedelta(hours=5)


def simulate_trade(bars, trade: TradeSetup, tick_size, tick_value, contracts):
    """Simulate trade execution and return result."""
    if len(bars) < 2:
        return None

    entry = trade.entry_price
    stop = trade.stop_price
    t1 = trade.t1_price
    t2 = trade.t2_price

    for i, bar in enumerate(bars[1:], 1):
        if trade.direction == 'LONG':
            if bar.low <= stop:
                return {'exit_price': stop, 'exit_bar': i, 'result': 'STOP',
                        'pnl': (stop - entry) / tick_size * tick_value * contracts}
            if bar.high >= t2:
                return {'exit_price': t2, 'exit_bar': i, 'result': 'TARGET',
                        'pnl': (t2 - entry) / tick_size * tick_value * contracts}
        else:
            if bar.high >= stop:
                return {'exit_price': stop, 'exit_bar': i, 'result': 'STOP',
                        'pnl': (entry - stop) / tick_size * tick_value * contracts}
            if bar.low <= t2:
                return {'exit_price': t2, 'exit_bar': i, 'result': 'TARGET',
                        'pnl': (entry - t2) / tick_size * tick_value * contracts}

    # EOD
    exit_price = bars[-1].close
    if trade.direction == 'LONG':
        pnl = (exit_price - entry) / tick_size * tick_value * contracts
    else:
        pnl = (entry - exit_price) / tick_size * tick_value * contracts
    return {'exit_price': exit_price, 'exit_bar': len(bars) - 1, 'result': 'EOD', 'pnl': pnl}


def plot_ict_sweep(symbol='ES', year=None, month=None, day=None, contracts=3):
    """Plot ICT Sweep strategy for a specific date."""

    # Instrument config
    tick_size = 0.25
    if symbol in ['ES', 'MES']:
        tick_value = 12.50 if symbol == 'ES' else 1.25
        min_fvg_ticks = 3
        max_risk_ticks = 80
    elif symbol in ['NQ', 'MNQ']:
        tick_value = 5.00 if symbol == 'NQ' else 0.50
        min_fvg_ticks = 8
        max_risk_ticks = 200
    else:
        tick_value = 12.50
        min_fvg_ticks = 5
        max_risk_ticks = 80

    # Fetch data
    print(f'Fetching {symbol} HTF (5m) data...')
    htf_bars = fetch_futures_bars(symbol=symbol, interval='5m', n_bars=1000)

    print(f'Fetching {symbol} MTF (3m) data...')
    mtf_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=1500)

    if not htf_bars or not mtf_bars:
        print('No data available')
        return

    ltf_bars = mtf_bars

    # Determine target date
    if year and month and day:
        target_date = date(year, month, day)
    else:
        target_date = to_est(htf_bars[-1].timestamp).date()

    print(f'Plotting date: {target_date} (EST)')

    # ETH session in UTC (data is in UTC)
    # ETH: 6:00 PM - 5:00 PM ET next day (23 hours)
    # For intraday, use 00:00 - 21:00 UTC = 7 PM prev day - 4 PM ET
    # Simpler: filter by EST date after converting

    # RTH session: 9:30 AM - 4:00 PM EST
    rth_start = dt_time(9, 30)
    rth_end = dt_time(16, 0)

    # Filter bars for target date using EST, RTH only
    day_htf = [b for b in htf_bars if to_est(b.timestamp).date() == target_date
               and rth_start <= to_est(b.timestamp).time() <= rth_end]
    day_mtf = [b for b in mtf_bars if to_est(b.timestamp).date() == target_date
               and rth_start <= to_est(b.timestamp).time() <= rth_end]
    day_ltf = day_mtf

    print(f'HTF bars: {len(day_htf)}, MTF bars: {len(day_mtf)}')

    if len(day_htf) < 30 or len(day_ltf) < 50:
        print(f'Insufficient bars (HTF: {len(day_htf)}, LTF: {len(day_ltf)})')
        return

    # Get lookback bars
    lookback_htf = [b for b in htf_bars if to_est(b.timestamp).date() < target_date][-50:]
    lookback_mtf = [b for b in mtf_bars if to_est(b.timestamp).date() < target_date][-100:]
    lookback_ltf = lookback_mtf

    # Strategy config
    config = {
        'symbol': symbol,
        'tick_size': tick_size,
        'tick_value': tick_value,
        'swing_lookback': 20,
        'swing_strength': 3,
        'min_sweep_ticks': 2,
        'max_sweep_ticks': 50,
        'displacement_multiplier': 2.0,
        'avg_body_lookback': 20,
        'min_fvg_ticks': min_fvg_ticks,
        'max_fvg_age_bars': 50,
        'mss_lookback': 20,
        'mss_swing_strength': 1,
        'stop_buffer_ticks': 2,
        'max_risk_ticks': max_risk_ticks,
        'allow_lunch': False,
        'require_killzone': False,
        'max_daily_trades': 5,
        'max_daily_losses': 2,
        'use_mtf_for_fvg': True,
        'entry_on_mitigation': True,
        'stop_buffer_pts': 2.0,
        'use_trend_filter': True,
        'ema_fast_period': 20,
        'ema_slow_period': 50,
    }

    # Initialize strategy
    strategy = ICTSweepStrategy(config)

    for bar in lookback_htf:
        strategy.htf_bars.append(bar)
    for bar in lookback_mtf:
        strategy.mtf_bars.append(bar)
    for bar in lookback_ltf:
        strategy.ltf_bars.append(bar)

    # Run strategy and collect trades
    trades = []
    setups = []
    htf_idx = 0
    mtf_idx = 0
    ltf_idx = 0

    while ltf_idx < len(day_ltf):
        ltf_bar = day_ltf[ltf_idx]

        while htf_idx < len(day_htf) and day_htf[htf_idx].timestamp <= ltf_bar.timestamp:
            htf_bar = day_htf[htf_idx]

            while mtf_idx < len(day_mtf) and day_mtf[mtf_idx].timestamp <= htf_bar.timestamp:
                strategy.update_mtf(day_mtf[mtf_idx])
                mtf_idx += 1

            setup = strategy.update_htf(htf_bar)
            if setup:
                setups.append({
                    'time': htf_bar.timestamp,
                    'type': setup.sweep.sweep_type,
                    'sweep_price': setup.sweep.sweep_price,
                    'fvg_top': setup.fvg.top,
                    'fvg_bottom': setup.fvg.bottom,
                })

            # Check mitigation - may return trade if entry_on_mitigation=True
            mitigation_result = strategy.check_htf_mitigation(htf_bar)
            if isinstance(mitigation_result, TradeSetup):
                trade = mitigation_result
                result = simulate_trade(day_ltf[ltf_idx:], trade, tick_size, tick_value, contracts)
                if result:
                    trades.append({
                        'trade': trade,
                        'entry_bar_idx': ltf_idx,
                        'exit_bar_idx': ltf_idx + result['exit_bar'],
                        'exit_price': result['exit_price'],
                        'result': result['result'],
                        'pnl': result['pnl'],
                    })
                    ltf_idx += result['exit_bar']

            htf_idx += 1

        trade = strategy.update_ltf(ltf_bar)
        if trade:
            result = simulate_trade(day_ltf[ltf_idx:], trade, tick_size, tick_value, contracts)
            if result:
                trades.append({
                    'trade': trade,
                    'entry_bar_idx': ltf_idx,
                    'exit_bar_idx': ltf_idx + result['exit_bar'],
                    'exit_price': result['exit_price'],
                    'result': result['result'],
                    'pnl': result['pnl'],
                })
                ltf_idx += result['exit_bar']

        ltf_idx += 1

    print(f'Setups detected: {len(setups)}')
    print(f'Trades executed: {len(trades)}')

    # Create plot
    fig, ax = plt.subplots(figsize=(20, 12))

    # Plot candlesticks (use 3m bars for detail)
    for i, bar in enumerate(day_ltf):
        color = '#4CAF50' if bar.close >= bar.open else '#F44336'
        ax.plot([i, i], [bar.low, bar.high], color=color, linewidth=0.8)
        body_bottom = min(bar.open, bar.close)
        body_height = abs(bar.close - bar.open)
        rect = plt.Rectangle((i - 0.3, body_bottom), 0.6, body_height,
                             facecolor=color, edgecolor=color)
        ax.add_patch(rect)

    # Plot FVG zones from setups
    for setup in setups:
        setup_time = setup['time']
        setup_idx = None
        for i, bar in enumerate(day_ltf):
            if bar.timestamp >= setup_time:
                setup_idx = i
                break

        if setup_idx is not None:
            fvg_color = '#2196F3' if setup['type'] == 'BULLISH' else '#FF5722'
            rect = plt.Rectangle((setup_idx, setup['fvg_bottom']),
                                  30, setup['fvg_top'] - setup['fvg_bottom'],
                                  facecolor=fvg_color, alpha=0.2, edgecolor=fvg_color, linewidth=1)
            ax.add_patch(rect)

            ax.hlines(setup['sweep_price'], setup_idx - 5, setup_idx + 5,
                     colors=fvg_color, linestyles='--', linewidth=2, alpha=0.8)

    # Plot trades
    total_pnl = 0
    for t in trades:
        trade = t['trade']
        entry_idx = t['entry_bar_idx']
        exit_idx = t['exit_bar_idx']
        exit_price = t['exit_price']
        pnl = t['pnl']
        total_pnl += pnl

        is_long = trade.direction == 'LONG'
        color = '#2196F3' if is_long else '#FF5722'
        result_color = '#4CAF50' if pnl > 0 else '#F44336'

        marker = '^' if is_long else 'v'
        ax.scatter([entry_idx], [trade.entry_price], color=color, s=200, zorder=5,
                   marker=marker, edgecolors='black', linewidths=2)

        # Entry annotation with EST time
        est_time = to_est(trade.timestamp)
        y_offset = 3 if is_long else -3
        ax.annotate(f'{trade.direction}\n{est_time.strftime("%H:%M")} EST\n{trade.entry_price:.2f}',
                    xy=(entry_idx, trade.entry_price),
                    xytext=(entry_idx - 8, trade.entry_price + y_offset),
                    fontsize=9, fontweight='bold', color=color,
                    bbox=dict(boxstyle='round', facecolor='white', alpha=0.9, edgecolor=color))

        # Trade lines
        line_end = min(len(day_ltf) - 1, exit_idx + 10)
        ax.hlines(trade.entry_price, entry_idx, line_end, colors=color, linestyles='-', linewidth=2, alpha=0.8)
        ax.hlines(trade.stop_price, entry_idx, line_end, colors='#F44336', linestyles='--', linewidth=1.5, alpha=0.6)
        ax.hlines(trade.t2_price, entry_idx, line_end, colors='#4CAF50', linestyles=':', linewidth=1.5, alpha=0.6)

        # Exit marker
        exit_marker = 'v' if is_long else '^'
        ax.scatter([exit_idx], [exit_price], color=result_color, s=150, zorder=5,
                   marker=exit_marker, edgecolors='black', linewidths=1.5)

        result_text = f"{t['result']}\n${pnl:+,.0f}"
        ax.annotate(result_text,
                    xy=(exit_idx, exit_price),
                    xytext=(exit_idx + 3, exit_price),
                    fontsize=8, fontweight='bold', color=result_color,
                    bbox=dict(boxstyle='round', facecolor='white', alpha=0.9))

    # X-axis labels in EST
    tick_positions = list(range(0, len(day_ltf), 20))
    tick_labels = [to_est(day_ltf[i].timestamp).strftime('%H:%M') for i in tick_positions if i < len(day_ltf)]
    ax.set_xticks(tick_positions[:len(tick_labels)])
    ax.set_xticklabels(tick_labels, rotation=45)

    # Title and labels
    win_count = sum(1 for t in trades if t['pnl'] > 0)
    loss_count = sum(1 for t in trades if t['pnl'] < 0)
    win_rate = (win_count / len(trades) * 100) if trades else 0

    ax.set_title(f'{symbol} ICT Liquidity Sweep - {target_date} (EST, ETH Session)\n'
                 f'Trades: {len(trades)} | Wins: {win_count} | Losses: {loss_count} | '
                 f'Win Rate: {win_rate:.0f}% | Total P/L: ${total_pnl:+,.2f}',
                 fontsize=14, fontweight='bold')
    ax.set_xlabel('Time (EST)')
    ax.set_ylabel('Price')
    ax.grid(True, alpha=0.3)

    # Legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='^', color='w', markerfacecolor='#2196F3', markersize=12, label='LONG Entry'),
        Line2D([0], [0], marker='v', color='w', markerfacecolor='#FF5722', markersize=12, label='SHORT Entry'),
        Line2D([0], [0], color='#F44336', linestyle='--', label='Stop Loss'),
        Line2D([0], [0], color='#4CAF50', linestyle=':', label='Target (4R)'),
        plt.Rectangle((0,0), 1, 1, facecolor='#2196F3', alpha=0.2, label='Bullish FVG'),
        plt.Rectangle((0,0), 1, 1, facecolor='#FF5722', alpha=0.2, label='Bearish FVG'),
    ]
    ax.legend(handles=legend_elements, loc='upper left')

    plt.tight_layout()
    plt.show()

    # Print trade summary
    print()
    print('=' * 60)
    print('TRADE SUMMARY (EST)')
    print('=' * 60)
    for i, t in enumerate(trades, 1):
        trade = t['trade']
        est_time = to_est(trade.timestamp)
        print(f"Trade {i}: {trade.direction} @ {trade.entry_price:.2f}")
        print(f"  Entry: {est_time.strftime('%H:%M')} EST")
        print(f"  Stop: {trade.stop_price:.2f}, Target: {trade.t2_price:.2f}")
        print(f"  Exit: {t['exit_price']:.2f} ({t['result']})")
        print(f"  P/L: ${t['pnl']:+,.2f}")
        print()
    print(f"TOTAL P/L: ${total_pnl:+,.2f}")


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'

    if len(sys.argv) >= 5:
        year = int(sys.argv[2])
        month = int(sys.argv[3])
        day = int(sys.argv[4])
        plot_ict_sweep(symbol, year, month, day)
    else:
        plot_ict_sweep(symbol)
