"""
ICT Optimal Trade Entry (OTE) Strategy - Backtest Runner

Entry Logic:
1. Impulse Leg - Strong directional move with displacement
2. OTE Zone - 62-79% Fibonacci retracement zone
3. FVG Confluence - Optional FVG overlap with OTE zone
4. Retracement Entry - Price retraces into OTE zone with rejection

Usage:
    python -m runners.run_ict_ote ES 14
    python -m runners.run_ict_ote NQ 14
    python -m runners.run_ict_ote ES 14 --t1-r=3 --trail-r=6
"""
import sys
sys.path.insert(0, '.')

import pickle
from pathlib import Path
from datetime import time as dt_time, timedelta
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict_ote.strategy import ICTOTEStrategy, TradeSetup
from strategies.ict_ote.signals.smt import get_correlated_symbol
from strategies.ict_sweep.filters.session import get_session_name

CACHE_DIR = Path('.cache')
CACHE_DIR.mkdir(exist_ok=True)


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


def run_backtest(symbol: str = 'ES', days: int = 14, contracts: int = 0,
                 t1_r: int = 2, trail_r: int = 4, risk_per_trade: float = 500):
    """
    Run ICT OTE strategy backtest.

    Args:
        symbol: Instrument symbol (ES, NQ, MES, MNQ, SPY, QQQ)
        days: Number of days to backtest
        contracts: Contracts per trade (futures only)
        t1_r: R-multiple for T1 fixed exit (default 3)
        trail_r: R-multiple for structure trail activation (default 6)
        risk_per_trade: Dollar risk per trade (equities only)
    """
    is_equity = symbol.upper() in EQUITY_SYMBOLS

    # Instrument config
    max_risk_ticks = 20
    if is_equity:
        eq_cfg = EQUITY_CONFIG[symbol.upper()]
        tick_size = 0.01
        tick_value = 0.01
        min_fvg_ticks = int(eq_cfg['min_fvg_points'] / tick_size)
        min_risk_ticks = int(eq_cfg['min_risk_points'] / tick_size)
        min_impulse_ticks = int(eq_cfg['min_risk_points'] * 3 / tick_size)  # 3x min risk
        max_risk_ticks = 500
    elif symbol in ['ES', 'MES']:
        tick_size = 0.25
        tick_value = 12.50 if symbol == 'ES' else 1.25
        min_fvg_ticks = 3
        min_impulse_ticks = 10  # 2.5 pts
        min_risk_ticks = 6     # 1.5 pts
        max_risk_ticks = 20    # 5 pts max risk
    elif symbol in ['NQ', 'MNQ']:
        tick_size = 0.25
        tick_value = 5.00 if symbol == 'NQ' else 0.50
        min_fvg_ticks = 8
        min_impulse_ticks = 30  # 7.5 pts
        min_risk_ticks = 24     # 6 pts
        max_risk_ticks = 60     # 15 pts max risk
    else:
        tick_size = 0.25
        tick_value = 12.50
        min_fvg_ticks = 5
        min_impulse_ticks = 10
        min_risk_ticks = 6

    # 1 contract per trade — simple R/R: Win=+2R, Loss=-1R, BE=0R
    if contracts == 0:
        contracts = 1

    # Bars needed
    htf_bars_per_day = 78   # 5m bars in RTH
    ltf_bars_per_day = 130  # 3m bars in RTH

    htf_bars_needed = days * htf_bars_per_day + 1000
    ltf_bars_needed = days * ltf_bars_per_day + 1500

    print(f"Fetching {symbol} HTF (5m) data...")
    htf_bars = fetch_futures_bars(symbol=symbol, interval='5m', n_bars=htf_bars_needed)

    print(f"Fetching {symbol} LTF (3m) data...")
    ltf_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=ltf_bars_needed)

    # Fetch 2m bars for trend filter
    trend_bars_needed = days * 240 + 1500
    print(f"Fetching {symbol} trend (2m) data for EMA...")
    trend_bars = fetch_futures_bars(symbol=symbol, interval='2m', n_bars=trend_bars_needed)

    # Fetch correlated symbol for SMT divergence
    correlated_symbol = get_correlated_symbol(symbol)
    correlated_htf_bars = []
    if correlated_symbol:
        print(f"Fetching {correlated_symbol} HTF (5m) data for SMT divergence...")
        correlated_htf_bars = fetch_futures_bars(
            symbol=correlated_symbol, interval='5m', n_bars=htf_bars_needed
        ) or []
        print(f"  {correlated_symbol} bars: {len(correlated_htf_bars)}")

    if not htf_bars or not ltf_bars:
        print("No data available")
        return

    # Cache data for plotter
    cache_file = CACHE_DIR / f'ict_ote_{symbol}.pkl'
    with open(cache_file, 'wb') as f:
        pickle.dump({'htf_bars': htf_bars, 'ltf_bars': ltf_bars}, f)
    print(f"Data cached to {cache_file}")

    # Strategy config
    config = {
        'symbol': symbol,
        'tick_size': tick_size,
        'tick_value': tick_value,
        'impulse_body_multiplier': 2.0,
        'avg_body_lookback': 20,
        'min_impulse_ticks': min_impulse_ticks,
        'swing_lookback': 3,
        'impulse_max_bars_back': 30,
        'require_fvg_confluence': False,
        'min_fvg_ticks': min_fvg_ticks,
        'stop_buffer_ticks': 2,
        'min_risk_ticks': min_risk_ticks,
        'max_risk_ticks': max_risk_ticks,
        'loss_cooldown_minutes': 15,
        'allow_lunch': False,
        'require_killzone': False,
        'max_daily_trades': 3,
        'max_daily_losses': 2,
        'max_ote_age_bars': 25,          # ~2hrs on 5m
        # Trend filter ON — EMA 20/50 as optional in hybrid chain
        'use_trend_filter': True,
        'ema_fast_period': 20,           # was 10 — match V10 proven pair
        'ema_slow_period': 50,           # was 20 — match V10 proven pair
        # DI direction filter — optional in hybrid chain (3/5)
        'use_di_filter': True,
        'di_period': 14,
        't1_r': t1_r,
        'trail_r': trail_r,
        'debug': '--debug' in sys.argv,
        # MMXM enhancements
        'correlated_symbol': correlated_symbol or '',
        'premium_discount': {'enabled': True, 'method': 'session'},
        'dealing_range': {'enabled': True, 'swing_lookback': 3, 'max_bars_back': 100},
        'mmxm': {
            'enabled': True,
            'require_valid_sequence': False,
            'min_accumulation_bars': 10,
            'accumulation_atr_ratio': 0.6,
        },
        'smt': {
            'enabled': bool(correlated_symbol),
            'require_confirmation': False,
            'lookback': 20,
        },
        # A+ filter: risk/impulse ratio — reject wide-stop small-impulse entries
        'max_risk_impulse_ratio': 0.20,
        # Hybrid filter config — DI+P/D mandatory, 2/3 optional (EMA/disp/FVG)
        'min_hybrid_passes': 2,
    }

    # Per-symbol tuning
    if symbol in ['NQ', 'MNQ']:
        config['max_risk_impulse_ratio'] = 0.35  # NQ OTE zones are wider relative to impulses

    # Group bars by date
    dates = sorted(set(b.timestamp.date() for b in ltf_bars))

    print(f"\nAvailable dates in data: {dates}")
    print(f"Processing last {days} days: {dates[-days:]}")

    print()
    print("=" * 110)
    print(f"{symbol} ICT OPTIMAL TRADE ENTRY (OTE) STRATEGY BACKTEST")
    size_str = f"Risk: ${risk_per_trade}/trade" if is_equity else f"Contracts: {contracts}"
    print(f"HTF: 5m (impulse) | LTF: 3m (entry) | Days: {min(len(dates), days)} | {size_str} | T1={t1_r}R Trail={trail_r}R")
    print("=" * 110)
    print()
    print(f"{'Date':<12} | {'Time':<5} | {'Dir':<8} | {'Entry':>10} | {'Stop':>10} | {'Risk':>6} | "
          f"{'OTE Zone':>22} | {'Result':<6} | {'P/L':>12} | {'Session':<10}")
    print("-" * 110)

    # Track results
    all_trades = []
    total_wins = 0
    total_losses = 0
    total_pnl = 0.0

    for day in dates[-days:]:
        session_end = dt_time(16, 0)

        if is_equity:
            prev_day = day - timedelta(days=1)
            while prev_day.weekday() >= 5:
                prev_day = prev_day - timedelta(days=1)

            prev_rth_start = dt_time(9, 30)

            day_htf = [b for b in htf_bars
                       if (b.timestamp.date() == prev_day
                           and prev_rth_start <= b.timestamp.time() <= session_end)
                       or (b.timestamp.date() == day and b.timestamp.time() <= session_end)]

            session_start = dt_time(9, 30)
            day_ltf = [b for b in ltf_bars if b.timestamp.date() == day
                       and session_start <= b.timestamp.time() <= session_end]
            day_trend = [b for b in trend_bars if b.timestamp.date() == day
                         and session_start <= b.timestamp.time() <= session_end]
        else:
            # Futures: include overnight/Globex for impulse context
            overnight_start = dt_time(18, 0)
            prev_day = day - timedelta(days=1)
            if prev_day.weekday() == 5:
                prev_day = prev_day - timedelta(days=1)

            day_htf = [b for b in htf_bars
                       if (b.timestamp.date() == prev_day and b.timestamp.time() >= overnight_start)
                       or (b.timestamp.date() == day and b.timestamp.time() <= session_end)]

            # Print overnight high/low
            overnight_only = [b for b in day_htf if b.timestamp.date() == prev_day]
            if overnight_only:
                ovn_high = max(b.high for b in overnight_only)
                ovn_low = min(b.low for b in overnight_only)
                print(f"  [{day}] Overnight: High={ovn_high:.2f} Low={ovn_low:.2f} (bars: {len(overnight_only)})")

            session_start = dt_time(8, 0)
            day_ltf = [b for b in ltf_bars if b.timestamp.date() == day
                       and session_start <= b.timestamp.time() <= session_end]
            day_trend = [b for b in trend_bars if b.timestamp.date() == day
                         and session_start <= b.timestamp.time() <= session_end]

        if len(day_htf) < 30 or len(day_ltf) < 50:
            print(f"  [{day}] Skipping - insufficient bars (HTF: {len(day_htf)}, LTF: {len(day_ltf)})")
            continue

        # Initialize strategy for the day
        strategy = ICTOTEStrategy(config)

        # HTF lookback for swing context
        lookback_htf = [b for b in htf_bars if b.timestamp.date() < (prev_day if not is_equity else day)][-50:]
        for bar in lookback_htf:
            strategy.htf_bars.append(bar)

        # LTF lookback
        lookback_ltf = [b for b in ltf_bars if b.timestamp.date() < day][-50:]
        for bar in lookback_ltf:
            strategy.ltf_bars.append(bar)

        # Trend bar lookback
        lookback_trend = [b for b in trend_bars if b.timestamp.date() < day][-100:]
        for bar in lookback_trend:
            strategy.trend_bars.append(bar)

        # Filter correlated bars for this day
        if correlated_htf_bars:
            if is_equity:
                day_corr = [b for b in correlated_htf_bars
                            if (b.timestamp.date() == prev_day
                                and dt_time(9, 30) <= b.timestamp.time() <= session_end)
                            or (b.timestamp.date() == day and b.timestamp.time() <= session_end)]
            else:
                day_corr = [b for b in correlated_htf_bars
                            if (b.timestamp.date() == prev_day and b.timestamp.time() >= dt_time(18, 0))
                            or (b.timestamp.date() == day and b.timestamp.time() <= session_end)]
        else:
            day_corr = []

        # Process HTF and LTF bars together
        htf_idx = 0
        ltf_idx = 0
        trend_idx = 0
        corr_idx = 0
        day_setups = 0

        while ltf_idx < len(day_ltf):
            ltf_bar = day_ltf[ltf_idx]

            # Process HTF bars up to this LTF bar
            while htf_idx < len(day_htf) and day_htf[htf_idx].timestamp <= ltf_bar.timestamp:
                htf_bar = day_htf[htf_idx]

                # Process trend bars
                while trend_idx < len(day_trend) and day_trend[trend_idx].timestamp <= htf_bar.timestamp:
                    strategy.update_trend(day_trend[trend_idx])
                    trend_idx += 1

                # Process correlated bars for SMT
                while corr_idx < len(day_corr) and day_corr[corr_idx].timestamp <= htf_bar.timestamp:
                    strategy.update_correlated(day_corr[corr_idx])
                    corr_idx += 1

                # Update HTF - check for impulse legs
                setup = strategy.update_htf(htf_bar)
                if setup:
                    day_setups += 1

                htf_idx += 1

            # Update LTF - check for OTE entry
            trade = strategy.update_ltf(ltf_bar)

            if trade:
                entry_hour = trade.timestamp.hour
                # Midday cutoff — skip entries 12:00-14:00
                if 12 <= entry_hour < 14:
                    trade = None
                # NQ/MNQ PM cutoff — no entries after 14:00 (V10 proven)
                elif symbol in ['NQ', 'MNQ'] and entry_hour >= 14:
                    trade = None

            if trade:
                # Position sizing — scale by symbol risk profile
                if is_equity:
                    risk_dollars = abs(trade.entry_price - trade.stop_price)
                    trade_contracts = max(1, int(risk_per_trade / risk_dollars)) if risk_dollars > 0 else 1
                else:
                    trade_contracts = contracts

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
                    ote = trade.ote_zone
                    ote_str = f"{ote.bottom:.2f}-{ote.top:.2f}"

                    # Build MMXM info string
                    mmxm_parts = []
                    if trade.pd_zone:
                        mmxm_parts.append(f'PD={trade.pd_zone[:4]}')
                    if trade.mmxm_phase and trade.mmxm_phase != 'NONE':
                        mmxm_parts.append(f'MMXM={trade.mmxm_phase[:5]}')
                    if trade.smt_divergence:
                        mmxm_parts.append(f'SMT={trade.smt_divergence.divergence_type[:4]}')
                    mmxm_str = ' '.join(mmxm_parts) if mmxm_parts else ''

                    print(f"{day} | {est_time:<5} | {trade.direction:<8} | {trade.entry_price:>10.2f} | "
                          f"{trade.stop_price:>10.2f} | {trade.risk_ticks:>6.1f} | "
                          f"{ote_str:>22} | "
                          f"{result_str:<6} | ${result['pnl_dollars']:>+10,.2f} | {session:<10}"
                          f"{' | ' + mmxm_str if mmxm_str else ''}")

                    ltf_idx += result.get('bars_held', 1)

            ltf_idx += 1

        # Day summary with MMXM state
        state = strategy.get_state_summary()
        mmxm_info = []
        if 'mmxm_phase' in state:
            mmxm_info.append(f"MMXM={state['mmxm_phase']}")
        if 'pd_zone' in state:
            mmxm_info.append(f"PD={state['pd_zone']}")
        if 'dealing_range' in state:
            mmxm_info.append(f"DR={state['dealing_range']}")
        if 'smt' in state:
            mmxm_info.append(f"SMT={state['smt']}")
        mmxm_summary = f" | {', '.join(mmxm_info)}" if mmxm_info else ""
        print(f"  [{day}] OTE Setups: {day_setups}, Pending: {strategy.get_pending_count()}{mmxm_summary}")

        # Cache day results for plotter
        day_trades = [t for t in all_trades if t.get('date') == day]
        day_cache = CACHE_DIR / f'ict_ote_{symbol}_{day}.pkl'
        with open(day_cache, 'wb') as f:
            pickle.dump({
                'trades': day_trades,
                'day_htf': day_htf,
                'day_ltf': day_ltf,
                'config': config,
            }, f)

    # Print summary
    print("-" * 110)
    print()
    print("=" * 110)
    print("SUMMARY")
    print("=" * 110)

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
    print("=" * 110)
    print()
    print("Strategy: ICT Optimal Trade Entry (OTE)")
    print("  1. Impulse leg detected on 5m (displacement candle)")
    print("  2. OTE zone calculated (62-79% Fibonacci retracement)")
    print("  3. Price retraces into OTE zone on 3m")
    print("  4. Rejection candle confirms entry")
    print()

    return all_trades


