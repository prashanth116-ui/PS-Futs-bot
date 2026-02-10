#!/bin/bash
# Start paper trading in background with auto-restart using systemd

REPO_DIR="$HOME/tradovate-futures-bot"
SERVICE_NAME="paper-trading"

echo "=== Starting V10.7 Paper Trading ==="

# Create systemd service file
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null << EOF
[Unit]
Description=V10.7 Paper Trading Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$REPO_DIR
Environment="PATH=$REPO_DIR/.venv/bin:/usr/bin"
ExecStart=$REPO_DIR/.venv/bin/python -u -m runners.run_live --paper --symbols ES NQ SPY QQQ
Restart=always
RestartSec=60
StandardOutput=append:$REPO_DIR/logs/paper_trading.log
StandardError=append:$REPO_DIR/logs/paper_trading.log

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and start service
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl restart ${SERVICE_NAME}

echo ""
echo "=== Paper Trading Started ==="
echo "Status: sudo systemctl status ${SERVICE_NAME}"
echo "Logs:   tail -f $REPO_DIR/logs/paper_trading.log"
echo "Stop:   sudo systemctl stop ${SERVICE_NAME}"
echo ""

# Show status
sudo systemctl status ${SERVICE_NAME} --no-pager
