# Tradovate Prop Firm Futures Risk Management Configuration Guide

**Account: $50K evaluation | ES/NQ futures | Manual trading**

---

## 1. Configure Default Bracket Orders

### Step-by-Step Setup

1. Open Tradovate → **Settings** (gear icon)
2. Go to **Trading** → **Order Ticket**
3. Enable **Bracket Order** as default order type
4. Set default bracket offsets:

| Symbol | Stop Loss (ticks) | Stop Loss (points) | Take Profit (ticks) | Take Profit (points) |
|--------|-------------------|--------------------|--------------------|---------------------|
| ES | 8 ticks | 2 points ($100/ct) | 16 ticks | 4 points ($200/ct) |
| NQ | 20 ticks | 5 points ($100/ct) | 40 ticks | 10 points ($200/ct) |
| MES | 8 ticks | 2 points ($10/ct) | 16 ticks | 4 points ($20/ct) |
| MNQ | 20 ticks | 5 points ($10/ct) | 40 ticks | 10 points ($20/ct) |

5. Click **Save** — these attach to EVERY order automatically

---

## 2. Risk Management Settings

### In Tradovate: Settings → Risk Management

1. **Max Position Size** (per symbol):
   - ES: 6 contracts max
   - NQ: 4 contracts max
   - MES: 10 contracts max
   - MNQ: 8 contracts max

2. **Max Daily Loss**: Set to 50-60% of your prop firm's daily loss limit
   - Prop allows -$2,000/day → set Tradovate limit to **-$1,200**
   - Prop allows -$1,500/day → set Tradovate limit to **-$900**
   - This buffer prevents the prop firm from force-closing your account

3. **Max Loss Per Trade**:
   - ES: $200/contract ($400 for 2 contracts)
   - NQ: $200/contract ($400 for 2 contracts)

---

## 3. Position Sizing for $50K Prop Firm Eval

### Typical Prop Firm Rules

| Rule | Typical Limit | Your Conservative Setting |
|------|--------------|---------------------------|
| Trailing Max Drawdown | $2,500 | Stay above -$1,500 |
| Daily Loss Limit | $1,500-$2,000 | Your limit: -$1,000 |
| Max Contracts | 10 | Your limit: 4-6 |
| Profit Target | $3,000-$4,000 | Aim for consistent $200-400/day |
| EOD Flat Required | Sometimes | Always flatten by 15:30 ET |

### Position Sizing Formula

```
Risk per trade = Daily loss limit / 5 trades
Contracts = Risk per trade / (Stop distance x Tick value)
```

**ES examples:**
```
Daily limit: $1,000 / 5 = $200 per trade
Stop: 2 points (8 ticks)
Per-contract risk: 2 pts x $12.50/tick x 4 ticks/pt = $100
Contracts: $200 / $100 = 2 contracts
```

**NQ examples:**
```
Daily limit: $1,000 / 5 = $200 per trade
Stop: 5 points (20 ticks)
Per-contract risk: 5 pts x $5/tick x 4 ticks/pt = $100
Contracts: $200 / $100 = 2 contracts
```

### Quick Reference Table

| Stop (ES pts) | Risk/Contract | Contracts @ $200 risk | Total Risk |
|--------------|--------------|----------------------|------------|
| 1.5 pts | $75 | 2 | $150 |
| 2.0 pts | $100 | 2 | $200 |
| 2.5 pts | $125 | 1 | $125 |
| 3.0 pts | $150 | 1 | $150 |
| 4.0 pts | $200 | 1 | $200 |

| Stop (NQ pts) | Risk/Contract | Contracts @ $200 risk | Total Risk |
|--------------|--------------|----------------------|------------|
| 3.0 pts | $60 | 3 | $180 |
| 5.0 pts | $100 | 2 | $200 |
| 7.5 pts | $150 | 1 | $150 |
| 10.0 pts | $200 | 1 | $200 |

**Rule: If the stop distance means you can only trade 1 contract at $200 risk, that's fine. NEVER increase risk to fit more contracts.**

---

## 4. Bracket Order Templates

### ES Conservative (Use During Eval)

```
Contracts: 2
Stop: 8 ticks (2 points)
  → $100/contract = $200 total risk

Target 1: 12 ticks (3 points) — close 1 contract
  → $150 profit, risk:reward = 1:1.5

Target 2: 20 ticks (5 points) — close 1 contract
  → $250 profit, risk:reward = 1:2.5

Best case: $150 + $250 = $400 profit on $200 risk (2R)
Worst case: -$200 (both stopped)
```

### ES Aggressive (After Passing Eval)

