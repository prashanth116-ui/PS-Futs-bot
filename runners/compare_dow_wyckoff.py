"""Compare Dow Theory + Wyckoff Range Filter vs Baseline.

Post-filters trades from run_session_v10() to estimate impact of each filter.
Not a full stateful implementation — for directional research only.

Usage:
    python -m runners.compare_dow_wyckoff           # Both ES and NQ, 22 days
    python -m runners.compare_dow_wyckoff ES 22     # ES only, 22 days
    python -m runners.compare_dow_wyckoff NQ 18     # NQ only, 18 days
"""
import sys
sys.path.insert(0, '.')

import math
from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from runners.run_v10_dual_entry import run_session_v10
from runners.symbol_defaults import get_symbol_config, get_session_v10_kwargs


# ── Dow Theory Swing Detection ───────────────────────────────────────

def detect_swings(bars, lookback=3):
    """Detect confirmed swing highs and lows.

    A swing high at bar i is confirmed when we've seen `lookback` bars after it
    without a higher high. Returns list of (type, bar_idx, price, confirmed_at).
    """
    swings = []
    for check_idx in range(lookback, len(bars)):
        # Need `lookback` bars on each side
        if check_idx < lookback:
            continue
        # Confirmation requires lookback bars after
        if check_idx + lookback >= len(bars):
            break

        is_high = True
        is_low = True
        for j in range(check_idx - lookback, check_idx + lookback + 1):
            if j == check_idx:
                continue
            if bars[j].high > bars[check_idx].high:
                is_high = False
            if bars[j].low < bars[check_idx].low:
                is_low = False

        confirmed_at = check_idx + lookback
        if is_high:
            swings.append(('HIGH', check_idx, bars[check_idx].high, confirmed_at))
        if is_low:
            swings.append(('LOW', check_idx, bars[check_idx].low, confirmed_at))

    return swings


def get_dow_state(swings, current_idx):
    """Get Dow Theory trend state at a given bar index.

    Returns: 'UPTREND', 'DOWNTREND', 'NEUTRAL', or 'UNKNOWN'
    """
    # Only use swings confirmed by current_idx
    confirmed_highs = [(idx, price) for typ, idx, price, conf in swings
                       if typ == 'HIGH' and conf <= current_idx]
    confirmed_lows = [(idx, price) for typ, idx, price, conf in swings
                      if typ == 'LOW' and conf <= current_idx]

    if len(confirmed_highs) < 2 or len(confirmed_lows) < 2:
        return 'UNKNOWN'

    _, h_prev = confirmed_highs[-2]
    _, h_last = confirmed_highs[-1]
    _, l_prev = confirmed_lows[-2]
    _, l_last = confirmed_lows[-1]

    higher_highs = h_last > h_prev
    higher_lows = l_last > l_prev

    if higher_highs and higher_lows:
        return 'UPTREND'
    elif not higher_highs and not higher_lows:
        return 'DOWNTREND'
    else:
        return 'NEUTRAL'


def dow_blocks_trade(dow_state, direction):
    """Check if Dow Theory would block a trade.

    Rules:
    - LONG only allowed in UPTREND
    - SHORT only allowed in DOWNTREND
    - UNKNOWN → allow (not enough data yet)
    - NEUTRAL → block (no clear trend)
    """
    if dow_state == 'UNKNOWN':
        return False  # Allow — not enough data
    if direction == 'LONG' and dow_state != 'UPTREND':
        return True
    if direction == 'SHORT' and dow_state != 'DOWNTREND':
        return True
    return False


# ── Wyckoff Consolidation Detection ──────────────────────────────────

def is_consolidation(bars, current_idx, range_bars=20, atr_mult=3.0):
    """Check if market is in Wyckoff consolidation range.

    Compares the recent N-bar range to ATR. If the range is compressed
    (below atr_mult × ATR), the market is consolidating.

    Expected range for random walk of N bars ≈ ATR × sqrt(N).
    For 20 bars: ≈ ATR × 4.47
    So atr_mult=3.0 catches range < 67% of expected (moderate consolidation).
    """
    if current_idx < max(range_bars, 20):
        return False

    # Recent range
    window = bars[current_idx - range_bars:current_idx]
    range_size = max(b.high for b in window) - min(b.low for b in window)

    # ATR over last 50 bars (or available)
    atr_start = max(1, current_idx - 50)
    trs = []
    for j in range(atr_start, current_idx):
        tr = max(
            bars[j].high - bars[j].low,
            abs(bars[j].high - bars[j - 1].close),
            abs(bars[j].low - bars[j - 1].close),
        )
        trs.append(tr)

    atr = sum(trs) / len(trs) if trs else 1
    return range_size < atr * atr_mult


# ── Backtest Comparison ──────────────────────────────────────────────

