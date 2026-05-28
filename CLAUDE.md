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

### Entry Types
| Type | Name | Description |
|------|------|-------------|
| A | Creation | Enter immediately when FVG forms with displacement **(3x override skips ADX)** |
| B1 | Overnight Retrace | Enter when price retraces into overnight FVG + rejection **(ADX >= 22)** |
| B2 | Intraday Retrace | Enter when price retraces into session FVG **(2+ bars old)** + rejection **[Disabled for SPY]** |
| C | BOS + Retrace | Enter when price retraces into FVG after BOS **[Per-symbol control with loss limit]** |

### Hybrid Exit Structure

**ES/MES (T2 fixed at 5R):**
```
Entry: Dynamic contracts at FVG midpoint
  - 1st trade of direction: 3 contracts (1 T1 + 1 T2 + 1 Runner)
  - 2nd/3rd trade: 2 contracts (1 T1 + 1 T2, no runner)
    ↓ Price hits 3R → T1 exits (fixed profit)
    ↓ Price hits 4R → Trail activates (3R floor)
    ↓ Price hits 5R → T2 exits (fixed profit)
    ↓ Runner trails with 6-tick buffer until trail stop or EOD
```

**NQ/MNQ (T2 trails, no fixed exit):**
```
Entry: Same dynamic sizing as ES/MES
    ↓ Price hits 3R → T1 exits (fixed profit)
    ↓ Price hits 4R → Trail activates (3R floor)
    ↓ T2 trails with 4-tick buffer, Runner trails with 6-tick buffer
    ↓ Both ride big NQ trends until trail stop or EOD
```

**R-Target CLI flags** (all runners support `--t1-r=N --trail-r=N --t2-fixed-r=N`).

### Hybrid Filter System (V10.8)
**MANDATORY:** DI Direction, FVG Size (>= 5 ticks)
**OPTIONAL (2/3 must pass):** Displacement (>= 1.0x avg body), ADX (>= 11), EMA Trend (20/50)

