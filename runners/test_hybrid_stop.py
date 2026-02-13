"""Test Option 7 - Hybrid Stop (tighter of wick vs FVG boundary)"""
import sys
sys.path.insert(0, '.')
from datetime import date, time as dt_time
from runners.tradingview_loader import fetch_futures_bars

tick_size = 0.25
tick_value = 12.50
contracts = 3

def is_swing_low(bars, idx, lookback=2):
    if idx < lookback or idx >= len(bars) - lookback:
        return False
    bar_low = bars[idx].low
    for i in range(1, lookback + 1):
        if bar_low >= bars[idx - i].low or bar_low >= bars[idx + i].low:
            return False
    return True

def is_swing_high(bars, idx, lookback=2):
    if idx < lookback or idx >= len(bars) - lookback:
        return False
    bar_high = bars[idx].high
    for i in range(1, lookback + 1):
        if bar_high <= bars[idx - i].high or bar_high <= bars[idx + i].high:
            return False
    return True

def simulate_trade(session_bars, entry_idx, direction, entry_price, stop_price):
    is_long = direction == "LONG"
    risk = abs(entry_price - stop_price)
    target_4r = entry_price + (4 * risk) if is_long else entry_price - (4 * risk)
    target_8r = entry_price + (8 * risk) if is_long else entry_price - (8 * risk)

    touched_4r = False
    touched_8r = False
    t1_exited = False
    t2_exited = False
    t1_trail = stop_price
    t2_trail = entry_price + (4 * risk) if is_long else entry_price - (4 * risk)
    runner_trail = t2_trail
    remaining = contracts
    exits = []

    for i in range(entry_idx + 1, len(session_bars)):
        bar = session_bars[i]

        if touched_4r and not t1_exited:
            check_idx = i - 2
            if check_idx > entry_idx:
                if is_long and is_swing_low(session_bars, check_idx, 2):
                    swing = session_bars[check_idx].low
                    new_trail = swing - (2 * tick_size)
                    if new_trail > t1_trail:
                        t1_trail = new_trail
                elif not is_long and is_swing_high(session_bars, check_idx, 2):
                    swing = session_bars[check_idx].high
                    new_trail = swing + (2 * tick_size)
                    if new_trail < t1_trail:
                        t1_trail = new_trail

        if touched_8r:
            check_idx = i - 2
            if check_idx > entry_idx:
                if is_long and is_swing_low(session_bars, check_idx, 2):
                    swing = session_bars[check_idx].low
                    new_t2 = swing - (4 * tick_size)
                    new_runner = swing - (6 * tick_size)
                    if new_t2 > t2_trail:
                        t2_trail = new_t2
                    if new_runner > runner_trail:
                        runner_trail = new_runner
                elif not is_long and is_swing_high(session_bars, check_idx, 2):
                    swing = session_bars[check_idx].high
                    new_t2 = swing + (4 * tick_size)
                    new_runner = swing + (6 * tick_size)
                    if new_t2 < t2_trail:
                        t2_trail = new_t2
                    if new_runner < runner_trail:
                        runner_trail = new_runner

        # Check 4R
        if not touched_4r:
            if (is_long and bar.high >= target_4r) or (not is_long and bar.low <= target_4r):
                touched_4r = True
                t1_trail = entry_price
                pnl = (target_4r - entry_price) if is_long else (entry_price - target_4r)
                exits.append({"type": "4R", "pnl": pnl, "cts": 1})
                t1_exited = True
                remaining -= 1

        # Check 8R
        if touched_4r and not touched_8r:
            if (is_long and bar.high >= target_8r) or (not is_long and bar.low <= target_8r):
                touched_8r = True
                t2_trail = target_4r
                runner_trail = target_4r

        # Check initial stop
        if not touched_4r and remaining > 0:
            if (is_long and bar.low <= stop_price) or (not is_long and bar.high >= stop_price):
                pnl = (stop_price - entry_price) * remaining if is_long else (entry_price - stop_price) * remaining
                exits.append({"type": "STOP", "pnl": pnl, "cts": remaining})
                remaining = 0
                break

        # Check trail after 4R
        if touched_4r and not touched_8r and remaining > 0:
            if (is_long and bar.low <= t1_trail) or (not is_long and bar.high >= t1_trail):
                pnl = (t1_trail - entry_price) * remaining if is_long else (entry_price - t1_trail) * remaining
                exits.append({"type": "TRAIL", "pnl": pnl, "cts": remaining})
                t2_exited = True
                remaining = 0
                break

        # Check T2/Runner after 8R
        if touched_8r and remaining > 0:
            if not t2_exited and remaining > 1:
                if (is_long and bar.low <= t2_trail) or (not is_long and bar.high >= t2_trail):
                    pnl = (t2_trail - entry_price) if is_long else (entry_price - t2_trail)
                    exits.append({"type": "T2", "pnl": pnl, "cts": 1})
                    t2_exited = True
                    remaining -= 1
            if t2_exited and remaining > 0:
                if (is_long and bar.low <= runner_trail) or (not is_long and bar.high >= runner_trail):
                    pnl = (runner_trail - entry_price) * remaining if is_long else (entry_price - runner_trail) * remaining
                    exits.append({"type": "RUNNER", "pnl": pnl, "cts": remaining})
                    remaining = 0
                    break

    # EOD exit
    if remaining > 0:
        last_bar = session_bars[-1]
        pnl = (last_bar.close - entry_price) * remaining if is_long else (entry_price - last_bar.close) * remaining
        exits.append({"type": "EOD", "pnl": pnl, "cts": remaining})

    total_pnl = sum(e["pnl"] for e in exits)
    total_dollars = (total_pnl / tick_size) * tick_value
    return total_dollars, exits


