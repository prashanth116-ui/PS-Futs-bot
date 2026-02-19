"""Test overnight session before RTH."""
import sys
sys.path.insert(0, '.')
from datetime import date, time as dt_time, timedelta
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict_sweep.strategy import ICTSweepStrategy, TradeSetup


def to_est(utc_dt):
    return utc_dt - timedelta(hours=5)


def simulate_trade(bars, trade, tick_size, tick_value, contracts):
    if len(bars) < 2:
        return None
    entry, stop, t2 = trade.entry_price, trade.stop_price, trade.t2_price
    for i, bar in enumerate(bars[1:], 1):
        if trade.direction == 'LONG':
            if bar.low <= stop:
                return {'exit': stop, 'bar': i, 'result': 'STOP',
                        'pnl': (stop - entry) / tick_size * tick_value * contracts}
            if bar.high >= t2:
                return {'exit': t2, 'bar': i, 'result': 'TARGET',
                        'pnl': (t2 - entry) / tick_size * tick_value * contracts}
        else:
            if bar.high >= stop:
                return {'exit': stop, 'bar': i, 'result': 'STOP',
                        'pnl': (entry - stop) / tick_size * tick_value * contracts}
            if bar.low <= t2:
                return {'exit': t2, 'bar': i, 'result': 'TARGET',
                        'pnl': (entry - t2) / tick_size * tick_value * contracts}
    exit_price = bars[-1].close
    pnl = ((exit_price - entry) if trade.direction == 'LONG' else (entry - exit_price)) / tick_size * tick_value * contracts
    return {'exit': exit_price, 'bar': len(bars) - 1, 'result': 'EOD', 'pnl': pnl}


def run_backtest(config, day_htf, day_mtf, day_ltf, lookback_htf, lookback_mtf, lookback_ltf, tick_size, tick_value, contracts):
    strategy = ICTSweepStrategy(config)
    for bar in lookback_htf:
        strategy.htf_bars.append(bar)
    for bar in lookback_mtf:
        strategy.mtf_bars.append(bar)
    for bar in lookback_ltf:
        strategy.ltf_bars.append(bar)

    trades = []
    htf_idx, mtf_idx, ltf_idx = 0, 0, 0

    while ltf_idx < len(day_ltf):
        ltf_bar = day_ltf[ltf_idx]
        while htf_idx < len(day_htf) and day_htf[htf_idx].timestamp <= ltf_bar.timestamp:
            htf_bar = day_htf[htf_idx]
            while mtf_idx < len(day_mtf) and day_mtf[mtf_idx].timestamp <= htf_bar.timestamp:
                strategy.update_mtf(day_mtf[mtf_idx])
                mtf_idx += 1
            strategy.update_htf(htf_bar)
            mitigation_result = strategy.check_htf_mitigation(htf_bar)
            if isinstance(mitigation_result, TradeSetup):
                result = simulate_trade(day_ltf[ltf_idx:], mitigation_result, tick_size, tick_value, contracts)
                if result:
                    trades.append({'trade': mitigation_result, 'result': result})
                    ltf_idx += result['bar']
            htf_idx += 1
        trade = strategy.update_ltf(ltf_bar)
        if trade:
            result = simulate_trade(day_ltf[ltf_idx:], trade, tick_size, tick_value, contracts)
            if result:
                trades.append({'trade': trade, 'result': result})
                ltf_idx += result['bar']
        ltf_idx += 1
    return trades


