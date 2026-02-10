# DigitalOcean Deployment

## One-Command Deploy (Windows)

After initial server setup, just run:
```batch
deploy\push_to_server.bat YOUR_DROPLET_IP
```

This will:
1. Export TradingView cookies from your local PC
2. Upload cookies to server
3. Update code and restart paper trading

---

## Initial Server Setup (First Time Only)

### 1. SSH into your droplet
```bash
ssh root@YOUR_DROPLET_IP
```

### 2. Run setup script
```bash
git clone https://github.com/prashanth116-ui/PS-Futs-bot.git ~/tradovate-futures-bot
cd ~/tradovate-futures-bot
chmod +x deploy/*.sh
./deploy/deploy_digitalocean.sh
```

### 3. Upload TradingView cookies (on your local PC)
```batch
:: First, make sure you're logged into TradingView in Chrome
:: Then run:
python deploy/export_tv_cookies.py
scp deploy/tv_cookies.json root@YOUR_DROPLET_IP:~/tradovate-futures-bot/deploy/
```

### 4. Start paper trading (on server)
```bash
./deploy/start_paper.sh
```

---

## Commands Reference

### On Server
| Command | Description |
|---------|-------------|
| `./deploy/start_paper.sh` | Start paper trading (auto-restarts) |
| `./deploy/stop_paper.sh` | Stop paper trading |
| `./deploy/logs.sh` | View live logs |
| `sudo systemctl status paper-trading` | Check status |
| `./deploy/import_tv_cookies.sh` | Import cookies manually |

### On Local PC (Windows)
| Command | Description |
|---------|-------------|
| `deploy\push_to_server.bat IP` | Push cookies + update + restart |
| `python deploy/export_tv_cookies.py` | Export TV cookies |

---

## TradingView Authentication

The bot uses cookie-based auth (most reliable). Cookies expire after ~30 days.

**If data fetching fails:**
1. Log into TradingView in Chrome on your PC
2. Run: `python -m runners.tv_login`
3. Run: `deploy\push_to_server.bat YOUR_IP`

---

## Features

- **Auto-restart**: Service restarts automatically if it crashes
- **Boot startup**: Starts automatically when droplet reboots
- **Logging**: All output saved to `logs/paper_trading.log`
- **Cookie auth**: No CAPTCHA issues

---

## Updating Code

Option 1 - From local PC:
```batch
deploy\push_to_server.bat YOUR_IP
```

Option 2 - On server:
```bash
cd ~/tradovate-futures-bot
git pull
./deploy/start_paper.sh
```
