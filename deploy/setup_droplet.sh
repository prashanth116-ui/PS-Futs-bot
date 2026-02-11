#!/bin/bash
# DigitalOcean Droplet Setup Script for Paper Trading
# Run this ON the droplet after copying files

set -e

echo "=========================================="
echo "Setting up Tradovate Paper Trading Bot"
echo "=========================================="

# Install Python and dependencies
echo "Installing system dependencies..."
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

# Create app directory
APP_DIR="/opt/tradovate-bot"
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR

# Create virtual environment
echo "Creating Python virtual environment..."
cd $APP_DIR
python3 -m venv venv
source venv/bin/activate

# Install Python packages
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install pandas numpy python-dotenv pytz requests pyyaml yfinance websockets
# tvDatafeed must be installed from GitHub (not on PyPI)
pip install https://github.com/rongardF/tvdatafeed/archive/main.zip

# Create logs directory
mkdir -p logs/paper_trading

# Create systemd service
echo "Creating systemd service..."
sudo tee /etc/systemd/system/paper-trading.service > /dev/null <<EOF
[Unit]
Description=Tradovate Paper Trading Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
Environment=PATH=$APP_DIR/venv/bin:/usr/bin
ExecStart=$APP_DIR/venv/bin/python run_paper_trading.py
Restart=on-failure
RestartSec=30
StandardOutput=append:$APP_DIR/logs/paper_trading/service.log
StandardError=append:$APP_DIR/logs/paper_trading/service.log

[Install]
WantedBy=multi-user.target
EOF

# Create timer for weekday scheduling
echo "Creating systemd timer..."
sudo tee /etc/systemd/system/paper-trading.timer > /dev/null <<EOF
[Unit]
Description=Run Paper Trading on Weekdays

[Timer]
OnCalendar=Mon..Fri 03:55:00 America/New_York
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Reload systemd
sudo systemctl daemon-reload

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Copy your project files to $APP_DIR"
echo "2. Copy TradingView cookies to ~/.tvdatafeed/"
echo "3. Enable and start the timer:"
echo "   sudo systemctl enable paper-trading.timer"
echo "   sudo systemctl start paper-trading.timer"
echo ""
echo "Useful commands:"
echo "  Start now:    sudo systemctl start paper-trading"
echo "  Stop:         sudo systemctl stop paper-trading"
echo "  Status:       sudo systemctl status paper-trading"
echo "  View logs:    tail -f $APP_DIR/logs/paper_trading/service.log"
echo "  Timer status: systemctl list-timers"
