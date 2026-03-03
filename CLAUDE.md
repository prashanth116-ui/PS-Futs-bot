# Project Instructions

## On Session Start
Run the health check script at the beginning of each session:
```
python health_check.py
```

## CRITICAL: No Deploys During Market Hours
**NEVER deploy code or restart the paper-trading service during market hours (04:00-16:30 ET Mon-Fri) without explicit user confirmation.** Mid-session restarts kill open trades and wipe trading history. Always deploy before 04:00 ET or after 16:30 ET. If a deploy is urgently needed during market hours, ALERT the user with a clear warning about the impact before proceeding.

## Important: Data Verification
**ALWAYS verify numerical data before making claims about prices.** Do NOT rely on visual interpretation of chart images. The backtest and plot scripts now print RTH key levels:
```
RTH: Open=6856.25 High=6965.50 Low=6850.25
```
Use these printed values, not the chart image, to reference price levels.

## Project Overview
Tradovate futures trading bot using ICT (Inner Circle Trader) strategy.

## Current Strategy: V10.16 (Trail Improvement) - Mar 3, 2026

### Supported Instruments
| Symbol | Type | Tick Value | Min Risk | Max BOS Risk | Max Retrace Risk | BOS Enabled | Consec Stop | Trail Trigger | T2 Exit |
|--------|------|------------|----------|--------------|------------------|-------------|-------------|---------------|---------|
| ES | E-mini S&P 500 | $12.50 | 1.5 pts | 8.0 pts | **8.0 pts (1-ct)** | **OFF** | **2/symbol** | **4R** | **Fixed 5R** |
| NQ | E-mini Nasdaq | $5.00 | 6.0 pts | 20.0 pts | None | ON (loss limit) | **3/symbol** | **4R** | Trail |
| MES | Micro E-mini S&P | $1.25 | 1.5 pts | 8.0 pts | **8.0 pts (1-ct)** | **OFF** | **2/symbol** | **4R** | **Fixed 5R** |
| MNQ | Micro E-mini Nasdaq | $0.50 | 6.0 pts | 20.0 pts | None | ON (loss limit) | **3/symbol** | **4R** | Trail |
| SPY | S&P 500 ETF | per share | $0.30 | - | - | **OFF** | OFF | 4R | Fixed 5R |
| QQQ | Nasdaq 100 ETF | per share | $0.50 | - | - | ON (loss limit) | OFF | 4R | Trail |

**Note:** MES/MNQ use same point-based parameters as ES/NQ (1/10th tick value only).

### V10.6 BOS LOSS_LIMIT Strategy
Per-symbol BOS optimization with daily loss limit:
- **ES/MES/SPY**: BOS disabled entirely (low win rate: 20-38%)
- **NQ/MNQ/QQQ**: BOS enabled with 1 loss/day limit
  - Take first BOS entry of the day
  - If it loses → disable BOS for rest of day
  - If it wins → continue taking BOS entries

**Result**: +$1.2k P/L improvement, -$500 drawdown, 64% BOS win rate (up from 47.5%)

**12-Day A/B Validation (Feb 17, 2026):**
| Config | Trades | Wins | Losses | Win Rate | Total P/L |
|--------|--------|------|--------|----------|-----------|
| **ES BOS OFF** | **126** | **113** | **13** | **89.7%** | **+$124,881** |
| ES BOS ON | 135 | 111 | 24 | 82.2% | +$118,406 |

BOS ON added 15 BOS trades — net -$6,475 drag. BOS OFF confirmed superior for ES.

### V10.11 Retrace Risk Cap (Feb 20, 2026)
When retrace entries (B1/B2) exceed `max_retrace_risk_pts`, force contracts to 1 instead of skipping entirely. Preserves optionality while capping damage on oversized retraces.

- **ES/MES**: Cap at 8.0 pts — retrace risk above this → 1 contract (instead of 3 or 2)
- **NQ/MNQ**: No cap — NQ retraces with wide risk catch big trend moves and win big

**15-Day A/B Validation (ES):**
| Config | Trades | WR | Total P/L | Retrace P/L |
|--------|--------|-----|-----------|-------------|
| **WITH cap (8.0)** | **154** | **86.4%** | **$+145,825** | **$+963** |
| WITHOUT cap | 154 | 86.4% | $+144,613 | $-250 |

The 24.25pt intraday retrace loss was cut from -$2,425 to -$1,212.50 (1 contract instead of 2).

**Why NQ has no cap**: 15-day A/B showed cap costs -$18,590 on NQ — 5 of 6 retraces exceeded 20pts, but 3 were big winners (one Feb 4 trade: +$21,540 uncapped vs +$3,600 capped).

### V10.10 Bug Fixes (Feb 17, 2026)

**Direction-Aware Circuit Breaker:**
- Old: Global loss counter — 2 short losses would block ALL entries (including longs)
- New: Per-direction loss tracking — short losses only disable shorts, long losses only disable longs
- Limit: 3 losses per direction per day (futures and equity)

**Entry Cap Fix:**
- Removed `entries_taken` lifetime counter that conflated concurrent open trade limit with total daily entries per direction
- Previously, after 2-3 entries in one direction, no more entries could fire even if positions had closed
- Now entries are only limited by concurrent open positions (`max_open_trades=3`)

**Equity FVG Date Filter:**
- Fixed stale FVG bug in `run_v10_equity.py` — old FVGs from previous sessions (weeks ago) were triggering entries at wrong prices
- Added `session_date` filter to skip FVGs not created on the current trading day

**Runner/Plot BOS Parity:**
- Added `disable_bos_retrace`, `bos_daily_loss_limit`, `high_displacement_override` to runner and multiday backtest
- Previously only the plot had V10.6 BOS per-symbol settings — runner was running BOS ON for all symbols

**Telegram Heartbeat:**
- Changed from every 30 minutes to every 1 hour

### V10.7 Entry Types
| Type | Name | Description |
|------|------|-------------|
| A | Creation | Enter immediately when FVG forms with displacement **(3x override skips ADX)** |
| B1 | Overnight Retrace | Enter when price retraces into overnight FVG + rejection **(ADX >= 22)** |
| B2 | Intraday Retrace | Enter when price retraces into session FVG **(2+ bars old)** + rejection **[Disabled for SPY]** |
| C | BOS + Retrace | Enter when price retraces into FVG after BOS **[Per-symbol control with loss limit]** |

### Hybrid Exit Structure (Dynamic Sizing + R-Target Tuning)

**ES/MES (T2 fixed at 5R):**
```
Entry: Dynamic contracts at FVG midpoint
  - 1st trade of direction: 3 contracts (1 T1 + 1 T2 + 1 Runner)
  - 2nd/3rd trade: 2 contracts (1 T1 + 1 T2, no runner)
    ↓ Price hits 3R target
T1 (1 ct): FIXED profit at 3R - guaranteed
    ↓ Price hits 4R target (V10.16: lowered from 6R)
  Trail activates — remaining contracts structure trail with 3R floor
    ↓ Price hits 5R target (V10.16: T2 fixed exit for ES/MES)
T2 (1 ct): FIXED profit at 5R - guaranteed, locked in
    ↓ Only Runner remains, structure trailing with 6-tick buffer
Runner (1 ct): Exits on trail stop or EOD (1st trade only)
```

