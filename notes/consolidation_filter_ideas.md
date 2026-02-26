# Consolidation Detection Filter Ideas (3-Min Chart)

## Problem
Avoid entries during consolidation/chop on 3-minute bars.

## Current Bot Coverage
- Displacement >= 1.0x avg body
- ADX >= 11 (>= 22 for B1 overnight retrace)
- DI direction (+DI vs -DI)
- EMA20/EMA50 trend alignment
- Midday cutoff 12:00-14:00

## Potential New Filter: Range Compression Detection
Detect when last N bars (e.g., 10 bars = 30 min) are all within a tight range, and suppress entries until a breakout.

### Indicators to Consider
- Range of last 10 bars vs ATR (if range < 0.5x ATR, consolidation)
- Bollinger Band width squeeze (bands narrowing)
- ADX slope (falling ADX = trend weakening even if above threshold)
- +DI/-DI separation distance (close together = no direction)
- EMA20/EMA50 slope going flat
- FVG fill rate (FVGs getting filled within 1-2 bars = no follow-through)
- Volume vs session average (below average = low conviction)
- Count of doji/small-body candles in recent window

### Implementation Approach
1. Backtest current strategy and tag trades that occurred during consolidation
2. Measure win rate of those trades vs trending trades
3. If consolidation trades have significantly lower WR, add a filter
4. A/B test the filter over 15+ days

## Next Step
Ask Claude: "Add a consolidation detection filter to the ICT sweep strategy on 3-min bars. Use range compression (last 10 bars vs ATR) as the primary signal. Backtest with and without the filter on ES over 15 days to measure impact."
