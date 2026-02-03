# V9 Alert Webhook Setup Guide

Get instant phone notifications when V9 trading signals form.

## Quick Start (5 minutes)

### Option A: Telegram (Recommended)

**Step 1: Create Telegram Bot**
1. Open Telegram, search for `@BotFather`
2. Send `/newbot`
3. Choose a name (e.g., "V9 Trading Alerts")
4. Choose a username (e.g., "v9_trading_bot")
5. Copy the **bot token** (looks like `123456789:ABCdefGHI...`)

**Step 2: Get Your Chat ID**
1. Message your new bot (send "hello")
2. Open browser: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Find `"chat":{"id":123456789}` - that's your chat ID

**Step 3: Configure**
```bash
cd alerts
copy .env.example .env
# Edit .env with your token and chat_id
```

**Step 4: Install Dependencies**
```bash
pip install flask requests python-dotenv
```

**Step 5: Run Server**
```bash
python -m alerts.webhook_server
```

**Step 6: Expose to Internet (ngrok)**
```bash
# In new terminal
ngrok http 5000
# Copy the https URL (e.g., https://abc123.ngrok.io)
```

**Step 7: Test**
- Open browser: `http://localhost:5000/test`
- You should receive a test message on Telegram!

---

## TradingView Alert Setup

### Step 1: Add Alert
1. Open TradingView chart with V9 indicator
2. Right-click chart → **Add Alert**
3. Condition: **V9 ICT FVG Strategy** → **V9 Any Signal**

### Step 2: Configure Webhook
1. Check **Webhook URL**
2. Enter your ngrok URL + `/webhook`:
   ```
   https://abc123.ngrok.io/webhook
   ```

### Step 3: Alert Message (JSON format)
```json
{
  "ticker": "{{ticker}}",
  "exchange": "{{exchange}}",
  "price": "{{close}}",
  "time": "{{time}}",
  "signal": "{{strategy.order.action}}",
  "message": "V9 {{strategy.order.action}}: {{ticker}} @ {{close}}"
}
```

Or simple text:
```
V9 {{strategy.order.action}}: {{ticker}} @ {{close}}
Entry now! Check chart for levels.
```

### Step 4: Other Settings
- **Alert name**: V9 ES Signals (or NQ)
- **Expiration**: Open-ended
- **Alert frequency**: Once Per Bar Close

---

## Running 24/7 (Optional)

### Option 1: Keep Computer Running
- Use ngrok with account (free tier expires after 2 hours)
- Or use paid ngrok ($5/month) for persistent URL

### Option 2: Cloud Deployment (Free)
Deploy to Railway, Render, or Fly.io:

```bash
# Example: Railway
npm install -g @railway/cli
railway login
railway init
railway up
```

### Option 3: VPS
- DigitalOcean ($5/month)
- Linode ($5/month)
- AWS Free Tier

---

## Troubleshooting

### No notifications received
1. Check server is running: `http://localhost:5000/health`
2. Check ngrok is running and URL is correct
3. Test endpoint: `http://localhost:5000/test`
4. Verify Telegram bot token and chat_id

### TradingView webhook not working
1. Ensure alert is active (not expired)
2. Check webhook URL is correct (with `/webhook` at end)
3. TradingView webhooks require paid plan (Pro+)

### Alert delay
- TradingView webhooks have 1-5 second delay
- Telegram delivery is instant
- Check your alert frequency setting

---

## Alert Message Templates

### Detailed Alert
```
🚨 V9 {{strategy.order.action}} SIGNAL 🚨
━━━━━━━━━━━━━━━━━━━━━━
Symbol: {{ticker}}
Price: {{close}}
Time: {{time}}
━━━━━━━━━━━━━━━━━━━━━━
Action: Enter {{strategy.order.action}} now
Check TradingView for entry/stop levels
```

### Simple Alert
```
V9 {{strategy.order.action}}: {{ticker}} @ {{close}}
```

---

## Security Notes

- Never share your bot token
- Keep `.env` file private (add to .gitignore)
- Use HTTPS (ngrok provides this)
- Consider IP whitelisting for production
