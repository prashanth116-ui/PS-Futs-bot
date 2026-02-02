# Project Instructions

## On Session Start
Run the health check script at the beginning of each session:
```
python health_check.py
```

## Project Overview
Tradovate futures trading bot using ICT (Inner Circle Trader) strategy.

## Current Strategy: V9 (Tiered Trail + Risk Filter) - Feb 2, 2026

### Supported Instruments (ES/NQ Only)
| Symbol | Exchange | Tick Value | Min Risk |
|--------|----------|------------|----------|
| ES | CME_MINI | $12.50 | 1.5 pts |
| NQ | CME_MINI | $5.00 | 8.0 pts |

### V9 New Features
- **Min Risk Filter**: Skips small FVGs with tight targets (ES: 1.5 pts, NQ: 8 pts)
- **Opposing FVG Exit**: Runner exits when reversal signal forms

### Strategy Features
- **Entry**: AT FVG CREATION (aggressive, no waiting for retracement)
- **2nd Entry**: INDEPENDENT - taken regardless of 1st trade status
- **Position Limit**: Max 2 open trades total (combined LONG + SHORT)
- **Stop**: FVG boundary + 2 tick buffer
- **Tiered Structure Trail**: Each contract trails swing points independently

### Tiered Structure Trail Exit Strategy
```
Entry: 3 contracts at FVG midpoint
    ↓ Price hits 4R target
T1 Trail activates: 1 ct uses fast trail (2-tick buffer)
    ↓ Stop moves to breakeven, trail follows swing lows
    ↓ Price hits 8R target
T2 Trail activates: 1 ct uses standard trail (4-tick buffer)
Runner: +4R trail OR opposing FVG exit (whichever first)
```

### Filters
| Filter | Value | Purpose |
|--------|-------|---------|
| Min FVG | 5 ticks | Filter tiny gaps |
| Min Risk | ES:1.5, NQ:8 pts | Skip small FVGs with tight targets |
| Displacement | 1.0x avg body | Lower threshold for more setups |
| HTF Bias | EMA 20/50 | Trade with trend |
| ADX | > 17 | Only trending markets |
| DI Direction | +DI/-DI | LONG if +DI > -DI, SHORT if -DI > +DI |
| Killzones | DISABLED | Trades any session time |
| Max Losses | 2/day | Circuit breaker |
| Max Open Trades | 2 | Combined position limit |

### Today's Results (Feb 2, 2026)
| Symbol | Trades | Result | Total P/L |
|--------|--------|--------|-----------|
| ES | 2 LONG | 2 WIN | +$11,031 |
| NQ | 2 | 1 WIN, 1 LOSS | +$15,593 |
| **Combined** | 4 | 3 WIN, 1 LOSS | **+$26,624** |

### 30-Day Backtest Results (20 trading days)
| Symbol | Trades | Wins | Losses | Win Rate | PF | Total P/L |
|--------|--------|------|--------|----------|-----|-----------|
| ES | 33 | 23 | 10 | 69.7% | 9.46 | +$39,488 |
| NQ | 20 | 14 | 6 | 70.0% | 11.26 | +$60,430 |
| **Combined** | **53** | **37** | **16** | **69.8%** | **10.20** | **+$99,918** |

### Why Min Risk Filter Works
- Small FVGs (< 2 pts ES, < 8 pts NQ) create tight 4R/8R targets
- Tight targets = quick exits on minor pullbacks
- Filter forces strategy to wait for quality setups with room to run

### Example: NQ Trade (09:33)
```
Entry: 25575.38 (3 cts) - Large FVG with 28.62 pt risk
  ↓ 4R hit (25689.88), T1 trail activates
  ↓ 8R hit (25804.38), T2 and runner trails activate
T1: 1 ct @ 25851.25 = +$5,518 (fast trail)
T2: 1 ct @ 25850.75 = +$5,508 (standard trail)
Runner: 1 ct @ OPP_FVG (25840.50) = +$5,303 (opposing FVG exit)
Total: +$16,328
```

## Key Commands

### Backtesting
```bash
# Backtest today (ES, 3 contracts)
python -m runners.run_today ES 3

# Backtest NQ
python -m runners.run_today NQ 3

# Multi-day backtest (30 days)
python -m runners.backtest_multiday ES 30
```

### Plotting
```bash
# Plot today's trade
python -m runners.plot_today ES LONG 3

# Plot NQ
python -m runners.plot_today NQ LONG 3
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
| `runners/run_today.py` | V8-Independent strategy backtest |
| `runners/backtest_multiday.py` | Multi-day backtest (supports V6/V7/V8) |
| `runners/plot_today.py` | Trade visualization |
| `runners/run_tv_live.py` | Live TradingView monitor |
| `runners/tv_login.py` | TradingView browser auth |
| `config/strategies/ict_es.yaml` | ES configuration |
| `config/strategies/ict_nq.yaml` | NQ configuration |
| `SESSION_NOTES.md` | Strategy changelog |

### Strategy Functions
| Function | Description |
|----------|-------------|
| `run_session_with_position_limit()` | V8-Independent with position limit |
| `run_multi_trade()` | V7-MultiEntry with profit-protected 2nd entry |
| `run_trade()` | V6-Aggressive single entry (legacy) |

## Daily Workflow

1. **Morning**: `python health_check.py`
2. **Pre-market**: `python -m runners.run_today ES 3` (review signals)
3. **Market hours**: `python -m runners.run_tv_live` (monitor)
4. **Post-market**: `python -m runners.plot_today ES LONG 3` (review)

## TradingView Connection
- Session cached at `~/.tvdatafeed/`
- If data shows "nologin method", run `python -m runners.tv_login`
