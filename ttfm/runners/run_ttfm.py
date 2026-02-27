"""
TTFM Single-Day Backtest Runner.

Usage:
    python -m ttfm.runners.run_ttfm ES 3
    python -m ttfm.runners.run_ttfm NQ 3
    python -m ttfm.runners.run_ttfm ES 3 --t1-r=3 --trail-r=6
"""
import sys
sys.path.insert(0, '.')

from datetime import time as dt_time
from ttfm.tradingview_loader import fetch_futures_bars
from ttfm.timeframe import aggregate_bars
from ttfm.signals.swing import find_swings
from ttfm.signals.bias import determine_bias
from ttfm.signals.cisd import detect_cisd
from ttfm.signals.candles import label_candles
from ttfm.signals.fvg import detect_fvgs, swings_as_pois
from ttfm.filters.alignment import check_alignment
from ttfm.filters.session import in_session


# ── Symbol config ──────────────────────────────────────────────────────────────

SYMBOL_CONFIG = {
    'ES':  {'tick_size': 0.25, 'tick_value': 12.50, 'min_risk': 1.5, 'max_risk': 7.0},
    'NQ':  {'tick_size': 0.25, 'tick_value': 5.00,  'min_risk': 6.0, 'max_risk': 20.0},
    'MES': {'tick_size': 0.25, 'tick_value': 1.25,  'min_risk': 1.5, 'max_risk': 7.0},
    'MNQ': {'tick_size': 0.25, 'tick_value': 0.50,  'min_risk': 6.0, 'max_risk': 20.0},
}


# ── Core session runner ───────────────────────────────────────────────────────

