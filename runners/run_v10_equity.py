"""
V10 Equity Runner - SPY/QQQ Support (V10.4 - ATR Buffer)

Adapts the V10 Quad Entry strategy for equity trading.
Uses share-based position sizing instead of contracts.

Key Differences from Futures:
- Position size: shares (based on risk $) instead of fixed contracts
- P/L calculation: shares × price move (no tick conversion)
- Same session times: 9:30-16:00 ET
- Same FVG/entry logic

V10.4 Changes:
- ATR-based stop buffer (ATR × 0.5) instead of fixed $0.02
- Improves P/L by ~$54k over 30 days by avoiding stop hunts
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time, timedelta
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import (
    calculate_ema,
    calculate_adx,
    is_swing_high,
    is_swing_low,
    find_recent_swing_high,
    find_recent_swing_low,
)
from strategies.ict.signals.fvg import detect_fvgs, update_fvg_mitigation


# Equity instrument configurations
EQUITY_CONFIG = {
    'SPY': {
        'name': 'S&P 500 ETF',
        'min_fvg_points': 0.20,      # Min FVG size in dollars
        'min_risk_points': 0.30,      # Min risk per trade
        'default_risk_dollars': 500,  # Risk per trade in dollars
    },
    'QQQ': {
        'name': 'Nasdaq 100 ETF',
        'min_fvg_points': 0.40,      # Min FVG size in dollars
        'min_risk_points': 0.50,      # Min risk per trade
        'default_risk_dollars': 500,  # Risk per trade in dollars
    },
    'IWM': {
        'name': 'Russell 2000 ETF',
        'min_fvg_points': 0.15,
        'min_risk_points': 0.25,
        'default_risk_dollars': 500,
    },
}


def calculate_atr(bars, period=14):
    """
    Calculate Average True Range for adaptive stop buffer.

    ATR measures volatility - higher ATR = more volatile = wider stops needed.
    """
    if len(bars) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        prev_close = bars[i-1].close

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    # Simple moving average of recent true ranges
    return sum(true_ranges[-period:]) / period


def run_session_v10_equity(
    session_bars,
    all_bars,
    symbol='SPY',
    risk_per_trade=500,         # Risk $ per trade
    max_open_trades=2,
    min_fvg_pts=None,           # Override config
    min_risk_pts=None,          # Override config
    t1_fixed_4r=True,           # HYBRID: T1 fixed at 4R
    overnight_retrace_min_adx=22,  # ADX filter for overnight retrace
    # V10.2 time filters
    midday_cutoff=True,         # No entries 12:00-14:00 (lunch lull)
    pm_cutoff_qqq=True,         # No QQQ entries after 14:00 (SPY allowed)
    # V10.3 entry type filters
    disable_intraday_spy=True,  # Disable INTRADAY entries for SPY (24% win rate)
    # V10.4 ATR buffer
    atr_buffer_multiplier=0.5,  # Stop buffer = ATR × multiplier (0 = use fixed $0.02)
    # V10.5 high displacement override
    high_displacement_override=3.0,  # Skip ADX check if displacement >= 3x avg body
):
    """
    Run V10 strategy on equity bars.

    Position sizing:
        shares = risk_per_trade / risk_in_points

    P/L calculation:
        pnl_dollars = shares × price_move
    """
    if not session_bars or len(session_bars) < 50:
        return []

    config = EQUITY_CONFIG.get(symbol.upper(), EQUITY_CONFIG['SPY'])
    min_fvg_size = min_fvg_pts if min_fvg_pts else config['min_fvg_points']
    min_risk = min_risk_pts if min_risk_pts else config['min_risk_points']

    # For equities, tick_size is $0.01
    tick_size = 0.01

    # FVG detection config
    fvg_config = {
        'min_fvg_ticks': int(min_fvg_size / tick_size),
        'tick_size': tick_size,
        'max_fvg_age_bars': 200,
        'invalidate_on_close_through': True
    }

    # Get bars before session for indicator calculation
    session_start = session_bars[0].timestamp
    pre_session_bars = [b for b in all_bars if b.timestamp < session_start]

    # Session time boundaries
    rth_start = dt_time(9, 30)
    rth_end = dt_time(16, 0)
    morning_end = dt_time(12, 0)

    # Detect all FVGs from all bars (similar to V10 futures)
    all_fvgs = detect_fvgs(all_bars, fvg_config)

    # Categorize FVGs as overnight or session
    overnight_fvgs = []
    session_fvgs = []
    all_valid_entries = []

    for fvg in all_fvgs:
        fvg_time = fvg.created_at.time() if hasattr(fvg, 'created_at') else None
        # Map direction: BULLISH -> LONG, BEARISH -> SHORT
        direction = 'LONG' if fvg.direction == 'BULLISH' else 'SHORT'
        # Convert FVG object to dict for compatibility
        fvg_dict = {
            'direction': direction,
            'low': fvg.low,
            'high': fvg.high,
            'created_at': fvg.created_at,
            'is_overnight': fvg_time and fvg_time < rth_start if fvg_time else False,
            'used_for_entry': False,
            'creation_bar_idx': next((i for i, b in enumerate(session_bars) if b.timestamp >= fvg.created_at), 0),
        }
        if fvg_dict['is_overnight']:
            overnight_fvgs.append(fvg_dict)
        else:
            session_fvgs.append(fvg_dict)

    # Calculate indicators
    indicator_bars = pre_session_bars[-100:] if len(pre_session_bars) >= 100 else pre_session_bars
    ema_20 = calculate_ema(indicator_bars, 20) if len(indicator_bars) >= 20 else None
    ema_50 = calculate_ema(indicator_bars, 50) if len(indicator_bars) >= 50 else None
    adx, plus_di, minus_di = calculate_adx(indicator_bars, 14) if len(indicator_bars) >= 28 else (None, None, None)
    current_atr = calculate_atr(indicator_bars, 14)

    # Determine bias
    if ema_20 and ema_50:
        htf_bias = 'LONG' if ema_20 > ema_50 else 'SHORT'
    else:
        htf_bias = None

    # Default stop buffer (fallback if ATR not available)
    default_buffer = 0.02

    # Track swing highs/lows for BOS
    recent_swing_high = None
    recent_swing_low = None

    # Process session bars
    for i, bar in enumerate(session_bars):
        bar_time = bar.timestamp.time()

        # Update indicators every 5 bars (was 20 - caused stale bias issues)
        if i % 5 == 0:
            bars_to_now = [b for b in all_bars if b.timestamp <= bar.timestamp][-100:]
            ema_20 = calculate_ema(bars_to_now, 20)
            ema_50 = calculate_ema(bars_to_now, 50)
            adx, plus_di, minus_di = calculate_adx(bars_to_now, 14)
            current_atr = calculate_atr(bars_to_now, 14)
            if ema_20 and ema_50:
                htf_bias = 'LONG' if ema_20 > ema_50 else 'SHORT'

        # Calculate stop buffer based on ATR (V10.4)
        if atr_buffer_multiplier > 0 and current_atr:
            stop_buffer = current_atr * atr_buffer_multiplier
        else:
            stop_buffer = default_buffer

        # Track swings for BOS detection
        if i >= 4:
            check_idx = i - 2
            if is_swing_high(session_bars, check_idx, 2):
                recent_swing_high = {'price': session_bars[check_idx].high, 'idx': check_idx}
            if is_swing_low(session_bars, check_idx, 2):
                recent_swing_low = {'price': session_bars[check_idx].low, 'idx': check_idx}

        # Skip entry detection before RTH
        if bar_time < rth_start:
            continue

        # Type A: Creation Entry - check for newly formed FVGs
        for fvg in session_fvgs:
            if fvg['used_for_entry']:
                continue
            # Check if this FVG was just created (within last 2 bars)
            if abs(fvg['creation_bar_idx'] - i) > 2:
                continue

            direction = fvg['direction']

            # Displacement check (needed before ADX for override logic)
            body = 0
            avg_body = 0
            if i >= 1:
                prev_bar = session_bars[i-1]
                body = abs(prev_bar.close - prev_bar.open)
                avg_body = sum(abs(b.close - b.open) for b in session_bars[max(0,i-10):i]) / min(10, i) if i > 0 else body
                if body < avg_body * 1.0:
                    continue

            # V10.5: Skip ADX check if displacement >= 3x average body (high momentum override)
            # But still require ADX >= 10 as a safety floor
            high_disp = high_displacement_override > 0 and avg_body > 0 and body >= avg_body * high_displacement_override

            # Trend filter
            if not high_disp and (adx is None or adx < 17):
                continue
            if high_disp and (adx is None or adx < 10):
                continue  # Safety floor for high displacement
            if htf_bias and htf_bias != direction:
                continue

            # DI filter
            if plus_di and minus_di:
                if direction == 'LONG' and plus_di < minus_di:
                    continue
                if direction == 'SHORT' and minus_di < plus_di:
                    continue

            entry_price = (fvg['low'] + fvg['high']) / 2
            if direction == 'LONG':
                stop_price = fvg['low'] - stop_buffer  # ATR-based buffer (V10.4)
            else:
                stop_price = fvg['high'] + stop_buffer

            risk = abs(entry_price - stop_price)
            if risk < min_risk:
                continue

            # V10.2 time filters
            entry_hour = bar.timestamp.hour
            if midday_cutoff and 12 <= entry_hour < 14:
                continue  # Skip lunch lull (12:00-14:00)
            if pm_cutoff_qqq and symbol == 'QQQ' and entry_hour >= 14:
                continue  # Skip QQQ afternoon entries

            fvg['used_for_entry'] = True
            all_valid_entries.append({
                'entry_type': 'CREATION',
                'direction': direction,
                'entry_bar_idx': i,
                'entry_time': bar.timestamp,
                'entry_price': entry_price,
                'stop_price': stop_price,
                'fvg_low': fvg['low'],
                'fvg_high': fvg['high'],
                'risk': risk,
                'stop_buffer': stop_buffer,
                'atr': current_atr,
            })

        # Type B1: Overnight FVG Retracement
        for fvg in overnight_fvgs:
            if fvg['used_for_entry']:
                continue

            direction = fvg['direction']
            fvg_mid = (fvg['low'] + fvg['high']) / 2

            # Morning filter
            if bar_time > morning_end:
                continue

            # ADX filter for overnight retrace
            if overnight_retrace_min_adx > 0:
                if adx is None or adx < overnight_retrace_min_adx:
                    continue

            # Check for retracement into FVG
            in_fvg = False
            if direction == 'LONG' and bar.low <= fvg['high'] and bar.close > fvg['low']:
                in_fvg = True
            elif direction == 'SHORT' and bar.high >= fvg['low'] and bar.close < fvg['high']:
                in_fvg = True

            if not in_fvg:
                continue

            # Check for rejection
            body = abs(bar.close - bar.open)
            wick = bar.high - max(bar.close, bar.open) if direction == 'SHORT' else min(bar.close, bar.open) - bar.low
            if wick <= body:
                continue

            entry_price = fvg_mid
            if direction == 'LONG':
                stop_price = bar.low - stop_buffer  # ATR-based buffer (V10.4)
            else:
                stop_price = bar.high + stop_buffer

            risk = abs(entry_price - stop_price)
            if risk < min_risk:
                continue

            # V10.2 time filters
            entry_hour = bar.timestamp.hour
            if midday_cutoff and 12 <= entry_hour < 14:
                continue  # Skip lunch lull (12:00-14:00)
            if pm_cutoff_qqq and symbol == 'QQQ' and entry_hour >= 14:
                continue  # Skip QQQ afternoon entries

            fvg['used_for_entry'] = True
            all_valid_entries.append({
                'entry_type': 'RETRACEMENT',
                'direction': direction,
                'entry_bar_idx': i,
                'entry_time': bar.timestamp,
                'entry_price': entry_price,
                'stop_price': stop_price,
                'fvg_low': fvg['low'],
                'fvg_high': fvg['high'],
                'risk': risk,
                'stop_buffer': stop_buffer,
                'atr': current_atr,
            })

        # Type B2: Intraday FVG Retracement
        # V10.3: Skip INTRADAY for SPY (24% win rate - consistent loser)
        if not (disable_intraday_spy and symbol == 'SPY'):
            for fvg in session_fvgs:
                if fvg['used_for_entry']:
                    continue
                if i - fvg['creation_bar_idx'] < 5:
                    continue

                direction = fvg['direction']
                fvg_mid = (fvg['low'] + fvg['high']) / 2

                # Trend filter (HTF bias)
                if htf_bias and htf_bias != direction:
                    continue

                # DI filter (was missing - caused QQQ losses)
                if plus_di and minus_di:
                    if direction == 'LONG' and plus_di < minus_di:
                        continue
                    if direction == 'SHORT' and minus_di < plus_di:
                        continue

                # Check for retracement
                in_fvg = False
                if direction == 'LONG' and bar.low <= fvg['high'] and bar.close > fvg['low']:
                    in_fvg = True
                elif direction == 'SHORT' and bar.high >= fvg['low'] and bar.close < fvg['high']:
                    in_fvg = True

                if not in_fvg:
                    continue

                # Check for rejection
                body = abs(bar.close - bar.open)
                wick = bar.high - max(bar.close, bar.open) if direction == 'SHORT' else min(bar.close, bar.open) - bar.low
                if wick <= body:
                    continue

                entry_price = fvg_mid
                if direction == 'LONG':
                    stop_price = bar.low - stop_buffer  # ATR-based buffer (V10.4)
                else:
                    stop_price = bar.high + stop_buffer

                risk = abs(entry_price - stop_price)
                if risk < min_risk:
                    continue

                # V10.2 time filters
                entry_hour = bar.timestamp.hour
                if midday_cutoff and 12 <= entry_hour < 14:
                    continue  # Skip lunch lull (12:00-14:00)
                if pm_cutoff_qqq and symbol == 'QQQ' and entry_hour >= 14:
                    continue  # Skip QQQ afternoon entries

                fvg['used_for_entry'] = True
                all_valid_entries.append({
                    'entry_type': 'INTRADAY',
                    'direction': direction,
                    'entry_bar_idx': i,
                    'entry_time': bar.timestamp,
                    'entry_price': entry_price,
                    'stop_price': stop_price,
                    'fvg_low': fvg['low'],
                    'fvg_high': fvg['high'],
                    'risk': risk,
                    'stop_buffer': stop_buffer,
                    'atr': current_atr,
                })

        # Type C: BOS + Retracement (check for BOS)
        if recent_swing_high and bar.high > recent_swing_high['price']:
            # Bullish BOS - look for LONG FVGs
            for fvg in session_fvgs:
                if fvg['used_for_entry']:
                    continue
                if fvg['direction'] != 'LONG':
                    continue
                if fvg['creation_bar_idx'] < recent_swing_high['idx']:
                    continue
                if i - fvg['creation_bar_idx'] > 5:
                    continue

                entry_price = (fvg['low'] + fvg['high']) / 2
                stop_price = fvg['low'] - stop_buffer  # ATR-based buffer (V10.4)
                risk = abs(entry_price - stop_price)

                if risk < min_risk:
                    continue

                # V10.2 time filters
                entry_hour = bar.timestamp.hour
                if midday_cutoff and 12 <= entry_hour < 14:
                    continue  # Skip lunch lull (12:00-14:00)
                if pm_cutoff_qqq and symbol == 'QQQ' and entry_hour >= 14:
                    continue  # Skip QQQ afternoon entries

                fvg['used_for_entry'] = True
                all_valid_entries.append({
                    'entry_type': 'BOS',
                    'direction': 'LONG',
                    'entry_bar_idx': i,
                    'entry_time': bar.timestamp,
                    'entry_price': entry_price,
                    'stop_price': stop_price,
                    'fvg_low': fvg['low'],
                    'fvg_high': fvg['high'],
                    'risk': risk,
                    'stop_buffer': stop_buffer,
                    'atr': current_atr,
                })

            recent_swing_high = None

        if recent_swing_low and bar.low < recent_swing_low['price']:
            # Bearish BOS - look for SHORT FVGs
            for fvg in session_fvgs:
                if fvg['used_for_entry']:
                    continue
                if fvg['direction'] != 'SHORT':
                    continue
                if fvg['creation_bar_idx'] < recent_swing_low['idx']:
                    continue
                if i - fvg['creation_bar_idx'] > 5:
                    continue

                entry_price = (fvg['low'] + fvg['high']) / 2
                stop_price = fvg['high'] + stop_buffer  # ATR-based buffer (V10.4)
                risk = abs(entry_price - stop_price)

                if risk < min_risk:
                    continue

                # V10.2 time filters
                entry_hour = bar.timestamp.hour
                if midday_cutoff and 12 <= entry_hour < 14:
                    continue  # Skip lunch lull (12:00-14:00)
                if pm_cutoff_qqq and symbol == 'QQQ' and entry_hour >= 14:
                    continue  # Skip QQQ afternoon entries

                fvg['used_for_entry'] = True
                all_valid_entries.append({
                    'entry_type': 'BOS',
                    'direction': 'SHORT',
                    'entry_bar_idx': i,
                    'entry_time': bar.timestamp,
                    'entry_price': entry_price,
                    'stop_price': stop_price,
                    'fvg_low': fvg['low'],
                    'fvg_high': fvg['high'],
                    'risk': risk,
                    'stop_buffer': stop_buffer,
                    'atr': current_atr,
                })

            recent_swing_low = None

    # Trade management phase
    active_trades = []
    completed_results = []
    entries_taken = {'LONG': 0, 'SHORT': 0}
    loss_count = 0
    max_losses = 2

    # Contract allocation (same ratios as futures)
    # For equities, we use position ratios: 33% T1, 33% T2, 33% Runner
    t1_ratio = 0.33
    t2_ratio = 0.33
    runner_ratio = 0.34

    for i, bar in enumerate(session_bars):
        trades_to_remove = []

        for trade in active_trades:
            is_long = trade['direction'] == 'LONG'
            remaining = trade['remaining_shares']

            # Update trailing stops after 4R
            if trade['touched_4r'] and not trade['touched_8r']:
                check_idx = i - 2
                if check_idx > trade['entry_bar_idx']:
                    if is_long and is_swing_low(session_bars, check_idx, 2):
                        swing = session_bars[check_idx].low
                        if swing > trade['t1_last_swing']:
                            new_trail = swing - 0.02
                            if new_trail > trade['t1_trail_stop']:
                                trade['t1_trail_stop'] = new_trail
                                trade['t1_last_swing'] = swing
                    elif not is_long and is_swing_high(session_bars, check_idx, 2):
                        swing = session_bars[check_idx].high
                        if swing < trade['t1_last_swing']:
                            new_trail = swing + 0.02
                            if new_trail < trade['t1_trail_stop']:
                                trade['t1_trail_stop'] = new_trail
                                trade['t1_last_swing'] = swing

            # Update T2 trail after 8R
            if trade['touched_8r'] and trade['t1_exited'] and not trade['t2_exited']:
                check_idx = i - 2
                if check_idx > trade['entry_bar_idx']:
                    if is_long and is_swing_low(session_bars, check_idx, 2):
                        swing = session_bars[check_idx].low
                        if swing > trade['t2_last_swing']:
                            new_trail = swing - 0.04
                            if new_trail > trade['t2_trail_stop']:
                                trade['t2_trail_stop'] = new_trail
                                trade['t2_last_swing'] = swing
                    elif not is_long and is_swing_high(session_bars, check_idx, 2):
                        swing = session_bars[check_idx].high
                        if swing < trade['t2_last_swing']:
                            new_trail = swing + 0.04
                            if new_trail < trade['t2_trail_stop']:
                                trade['t2_trail_stop'] = new_trail
                                trade['t2_last_swing'] = swing

            # Update Runner trail after 8R
            if trade['touched_8r'] and trade['t1_exited'] and trade['t2_exited']:
                check_idx = i - 2
                if check_idx > trade['entry_bar_idx']:
                    if is_long and is_swing_low(session_bars, check_idx, 2):
                        swing = session_bars[check_idx].low
                        if swing > trade.get('runner_last_swing', trade['entry_price']):
                            new_trail = swing - 0.06
                            if new_trail > trade['runner_stop']:
                                trade['runner_stop'] = new_trail
                                trade['runner_last_swing'] = swing
                    elif not is_long and is_swing_high(session_bars, check_idx, 2):
                        swing = session_bars[check_idx].high
                        if swing < trade.get('runner_last_swing', trade['entry_price']):
                            new_trail = swing + 0.06
                            if new_trail < trade['runner_stop']:
                                trade['runner_stop'] = new_trail
                                trade['runner_last_swing'] = swing

            # Check 4R touch
            if not trade['touched_4r']:
                t4r_hit = bar.high >= trade['target_4r'] if is_long else bar.low <= trade['target_4r']
                if t4r_hit:
                    trade['touched_4r'] = True
                    trade['t1_trail_stop'] = trade['entry_price']
                    trade['t1_last_swing'] = trade['entry_price']

                    # HYBRID: Take T1 profit at 4R immediately
                    if t1_fixed_4r and not trade['t1_exited'] and remaining > 0:
                        exit_shares = trade['t1_shares']
                        pnl = (trade['target_4r'] - trade['entry_price']) * exit_shares if is_long else (trade['entry_price'] - trade['target_4r']) * exit_shares
                        trade['exits'].append({'type': '4R_PARTIAL', 'pnl': pnl, 'price': trade['target_4r'], 'time': bar.timestamp, 'shares': exit_shares})
                        trade['remaining_shares'] -= exit_shares
                        trade['t1_exited'] = True
                        remaining = trade['remaining_shares']

            # Check 8R touch
            if trade['touched_4r'] and not trade['touched_8r']:
                t8r_hit = bar.high >= trade['target_8r'] if is_long else bar.low <= trade['target_8r']
                if t8r_hit:
                    trade['touched_8r'] = True
                    trade['t2_trail_stop'] = trade['plus_4r']
                    trade['t2_last_swing'] = bar.high if is_long else bar.low
                    trade['runner_stop'] = trade['plus_4r']
                    trade['runner_last_swing'] = bar.high if is_long else bar.low

            # Check stops
            if not trade['touched_4r'] and remaining > 0:
                stop_hit = bar.low <= trade['stop_price'] if is_long else bar.high >= trade['stop_price']
                if stop_hit:
                    pnl = (trade['stop_price'] - trade['entry_price']) * remaining if is_long else (trade['entry_price'] - trade['stop_price']) * remaining
                    trade['exits'].append({'type': 'STOP', 'pnl': pnl, 'price': trade['stop_price'], 'time': bar.timestamp, 'shares': remaining})
                    trade['remaining_shares'] = 0
                    loss_count += 1
                    remaining = 0

            # After 4R but before 8R
            if trade['touched_4r'] and not trade['touched_8r'] and remaining > 0:
                t1_stop_hit = bar.low <= trade['t1_trail_stop'] if is_long else bar.high >= trade['t1_trail_stop']
                if t1_stop_hit:
                    pnl = (trade['t1_trail_stop'] - trade['entry_price']) * remaining if is_long else (trade['entry_price'] - trade['t1_trail_stop']) * remaining
                    trade['exits'].append({'type': 'TRAIL_STOP', 'pnl': pnl, 'price': trade['t1_trail_stop'], 'time': bar.timestamp, 'shares': remaining})
                    trade['t1_exited'] = True
                    trade['t2_exited'] = True
                    trade['remaining_shares'] = 0
                    remaining = 0

            # After 8R - T2 exit
            if trade['touched_8r'] and remaining > 0:
                if not trade['t2_exited'] and remaining > trade['runner_shares']:
                    t2_stop_hit = bar.low <= trade['t2_trail_stop'] if is_long else bar.high >= trade['t2_trail_stop']
                    if t2_stop_hit:
                        exit_shares = trade['t2_shares']
                        pnl = (trade['t2_trail_stop'] - trade['entry_price']) * exit_shares if is_long else (trade['entry_price'] - trade['t2_trail_stop']) * exit_shares
                        trade['exits'].append({'type': 'T2_STRUCT', 'pnl': pnl, 'price': trade['t2_trail_stop'], 'time': bar.timestamp, 'shares': exit_shares})
                        trade['remaining_shares'] -= exit_shares
                        trade['t2_exited'] = True
                        remaining = trade['remaining_shares']

                # Runner exit
                if trade['t1_exited'] and trade['t2_exited'] and remaining > 0:
                    runner_stop_hit = bar.low <= trade['runner_stop'] if is_long else bar.high >= trade['runner_stop']
                    if runner_stop_hit:
                        pnl = (trade['runner_stop'] - trade['entry_price']) * remaining if is_long else (trade['entry_price'] - trade['runner_stop']) * remaining
                        trade['exits'].append({'type': 'RUNNER_STOP', 'pnl': pnl, 'price': trade['runner_stop'], 'time': bar.timestamp, 'shares': remaining})
                        trade['remaining_shares'] = 0
                        remaining = 0

            if trade['remaining_shares'] <= 0:
                trades_to_remove.append(trade)

        for trade in trades_to_remove:
            if trade in active_trades:
                active_trades.remove(trade)
                completed_results.append(trade)

        # Check for new entries
        if loss_count >= max_losses:
            continue

        current_open = len(active_trades)

        for entry in all_valid_entries:
            if entry['entry_bar_idx'] != i:
                continue

            direction = entry['direction']

            if current_open >= max_open_trades:
                continue

            if entries_taken[direction] >= 2:
                continue

            is_long = direction == 'LONG'
            entry_price = entry['entry_price']
            stop_price = entry['stop_price']
            risk = abs(entry_price - stop_price)

            # Calculate position size based on risk
            total_shares = int(risk_per_trade / risk)
            if total_shares < 3:
                total_shares = 3  # Minimum for T1/T2/Runner split

            t1_shares = max(1, int(total_shares * t1_ratio))
            t2_shares = max(1, int(total_shares * t2_ratio))
            runner_shares = total_shares - t1_shares - t2_shares

            target_4r = entry_price + (4 * risk) if is_long else entry_price - (4 * risk)
            target_8r = entry_price + (8 * risk) if is_long else entry_price - (8 * risk)
            plus_4r = target_4r

            new_trade = {
                'direction': direction,
                'entry_type': entry['entry_type'],
                'entry_bar_idx': i,
                'entry_time': entry['entry_time'],
                'entry_price': entry_price,
                'stop_price': stop_price,
                'fvg_low': entry['fvg_low'],
                'fvg_high': entry['fvg_high'],
                'risk': risk,
                'target_4r': target_4r,
                'target_8r': target_8r,
                'plus_4r': plus_4r,
                'touched_4r': False,
                'touched_8r': False,
                't1_trail_stop': stop_price,
                't1_last_swing': entry_price,
                't1_exited': False,
                't2_trail_stop': plus_4r,
                't2_last_swing': entry_price,
                't2_exited': False,
                'runner_stop': plus_4r,
                'runner_last_swing': entry_price,
                'total_shares': total_shares,
                't1_shares': t1_shares,
                't2_shares': t2_shares,
                'runner_shares': runner_shares,
                'remaining_shares': total_shares,
                'is_2nd_entry': entries_taken[direction] > 0,
                'exits': [],
                'stop_buffer': entry.get('stop_buffer'),
                'atr': entry.get('atr'),
            }

            active_trades.append(new_trade)
            entries_taken[direction] += 1
            current_open += 1

    # EOD exit
    last_bar = session_bars[-1]
    for trade in active_trades:
        if trade['remaining_shares'] > 0:
            is_long = trade['direction'] == 'LONG'
            pnl = (last_bar.close - trade['entry_price']) * trade['remaining_shares'] if is_long else (trade['entry_price'] - last_bar.close) * trade['remaining_shares']
            trade['exits'].append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'shares': trade['remaining_shares']})
            trade['remaining_shares'] = 0
        completed_results.append(trade)

    # Build results
    final_results = []
    for trade in completed_results:
        if not trade.get('exits'):
            continue

        total_pnl = sum(e['pnl'] for e in trade['exits'])

        exit_types = [e['type'] for e in trade['exits']]
        if 'STOP' in exit_types:
            result = 'LOSS'
        elif 'RUNNER_STOP' in exit_types or 'EOD' in exit_types:
            result = 'WIN' if total_pnl > 0 else 'LOSS'
        else:
            result = 'WIN' if total_pnl > 0 else 'LOSS'

        final_results.append({
            'direction': trade['direction'],
            'entry_type': trade['entry_type'],
            'entry_time': trade['entry_time'],
            'entry_price': trade['entry_price'],
            'stop_price': trade['stop_price'],
            'fvg_low': trade['fvg_low'],
            'fvg_high': trade['fvg_high'],
            'risk': trade['risk'],
            'total_shares': trade['total_shares'],
            'total_pnl': total_pnl,
            'total_dollars': total_pnl,  # For equities, pnl IS dollars
            'exits': trade['exits'],
            'result': result,
            'is_2nd_entry': trade['is_2nd_entry'],
            'stop_buffer': trade.get('stop_buffer'),
            'atr': trade.get('atr'),
        })

    return final_results


def run_today_v10_equity(symbol='SPY', risk_per_trade=500, n_bars=3000):
    """Run V10 strategy on equity for today."""
    print(f"Fetching {symbol} data...")
    bars = fetch_futures_bars(symbol, interval='3m', n_bars=n_bars)

    if not bars:
        print(f"No data available for {symbol}")
        return

    today = date.today()
    day_bars = [b for b in bars if b.timestamp.date() == today]

    if not day_bars:
        # Try yesterday
        yesterday = today - timedelta(days=1)
        day_bars = [b for b in bars if b.timestamp.date() == yesterday]
        if day_bars:
            today = yesterday

    if not day_bars:
        print(f"No bars for {today}")
        return

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

    print(f"\n{'='*70}")
    print(f"V10 EQUITY - {symbol} - {today}")
    print(f"{'='*70}")
    print(f"Session bars: {len(session_bars)}")
    print(f"Risk per trade: ${risk_per_trade}")

    config = EQUITY_CONFIG.get(symbol.upper(), EQUITY_CONFIG['SPY'])
    print(f"Min FVG: ${config['min_fvg_points']:.2f}")
    print(f"Min Risk: ${config['min_risk_points']:.2f}")
    print(f"Stop Buffer: ATR x 0.5 (V10.4)")

    results = run_session_v10_equity(
        session_bars,
        bars,
        symbol=symbol,
        risk_per_trade=risk_per_trade,
        max_open_trades=2,
        t1_fixed_4r=True,
        overnight_retrace_min_adx=22,
    )

    if not results:
        print("\nNo trades generated")
        return

    print(f"\n{'='*70}")
    print(f"TRADES ({len(results)})")
    print(f"{'='*70}")

    total_pnl = 0
    wins = 0
    losses = 0

    for r in results:
        result_str = 'WIN' if r['total_dollars'] > 0 else 'LOSS'
        entry_tag = '2nd' if r['is_2nd_entry'] else '1st'
        print(f"\n{r['direction']} ({r['entry_type']}) @ {r['entry_time'].strftime('%H:%M')} [{entry_tag}]")
        buffer_str = f"${r['stop_buffer']:.3f}" if r.get('stop_buffer') else "$0.02"
        atr_str = f"ATR=${r['atr']:.3f}" if r.get('atr') else ""
        print(f"  Entry: ${r['entry_price']:.2f} | Stop: ${r['stop_price']:.2f} | Risk: ${r['risk']:.2f} | Buffer: {buffer_str} {atr_str}")
        print(f"  Shares: {r['total_shares']}")
        exit_str = [f"{e['type']}@${e['price']:.2f}" for e in r['exits']]
        print(f"  Exits: {exit_str}")
        print(f"  P/L: ${r['total_dollars']:+,.2f} ({result_str})")

        total_pnl += r['total_dollars']
        if r['total_dollars'] > 0:
            wins += 1
        else:
            losses += 1

    print(f"\n{'='*70}")
    print(f"SUMMARY - {symbol}")
    print(f"{'='*70}")
    print(f"Trades: {len(results)} ({wins} wins, {losses} losses)")
    if results:
        print(f"Win Rate: {wins/len(results)*100:.1f}%")
    print(f"Total P/L: ${total_pnl:+,.2f}")

    return results


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'SPY'
    risk = int(sys.argv[2]) if len(sys.argv) > 2 else 500

    run_today_v10_equity(symbol, risk)
