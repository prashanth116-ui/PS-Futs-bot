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

import pickle
from pathlib import Path
from datetime import time as dt_time, timedelta
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict_sweep.strategy import ICTSweepStrategy, TradeSetup

CACHE_DIR = Path('.cache')
CACHE_DIR.mkdir(exist_ok=True)
from strategies.ict_sweep.filters.session import get_session_name


def format_et(ts):
    """Format timestamp as ET time string (data is already in ET)."""
    return ts.strftime('%H:%M')


def is_swing_high(bars, idx, lookback=2):
    """Check if bar at idx is a swing high."""
    if idx < lookback or idx >= len(bars) - lookback:
        return False
    bar_high = bars[idx].high
    for i in range(1, lookback + 1):
        if bar_high <= bars[idx - i].high or bar_high <= bars[idx + i].high:
            return False
    return True


def is_swing_low(bars, idx, lookback=2):
    """Check if bar at idx is a swing low."""
    if idx < lookback or idx >= len(bars) - lookback:
        return False
    bar_low = bars[idx].low
    for i in range(1, lookback + 1):
        if bar_low >= bars[idx - i].low or bar_low >= bars[idx + i].low:
            return False
    return True


EQUITY_SYMBOLS = {'SPY', 'QQQ', 'IWM'}

EQUITY_CONFIG = {
    'SPY': {
        'name': 'S&P 500 ETF',
        'min_fvg_points': 0.20,
        'min_risk_points': 0.30,
        'default_risk_dollars': 500,
    },
    'QQQ': {
        'name': 'Nasdaq 100 ETF',
        'min_fvg_points': 0.40,
        'min_risk_points': 0.50,
        'default_risk_dollars': 500,
    },
    'IWM': {
        'name': 'Russell 2000 ETF',
        'min_fvg_points': 0.20,
        'min_risk_points': 0.30,
        'default_risk_dollars': 500,
    },
}


