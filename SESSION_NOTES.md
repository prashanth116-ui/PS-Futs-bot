# Session Notes - 2026-01-29

## Strategy Upgrade: V3-StructureTrail

### Changes Made:
1. **EMA Filter Fix**: Now checks EMA at entry time (not end of session)
   - Allows early session trades when EMA can't be calculated yet (<50 bars)
   - Fixed SHORT trade being blocked on 1/29

2. **Tiered Structure Trail** (replaces fixed 4R/8R exits):
   - **1st contract**: Fast trail after 4R touch (2-tick buffer)
   - **2nd contract**: Standard trail after 8R touch (4-tick buffer)
   - **3rd contract (Runner)**: Opposing FVG or +4R trailing stop

### Backtest Results (30 days):
- Win Rate: 27-33%
- Avg Win: $3,723 | Avg Loss: $397
- Profit Factor: 3.51
- Total P/L: +$23,975

### 1/29 Trade Example:
- Entry: SHORT @ 7020.75
- Old exits: 4R=$400, 8R=$800, Runner=$3,400 = **$4,600**
- New exits: T1=$5,037, T2=$5,012, Runner=$4,725 = **$14,775**

## TradingView Pro Connection

**Status**: Working

### Commands:
```bash
# Health check
python health_check.py

# Backtest today
PYTHONPATH=. python runners/run_today.py ES 3

# Multi-day backtest
PYTHONPATH=. python runners/backtest_multiday.py ES 30

# Run TradingView live monitor
PYTHONPATH=. python runners/run_tv_live.py

# If session expires, re-authenticate via browser:
python runners/tv_login.py
```

### Files modified:
- `runners/run_today.py` - V3-StructureTrail with tiered exits
- `runners/run_tv_live.py` - Cached session with retry logic

### Notes:
- TradingView session cached at `~/.tvdatafeed/`
- Strategy verified over 17 trading days - no bugs found
