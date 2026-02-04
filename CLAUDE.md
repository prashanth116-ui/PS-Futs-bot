# Project Instructions

## On Session Start
Run the health check script at the beginning of each session:
```
python health_check.py
```

## Project Overview
Tradovate futures trading bot using ICT (Inner Circle Trader) strategy.

## Current Strategy: V10.1 (Quad Entry + ADX Filter) - Feb 4, 2026

### Supported Instruments (ES/NQ Only)
| Symbol | Exchange | Tick Value | Min Risk |
|--------|----------|------------|----------|
| ES | CME_MINI | $12.50 | 1.5 pts |
| NQ | CME_MINI | $5.00 | 6.0 pts |

### V10.1 Entry Types
| Type | Name | Description |
|------|------|-------------|
| A | Creation | Enter immediately when FVG forms with displacement |
| B1 | Overnight Retrace | Enter when price retraces into overnight FVG + rejection **(ADX >= 22)** |
| B2 | Intraday Retrace | Enter when price retraces into session FVG (5+ bars old) + rejection |
| C | BOS + Retrace | Enter when price retraces into FVG after Break of Structure |

### Hybrid Exit Structure
```
Entry: 3 contracts at FVG midpoint
    ↓ Price hits 4R target
T1 (1 ct): FIXED profit at 4R - guaranteed, isolated from trail
    ↓ Price hits 8R target
T2 (1 ct): Structure trail with 4-tick buffer
Runner (1 ct): Structure trail with 6-tick buffer
    ↓ Swing pullback
T2/Runner exit on respective trail stops or EOD
```

### Strategy Features
- **Quad Entry Mode**: 4 distinct entry types (Creation, Overnight, Intraday, BOS)
- **Hybrid Exit**: T1 fixed at 4R, T2/Runner structure trail
- **ADX Filter for B1**: Overnight retrace requires ADX >= 22 (filters weak trends)
- **2nd Entry**: INDEPENDENT - taken regardless of 1st trade status
- **Position Limit**: Max 2 open trades total (combined LONG + SHORT)
- **Stop**: FVG boundary + 2 tick buffer

### Filters
| Filter | Value | Purpose |
|--------|-------|---------|
| Min FVG | 5 ticks | Filter tiny gaps |
| Min Risk | ES:1.5, NQ:6.0 pts | Skip small FVGs with tight targets |
| Displacement | 1.0x avg body | Lower threshold for more setups |
| HTF Bias | EMA 20/50 | Trade with trend |
| ADX | > 17 | Only trending markets |
| **B1 ADX** | **>= 22** | **Overnight retrace only in strong trends (+$6,800/14d)** |
| DI Direction | +DI/-DI | LONG if +DI > -DI, SHORT if -DI > +DI |
| Morning Only | Overnight retrace | B1 entries only 9:30-12:00 |
| Max Losses | 2/day | Circuit breaker |
| Max Open Trades | 2 | Combined position limit |

### 12-Day Backtest Results
| Symbol | Trades | Wins | Losses | Win Rate | PF | Total P/L |
|--------|--------|------|--------|----------|-----|-----------|
| ES | 37 | 21 | 16 | 56.8% | 5.47 | +$40,988 |
| NQ | 38 | 20 | 18 | 52.6% | 11.04 | +$105,913 |
| **Combined** | **75** | **41** | **34** | **54.7%** | **7.70** | **+$146,901** |

### Entry Type Breakdown
| Entry Type | ES | NQ | Total |
|------------|-----|-----|-------|
| Creation | 15 (40.5%) | 15 (39.5%) | 30 (40%) |
| Overnight | 15 (40.5%) | 13 (34.2%) | 28 (37%) |
| Intraday | 4 (10.8%) | 4 (10.5%) | 8 (11%) |
| BOS | 3 (8.1%) | 6 (15.8%) | 9 (12%) |

### Key Insights
- Strategy is "home run" dependent - big trending days drive profits
- Winning days avg 85 pts range vs 53 pts on losing days
- Creation entries perform best (73% on winning days)
- Breakeven at 2R tested but REJECTED - hurts runners more than helps

## Key Commands

### Backtesting
```bash
# V10 backtest today
python -m runners.run_v10_dual_entry ES 3

# V10 multi-day backtest (30 days)
python -m runners.backtest_v10_multiday ES 30
python -m runners.backtest_v10_multiday NQ 30

# Analyze winning vs losing days
python -m runners.analyze_win_loss ES
```

### Plotting
```bash
# Plot V10 today
python -m runners.plot_v10 ES 3

# Plot V10 specific date
python -m runners.plot_v10_date 2026 2 3
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
| `runners/run_v10_dual_entry.py` | V10 Quad Entry strategy (current) |
| `runners/backtest_v10_multiday.py` | V10 multi-day backtest |
| `runners/plot_v10.py` | V10 trade visualization |
| `runners/plot_v10_date.py` | V10 date-specific plotting |
| `runners/analyze_win_loss.py` | Win/loss day analysis |
| `runners/run_tv_live.py` | Live TradingView monitor |
| `runners/tv_login.py` | TradingView browser auth |
| `config/strategies/ict_es.yaml` | ES configuration |
| `config/strategies/ict_nq.yaml` | NQ configuration |

### Strategy Functions
| Function | Description |
|----------|-------------|
| `run_session_v10()` | V10 Quad Entry with hybrid exit (current) |
| `run_session_with_position_limit()` | V8-Independent with position limit |
| `run_multi_trade()` | V7-MultiEntry with profit-protected 2nd entry |
| `run_trade()` | V6-Aggressive single entry (legacy) |

## Daily Workflow

1. **Morning**: `python health_check.py`
2. **Pre-market**: `python -m runners.run_v10_dual_entry ES 3` (review signals)
3. **Market hours**: `python -m runners.run_tv_live` (monitor)
4. **Post-market**: `python -m runners.plot_v10 ES 3` (review)

## TradingView Connection
- Session cached at `~/.tvdatafeed/`
- If data shows "nologin method", run `python -m runners.tv_login`

## Strategy Evolution
| Version | Key Feature |
|---------|-------------|
| V10.1 | ADX >= 22 filter for Overnight Retrace (+$6,800/14d improvement) |
| V10 | Quad Entry (Creation, Overnight, Intraday, BOS) + Hybrid Exit |
| V9 | Min Risk Filter + Opposing FVG Exit |
| V8 | Independent 2nd Entry + Position Limit |
| V7 | Profit-Protected 2nd Entry |
| V6 | Aggressive FVG Creation Entry |