def run_backtest(symbol: str = 'ES', days: int = 14, contracts: int = 3, ltf_interval: str = '3m',
                 t1_r: int = 3, trail_r: int = 6, risk_per_trade: float = 500):
    """
    Run ICT Sweep strategy backtest.

    Args:
        symbol: Instrument symbol (ES, NQ, MES, MNQ, SPY, QQQ)
        days: Number of days to backtest
        contracts: Contracts per trade (futures only)
        t1_r: R-multiple for T1 fixed exit (default 3)
        trail_r: R-multiple for structure trail activation (default 6)
        risk_per_trade: Dollar risk per trade (equities only, default $500)
    """
    is_equity = symbol.upper() in EQUITY_SYMBOLS

    # Instrument config
    max_risk_ticks = 40  # ES/MES default: 10 pts
    if is_equity:
        eq_cfg = EQUITY_CONFIG[symbol.upper()]
        tick_size = 0.01
        tick_value = 0.01  # $0.01 per tick per share
        min_fvg_ticks = int(eq_cfg['min_fvg_points'] / tick_size)  # e.g. $0.20 = 20 ticks
        min_risk_ticks = int(eq_cfg['min_risk_points'] / tick_size)  # e.g. $0.30 = 30 ticks
        max_risk_ticks = 500  # $5.00 max risk per share
    elif symbol in ['ES', 'MES']:
        tick_size = 0.25
        tick_value = 12.50 if symbol == 'ES' else 1.25
        min_fvg_ticks = 3  # Reduced to catch smaller FVGs like the 9:45 gap
    elif symbol in ['NQ', 'MNQ']:
        tick_size = 0.25
        tick_value = 5.00 if symbol == 'NQ' else 0.50
        min_fvg_ticks = 8  # Reduced from 15 to allow more setups
        max_risk_ticks = 80  # NQ: 20 pts (was 200)
    else:
        tick_size = 0.25
        tick_value = 12.50
        min_fvg_ticks = 5

    # Bars needed - Hybrid timeframes
    # HTF (5m): sweep detection with proper lookback
    # MTF: FVG detection (3m catches gaps 5m misses, or 5m for unified)
    # LTF: MSS confirmation + trade simulation
    htf_bars_per_day = 78   # 5m bars in RTH
    if ltf_interval == '5m':
        mtf_bars_per_day = 78
        ltf_bars_per_day = 78
    else:
        mtf_bars_per_day = 130  # 3m bars in RTH
        ltf_bars_per_day = 130

    htf_bars_needed = days * htf_bars_per_day + 1000
    mtf_bars_needed = days * mtf_bars_per_day + 1500
    days * ltf_bars_per_day + 1500

    print(f"Fetching {symbol} HTF (5m) data...")
    htf_bars = fetch_futures_bars(symbol=symbol, interval='5m', n_bars=htf_bars_needed)

    if ltf_interval == '5m':
        print("Using 5m for all timeframes")
        mtf_bars = htf_bars
    else:
        print(f"Fetching {symbol} MTF ({ltf_interval}) data for FVG...")
        mtf_bars = fetch_futures_bars(symbol=symbol, interval=ltf_interval, n_bars=mtf_bars_needed)

    # Fetch 2m bars for trend filter (faster EMA)
    trend_bars_needed = days * 240 + 1500  # ~240 2m bars per day (8hrs)
    print(f"Fetching {symbol} trend (2m) data for EMA...")
    trend_bars = fetch_futures_bars(symbol=symbol, interval='2m', n_bars=trend_bars_needed)

    # Use same bars for MTF and LTF
    ltf_bars = mtf_bars

    if not htf_bars or not mtf_bars:
        print("No data available")
        return

    # Cache data so plotter uses identical bars
    cache_file = CACHE_DIR / f'ict_sweep_{symbol}.pkl'
    with open(cache_file, 'wb') as f:
        pickle.dump({'htf_bars': htf_bars, 'mtf_bars': mtf_bars}, f)
    print(f"Data cached to {cache_file}")

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
        'min_risk_ticks': min_risk_ticks if is_equity else 12,
        'max_risk_ticks': max_risk_ticks,
        'loss_cooldown_minutes': 15,  # No re-entry within 15 min of a loss
        'allow_lunch': False,
        'require_killzone': False,
        'max_daily_trades': 2,
        'max_daily_losses': 1,
        'use_mtf_for_fvg': True,      # Use 3m for FVG detection (catches gaps 5m misses)
        'entry_on_mitigation': True,  # Enter on FVG tap, don't wait for MSS
        'use_trend_filter': True,     # EMA 10/20 on 2m bars (faster trend detection)
        'ema_fast_period': 10,
        'ema_slow_period': 20,
        't1_r': t1_r,
        'trail_r': trail_r,
        'debug': '--debug' in sys.argv,
    }

    # Group bars by date
    dates = sorted(set(b.timestamp.date() for b in ltf_bars))

    print(f"\nAvailable dates in data: {dates}")
    print(f"Processing last {days} days: {dates[-days:]}")

    print()
    print("=" * 100)
    print(f"{symbol} ICT LIQUIDITY SWEEP STRATEGY BACKTEST")
    size_str = f"Risk: ${risk_per_trade}/trade" if is_equity else f"Contracts: {contracts}"
    print(f"HTF: 5m (sweep) | MTF: {ltf_interval} (FVG) | LTF: {ltf_interval} (MSS) | Days: {min(len(dates), days)} | {size_str} | T1={t1_r}R Trail={trail_r}R")
    print("=" * 100)
    print()
    print(f"{'Date':<12} | {'Time':<5} | {'Dir':<5} | {'Entry':>10} | {'Stop':>10} | {'Risk':>6} | "
          f"{'Result':<6} | {'P/L':>12} | {'Session':<10}")
    print("-" * 100)

    # Track results
    all_trades = []
    total_wins = 0
    total_losses = 0
    total_pnl = 0.0

    for day in dates[-days:]:
        session_end = dt_time(16, 0)

        if is_equity:
            # Equities: no Globex overnight session
            # HTF includes previous day RTH (swing highs/lows as liquidity) + current day premarket
            prev_day = day - timedelta(days=1)
            while prev_day.weekday() >= 5:  # Skip weekends
                prev_day = prev_day - timedelta(days=1)

            prev_rth_start = dt_time(9, 30)
            dt_time(4, 0)

            # HTF: prev day RTH + current day premarket through close
            day_htf = [b for b in htf_bars
                       if (b.timestamp.date() == prev_day
                           and prev_rth_start <= b.timestamp.time() <= session_end)
                       or (b.timestamp.date() == day and b.timestamp.time() <= session_end)]

            # Print previous day high/low for verification
            prev_day_bars = [b for b in day_htf if b.timestamp.date() == prev_day]
            if prev_day_bars:
                pdh = max(b.high for b in prev_day_bars)
                pdl = min(b.low for b in prev_day_bars)
                print(f"  [{day}] Prev Day: High={pdh:.2f} Low={pdl:.2f} (bars: {len(prev_day_bars)})")

            # MTF/LTF/trend: RTH only (9:30-16:00) for entries
            session_start = dt_time(9, 30)
            day_mtf = [b for b in mtf_bars if b.timestamp.date() == day
                       and session_start <= b.timestamp.time() <= session_end]
            day_ltf = [b for b in ltf_bars if b.timestamp.date() == day
                       and session_start <= b.timestamp.time() <= session_end]
            day_trend = [b for b in trend_bars if b.timestamp.date() == day
                         and session_start <= b.timestamp.time() <= session_end]
        else:
            # Futures: include overnight/Globex bars for liquidity level detection
            # Overnight session runs from previous day 18:00 through current day
            overnight_start = dt_time(18, 0)
            prev_day = day - timedelta(days=1)
            # Don't skip Sunday — futures Globex session opens Sunday 18:00 ET
            # If prev_day is Saturday, go back to Friday (no Globex on Saturday)
            if prev_day.weekday() == 5:  # Saturday
                prev_day = prev_day - timedelta(days=1)

            # HTF bars: previous day overnight (18:00+) + current day through session end
            day_htf = [b for b in htf_bars
                       if (b.timestamp.date() == prev_day and b.timestamp.time() >= overnight_start)
                       or (b.timestamp.date() == day and b.timestamp.time() <= session_end)]

            # Print overnight high/low for verification
            overnight_only = [b for b in day_htf if b.timestamp.date() == prev_day]
            if overnight_only:
                ovn_high = max(b.high for b in overnight_only)
                ovn_low = min(b.low for b in overnight_only)
                print(f"  [{day}] Overnight: High={ovn_high:.2f} Low={ovn_low:.2f} (bars: {len(overnight_only)})")

            # MTF/LTF/trend: keep restricted to current day 8:00-16:00 for entries
            session_start = dt_time(8, 0)
            day_mtf = [b for b in mtf_bars if b.timestamp.date() == day
                       and session_start <= b.timestamp.time() <= session_end]
            day_ltf = [b for b in ltf_bars if b.timestamp.date() == day
                       and session_start <= b.timestamp.time() <= session_end]
            day_trend = [b for b in trend_bars if b.timestamp.date() == day
                         and session_start <= b.timestamp.time() <= session_end]

        if len(day_htf) < 30 or len(day_ltf) < 50:
            print(f"  [{day}] Skipping - insufficient bars (HTF: {len(day_htf)}, LTF: {len(day_ltf)})")
            continue

        # Initialize strategy for the day
        strategy = ICTSweepStrategy(config)

        # HTF lookback from days before the lookback window for swing context
        lookback_htf = [b for b in htf_bars if b.timestamp.date() < prev_day][-50:]
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

        # Add trend bar lookback for EMA calculation
        lookback_trend = [b for b in trend_bars if b.timestamp.date() < day][-100:]
        for bar in lookback_trend:
            strategy.trend_bars.append(bar)

        # Dynamic sizing: track trades per direction for the day
        day_direction_trades = {'BULLISH': 0, 'BEARISH': 0, 'LONG': 0, 'SHORT': 0}

        # Process HTF, MTF, LTF, and trend bars together
        htf_idx = 0
        mtf_idx = 0
        ltf_idx = 0
        trend_idx = 0
        day_setups = 0
        day_mitigations = 0

        while ltf_idx < len(day_ltf):
            ltf_bar = day_ltf[ltf_idx]

            # Process any HTF bars that complete before this LTF bar
            while htf_idx < len(day_htf) and day_htf[htf_idx].timestamp <= ltf_bar.timestamp:
                htf_bar = day_htf[htf_idx]

                # Process trend (2m) bars up to this HTF bar
                while trend_idx < len(day_trend) and day_trend[trend_idx].timestamp <= htf_bar.timestamp:
                    strategy.update_trend(day_trend[trend_idx])
                    trend_idx += 1

                # Process MTF bars up to this HTF bar (must be before HTF for FVG detection)
                while mtf_idx < len(day_mtf) and day_mtf[mtf_idx].timestamp <= htf_bar.timestamp:
                    strategy.update_mtf(day_mtf[mtf_idx])
                    mtf_idx += 1

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

                    # Position sizing
                    dir_count = day_direction_trades.get(trade.direction, 0)
                    if is_equity:
                        risk_dollars = abs(trade.entry_price - trade.stop_price)
                        trade_contracts = max(3, int(risk_per_trade / risk_dollars)) if risk_dollars > 0 else 3
                    else:
                        # Dynamic sizing: 1st trade of direction = 3 cts, 2nd+ = 2 cts
                        trade_contracts = contracts if dir_count == 0 else max(2, contracts - 1)

                    # Simulate the trade
                    result = simulate_trade(
                        day_ltf[ltf_idx:],
                        trade,
                        tick_size,
                        tick_value,
                        trade_contracts,
                        t1_r=t1_r,
                        trail_r=trail_r,
                    )

                    if result:
                        day_direction_trades[trade.direction] = dir_count + 1
                        is_win = result['pnl_dollars'] > 0
                        is_loss = result['pnl_dollars'] < 0
                        exit_bar_idx = min(ltf_idx + result.get('bars_held', 1), len(day_ltf) - 1)
                        exit_time = day_ltf[exit_bar_idx].timestamp

                        if is_win:
                            total_wins += 1
                            result_str = 'WIN'
                        elif is_loss:
                            total_losses += 1
                            strategy.on_trade_result(result['pnl_dollars'], exit_time)
                            result_str = 'LOSS'
                        else:
                            result_str = 'BE'

                        total_pnl += result['pnl_dollars']
                        result['trade'] = trade
                        result['date'] = day
                        all_trades.append(result)

                        session = get_session_name(trade.timestamp)
                        est_time = format_et(trade.timestamp)

                        print(f"{day} | {est_time:<5} | {trade.direction:<5} | {trade.entry_price:>10.2f} | "
                              f"{trade.stop_price:>10.2f} | {trade.risk_ticks:>6.1f} | "
                              f"{result_str:<6} | ${result['pnl_dollars']:>+10,.2f} | {session:<10}")

                        ltf_idx += result.get('bars_held', 1)

                elif mitigation_result:
                    day_mitigations += len(mitigation_result)

                htf_idx += 1

            # Update LTF - check for MSS confirmation
            trade = strategy.update_ltf(ltf_bar)

            if trade:
                # Position sizing
                dir_count = day_direction_trades.get(trade.direction, 0)
                if is_equity:
                    risk_dollars = abs(trade.entry_price - trade.stop_price)
                    trade_contracts = max(3, int(risk_per_trade / risk_dollars)) if risk_dollars > 0 else 3
                else:
                    # Dynamic sizing: 1st trade of direction = 3 cts, 2nd+ = 2 cts
                    trade_contracts = contracts if dir_count == 0 else max(2, contracts - 1)

                # Simulate the trade
                result = simulate_trade(
                    day_ltf[ltf_idx:],
                    trade,
                    tick_size,
                    tick_value,
                    trade_contracts,
                    t1_r=t1_r,
                    trail_r=trail_r,
                )

                if result:
                    day_direction_trades[trade.direction] = dir_count + 1
                    is_win = result['pnl_dollars'] > 0
                    is_loss = result['pnl_dollars'] < 0
                    exit_bar_idx = min(ltf_idx + result.get('bars_held', 1), len(day_ltf) - 1)
                    exit_time = day_ltf[exit_bar_idx].timestamp

                    if is_win:
                        total_wins += 1
                        result_str = 'WIN'
                    elif is_loss:
                        total_losses += 1
                        strategy.on_trade_result(result['pnl_dollars'], exit_time)
                        result_str = 'LOSS'
                    else:
                        result_str = 'BE'

                    total_pnl += result['pnl_dollars']
                    result['trade'] = trade
                    result['date'] = day
                    all_trades.append(result)

                    session = get_session_name(trade.timestamp)
                    est_time = format_et(trade.timestamp)

                    print(f"{day} | {est_time:<5} | {trade.direction:<5} | {trade.entry_price:>10.2f} | "
                          f"{trade.stop_price:>10.2f} | {trade.risk_ticks:>6.1f} | "
                          f"{result_str:<6} | ${result['pnl_dollars']:>+10,.2f} | {session:<10}")

                    # Skip ahead to avoid overlapping trades
                    ltf_idx += result.get('bars_held', 1)

            ltf_idx += 1

        # Day summary
        print(f"  [{day}] Setups: {day_setups}, Mitigations: {day_mitigations}, Pending: {strategy.get_pending_count()}")

        # Cache day results for plotter
        day_trades = [t for t in all_trades if t.get('date') == day]
        day_cache = CACHE_DIR / f'ict_sweep_{symbol}_{day}.pkl'
        with open(day_cache, 'wb') as f:
            pickle.dump({
                'trades': day_trades,
                'day_htf': day_htf,
                'day_mtf': day_mtf,
                'day_ltf': day_ltf,
                'config': config,
            }, f)

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