def run_session_ttfm(
    session_bars,       # 3m bars for the trading day (04:00–16:00)
    all_bars,           # all available 3m bars (for history/daily agg)
    tick_size=0.25,
    tick_value=12.50,
    contracts=3,
    min_risk_pts=1.5,
    max_risk_pts=10.0,
    t1_r_target=2,
    trail_r_trigger=4,
    stop_buffer_ticks=2,
    symbol='ES',
    swing_left=2,
    swing_right=2,
    entry_on='C3',
    require_cisd=True,
    max_open_trades=3,
):
    """Run TTFM strategy on a single day's session bars.

    Returns a list of trade result dicts compatible with the multiday runner.
    """
    if len(session_bars) < 30:
        return []

    cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG['ES'])

    # ── 1. Build timeframes ─────────────────────────────────────────────────
    bars_1h = aggregate_bars(session_bars, 60)
    bars_15m = aggregate_bars(session_bars, 15)

    # Daily bias: use only bars BEFORE the current session date (no look-ahead)
    session_date = session_bars[0].timestamp.date()
    history_bars = [b for b in all_bars if b.timestamp.date() < session_date]
    daily_bars = _build_daily_bars(history_bars)

    # ── 2. HTF bias (Daily) ─────────────────────────────────────────────────
    htf_bias = determine_bias(daily_bars)

    # ── 3. LTF analysis (15m — entry timeframe) ───────────────────────────
    ltf_swings = find_swings(bars_15m, left=swing_left, right=swing_right, timeframe="15m")
    ltf_cisds = detect_cisd(bars_15m, ltf_swings, lookback=10)
    ltf_labels = label_candles(bars_15m, ltf_swings)

    label_by_idx = {}
    for lbl in ltf_labels:
        label_by_idx[lbl.bar_index] = lbl

    cisd_by_idx = {}
    for c in ltf_cisds:
        cisd_by_idx[c.bar_index] = c

    # ── 4. Build 15m->3m timestamp mapping for entry execution ───────────
    def _find_3m_bar_for_15m(ltf_bar_idx):
        """Find the 3m bar index closest to when a 15m bar closes."""
        if ltf_bar_idx >= len(bars_15m):
            return None
        target_ts = bars_15m[ltf_bar_idx].timestamp
        best = None
        for si in range(len(session_bars)):
            if session_bars[si].timestamp >= target_ts:
                best = min(si + 4, len(session_bars) - 1)
                break
        return best

    # ── 5. Scan 15m bars for entries, manage trades on 3m ─────────────────
    active_trades = []
    completed_trades = []
    trades_in_direction = {'BULLISH': 0, 'BEARISH': 0}
    stop_buffer = stop_buffer_ticks * tick_size
    pending_entries = []

    for ltf_idx, lbl in label_by_idx.items():
        if lbl.label != entry_on:
            continue
        ltf_bar = bars_15m[ltf_idx] if ltf_idx < len(bars_15m) else None
        if ltf_bar is None:
            continue
        if not in_session(ltf_bar.timestamp):
            continue

        if htf_bias.direction == "NEUTRAL":
            continue
        if lbl.direction != htf_bias.direction:
            continue

        matching_cisd = None
        if require_cisd:
            for ci in range(max(0, ltf_idx - 5), ltf_idx + 1):
                if ci in cisd_by_idx and cisd_by_idx[ci].direction == lbl.direction:
                    matching_cisd = cisd_by_idx[ci]
                    break
            if matching_cisd is None:
                continue

        bar_3m_idx = _find_3m_bar_for_15m(ltf_idx)
        if bar_3m_idx is None or bar_3m_idx >= len(session_bars):
            continue

        pending_entries.append((bar_3m_idx, lbl, matching_cisd))

    pending_entries.sort(key=lambda x: x[0])
    pending_iter = iter(pending_entries)
    next_entry = next(pending_iter, None)

    for i in range(5, len(session_bars)):
        bar = session_bars[i]

        _manage_trades(
            active_trades, completed_trades, bar, i,
            tick_size, tick_value, t1_r_target, trail_r_trigger,
            trades_in_direction, session_bars,
        )

        if next_entry is None:
            continue
        entry_3m_idx, lbl, matching_cisd = next_entry
        if i < entry_3m_idx:
            continue
        next_entry = next(pending_iter, None)

        direction = lbl.direction

        open_in_dir = sum(1 for t in active_trades if t['direction'] == direction)
        if open_in_dir >= max_open_trades:
            continue

        if direction == "BULLISH":
            entry_price = bar.close
            c2_price = lbl.swing_point.price if lbl.swing_point else bar.low
            stop_price = c2_price - stop_buffer
            risk = entry_price - stop_price
        else:
            entry_price = bar.close
            c2_price = lbl.swing_point.price if lbl.swing_point else bar.high
            stop_price = c2_price + stop_buffer
            risk = stop_price - entry_price

        if risk <= 0:
            continue

        risk_pts = risk
        if risk_pts < min_risk_pts or risk_pts > max_risk_pts:
            continue

        t1_target = entry_price + risk * t1_r_target if direction == "BULLISH" else entry_price - risk * t1_r_target
        trail_target = entry_price + risk * trail_r_trigger if direction == "BULLISH" else entry_price - risk * trail_r_trigger

        is_first = trades_in_direction[direction] == 0
        n_contracts = contracts if is_first else max(2, contracts - 1)
        has_runner = is_first and n_contracts >= 3

        trade = {
            'direction': direction,
            'entry_type': f'TTFM_{lbl.label}',
            'entry_time': bar.timestamp,
            'entry_price': entry_price,
            'stop_price': stop_price,
            'original_stop': stop_price,
            'risk': risk,
            'risk_pts': risk_pts,
            'contracts': n_contracts,
            'remaining': n_contracts,
            'has_runner': has_runner,
            'target_t1': t1_target,
            'target_trail': trail_target,
            't1_hit': False,
            'trail_active': False,
            'trail_stop': None,
            'last_swing': entry_price,
            'exits': [],
            'bar_index': i,
            'htf_bias': htf_bias.direction,
            'htf_reason': htf_bias.reason,
        }
        active_trades.append(trade)
        trades_in_direction[direction] += 1

    # ── EOD close all remaining ─────────────────────────────────────────────
    last_bar = session_bars[-1]
    for trade in active_trades:
        if trade['remaining'] > 0:
            is_long = trade['direction'] == 'BULLISH'
            pnl = (last_bar.close - trade['entry_price']) * trade['remaining'] if is_long else (trade['entry_price'] - last_bar.close) * trade['remaining']
            trade['exits'].append({
                'type': 'EOD', 'pnl': pnl, 'price': last_bar.close,
                'time': last_bar.timestamp, 'cts': trade['remaining'],
            })
            trade['remaining'] = 0
        completed_trades.append(trade)

    # ── Build final results ─────────────────────────────────────────────────
    results = []
    for trade in completed_trades:
        if not trade.get('exits'):
            continue
        total_pnl = sum(e['pnl'] for e in trade['exits'])
        total_dollars = (total_pnl / tick_size) * tick_value
        results.append({
            'direction': trade['direction'],
            'entry_type': trade['entry_type'],
            'entry_time': trade['entry_time'],
            'entry_price': trade['entry_price'],
            'stop_price': trade['original_stop'],
            'risk': trade['risk'],
            'contracts': trade['contracts'],
            'total_pnl': total_pnl,
            'total_dollars': total_dollars,
            'was_stopped': any(e['type'] == 'STOP' for e in trade['exits']),
            'exits': trade['exits'],
            'htf_bias': trade['htf_bias'],
            'htf_reason': trade['htf_reason'],
        })

    return results


