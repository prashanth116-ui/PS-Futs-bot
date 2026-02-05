# Project Instructions

## On Session Start
Run the health check script at the beginning of each session:
```
python health_check.py
```

## Project Overview
Tradovate futures trading bot using ICT (Inner Circle Trader) strategy.

## Current Strategy: V10.3 (Quad Entry + Optimized Filters) - Feb 4, 2026

### Supported Instruments
| Symbol | Type | Tick Value | Min Risk | Max BOS Risk |
|--------|------|------------|----------|--------------|
| ES | Futures | $12.50 | 1.5 pts | 8.0 pts |
| NQ | Futures | $5.00 | 6.0 pts | 20.0 pts |
| SPY | Equity | per share | $0.30 | - |
| QQQ | Equity | per share | $0.50 | - |

### V10.3 Entry Types
| Type | Name | Description |
|------|------|-------------|
| A | Creation | Enter immediately when FVG forms with displacement |
| B1 | Overnight Retrace | Enter when price retraces into overnight FVG + rejection **(ADX >= 22)** |
| B2 | Intraday Retrace | Enter when price retraces into session FVG (5+ bars old) + rejection **[Disabled for SPY]** |
| C | BOS + Retrace | Enter when price retraces into FVG after Break of Structure **(Risk capped)** |

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
| **Max BOS Risk** | **ES:8, NQ:20 pts** | **Cap oversized BOS entries** |
| Displacement | 1.0x avg body | Lower threshold for more setups |
| HTF Bias | EMA 20/50 | Trade with trend |
| ADX | > 17 | Only trending markets |
| **B1 ADX** | **>= 22** | **Overnight retrace only in strong trends** |
| DI Direction | +DI/-DI | LONG if +DI > -DI, SHORT if -DI > +DI |
| Morning Only | Overnight retrace | B1 entries only 9:30-12:00 |
| **Midday Cutoff** | **12:00-14:00** | **No entries during lunch lull** |
| **PM Cutoff** | **NQ/QQQ only** | **No NQ/QQQ entries after 14:00** |
| **SPY INTRADAY** | **Disabled** | **Skip SPY B2 entries (24% WR drag)** |
| Max Losses | 2/day | Circuit breaker |
| Max Open Trades | 2 | Combined position limit |

### 13-Day Backtest Results (V10.3)
| Symbol | Trades | Wins | Losses | Win Rate | PF | Total P/L |
|--------|--------|------|--------|----------|-----|-----------|
| ES | 41 | 26 | 15 | 63.4% | 11.19 | +$48,594 |
| NQ | 31 | 21 | 10 | 67.7% | 19.39 | +$108,418 |
| **Futures** | **72** | **47** | **25** | **65.3%** | **14.39** | **+$157,012** |

### 30-Day Equity Results (V10.3)
| Symbol | Trades | Wins | Losses | Win Rate | PF | Total P/L |
|--------|--------|------|--------|----------|-----|-----------|
| SPY | 46 | 27 | 19 | 58.7% | 10.16 | +$86,943 |
| QQQ | 67 | 38 | 29 | 56.7% | 5.40 | +$63,729 |
| **Equities** | **113** | **65** | **48** | **57.5%** | **7.10** | **+$150,672** |

### Entry Type Breakdown (Futures)
| Entry Type | ES | NQ | Total |
|------------|-----|-----|-------|
| Creation | 21 (51%) | 16 (52%) | 37 (51%) |
| Overnight | 11 (27%) | 12 (39%) | 23 (32%) |
| Intraday | 4 (10%) | 1 (3%) | 5 (7%) |
| BOS | 5 (12%) | 2 (6%) | 7 (10%) |

### Key Insights
- Strategy is "home run" dependent - big trending days drive profits
- Creation entries dominate profits across all symbols
- BOS risk cap prevents oversized losses (ES -$900 improvement)
- SPY INTRADAY disabled: 41% → 59% win rate, +$16k improvement
- NQ benefits most from time filters (69% day win rate)

## Key Commands

### Backtesting
```bash
# V10 futures backtest today
python -m runners.run_v10_dual_entry ES 3
python -m runners.run_v10_dual_entry NQ 3

# V10 equity backtest today (SPY/QQQ)
python -m runners.run_v10_equity SPY 500   # $500 risk per trade
python -m runners.run_v10_equity QQQ 500

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
| `runners/run_v10_dual_entry.py` | V10 Quad Entry strategy - futures (ES/NQ) |
| `runners/run_v10_equity.py` | V10 Quad Entry strategy - equities (SPY/QQQ) |
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
| `run_session_v10()` | V10 Quad Entry - futures (ES/NQ) |
| `run_session_v10_equity()` | V10 Quad Entry - equities (SPY/QQQ) |
| `run_session_with_position_limit()` | V8-Independent with position limit |
| `run_multi_trade()` | V7-MultiEntry with profit-protected 2nd entry |
| `run_trade()` | V6-Aggressive single entry (legacy) |

### Equity vs Futures Differences
| Aspect | Futures (ES/NQ) | Equities (SPY/QQQ) |
|--------|-----------------|-------------------|
| Position Size | Fixed contracts (3) | Risk-based shares |
| P/L Calculation | ticks × tick_value | shares × price move |
| Stop Buffer | 2 ticks | $0.02 |
| Trail Buffer | 4-6 ticks | $0.04-0.06 |
| Risk Input | N/A | $ per trade |

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
| V10.3 | BOS risk cap (ES:8, NQ:20) + Disable SPY INTRADAY (+$19,692 improvement) |
| V10.2 | Midday cutoff (12-14) + NQ/QQQ PM cutoff (+$10,340/13d improvement) |
| V10.1 | ADX >= 22 filter for Overnight Retrace |
| V10 | Quad Entry (Creation, Overnight, Intraday, BOS) + Hybrid Exit |
| V9 | Min Risk Filter + Opposing FVG Exit |
| V8 | Independent 2nd Entry + Position Limit |
| V7 | Profit-Protected 2nd Entry |
| V6 | Aggressive FVG Creation Entry |