**NQ/MNQ (T2 trails, no fixed exit):**
```
Entry: Dynamic contracts at FVG midpoint
  - 1st trade of direction: 3 contracts (1 T1 + 1 T2 + 1 Runner)
  - 2nd/3rd trade: 2 contracts (1 T1 + 1 T2, no runner)
    ↓ Price hits 3R target
T1 (1 ct): FIXED profit at 3R - guaranteed
    ↓ Price hits 4R target (V10.16: lowered from 6R)
  Trail activates — T2 and Runner structure trail with 3R floor
    ↓ T2 trails with 4-tick buffer, Runner trails with 6-tick buffer
T2/Runner ride big NQ trends until trail stop or EOD
```

**R-Target CLI flags** (all runners support `--t1-r=N --trail-r=N --t2-fixed-r=N`):
```bash
# Default (V10.16): T1=3R, Trail=4R, T2 fixed at 5R for ES/MES
python -m runners.backtest_v10_multiday ES 22

# Override to old V10.9 baseline
python -m runners.backtest_v10_multiday ES 22 --trail-r=6 --t2-fixed-r=0

# A/B test trail options
python -m runners.backtest_v10_multiday ES 18 --post-t1-trail-r=1      # Trail at +1R after T1
python -m runners.backtest_v10_multiday ES 18 --time-decay-bars=10 --time-decay-r=2  # Time decay
```

### V10.8 Hybrid Filter System
Separates filters into mandatory (must pass) and optional (2/3 must pass):

**MANDATORY (must pass):**
1. **DI Direction**: +DI > -DI for LONG, -DI > +DI for SHORT
2. **FVG Size**: >= 5 ticks (futures) or min size (equities)

**OPTIONAL (2 of 3 must pass):**
3. **Displacement**: >= 1.0x average body
4. **ADX**: >= 11 (or >= 10 with 3x displacement override)
5. **EMA Trend**: EMA20 > EMA50 for LONG, EMA20 < EMA50 for SHORT

**Result**: +$90k P/L improvement over 30 days, +71% more trades, same win rate

**Implementation (Feb 10, 2026 Audit):**
All 8 entry types now have consistent hybrid filters:
- **Futures (3 entries)**: Creation, Retrace, BOS in `run_v10_dual_entry.py`
- **Equities (5 entries)**: Creation, Overnight, Intraday, BOS LONG, BOS SHORT in `run_v10_equity.py`

Fixes applied:
- Added explicit FVG size check to futures Retrace entry (L548-551)
- Added full hybrid filter blocks to equity BOS LONG (L509-529) and BOS SHORT (L578-598)
- Added full hybrid filter block to equity Intraday entry (L421-441)
- Added FVG size checks to equity Creation (L261-263) and Overnight (L335-337)

### V10.9 R-Target Tuning (A/B Test Results)
Lowered T1 exit from 4R to 3R and trail activation from 8R to 6R.

**A/B Test (11 days, ES + NQ):**
| Config | T1/Trail | Total P/L | Win Rate | Max DD | Win Days |
|--------|----------|-----------|----------|--------|----------|
| 4R/8R (old) | 4R/8R | $142,034 | 74.5% | $1,319 | 9/11 |
| **3R/6R (new)** | **3R/6R** | **$179,358** | **90.6%** | **$0** | **11/11** |
| 4R/6R | 4R/6R | $138,024 | 74.5% | $975 | 10/11 |
| 5R/10R | 5R/10R | $146,940 | 70.0% | $975 | 9/11 |

**15-Day Validation (ES + NQ):**
| Config | Total P/L | Win Rate | Max DD | Day Win Rate |
|--------|-----------|----------|--------|-------------|
| **3R/6R (new)** | **$200,533** | **87.7%** | **$0** | **100% (15/15)** |
| 4R/8R (old) | $153,275 | 69.2% | $1,319 | 73.3% (11/15) |

**Result**: +$47k P/L improvement (+31%), +18.5% win rate, zero drawdown

**Why it works**: Lower 3R T1 locks profit before most pullbacks. Narrower gap between T1 (3R) and trail activation (6R) means fewer trades get caught in the dead zone where they gave back gains.

### EOD Next-Day Outlook Alert (Feb 20, 2026)
Telegram alert sent at market close (ES only, NQ to be enabled later).

**Conviction scoring** synthesizes 4 signals into one line:
| Signal | Bearish | Bullish |
|--------|---------|---------|
| Pivot Bias | Close < next day pivot | Close > next day pivot |
| Close Position | Lower quartile (<25%) | Upper quartile (>=75%) |
| CPR Width | Narrow (<5 pts ES) | Narrow (<5 pts ES) |
| Volume | Above 5-day avg (>=1.2x) | Above 5-day avg (>=1.2x) |

**Conviction levels**: 2+ signals = HIGH CONVICTION, 1 signal = LEAN, conflicting = MIXED

**CPR context**: Narrow CPR + prior day <80% ATR = "coiling" (breakout likely). Narrow + expanded prior day = less reliable.

**Alert contents**:
- Conviction summary (HIGH/LEAN/MIXED + direction + reasons)
- Volume vs 5-day average (confirms/denies move)
- CPR: Pivot, TC, BC, width with coiling context
- R1/S1 pivot levels
- 5-day ATR + prior day range as % of ATR
- Key levels: prior day H/L/C

**Implementation**: `_calculate_next_day_outlook()` in `LiveTrader`, called from `_print_summary()` after daily summary. Uses `fetch_futures_bars(symbol, interval='1d', n_bars=15)` for daily data.

### V10.11 Startup Data Lag Fix (Feb 23, 2026)
Live bot had a 57-minute data lag at market open — waited for 20 session bars (20 × 3min = 60min) before trading because it discarded yesterday's data.

**Root cause**: `_scan_futures_symbol()` and `_scan_equity_symbol()` used `fetch_futures_bars()` (live only) and filtered to today's session bars. At 04:00 ET, session bars = 0. Indicators (EMA 20/50, ADX 14) couldn't calculate until 20+ bars accumulated.