# ── Trade management ──────────────────────────────────────────────────────────

def _manage_trades(
    active_trades, completed_trades, bar, bar_idx,
    tick_size, tick_value, t1_r, trail_r,
    trades_in_dir, bars,
    t2_r=None,
):
    """Check stops, T1/T2 exits, and trail updates for all active trades."""
    to_remove = []

    for trade in active_trades:
        is_long = trade['direction'] == 'BULLISH'
        remaining = trade['remaining']
        if remaining <= 0:
            to_remove.append(trade)
            continue

        entry = trade['entry_price']
        stop = trade['stop_price']

        # ── Check stop hit ──────────────────────────────────────────────
        stopped = (bar.low <= stop) if is_long else (bar.high >= stop)
        if stopped and not trade['t1_hit']:
            pnl = (stop - entry) * remaining if is_long else (entry - stop) * remaining
            trade['exits'].append({
                'type': 'STOP', 'pnl': pnl, 'price': stop,
                'time': bar.timestamp, 'cts': remaining,
            })
            trade['remaining'] = 0
            to_remove.append(trade)
            continue

        # ── Check T1 hit ────────────────────────────────────────────────
        if not trade['t1_hit'] and remaining > 0:
            t1 = trade['target_t1']
            t1_hit = (bar.high >= t1) if is_long else (bar.low <= t1)
            if t1_hit:
                cts = 1
                pnl = (t1 - entry) * cts if is_long else (entry - t1) * cts
                trade['exits'].append({
                    'type': 'T1', 'pnl': pnl, 'price': t1,
                    'time': bar.timestamp, 'cts': cts,
                })
                trade['remaining'] -= cts
                trade['t1_hit'] = True
                trade['stop_price'] = entry
                trade['last_swing'] = entry
                if trade['remaining'] <= 0:
                    to_remove.append(trade)
                    continue

        # ── Check T2 hit ────────────────────────────────────────────────
        if t2_r and trade['t1_hit'] and not trade.get('t2_hit') and remaining > 1:
            t2_price = entry + trade['risk'] * t2_r if is_long else entry - trade['risk'] * t2_r
            t2_hit = (bar.high >= t2_price) if is_long else (bar.low <= t2_price)
            if t2_hit:
                cts = 1
                pnl = (t2_price - entry) * cts if is_long else (entry - t2_price) * cts
                trade['exits'].append({
                    'type': 'T2', 'pnl': pnl, 'price': t2_price,
                    'time': bar.timestamp, 'cts': cts,
                })
                trade['remaining'] -= cts
                trade['t2_hit'] = True
                t1_floor = entry + trade['risk'] * t1_r if is_long else entry - trade['risk'] * t1_r
                trade['stop_price'] = t1_floor
                trade['last_swing'] = t1_floor
                if trade['remaining'] <= 0:
                    to_remove.append(trade)
                    continue

        # ── Check trail activation ──────────────────────────────────────
        if trade['t1_hit'] and not trade['trail_active'] and trade['remaining'] > 0:
            tt = trade['target_trail']
            trail_hit = (bar.high >= tt) if is_long else (bar.low <= tt)
            if trail_hit:
                trade['trail_active'] = True
                floor = entry + trade['risk'] * t1_r if is_long else entry - trade['risk'] * t1_r
                trade['trail_stop'] = floor
                trade['stop_price'] = floor
                trade['last_swing'] = bar.high if is_long else bar.low

        # ── Trail stop update (structure trail) ─────────────────────────
        if trade['trail_active'] and trade['remaining'] > 0:
            trail_buffer = 4 * tick_size
            if bar_idx >= 2:
                check_bar = bars[bar_idx - 2]
                if is_long:
                    if (bars[bar_idx - 2].low < bars[bar_idx - 3].low if bar_idx >= 3 else False) and bars[bar_idx - 2].low < bars[bar_idx - 1].low:
                        new_trail = check_bar.low - trail_buffer
                        if new_trail > trade['trail_stop'] and check_bar.low > trade['last_swing']:
                            trade['trail_stop'] = new_trail
                            trade['stop_price'] = new_trail
                            trade['last_swing'] = check_bar.low
                else:
                    if (bars[bar_idx - 2].high > bars[bar_idx - 3].high if bar_idx >= 3 else False) and bars[bar_idx - 2].high > bars[bar_idx - 1].high:
                        new_trail = check_bar.high + trail_buffer
                        if new_trail < trade['trail_stop'] and check_bar.high < trade['last_swing']:
                            trade['trail_stop'] = new_trail
                            trade['stop_price'] = new_trail
                            trade['last_swing'] = check_bar.high

            trail_stopped = (bar.low <= trade['trail_stop']) if is_long else (bar.high >= trade['trail_stop'])
            if trail_stopped:
                remaining = trade['remaining']
                pnl = (trade['trail_stop'] - entry) * remaining if is_long else (entry - trade['trail_stop']) * remaining
                trade['exits'].append({
                    'type': 'TRAIL', 'pnl': pnl, 'price': trade['trail_stop'],
                    'time': bar.timestamp, 'cts': remaining,
                })
                trade['remaining'] = 0
                to_remove.append(trade)
                continue

        # ── Post-T1 breakeven stop ────────────────────────────────────
        if trade['t1_hit'] and not trade['trail_active'] and trade['remaining'] > 0:
            be_stopped = (bar.low <= trade['stop_price']) if is_long else (bar.high >= trade['stop_price'])
            if be_stopped:
                remaining = trade['remaining']
                pnl = (trade['stop_price'] - entry) * remaining if is_long else (entry - trade['stop_price']) * remaining
                trade['exits'].append({
                    'type': 'BE_STOP', 'pnl': pnl, 'price': trade['stop_price'],
                    'time': bar.timestamp, 'cts': remaining,
                })
                trade['remaining'] = 0
                to_remove.append(trade)
                continue

    for trade in to_remove:
        if trade in active_trades:
            active_trades.remove(trade)
            completed_trades.append(trade)


