# Position Sizing Quick Reference Sheet

Print this out and keep it next to your monitor.

---

## Options (TOS) — $5-10K Account

### Formula
```
Max contracts = floor(Risk $ / (Option price x 100))
```

### Lookup Table (1% risk = $50-$100)

| Option Price | $50 Risk | $100 Risk | $150 Risk | $200 Risk |
|-------------|----------|-----------|-----------|-----------|
| $0.25 | 2 ct | 4 ct | 6 ct | 8 ct |
| $0.50 | 1 ct | 2 ct | 3 ct | 4 ct |
| $0.75 | 0 - SKIP | 1 ct | 2 ct | 2 ct |
| $1.00 | 0 - SKIP | 1 ct | 1 ct | 2 ct |
| $1.50 | 0 - SKIP | 0 - SKIP | 1 ct | 1 ct |
| $2.00 | 0 - SKIP | 0 - SKIP | 0 - SKIP | 1 ct |
| $3.00 | 0 - SKIP | 0 - SKIP | 0 - SKIP | 0 - SKIP |

**If the table says SKIP, the option is too expensive for your risk budget. Find a cheaper strike or don't take the trade.**

### Account Size Limits

| Account | 1% Risk | 2% Risk | Max Position (5%) | Daily Limit (3%) | Weekly Limit (6%) |
|---------|---------|---------|-------------------|-------------------|--------------------|
| $5,000 | $50 | $100 | $250 | $150 | $300 |
| $6,000 | $60 | $120 | $300 | $180 | $360 |
| $7,000 | $70 | $140 | $350 | $210 | $420 |
| $8,000 | $80 | $160 | $400 | $240 | $480 |
| $9,000 | $90 | $180 | $450 | $270 | $540 |
| $10,000 | $100 | $200 | $500 | $300 | $600 |

---

## Futures (Tradovate) — $50K Prop Firm

### Formula
```
Risk per trade = Daily loss limit / 5
Contracts = Risk per trade / (Stop in pts x Point value)
```

**Point values:**
- ES: $50/point (4 ticks x $12.50)
- NQ: $20/point (4 ticks x $5.00)
- MES: $5/point (4 ticks x $1.25)
- MNQ: $2/point (4 ticks x $0.50)

### ES Contract Lookup ($200 risk budget)

| Stop (pts) | Stop (ticks) | Risk/Contract | Max Contracts | Total Risk |
|-----------|-------------|--------------|---------------|------------|
| 1.00 | 4 | $50 | 4 | $200 |
| 1.50 | 6 | $75 | 2 | $150 |
| 2.00 | 8 | $100 | 2 | $200 |
| 2.50 | 10 | $125 | 1 | $125 |
| 3.00 | 12 | $150 | 1 | $150 |
| 4.00 | 16 | $200 | 1 | $200 |
| 5.00 | 20 | $250 | 0 - SKIP | — |

### NQ Contract Lookup ($200 risk budget)

| Stop (pts) | Stop (ticks) | Risk/Contract | Max Contracts | Total Risk |
|-----------|-------------|--------------|---------------|------------|
| 2.50 | 10 | $50 | 4 | $200 |
| 3.75 | 15 | $75 | 2 | $150 |
| 5.00 | 20 | $100 | 2 | $200 |
| 7.50 | 30 | $150 | 1 | $150 |
| 10.00 | 40 | $200 | 1 | $200 |
| 12.50 | 50 | $250 | 0 - SKIP | — |

### MES Contract Lookup ($200 risk budget)

| Stop (pts) | Stop (ticks) | Risk/Contract | Max Contracts | Total Risk |
|-----------|-------------|--------------|---------------|------------|
| 1.00 | 4 | $5.00 | 40 | $200 |
| 2.00 | 8 | $10.00 | 20 | $200 |
| 3.00 | 12 | $15.00 | 13 | $195 |
| 4.00 | 16 | $20.00 | 10 | $200 |
| 5.00 | 20 | $25.00 | 8 | $200 |

### MNQ Contract Lookup ($200 risk budget)

| Stop (pts) | Stop (ticks) | Risk/Contract | Max Contracts | Total Risk |
|-----------|-------------|--------------|---------------|------------|
| 2.50 | 10 | $5.00 | 40 | $200 |
| 5.00 | 20 | $10.00 | 20 | $200 |
| 7.50 | 30 | $15.00 | 13 | $195 |
| 10.00 | 40 | $20.00 | 10 | $200 |
| 12.50 | 50 | $25.00 | 8 | $200 |

---

## Bracket Order Quick Reference

### ES Default Bracket
```
Stop:   8 ticks (2 pts) = $100/contract
T1:    12 ticks (3 pts) = $150/contract  [close half]
T2:    20 ticks (5 pts) = $250/contract  [close rest]
```

### NQ Default Bracket
```
Stop:  20 ticks (5 pts)  = $100/contract
T1:    30 ticks (7.5 pts) = $150/contract  [close half]
T2:    60 ticks (15 pts)  = $300/contract  [close rest]
```

---

## Drawdown Scaling Protocol (Prop Firm)

| Drawdown Used | Max Contracts (ES) | Max Contracts (NQ) | Action |
|--------------|-------------------|-------------------|--------|
| 0-30% | 2 | 2 | Normal trading |
| 30-50% | 1 | 1 | Reduced size |
| 50-70% | MES only (10 ct) | MNQ only (10 ct) | Micro contracts only |
| 70%+ | 0 | 0 | STOP — reassess |

---

## Key Numbers to Memorize

| Metric | Value |
|--------|-------|
| ES tick value | $12.50 |
| NQ tick value | $5.00 |
| MES tick value | $1.25 |
| MNQ tick value | $0.50 |
| ES point = ticks | 4 ticks |
| NQ point = ticks | 4 ticks |
| ES 1 point loss (1 ct) | $50 |
| NQ 1 point loss (1 ct) | $20 |
| Your daily loss limit | $1,000 |
| Your per-trade risk | $200 |
| Max trades before stopping | 5 (or 2 consecutive losses) |