def find_bar_idx(session_bars, entry_time):
    """Find the bar index matching an entry timestamp."""
    for i, bar in enumerate(session_bars):
        if bar.timestamp == entry_time:
            return i
    # Fallback: closest timestamp
    target_ts = entry_time.timestamp()
    best_idx = 0
    best_diff = float('inf')
    for i, bar in enumerate(session_bars):
        diff = abs(bar.timestamp.timestamp() - target_ts)
        if diff < best_diff:
            best_diff = diff
            best_idx = i
    return best_idx


def run_comparison(symbol, days=22):
    """Run baseline vs Dow/Wyckoff comparison for a symbol."""
    cfg = get_symbol_config(symbol)

    print(f'\nFetching {symbol} 3m data...')
    all_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=10000)
    if not all_bars:
        print(f'  No data for {symbol}')
        return None

    # Get unique trading dates
    premarket_start = dt_time(4, 0)
    rth_end = dt_time(16, 0)

    all_dates = sorted(set(b.timestamp.date() for b in all_bars))
    # Filter to dates with enough session bars
    trading_dates = []
    for d in all_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == d]
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]
        if len(session_bars) >= 50:
            trading_dates.append(d)

    trading_dates = trading_dates[-days:]
    print(f'  Testing {len(trading_dates)} trading days: {trading_dates[0]} to {trading_dates[-1]}')

    # Define filter configs to test
    configs = [
        {'name': 'Baseline', 'dow': False, 'dow_lb': 0, 'wyckoff': False, 'wk_mult': 0},
        {'name': 'Dow (3-bar)', 'dow': True, 'dow_lb': 3, 'wyckoff': False, 'wk_mult': 0},
        {'name': 'Dow (5-bar)', 'dow': True, 'dow_lb': 5, 'wyckoff': False, 'wk_mult': 0},
        {'name': 'Wyckoff (ATR×3)', 'dow': False, 'dow_lb': 0, 'wyckoff': True, 'wk_mult': 3.0},
        {'name': 'Wyckoff (ATR×5)', 'dow': False, 'dow_lb': 0, 'wyckoff': True, 'wk_mult': 5.0},
        {'name': 'Dow(3)+Wk(3)', 'dow': True, 'dow_lb': 3, 'wyckoff': True, 'wk_mult': 3.0},
        {'name': 'Dow(3)+Wk(5)', 'dow': True, 'dow_lb': 3, 'wyckoff': True, 'wk_mult': 5.0},
        {'name': 'Dow(5)+Wk(5)', 'dow': True, 'dow_lb': 5, 'wyckoff': True, 'wk_mult': 5.0},
    ]

    # Initialize results tracking for each config
    results_by_config = {}
    for c in configs:
        results_by_config[c['name']] = {
            'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0.0,
            'blocked': 0, 'blocked_wins': 0, 'blocked_losses': 0,
            'blocked_win_pnl': 0.0, 'blocked_loss_pnl': 0.0,
            'daily_pnl': [], 'winning_days': 0, 'losing_days': 0,
        }

    # Pre-compute swings for each lookback value we need
    swing_lookbacks = set(c['dow_lb'] for c in configs if c['dow'])

    for target_date in trading_dates:
        day_bars = [b for b in all_bars if b.timestamp.date() == target_date]
        session_bars = [b for b in day_bars if premarket_start <= b.timestamp.time() <= rth_end]

        if len(session_bars) < 50:
            continue

        # Run baseline strategy
        kwargs = get_session_v10_kwargs(symbol)
        kwargs['contracts'] = 3
        trade_results = run_session_v10(session_bars, all_bars, **kwargs)

        if not trade_results:
            for c in configs:
                results_by_config[c['name']]['daily_pnl'].append(0.0)
            continue

        # Pre-compute swings for this day
        swings_by_lb = {}
        for lb in swing_lookbacks:
            swings_by_lb[lb] = detect_swings(session_bars, lookback=lb)

        # For each trade, compute filter states
        trade_annotations = []
        for result in trade_results:
            entry_time = result['entry_time']
            bar_idx = find_bar_idx(session_bars, entry_time)
            direction = result['direction']
            pnl = result['total_dollars']
            is_win = pnl > 0
            is_loss = pnl < 0

            # Compute Dow state for each lookback
            dow_states = {}
            for lb in swing_lookbacks:
                dow_states[lb] = get_dow_state(swings_by_lb[lb], bar_idx)

            # Compute Wyckoff consolidation for each multiplier
            wk_states = {}
            for c in configs:
                if c['wyckoff']:
                    mult = c['wk_mult']
                    if mult not in wk_states:
                        wk_states[mult] = is_consolidation(session_bars, bar_idx,
                                                            range_bars=20, atr_mult=mult)

            trade_annotations.append({
                'result': result,
                'bar_idx': bar_idx,
                'direction': direction,
                'pnl': pnl,
                'is_win': is_win,
                'is_loss': is_loss,
                'dow_states': dow_states,
                'wk_states': wk_states,
            })

        # Apply each config filter and tally
        for c in configs:
            config_name = c['name']
            day_pnl = 0.0
            day_trades = 0

            for ta in trade_annotations:
                blocked = False

                # Dow Theory filter
                if c['dow']:
                    dow_state = ta['dow_states'].get(c['dow_lb'], 'UNKNOWN')
                    if dow_blocks_trade(dow_state, ta['direction']):
                        blocked = True

                # Wyckoff filter
                if c['wyckoff']:
                    is_consol = ta['wk_states'].get(c['wk_mult'], False)
                    if is_consol:
                        blocked = True

                r = results_by_config[config_name]
                if blocked:
                    r['blocked'] += 1
                    if ta['is_win']:
                        r['blocked_wins'] += 1
                        r['blocked_win_pnl'] += ta['pnl']
                    elif ta['is_loss']:
                        r['blocked_losses'] += 1
                        r['blocked_loss_pnl'] += ta['pnl']
                else:
                    r['trades'] += 1
                    r['pnl'] += ta['pnl']
                    day_pnl += ta['pnl']
                    day_trades += 1
                    if ta['is_win']:
                        r['wins'] += 1
                    elif ta['is_loss']:
                        r['losses'] += 1

            r = results_by_config[config_name]
            r['daily_pnl'].append(day_pnl)
            if day_pnl > 0:
                r['winning_days'] += 1
            elif day_pnl < 0:
                r['losing_days'] += 1

    return results_by_config, len(trading_dates)


