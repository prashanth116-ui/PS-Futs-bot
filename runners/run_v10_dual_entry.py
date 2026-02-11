"""
V10.8 Quad Entry Mode - FVG Creation + Retracement + Smart BOS

ENTRY TYPES:
============
Entry Type A: FVG Creation
- Enter immediately when FVG forms with displacement
- Aggressive entry, catches momentum moves

Entry Type B1: Overnight FVG Retracement + Rejection
- Track FVGs from overnight/premarket (before 9:30)
- Enter when price wicks INTO FVG zone and rejects
- ADX >= 22 required for overnight retrace

Entry Type B2: Intraday FVG Retracement + Rejection
- Track FVGs created during RTH session
- Enter when price retraces into FVG (min 2 bars after creation)

Entry Type C: BOS + Session FVG Retracement
- Per-symbol control + daily loss limit
- ES: Disabled (20% win rate)
- NQ/SPY/QQQ: Enabled with LOSS_LIMIT (stop after 1 BOS loss/day)

HYBRID FILTER SYSTEM (V10.8):
=============================
MANDATORY (must pass):
  1. DI Direction (+DI > -DI for LONG, -DI > +DI for SHORT)
  2. FVG Size >= 5 ticks

OPTIONAL (2 of 3 must pass):
  3. Displacement >= 1.0x avg body
  4. ADX >= 11
  5. EMA20 vs EMA50 trend alignment

EXIT STRUCTURE (HYBRID + DYNAMIC SIZING):
=========================================
1st trade: 3 contracts (T1=1, T2=1, Runner=1)
2nd+ trades: 2 contracts (T1=1, T2=1, no runner)
T1: FIXED profit at 4R
T2/Runner: Structure trail with 4-6 tick buffer after 8R

VERSION HISTORY:
================
V10.8: Hybrid filter system (2 mandatory + 2/3 optional) - +$90k/30d improvement
V10.7: Dynamic sizing (3->2 cts), ADX>=11, 3 trades/dir, FVG age 2 bars
V10.6: BOS LOSS_LIMIT (stop after 1 loss/day), ES BOS disabled
V10.5: High displacement override (3x body skips ADX >= 17)
V10.4: BOS risk cap (ES: 8pts, NQ: 20pts)
V10.3: Midday cutoff, PM cutoff for NQ
"""
import sys
sys.path.insert(0, '.')

from datetime import date, time as dt_time
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict.signals.fvg import detect_fvgs, update_fvg_mitigation


# EST timezone for time-based filters
EST = ZoneInfo('America/New_York')


def get_est_hour(timestamp):
    """Get hour in EST timezone from a timestamp.

    Handles both naive (assumed EST) and aware datetimes.
    """
    if timestamp.tzinfo is None:
        # Naive datetime - assume it's already EST (TradingView convention for CME futures)
        return timestamp.hour
    else:
        # Aware datetime - convert to EST
        return timestamp.astimezone(EST).hour


def calculate_ema(bars, period):
    """Calculate EMA for the given bars."""
    if len(bars) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(b.close for b in bars[:period]) / period
    for bar in bars[period:]:
        ema = (bar.close - ema) * multiplier + ema
    return ema


def calculate_adx(bars, period=14):
    """Calculate ADX and DI values."""
    if len(bars) < period * 2:
        return None, None, None

    tr_list = []
    plus_dm_list = []
    minus_dm_list = []

    for i in range(1, len(bars)):
        high = bars[i].high
        low = bars[i].low
        close_prev = bars[i-1].close
        high_prev = bars[i-1].high
        low_prev = bars[i-1].low

        tr = max(high - low, abs(high - close_prev), abs(low - close_prev))
        tr_list.append(tr)

        up_move = high - high_prev
        down_move = low_prev - low

        plus_dm = up_move if up_move > down_move and up_move > 0 else 0
        minus_dm = down_move if down_move > up_move and down_move > 0 else 0

        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)

    if len(tr_list) < period:
        return None, None, None

    def wilder_smooth(data, period):
        smoothed = [sum(data[:period])]
        for i in range(period, len(data)):
            smoothed.append(smoothed[-1] - (smoothed[-1] / period) + data[i])
        return smoothed

    atr = wilder_smooth(tr_list, period)
    plus_dm_smooth = wilder_smooth(plus_dm_list, period)
    minus_dm_smooth = wilder_smooth(minus_dm_list, period)

    dx_list = []
    plus_di = 0
    minus_di = 0
    for i in range(len(atr)):
        if atr[i] == 0:
            continue
        plus_di = 100 * plus_dm_smooth[i] / atr[i]
        minus_di = 100 * minus_dm_smooth[i] / atr[i]

        di_sum = plus_di + minus_di
        if di_sum == 0:
            continue
        dx = 100 * abs(plus_di - minus_di) / di_sum
        dx_list.append(dx)

    if len(dx_list) < period:
        return None, None, None

    adx = sum(dx_list[-period:]) / period
    return adx, plus_di, minus_di


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


def find_recent_swing_high(bars, end_idx, lookback=10, swing_lookback=2):
    """Find most recent confirmed swing high before end_idx."""
    for i in range(end_idx - swing_lookback - 1, max(0, end_idx - lookback), -1):
        if is_swing_high(bars, i, swing_lookback):
            return i, bars[i].high
    return None, None


def find_recent_swing_low(bars, end_idx, lookback=10, swing_lookback=2):
    """Find most recent confirmed swing low before end_idx."""
    for i in range(end_idx - swing_lookback - 1, max(0, end_idx - lookback), -1):
        if is_swing_low(bars, i, swing_lookback):
            return i, bars[i].low
    return None, None


def detect_bos(bars, idx, lookback=10):
    """Detect Break of Structure at bar index.

    Returns:
        ('BULLISH', swing_low_price) if price broke above recent swing high
        ('BEARISH', swing_high_price) if price broke below recent swing low
        (None, None) if no BOS
    """
    if idx < lookback:
        return None, None

    bar = bars[idx]

    # Check for bullish BOS (broke above swing high)
    sh_idx, sh_price = find_recent_swing_high(bars, idx, lookback)
    if sh_idx is not None and bar.close > sh_price:
        return 'BULLISH', sh_price

    # Check for bearish BOS (broke below swing low)
    sl_idx, sl_price = find_recent_swing_low(bars, idx, lookback)
    if sl_idx is not None and bar.close < sl_price:
        return 'BEARISH', sl_price

    return None, None