# ── Native 15m session runner (for long-range backtests) ─────────────────────

def run_session_ttfm_native(
    bars_15m_session,   # 15m bars for the trading day (04:00-16:00)
    bars_1h_session,    # 1H bars for the trading day
    daily_bars,         # daily bars up to (but NOT including) session date
    tick_size=0.25,
    tick_value=12.50,
    contracts=3,
    min_risk_pts=1.5,
    max_risk_pts=10.0,
    t1_r_target=2,
    trail_r_trigger=4,
    stop_buffer_ticks=2,
    symbol='ES',
    swing_left=2,
    swing_right=2,
    entry_on='C3',
    require_cisd=True,
    max_open_trades=3,
    risk_cap_pts=None,
    allow_lunch=False,
    rth_only=False,
    skip_risk_deadzone=False,
    t2_r_target=None,
):
    """Run TTFM on native 15m bars (no 3m aggregation needed).

    Used by the long-range backtest which fetches 15m bars directly from
    TradingView for 60+ day coverage. Trade management runs on 15m bars.
    """
    if len(bars_15m_session) < 10:
        return []

    htf_bias = determine_bias(daily_bars)

    ltf_swings = find_swings(bars_15m_session, left=swing_left, right=swing_right, timeframe="15m")
    ltf_cisds = detect_cisd(bars_15m_session, ltf_swings, lookback=10)
    ltf_labels = label_candles(bars_15m_session, ltf_swings)

    label_by_idx = {}
    for lbl in ltf_labels:
        label_by_idx[lbl.bar_index] = lbl

    cisd_by_idx = {}
    for c in ltf_cisds:
        cisd_by_idx[c.bar_index] = c

    active_trades = []
    completed_trades = []
    trades_in_direction = {'BULLISH': 0, 'BEARISH': 0}
    stop_buffer = stop_buffer_ticks * tick_size

    for i in range(2, len(bars_15m_session)):
        bar = bars_15m_session[i]

        _manage_trades(
            active_trades, completed_trades, bar, i,
            tick_size, tick_value, t1_r_target, trail_r_trigger,
            trades_in_direction, bars_15m_session,
            t2_r=t2_r_target,
        )

        lbl = label_by_idx.get(i)
        if lbl is None or lbl.label != entry_on:
            continue

        sess_start = "08:00" if rth_only else "04:00"
        no_start = "23:59" if allow_lunch else "12:00"
        no_end = "23:59" if allow_lunch else "14:00"
        if not in_session(bar.timestamp, session_start=sess_start,
                          no_entry_start=no_start, no_entry_end=no_end):
            continue

        direction = lbl.direction

        if htf_bias.direction == "NEUTRAL":
            continue
        if direction != htf_bias.direction:
            continue

        matching_cisd = None
        if require_cisd:
            for ci in range(max(0, i - 5), i + 1):
                if ci in cisd_by_idx and cisd_by_idx[ci].direction == direction:
                    matching_cisd = cisd_by_idx[ci]
                    break
            if matching_cisd is None:
                continue

        open_in_dir = sum(1 for t in active_trades if t['direction'] == direction)
        if open_in_dir >= max_open_trades:
            continue

        if direction == "BULLISH":
            entry_price = bar.close
            c2_price = lbl.swing_point.price if lbl.swing_point else bar.low
            stop_price = c2_price - stop_buffer
            risk = entry_price - stop_price
        else:
            entry_price = bar.close
            c2_price = lbl.swing_point.price if lbl.swing_point else bar.high
            stop_price = c2_price + stop_buffer
            risk = stop_price - entry_price

        if risk <= 0:
            continue
        if risk < min_risk_pts:
            continue
        if skip_risk_deadzone and 7.0 <= risk < 12.0:
            continue
        oversized = False
        if risk_cap_pts and risk > risk_cap_pts:
            if risk > max_risk_pts:
                continue
            oversized = True
        elif risk > max_risk_pts:
            continue

        t1_target = entry_price + risk * t1_r_target if direction == "BULLISH" else entry_price - risk * t1_r_target
        trail_target = entry_price + risk * trail_r_trigger if direction == "BULLISH" else entry_price - risk * trail_r_trigger

        is_first = trades_in_direction[direction] == 0
        if oversized:
            n_contracts = 1
            has_runner = False
        else:
            n_contracts = contracts if is_first else max(2, contracts - 1)
            has_runner = is_first and n_contracts >= 3

        trade = {
            'direction': direction,
            'entry_type': f'TTFM_{lbl.label}',
            'entry_time': bar.timestamp,
            'entry_price': entry_price,
            'stop_price': stop_price,
            'original_stop': stop_price,
            'risk': risk,
            'risk_pts': risk,
            'contracts': n_contracts,
            'remaining': n_contracts,
            'has_runner': has_runner,
            'target_t1': t1_target,
            'target_trail': trail_target,
            't1_hit': False,
            'trail_active': False,
            'trail_stop': None,
            'last_swing': entry_price,
            'exits': [],
            'bar_index': i,
            'htf_bias': htf_bias.direction,
            'htf_reason': htf_bias.reason,
        }
        active_trades.append(trade)
        trades_in_direction[direction] += 1

    # ── EOD close ─────────────────────────────────────────────────────────
    last_bar = bars_15m_session[-1]
    for trade in active_trades:
        if trade['remaining'] > 0:
            is_long = trade['direction'] == 'BULLISH'
            pnl = (last_bar.close - trade['entry_price']) * trade['remaining'] if is_long else (trade['entry_price'] - last_bar.close) * trade['remaining']
            trade['exits'].append({
                'type': 'EOD', 'pnl': pnl, 'price': last_bar.close,
                'time': last_bar.timestamp, 'cts': trade['remaining'],
            })
            trade['remaining'] = 0
        completed_trades.append(trade)

    results = []
    for trade in completed_trades:
        if not trade.get('exits'):
            continue
        total_pnl = sum(e['pnl'] for e in trade['exits'])
        total_dollars = (total_pnl / tick_size) * tick_value
        results.append({
            'direction': trade['direction'],
            'entry_type': trade['entry_type'],
            'entry_time': trade['entry_time'],
            'entry_price': trade['entry_price'],
            'stop_price': trade['original_stop'],
            'risk': trade['risk'],
            'contracts': trade['contracts'],
            'total_pnl': total_pnl,
            'total_dollars': total_dollars,
            'was_stopped': any(e['type'] == 'STOP' for e in trade['exits']),
            'exits': trade['exits'],
            'htf_bias': trade['htf_bias'],
            'htf_reason': trade['htf_reason'],
        })
    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_daily_bars(all_bars):
    """Aggregate all_bars into daily bars for HTF bias."""
    from ttfm.core import Bar
    by_date = {}
    for b in all_bars:
        d = b.timestamp.date()
        by_date.setdefault(d, []).append(b)

    daily = []
    for d in sorted(by_date):
        day = by_date[d]
        daily.append(Bar(
            timestamp=day[0].timestamp,
            open=day[0].open,
            high=max(b.high for b in day),
            low=min(b.low for b in day),
            close=day[-1].close,
            volume=sum(b.volume for b in day),
            symbol=day[0].symbol,
            timeframe="1d",
        ))
    return daily


