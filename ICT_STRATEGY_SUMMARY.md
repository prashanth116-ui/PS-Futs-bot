# ICT Re-entry Strategy Summary

## Strategy Overview

| Component | Details |
|-----------|---------|
| **Instrument** | ES (E-mini S&P 500) or MES (Micro) |
| **Timeframe** | 3-minute charts |
| **Session** | 4:00 AM - 4:00 PM ET |
| **Direction** | LONG and SHORT |

---

## Entry Rules

1. **Detect Fair Value Gap (FVG)**
   - Minimum 4 ticks gap size
   - Bullish FVG for LONG, Bearish FVG for SHORT

2. **Entry Price**
   - Enter at FVG midpoint when price retraces

3. **Stop Loss - FVG Mitigation**
   - LONG: Exit only if candle CLOSES below FVG low
   - SHORT: Exit only if candle CLOSES above FVG high
   - Wicks/spikes do NOT trigger stop
   - FVG remains valid until truly mitigated

4. **Re-entry Rule**
   - If stopped out on 1st FVG → re-enter on 2nd FVG
   - Same direction, same rules

---

## Exit Rules (Scaled)

| Target | Contracts | Exit Condition |
|--------|-----------|----------------|
| **4R** | 1/3 | 4x risk from entry |
| **8R** | 1/3 | 8x risk from entry |
| **Runner** | 1/3 | Close below/above EMA50 |

---

## Position Sizing

| Account Size | ES Contracts | MES Contracts |
|--------------|--------------|---------------|
| $5,000 | 1 | 10 |
| $10,000 | 2 | 20 |
| $15,000 | 3 | 30 |
| $20,000+ | 4+ | 40+ |

**Rule:** Risk 2% per trade maximum

---

## Backtest Results (15 Days: Jan 11-27, 2026)

| Metric | ES (3 cts) | MES (3 cts) |
|--------|------------|-------------|
| Total Trades | 13 | 15 |
| Win Rate | 61.5% | 53.3% |
| Profit Factor | 10.60 | 6.88 |
| **Total P/L** | **+$11,162** | **+$959** |
| Long P/L | +$4,512 | +$188 |
| Short P/L | +$6,650 | +$771 |
| Avg per Trade | +$859 | +$64 |
| Monthly ROI | +99% | +99% |

---

## Capital Requirements

| Risk Level | Capital for 3 ES | Risk per Trade |
|------------|------------------|----------------|
| Conservative (1%) | $30,000 | $300 |
| **Recommended (2%)** | **$15,000** | **$300** |
| Aggressive (3%) | $10,000 | $300 |

---

## Key Features

- **Re-entry mechanism** captures big moves after initial stop-outs
- **Scaled exits** lock in profits while letting runners ride
- **EMA50 runner** maximizes trend continuation
- **4R/8R targets** optimal balance of win rate vs reward

---

## Daily Workflow

```
1. Identify bias (LONG or SHORT)
2. Wait for FVG formation
3. Set limit order at FVG midpoint
4. Place stop below/above FVG
5. Scale out: 4R → 8R → EMA50 cross
6. If stopped: re-enter on 2nd FVG
```

---

## Expected Performance

| Timeframe | 1 ES | 3 ES | 3 MES |
|-----------|------|------|-------|
| Daily | +$248 | +$744 | +$74 |
| Weekly | +$1,240 | +$3,721 | +$372 |
| Monthly | +$4,961 | +$14,883 | +$1,488 |

---

## Risk Management

### Drawdown Scenarios (3 ES Contracts)

| Consecutive Losses | Drawdown | % of $15K Account |
|--------------------|----------|-------------------|
| 2 | -$465 | 3.1% |
| 3 | -$698 | 4.7% |
| 4 | -$930 | 6.2% |
| 5 | -$1,163 | 7.8% |

### Probability of Losing Streaks (61.5% Win Rate)

| Streak | Probability |
|--------|-------------|
| 2 losses | 14.8% |
| 3 losses | 5.7% |
| 4 losses | 2.2% |
| 5 losses | 0.85% |

---

## Scaling Plan

| Account Balance | Action |
|-----------------|--------|
| $5,000 - $10,000 | Trade 1 ES or 10 MES |
| $10,000 - $15,000 | Trade 2 ES or 20 MES |
| $15,000 - $20,000 | Trade 3 ES or 30 MES |
| $20,000+ | Scale further |

---

## Files Reference

| File | Description |
|------|-------------|
| `runners/run_full_backtest.py` | Main backtest engine |
| `runners/run_mes_backtest.py` | MES backtest |
| `runners/plot_today_trade.py` | Plot daily trade |
| `strategies/ict/signals/fvg.py` | FVG detection logic |

---

## Notes

- Strategy performs better on ES than NQ (more trade opportunities)
- Short trades slightly outperform long trades in backtest period
- Re-entry mechanism added +$3,869 on Jan 26 alone
- EMA50 runner captures extended moves beyond 8R

---

*Strategy developed and backtested: January 2026*