def is_rejection_candle(bar, fvg, direction, tick_size=0.25, proximity_ticks=4):
    """Check if bar shows rejection from FVG zone.

    Rejection criteria:
    - Price wicks INTO or NEAR the FVG zone (within proximity_ticks)
    - Wick into FVG > body size (shows rejection)
    - Close is outside or at edge of FVG

    Args:
        bar: Current bar
        fvg: FVG zone being tested
        direction: Expected trade direction if rejection confirms
        tick_size: Instrument tick size
        proximity_ticks: Allow wick within this many ticks of FVG

    Returns:
        (is_rejection, entry_price, stop_price) or (False, None, None)
    """
    body = abs(bar.close - bar.open)
    proximity = proximity_ticks * tick_size

    if direction == 'LONG':
        # For LONG: price wicks DOWN into/near bullish FVG and rejects UP
        wick_into_fvg = bar.low <= fvg.high and bar.low >= fvg.low
        wick_through_fvg = bar.low < fvg.low
        wick_near_fvg = bar.low <= fvg.high + proximity and bar.low >= fvg.low - proximity

        if not wick_into_fvg and not wick_through_fvg and not wick_near_fvg:
            return False, None, None

        # Calculate wick size
        wick_bottom = min(bar.open, bar.close)
        wick_size = wick_bottom - bar.low

        # Rejection: wick >= body * 0.85 (relaxed from wick > body to catch more setups)
        if wick_size < body * 0.85:
            return False, None, None

        # Close should be above FVG high (strong rejection)
        if bar.close < fvg.high:
            return False, None, None

        # Entry at rejection candle close (enter after confirmation)
        entry_price = bar.close

        # Stop: below rejection wick + buffer
        stop_price = bar.low - (2 * tick_size)

        return True, entry_price, stop_price

    else:  # SHORT
        # For SHORT: price wicks UP into/near bearish FVG and rejects DOWN
        wick_into_fvg = bar.high >= fvg.low and bar.high <= fvg.high
        wick_through_fvg = bar.high > fvg.high
        wick_near_fvg = bar.high >= fvg.low - proximity and bar.high <= fvg.high + proximity

        if not wick_into_fvg and not wick_through_fvg and not wick_near_fvg:
            return False, None, None

        # Calculate wick size
        wick_top = max(bar.open, bar.close)
        wick_size = bar.high - wick_top

        # Rejection: wick >= body * 0.85 (relaxed from wick > body to catch more setups)
        if wick_size < body * 0.85:
            return False, None, None

        # Close should show rejection - close below the wick top (bearish close)
        # For wick_into/through: close should be below FVG
        # For wick_near: close should be below the open (bearish candle)
        if wick_into_fvg or wick_through_fvg:
            if bar.close > fvg.low:
                return False, None, None
        else:  # wick_near
            if bar.close >= bar.open:  # Not a bearish candle
                return False, None, None

        # Entry at rejection candle close (enter after confirmation)
        entry_price = bar.close

        # Stop: above rejection wick + buffer
        stop_price = bar.high + (2 * tick_size)

        return True, entry_price, stop_price