### Strategy Features
- **Centralized Symbol Config**: All per-symbol params in `runners/symbol_defaults.py` — single source of truth, 22 parity tests prevent drift
- **Trail Improvement (V10.16)**: Trail trigger 6R→4R all symbols + T2 fixed at 5R for ES/MES
- **Per-Symbol Consecutive Loss Stop**: ES/MES: 2 losses/symbol, NQ/MNQ: 3 losses/symbol
- **Opposing FVG Exit (V10.14)**: Exit T2/Runner on opposing FVG after 6R (ES: 10 ticks, NQ: 5 ticks)
- **PickMyTrade Webhook**: Multi-account execution for personal + prop firm Tradovate accounts
- **Bar-Aligned Scanning (V10.15)**: Scan timing synced to 3-min bar close + 5s buffer
- **Instant Startup (V10.11)**: Live bot uses local bar history for immediate indicator warmup at 04:00 ET
- **Local Bar Storage**: Saves 3m bars to CSV daily, merges with live TradingView data (90-day retention)
- **Retrace Risk Cap (V10.11)**: ES/MES retrace risk > 8pts → force 1 contract (NQ/MNQ uncapped)
- **EOD Next-Day Outlook**: Conviction-scored Telegram alert with CPR, pivots, ATR, volume (ES only)
- **Direction-Aware Circuit Breaker**: 3 losses/direction/day (short losses don't block longs)
- **BOS LOSS_LIMIT (V10.6)**: ES/MES/SPY BOS off; NQ/MNQ/QQQ BOS enabled with 1 loss/day limit
- **High Displacement Override**: Skip ADX check if candle body >= 3x avg
- **Dynamic Position Sizing**: 1st trade: 3 cts, 2nd+ trades: 2 cts (max 6 cts, max 3 open/direction)

### Filters
| Filter | Value | Purpose |
|--------|-------|---------|
| Min FVG | 5 ticks | Filter tiny gaps |
| Min Risk | ES:1.5, NQ:6.0 pts | Skip small FVGs with tight targets |
| Max BOS Risk | ES:8, NQ:20 pts | Cap oversized BOS entries |
| Max Retrace Risk | ES/MES:8 pts | Force 1 ct on oversized retrace (NQ/MNQ uncapped) |
| Displacement | 1.0x avg body (3x overrides ADX to >= 10) |
| ADX | >= 11 (B1 Overnight: >= 22) |
| DI Direction | +DI/-DI for LONG/SHORT |
| Rejection Wick | >= 0.85×body |
| FVG Age (B2) | 2+ bars |
| Midday Cutoff | 12:00-14:00 (no entries) |
| PM Cutoff | NQ/MNQ/QQQ (no entries after 14:00) |
| SPY INTRADAY | Disabled (24% WR drag) |
| BOS Disable | ES/MES/SPY |
| BOS Loss Limit | NQ/MNQ/QQQ: 1/day |
| Max Losses | 3/direction/day |
| Consec Loss Stop | ES/MES: 2, NQ/MNQ: 3 |
| Trail Trigger | 4R (all symbols) |
| T2 Fixed Exit | ES/MES: 5R (NQ/MNQ: trails) |
| Max Open Trades | 3 per direction |
| Position Sizing | Dynamic: 1st trade 3 cts, 2nd+ 2 cts |

### Per-Symbol Design Pattern
ES/MES benefits from tighter risk management (BOS off, retrace cap, consec stop at 2, T2 fixed at 5R). NQ/MNQ benefits from letting runners run (BOS with loss limit, no retrace cap, consec stop at 3, T2 trails).

## Key Commands

### Backtesting
```bash
python -m runners.run_v10_dual_entry ES 3        # Today, mini
python -m runners.run_v10_dual_entry MES 3       # Today, micro
python -m runners.run_v10_equity SPY 500         # Today, equity
python -m runners.backtest_v10_multiday ES 30    # Multi-day
python -m runners.backtest_v10_multiday ES 1 3 --verbose  # Per-trade output
python -m runners.backtest_v10_multiday ES 11 --t1-r=4 --trail-r=8  # A/B test
python -m runners.analyze_win_loss ES            # Win/loss analysis
```

### Bar Storage
```bash
python -m runners.save_bars ES NQ MES MNQ  # Seed local storage (run once)
# Bars auto-save at EOD via run_live.py — data/bars/{symbol}/YYYY-MM-DD.csv
```

### Plotting
```bash
python -m runners.plot_v10 ES 3                  # Today, futures
python -m runners.plot_v10 SPY 0 3m 50           # Today, equity
python -m runners.plot_v10_date 2026 2 3         # Specific date
```

### Live Trading
```bash
python -m runners.run_live --paper --symbols ES MES           # Paper, futures
python -m runners.run_live --paper --symbols SPY QQQ --equity-risk 1000  # Paper, equities
python -m runners.run_live --paper --webhook --symbols ES MES # Paper + webhook
python -m runners.run_live --live --symbols ES MES            # Live (real money)
```

### Live Monitoring
```bash
python -m runners.run_tv_live    # TradingView live monitor
python -m runners.tv_login       # Re-authenticate TradingView
```

### Testing
```bash
python -m pytest tests/                        # All tests (126 incl 22 parity)
python -m pytest tests/test_symbol_parity.py -v  # Symbol parity only
```

## Key Files

| File | Purpose |
|------|---------|
| `runners/symbol_defaults.py` | **Centralized symbol config** — single source of truth |
| `runners/run_live.py` | **Combined live trader** — futures + equities + webhook |
| `runners/webhook_executor.py` | **PickMyTrade webhook** — multi-account execution |
| `runners/run_v10_dual_entry.py` | V10 Quad Entry — futures |
| `runners/run_v10_equity.py` | V10 Quad Entry — equities |
| `runners/bar_storage.py` | Local bar save/load/merge |
| `runners/backtest_v10_multiday.py` | V10 multi-day backtest |
| `runners/plot_v10.py` / `plot_v10_date.py` | Trade visualization |
| `runners/risk_manager.py` | Risk controls & limits |
| `runners/tradovate_client.py` | Tradovate API client |
| `runners/order_manager.py` | Trade execution & management |
| `run_paper_trading.py` | Paper trading wrapper — health check, auto-restart |
| `deploy/deploy.sh` | Deploy code updates to droplet |

### Strategy Functions
| Function | Description |
|----------|-------------|
| `run_session_v10()` | V10 Quad Entry — futures (ES/NQ/MES/MNQ) |
| `run_session_v10_equity()` | V10 Quad Entry — equities (SPY/QQQ) |

### Instrument Differences
| Aspect | Mini (ES/NQ) | Micro (MES/MNQ) | Equities (SPY/QQQ) |
|--------|--------------|-----------------|-------------------|
| Position Size | Dynamic (3→2 cts) | Dynamic (3→2 cts) | Risk-based shares |
| Tick Value | ES:$12.50, NQ:$5 | MES:$1.25, MNQ:$0.50 | $1/share |
| Stop Buffer | 2 ticks | 2 ticks | ATR × 0.5 |
| Trail Buffer | 4-6 ticks | 4-6 ticks | $0.04-0.06 |
| Max Exposure | 6 contracts | 6 contracts | Risk-based |

## Daily Workflow

1. **Morning**: `python health_check.py`
2. **Pre-market**: `python -m runners.run_v10_dual_entry ES 3` (review signals)
3. **Market hours**: `python -m runners.run_live --paper --symbols ES MES` (paper trade)
4. **Post-market**: `python -m runners.plot_v10 ES 3` (review)

## TradingView Connection
- Session cached at `~/.tvdatafeed/`
- If data shows "nologin method", run `python -m runners.tv_login`

## Automated Paper Trading (DigitalOcean Droplet)

**Droplet**: `107.170.74.154` — runs at 3:55 AM ET Mon-Fri

```bash
./deploy/deploy.sh                                    # Deploy code
ssh root@107.170.74.154                               # SSH in
sudo systemctl status paper-trading                   # Check status
tail -f /opt/tradovate-bot/logs/paper_trading/service.log  # View logs
sudo systemctl start|stop paper-trading               # Manual control
```

Features: health check, auto-restart (5x/day), graceful shutdown at 16:30 ET, weekend skip, Telegram alerts (entry/exit + hourly heartbeat + daily summary + EOD outlook), PickMyTrade webhook support.

## Strategy Evolution
| Version | Key Change |
|---------|------------|
| V10.16 | Trail 6R→4R + T2 fixed 5R (ES/MES) + per-symbol consec loss stop |
| V10.15 | Bar-aligned scanning (3-min bar close + 5s buffer) |
| V10.14 | Opposing FVG exit after 6R (ES:10t, NQ:5t) |
| V10.13 | Global consecutive loss stop (ES/MES: 2 consec) |
| V10.12 | Backtest parity fixes (trail logic, params, risk manager) |
| V10.11 | Retrace risk cap + startup data lag fix (57min → instant) |
| V10.10 | Entry cap fix + direction-aware circuit breaker + EOD outlook |
| V10.9 | R-target tuning: T1=3R, Trail=6R |
| V10.8 | Hybrid filter system (2 mandatory + 2/3 optional) |
| V10.7 | Dynamic sizing + ADX>=11 + 3 trades/dir |
| V10.6 | BOS per-symbol control + 1 loss/day limit |
| V10.5 | High displacement override (3x skips ADX) |
| V10.4 | ATR buffer for equities |