def print_results(symbol, results_by_config, n_days):
    """Print comparison table."""
    baseline_pnl = results_by_config['Baseline']['pnl']

    print(f'\n{"=" * 120}')
    print(f'  {symbol} — {n_days}-Day Dow Theory + Wyckoff Filter Comparison')
    print(f'{"=" * 120}')

    header = (f'{"Config":<20} {"Trades":>6} {"Wins":>5} {"Loss":>5} '
              f'{"WR%":>6} {"Total P/L":>12} {"Day WR":>8} '
              f'{"Blkd":>5} {"Blk L":>5} {"Blk W":>5} '
              f'{"Blk L $":>10} {"Blk W $":>10} {"Net Impact":>12}')
    print(header)
    print('-' * 120)

    for config_name in results_by_config:
        r = results_by_config[config_name]
        trades = r['trades']
        wins = r['wins']
        losses = r['losses']
        pnl = r['pnl']
        wr = (wins / trades * 100) if trades > 0 else 0
        win_days = r['winning_days']
        total_days = len(r['daily_pnl'])
        day_wr = f"{win_days}/{total_days}"
        blocked = r['blocked']
        blk_w = r['blocked_wins']
        blk_l = r['blocked_losses']
        blk_w_pnl = r['blocked_win_pnl']
        blk_l_pnl = r['blocked_loss_pnl']
        net_impact = pnl - baseline_pnl

        if config_name == 'Baseline':
            net_str = '—'
            blk_str = '—'
            blk_l_str = '—'
            blk_w_str = '—'
            blk_lp_str = '—'
            blk_wp_str = '—'
        else:
            net_str = f'${net_impact:+,.0f}'
            blk_str = str(blocked)
            blk_l_str = str(blk_l)
            blk_w_str = str(blk_w)
            blk_lp_str = f'${blk_l_pnl:+,.0f}'
            blk_wp_str = f'${blk_w_pnl:+,.0f}'

        row = (f'{config_name:<20} {trades:>6} {wins:>5} {losses:>5} '
               f'{wr:>5.1f}% {f"${pnl:+,.0f}":>12} {day_wr:>8} '
               f'{blk_str:>5} {blk_l_str:>5} {blk_w_str:>5} '
               f'{blk_lp_str:>10} {blk_wp_str:>10} {net_str:>12}')
        print(row)

    # Max drawdown for each config
    print(f'\n  Max Drawdown:')
    for config_name in results_by_config:
        r = results_by_config[config_name]
        daily = r['daily_pnl']
        cum = 0
        peak = 0
        max_dd = 0
        for d in daily:
            cum += d
            peak = max(peak, cum)
            dd = peak - cum
            max_dd = max(max_dd, dd)
        print(f'    {config_name:<20} ${max_dd:,.0f}')

    print()


if __name__ == '__main__':
    symbols_to_test = []
    days = 22

    if len(sys.argv) > 1:
        i = 1
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg.isdigit():
                days = int(arg)
            else:
                symbols_to_test.append(arg.upper())
            i += 1

    if not symbols_to_test:
        symbols_to_test = ['ES', 'NQ']

    for symbol in symbols_to_test:
        result = run_comparison(symbol, days)
        if result:
            results_by_config, n_days = result
            print_results(symbol, results_by_config, n_days)