def run_session_v10(
    session_bars,
    all_bars,  # Include overnight bars for FVG tracking
    tick_size=0.25,
    tick_value=12.50,
    contracts=3,
    max_open_trades=3,  # V10.7: Increased from 2 to allow 3rd entry
    max_losses_per_day=2,
    displacement_threshold=1.0,
    min_adx=11,  # V10.7: Lowered from 17 to catch earlier setups
    min_risk_pts=0,
    use_opposing_fvg_exit=False,
    # V10 specific
    enable_creation_entry=True,   # Entry Type A
    enable_retracement_entry=True,  # Entry Type B
    enable_bos_entry=True,  # Entry Type C: BOS + Session FVG Retracement
    # V10 filters
    retracement_morning_only=False,  # Only take retracement entries 9:30-12:00
    retracement_trend_aligned=False,  # Only take retracement entries matching daily trend
    overnight_retrace_min_adx=22,  # Min ADX for overnight retrace entries (0 to disable)
    bos_lookback=10,  # Bars to look back for swing points
    bos_fvg_window=5,  # Bars after BOS to look for FVG
    # V10.2 time filters
    midday_cutoff=True,  # No entries 12:00-14:00 (lunch lull)
    pm_cutoff_nq=True,   # No NQ entries after 14:00
    symbol='ES',         # Symbol for PM cutoff logic
    # V10.4 risk caps for BOS entries
    max_bos_risk_pts=None,  # Max risk for BOS entries (ES: 8, NQ: 20)
    # V10.5 high displacement override
    high_displacement_override=3.0,  # Skip ADX check if displacement >= 3x avg body
    # V10.6 BOS controls
    disable_bos_retrace=False,  # Disable BOS entries entirely (use for ES)
    bos_daily_loss_limit=1,  # Stop BOS after N losses per day (0=no limit)
    # Exit options
    t1_fixed_4r=False,  # Hybrid: Take T1 profit at 4R instead of trailing
    # V10.8 Hybrid filters
    use_hybrid_filters=True,  # Use 2 mandatory + 2/3 optional filter mode
):
    """V10: Quad entry mode with FVG creation + retracement + BOS.

    Entry Type A (Creation): Enter when FVG forms (existing V9 logic)
    Entry Type B1 (Overnight Retrace): Enter when price wicks into overnight FVG and rejects
    Entry Type B2 (Intraday Retrace): Enter when price wicks into session FVG and rejects
    Entry Type C (BOS): Enter when price retraces into session FVG after BOS
    """

    # Calculate average body size from session bars (today only, like V9)
    body_sizes = [abs(b.close - b.open) for b in session_bars[:50]]
    avg_body_size = sum(body_sizes) / len(body_sizes) if body_sizes else tick_size * 4

    fvg_config = {
        'min_fvg_ticks': 2,  # Lower threshold to catch smaller overnight FVGs
        'tick_size': tick_size,
        'max_fvg_age_bars': 200,  # Extended for overnight FVGs
        'invalidate_on_close_through': True
    }

    # Detect FVGs from ALL bars (including overnight)
    all_fvgs = detect_fvgs(all_bars, fvg_config)

    # Update FVG mitigation status for all detected FVGs
    # This fixes the bug where mitigated FVGs were still being used for entries
    for fvg in all_fvgs:
        if fvg.mitigated:
            continue
        # Check all bars after FVG creation for mitigation
        for bar_idx in range(fvg.created_bar_index + 1, len(all_bars)):
            update_fvg_mitigation(fvg, all_bars[bar_idx], bar_idx, fvg_config)
            if fvg.mitigated:
                break  # Stop once mitigated

    # Create mappings between session_bars and all_bars indices
    session_to_all_idx = {}
    all_to_session_idx = {}
    for i, sbar in enumerate(session_bars):
        for j, abar in enumerate(all_bars):
            if abar.timestamp == sbar.timestamp:
                session_to_all_idx[i] = j
                all_to_session_idx[j] = i
                break

    # Track valid entries for each type
    valid_entries = {'LONG': [], 'SHORT': []}

    # === Entry Type A: FVG Creation ===
    if enable_creation_entry:
        for direction in ['LONG', 'SHORT']:
            is_long = direction == 'LONG'
            fvg_dir = 'BULLISH' if is_long else 'BEARISH'

            for fvg in all_fvgs:
                if fvg.direction != fvg_dir:
                    continue

                # Only consider FVGs created during session
                session_bar_idx = all_to_session_idx.get(fvg.created_bar_index)
                if session_bar_idx is None:
                    continue

                # Min FVG size filter for creation entries (5 ticks) - MANDATORY
                fvg_size_ticks = (fvg.high - fvg.low) / tick_size
                if fvg_size_ticks < 5:
                    continue

                creating_bar = all_bars[fvg.created_bar_index]
                body = abs(creating_bar.close - creating_bar.open)

                bars_to_entry = all_bars[:fvg.created_bar_index + 1]
                ema_fast = calculate_ema(bars_to_entry, 20)
                ema_slow = calculate_ema(bars_to_entry, 50)
                adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)

                # V10.8 HYBRID FILTER SYSTEM
                # MANDATORY: DI Direction (must pass)
                di_ok = adx is None or (plus_di > minus_di if is_long else minus_di > plus_di)
                if not di_ok:
                    continue

                # OPTIONAL filters (2/3 must pass)
                disp_ok = body > avg_body_size * displacement_threshold
                ema_ok = ema_fast is None or ema_slow is None or (ema_fast > ema_slow if is_long else ema_fast < ema_slow)
                # V10.5: High displacement override still applies
                high_disp = high_displacement_override > 0 and body >= avg_body_size * high_displacement_override
                adx_ok = adx is None or adx >= min_adx or (high_disp and adx is not None and adx >= 10)

                if use_hybrid_filters:
                    # Hybrid mode: 2 of 3 optional filters must pass
                    optional_passed = sum([disp_ok, adx_ok, ema_ok])
                    if optional_passed < 2:
                        continue
                else:
                    # Strict mode: all filters must pass
                    if not (disp_ok and adx_ok and ema_ok):
                        continue

                if True:  # Filters passed
                    stop_buffer_ticks = 2
                    entry_price = fvg.midpoint
                    stop_price = fvg.low - (stop_buffer_ticks * tick_size) if is_long else fvg.high + (stop_buffer_ticks * tick_size)
                    risk = abs(entry_price - stop_price)

                    if min_risk_pts > 0 and risk < min_risk_pts:
                        continue

                    # V10.2 time filters (V10.7: use EST timezone)
                    entry_hour = get_est_hour(creating_bar.timestamp)
                    if midday_cutoff and 12 <= entry_hour < 14:
                        continue  # Skip lunch lull (12:00-14:00 EST)
                    if pm_cutoff_nq and symbol in ['NQ', 'MNQ'] and entry_hour >= 14:
                        continue  # Skip NQ afternoon entries (after 14:00 EST)

                    valid_entries[direction].append({
                        'fvg': fvg,
                        'direction': direction,
                        'entry_type': 'CREATION',
                        'entry_bar_idx': session_bar_idx,
                        'entry_time': creating_bar.timestamp,
                        'entry_price': entry_price,
                        'stop_price': stop_price,
                        'fvg_low': fvg.low,
                        'fvg_high': fvg.high,
                    })

    # === Entry Type B: FVG Retracement + Rejection (Overnight + Intraday) ===
    if enable_retracement_entry:
        rth_start = dt_time(9, 30)

        # Get FVGs from overnight/premarket (before RTH 9:30)
        overnight_fvgs = [f for f in all_fvgs
                         if all_bars[f.created_bar_index].timestamp.time() < rth_start]

        # Get session FVGs (created during RTH) - for intraday retracement
        session_fvgs = [f for f in all_fvgs
                        if all_bars[f.created_bar_index].timestamp.time() >= rth_start]

        for i, bar in enumerate(session_bars):
            if i < 1:  # Need at least 1 bar of context
                continue

            # Only take retracement entries during RTH (9:30+)
            if bar.timestamp.time() < rth_start:
                continue

            # Morning only filter for OVERNIGHT retracement entries only
            # Intraday retracements can happen any time
            morning_end = dt_time(12, 0)
            is_morning = bar.timestamp.time() <= morning_end

            all_bar_idx = session_to_all_idx.get(i, i)

            # Calculate daily trend bias (EMA at 9:45 - 15 mins into RTH)
            daily_bias = None
            if retracement_trend_aligned:
                # Use EMA from 30 bars into session for stable trend reading
                trend_check_idx = min(120, len(session_bars) - 1)  # ~6 hours into session
                trend_bars = session_bars[:trend_check_idx + 1]
                trend_ema20 = calculate_ema(trend_bars, 20)
                trend_ema50 = calculate_ema(trend_bars, 50)
                if trend_ema20 and trend_ema50:
                    daily_bias = 'BULLISH' if trend_ema20 > trend_ema50 else 'BEARISH'

            for direction in ['LONG', 'SHORT']:
                is_long = direction == 'LONG'
                fvg_dir = 'BULLISH' if is_long else 'BEARISH'

                # Trend alignment filter - skip if direction doesn't match daily bias
                if retracement_trend_aligned and daily_bias:
                    expected_dir = 'LONG' if daily_bias == 'BULLISH' else 'SHORT'
                    if direction != expected_dir:
                        continue

                # Build list of FVGs to check: overnight (if morning) + intraday (created before current bar)
                fvgs_to_check = []

                # Add overnight FVGs (only in morning if filter enabled)
                if not retracement_morning_only or is_morning:
                    fvgs_to_check.extend(overnight_fvgs)

                # Add intraday FVGs created at least 2 bars ago (V10.7: reduced from 5 for quicker retrace)
                min_bars_ago = 2
                for fvg in session_fvgs:
                    fvg_session_idx = all_to_session_idx.get(fvg.created_bar_index)
                    if fvg_session_idx is not None and i - fvg_session_idx >= min_bars_ago:
                        fvgs_to_check.append(fvg)

                # Check FVGs for rejection entry
                for fvg in fvgs_to_check:
                    if fvg.direction != fvg_dir:
                        continue
                    if fvg.mitigated:
                        continue

                    # Check if this bar shows rejection from the FVG
                    is_rejection, entry_price, stop_price = is_rejection_candle(bar, fvg, direction, tick_size)

                    if not is_rejection:
                        continue

                    # Apply filters at rejection time
                    bars_to_entry = all_bars[:all_bar_idx + 1]
                    ema_fast = calculate_ema(bars_to_entry, 20)
                    ema_slow = calculate_ema(bars_to_entry, 50)
                    adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)

                    # V10.8 HYBRID FILTER SYSTEM
                    # MANDATORY: FVG Size (must pass)
                    fvg_size_ticks = (fvg.high - fvg.low) / tick_size
                    if fvg_size_ticks < 5:
                        continue

                    # MANDATORY: DI Direction (must pass)
                    di_ok = adx is None or (plus_di > minus_di if is_long else minus_di > plus_di)
                    if not di_ok:
                        continue

                    # OPTIONAL filters (2/3 must pass)
                    ema_ok = ema_fast is None or ema_slow is None or (ema_fast > ema_slow if is_long else ema_fast < ema_slow)
                    adx_ok = adx is None or adx >= min_adx
                    disp_ok = True  # Displacement already checked via rejection candle

                    if use_hybrid_filters:
                        optional_passed = sum([disp_ok, adx_ok, ema_ok])
                        if optional_passed < 2:
                            continue
                    else:
                        if not (ema_ok and adx_ok):
                            continue

                    risk = abs(entry_price - stop_price)
                    if min_risk_pts > 0 and risk < min_risk_pts:
                        continue

                    # Check if we already have an entry at similar price/time
                    duplicate = False
                    for existing in valid_entries[direction]:
                        if abs(existing['entry_price'] - entry_price) < tick_size * 4:
                            if abs(existing['entry_bar_idx'] - i) < 3:
                                duplicate = True
                                break

                    if not duplicate:
                        # Determine if overnight or intraday FVG
                        fvg_created_time = all_bars[fvg.created_bar_index].timestamp.time()
                        is_intraday = fvg_created_time >= rth_start
                        entry_label = 'INTRADAY_RETRACE' if is_intraday else 'RETRACEMENT'

                        # ADX filter for overnight retrace entries only
                        if not is_intraday and overnight_retrace_min_adx > 0:
                            if adx is None or adx < overnight_retrace_min_adx:
                                continue  # Skip overnight retrace if ADX too low

                        # V10.2 time filters (V10.7: use EST timezone)
                        entry_hour = get_est_hour(bar.timestamp)
                        if midday_cutoff and 12 <= entry_hour < 14:
                            continue  # Skip lunch lull (12:00-14:00 EST)
                        if pm_cutoff_nq and symbol in ['NQ', 'MNQ'] and entry_hour >= 14:
                            continue  # Skip NQ afternoon entries (after 14:00 EST)

                        valid_entries[direction].append({
                            'fvg': fvg,
                            'direction': direction,
                            'entry_type': entry_label,
                            'entry_bar_idx': i,
                            'entry_time': bar.timestamp,
                            'entry_price': entry_price,
                            'stop_price': stop_price,
                            'fvg_low': fvg.low,
                            'fvg_high': fvg.high,
                            'rejection_bar': bar,
                        })

    # === Entry Type C: BOS + Session FVG Retracement ===
    # V10.6: Skip BOS_RETRACE entries entirely (25% win rate drag)
    if enable_bos_entry and not disable_bos_retrace:
        rth_start = dt_time(9, 30)

        # Track BOS events and their associated FVGs
        bos_fvgs = []  # List of (bos_bar_idx, bos_direction, fvg)

        # First pass: find BOS events and FVGs that form after them
        for i in range(bos_lookback, len(session_bars)):
            bar = session_bars[i]
            all_bar_idx = session_to_all_idx.get(i)
            if all_bar_idx is None:
                continue

            # Only look for BOS during RTH
            if bar.timestamp.time() < rth_start:
                continue

            # Check for BOS at this bar
            bos_dir, bos_level = detect_bos(session_bars, i, bos_lookback)
            if bos_dir is None:
                continue

            # Find FVGs created within bos_fvg_window bars after this BOS
            for fvg in all_fvgs:
                fvg_session_idx = all_to_session_idx.get(fvg.created_bar_index)
                if fvg_session_idx is None:
                    continue

                # FVG must be created after BOS, within window
                bars_after_bos = fvg_session_idx - i
                if bars_after_bos < 0 or bars_after_bos > bos_fvg_window:
                    continue

                # FVG direction must match BOS direction
                expected_fvg_dir = 'BULLISH' if bos_dir == 'BULLISH' else 'BEARISH'
                if fvg.direction != expected_fvg_dir:
                    continue

                # Min FVG size (5 ticks)
                fvg_size_ticks = (fvg.high - fvg.low) / tick_size
                if fvg_size_ticks < 5:
                    continue

                # Check if FVG already tracked from this BOS
                already_tracked = False
                for existing in bos_fvgs:
                    if existing[2].low == fvg.low and existing[2].high == fvg.high:
                        already_tracked = True
                        break

                if not already_tracked:
                    bos_fvgs.append((i, bos_dir, fvg))

        # Second pass: find retracement entries into BOS FVGs
        for bos_bar_idx, bos_dir, fvg in bos_fvgs:
            fvg_session_idx = all_to_session_idx.get(fvg.created_bar_index)
            if fvg_session_idx is None:
                continue

            direction = 'LONG' if bos_dir == 'BULLISH' else 'SHORT'
            is_long = direction == 'LONG'

            # Look for retracement after FVG creation
            for i in range(fvg_session_idx + 1, len(session_bars)):
                bar = session_bars[i]
                all_bar_idx = session_to_all_idx.get(i)
                if all_bar_idx is None:
                    continue

                # Check if bar retraces into FVG
                if is_long:
                    # For LONG: price dips into FVG (low touches FVG zone)
                    touches_fvg = bar.low <= fvg.high and bar.low >= fvg.low - (tick_size * 2)
                    if not touches_fvg:
                        continue

                    # Entry at FVG midpoint or bar close (whichever is higher for safety)
                    entry_price = max(fvg.midpoint, bar.close)
                    stop_price = fvg.low - (2 * tick_size)
                else:
                    # For SHORT: price rallies into FVG (high touches FVG zone)
                    touches_fvg = bar.high >= fvg.low and bar.high <= fvg.high + (tick_size * 2)
                    if not touches_fvg:
                        continue

                    # Entry at FVG midpoint or bar close (whichever is lower for safety)
                    entry_price = min(fvg.midpoint, bar.close)
                    stop_price = fvg.high + (2 * tick_size)

                # Apply filters
                bars_to_entry = all_bars[:all_bar_idx + 1]
                ema_fast = calculate_ema(bars_to_entry, 20)
                ema_slow = calculate_ema(bars_to_entry, 50)
                adx, plus_di, minus_di = calculate_adx(bars_to_entry, 14)

                # V10.8 HYBRID FILTER SYSTEM
                # MANDATORY: DI Direction (must pass)
                di_ok = adx is None or (plus_di > minus_di if is_long else minus_di > plus_di)
                if not di_ok:
                    continue

                # OPTIONAL filters (2/3 must pass)
                ema_ok = ema_fast is None or ema_slow is None or (ema_fast > ema_slow if is_long else ema_fast < ema_slow)
                adx_ok = adx is None or adx >= min_adx
                disp_ok = True  # BOS already confirms momentum

                if use_hybrid_filters:
                    optional_passed = sum([disp_ok, adx_ok, ema_ok])
                    if optional_passed < 2:
                        continue
                else:
                    if not (ema_ok and adx_ok):
                        continue

                risk = abs(entry_price - stop_price)
                if min_risk_pts > 0 and risk < min_risk_pts:
                    continue

                # V10.4: Cap max risk for BOS entries to avoid oversized losses
                if max_bos_risk_pts and risk > max_bos_risk_pts:
                    continue  # Skip BOS entries with excessive risk

                # Check for duplicate entries
                duplicate = False
                for existing in valid_entries[direction]:
                    if abs(existing['entry_price'] - entry_price) < tick_size * 4:
                        if abs(existing['entry_bar_idx'] - i) < 3:
                            duplicate = True
                            break

                if not duplicate:
                    # V10.2 time filters (V10.7: use EST timezone)
                    entry_hour = get_est_hour(bar.timestamp)
                    if midday_cutoff and 12 <= entry_hour < 14:
                        continue  # Skip lunch lull (12:00-14:00 EST)
                    if pm_cutoff_nq and symbol in ['NQ', 'MNQ'] and entry_hour >= 14:
                        continue  # Skip NQ afternoon entries (after 14:00 EST)

                    valid_entries[direction].append({
                        'fvg': fvg,
                        'direction': direction,
                        'entry_type': 'BOS_RETRACE',
                        'entry_bar_idx': i,
                        'entry_time': bar.timestamp,
                        'entry_price': entry_price,
                        'stop_price': stop_price,
                        'fvg_low': fvg.low,
                        'fvg_high': fvg.high,
                        'bos_bar_idx': bos_bar_idx,
                    })
                    break  # Only one entry per BOS FVG

    # Combine and sort all entries by bar index
    all_valid_entries = valid_entries['LONG'] + valid_entries['SHORT']
    all_valid_entries.sort(key=lambda x: x['entry_bar_idx'])

    # Rest of the trade management logic (same as V9)
    active_trades = []
    completed_results = []
    entries_taken = {'LONG': 0, 'SHORT': 0}
    loss_count = 0
    bos_loss_count = 0  # V10.6: Track BOS losses for daily limit

    # V10.7: T1/T2/runner splits are now calculated per-trade based on trade's contract count
    # For 3 contracts: T1=1, T2=1, Runner=1
    # For 2 contracts: T1=1, T2=1, Runner=0

    for i in range(len(session_bars)):
        bar = session_bars[i]

        # Manage active trades
        trades_to_remove = []
        for trade in active_trades:
            is_long = trade['direction'] == 'LONG'
            remaining = trade['remaining']

            # V10.7: Calculate T1/T2/runner based on this trade's contract count
            trade_cts = trade.get('contracts', contracts)
            cts_t1 = 1
            cts_t2 = 1
            cts_runner = max(0, trade_cts - cts_t1 - cts_t2)

            if remaining <= 0:
                trades_to_remove.append(trade)
                continue

            # Update T1 fast structure trail after 4R
            if trade['touched_4r'] and not trade['t1_exited']:
                check_idx = i - 2
                if check_idx > trade['entry_bar_idx']:
                    if is_long and is_swing_low(session_bars, check_idx, lookback=2):
                        swing = session_bars[check_idx].low
                        if swing > trade['t1_last_swing']:
                            new_trail = swing - (2 * tick_size)
                            if new_trail > trade['t1_trail_stop']:
                                trade['t1_trail_stop'] = new_trail
                                trade['t1_last_swing'] = swing
                    elif not is_long and is_swing_high(session_bars, check_idx, lookback=2):
                        swing = session_bars[check_idx].high
                        if swing < trade['t1_last_swing']:
                            new_trail = swing + (2 * tick_size)
                            if new_trail < trade['t1_trail_stop']:
                                trade['t1_trail_stop'] = new_trail
                                trade['t1_last_swing'] = swing

            # Update T2 structure trail after 8R
            if trade['touched_8r'] and not trade['t2_exited']:
                check_idx = i - 2
                if check_idx > trade['entry_bar_idx']:
                    if is_long and is_swing_low(session_bars, check_idx, lookback=2):
                        swing = session_bars[check_idx].low
                        if swing > trade['t2_last_swing']:
                            new_trail = swing - (4 * tick_size)
                            if new_trail > trade['t2_trail_stop']:
                                trade['t2_trail_stop'] = new_trail
                                trade['t2_last_swing'] = swing
                    elif not is_long and is_swing_high(session_bars, check_idx, lookback=2):
                        swing = session_bars[check_idx].high
                        if swing < trade['t2_last_swing']:
                            new_trail = swing + (4 * tick_size)
                            if new_trail < trade['t2_trail_stop']:
                                trade['t2_trail_stop'] = new_trail
                                trade['t2_last_swing'] = swing

            # Update Runner structure trail after 8R (6-tick buffer, wider than T2)
            if trade['touched_8r'] and trade['t1_exited'] and trade['t2_exited']:
                check_idx = i - 2
                if check_idx > trade['entry_bar_idx']:
                    if is_long and is_swing_low(session_bars, check_idx, lookback=2):
                        swing = session_bars[check_idx].low
                        if swing > trade.get('runner_last_swing', trade['entry_price']):
                            new_trail = swing - (6 * tick_size)
                            if new_trail > trade['runner_stop']:
                                trade['runner_stop'] = new_trail
                                trade['runner_last_swing'] = swing
                    elif not is_long and is_swing_high(session_bars, check_idx, lookback=2):
                        swing = session_bars[check_idx].high
                        if swing < trade.get('runner_last_swing', trade['entry_price']):
                            new_trail = swing + (6 * tick_size)
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
                        exit_cts = min(cts_t1, remaining)
                        pnl = (trade['target_4r'] - trade['entry_price']) * exit_cts if is_long else (trade['entry_price'] - trade['target_4r']) * exit_cts
                        trade['exits'].append({'type': '4R_PARTIAL', 'pnl': pnl, 'price': trade['target_4r'], 'time': bar.timestamp, 'cts': exit_cts})
                        trade['remaining'] -= exit_cts
                        trade['t1_exited'] = True
                        remaining = trade['remaining']

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
                    trade['exits'].append({'type': 'STOP', 'pnl': pnl, 'price': trade['stop_price'], 'time': bar.timestamp, 'cts': remaining})
                    trade['remaining'] = 0
                    loss_count += 1
                    # V10.6: Track BOS losses for daily limit
                    if 'BOS' in trade.get('entry_type', ''):
                        bos_loss_count += 1
                    remaining = 0

            # After 4R but before 8R
            if trade['touched_4r'] and not trade['touched_8r'] and remaining > 0:
                t1_stop_hit = bar.low <= trade['t1_trail_stop'] if is_long else bar.high >= trade['t1_trail_stop']
                if t1_stop_hit:
                    if not trade['t1_exited']:
                        exit_cts = min(cts_t1, remaining)
                        pnl = (trade['t1_trail_stop'] - trade['entry_price']) * exit_cts if is_long else (trade['entry_price'] - trade['t1_trail_stop']) * exit_cts
                        trade['exits'].append({'type': 'T1_STRUCT', 'pnl': pnl, 'price': trade['t1_trail_stop'], 'time': bar.timestamp, 'cts': exit_cts})
                        trade['remaining'] -= exit_cts
                        trade['t1_exited'] = True
                        remaining = trade['remaining']

                    if remaining > 0:
                        pnl = (trade['t1_trail_stop'] - trade['entry_price']) * remaining if is_long else (trade['entry_price'] - trade['t1_trail_stop']) * remaining
                        trade['exits'].append({'type': 'TRAIL_STOP', 'pnl': pnl, 'price': trade['t1_trail_stop'], 'time': bar.timestamp, 'cts': remaining})
                        trade['t2_exited'] = True
                        trade['remaining'] = 0
                        remaining = 0

            # After 8R
            if trade['touched_8r'] and remaining > 0:
                if not trade['t1_exited']:
                    t1_stop_hit = bar.low <= trade['t1_trail_stop'] if is_long else bar.high >= trade['t1_trail_stop']
                    if t1_stop_hit:
                        exit_cts = min(cts_t1, remaining)
                        pnl = (trade['t1_trail_stop'] - trade['entry_price']) * exit_cts if is_long else (trade['entry_price'] - trade['t1_trail_stop']) * exit_cts
                        trade['exits'].append({'type': 'T1_STRUCT', 'pnl': pnl, 'price': trade['t1_trail_stop'], 'time': bar.timestamp, 'cts': exit_cts})
                        trade['remaining'] -= exit_cts
                        trade['t1_exited'] = True
                        remaining = trade['remaining']

                if not trade['t2_exited'] and remaining > cts_runner:
                    t2_stop_hit = bar.low <= trade['t2_trail_stop'] if is_long else bar.high >= trade['t2_trail_stop']
                    if t2_stop_hit:
                        exit_cts = min(cts_t2, remaining - cts_runner)
                        pnl = (trade['t2_trail_stop'] - trade['entry_price']) * exit_cts if is_long else (trade['entry_price'] - trade['t2_trail_stop']) * exit_cts
                        trade['exits'].append({'type': 'T2_STRUCT', 'pnl': pnl, 'price': trade['t2_trail_stop'], 'time': bar.timestamp, 'cts': exit_cts})
                        trade['remaining'] -= exit_cts
                        trade['t2_exited'] = True
                        remaining = trade['remaining']

                if trade['t1_exited'] and trade['t2_exited'] and remaining > 0:
                    runner_stop_hit = bar.low <= trade['runner_stop'] if is_long else bar.high >= trade['runner_stop']
                    if runner_stop_hit:
                        pnl = (trade['runner_stop'] - trade['entry_price']) * remaining if is_long else (trade['entry_price'] - trade['runner_stop']) * remaining
                        trade['exits'].append({'type': 'RUNNER_STOP', 'pnl': pnl, 'price': trade['runner_stop'], 'time': bar.timestamp, 'cts': remaining})
                        trade['remaining'] = 0
                        remaining = 0

            if trade['remaining'] <= 0:
                trades_to_remove.append(trade)

        for trade in trades_to_remove:
            if trade in active_trades:
                active_trades.remove(trade)
                completed_results.append(trade)

        # Check for new entries
        if loss_count >= max_losses_per_day:
            continue

        current_open = len(active_trades)

        for entry in all_valid_entries:
            if entry['entry_bar_idx'] != i:
                continue

            direction = entry['direction']
            entry_type = entry.get('entry_type', '')

            # V10.6: Skip BOS entries if daily loss limit reached
            if 'BOS' in entry_type and bos_daily_loss_limit > 0 and bos_loss_count >= bos_daily_loss_limit:
                continue

            if current_open >= max_open_trades:
                continue

            if entries_taken[direction] >= max_open_trades:  # V10.7: Use max_open_trades instead of hardcoded 2
                continue

            is_long = direction == 'LONG'
            entry_price = entry['entry_price']
            stop_price = entry['stop_price']
            risk = abs(entry_price - stop_price)

            # V10.7: Dynamic position sizing - scale down when multiple trades open
            # 0 trades open: 3 contracts, 1+ trades open: 2 contracts
            # This keeps max exposure at 6 contracts (vs 9 with fixed 3)
            trade_contracts = contracts if current_open == 0 else max(2, contracts - 1)

            target_4r = entry_price + (4 * risk) if is_long else entry_price - (4 * risk)
            target_8r = entry_price + (8 * risk) if is_long else entry_price - (8 * risk)
            plus_4r = entry_price + (4 * risk) if is_long else entry_price - (4 * risk)

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
                'is_2nd_entry': entries_taken[direction] > 0,
                'remaining': trade_contracts,  # V10.7: Use dynamic size
                'contracts': trade_contracts,  # V10.7: Store for reference
                'exits': [],
            }

            active_trades.append(new_trade)
            entries_taken[direction] += 1
            current_open += 1

    # EOD exit
    last_bar = session_bars[-1]
    for trade in active_trades:
        if trade['remaining'] > 0:
            is_long = trade['direction'] == 'LONG'
            pnl = (last_bar.close - trade['entry_price']) * trade['remaining'] if is_long else (trade['entry_price'] - last_bar.close) * trade['remaining']
            trade['exits'].append({'type': 'EOD', 'pnl': pnl, 'price': last_bar.close, 'time': last_bar.timestamp, 'cts': trade['remaining']})
            trade['remaining'] = 0
        completed_results.append(trade)

    # Build results
    final_results = []
    for trade in completed_results:
        if not trade.get('exits'):
            continue

        is_long = trade['direction'] == 'LONG'
        total_pnl = sum(e['pnl'] for e in trade['exits'])
        total_dollars = (total_pnl / tick_size) * tick_value

        final_results.append({
            'direction': trade['direction'],
            'entry_type': trade['entry_type'],
            'entry_time': trade['entry_time'],
            'entry_price': trade['entry_price'],
            'edge_price': trade['fvg_high'] if is_long else trade['fvg_low'],
            'midpoint_price': trade['entry_price'],
            'contracts_filled': trade.get('contracts', contracts),  # V10.7: Use trade's actual contract count
            'fill_type': 'FULL',
            'stop_price': trade['stop_price'],
            'fvg_low': trade['fvg_low'],
            'fvg_high': trade['fvg_high'],
            'target_4r': trade['target_4r'],
            'target_8r': trade['target_8r'],
            'plus_4r': trade.get('plus_4r', trade['target_4r']),
            'risk': trade['risk'],
            'total_pnl': total_pnl,
            'total_dollars': total_dollars,
            'was_stopped': any(e['type'] == 'STOP' for e in trade['exits']),
            'exits': trade['exits'],
            'is_reentry': trade.get('is_2nd_entry', False),
            'contracts': trade.get('contracts', contracts),  # V10.7: Actual contracts used
        })

    return final_results