def simulate_trade(bars, trade: TradeSetup, tick_size, tick_value, contracts,
                   t1_r=3, trail_r=6):
    """
    Simulate trade execution with hybrid exit: partial T1 + structure trailing.

    FVG-close stop logic preserved: candle CLOSE past FVG boundary stops out.
    Safety cap prevents runaway losses.

    Exit structure:
    - Pre-T1: FVG-close stop exits ALL contracts
    - T1 hit (t1_r): Fixed exit of 1 contract, trail floor at t1_r for remaining
    - Between T1 and trail_r: Floor at T1 profit acts as hard stop for T2/Runner
    - trail_r hit: Activate structure trailing for T2 (4-tick) and Runner (6-tick)
    - EOD: Exit all remaining at close

    Contract allocation:
    - 3 contracts: T1=1ct, T2=1ct, Runner=1ct
    - 2 contracts: T1=1ct, T2=1ct, Runner=0

    Args:
        bars: Remaining bars for the day
        trade: TradeSetup object
        tick_size: Instrument tick size
        tick_value: Dollar value per tick
        contracts: Number of contracts
        t1_r: R-multiple for T1 fixed exit
        trail_r: R-multiple for structure trail activation

    Returns:
        Trade result dict with backward-compatible fields plus 'exits' list
    """
    if len(bars) < 2:
        return None

    entry = trade.entry_price
    risk = abs(entry - trade.stop_price)

    # Calculate R-targets from entry
    is_long = trade.direction in ('LONG', 'BULLISH')
    if is_long:
        t1_price = entry + (risk * t1_r)
        trail_activate_price = entry + (risk * trail_r)
        t1_floor_price = entry + (risk * t1_r)  # Floor for T2/Runner after T1
    else:
        t1_price = entry - (risk * t1_r)
        trail_activate_price = entry - (risk * trail_r)
        t1_floor_price = entry - (risk * t1_r)

    # FVG-close stop: use FVG boundary for close-based stop
    fvg_stop_level = trade.fvg.top if trade.direction == 'BEARISH' else trade.fvg.bottom

    # Safety cap per symbol (ticks)
    max_loss_ticks = 100

    # Contract allocation
    t1_contracts = 1
    t2_contracts = 1
    runner_contracts = max(0, contracts - 2)  # 0 if only 2 contracts

    # Trail buffer configuration (ticks)
    t2_buffer_ticks = 4
    runner_buffer_ticks = 6
    t2_buffer = t2_buffer_ticks * tick_size
    runner_buffer = runner_buffer_ticks * tick_size

    # State tracking
    t1_exited = False
    t2_exited = False
    runner_exited = (runner_contracts == 0)  # Already "exited" if no runner
    trail_active = False

    # Trail stop levels (None until trail activates)
    t2_trail_stop = None
    runner_trail_stop = None

    # Track all exits for per-leg detail
    exits = []
    total_pnl = 0.0

    for i, bar in enumerate(bars[1:], 1):
        remaining = (0 if t1_exited else t1_contracts) + \
                    (0 if t2_exited else t2_contracts) + \
                    (0 if runner_exited else runner_contracts)

        if remaining == 0:
            break

        # --- PRE-T1: FVG-close stop exits ALL remaining contracts ---
        if not t1_exited:
            stopped = False
            if is_long:
                loss_ticks = (entry - bar.low) / tick_size
                if bar.close < fvg_stop_level or loss_ticks >= max_loss_ticks:
                    exit_price = bar.close if bar.close < fvg_stop_level else bar.low
                    stopped = True
            else:
                loss_ticks = (bar.high - entry) / tick_size
                if bar.close > fvg_stop_level or loss_ticks >= max_loss_ticks:
                    exit_price = bar.close if bar.close > fvg_stop_level else bar.high
                    stopped = True

            if stopped:
                pnl_ticks = ((exit_price - entry) if is_long else (entry - exit_price)) / tick_size
                leg_pnl = pnl_ticks * tick_value * remaining
                total_pnl += leg_pnl
                exits.append({'leg': 'STOP', 'price': exit_price, 'contracts': remaining,
                              'pnl': leg_pnl, 'bar_idx': i})
                return {
                    'entry': entry, 'exit': exit_price,
                    'pnl_ticks': pnl_ticks,
                    'pnl_dollars': total_pnl,
                    'hit_target': False, 'bars_held': i,
                    'exits': exits,
                }

        # --- Check T1 hit ---
        if not t1_exited:
            t1_hit = (bar.high >= t1_price) if is_long else (bar.low <= t1_price)
            if t1_hit:
                t1_exited = True
                pnl_ticks_t1 = ((t1_price - entry) if is_long else (entry - t1_price)) / tick_size
                leg_pnl = pnl_ticks_t1 * tick_value * t1_contracts
                total_pnl += leg_pnl
                exits.append({'leg': 'T1', 'price': t1_price, 'contracts': t1_contracts,
                              'pnl': leg_pnl, 'bar_idx': i})

        # --- Post-T1: trail floor at T1 profit as hard stop for T2/Runner ---
        if t1_exited and not trail_active:
            floor_hit = False
            if is_long:
                if bar.low <= t1_floor_price:
                    floor_hit = True
                    exit_price = t1_floor_price
            else:
                if bar.high >= t1_floor_price:
                    floor_hit = True
                    exit_price = t1_floor_price

            if floor_hit:
                remaining_after_t1 = (0 if t2_exited else t2_contracts) + \
                                     (0 if runner_exited else runner_contracts)
                if remaining_after_t1 > 0:
                    pnl_ticks_floor = ((exit_price - entry) if is_long else (entry - exit_price)) / tick_size
                    leg_pnl = pnl_ticks_floor * tick_value * remaining_after_t1
                    total_pnl += leg_pnl
                    exits.append({'leg': 'FLOOR', 'price': exit_price,
                                  'contracts': remaining_after_t1, 'pnl': leg_pnl, 'bar_idx': i})
                    t2_exited = True
                    runner_exited = True

                    # All out
                    pnl_ticks = ((exit_price - entry) if is_long else (entry - exit_price)) / tick_size
                    return {
                        'entry': entry, 'exit': exit_price,
                        'pnl_ticks': pnl_ticks,
                        'pnl_dollars': total_pnl,
                        'hit_target': True, 'bars_held': i,
                        'exits': exits,
                    }

        # --- Check trail activation (trail_r hit) ---
        if t1_exited and not trail_active:
            trail_hit = (bar.high >= trail_activate_price) if is_long else (bar.low <= trail_activate_price)
            if trail_hit:
                trail_active = True
                # Initialize trail stops from current structure
                if is_long:
                    # Find most recent swing low for trail
                    best_swing = entry  # fallback
                    for j in range(max(0, i - 10), i):
                        if j >= 1 and is_swing_low(bars, j, lookback=2):
                            best_swing = max(best_swing, bars[j].low)
                    t2_trail_stop = best_swing - t2_buffer
                    runner_trail_stop = best_swing - runner_buffer
                else:
                    best_swing = entry + risk * 20  # fallback (high value)
                    for j in range(max(0, i - 10), i):
                        if j >= 1 and is_swing_high(bars, j, lookback=2):
                            best_swing = min(best_swing, bars[j].high)
                    t2_trail_stop = best_swing + t2_buffer
                    runner_trail_stop = best_swing + runner_buffer

                # Ensure trail is at least at T1 floor
                if is_long:
                    t2_trail_stop = max(t2_trail_stop, t1_floor_price)
                    runner_trail_stop = max(runner_trail_stop, t1_floor_price)
                else:
                    t2_trail_stop = min(t2_trail_stop, t1_floor_price)
                    runner_trail_stop = min(runner_trail_stop, t1_floor_price)

        # --- Update structure trail stops ---
        if trail_active:
            # Update trail using swing structure
            if is_long:
                if i >= 3 and is_swing_low(bars, i - 2, lookback=2):
                    new_trail = bars[i - 2].low
                    t2_trail_stop = max(t2_trail_stop, new_trail - t2_buffer)
                    runner_trail_stop = max(runner_trail_stop, new_trail - runner_buffer)
            else:
                if i >= 3 and is_swing_high(bars, i - 2, lookback=2):
                    new_trail = bars[i - 2].high
                    t2_trail_stop = min(t2_trail_stop, new_trail + t2_buffer)
                    runner_trail_stop = min(runner_trail_stop, new_trail + runner_buffer)

            # Check T2 trail stop
            if not t2_exited:
                t2_stopped = (bar.low <= t2_trail_stop) if is_long else (bar.high >= t2_trail_stop)
                if t2_stopped:
                    t2_exited = True
                    exit_price = t2_trail_stop
                    pnl_ticks_t2 = ((exit_price - entry) if is_long else (entry - exit_price)) / tick_size
                    leg_pnl = pnl_ticks_t2 * tick_value * t2_contracts
                    total_pnl += leg_pnl
                    exits.append({'leg': 'T2', 'price': exit_price, 'contracts': t2_contracts,
                                  'pnl': leg_pnl, 'bar_idx': i})

            # Check Runner trail stop
            if not runner_exited:
                runner_stopped = (bar.low <= runner_trail_stop) if is_long else (bar.high >= runner_trail_stop)
                if runner_stopped:
                    runner_exited = True
                    exit_price = runner_trail_stop
                    pnl_ticks_r = ((exit_price - entry) if is_long else (entry - exit_price)) / tick_size
                    leg_pnl = pnl_ticks_r * tick_value * runner_contracts
                    total_pnl += leg_pnl
                    exits.append({'leg': 'Runner', 'price': exit_price, 'contracts': runner_contracts,
                                  'pnl': leg_pnl, 'bar_idx': i})

        # Check if all legs exited
        if t1_exited and t2_exited and runner_exited:
            last_exit = exits[-1] if exits else {'price': entry, 'bar_idx': i}
            pnl_ticks = ((last_exit['price'] - entry) if is_long else (entry - last_exit['price'])) / tick_size
            return {
                'entry': entry, 'exit': last_exit['price'],
                'pnl_ticks': pnl_ticks,
                'pnl_dollars': total_pnl,
                'hit_target': True, 'bars_held': i,
                'exits': exits,
            }

    # End of day - exit all remaining at close
    exit_price = bars[-1].close
    remaining = (0 if t1_exited else t1_contracts) + \
                (0 if t2_exited else t2_contracts) + \
                (0 if runner_exited else runner_contracts)

    if remaining > 0:
        pnl_ticks_eod = ((exit_price - entry) if is_long else (entry - exit_price)) / tick_size
        leg_pnl = pnl_ticks_eod * tick_value * remaining
        total_pnl += leg_pnl
        exits.append({'leg': 'EOD', 'price': exit_price, 'contracts': remaining,
                      'pnl': leg_pnl, 'bar_idx': len(bars) - 1})

    pnl_ticks = ((exit_price - entry) if is_long else (entry - exit_price)) / tick_size
    return {
        'entry': entry, 'exit': exit_price,
        'pnl_ticks': pnl_ticks,
        'pnl_dollars': total_pnl,
        'hit_target': t1_exited, 'bars_held': len(bars) - 1,
        'exits': exits,
    }