def main():
    symbol = 'ES'
    tick_size = 0.25
    tick_value = 12.50
    contracts = 3

    print('Fetching data...')
    htf_bars = fetch_futures_bars(symbol=symbol, interval='5m', n_bars=1000)
    mtf_bars = fetch_futures_bars(symbol=symbol, interval='3m', n_bars=1500)

    target_date = date(2026, 2, 12)

    # Overnight before RTH: midnight to 9:29 AM EST
    overnight_start = dt_time(0, 0)
    overnight_end = dt_time(9, 29)

    day_htf = [b for b in htf_bars if to_est(b.timestamp).date() == target_date
               and overnight_start <= to_est(b.timestamp).time() <= overnight_end]
    day_mtf = [b for b in mtf_bars if to_est(b.timestamp).date() == target_date
               and overnight_start <= to_est(b.timestamp).time() <= overnight_end]
    day_ltf = day_mtf

    print(f'Overnight (00:00-09:29 EST): HTF={len(day_htf)}, MTF={len(day_mtf)}')

    if day_mtf:
        print(f'First bar: {to_est(day_mtf[0].timestamp).strftime("%H:%M")} EST, Close={day_mtf[0].close}')
        print(f'Last bar: {to_est(day_mtf[-1].timestamp).strftime("%H:%M")} EST, Close={day_mtf[-1].close}')
        high = max(b.high for b in day_mtf)
        low = min(b.low for b in day_mtf)
        print(f'Session High: {high}, Low: {low}')
    print()

    if not day_htf:
        print('No overnight data found')
        return

    lookback_htf = [b for b in htf_bars if b.timestamp < day_htf[0].timestamp][-100:]
    lookback_mtf = [b for b in mtf_bars if b.timestamp < day_mtf[0].timestamp][-200:]
    lookback_ltf = lookback_mtf

    base_config = {
        'symbol': symbol, 'tick_size': tick_size, 'tick_value': tick_value,
        'swing_lookback': 20, 'swing_strength': 3, 'min_sweep_ticks': 2,
        'max_sweep_ticks': 50, 'displacement_multiplier': 2.0, 'avg_body_lookback': 20,
        'min_fvg_ticks': 3, 'max_fvg_age_bars': 50, 'mss_lookback': 20,
        'mss_swing_strength': 1, 'stop_buffer_ticks': 2, 'max_risk_ticks': 80,
        'allow_lunch': False, 'require_killzone': False, 'max_daily_trades': 5,
        'max_daily_losses': 2, 'use_mtf_for_fvg': True, 'entry_on_mitigation': True,
        'stop_buffer_pts': 2.0,
    }

    # Without trend filter
    config_no = base_config.copy()
    config_no['use_trend_filter'] = False
    trades_no = run_backtest(config_no, day_htf, day_mtf, day_ltf,
                              lookback_htf, lookback_mtf, lookback_ltf,
                              tick_size, tick_value, contracts)

    # With trend filter
    config_with = base_config.copy()
    config_with['use_trend_filter'] = True
    config_with['ema_fast_period'] = 20
    config_with['ema_slow_period'] = 50
    trades_with = run_backtest(config_with, day_htf, day_mtf, day_ltf,
                                lookback_htf, lookback_mtf, lookback_ltf,
                                tick_size, tick_value, contracts)

    print('=' * 100)
    print('ES ICT SWEEP - 2026-02-12 OVERNIGHT (00:00-09:29 EST)')
    print('=' * 100)
    print()
    print(f"{'WITHOUT TREND FILTER':<50} | {'WITH TREND FILTER (3m EMA20/50)':<50}")
    print('-' * 100)

    max_len = max(len(trades_no), len(trades_with), 1)
    for i in range(max_len):
        left, right = '', ''
        if i < len(trades_no):
            t = trades_no[i]
            trade = t['trade']
            r = t['result']
            est = to_est(trade.timestamp).strftime('%H:%M')
            emoji = 'W' if r['pnl'] > 0 else 'L'
            left = f"{emoji} {est} {trade.direction:<6} {r['result']:<6} ${r['pnl']:>+9,.0f}"
        if i < len(trades_with):
            t = trades_with[i]
            trade = t['trade']
            r = t['result']
            est = to_est(trade.timestamp).strftime('%H:%M')
            emoji = 'W' if r['pnl'] > 0 else 'L'
            right = f"{emoji} {est} {trade.direction:<6} {r['result']:<6} ${r['pnl']:>+9,.0f}"
        print(f"{left:<50} | {right:<50}")

    print('-' * 100)

    def stats(trades):
        if not trades:
            return 0, 0, 0, 0, 0
        pnl = sum(t['result']['pnl'] for t in trades)
        w = sum(1 for t in trades if t['result']['pnl'] > 0)
        l = sum(1 for t in trades if t['result']['pnl'] < 0)
        wr = (w / len(trades) * 100)
        return len(trades), w, l, wr, pnl

    s1, s2 = stats(trades_no), stats(trades_with)

    print()
    print(f"{'Trades: %d, Wins: %d, Losses: %d' % (s1[0], s1[1], s1[2]):<50} | "
          f"{'Trades: %d, Wins: %d, Losses: %d' % (s2[0], s2[1], s2[2]):<50}")
    print(f"{'Win Rate: %.0f%%, P/L: $%.0f' % (s1[3], s1[4]):<50} | "
          f"{'Win Rate: %.0f%%, P/L: $%.0f' % (s2[3], s2[4]):<50}")
    print('=' * 100)

    # Show trade details
    print()
    print('TRADE DETAILS (Without Filter):')
    for i, t in enumerate(trades_no, 1):
        trade = t['trade']
        r = t['result']
        est = to_est(trade.timestamp).strftime('%H:%M')
        print(f"  {i}. {est} EST {trade.direction} @ {trade.entry_price:.2f}")
        print(f"     Stop: {trade.stop_price:.2f}, Target: {trade.t2_price:.2f}")
        print(f"     Exit: {r['exit']:.2f} ({r['result']}) -> ${r['pnl']:+,.0f}")


if __name__ == '__main__':
    main()