```
Contracts: 3
Stop: 8 ticks (2 points)
  → $100/contract = $300 total risk

Target 1: 12 ticks (3 points) — close 1 contract → move stop to breakeven
  → $150 locked

Target 2: 20 ticks (5 points) — close 1 contract
  → $250 locked

Runner: Trail with 8-tick trailing stop until stopped out
  → Unlimited upside on trend days

Best case: $150 + $250 + runner profit
Worst case: -$300 (all stopped)
After T1: -$100 worst case (1 stopped at BE, 1 stopped at original stop)
```

### NQ Conservative (Use During Eval)

```
Contracts: 2
Stop: 20 ticks (5 points)
  → $100/contract = $200 total risk

Target 1: 30 ticks (7.5 points) — close 1 contract
  → $150 profit, risk:reward = 1:1.5

Target 2: 60 ticks (15 points) — close 1 contract
  → $300 profit, risk:reward = 1:3

Best case: $150 + $300 = $450 profit on $200 risk (2.25R)
Worst case: -$200 (both stopped)
```

### NQ Aggressive (After Passing Eval)

```
Contracts: 3
Stop: 20 ticks (5 points)
  → $100/contract = $300 total risk

Target 1: 30 ticks — close 1 → move stop to breakeven
Target 2: 60 ticks — close 1
Runner: Trail with 16-tick trailing stop

Best case: $150 + $300 + runner profit
Worst case: -$300 (all stopped)
```

---

## 5. Trailing Stop Procedure

### Step-by-Step During a Trade

1. **Entry**: Place bracket order (stop + target attached automatically)
2. **T1 Hit**: First target fills, 1 contract closed
   - Immediately modify the stop on remaining contracts → move to **breakeven** (entry price)
3. **Convert to trailing stop** (for remaining contracts):
   - Right-click the stop order in the Orders panel
   - Select **Modify**
   - Change order type to **Trailing Stop**
   - Set trail distance:
     - ES: 8 ticks (2 points)
     - NQ: 16 ticks (4 points)
4. **Let it ride** until trailing stop triggers or T2/target hits

### Trailing Stop Reference

| Symbol | Trail Distance | Trail (points) | Trail ($) |
|--------|---------------|----------------|-----------|
| ES | 8 ticks | 2 points | $100/contract |
| NQ | 16 ticks | 4 points | $80/contract |
| MES | 8 ticks | 2 points | $10/contract |
| MNQ | 16 ticks | 4 points | $8/contract |

---

## 6. Prop Firm Survival Rules

| # | Rule | Why | Enforcement |
|---|------|-----|-------------|
| 1 | Max 2-3 trades per day | Quality over quantity | Self-discipline, close after 3 |
| 2 | Stop after 2 consecutive losses | Prevents tilt/revenge trading | Close the platform |
| 3 | Never move stop further away | #1 account killer | Bracket order enforces this |
| 4 | Always take T1 at target | Locks in partial profit | OCO bracket auto-closes |
| 5 | Flatten by 15:30 ET | Avoid overnight risk + prop rules | Set alarm at 15:25 |
| 6 | Risk max $200 per trade | 5 full losses = daily limit | Position sizing formula |
| 7 | No trading first 15 min | Opening volatility is random | Wait for 09:45 ET or later |
| 8 | Journal every trade | Identify patterns, improve | Screenshot + notes |
| 9 | No trading during FOMC/CPI/NFP | Unpredictable moves, wide stops | Check economic calendar AM |
| 10 | Reduce size after drawdown | -$500 DD → cut to 1 contract | Reassess at halfway to limit |

### Drawdown Management Protocol

| Trailing Drawdown Used | Action |
|----------------------|--------|
| 0-30% ($0-$750) | Normal trading, 2 contracts |
| 30-50% ($750-$1,250) | Reduce to 1 contract |
| 50-70% ($1,250-$1,750) | 1 MES/MNQ only (micro contracts) |
| 70%+ ($1,750+) | STOP TRADING — reassess strategy |

---

## 7. Daily Routine for Prop Firm

### Pre-Market (8:00-9:15 ET)
- [ ] Check overnight price action on ES/NQ
- [ ] Identify key levels (prior day high/low, overnight high/low, weekly pivots)
- [ ] Check economic calendar for news events
- [ ] Set price alerts at key levels in Tradovate
- [ ] Verify bracket order defaults are set correctly

### Market Open (9:30-9:45 ET)
- [ ] DO NOT TRADE — observe opening volatility
- [ ] Note which direction price moves off the open
- [ ] Watch for FVG formation on 3-min chart

### Trading Session (9:45-15:30 ET)
- [ ] Execute setups per the strategy — bracket orders only
- [ ] After each trade: journal immediately
- [ ] After 2 consecutive losses: DONE for the day
- [ ] After hitting -$1,000: DONE for the day

### Close (15:30-16:00 ET)
- [ ] Flatten all positions by 15:30 ET
- [ ] Review P&L for the day
- [ ] Complete trade journal
- [ ] Note lessons learned
