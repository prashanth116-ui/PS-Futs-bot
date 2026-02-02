# Project Instructions

## On Session Start
Run the health check script at the beginning of each session:
```
python health_check.py
```

## Project Overview
Tradovate futures trading bot using ICT (Inner Circle Trader) strategy.

## Current Strategy: V7-MultiEntry (Feb 2, 2026)

### Supported Instruments (ES/NQ Only)
| Symbol | Exchange | Tick Value |
|--------|----------|------------|
| ES | CME_MINI | $12.50 |
| NQ | CME_MINI | $5.00 |

### Strategy Features
- **Entry**: AT FVG CREATION (aggressive, no waiting for retracement)
- **2nd Entry**: Profit-protected - only when 1st trade is at +2R or better
- **Stop Lock**: Move 1st trade stop to +1R when 2nd entry triggers
- **Stop**: FVG boundary + 2 tick buffer
- **Exits**: Structure trail after 4R touch, +4R runner stop after 8R

### Filters
| Filter | Value | Purpose |
|--------|-------|---------|
| Min FVG | 5 ticks | Filter tiny gaps |
| Displacement | 1.0x avg body | Lower threshold for more setups |
| HTF Bias | EMA 20/50 | Trade with trend |
| ADX | > 17 | Only trending markets |
| DI Direction | +DI/-DI | LONG if +DI > -DI, SHORT if -DI > +DI |
| Killzones | DISABLED | Trades any session time |
| Max Losses | 2/day | Circuit breaker |

### Profit-Protected 2nd Entry Logic
```
1st Trade enters at FVG creation
    ↓ Price moves, 1st trade reaches +2R profit
    ↓ New valid FVG forms (passes all filters)
2nd Trade enters at new FVG
    ↓ 1st trade stop moves to +1R (locks in profit)

If market reverses:
- 1st trade: Stopped at +1R = guaranteed profit
- 2nd trade: Stopped at FVG boundary = normal loss
- Net risk reduced vs two independent entries
```

### 13-Day Backtest Results
| Symbol | Trades | Win Rate | PF | Total P/L |
|--------|--------|----------|-----|-----------|
| ES | 22 | 68.2% | 14.15 | +$27,625 |
| NQ | 21 | 95.2% | 50.08 | +$31,290 |
| **Combined** | 43 | 81.4% | 27.95 | **+$58,915** |

### V7 vs V6 Comparison
| Metric | V6-Aggressive | V7-MultiEntry |
|--------|---------------|---------------|
| Entry Style | Single + re-entry on stop | Profit-protected 2nd entry |
| Win Rate | 42-48% | 68-95% |
| Risk Control | Original stop only | +1R lock on 2nd entry |

### Key Improvements in V7
- Higher win rate due to profit-protected entries
- More BE exits (structure trail at breakeven after 4R)
- Reduced drawdown from +1R stop lock
- Captures trending days with multiple entries

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
| `runners/run_today.py` | V7-MultiEntry strategy backtest |
| `runners/backtest_multiday.py` | Multi-day backtest (supports V6/V7) |
| `runners/plot_today.py` | Trade visualization |
| `runners/run_tv_live.py` | Live TradingView monitor |
| `runners/tv_login.py` | TradingView browser auth |
| `config/strategies/ict_es.yaml` | ES configuration |
| `config/strategies/ict_nq.yaml` | NQ configuration |
| `SESSION_NOTES.md` | Strategy changelog |

### Strategy Functions
| Function | Description |
|----------|-------------|
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
