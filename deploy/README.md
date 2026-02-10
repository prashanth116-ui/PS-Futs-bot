# DigitalOcean Deployment

## Quick Start

### 1. SSH into your droplet
```bash
ssh root@YOUR_DROPLET_IP
```

### 2. Run setup (first time only)
```bash
curl -sSL https://raw.githubusercontent.com/prashanth116-ui/PS-Futs-bot/master/deploy/deploy_digitalocean.sh | bash
```

Or manually:
```bash
git clone https://github.com/prashanth116-ui/PS-Futs-bot.git
cd tradovate-futures-bot
chmod +x deploy/*.sh
./deploy/deploy_digitalocean.sh
```

### 3. Configure credentials
```bash
nano config/.env
```

### 4. Start paper trading
```bash
./deploy/start_paper.sh
```

## Commands

| Command | Description |
|---------|-------------|
| `./deploy/start_paper.sh` | Start paper trading (auto-restarts) |
| `./deploy/stop_paper.sh` | Stop paper trading |
| `./deploy/logs.sh` | View live logs |
| `sudo systemctl status paper-trading` | Check status |

## Features

- **Auto-restart**: Service restarts automatically if it crashes
- **Boot startup**: Starts automatically when droplet reboots
- **Logging**: All output saved to `logs/paper_trading.log`

## Updating

```bash
cd ~/tradovate-futures-bot
git pull
./deploy/start_paper.sh  # Restarts with new code
```