def main():
    print("Fetching ES data...")
    bars = fetch_futures_bars("ES", interval="3m", n_bars=3000)

    # Feb 3 trades
    print("=" * 70)
    print("FEB 3, 2026 - OPTION 7 HYBRID STOP TEST")
    print("=" * 70)

    day_bars = [b for b in bars if b.timestamp.date() == date(2026, 2, 3)]
    session_bars = [b for b in day_bars if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]

    trades_feb3 = [
        {"time": "09:30", "dir": "SHORT", "entry": 7007.75, "wick": 7017.50, "fvg_h": 7019.25, "fvg_l": 7015.00},
        {"time": "09:39", "dir": "SHORT", "entry": 7007.00, "wick": 7011.00, "fvg_h": 7011.25, "fvg_l": 7010.50},
        {"time": "15:36", "dir": "LONG", "entry": 6938.00, "wick": 6931.25, "fvg_h": 6933.75, "fvg_l": 6933.25},
    ]

    total_curr_feb3 = 0
    total_hyb_feb3 = 0

    for t in trades_feb3:
        is_long = t["dir"] == "LONG"
        if is_long:
            fvg_stop = t["fvg_l"] - 0.5
            hybrid_stop = max(t["wick"], fvg_stop)  # Higher = tighter for LONG
        else:
            fvg_stop = t["fvg_h"] + 0.5
            hybrid_stop = min(t["wick"], fvg_stop)  # Lower = tighter for SHORT

        # Find entry bar
        entry_idx = None
        th, tm = int(t["time"].split(":")[0]), int(t["time"].split(":")[1])
        for i, bar in enumerate(session_bars):
            if bar.timestamp.hour == th and abs(bar.timestamp.minute - tm) <= 3:
                entry_idx = i
                break

        if entry_idx is None:
            print(f"Could not find entry bar for {t['time']}")
            continue

        curr_pnl, _ = simulate_trade(session_bars, entry_idx, t["dir"], t["entry"], t["wick"])
        hyb_pnl, _ = simulate_trade(session_bars, entry_idx, t["dir"], t["entry"], hybrid_stop)

        total_curr_feb3 += curr_pnl
        total_hyb_feb3 += hyb_pnl

        wick_risk = abs(t["entry"] - t["wick"])
        hyb_risk = abs(t["entry"] - hybrid_stop)

        print(f"\n{t['dir']} @ {t['time']}")
        print(f"  Wick Stop: {t['wick']:.2f} (risk: {wick_risk:.2f} pts)")
        print(f"  FVG Stop:  {fvg_stop:.2f}")
        print(f"  HYBRID:    {hybrid_stop:.2f} (risk: {hyb_risk:.2f} pts) <- TIGHTER")
        print(f"  Current P/L: ${curr_pnl:+,.2f}")
        print(f"  Hybrid P/L:  ${hyb_pnl:+,.2f}")
        print(f"  Diff:        ${hyb_pnl - curr_pnl:+,.2f}")

    print(f"\nFEB 3 TOTAL: Current ${total_curr_feb3:+,.2f} | Hybrid ${total_hyb_feb3:+,.2f} | Diff ${total_hyb_feb3 - total_curr_feb3:+,.2f}")

    # Feb 4 trades
    print("\n" + "=" * 70)
    print("FEB 4, 2026 - OPTION 7 HYBRID STOP TEST")
    print("=" * 70)

    day_bars = [b for b in bars if b.timestamp.date() == date(2026, 2, 4)]
    session_bars = [b for b in day_bars if dt_time(4, 0) <= b.timestamp.time() <= dt_time(16, 0)]

    trades_feb4 = [
        {"time": "09:36", "dir": "SHORT", "entry": 6949.50, "wick": 6957.00, "fvg_h": 6956.00, "fvg_l": 6954.75},
    ]

    total_curr_feb4 = 0
    total_hyb_feb4 = 0

    for t in trades_feb4:
        fvg_stop = t["fvg_h"] + 0.5
        hybrid_stop = min(t["wick"], fvg_stop)  # Lower = tighter for SHORT

        # Find entry bar
        entry_idx = None
        th, tm = int(t["time"].split(":")[0]), int(t["time"].split(":")[1])
        for i, bar in enumerate(session_bars):
            if bar.timestamp.hour == th and abs(bar.timestamp.minute - tm) <= 3:
                entry_idx = i
                break

        if entry_idx is None:
            print(f"Could not find entry bar for {t['time']}")
            continue

        curr_pnl, _ = simulate_trade(session_bars, entry_idx, t["dir"], t["entry"], t["wick"])
        hyb_pnl, _ = simulate_trade(session_bars, entry_idx, t["dir"], t["entry"], hybrid_stop)

        total_curr_feb4 += curr_pnl
        total_hyb_feb4 += hyb_pnl

        wick_risk = abs(t["entry"] - t["wick"])
        hyb_risk = abs(t["entry"] - hybrid_stop)

        print(f"\n{t['dir']} @ {t['time']}")
        print(f"  Wick Stop: {t['wick']:.2f} (risk: {wick_risk:.2f} pts)")
        print(f"  FVG Stop:  {fvg_stop:.2f}")
        print(f"  HYBRID:    {hybrid_stop:.2f} (risk: {hyb_risk:.2f} pts) <- TIGHTER")
        print(f"  Current P/L: ${curr_pnl:+,.2f}")
        print(f"  Hybrid P/L:  ${hyb_pnl:+,.2f}")
        print(f"  Diff:        ${hyb_pnl - curr_pnl:+,.2f}")

    print(f"\nFEB 4 TOTAL: Current ${total_curr_feb4:+,.2f} | Hybrid ${total_hyb_feb4:+,.2f} | Diff ${total_hyb_feb4 - total_curr_feb4:+,.2f}")

    # Combined
    print("\n" + "=" * 70)
    print("COMBINED 2-DAY SUMMARY")
    print("=" * 70)
    total_curr = total_curr_feb3 + total_curr_feb4
    total_hyb = total_hyb_feb3 + total_hyb_feb4
    print(f"Current Strategy:  ${total_curr:+,.2f}")
    print(f"HYBRID (Option 7): ${total_hyb:+,.2f}")
    print(f"Net Difference:    ${total_hyb - total_curr:+,.2f}")


if __name__ == "__main__":
    main()
