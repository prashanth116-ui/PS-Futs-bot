# Session Notes

## Strategy Upgrade: V5-Optimized (2026-01-31)

### Supported Instruments
- **ES** (E-mini S&P 500) - $12.50/tick
- **NQ** (E-mini Nasdaq-100) - $5.00/tick

### Filter Settings
| Filter | Value | Purpose |
|--------|-------|---------|
| Min FVG | 5 ticks | Filter tiny gaps |
| Displacement | 1.2x avg body | Only strong moves |
| EMA | 20/50 | Trade with trend |
| ADX | > 17 | Only trending markets |
| DI Direction | +DI/-DI | Align with momentum |
| Killzones | DISABLED | Trade any session time |
| Max Losses | 2/day | Circuit breaker |

### Entry Strategy
- **Partial Fill**: 1 ct @ FVG edge, 2 cts @ FVG midpoint
- **Stop**: FVG boundary + 2 tick buffer

### Exit Strategy (Tiered Structure Trail)
- **1st contract**: Fast trail after 4R touch (2-tick buffer)
- **2nd contract**: Standard trail after 8R touch (4-tick buffer)
- **3rd contract (Runner)**: Opposing FVG or +4R trailing stop

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
- Strategy NOT suitable for stocks (different tick values, volatility)

---

## Previous: V3-StructureTrail (2026-01-29)

### Changes Made:
1. **EMA Filter Fix**: Now checks EMA at entry time (not end of session)
2. **Tiered Structure Trail** (replaces fixed 4R/8R exits)

### Backtest Results (30 days):
- Win Rate: 27-33%
- Profit Factor: 3.51
- Total P/L: +$23,975

---

## TradingView Pro Connection

**Status**: Working

### Commands:
```bash
# Health check
python health_check.py

# Backtest today
python -m runners.run_today ES 3
python -m runners.run_today NQ 3

# Multi-day backtest
python -m runners.backtest_multiday ES 30
python -m runners.backtest_multiday NQ 30

# Run TradingView live monitor
python -m runners.run_tv_live

# If session expires, re-authenticate via browser:
python -m runners.tv_login
```

### Notes:
- TradingView session cached at `~/.tvdatafeed/`
- Strategy optimized for ES and NQ futures only