def run_today_v10(symbol='ES', contracts=3, max_open_trades=2, min_risk_pts=None,
                  enable_creation=True, enable_retracement=True, enable_bos=True,
                  interval='3m', retracement_morning_only=False, retracement_trend_aligned=False,
                  overnight_retrace_min_adx=22,  # V11: ADX filter for overnight retrace
                  t1_fixed_4r=True):  # HYBRID default: T1 takes profit at 4R
    """Run V10 backtest for today.

    Args:
        enable_creation: Entry Type A - FVG creation entries
        enable_retracement: Entry Type B - Overnight FVG retracement entries
        enable_bos: Entry Type C - BOS + Session FVG retracement entries
        retracement_morning_only: Only take retracement entries 9:30-12:00 ET
        retracement_trend_aligned: Only take retracement entries matching daily trend
        overnight_retrace_min_adx: Min ADX for overnight retrace entries (22 default, 0 to disable)
        t1_fixed_4r: HYBRID - Take T1 profit at 4R instead of trailing
    """

    tick_size = 0.25
    # Tick values: ES=$12.50, NQ=$5.00, MES=$1.25 (1/10 ES), MNQ=$0.50 (1/10 NQ)
    tick_value = 12.50 if symbol == 'ES' else 5.00 if symbol == 'NQ' else 1.25 if symbol == 'MES' else 0.50 if symbol == 'MNQ' else 1.25

    if min_risk_pts is None:
        # Min risk in points (same for micro and mini contracts)
        min_risk_pts = 1.5 if symbol in ['ES', 'MES'] else 6.0 if symbol in ['NQ', 'MNQ'] else 1.5

    print(f'Fetching {symbol} {interval} data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval=interval, n_bars=1000)

    if all_bars:
        today = all_bars[-1].timestamp.date()
    else:
        print('No data available')
        return []

    today_bars = [b for b in all_bars if b.timestamp.date() == today]

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

    print(f'Date: {today}')
    print(f'Session bars: {len(session_bars)}')

    # Print RTH key levels (safeguard against misreading data)
    rth_bars = [b for b in session_bars if b.timestamp.time() >= dt_time(9, 30)]
    if rth_bars:
        rth_open = rth_bars[0].open
        rth_high = max(b.high for b in rth_bars)
        rth_low = min(b.low for b in rth_bars)
        print(f'RTH: Open={rth_open:.2f} High={rth_high:.2f} Low={rth_low:.2f}')

    print()
    print('='*70)
    print(f'{symbol} BACKTEST - {today} - {contracts} Contracts')
    print('='*70)
    print('Strategy: ICT FVG V10 (Quad Entry Mode)')
    print(f'  - Entry Type A (Creation): {"ENABLED" if enable_creation else "DISABLED"}')
    print(f'  - Entry Type B (Retrace): {"ENABLED" if enable_retracement else "DISABLED"}')
    if enable_retracement:
        print(f'    - B1: Overnight FVGs (ADX >= {overnight_retrace_min_adx})')
        print(f'    - B2: Intraday FVGs (5+ bars old)')
        print(f'    - Morning only filter: {"YES" if retracement_morning_only else "NO"}')
        print(f'    - Trend aligned: {"YES" if retracement_trend_aligned else "NO"}')
    print(f'  - Entry Type C (BOS + Retrace): {"ENABLED" if enable_bos else "DISABLED"}')
    print('  - Stop buffer: +2 ticks')
    print('  - HTF bias: EMA 20/50')
    print('  - ADX filter: > 17 (or 3x displacement with ADX >= 10)')
    print(f'  - Max open trades: {max_open_trades}')
    # Max BOS risk in points (same for micro and mini contracts)
    max_bos_risk_pts = 8.0 if symbol in ['ES', 'MES'] else 20.0 if symbol in ['NQ', 'MNQ'] else 8.0
    print(f'  - Min risk: {min_risk_pts} pts')
    print(f'  - Max BOS risk: {max_bos_risk_pts} pts')
    print(f'  - T1 Exit: {"4R FIXED (Hybrid)" if t1_fixed_4r else "Structure Trail"}')
    print(f'  - Midday cutoff (12-14): YES')
    print(f'  - PM cutoff (NQ/MNQ): {"YES" if symbol in ["NQ", "MNQ"] else "NO"}')
    print('='*70)

    all_results = run_session_v10(
        session_bars,
        all_bars,
        tick_size=tick_size,
        tick_value=tick_value,
        contracts=contracts,
        max_open_trades=max_open_trades,
        min_risk_pts=min_risk_pts,
        enable_creation_entry=enable_creation,
        enable_retracement_entry=enable_retracement,
        enable_bos_entry=enable_bos,
        retracement_morning_only=retracement_morning_only,
        retracement_trend_aligned=retracement_trend_aligned,
        overnight_retrace_min_adx=overnight_retrace_min_adx,
        t1_fixed_4r=t1_fixed_4r,
        midday_cutoff=True,
        pm_cutoff_nq=True,
        max_bos_risk_pts=max_bos_risk_pts,
        symbol=symbol,
    )

    total_pnl = 0
    creation_count = 0
    overnight_count = 0
    intraday_count = 0
    bos_count = 0

    for r in all_results:
        entry_tag = f" [{r['entry_type']}]"
        if r['entry_type'] == 'CREATION':
            creation_count += 1
        elif r['entry_type'] == 'BOS_RETRACE':
            bos_count += 1
        elif r['entry_type'] == 'INTRADAY_RETRACE':
            intraday_count += 1
        else:  # RETRACEMENT (overnight)
            overnight_count += 1

        if r.get('is_reentry'):
            entry_tag += ' [2nd]'

        result_str = 'WIN' if r['total_pnl'] > 0.01 else 'LOSS' if r['total_pnl'] < -0.01 else 'BE'
        total_pnl += r['total_dollars']

        print(f"\n{r['direction']} TRADE{entry_tag}")
        print(f"  Entry: {r['entry_price']:.2f} @ {r['entry_time'].strftime('%H:%M')}")
        print(f"  FVG: {r['fvg_low']:.2f} - {r['fvg_high']:.2f}")
        print(f"  Stop: {r['stop_price']:.2f}")
        print(f"  Risk: {r['risk']:.2f} pts")
        print(f"  Targets: 4R={r['target_4r']:.2f}, 8R={r['target_8r']:.2f}")
        print(f"  Exits:")
        for e in r['exits']:
            dollars = (e['pnl'] / tick_size) * tick_value
            print(f"    {e['type']}: {e['cts']} ct @ {e['price']:.2f} = ${dollars:+,.2f}")
        print(f"  Result: {result_str} | P/L: ${r['total_dollars']:+,.2f}")

    print()
    print('='*70)
    print(f'Entry Summary: {creation_count} Creation, {overnight_count} Overnight, {intraday_count} Intraday, {bos_count} BOS')
    print(f'TOTAL P/L: ${total_pnl:+,.2f}')
    print('='*70)

    return all_results


if __name__ == '__main__':
    symbol = sys.argv[1] if len(sys.argv) > 1 else 'ES'
    contracts = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    # Parse optional flags
    enable_creation = True
    enable_retracement = True
    enable_bos = True
    morning_only = False
    trend_aligned = False

    for arg in sys.argv[3:]:
        if arg == '--creation-only':
            enable_retracement = False
            enable_bos = False
        elif arg == '--retracement-only':
            enable_creation = False
            enable_bos = False
        elif arg == '--bos-only':
            enable_creation = False
            enable_retracement = False
        elif arg == '--no-bos':
            enable_bos = False
        elif arg == '--morning-only':
            morning_only = True
        elif arg == '--trend-aligned':
            trend_aligned = True

    run_today_v10(
        symbol=symbol,
        contracts=contracts,
        enable_creation=enable_creation,
        enable_retracement=enable_retracement,
        enable_bos=enable_bos,
        retracement_morning_only=morning_only,
        retracement_trend_aligned=trend_aligned,
    )
