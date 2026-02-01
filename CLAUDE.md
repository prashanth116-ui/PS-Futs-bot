# Project Instructions

## On Session Start
Run the health check script at the beginning of each session:
```
python health_check.py
```

## Project Overview
Tradovate futures trading bot using ICT (Inner Circle Trader) strategy.

## Current Strategy: V5-Optimized (Jan 31, 2026)

### Supported Instruments (ES/NQ Only)
| Symbol | Exchange | Tick Value |
|--------|----------|------------|
| ES | CME_MINI | $12.50 |
| NQ | CME_MINI | $5.00 |

### Strategy Features
- **Entry**: FVG midpoint with partial fill (1 ct @ edge, 2 cts @ midpoint)
- **Stop**: FVG boundary + 2 tick buffer
- **Exits**: Tiered structure trail (4R fast trail, 8R standard trail, Runner +4R/Opposing FVG)

### Filters
| Filter | Value | Purpose |
|--------|-------|---------|
| Min FVG | 5 ticks | Filter tiny gaps |
| Displacement | 1.2x avg body | Only strong moves |
| HTF Bias | EMA 20/50 | Trade with trend |
| ADX | > 17 | Only trending markets |
| DI Direction | +DI/-DI | LONG if +DI > -DI, SHORT if -DI > +DI |
| Killzones | DISABLED | Trades any session time |
| Max Losses | 2/day | Circuit breaker |

### 18-Day Backtest Results
| Symbol | Trades | Win Rate | PF | Total P/L |
|--------|--------|----------|-----|-----------|
| ES | 31 | 38.7% | 4.56 | +$29,967 |
| NQ | 33 | 54.5% | 6.05 | +$42,535 |
| **Combined** | 64 | 47.0% | 5.30 | **+$72,502** |

### Key Findings from Optimization
- EMA 20/50 outperforms EMA 9/21 (slower = better trend confirmation)
- EMA + DI Direction together outperform either alone
- Displacement 1.2x filters weak setups effectively
- ADX > 17 balances trade frequency vs quality

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
| `runners/run_today.py` | V5-Optimized strategy backtest |
| `runners/backtest_multiday.py` | Multi-day backtest |
| `runners/plot_today.py` | Trade visualization |
| `runners/run_tv_live.py` | Live TradingView monitor |
| `runners/tv_login.py` | TradingView browser auth |
| `config/strategies/ict_es.yaml` | ES configuration |
| `config/strategies/ict_nq.yaml` | NQ configuration |
| `SESSION_NOTES.md` | Strategy changelog |

## Daily Workflow

1. **Morning**: `python health_check.py`
2. **Pre-market**: `python -m runners.run_today ES 3` (review signals)
3. **Market hours**: `python -m runners.run_tv_live` (monitor)
4. **Post-market**: `python -m runners.plot_today ES LONG 3` (review)

## TradingView Connection
- Session cached at `~/.tvdatafeed/`
- If data shows "nologin method", run `python -m runners.tv_login`