if __name__ == '__main__':
    # Parse flags
    use_5m = '--5m' in sys.argv
    t1_r_val = 3
    trail_r_val = 6
    positional = []
    for a in sys.argv[1:]:
        if a == '--5m':
            continue
        elif a.startswith('--t1-r='):
            t1_r_val = int(a.split('=')[1])
        elif a.startswith('--trail-r='):
            trail_r_val = int(a.split('=')[1])
        elif a.startswith('--'):
            continue  # Skip other flags like --debug
        else:
            positional.append(a)

    symbol = positional[0] if len(positional) > 0 else 'ES'
    days = int(positional[1]) if len(positional) > 1 else 14
    ltf = '5m' if use_5m else '3m'

    # 3rd positional: contracts (futures) or risk_per_trade (equities)
    if symbol.upper() in EQUITY_SYMBOLS:
        risk_dollars = float(positional[2]) if len(positional) > 2 else 500
        run_backtest(symbol=symbol, days=days, contracts=3, ltf_interval=ltf,
                     t1_r=t1_r_val, trail_r=trail_r_val, risk_per_trade=risk_dollars)
    else:
        contracts = int(positional[2]) if len(positional) > 2 else 3
        run_backtest(symbol=symbol, days=days, contracts=contracts, ltf_interval=ltf,
                     t1_r=t1_r_val, trail_r=trail_r_val)
