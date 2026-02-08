# Cloud Server Setup for V10.5 Paper Trading

This guide sets up a $5/month cloud server to run paper trading 24/7.

## Step 1: Create a DigitalOcean Account

1. Go to https://www.digitalocean.com
2. Sign up (you can use GitHub login)
3. Add a payment method ($5/mo minimum)

## Step 2: Create a Droplet (Server)

1. Click "Create" → "Droplets"
2. Choose:
   - **Image**: Ubuntu 22.04 LTS
   - **Plan**: Basic → Regular → $6/mo (1GB RAM, 1 CPU)
   - **Region**: New York (closest to market data)
   - **Authentication**: Password (create a strong one)
   - **Hostname**: `trading-bot`
3. Click "Create Droplet"
4. Copy the IP address shown (e.g., `164.92.xxx.xxx`)

## Step 3: Connect to Your Server

### From Windows (PowerShell):
```powershell
ssh root@YOUR_IP_ADDRESS
```

### Or use PuTTY:
1. Download PuTTY from https://putty.org
2. Enter your IP address
3. Click "Open"
4. Login as `root` with your password

## Step 4: Run the Setup Script

Once connected, run these commands:

```bash
# Download and run setup script
curl -sSL https://raw.githubusercontent.com/prashanth116-ui/PS-Futs-bot/master/deploy/setup_server.sh | bash
```

Or manually:

```bash
# Update system
apt update && apt upgrade -y

# Install Python and dependencies
apt install -y python3 python3-pip python3-venv git screen

# Clone repository
cd /root
git clone https://github.com/prashanth116-ui/PS-Futs-bot.git trading-bot
cd trading-bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install tvdatafeed pandas numpy pyyaml requests websocket-client

# Test the setup
python -m runners.run_v10_equity SPY 500
```

## Step 5: Start Paper Trading

```bash
# Start a screen session (persists after disconnect)
screen -S trading

# Activate virtual environment
cd /root/trading-bot
source venv/bin/activate

# Start paper trading
python -u -m runners.run_live --paper --symbols ES NQ SPY QQQ 2>&1 | tee -a logs/paper_trade.log

# Detach from screen: Press Ctrl+A, then D
```

## Step 6: Reconnect Later

```bash
# SSH back into server
ssh root@YOUR_IP_ADDRESS

# Reattach to trading session
screen -r trading
```

## Useful Commands

| Command | Description |
|---------|-------------|
| `screen -r trading` | Reattach to trading session |
| `screen -ls` | List all screen sessions |
| `Ctrl+A, D` | Detach from screen (keeps running) |
| `tail -f logs/paper_trade.log` | View live logs |
| `Ctrl+C` | Stop paper trading |

## Auto-Start on Reboot (Optional)

```bash
# Create systemd service
cat > /etc/systemd/system/paper-trading.service << 'EOF'
[Unit]
Description=V10.5 Paper Trading Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/trading-bot
ExecStart=/root/trading-bot/venv/bin/python -u -m runners.run_live --paper --symbols ES NQ SPY QQQ
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
systemctl enable paper-trading
systemctl start paper-trading

# Check status
systemctl status paper-trading

# View logs
journalctl -u paper-trading -f
```

## Costs

- DigitalOcean: $6/month
- Vultr: $5/month
- AWS Lightsail: $5/month

## Troubleshooting

### "No data" errors
TradingView may rate-limit. Wait a few minutes and retry.

### Connection drops
Use `screen` or `tmux` to keep sessions alive.

### Server restart
If using systemd service, it auto-restarts. Otherwise, re-run the screen commands.
