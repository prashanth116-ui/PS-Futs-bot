# Project Instructions

## On Session Start
Run the health check script at the beginning of each session:
```
python health_check.py
```

## Important: Data Verification
**ALWAYS verify numerical data before making claims about prices.** Do NOT rely on visual interpretation of chart images. The backtest and plot scripts now print RTH key levels:
```
RTH: Open=6856.25 High=6965.50 Low=6850.25
```
Use these printed values, not the chart image, to reference price levels.

## Project Overview
Tradovate futures trading bot using ICT (Inner Circle Trader) strategy.

## Current Strategy: V10.10 (Entry & Circuit Breaker Fixes) - Feb 17, 2026

### Supported Instruments
| Symbol | Type | Tick Value | Min Risk | Max BOS Risk | BOS Enabled |
|--------|------|------------|----------|--------------|-------------|
| ES | E-mini S&P 500 | $12.50 | 1.5 pts | 8.0 pts | **OFF** |
| NQ | E-mini Nasdaq | $5.00 | 6.0 pts | 20.0 pts | ON (loss limit) |
| MES | Micro E-mini S&P | $1.25 | 1.5 pts | 8.0 pts | **OFF** |
| MNQ | Micro E-mini Nasdaq | $0.50 | 6.0 pts | 20.0 pts | ON (loss limit) |
| SPY | S&P 500 ETF | per share | $0.30 | - | **OFF** |
| QQQ | Nasdaq 100 ETF | per share | $0.50 | - | ON (loss limit) |

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
```
Entry: Dynamic contracts at FVG midpoint
  - 1st trade of direction: 3 contracts (1 T1 + 1 T2 + 1 Runner)
  - 2nd/3rd trade: 2 contracts (1 T1 + 1 T2, no runner)
    ↓ Price hits 3R target (V10.9: lowered from 4R)
T1 (1 ct): FIXED profit at 3R - guaranteed, isolated from trail
    ↓ Price hits 6R target (V10.9: lowered from 8R)
T2 (1 ct): Structure trail with 4-tick buffer (floor at 3R)
Runner (1 ct): Structure trail with 6-tick buffer (1st trade only, floor at 3R)
    ↓ Swing pullback
T2/Runner exit on respective trail stops or EOD
```

**R-Target CLI flags** (all runners support `--t1-r=N --trail-r=N`):
```bash
# Default (V10.9): T1=3R, Trail=6R
python -m runners.backtest_v10_multiday ES 11

# Override to old baseline
python -m runners.backtest_v10_multiday ES 11 --t1-r=4 --trail-r=8
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

### Strategy Features
- **Direction-Aware Circuit Breaker (V10.10)**: 3 losses/direction/day (short losses don't block longs)
- **Entry Cap Fix (V10.10)**: Removed lifetime entries_taken counter; only concurrent open positions limited
- **Equity FVG Date Filter (V10.10)**: Skip stale FVGs from previous sessions
- **R-Target Tuning (V10.9)**: T1 at 3R, trail at 6R (+31% P/L, 87.7% WR, zero DD)
- **Hybrid Filter System (V10.8)**: 2 mandatory + 2/3 optional filters (+$90k/30d improvement)
- **Quad Entry Mode**: 4 entry types (Creation, Overnight, Intraday, BOS) with per-symbol BOS control
- **Hybrid Exit**: T1 fixed at 3R, T2/Runner structure trail after 6R
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

### Key Insights (V10.10)
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

# R-target A/B testing (override defaults)
python -m runners.backtest_v10_multiday ES 11 --t1-r=4 --trail-r=8
python -m runners.run_v10_dual_entry ES 3 --t1-r=5 --trail-r=10
python -m runners.run_v10_equity SPY 500 --t1-r=3 --trail-r=6

# Analyze winning vs losing days
python -m runners.analyze_win_loss ES
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
python -m runners.run_live --paper --symbols ES NQ MES MNQ SPY QQQ

# Paper mode - futures only
python -m runners.run_live --paper --symbols ES NQ MES MNQ

# Paper mode - equities only (custom risk per trade)
python -m runners.run_live --paper --symbols SPY QQQ --equity-risk 1000

# Demo mode (Tradovate sim account)
python -m runners.run_live --symbols ES NQ

# Live mode (real money - be careful!)
python -m runners.run_live --live --symbols ES NQ
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
# Run all tests
python -m pytest tests/

# Run backtest replay
python -m runners.run_replay
```

## Key Files

| File | Purpose |
|------|---------|
| `runners/run_live.py` | **Combined live trader** - futures + equities |
| `runners/run_v10_dual_entry.py` | V10 Quad Entry strategy - futures (ES/NQ/MES/MNQ) |
| `runners/run_v10_equity.py` | V10 Quad Entry strategy - equities (SPY/QQQ) |
| `runners/backtest_v10_multiday.py` | V10 multi-day backtest |
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
3. **Market hours**: `python -m runners.run_live --paper --symbols ES NQ SPY QQQ` (paper trade)
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
- Telegram alerts: entry/exit events + hourly heartbeat + daily summary

## Strategy Evolution
| Version | Key Feature |
|---------|-------------|
| V10.10 | Entry cap fix + direction-aware circuit breaker + equity FVG date filter + BOS parity - **+$350k/12d** |
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