def _result_dict(entry, exit_price, pnl_ticks, pnl_dollars, hit_target, bars_held, leg, contracts):
    """Build result dict with exits list for plotter compatibility."""
    return {
        'entry': entry, 'exit': exit_price,
        'pnl_ticks': pnl_ticks,
        'pnl_dollars': pnl_dollars,
        'hit_target': hit_target, 'bars_held': bars_held,
        'exits': [{'leg': leg, 'price': exit_price, 'contracts': contracts,
                   'pnl': pnl_dollars, 'bar_idx': bars_held}],
    }


def simulate_trade(bars, trade: TradeSetup, tick_size, tick_value, contracts=1,
                   t1_r=2, trail_r=None):
    """
    Simulate 1-contract trade: target at t1_r, breakeven after 1R.

    Exit structure:
    - Stop: Original stop exits at -1R
    - BE: After price reaches 1R profit, stop moves to entry (breakeven)
    - T1: Fixed exit at t1_r (default 2R)
    - EOD: Exit at close if neither stop nor target hit

    Args:
        bars: Remaining bars for the day
        trade: TradeSetup object
        tick_size: Instrument tick size
        tick_value: Dollar value per tick
        contracts: Number of contracts (default 1)
        t1_r: R-multiple for target exit (default 2)
        trail_r: Unused, kept for API compatibility

    Returns:
        Trade result dict
    """
    if len(bars) < 2:
        return None

    entry = trade.entry_price
    stop = trade.stop_price
    risk = abs(entry - stop)
    is_long = trade.direction == 'BULLISH'

    target = entry + (risk * t1_r) if is_long else entry - (risk * t1_r)
    be_trigger = entry + risk if is_long else entry - risk  # 1R profit level
    be_active = False
    current_stop = stop

    for i, bar in enumerate(bars[1:], 1):
        # 1. Check stop (original or breakeven)
        if is_long:
            if bar.low <= current_stop:
                pnl_ticks = (current_stop - entry) / tick_size
                pnl = pnl_ticks * tick_value * contracts
                leg = 'BE' if be_active else 'STOP'
                return _result_dict(entry, current_stop, pnl_ticks, pnl, False, i, leg, contracts)
        else:
            if bar.high >= current_stop:
                pnl_ticks = (entry - current_stop) / tick_size
                pnl = pnl_ticks * tick_value * contracts
                leg = 'BE' if be_active else 'STOP'
                return _result_dict(entry, current_stop, pnl_ticks, pnl, False, i, leg, contracts)

        # 2. Check target
        if is_long and bar.high >= target:
            pnl_ticks = (target - entry) / tick_size
            pnl = pnl_ticks * tick_value * contracts
            return _result_dict(entry, target, pnl_ticks, pnl, True, i, 'T1', contracts)
        elif not is_long and bar.low <= target:
            pnl_ticks = (entry - target) / tick_size
            pnl = pnl_ticks * tick_value * contracts
            return _result_dict(entry, target, pnl_ticks, pnl, True, i, 'T1', contracts)

        # 3. Check breakeven activation (price reaches 1R profit)
        if not be_active:
            if (is_long and bar.high >= be_trigger) or (not is_long and bar.low <= be_trigger):
                be_active = True
                current_stop = entry  # move stop to breakeven

    # EOD exit
    exit_price = bars[-1].close
    pnl_ticks = ((exit_price - entry) if is_long else (entry - exit_price)) / tick_size
    pnl = pnl_ticks * tick_value * contracts
    return _result_dict(entry, exit_price, pnl_ticks, pnl, False, len(bars) - 1, 'EOD', contracts)


if __name__ == '__main__':
    t1_r_val = 2
    trail_r_val = 4
    positional = []
    for a in sys.argv[1:]:
        if a.startswith('--t1-r='):
            t1_r_val = float(a.split('=')[1])
        elif a.startswith('--trail-r='):
            trail_r_val = float(a.split('=')[1])
        elif a.startswith('--'):
            continue
        else:
            positional.append(a)

    symbol = positional[0] if len(positional) > 0 else 'ES'
    days = int(positional[1]) if len(positional) > 1 else 14

    if symbol.upper() in EQUITY_SYMBOLS:
        risk_dollars = float(positional[2]) if len(positional) > 2 else 500
        run_backtest(symbol=symbol, days=days, contracts=0,
                     t1_r=t1_r_val, trail_r=trail_r_val, risk_per_trade=risk_dollars)
    else:
        contracts = int(positional[2]) if len(positional) > 2 else 0  # 0 = auto-size
        run_backtest(symbol=symbol, days=days, contracts=contracts,
                     t1_r=t1_r_val, trail_r=trail_r_val)
