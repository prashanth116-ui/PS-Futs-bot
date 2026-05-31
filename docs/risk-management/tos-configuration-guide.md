# ThinkorSwim (TOS) Options Risk Management Configuration Guide

**Account size: $5-10K | Single-leg options | Manual trading**

---

## 1. Configure Default Bracket Orders

This is the single most important setting. It forces a stop loss and profit target on EVERY trade automatically.

### Step-by-Step Setup

1. Open TOS desktop platform
2. Go to **Setup** (gear icon, top right) → **Order Defaults**
3. Select the **Options (Single)** tab
4. Configure:
   - **Order Type**: Limit
   - **Advanced Order**: Select **1st trgs OCO** (One-Cancels-Other bracket)
   - **Stop**: Market, Offset = your default stop percentage
   - **Limit (profit target)**: Limit, Offset = your target percentage
5. Click **Apply** then **OK**

Every option order you place now automatically attaches a stop loss and profit target. You cannot enter without a stop.

---

## 2. Bracket Order Entry (Per-Trade)

### From the Chart
1. Right-click on chart → **Buy Custom** → **With OCO Bracket**
2. Set your entry price (limit order)
3. The bracket auto-creates two linked orders:
   - **Stop (loss side)**: Set to 50% of premium paid
     - Example: Bought at $2.00 → stop at $1.00
   - **Limit (profit side)**: Set to 100% gain
     - Example: Bought at $2.00 → target at $4.00
4. Click **Confirm and Send**
5. All 3 orders go live as a linked group
6. When stop OR target fills, the other auto-cancels

### From the Trade Tab
1. Go to **Trade** tab → find your option
2. Right-click → **Buy** → **OCO Bracket**
3. Same bracket configuration as above

---

## 3. Order Templates (Save for Consistency)

Create templates so you don't recalculate every time.

### How to Save Templates
1. Setup → Order Defaults → configure your bracket settings
2. Click **Save as Template** → name it

### Recommended Templates

| Template | Stop (% of premium) | Target (% of premium) | Risk:Reward | Use Case |
|----------|---------------------|----------------------|-------------|----------|
| **Conservative** | -50% | +100% | 1:2 | Default for most trades |
| **Swing** | -40% | +150% | 1:3.75 | Multi-day holds with conviction |
| **Scalp** | -30% | +50% | 1:1.67 | Quick in-and-out, high probability |

### Template Setup Details

**Conservative (use this most often):**
- Entry: Limit order at your price
- Stop: 50% loss of premium (bought at $2.00, stop at $1.00)
- Target: 100% gain (bought at $2.00, target at $4.00)
- Net risk:reward = 1:2

**Swing:**
- Entry: Limit order at your price
- Stop: 40% loss of premium (bought at $2.00, stop at $1.20)
- Target: 150% gain (bought at $2.00, target at $5.00)
- Net risk:reward = 1:3.75

**Scalp:**
- Entry: Limit order at your price
- Stop: 30% loss of premium (bought at $2.00, stop at $1.40)
- Target: 50% gain (bought at $2.00, target at $3.00)
- Net risk:reward = 1:1.67

---

## 4. Position Sizing Rules ($5-10K Account)

| Rule | Value | Rationale |
|------|-------|-----------|
| Max risk per trade | 1-2% of account ($50-$200) | Survive 10+ consecutive losers |
| Max position size | 5% of account ($250-$500 premium) | Premium paid = max loss on long options |
| Max open positions | 3-4 simultaneously | Limits correlation risk |
| Max daily loss | 3% of account ($150-$300) | Stop trading for the day |
| Max weekly loss | 6% of account ($300-$600) | Reduce size next week |

### Position Sizing Formula

```
Max contracts = floor(Risk $ / (Option price x 100))
```

**Examples ($100 risk budget):**

| Option Price | Calculation | Contracts | Decision |
|-------------|-------------|-----------|----------|
| $0.50 | 100 / 50 = 2 | 2 | Take trade |
| $0.80 | 100 / 80 = 1.25 | 1 | Take trade |
| $1.50 | 100 / 150 = 0.67 | 0 | DON'T TRADE (or accept $150 risk for 1) |
| $2.50 | 100 / 250 = 0.4 | 0 | DON'T TRADE |
| $5.00 | 100 / 500 = 0.2 | 0 | DON'T TRADE |

**Key insight:** With a $5-10K account, you should be buying 1-3 contracts max per trade. If the option costs more than your risk budget per contract, skip it or find a cheaper strike.

### Quick Reference by Account Size

| Account Size | 1% Risk | 2% Risk | Max Position (5%) | Daily Limit (3%) |
|-------------|---------|---------|-------------------|-------------------|
| $5,000 | $50 | $100 | $250 | $150 |
| $7,500 | $75 | $150 | $375 | $225 |
| $10,000 | $100 | $200 | $500 | $300 |

---

## 5. Trailing Stop Strategy (Manual Process)

TOS doesn't support native trailing stops on options well. Use this alert-based approach:

### Method 1: Price Alerts on Underlying
1. After entry, set a **price alert** on the underlying stock/ETF at your trail trigger level
2. When alert fires → manually tighten stop to breakeven
3. Set another alert at next profit level → tighten stop again
4. Repeat until stopped out at profit or target hit

### Method 2: Conditional Orders (More Automated)
1. Enter your bracket order normally
2. Create a separate conditional order:
   - **Condition**: "Mark of [your option symbol] >= [2x your entry price]"
   - **Action**: Cancel existing stop, replace with trailing stop order
3. This auto-converts to a trailing stop once you're up 100%

### Suggested Trail Levels

| Option P/L | Action |
|-----------|--------|
| +50% | Move stop to breakeven (entry price) |
| +100% | Move stop to +50% (lock in profit) |
| +150% | Move stop to +100% |
| +200%+ | Trail stop at -25% from high |

---

## 6. Hard Rules for TOS Account

| # | Rule | Enforcement |
|---|------|-------------|
| 1 | Never remove a stop | Bracket orders make stops automatic |
| 2 | Take profit at target | Bracket auto-closes at limit |
| 3 | Max 3% daily loss | After 3 losing trades → close TOS for the day |
| 4 | No revenge trading | If hit daily loss → physically close the platform |
| 5 | Size down after losses | 2 consecutive losses → cut position size by 50% |
| 6 | No averaging down | NEVER add to a losing option position |
| 7 | No holding through earnings | Close before earnings unless that's the thesis |
| 8 | Check IV before entry | High IV = expensive premium = smaller size |
| 9 | 1-3 contracts max | Position sizing formula enforces this |
| 10 | Journal every trade | Screenshot the chart + bracket + write 1 sentence on why |