**Fix**: Replaced `fetch_futures_bars()` with `load_bars_with_history()` which merges local stored bars (yesterday's 130+ bars from CSV) with today's live data. Lowered session bar gate from 20 to 1.

**Result**: Bot starts trading at 04:03 ET (first candle close) instead of ~05:00 ET. On Feb 23, this would have captured 3 early winning trades worth +$1,537.50 that the old bot missed.

**Note**: Backtest and live bot will still diverge due to real-time vs post-session bar construction, but the 57-min blind spot is eliminated.

### V10.13 Global Consecutive Loss Stop (Feb 24, 2026)
After investigating Feb 19 (worst bot day: -$5,562.50, 11 losses), added a global consecutive loss counter that stops all trading for the day after 2 consecutive losses. Applied to ES/MES only — NQ consecutive losses often precede big trend recoveries.

**How it works:**
- Counter increments on any losing trade (regardless of direction)
- Counter resets to 0 on any winning trade
- When counter >= 2: all entries disabled for rest of day
- Resets daily

**Why global (not per-direction):** Feb 19 losses alternated directions (SHORT, LONG, SHORT, LONG). Per-direction counters never reach 2 because each direction only sees 1 consecutive loss.

**Why ES/MES only:** On NQ Feb 12, 2 consecutive losses at 10:06/10:18 were followed by +$30k in winners ($6,675 + $5,970 + $17,412). Applying to NQ would cost -$29,228 over 17 days.

**17-Day A/B Validation (ES):**
| Config | Trades | Wins | Losses | Win Rate | Total P/L | Feb 19 |
|--------|--------|------|--------|----------|-----------|--------|
| **WITH 2-consec stop** | **178** | **156** | **22** | **87.6%** | **+$161,194** | **-$412** |
| WITHOUT (baseline) | 180 | 156 | 24 | **86.7%** | +$160,706 | -$900 |

**Result**: +$488 improvement, zero harm to any winning day, Feb 19 loss cut from -$900 to -$412.

### V10.12 Backtest Parity Fixes (Feb 24, 2026)
Live bot P/L diverged from backtest by ~$1,231 (11%) on Feb 24. Root cause: trail logic and parameter mismatches between `run_live.py` and `run_v10_dual_entry.py`.

**Trail logic fixes (biggest impact — ~$850 recovered):**
- Added `last_swing` gate to T1/T2/Runner trail updates — live bot was accepting any improving swing; backtest requires swing beyond previous
- Changed trail scan from 3-bar loop to single bar at `i-2` (matching backtest's `check_idx = i - 2`)
- Increased bar fetch from 10 to 20 for swing detection context
- Initialize `last_swing` at entry price on trade open, T1 hit (breakeven), and 6R touch (current bar high/low)

**Parameter parity:**
- Fixed `retracement_morning_only=True` → `False` (was blocking overnight retrace entries after noon; backtest allows all day)
- Made all `run_session_v10()` params explicit: `max_open_trades=3`, `overnight_retrace_min_adx=22`, `high_displacement_override=3.0`, `t1_r_target=3`, `trail_r_trigger=6`

**Risk manager parity:**
- Added `record_trade_entry()` in paper mode (was never called — risk manager saw 0 open trades)
- Added `record_trade_exit()` on paper trade close (risk manager now tracks P/L, consecutive losses, open positions)

**Result**: Estimated gap reduction from ~11% to ~2-3% (remaining gap is inherent real-time vs post-session bar data).

**Additional parity fix (Feb 26, 2026):**
- Fixed `retracement_morning_only=True` → `False` in `backtest_v10_multiday.py:109` (was mismatched with `run_live.py:520` which uses `False`)
- Added `--verbose` / `-v` flag to multiday backtest for per-trade output (enables trade-by-trade comparison with live logs)

**Feb 25 Divergence Analysis (Live +$3,131 vs Backtest +$5,631 = $2,500 gap):**

| # | Live Runner | Backtest | Notes |
|---|-------------|----------|-------|
| 1 | CREATION 07:21 @ 6924.75, STOP -$375 | CREATION 07:21 @ 6924.62, STOP -$356 | Entry price differs (real-time vs finalized FVG midpoint) |
| 2 | CREATION 08:58 @ 6926.38, +$731 | *(not present)* | Live-only: real-time bars produced FVG that finalized bars didn't |
| 3 | CREATION 09:34 @ 6933.62, +$731 | CREATION 09:33 @ 6933.62, +$731 | Match |
| 4 | CREATION 09:49 @ 6942.25, T1 only +$338 | CREATION 09:48 @ 6942.25, T1 only +$338 | Match |
| 5 | INTRADAY 10:10 @ 6935.25, STOP -$488 | *(not present)* | Live-only: different FVG from real-time bars |
| 6 | CREATION 11:02 @ 6935.38, +$2,194 | CREATION 11:00 @ 6935.38, +$2,194 | Match |
| - | *(not present)* | CREATION 11:27 @ 6940.50, +$1,188 | Backtest-only |
| - | *(not present)* | INTRADAY 11:18 @ 6938.75, +$1,538 | Backtest-only |

**Root cause**: Real-time vs finalized bar data. Live TradingView bars have different OHLC values while candles are still forming, producing different FVGs and trade decisions. 3 of 4 matching trades are identical; the gap comes entirely from trades that only exist in one system. This is inherent and unfixable — not a code bug.

### PickMyTrade Webhook Integration (Feb 24, 2026)
Enables multi-account execution via PickMyTrade ($50/mo flat) for personal + prop firm Tradovate accounts. Tradovate blocks direct API on prop firm accounts; PickMyTrade is an authorized vendor that acts as the execution bridge.

**Architecture**: Paper mode is the "brain" — manages the full trade lifecycle. `WebhookExecutor` fires HTTP calls to PickMyTrade at each lifecycle event for broker execution.

**Why not PickMyTrade's built-in TP/SL**: T2 (4-tick buffer) and Runner (6-tick buffer) need different trail levels, but PickMyTrade's `update_sl` applies to ALL remaining contracts equally. Instead, the bot manages all exits explicitly.

**Trail stop synchronization**: After 6R, broker stop is set to the tighter T2 trail. When T2 exits, broker stop moves to runner trail. If price gaps through both between scans, broker stop fires for all remaining (acceptable — protects capital).

**9 Webhook Lifecycle Events:**
| # | Event | Webhook Call |
|---|-------|-------------|
| 1 | Entry | `open_position()` — market order + initial protective stop |
| 2 | T1 hit (3R) | `partial_close(1ct)` + `update_stop(breakeven)` |
| 3 | T1 trail update | `update_stop(t1_trail)` |
| 4 | 6R touch | `update_stop(plus_4r floor)` |
| 5 | T2 trail update | `update_stop(t2_trail)` — tighter, covers T2+Runner |
| 6 | Full stop | `close_position()` |
| 7 | Trail stop (before 6R) | `close_position()` |
| 8 | T2/Runner exit | `partial_close()` or `close_position()` |
| 9 | EOD | `close_position()` for each open trade |

**Config** (`config/pickmytrade_accounts.json` — gitignored):
- `contract_months`: Updated quarterly at roll (e.g., `ESM6` → `ESU6`)
- `qty_multiplier`: Per-account sizing (e.g., 0.5 for prop evals with lower limits)
- `enabled`: Toggle accounts without removing config
- `strategy_groups`: Route different strategies to different account sets

**Error handling**: Max 2 retries, 1-sec delay. No retry on 4xx. On failure: log + Telegram alert. Paper mode continues regardless (source of truth). All accounts fire in parallel via `ThreadPoolExecutor` (~100ms spread).

### FVG Detection Mode: Wick vs Body A/B Test (Feb 26, 2026)
Tested body-based FVG detection (open/close boundaries, matching TradingView's indicator) vs current wick-based (high/low boundaries, ICT's definition). Added `--fvg-mode=body` CLI flag to backtest and plot runners.

**ICT Definition**: FVGs use wicks — the gap must be a price range where no trading occurred at all. Body-based gaps may have already been filled by wicks.

**18-Day A/B Results (ES):**
| Config | Trades | Wins | Losses | Win Rate | Total P/L | Max DD |
|--------|--------|------|--------|----------|-----------|--------|
| **Wick (default)** | **180** | **157** | **23** | **87.2%** | **+$163,825** | **$413** |
| Body | 218 | 150 | 68 | 68.8% | +$151,375 | $600 |

Body mode found 38 more trades but generated 45 more losses. Net **-$12,450** on ES.

**18-Day A/B Results (NQ):**
| Config | Trades | Wins | Losses | Win Rate | Total P/L | Max DD |
|--------|--------|------|--------|----------|-----------|--------|
| Wick (default) | 138 | 115 | 23 | 83.3% | +$280,525 | $778 |
| **Body** | **279** | **204** | **75** | **73.1%** | **+$401,698** | **$2,263** |

Body mode found 141 more trades and generated **+$121,173** on NQ — extra entries catch big trend runners.

**Combined 18-Day (ES + NQ):**
| Config | Combined P/L |
|--------|-------------|
| All Wick | $444,350 |
| All Body | $553,073 |
| Per-Symbol (ES wick, NQ body) | $565,523 |

**Decision**: Keep **wick as default** for all symbols. It's the correct ICT definition, validated on ES (87% vs 69% WR). NQ body-mode edge is real (+$121k) but comes with 3x drawdown and lower quality entries — could reverse in different market conditions. The `--fvg-mode=body` flag remains available for future retesting.

**CLI usage:**
```bash
# Default (wick)
python -m runners.backtest_v10_multiday ES 17

# Body mode
python -m runners.backtest_v10_multiday ES 17 --fvg-mode=body
python -m runners.plot_v10 ES 3 --fvg-mode=body
python -m runners.run_v10_dual_entry ES 3 --fvg-mode=body
```

### V10.14 Opposing FVG Exit for T2/Runner (Feb 26, 2026)
When a strong opposing FVG forms after entry, exit remaining T2/Runner contracts at bar close instead of waiting for trail stop. Catches reversals that the structure trail misses (e.g., Feb 26: SHORT rode 86-point drop but trail didn't tighten during waterfall — 41-point reversal gave back profit while a 29-tick bullish FVG formed at 10:39).

**How it works:**
- After 6R touch, scan for opposing FVGs created since entry
- Opposing = BULLISH FVG for SHORT trades, BEARISH FVG for LONG trades
- FVG must meet minimum size threshold
- Exit ALL remaining contracts (T2 + Runner) at bar close
- Exit type: `OPP_FVG`

**Per-symbol config (A/B tested):**
| Symbol | Config | Trigger | Min FVG Size |
|--------|--------|---------|-------------|
| ES/MES | B2 | After 6R | 10 ticks (2.5 pts) |
| NQ/MNQ | B1 | After 6R | 5 ticks (1.25 pts) |

**18-Day A/B Test Matrix (ES):**
| Config | Trigger | Min FVG | Total P/L | vs Baseline |
|--------|---------|---------|-----------|-------------|
| Baseline | — | — | $163,350 | — |
| A1 | After T1 | 5 ticks | $167,113 | +$3,763 |
| A2 | After T1 | 10 ticks | $171,306 | +$7,956 |
| A3 | After T1 | 20 ticks | $167,619 | +$4,269 |
| B1 | After 6R | 5 ticks | $169,100 | +$5,750 |
| **B2** | **After 6R** | **10 ticks** | **$172,869** | **+$9,519** |
| B3 | After 6R | 20 ticks | $167,081 | +$3,731 |

**ES: All configs beat baseline. B2 (after 6R, 10 ticks) is best at +$9,519 (+5.8%).**

**18-Day A/B Test Matrix (NQ):**
| Config | Trigger | Min FVG | Total P/L | vs Baseline |
|--------|---------|---------|-----------|-------------|
| Baseline | — | — | $293,160 | — |
| A1 | After T1 | 5 ticks | $279,945 | -$13,215 |
| B1 | After 6R | 5 ticks | $284,105 | -$9,055 |
| B2 | After 6R | 10 ticks | $282,365 | -$10,795 |
| B3 | After 6R | 20 ticks | $284,330 | -$8,830 |

**NQ: All configs lose money vs baseline.** Opposing FVG exit cuts runners short — big NQ trend moves get exited prematurely. B1 (after 6R, 5 ticks) is least harmful at -$9,055.

**Why per-symbol:** Same pattern as retrace risk cap and consecutive loss stop — ES benefits from tighter risk management, NQ benefits from letting runners run. NQ's B1 config enabled despite negative backtest to protect against extreme reversals (the cost is small relative to potential tail risk).

**CLI usage:**
```bash
# A/B test opposing FVG exit
python -m runners.backtest_v10_multiday ES 18 --opp-fvg-exit --opp-fvg-min-ticks=10 --opp-fvg-after-6r
python -m runners.backtest_v10_multiday NQ 18 --opp-fvg-exit --opp-fvg-min-ticks=5 --opp-fvg-after-6r
```

### V10.16 Trail Improvement (Mar 3, 2026)
Lowered trail activation from 6R to 4R for all symbols, and added fixed T2 exit at 5R for ES/MES. Addresses the "dead zone" between T1 exit at 3R and trail activation at 6R where 2 contracts sat at breakeven and got stopped on pullbacks.

**Problem:** After T1 exits at 3R (1 ct), remaining 2 contracts (T2+Runner) trailed at breakeven until 6R. During pullbacks in the 3R-6R gap, both contracts exited at breakeven — giving back all unrealized profit.

**Solution (per-symbol):**
- **ES/MES**: Trail trigger lowered 6R→4R + T2 fixed exit at 5R (only Runner trails)
- **NQ/MNQ**: Trail trigger lowered 6R→4R only (T2 and Runner both trail — NQ needs runners for big trends)

**18-Day A/B Test (ES):**
| Option | Description | Total P/L | vs Baseline | Max DD | Day WR |
|--------|-------------|-----------|-------------|--------|--------|
| Baseline | 3R/6R | $131,988 | — | $413 | 94.4% |
| A | Trail 6R→4R | $147,125 | +$15,137 | $131 | 94.4% |
| B | Post-T1 trail +1R | $135,331 | +$3,344 | $0 | 100% |
| C | T2 fixed at 5R | $146,519 | +$14,531 | $0 | 100% |
| D | Time decay +2R@10bars | $134,156 | +$2,169 | $13 | 94.4% |
| **A+C** | **Trail 4R + T2 fixed 5R** | **$151,250** | **+$19,263** | **$0** | **100%** |

**18-Day A/B Test (NQ):**
| Option | Total P/L | vs Baseline |
|--------|-----------|-------------|
| Baseline (3R/6R) | $233,788 | — |
| A: Trail 4R | **$247,605** | **+$13,818** |
| C: T2 fixed 5R | $237,675 | +$3,888 |
| A+C combined | $238,145 | +$4,358 |

**NQ: Option A alone is best.** T2 fixed exit cuts NQ runners short — big NQ trends go 10-20R.

**22-Day Validation (all symbols):**
| Symbol | Config | Trades | WR | Total P/L | Day WR | Max DD |
|--------|--------|--------|-----|-----------|--------|--------|
| ES | A+C | 219 | 84.5% | +$191,231 | **100% (22/22)** | **$0** |
| MES | A+C | 210 | 81.9% | +$17,864 | **100% (22/22)** | **$0** |
| NQ | A only | 169 | 82.2% | +$340,743 | 90.9% (20/22) | $778 |
| MNQ | A only | 162 | 80.9% | +$31,349 | 90.9% (20/22) | $55 |
| **Combined** | — | **760** | **82.5%** | **+$581,187** | — | **$778** |

**Why per-symbol:** Same pattern as retrace risk cap, BOS control, and consecutive loss stop — ES benefits from tighter profit management (lock T2 early), NQ benefits from letting runners ride (big trend moves go 10-20R).

**CLI usage:**
```bash
# Default V10.16 (auto per-symbol config)
python -m runners.backtest_v10_multiday ES 22
python -m runners.backtest_v10_multiday NQ 22

# Override to old V10.15 baseline
python -m runners.backtest_v10_multiday ES 22 --trail-r=6 --t2-fixed-r=0

# A/B test other trail options
python -m runners.backtest_v10_multiday ES 18 --post-t1-trail-r=1
python -m runners.backtest_v10_multiday ES 18 --time-decay-bars=10 --time-decay-r=2
```

### V10.15 Bar-Aligned Scanning (Feb 26, 2026)
Live bot scanned on a fixed 180s interval, which often fired mid-bar when TradingView OHLC data was still incomplete. This produced phantom FVGs that disappeared once the bar finalized — generating extra low-quality entries that don't exist in backtest.

**9-Day Comparison (Feb 16–26, before fix):**
| Metric | Backtest (ES) | Live Paper |
|--------|--:|--:|
| Trades | 83 | 115 |
| Win Rate | 84.3% | 60.0% |
| Total P/L | +$65,094 | +$52,120 |
| Worst Day | -$413 | -$5,563 |

**Root cause**: Fixed 180s sleep fired at arbitrary wall-clock times. If a scan landed at :01:30 (90s into a 3-min bar), TradingView's OHLC for that bar was incomplete — wicks and body still forming. FVGs computed from incomplete data are phantoms.

**Fix**: Replaced `self._interruptible_sleep(self.scan_interval)` with `self._sleep_until_next_bar_close()` that calculates the next 3-minute boundary and sleeps until boundary + 5 seconds. Scans now fire at :00:05, :03:05, :06:05, etc. — always processing finalized bars.

**Implementation**: `_sleep_until_next_bar_close()` in `run_live.py`:
- Calculates `seconds_into_bar = (minute * 60 + second) % 180`
- Sleeps `180 - seconds_into_bar + 5` seconds (minimum 10s to avoid double-fires)

**Status**: Deployed Feb 26. Monitoring for gap closure. If gap persists, remaining fixes: (1) drop last bar from array before `run_session_v10()`, (2) FVG confirmation filter requiring persistence on next scan.

### Centralized Symbol Config (Mar 3, 2026)
All per-symbol strategy parameters live in `runners/symbol_defaults.py`. Every runner, backtest, plot, and divergence tracker imports from this module instead of defining params inline.

**Why**: V10.16 changed `trail_r_trigger` from 6→4 and added `t2_fixed_r=5` for ES/MES. These params were hardcoded in 10+ files independently — 6 files were missed during initial implementation. The centralized module prevents this class of drift.

**Architecture:**
- `FUTURES_DEFAULTS` dict — ES, NQ, MES, MNQ with all 20+ params each
- `EQUITY_DEFAULTS` dict — SPY, QQQ, IWM
- `get_symbol_config(symbol)` — returns a deep copy of config dict
- `get_session_v10_kwargs(symbol, **overrides)` — maps config to `run_session_v10()` kwargs
- `get_live_futures_config(symbol)` — format for `LiveTrader.FUTURES_SYMBOLS`
- `get_consec_loss_limit(symbol)` — for `risk_manager.py`

**To change a param (e.g., V10.17 raises trail_r_trigger to 5):**
1. Edit ONE line in `runners/symbol_defaults.py`
2. Run `python -m pytest tests/test_symbol_parity.py`
3. Done — all callers pick up the change automatically

**CLI overrides still work** via `**overrides` pattern:
```bash
# Override trail trigger for A/B test
python -m runners.backtest_v10_multiday ES 18 --trail-r=6
# get_session_v10_kwargs('ES', trail_r_trigger=6) overrides just that param
```

**8 files migrated:**
| File | What changed |
|------|-------------|
| `backtest_v10_multiday.py` | Replaced 7 ternaries + `run_session_v10()` call with `get_session_v10_kwargs()` |
| `run_live.py` | `FUTURES_SYMBOLS`/`EQUITY_SYMBOLS` dicts derived from centralized config |
| `run_v10_dual_entry.py` | `run_today_v10()` uses centralized config |
| `plot_v10.py` | Replaced 6 ternaries + 30-line call |
| `plot_v10_date.py` | Replaced 4 ternaries + 20-line call |
| `divergence_tracker.py` | Replaced 20-line if/elif config block |
| `run_v10_equity.py` | `EQUITY_CONFIG` derived from `EQUITY_DEFAULTS` |
| `risk_manager.py` | `_get_symbol_consec_limit()` + BOS risk caps from centralized config |

**Parity tests** (`tests/test_symbol_parity.py` — 22 tests):
1. **No hardcoded patterns** — regex scan of 7 critical files catches old inline ternary patterns
2. **Kwargs match signature** — all `get_session_v10_kwargs()` keys verified against `run_session_v10()` signature
3. **Mini/micro parity** — ES must match MES (and NQ match MNQ) on all strategy params (only tick_value differs)

### Strategy Features
- **Centralized Symbol Config**: All per-symbol params in `runners/symbol_defaults.py` — single source of truth, 22 parity tests prevent drift
- **Trail Improvement (V10.16)**: Trail trigger 6R→4R all symbols + T2 fixed at 5R for ES/MES — ES +$19k/18d (+14.6%), 100% winning days, zero DD
- **Per-Symbol Consecutive Loss Stop (V10.16)**: ES/MES: 2 losses/symbol, NQ/MNQ: 3 losses/symbol (tracked in risk_manager, not strategy)
- **Opposing FVG Exit (V10.14)**: Exit T2/Runner on opposing FVG after 6R (ES: 10 ticks, NQ: 5 ticks) — ES +$9.5k/18d
- **PickMyTrade Webhook**: Multi-account execution for personal + prop firm Tradovate accounts (futures only)
- **Bar-Aligned Scanning (V10.15)**: Scan timing synced to 3-min bar close + 5s buffer — eliminates phantom FVGs from incomplete bars
- **Instant Startup (V10.11)**: Live bot uses local bar history for immediate indicator warmup at 04:00 ET (was 57-min lag)
- **Local Bar Storage**: Saves 3m bars to CSV daily, merges with live TradingView data for 30+ day backtests (90-day retention)
- **Retrace Risk Cap (V10.11)**: ES/MES retrace risk > 8pts → force 1 contract (NQ/MNQ uncapped)
- **EOD Next-Day Outlook**: Conviction-scored Telegram alert with CPR, pivots, ATR, volume (ES only)
- **Direction-Aware Circuit Breaker (V10.10)**: 3 losses/direction/day (short losses don't block longs)
- **Entry Cap Fix (V10.10)**: Removed lifetime entries_taken counter; only concurrent open positions limited
- **Equity FVG Date Filter (V10.10)**: Skip stale FVGs from previous sessions
- **R-Target Tuning (V10.9→V10.16)**: T1 at 3R, trail at 4R (was 6R), T2 fixed at 5R for ES/MES
- **Hybrid Filter System (V10.8)**: 2 mandatory + 2/3 optional filters (+$90k/30d improvement)
- **Quad Entry Mode**: 4 entry types (Creation, Overnight, Intraday, BOS) with per-symbol BOS control
- **Hybrid Exit**: T1 fixed at 3R, trail at 4R; ES/MES: T2 fixed at 5R, Runner trails; NQ/MNQ: T2+Runner both trail
- **Dynamic Position Sizing (V10.7)**: 1st trade: 3 cts, 2nd+ trades: 2 cts (max 6 cts exposure)
- **Position Limit (V10.7)**: Max 3 open trades total per direction
- **BOS LOSS_LIMIT (V10.6)**: Per-symbol optimization + daily loss limit
- **High Displacement Override (V10.5)**: Skip ADX check if candle body >= 3x avg
- **ADX Filter for B1**: Overnight retrace requires ADX >= 22 (filters weak trends)
- **Stop**: FVG boundary + buffer (futures: 2 ticks, equities: ATR × 0.5)
- **ATR Buffer (V10.4)**: Equities use adaptive stops based on volatility

### Filters
| Filter | Value | Purpose |
|--------|-------|---------|
| Min FVG | 5 ticks | Filter tiny gaps |
| Min Risk | ES:1.5, NQ:6.0 pts | Skip small FVGs with tight targets |
| **Max BOS Risk** | **ES:8, NQ:20 pts** | **Cap oversized BOS entries** |
| **Max Retrace Risk** | **ES/MES:8 pts** | **V10.11: Force 1 ct on oversized retrace (NQ/MNQ uncapped)** |
| Displacement | 1.0x avg body | Lower threshold for more setups |
| **3x Displacement** | **>= 3.0x avg body** | **Reduce ADX to >= 10 for high-momentum Creation entries** |
| HTF Bias | EMA 20/50 | Trade with trend |
| **ADX** | **>= 11** | **V10.7: Lowered from 17 to catch earlier setups** |
| **B1 ADX** | **>= 22** | **Overnight retrace only in strong trends** |
| DI Direction | +DI/-DI | LONG if +DI > -DI, SHORT if -DI > +DI |
| **Rejection Wick** | **>= 0.85×body** | **V10.7: Relaxed from wick > body** |
| **FVG Age (B2)** | **2+ bars** | **V10.7: Reduced from 5 bars for quicker retrace** |
| Morning Only | Overnight retrace | B1 entries only 9:30-12:00 |
| **Midday Cutoff** | **12:00-14:00** | **No entries during lunch lull** |
| **PM Cutoff** | **NQ/MNQ/QQQ** | **No NQ/MNQ/QQQ entries after 14:00** |
| **SPY INTRADAY** | **Disabled** | **Skip SPY B2 entries (24% WR drag)** |
| **ATR Buffer** | **SPY/QQQ only** | **Adaptive stop: ATR(14) × 0.5 vs fixed $0.02** |
| **BOS Disable** | **ES/MES/SPY** | **BOS off for low win-rate symbols (V10.6)** |
| **BOS Loss Limit** | **NQ/MNQ/QQQ: 1/day** | **Stop BOS after 1 loss per day (V10.6)** |
| **Max Losses** | **3/direction/day** | **V10.10: Direction-aware circuit breaker** |
| **Consec Loss Stop** | **ES/MES: 2, NQ/MNQ: 3** | **V10.16: Per-symbol consecutive loss stop (tracked in risk_manager)** |
| **Trail Trigger** | **4R (all symbols)** | **V10.16: Lowered from 6R — activates structure trail sooner** |
| **T2 Fixed Exit** | **ES/MES: 5R** | **V10.16: Lock T2 profit at 5R (NQ/MNQ: T2 trails instead)** |
| **Max Open Trades** | **3 per direction** | **V10.7: Increased from 2** |
| **Position Sizing** | **Dynamic** | **V10.7: 1st trade: 3 cts, 2nd+: 2 cts (max 6 cts)** |

### 12-Day Backtest Results (V10.10 - Entry & Circuit Breaker Fixes)
| Symbol | Trades | Wins | Losses | Win Rate | PF | Total P/L | Avg Daily | Day WR |
|--------|--------|------|--------|----------|-----|-----------|-----------|--------|
| ES | 126 | 113 | 13 | 89.7% | inf | +$124,881 | +$10,407 | 100% (12/12) |
| NQ | 102 | 82 | 20 | 80.4% | 290.8 | +$225,295 | +$18,775 | 91.7% (11/12) |
| **Mini Total** | **228** | **195** | **33** | **85.5%** | **-** | **+$350,176** | **+$29,181** | - |

*V10.10 vs V10.9: +$150k P/L (+75%), more trades firing due to entry cap fix and direction-aware breaker*

### 30-Day Equity Results (V10.4 - ATR Buffer)
| Symbol | Trades | Wins | Losses | Win Rate | PF | Total P/L |
|--------|--------|------|--------|----------|-----|-----------|
| SPY | 47 | 27 | 20 | 57.4% | - | +$103,061 |
| QQQ | 65 | 33 | 32 | 50.8% | - | +$69,249 |
| **Equities** | **112** | **60** | **52** | **53.6%** | **-** | **+$172,310** |

*Note: ATR buffer improves P/L by +$54k vs fixed $0.02 buffer despite lower win rate (wider stops = larger risk per trade but fewer stop-hunts)*

### Entry Type Breakdown (V10.7 - 11 Days)
| Entry Type | ES | NQ | Total |
|------------|-----|-----|-------|
| Creation | 31 (70.5%) | 24 (75.0%) | 55 (72.4%) |
| Overnight | 3 (6.8%) | 2 (6.2%) | 5 (6.6%) |
| Intraday | 2 (4.5%) | 1 (3.1%) | 3 (3.9%) |
| BOS | 8 (18.2%) | 5 (15.6%) | 13 (17.1%) |

### Key Insights (V10.16)
- V10.16 trail improvement: ES +$19k/18d (+14.6%), 100% winning days, zero DD over 22 days
- "Dead zone" between T1 (3R) and trail (6R) was the #1 profit drag — 2 contracts sat at breakeven for too long
- Lowering trail trigger to 4R shrinks dead zone from 3R gap to 1R gap — massive improvement
- T2 fixed at 5R locks 2nd contract profit — ES/MES only (NQ needs runners for big trends)
- NQ benefits from trail 4R but NOT from T2 fixed exit — big NQ trends go 10-20R
- Per-symbol consecutive loss stop (ES/MES=2, NQ/MNQ=3) replaces global counter — scales to any number of tickers
- Combined 22-day results: ES +$191k, MES +$18k, NQ +$341k, MNQ +$31k = **+$581k total**
- Per-symbol config pattern confirmed again: ES benefits from tighter management, NQ benefits from letting runners run
- Global consecutive loss stop (ES/MES only) prevents whipsaw damage — Feb 19 loss cut from -$900 to +$388
- NQ consecutive loss at 3/symbol: Feb 12 had 2 consec losses then +$30k in winners
- Cooldown-based approaches (30/60/90/120min) had zero effect — post-trigger trades come hours later
- Live bot startup fix eliminates 57-min data lag — trades from 04:03 instead of ~05:00
- Feb 23 analysis: old bot missed 3 early winners (+$1,537.50) due to data lag
- Backtest vs live will still diverge (real-time vs post-session bars) but gap is much smaller
- ES retrace risk cap (8pts) cuts oversized retrace losses by ~50% with 1-ct sizing
- NQ retrace cap is counterproductive — wide retraces catch big trends (+$18.6k difference uncapped)
- Direction-aware circuit breaker prevents short losses from blocking long entries (and vice versa)
- Removing entries_taken lifetime cap allows more trades to fire after early positions close
- ES BOS OFF validated: 15 BOS trades over 12 days were net -$6,475 drag
- ES: 100% winning days (12/12), zero drawdown, $10.4k avg daily
- NQ: 91.7% winning days (11/12), $778 max drawdown, $18.8k avg daily
- Creation entries dominate: ES 100%, NQ 85.3%
- Lower R-targets (3R/6R) lock profit before most pullbacks
- R-targets are parameterized via `--t1-r=N --trail-r=N` CLI flags for future A/B tests

## Key Commands

### Backtesting
```bash
# V10 futures backtest today (mini contracts)
python -m runners.run_v10_dual_entry ES 3
python -m runners.run_v10_dual_entry NQ 3

# V10 futures backtest today (micro contracts)
python -m runners.run_v10_dual_entry MES 3
python -m runners.run_v10_dual_entry MNQ 3

# V10 equity backtest today (SPY/QQQ)
python -m runners.run_v10_equity SPY 500   # $500 risk per trade
python -m runners.run_v10_equity QQQ 500

# V10 multi-day backtest (30 days)
python -m runners.backtest_v10_multiday ES 30
python -m runners.backtest_v10_multiday NQ 30
python -m runners.backtest_v10_multiday MES 30
python -m runners.backtest_v10_multiday MNQ 30

# Verbose per-trade output (compare with live runner logs)
python -m runners.backtest_v10_multiday ES 1 3 --verbose

# R-target A/B testing (override defaults)
python -m runners.backtest_v10_multiday ES 11 --t1-r=4 --trail-r=8
python -m runners.run_v10_dual_entry ES 3 --t1-r=5 --trail-r=10
python -m runners.run_v10_equity SPY 500 --t1-r=3 --trail-r=6

# Analyze winning vs losing days
python -m runners.analyze_win_loss ES
```

### Bar Storage
```bash
# Seed local storage with current TradingView data (run once)
python -m runners.save_bars ES NQ MES MNQ

# Bars auto-save at EOD on the droplet via run_live.py
# Stored at data/bars/{symbol}/YYYY-MM-DD.csv (90-day retention)
# Multi-day backtest automatically merges local + live bars
```

### Plotting
```bash
# Plot V10 today (futures)
python -m runners.plot_v10 ES 3
python -m runners.plot_v10 NQ 3

# Plot V10 today (equities - 4th arg is risk per trade)
python -m runners.plot_v10 SPY 0 3m 50
python -m runners.plot_v10 QQQ 0 3m 50

# Plot V10 specific date
python -m runners.plot_v10_date 2026 2 3
```

### Live Trading
```bash
# Paper mode - all symbols (futures + equities)
python -m runners.run_live --paper --symbols ES MES SPY QQQ

# Paper mode - futures only
python -m runners.run_live --paper --symbols ES MES

# Paper mode - equities only (custom risk per trade)
python -m runners.run_live --paper --symbols SPY QQQ --equity-risk 1000

# Paper + webhook (primary use case for live execution)
python -m runners.run_live --paper --webhook --symbols ES MES

# Paper + webhook (custom strategy group / config path)
python -m runners.run_live --paper --webhook --strategy-group ict_v10 --webhook-config config/pickmytrade_accounts.json

# Demo mode (Tradovate sim account)
python -m runners.run_live --symbols ES MES

# Live mode (real money - be careful!)
python -m runners.run_live --live --symbols ES MES
```

### Live Monitoring
```bash
# Start TradingView live monitor
python -m runners.run_tv_live

# Re-authenticate TradingView (if session expires)
python -m runners.tv_login
```

### Testing
```bash
# Run all tests (126 tests including 22 symbol parity tests)
python -m pytest tests/

# Run only symbol parity tests (fast — catches config drift)
python -m pytest tests/test_symbol_parity.py -v

# Run backtest replay
python -m runners.run_replay
```

## Key Files

| File | Purpose |
|------|---------|
| `runners/symbol_defaults.py` | **Centralized symbol config** - single source of truth for all per-symbol params |
| `runners/run_live.py` | **Combined live trader** - futures + equities + webhook integration |
| `runners/webhook_executor.py` | **PickMyTrade webhook** - multi-account execution for Tradovate |
| `runners/run_v10_dual_entry.py` | V10 Quad Entry strategy - futures (ES/NQ/MES/MNQ) |
| `runners/run_v10_equity.py` | V10 Quad Entry strategy - equities (SPY/QQQ) |
| `runners/bar_storage.py` | Local bar save/load/merge (90-day retention) |
| `runners/save_bars.py` | CLI backfill script for bar storage |
| `runners/backtest_v10_multiday.py` | V10 multi-day backtest (uses local + live bars) |
| `runners/plot_v10.py` | V10 trade visualization |
| `runners/plot_v10_date.py` | V10 date-specific plotting |
| `runners/analyze_win_loss.py` | Win/loss day analysis |
| `runners/tradovate_client.py` | Tradovate API client |
| `runners/order_manager.py` | Trade execution & management |
| `runners/risk_manager.py` | Risk controls & limits |
| `runners/run_tv_live.py` | Live TradingView monitor |
| `runners/tv_login.py` | TradingView browser auth |
| `config/strategies/ict_es.yaml` | ES configuration |
| `config/strategies/ict_nq.yaml` | NQ configuration |
| `config/tradovate_credentials.template.json` | API credentials template |
| `config/pickmytrade_accounts.template.json` | PickMyTrade config template |
| `config/pickmytrade_accounts.json` | PickMyTrade credentials (**gitignored**) |
| `run_paper_trading.py` | **Paper trading wrapper** - health check, auto-restart |
| `deploy/setup_droplet.sh` | DigitalOcean droplet initial setup |
| `deploy/deploy.sh` | Deploy code updates to droplet |

### Strategy Functions
| Function | Description |
|----------|-------------|
| `run_session_v10()` | V10 Quad Entry - futures (ES/NQ/MES/MNQ) |
| `run_session_v10_equity()` | V10 Quad Entry - equities (SPY/QQQ) |
| `run_session_with_position_limit()` | V8-Independent with position limit |
| `run_multi_trade()` | V7-MultiEntry with profit-protected 2nd entry |
| `run_trade()` | V6-Aggressive single entry (legacy) |

### Instrument Differences
| Aspect | Mini (ES/NQ) | Micro (MES/MNQ) | Equities (SPY/QQQ) |
|--------|--------------|-----------------|-------------------|
| Position Size | **Dynamic (3→2 cts)** | **Dynamic (3→2 cts)** | Risk-based shares |
| Tick Value | ES:$12.50, NQ:$5 | MES:$1.25, MNQ:$0.50 | $1/share |
| P/L Calculation | ticks × tick_value | ticks × tick_value | shares × price move |
| Stop Buffer | 2 ticks | 2 ticks | **ATR × 0.5** (V10.4) |
| Trail Buffer | 4-6 ticks | 4-6 ticks | $0.04-0.06 |
| Max Exposure | **6 contracts** | **6 contracts** | Risk-based |

## Daily Workflow

1. **Morning**: `python health_check.py`
2. **Pre-market**: `python -m runners.run_v10_dual_entry ES 3` (review signals)
3. **Market hours**: `python -m runners.run_live --paper --symbols ES MES` (paper trade)
4. **Post-market**: `python -m runners.plot_v10 ES 3` (review)

## TradingView Connection
- Session cached at `~/.tvdatafeed/`
- If data shows "nologin method", run `python -m runners.tv_login`

## Automated Paper Trading (DigitalOcean Droplet)

### Deployment
The bot runs automatically on a DigitalOcean droplet at **3:55 AM ET Mon-Fri**.

**Droplet**: `107.170.74.154`

**Files**:
- `deploy/setup_droplet.sh` - Initial droplet setup script
- `deploy/deploy.sh` - Deploy code updates to droplet
- `run_paper_trading.py` - Wrapper with health check, auto-restart, market hours enforcement

**Quick Commands**:
```bash
# Deploy updated code to droplet
./deploy/deploy.sh

# SSH into droplet
ssh root@107.170.74.154

# On droplet - check status
sudo systemctl status paper-trading
systemctl list-timers

# On droplet - view logs
tail -f /opt/tradovate-bot/logs/paper_trading/service.log

# On droplet - manual start/stop
sudo systemctl start paper-trading
sudo systemctl stop paper-trading
```

**Features**:
- Health check with TradingView Pro connectivity verification on startup
- Auto-restarts on crash (up to 5 times per day)
- Graceful shutdown at market close (4:30 PM ET)
- Skips weekends automatically
- Telegram alerts: entry/exit events + hourly heartbeat + daily summary + EOD next-day outlook
- PickMyTrade webhook support (`python run_paper_trading.py --webhook`)

## Strategy Evolution
| Version | Key Feature |
|---------|-------------|
| V10.16 | Trail improvement: trail 6R→4R + T2 fixed 5R for ES/MES + per-symbol consec loss stop — **ES +$19k/18d (+14.6%), 100% winning days, zero DD** |
| V10.15 | Bar-aligned scanning: sync to 3-min bar close + 5s buffer — **eliminates phantom FVGs from incomplete bars** |
| V10.14 | Opposing FVG exit for T2/Runner: per-symbol (ES:10t, NQ:5t) after 6R - **ES +$9.5k/18d (+5.8%)** |
| V10.13 | Global consecutive loss stop: ES/MES stop after 2 consec losses (NQ exempt) - **+$488 ES, Feb 19 loss halved** |
| V10.12 | Backtest parity fixes: trail logic, parameter matching, risk manager tracking - **~11% gap → ~2-3%** |
| V10.11 | Retrace risk cap: ES/MES >8pts → 1 ct (NQ uncapped) + **startup data lag fix (57min → instant)** |
| V10.10 | Entry cap fix + direction-aware circuit breaker + equity FVG date filter + BOS parity + **EOD outlook alert** - **+$350k/12d** |
| V10.9 | R-target tuning: T1=3R, Trail=6R (was 4R/8R) - **+31% P/L, 87.7% WR, zero DD** |
| V10.8 | Hybrid filter system (2 mandatory + 2/3 optional) - **+$90k/30d, +71% trades** |
| V10.7 | Dynamic sizing (1st:3cts, 2nd+:2cts) + ADX>=11 + 3 trades/dir + FVG mitigation fix |
| V10.6 | BOS LOSS_LIMIT - per-symbol control + 1 loss/day limit |
| V10.5 | High displacement override (3x skips ADX) |
| V10.4 | ATR buffer for equities (ATR × 0.5 vs $0.02) |
| V10.3 | BOS risk cap (ES:8, NQ:20) + Disable SPY INTRADAY |
| V10.2 | Midday cutoff (12-14) + NQ/QQQ PM cutoff |
| V10.1 | ADX >= 22 filter for Overnight Retrace |
| V10 | Quad Entry (Creation, Overnight, Intraday, BOS) + Hybrid Exit |
| V9 | Min Risk Filter + Opposing FVG Exit |
| V8 | Independent 2nd Entry + Position Limit |
| V7 | Profit-Protected 2nd Entry |
| V6 | Aggressive FVG Creation Entry |
