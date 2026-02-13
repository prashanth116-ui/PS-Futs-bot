"""
HTF (Higher Time Frame) Strategy Backtest Runner

Multi-timeframe strategy:
- HTF (15m/1h) for bias and key levels
- LTF (3m/5m) for precise entries

V10.8 Hybrid Filter System:
- 2 mandatory filters (DI direction)
- 2/3 optional filters (displacement, ADX, EMA alignment)
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time, timedelta
from core.types import Bar
from runners.tradingview_loader import fetch_futures_bars
from strategies.htf_strategy.filters.trend import (
    calculate_adx, calculate_displacement, calculate_avg_body_size
)


def run_htf_backtest(symbol='ES', days=14, contracts=3, htf='15m', ltf='3m'):
    """
    Run HTF strategy backtest.

    Args:
        symbol: Instrument symbol (ES, NQ)
        days: Number of days to backtest
        contracts: Number of contracts per trade
        htf: Higher timeframe for bias (15m, 1h)
        ltf: Lower timeframe for entry (3m, 5m)
    """
    tick_size = 0.25
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25

    # Bars per day for each timeframe
    bars_per_day = {'1m': 780, '3m': 260, '5m': 156, '15m': 52, '30m': 26, '1h': 13}

    # Fetch both timeframes
    htf_bars_needed = days * bars_per_day.get(htf, 52)
    ltf_bars_needed = days * bars_per_day.get(ltf, 260)

    print(f'Fetching {symbol} HTF ({htf}) data...')
    htf_bars = fetch_futures_bars(symbol=symbol, interval=htf, n_bars=htf_bars_needed)

    print(f'Fetching {symbol} LTF ({ltf}) data...')
    ltf_bars = fetch_futures_bars(symbol=symbol, interval=ltf, n_bars=ltf_bars_needed)

    if not htf_bars or not ltf_bars:
        print('No data available')
        return

    # Group by date
    dates = sorted(set(b.timestamp.date() for b in ltf_bars))

    print()
    print(f"=" * 80)
    print(f"{symbol} HTF STRATEGY BACKTEST")
    print(f"HTF: {htf} | LTF: {ltf} | Days: {len(dates)} | Contracts: {contracts}")
    print(f"=" * 80)
    print()

    # Strategy parameters
    config = {
        'swing_lookback': 5,
        'level_tolerance_ticks': 8,
        'stop_buffer_ticks': 4,
        'min_rr_ratio': 2.0,
        'htf_ema_fast': 20,
        'htf_ema_slow': 50,
        # V10.8 Hybrid Filter Settings
        'displacement_threshold': 1.0,  # >= 1.0x average body
        'min_adx': 11,                  # ADX >= 11 (V10.8 default)
        'high_displacement_override': 3.0,  # 3x body allows ADX >= 10
        'high_displacement_min_adx': 10,
        # Optional: require displacement for patterns
        'require_displacement': False,  # If True, displacement must pass
    }

    # Track results
    total_wins = 0
    total_losses = 0
    total_pnl = 0.0
    all_trades = []
    max_losses_per_day = 2

    print(f"{'Date':<12} | {'Dir':<5} | {'Pattern':<15} | {'Entry':<10} | {'ADX':>5} | {'Disp':>5} | {'Result':<6} | {'P/L':>12}")
    print("-" * 95)

    for day in dates[-days:]:
        # Get HTF bars for this day (and lookback for levels)
        day_htf = [b for b in htf_bars if b.timestamp.date() <= day][-100:]
        day_ltf = [b for b in ltf_bars if b.timestamp.date() == day]

        # Filter to trading session
        premarket_start = dt_time(4, 0)
        rth_end = dt_time(16, 0)
        session_ltf = [b for b in day_ltf if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_ltf) < 30 or len(day_htf) < 50:
            continue

        # Calculate average body size for displacement filter (first 50 bars)
        avg_body_size = calculate_avg_body_size(session_ltf[:50]) if len(session_ltf) >= 50 else calculate_avg_body_size(session_ltf)

        # Analyze HTF bias and levels
        htf_bias = analyze_htf_bias(day_htf, config)

        if htf_bias['direction'] == 'NEUTRAL':
            continue

        # Find key levels
        key_levels = find_key_levels(day_htf, config, tick_size)

        if not key_levels:
            continue

        day_loss_count = 0

        # Process LTF bars for entries
        for i in range(20, len(session_ltf)):
            if day_loss_count >= max_losses_per_day:
                break

            ltf_window = session_ltf[:i+1]
            current_bar = ltf_window[-1]
            current_price = current_bar.close

            # Find nearest levels
            nearest_support, nearest_resistance = find_nearest_levels(key_levels, current_price)

            # Check for entry based on HTF bias
            setup = None

            if htf_bias['direction'] == 'BULLISH' and nearest_support:
                # Look for long at support
                tolerance = config['level_tolerance_ticks'] * tick_size
                if abs(current_price - nearest_support) <= tolerance:
                    pattern = check_bullish_pattern(ltf_window)
                    if pattern:
                        # V10.8 Hybrid Filter Check
                        filter_pass, filter_details = check_hybrid_filters(
                            ltf_window, 'LONG', config, avg_body_size
                        )
                        if not filter_pass:
                            continue  # Skip entry if filters fail

                        stop = nearest_support - (config['stop_buffer_ticks'] * tick_size)
                        risk = current_price - stop
                        target = current_price + (risk * config['min_rr_ratio'])

                        if nearest_resistance and nearest_resistance > current_price:
                            target = min(target, nearest_resistance)

                        setup = {
                            'direction': 'LONG',
                            'entry': current_price,
                            'stop': stop,
                            'target': target,
                            'pattern': pattern,
                            'bar_idx': i,
                            'filter_details': filter_details
                        }

            elif htf_bias['direction'] == 'BEARISH' and nearest_resistance:
                # Look for short at resistance
                tolerance = config['level_tolerance_ticks'] * tick_size
                if abs(current_price - nearest_resistance) <= tolerance:
                    pattern = check_bearish_pattern(ltf_window)
                    if pattern:
                        # V10.8 Hybrid Filter Check
                        filter_pass, filter_details = check_hybrid_filters(
                            ltf_window, 'SHORT', config, avg_body_size
                        )
                        if not filter_pass:
                            continue  # Skip entry if filters fail

                        stop = nearest_resistance + (config['stop_buffer_ticks'] * tick_size)
                        risk = stop - current_price
                        target = current_price - (risk * config['min_rr_ratio'])

                        if nearest_support and nearest_support < current_price:
                            target = max(target, nearest_support)

                        setup = {
                            'direction': 'SHORT',
                            'entry': current_price,
                            'stop': stop,
                            'target': target,
                            'pattern': pattern,
                            'bar_idx': i,
                            'filter_details': filter_details
                        }

            if setup:
                # Simulate trade
                result = simulate_trade(
                    bars=session_ltf[setup['bar_idx']:],
                    direction=setup['direction'],
                    entry=setup['entry'],
                    stop=setup['stop'],
                    target=setup['target'],
                    tick_size=tick_size,
                    tick_value=tick_value,
                    contracts=contracts
                )

                if result:
                    is_win = result['pnl_dollars'] > 0
                    is_loss = result['pnl_dollars'] < 0

                    if is_win:
                        total_wins += 1
                        result_str = 'WIN'
                    elif is_loss:
                        total_losses += 1
                        day_loss_count += 1
                        result_str = 'LOSS'
                    else:
                        result_str = 'BE'

                    total_pnl += result['pnl_dollars']
                    # Store filter details with trade result
                    result['filter_details'] = setup.get('filter_details', {})
                    all_trades.append(result)

                    fd = setup.get('filter_details', {})
                    adx_str = f"{fd.get('adx', 0):.0f}"
                    disp_str = f"{fd.get('disp_ratio', 0):.1f}x"
                    print(f"{day} | {setup['direction']:<5} | {setup['pattern']:<15} | "
                          f"{setup['entry']:<10.2f} | {adx_str:>5} | {disp_str:>5} | {result_str:<6} | "
                          f"${result['pnl_dollars']:>+10,.2f}")

                    # Skip ahead to avoid overlapping trades
                    break

    # Print summary
    print("-" * 95)
    print()
    print("=" * 95)
    print("SUMMARY")
    print("=" * 95)

    total_trades = total_wins + total_losses
    win_rate = (total_wins / total_trades * 100) if total_trades > 0 else 0
    avg_win = sum(t['pnl_dollars'] for t in all_trades if t['pnl_dollars'] > 0) / total_wins if total_wins > 0 else 0
    avg_loss = sum(t['pnl_dollars'] for t in all_trades if t['pnl_dollars'] < 0) / total_losses if total_losses > 0 else 0

    print(f"  HTF: {htf} | LTF: {ltf}")
    print(f"  Total Trades:  {total_trades}")
    print(f"  Wins:          {total_wins}")
    print(f"  Losses:        {total_losses}")
    print(f"  Win Rate:      {win_rate:.1f}%")
    print(f"  Avg Win:       ${avg_win:+,.2f}")
    print(f"  Avg Loss:      ${avg_loss:+,.2f}")
    if total_losses > 0 and avg_loss != 0:
        print(f"  Profit Factor: {abs(avg_win * total_wins / (avg_loss * total_losses)):.2f}")
    print()
    print(f"  TOTAL P/L:     ${total_pnl:+,.2f}")
    print("=" * 95)
    print()
    print("V10.8 Hybrid Filter System:")
    print("  - MANDATORY: DI Direction (must pass)")
    print("  - OPTIONAL: 2/3 of [Displacement >= 1.0x, ADX >= 11, EMA Alignment]")
    print("  - High Disp Override: 3x body allows ADX >= 10")
    print()

    # Show filter breakdown for analysis
    if all_trades:
        high_disp_trades = [t for t in all_trades if t.get('filter_details', {}).get('high_disp', False)]
        adx_pass_trades = [t for t in all_trades if t.get('filter_details', {}).get('adx_ok', False)]
        ema_pass_trades = [t for t in all_trades if t.get('filter_details', {}).get('ema_ok', False)]
        disp_pass_trades = [t for t in all_trades if t.get('filter_details', {}).get('disp_ok', False)]

        print("Filter Breakdown:")
        print(f"  Displacement Pass: {len(disp_pass_trades)}/{len(all_trades)}")
        print(f"  ADX Pass:          {len(adx_pass_trades)}/{len(all_trades)}")
        print(f"  EMA Pass:          {len(ema_pass_trades)}/{len(all_trades)}")
        print(f"  High Disp (3x):    {len(high_disp_trades)}/{len(all_trades)}")
        print()

    return all_trades


def analyze_htf_bias(bars, config):
    """Analyze HTF bars for trend bias."""
    if len(bars) < config['htf_ema_slow']:
        return {'direction': 'NEUTRAL', 'strength': 0}

    closes = [b.close for b in bars]
    fast_ema = calculate_ema(closes, config['htf_ema_fast'])
    slow_ema = calculate_ema(closes, config['htf_ema_slow'])

    if not fast_ema or not slow_ema:
        return {'direction': 'NEUTRAL', 'strength': 0}

    if fast_ema[-1] > slow_ema[-1]:
        direction = 'BULLISH'
        strength = (fast_ema[-1] - slow_ema[-1]) / slow_ema[-1] * 100
    elif fast_ema[-1] < slow_ema[-1]:
        direction = 'BEARISH'
        strength = (slow_ema[-1] - fast_ema[-1]) / slow_ema[-1] * 100
    else:
        direction = 'NEUTRAL'
        strength = 0

    return {'direction': direction, 'strength': strength}


def find_key_levels(bars, config, tick_size):
    """Find support/resistance levels from swing points."""
    lookback = config['swing_lookback']
    levels = []

    if len(bars) < lookback * 2 + 1:
        return levels

    for i in range(lookback, len(bars) - lookback):
        bar = bars[i]

        # Swing high
        is_swing_high = all(
            bar.high >= bars[i + j].high
            for j in range(-lookback, lookback + 1) if j != 0
        )
        if is_swing_high:
            levels.append({'price': bar.high, 'type': 'RESISTANCE'})

        # Swing low
        is_swing_low = all(
            bar.low <= bars[i + j].low
            for j in range(-lookback, lookback + 1) if j != 0
        )
        if is_swing_low:
            levels.append({'price': bar.low, 'type': 'SUPPORT'})

    # Merge nearby levels
    tolerance = config['level_tolerance_ticks'] * tick_size
    merged = []

    for level in sorted(levels, key=lambda x: x['price']):
        found = False
        for m in merged:
            if abs(m['price'] - level['price']) <= tolerance:
                m['price'] = (m['price'] + level['price']) / 2
                m['touches'] = m.get('touches', 1) + 1
                found = True
                break
        if not found:
            merged.append({'price': level['price'], 'type': level['type'], 'touches': 1})

    return merged


def find_nearest_levels(levels, current_price):
    """Find nearest support and resistance."""
    supports = [l['price'] for l in levels if l['price'] < current_price]
    resistances = [l['price'] for l in levels if l['price'] > current_price]

    nearest_support = max(supports) if supports else None
    nearest_resistance = min(resistances) if resistances else None

    return nearest_support, nearest_resistance


def check_bullish_pattern(bars):
    """Check for bullish entry pattern."""
    if len(bars) < 3:
        return None

    current = bars[-1]
    prev = bars[-2]

    # Bullish engulfing
    if (prev.close < prev.open and
        current.close > current.open and
        current.close > prev.open and
        current.open <= prev.close):
        return 'bull_engulfing'

    # Hammer
    body = abs(current.close - current.open)
    lower_wick = min(current.open, current.close) - current.low
    upper_wick = current.high - max(current.open, current.close)

    if body > 0 and lower_wick > body * 2 and upper_wick < body:
        return 'hammer'

    # Bullish rejection
    if body > 0 and lower_wick > body * 1.5:
        return 'bull_rejection'

    return None


def check_bearish_pattern(bars):
    """Check for bearish entry pattern."""
    if len(bars) < 3:
        return None

    current = bars[-1]
    prev = bars[-2]

    # Bearish engulfing
    if (prev.close > prev.open and
        current.close < current.open and
        current.close < prev.open and
        current.open >= prev.close):
        return 'bear_engulfing'

    # Shooting star
    body = abs(current.close - current.open)
    lower_wick = min(current.open, current.close) - current.low
    upper_wick = current.high - max(current.open, current.close)

    if body > 0 and upper_wick > body * 2 and lower_wick < body:
        return 'shooting_star'

    # Bearish rejection
    if body > 0 and upper_wick > body * 1.5:
        return 'bear_rejection'

    return None


def simulate_trade(bars, direction, entry, stop, target, tick_size, tick_value, contracts):
    """Simulate trade execution."""
    if len(bars) < 2:
        return None

    for bar in bars[1:]:
        if direction == 'LONG':
            # Check stop first (conservative)
            if bar.low <= stop:
                exit_price = stop
                pnl_ticks = (exit_price - entry) / tick_size
                return {
                    'entry': entry,
                    'exit': exit_price,
                    'pnl_ticks': pnl_ticks,
                    'pnl_dollars': pnl_ticks * tick_value * contracts,
                    'hit_target': False
                }
            # Check target
            if bar.high >= target:
                exit_price = target
                pnl_ticks = (exit_price - entry) / tick_size
                return {
                    'entry': entry,
                    'exit': exit_price,
                    'pnl_ticks': pnl_ticks,
                    'pnl_dollars': pnl_ticks * tick_value * contracts,
                    'hit_target': True
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
                    'pnl_dollars': pnl_ticks * tick_value * contracts,
                    'hit_target': False
                }
            # Check target
            if bar.low <= target:
                exit_price = target
                pnl_ticks = (entry - exit_price) / tick_size
                return {
                    'entry': entry,
                    'exit': exit_price,
                    'pnl_ticks': pnl_ticks,
                    'pnl_dollars': pnl_ticks * tick_value * contracts,
                    'hit_target': True
                }

    # End of day - exit at last close
    exit_price = bars[-1].close
    if direction == 'LONG':
        pnl_ticks = (exit_price - entry) / tick_size
    else:
        pnl_ticks = (entry - exit_price) / tick_size

    return {
        'entry': entry,
        'exit': exit_price,
        'pnl_ticks': pnl_ticks,
        'pnl_dollars': pnl_ticks * tick_value * contracts,
        'hit_target': False
    }


def calculate_ema(prices, period):
    """Calculate EMA."""
    if len(prices) < period:
        return []
    multiplier = 2 / (period + 1)
    ema = [sum(prices[:period]) / period]
    for price in prices[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema


def check_hybrid_filters(bars, direction, config, avg_body_size):
    """
    V10.8 Hybrid Filter System.

    MANDATORY (must pass):
    - DI Direction: +DI > -DI for LONG, -DI > +DI for SHORT

    OPTIONAL (2 of 3 must pass):
    - Displacement: >= threshold * average body
    - ADX: >= min_adx (or high_displacement_min_adx if 3x displacement)
    - EMA Alignment: EMA20 vs EMA50

    Args:
        bars: Price bars for indicator calculation
        direction: 'LONG' or 'SHORT'
        config: Strategy config with filter thresholds
        avg_body_size: Pre-calculated average body size

    Returns:
        Tuple of (passes, details_dict)
    """
    is_long = direction == 'LONG'
    current_bar = bars[-1]

    # Calculate indicators
    adx, plus_di, minus_di = calculate_adx(bars)

    closes = [b.close for b in bars]
    ema_fast = calculate_ema(closes, config.get('htf_ema_fast', 20))
    ema_slow = calculate_ema(closes, config.get('htf_ema_slow', 50))

    # === MANDATORY: DI Direction ===
    if adx > 0:  # Only check if ADX is valid
        di_ok = (plus_di > minus_di) if is_long else (minus_di > plus_di)
        if not di_ok:
            return False, {'reason': 'DI_DIRECTION_FAIL', 'adx': adx, 'plus_di': plus_di, 'minus_di': minus_di}
    else:
        di_ok = True  # Skip if no ADX data

    # === OPTIONAL FILTERS (2 of 3 must pass) ===
    body = abs(current_bar.close - current_bar.open)

    # 1. Displacement check
    disp_threshold = config.get('displacement_threshold', 1.0)
    disp_ok = body >= avg_body_size * disp_threshold if avg_body_size > 0 else True

    # 2. ADX check (with high displacement override)
    high_disp_threshold = config.get('high_displacement_override', 3.0)
    high_disp = body >= avg_body_size * high_disp_threshold if avg_body_size > 0 else False
    min_adx = config.get('high_displacement_min_adx', 10) if high_disp else config.get('min_adx', 11)
    # If no ADX data, default to False (require valid ADX) unless high displacement
    adx_ok = adx >= min_adx if adx > 0 else high_disp

    # 3. EMA Alignment check
    if ema_fast and ema_slow:
        ema_ok = (ema_fast[-1] > ema_slow[-1]) if is_long else (ema_fast[-1] < ema_slow[-1])
    else:
        ema_ok = True  # Skip if no EMA data

    # Count optional filters passed
    optional_passed = sum([disp_ok, adx_ok, ema_ok])

    details = {
        'adx': round(adx, 1),
        'plus_di': round(plus_di, 1),
        'minus_di': round(minus_di, 1),
        'body': round(body, 2),
        'avg_body': round(avg_body_size, 2),
        'disp_ratio': round(body / avg_body_size, 2) if avg_body_size > 0 else 0,
        'disp_ok': disp_ok,
        'adx_ok': adx_ok,
        'ema_ok': ema_ok,
        'optional_passed': optional_passed,
        'high_disp': high_disp,
    }

    # Optional: require displacement for pattern entries at S/R
    require_disp = config.get('require_displacement', False)
    if require_disp and not disp_ok:
        details['reason'] = 'DISPLACEMENT_REQUIRED'
        return False, details

    if optional_passed < 2:
        details['reason'] = f'OPTIONAL_FAIL ({optional_passed}/3)'
        return False, details

    details['reason'] = 'PASS'
    return True, details


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 14
    htf = sys.argv[3] if len(sys.argv) > 3 else '15m'
    ltf = sys.argv[4] if len(sys.argv) > 4 else '3m'

    run_htf_backtest(symbol=symbol, days=days, htf=htf, ltf=ltf)
