#!/bin/bash
# V10.5 Trading Bot - Server Setup Script
# Run this on a fresh Ubuntu 22.04 server

set -e

echo "========================================"
echo "V10.5 Trading Bot - Server Setup"
echo "========================================"

# Update system
echo "[1/6] Updating system..."
apt update && apt upgrade -y

# Install dependencies
echo "[2/6] Installing Python and tools..."
apt install -y python3 python3-pip python3-venv git screen curl

# Clone repository
echo "[3/6] Cloning repository..."
cd /root
if [ -d "trading-bot" ]; then
    echo "Repository exists, pulling latest..."
    cd trading-bot
    git pull
else
    git clone https://github.com/prashanth116-ui/PS-Futs-bot.git trading-bot
    cd trading-bot
fi

# Create virtual environment
echo "[4/6] Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate

# Install Python packages
echo "[5/6] Installing Python packages..."
pip install --upgrade pip
pip install tvdatafeed pandas numpy pyyaml requests websocket-client

# Create logs directory
mkdir -p logs

# Create convenience scripts
echo "[6/6] Creating helper scripts..."

cat > /root/start_trading.sh << 'EOF'
#!/bin/bash
cd /root/trading-bot
source venv/bin/activate
screen -dmS trading bash -c 'python -u -m runners.run_live --paper --symbols ES NQ SPY QQQ 2>&1 | tee -a logs/paper_trade_$(date +%Y-%m-%d).log'
echo "Paper trading started in background"
echo "Use 'screen -r trading' to view"
EOF
chmod +x /root/start_trading.sh

cat > /root/stop_trading.sh << 'EOF'
#!/bin/bash
screen -S trading -X quit 2>/dev/null
echo "Paper trading stopped"
EOF
chmod +x /root/stop_trading.sh

cat > /root/view_trading.sh << 'EOF'
#!/bin/bash
screen -r trading
EOF
chmod +x /root/view_trading.sh

cat > /root/logs_trading.sh << 'EOF'
#!/bin/bash
tail -f /root/trading-bot/logs/paper_trade_$(date +%Y-%m-%d).log
EOF
chmod +x /root/logs_trading.sh

echo ""
echo "========================================"
echo "Setup Complete!"
echo "========================================"
echo ""
echo "Quick Commands:"
echo "  /root/start_trading.sh  - Start paper trading"
echo "  /root/stop_trading.sh   - Stop paper trading"
echo "  /root/view_trading.sh   - View live session"
echo "  /root/logs_trading.sh   - Tail log file"
echo ""
echo "To start now:"
echo "  /root/start_trading.sh"
echo ""
