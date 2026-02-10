# Telegram Notifications Setup

Get real-time trade alerts on your phone!

## Step 1: Create a Telegram Bot (2 minutes)

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name: `V10.7 Trading Bot`
4. Choose a username: `your_trading_bot` (must end in `bot`)
5. **Copy the API token** - looks like: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`

## Step 2: Get Your Chat ID

1. Search for **@userinfobot** in Telegram
2. Send `/start`
3. **Copy your Chat ID** - looks like: `123456789`

## Step 3: Add to Config

Add these lines to `config/.env`:

```
TELEGRAM_BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=123456789
```

## Step 4: Test It

```bash
python -m runners.notifier
```

You should receive test notifications!

## Step 5: Deploy to Server

```batch
deploy\push_to_server.bat 107.170.74.154
```

---

## What You'll Receive

### Trade Entry
```
🟢 NEW TRADE - ES

Direction: LONG
Type: CREATION
Entry: $6,950.25
Stop: $6,945.00
Risk: 5.25 pts
Size: 3 contracts

⏰ 09:45:32 ET
```

### Trade Exit
```
✅ TRADE EXIT - ES

Direction: LONG
Exit Type: T1_4R
Exit Price: $6,971.25
Contracts: 1
💰 P/L: +$787.50

⏰ 10:23:15 ET
```

### Daily Summary
```
🎉 DAILY SUMMARY

Trades: 5
Wins: 4 | Losses: 1
Win Rate: 80.0%
Symbols: ES, NQ

💵 Total P/L: +$2,150.00

📅 2026-02-10
```

---

## Troubleshooting

**Not receiving messages?**
1. Make sure you started a chat with your bot (send `/start`)
2. Check bot token and chat ID are correct
3. Check `config/.env` file exists with correct values

**Want notifications in a group?**
1. Add your bot to the group
2. Send a message in the group
3. Get group chat ID from: `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Group IDs are negative numbers like `-123456789`
