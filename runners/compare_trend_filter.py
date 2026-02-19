"""Compare ICT Sweep with and without trend filter."""
import sys
sys.path.insert(0, '.')
from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars
from strategies.ict_sweep.strategy import ICTSweepStrategy, TradeSetup


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
    ltf_bars = mtf_bars

    target_date = date(2026, 2, 12)
    session_start = dt_time(9, 30)
    session_end = dt_time(16, 0)

    day_htf = [b for b in htf_bars if b.timestamp.date() == target_date
               and session_start <= b.timestamp.time() <= session_end]
    day_mtf = [b for b in mtf_bars if b.timestamp.date() == target_date
               and session_start <= b.timestamp.time() <= session_end]
    day_ltf = day_mtf

    lookback_htf = [b for b in htf_bars if b.timestamp.date() < target_date][-50:]
    lookback_mtf = [b for b in mtf_bars if b.timestamp.date() < target_date][-100:]
    lookback_ltf = [b for b in ltf_bars if b.timestamp.date() < target_date][-50:]

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

    # Run without trend filter
    config_no_filter = base_config.copy()
    config_no_filter['use_trend_filter'] = False
    trades_no_filter = run_backtest(config_no_filter, day_htf, day_mtf, day_ltf,
                                     lookback_htf, lookback_mtf, lookback_ltf,
                                     tick_size, tick_value, contracts)

    # Run with trend filter
    config_with_filter = base_config.copy()
    config_with_filter['use_trend_filter'] = True
    config_with_filter['ema_fast_period'] = 20
    config_with_filter['ema_slow_period'] = 50
    trades_with_filter = run_backtest(config_with_filter, day_htf, day_mtf, day_ltf,
                                       lookback_htf, lookback_mtf, lookback_ltf,
                                       tick_size, tick_value, contracts)

    print()
    print('=' * 100)
    print(f'ES ICT SWEEP COMPARISON - {target_date}')
    print('=' * 100)
    print()
    print(f"{'WITHOUT TREND FILTER':<50} | {'WITH TREND FILTER (EMA20/50)':<50}")
    print('-' * 100)

    max_len = max(len(trades_no_filter), len(trades_with_filter))

    for i in range(max_len):
        left = ''
        right = ''

        if i < len(trades_no_filter):
            t = trades_no_filter[i]
            trade = t['trade']
            r = t['result']
            emoji = 'W' if r['pnl'] > 0 else 'L'
            left = f"{emoji} {trade.timestamp.strftime('%H:%M')} {trade.direction:<5} {r['result']:<6} ${r['pnl']:>+10,.0f}"

        if i < len(trades_with_filter):
            t = trades_with_filter[i]
            trade = t['trade']
            r = t['result']
            emoji = 'W' if r['pnl'] > 0 else 'L'
            right = f"{emoji} {trade.timestamp.strftime('%H:%M')} {trade.direction:<5} {r['result']:<6} ${r['pnl']:>+10,.0f}"

        print(f"{left:<50} | {right:<50}")

    print('-' * 100)

    def calc_stats(trades):
        total_pnl = sum(t['result']['pnl'] for t in trades)
        wins = sum(1 for t in trades if t['result']['pnl'] > 0)
        losses = sum(1 for t in trades if t['result']['pnl'] < 0)
        win_rate = (wins / len(trades) * 100) if trades else 0
        return len(trades), wins, losses, win_rate, total_pnl

    stats_no = calc_stats(trades_no_filter)
    stats_with = calc_stats(trades_with_filter)

    print()
    print(f"{'SUMMARY':<50} | {'SUMMARY':<50}")
    print(f"{'Trades: ' + str(stats_no[0]):<50} | {'Trades: ' + str(stats_with[0]):<50}")
    print(f"{'Wins: ' + str(stats_no[1]):<50} | {'Wins: ' + str(stats_with[1]):<50}")
    print(f"{'Losses: ' + str(stats_no[2]):<50} | {'Losses: ' + str(stats_with[2]):<50}")
    print(f"{'Win Rate: ' + f'{stats_no[3]:.0f}%':<50} | {'Win Rate: ' + f'{stats_with[3]:.0f}%':<50}")
    print(f"{'P/L: $' + f'{stats_no[4]:+,.2f}':<50} | {'P/L: $' + f'{stats_with[4]:+,.2f}':<50}")
    print('=' * 100)

    # Show filtered trade
    print()
    print('FILTERED TRADE (counter-trend):')
    for t in trades_no_filter:
        trade = t['trade']
        in_filtered = not any(tf['trade'].timestamp == trade.timestamp for tf in trades_with_filter)
        if in_filtered:
            print(f"  {trade.timestamp.strftime('%H:%M')} {trade.direction} @ {trade.entry_price:.2f}")
            print(f"    Result: {t['result']['result']} -> ${t['result']['pnl']:+,.0f}")
            print("    ^ FILTERED: Counter-trend (EMA20 < EMA50 = bearish, trade was BULLISH)")


if __name__ == '__main__':
    main()