# ── Single-day backtest CLI ───────────────────────────────────────────────────

def run_today_ttfm(symbol='ES', contracts=3, t1_r=2, trail_r=4):
    """Run TTFM backtest for today."""
    cfg = SYMBOL_CONFIG.get(symbol, SYMBOL_CONFIG['ES'])
    tick_size = cfg['tick_size']
    tick_value = cfg['tick_value']
    min_risk = cfg['min_risk']
    max_risk = cfg['max_risk']

    print(f'Fetching {symbol} 3m data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=1000)

    if not all_bars:
        print('No data available')
        return

    today = all_bars[-1].timestamp.date()
    today_bars = [b for b in all_bars if b.timestamp.date() == today]

    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)
    session_bars = [b for b in today_bars if premarket_start <= b.timestamp.time() <= rth_end]

    print(f'Date: {today}')
    print(f'Session bars: {len(session_bars)}')

    rth_bars = [b for b in session_bars if b.timestamp.time() >= dt_time(9, 30)]
    if rth_bars:
        print(f'RTH: Open={rth_bars[0].open:.2f} High={max(b.high for b in rth_bars):.2f} Low={min(b.low for b in rth_bars):.2f}')

    print()
    print('='*80)
    print(f'{symbol} TTFM SINGLE-DAY BACKTEST - {today}')
    print('='*80)
    print(f'Strategy: TTrades Fractal Model (T1={t1_r}R, Trail={trail_r}R)')
    print(f'  Min risk: {min_risk} pts | Max risk: {max_risk} pts')
    print(f'  Contracts: {contracts} (1st trade) / {max(2, contracts-1)} (subsequent)')
    print('='*80)
    print()

    results = run_session_ttfm(
        session_bars, all_bars,
        tick_size=tick_size, tick_value=tick_value,
        contracts=contracts,
        min_risk_pts=min_risk, max_risk_pts=max_risk,
        t1_r_target=t1_r, trail_r_trigger=trail_r,
        symbol=symbol,
    )

    total_pnl = 0
    wins = 0
    losses = 0

    if results:
        print(f'{"#":>3} {"Time":<8} {"Dir":<8} {"Type":<10} {"Entry":>10} {"Stop":>10} {"Risk":>6} {"Cts":>4} {"P/L":>12}')
        print('-'*80)
        for i, r in enumerate(results):
            t = r['entry_time']
            time_str = t.strftime('%H:%M') if t else '??:??'
            total_pnl += r['total_dollars']
            is_win = r['total_dollars'] > 0
            if is_win:
                wins += 1
            elif r['total_dollars'] < 0:
                losses += 1
            print(f'{i+1:>3} {time_str:<8} {r["direction"]:<8} {r["entry_type"]:<10} {r["entry_price"]:>10.2f} {r["stop_price"]:>10.2f} {r["risk"]:>6.2f} {r["contracts"]:>4} ${r["total_dollars"]:>+10,.0f}')

    print('-'*80)
    print()

    n_trades = len(results)
    win_rate = (wins / n_trades * 100) if n_trades > 0 else 0

    print(f'Trades: {n_trades}  |  Wins: {wins}  |  Losses: {losses}  |  Win Rate: {win_rate:.1f}%')
    print(f'Total P/L: ${total_pnl:+,.2f}')
    print()

    if results:
        print(f'HTF Bias: {results[0]["htf_bias"]} — {results[0]["htf_reason"]}')

    return results


if __name__ == '__main__':
    positional = []
    t1_r = 2
    trail_r = 4
    for arg in sys.argv[1:]:
        if arg.startswith('--t1-r='):
            t1_r = int(arg.split('=')[1])
        elif arg.startswith('--trail-r='):
            trail_r = int(arg.split('=')[1])
        else:
            positional.append(arg)

    symbol = positional[0] if len(positional) > 0 else 'ES'
    contracts = int(positional[1]) if len(positional) > 1 else 3

    run_today_ttfm(symbol=symbol, contracts=contracts, t1_r=t1_r, trail_r=trail_r)
