"""
ICT Liquidity Sweep Strategy - Backtest Runner

Entry Logic:
1. Liquidity Sweep - Price sweeps swing high/low
2. Displacement - Strong rejection candle
3. FVG Forms - Fair Value Gap created
4. FVG Mitigation - Price retraces into FVG
5. LTF MSS Confirms - Market Structure Shift

Usage:
    python -m runners.run_ict_sweep ES 14
    python -m runners.run_ict_sweep NQ 14
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time, timedelta
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict_sweep.strategy import ICTSweepStrategy, TradeSetup, SetupState
from strategies.ict_sweep.filters.session import get_session_name


def run_backtest(symbol: str = 'ES', days: int = 14, contracts: int = 3):
    """
    Run ICT Sweep strategy backtest.

    Args:
        symbol: Instrument symbol (ES, NQ, MES, MNQ)
        days: Number of days to backtest
        contracts: Contracts per trade
    """
    # Instrument config
    max_risk_ticks = 80  # Default
    if symbol in ['ES', 'MES']:
        tick_size = 0.25
        tick_value = 12.50 if symbol == 'ES' else 1.25
        min_fvg_ticks = 3  # Reduced to catch smaller FVGs like the 9:45 gap
    elif symbol in ['NQ', 'MNQ']:
        tick_size = 0.25
        tick_value = 5.00 if symbol == 'NQ' else 0.50
        min_fvg_ticks = 8  # Reduced from 15 to allow more setups
        max_risk_ticks = 200  # NQ has larger moves, need higher risk limit
    else:
        tick_size = 0.25
        tick_value = 12.50
        min_fvg_ticks = 5

    # Bars needed - Hybrid timeframes
    # HTF (5m): sweep detection with proper lookback
    # MTF (3m): FVG detection (catches gaps 5m misses)
    # LTF (3m): MSS confirmation
    htf_bars_per_day = 78   # 5m bars in RTH
    mtf_bars_per_day = 130  # 3m bars in RTH
    ltf_bars_per_day = 130  # 3m bars in RTH

    htf_bars_needed = days * htf_bars_per_day + 200
    mtf_bars_needed = days * mtf_bars_per_day + 300
    ltf_bars_needed = days * ltf_bars_per_day + 300

    print(f"Fetching {symbol} HTF (5m) data...")
    htf_bars = fetch_futures_bars(symbol=symbol, interval='5m', n_bars=htf_bars_needed)

    print(f"Fetching {symbol} MTF (3m) data for FVG...")
    mtf_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=mtf_bars_needed)

    # Use 3m for both MTF and LTF
    ltf_bars = mtf_bars

    if not htf_bars or not mtf_bars:
        print("No data available")
        return

    # Strategy config
    config = {
        'symbol': symbol,
        'tick_size': tick_size,
        'tick_value': tick_value,
        'swing_lookback': 20,
        'swing_strength': 3,
        'min_sweep_ticks': 2,
        'max_sweep_ticks': 50,  # Increased to allow deeper sweeps
        'displacement_multiplier': 2.0,
        'avg_body_lookback': 20,
        'min_fvg_ticks': min_fvg_ticks,
        'max_fvg_age_bars': 50,
        'mss_lookback': 20,           # Increased to find swings further back
        'mss_swing_strength': 1,      # Reduced for more sensitive swing detection
        'stop_buffer_ticks': 2,
        'max_risk_ticks': max_risk_ticks,
        'allow_lunch': False,
        'require_killzone': False,
        'max_daily_trades': 5,
        'max_daily_losses': 2,
        'use_mtf_for_fvg': True,      # Use 3m for FVG detection (catches gaps 5m misses)
        'entry_on_mitigation': True,  # Enter on FVG tap, don't wait for MSS
    }

    # Group bars by date
    dates = sorted(set(b.timestamp.date() for b in ltf_bars))

    print(f"\nAvailable dates in data: {dates}")
    print(f"Processing last {days} days: {dates[-days:]}")

    print()
    print("=" * 100)
    print(f"{symbol} ICT LIQUIDITY SWEEP STRATEGY BACKTEST")
    print(f"HTF: 5m (sweep) | MTF: 3m (FVG) | LTF: 3m (MSS) | Days: {min(len(dates), days)} | Contracts: {contracts}")
    print("=" * 100)
    print()
    print(f"{'Date':<12} | {'Dir':<5} | {'Entry':>10} | {'Stop':>10} | {'Risk':>6} | "
          f"{'Result':<6} | {'P/L':>12} | {'Session':<10}")
    print("-" * 100)

    # Track results
    all_trades = []
    total_wins = 0
    total_losses = 0
    total_pnl = 0.0

    for day in dates[-days:]:
        # Get bars for this day
        day_htf = [b for b in htf_bars if b.timestamp.date() == day]
        day_mtf = [b for b in mtf_bars if b.timestamp.date() == day]
        day_ltf = [b for b in ltf_bars if b.timestamp.date() == day]

        # Filter to trading session (9:30 - 16:00)
        session_start = dt_time(9, 30)
        session_end = dt_time(16, 0)

        day_htf = [b for b in day_htf if session_start <= b.timestamp.time() <= session_end]
        day_mtf = [b for b in day_mtf if session_start <= b.timestamp.time() <= session_end]
        day_ltf = [b for b in day_ltf if session_start <= b.timestamp.time() <= session_end]

        if len(day_htf) < 30 or len(day_ltf) < 100:
            print(f"  [{day}] Skipping - insufficient bars (HTF: {len(day_htf)}, LTF: {len(day_ltf)})")
            continue

        # Initialize strategy for the day
        strategy = ICTSweepStrategy(config)

        # Also get lookback bars from previous days for context
        lookback_htf = [b for b in htf_bars if b.timestamp.date() < day][-50:]
        for bar in lookback_htf:
            strategy.htf_bars.append(bar)

        # Add MTF lookback
        lookback_mtf = [b for b in mtf_bars if b.timestamp.date() < day][-100:]
        for bar in lookback_mtf:
            strategy.mtf_bars.append(bar)

        # Add LTF lookback (needed for MSS detection)
        lookback_ltf = [b for b in ltf_bars if b.timestamp.date() < day][-50:]
        for bar in lookback_ltf:
            strategy.ltf_bars.append(bar)

        # Process HTF, MTF, and LTF bars together
        htf_idx = 0
        mtf_idx = 0
        ltf_idx = 0
        day_setups = 0
        day_mitigations = 0

        while ltf_idx < len(day_ltf):
            ltf_bar = day_ltf[ltf_idx]

            # Process any HTF bars that complete before this LTF bar
            while htf_idx < len(day_htf) and day_htf[htf_idx].timestamp <= ltf_bar.timestamp:
                htf_bar = day_htf[htf_idx]

                # Update HTF - check for new setups
                setup = strategy.update_htf(htf_bar)
                if setup:
                    day_setups += 1

                # Check for FVG mitigation (may return trade if entry_on_mitigation=True)
                mitigation_result = strategy.check_htf_mitigation(htf_bar)

                # Handle mitigation entry
                if isinstance(mitigation_result, TradeSetup):
                    trade = mitigation_result
                    day_mitigations += 1

                    # Simulate the trade
                    result = simulate_trade(
                        day_ltf[ltf_idx:],
                        trade,
                        tick_size,
                        tick_value,
                        contracts
                    )

                    if result:
                        is_win = result['pnl_dollars'] > 0
                        is_loss = result['pnl_dollars'] < 0

                        if is_win:
                            total_wins += 1
                            result_str = 'WIN'
                        elif is_loss:
                            total_losses += 1
                            strategy.on_trade_result(result['pnl_dollars'])
                            result_str = 'LOSS'
                        else:
                            result_str = 'BE'

                        total_pnl += result['pnl_dollars']
                        result['trade'] = trade
                        result['date'] = day
                        all_trades.append(result)

                        session = get_session_name(trade.timestamp)

                        print(f"{day} | {trade.direction:<5} | {trade.entry_price:>10.2f} | "
                              f"{trade.stop_price:>10.2f} | {trade.risk_ticks:>6.1f} | "
                              f"{result_str:<6} | ${result['pnl_dollars']:>+10,.2f} | {session:<10}")

                        ltf_idx += result.get('bars_held', 1)

                elif mitigation_result:
                    day_mitigations += len(mitigation_result)

                htf_idx += 1

            # Process any MTF bars that complete before this LTF bar
            while mtf_idx < len(day_mtf) and day_mtf[mtf_idx].timestamp <= ltf_bar.timestamp:
                strategy.update_mtf(day_mtf[mtf_idx])
                mtf_idx += 1

            # Update LTF - check for MSS confirmation
            trade = strategy.update_ltf(ltf_bar)

            if trade:
                # Simulate the trade
                result = simulate_trade(
                    day_ltf[ltf_idx:],
                    trade,
                    tick_size,
                    tick_value,
                    contracts
                )

                if result:
                    is_win = result['pnl_dollars'] > 0
                    is_loss = result['pnl_dollars'] < 0

                    if is_win:
                        total_wins += 1
                        result_str = 'WIN'
                    elif is_loss:
                        total_losses += 1
                        strategy.on_trade_result(result['pnl_dollars'])
                        result_str = 'LOSS'
                    else:
                        result_str = 'BE'

                    total_pnl += result['pnl_dollars']
                    result['trade'] = trade
                    result['date'] = day
                    all_trades.append(result)

                    session = get_session_name(trade.timestamp)

                    print(f"{day} | {trade.direction:<5} | {trade.entry_price:>10.2f} | "
                          f"{trade.stop_price:>10.2f} | {trade.risk_ticks:>6.1f} | "
                          f"{result_str:<6} | ${result['pnl_dollars']:>+10,.2f} | {session:<10}")

                    # Skip ahead to avoid overlapping trades
                    ltf_idx += result.get('bars_held', 1)

            ltf_idx += 1

        # Day summary
        print(f"  [{day}] Setups: {day_setups}, Mitigations: {day_mitigations}, Pending: {strategy.get_pending_count()}")

    # Print summary
    print("-" * 100)
    print()
    print("=" * 100)
    print("SUMMARY")
    print("=" * 100)

    total_trades = total_wins + total_losses
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0

    wins = [t for t in all_trades if t['pnl_dollars'] > 0]
    losses = [t for t in all_trades if t['pnl_dollars'] < 0]

    avg_win = sum(t['pnl_dollars'] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t['pnl_dollars'] for t in losses) / len(losses) if losses else 0

    print(f"  Total Trades:  {total_trades}")
    print(f"  Wins:          {total_wins}")
    print(f"  Losses:        {total_losses}")
    print(f"  Win Rate:      {win_rate:.1f}%")
    print(f"  Avg Win:       ${avg_win:+,.2f}")
    print(f"  Avg Loss:      ${avg_loss:+,.2f}")

    if losses and avg_loss != 0:
        pf = abs(sum(t['pnl_dollars'] for t in wins) / sum(t['pnl_dollars'] for t in losses))
        print(f"  Profit Factor: {pf:.2f}")

    print()
    print(f"  TOTAL P/L:     ${total_pnl:+,.2f}")
    print("=" * 100)
    print()
    print("Strategy: ICT Liquidity Sweep (Hybrid Timeframe)")
    print("  1. Sweep detected on 5m (stop hunt at swing high/low)")
    print("  2. Displacement confirmed (2x+ avg body)")
    print("  3. FVG detected on 5m OR 3m (catches more gaps)")
    print("  4. Price mitigated FVG (retraced into zone)")
    print("  5. LTF MSS confirmed on 3m (structure break)")
    print()

    return all_trades


def simulate_trade(bars, trade: TradeSetup, tick_size, tick_value, contracts):
    """
    Simulate trade execution.

    Args:
        bars: Remaining bars for the day
        trade: TradeSetup object
        tick_size: Instrument tick size
        tick_value: Dollar value per tick
        contracts: Number of contracts

    Returns:
        Trade result dict
    """
    if len(bars) < 2:
        return None

    entry = trade.entry_price
    stop = trade.stop_price
    t1 = trade.t1_price
    t2 = trade.t2_price

    # Track partial exits
    t1_hit = False
    remaining_contracts = contracts

    for i, bar in enumerate(bars[1:], 1):
        if trade.direction == 'LONG':
            # Check stop first (conservative)
            if bar.low <= stop:
                exit_price = stop
                pnl_ticks = (exit_price - entry) / tick_size
                return {
                    'entry': entry,
                    'exit': exit_price,
                    'pnl_ticks': pnl_ticks,
                    'pnl_dollars': pnl_ticks * tick_value * remaining_contracts,
                    'hit_target': False,
                    'bars_held': i
                }

            # Check T1
            if not t1_hit and bar.high >= t1:
                t1_hit = True
                # Partial exit at T1 (1 contract)
                # Continue with remaining

            # Check T2
            if bar.high >= t2:
                exit_price = t2
                pnl_ticks = (exit_price - entry) / tick_size
                return {
                    'entry': entry,
                    'exit': exit_price,
                    'pnl_ticks': pnl_ticks,
                    'pnl_dollars': pnl_ticks * tick_value * contracts,
                    'hit_target': True,
                    'bars_held': i
                }

        else:  # SHORT
            # Check stop first
            if bar.high >= stop:
                exit_price = stop
                pnl_ticks = (entry - exit_price) / tick_size
                return {
                    'entry': entry,
                    'exit': exit_price,
                    'pnl_ticks': pnl_ticks,
                    'pnl_dollars': pnl_ticks * tick_value * remaining_contracts,
                    'hit_target': False,
                    'bars_held': i
                }

            # Check T1
            if not t1_hit and bar.low <= t1:
                t1_hit = True

            # Check T2
            if bar.low <= t2:
                exit_price = t2
                pnl_ticks = (entry - exit_price) / tick_size
                return {
                    'entry': entry,
                    'exit': exit_price,
                    'pnl_ticks': pnl_ticks,
                    'pnl_dollars': pnl_ticks * tick_value * contracts,
                    'hit_target': True,
                    'bars_held': i
                }

    # End of day - exit at close
    exit_price = bars[-1].close
    if trade.direction == 'LONG':
        pnl_ticks = (exit_price - entry) / tick_size
    else:
        pnl_ticks = (entry - exit_price) / tick_size

    return {
        'entry': entry,
        'exit': exit_price,
        'pnl_ticks': pnl_ticks,
        'pnl_dollars': pnl_ticks * tick_value * contracts,
        'hit_target': False,
        'bars_held': len(bars) - 1
    }


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 14
    contracts = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    run_backtest(symbol=symbol, days=days, contracts=contracts)
