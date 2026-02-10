#!/bin/bash
# DigitalOcean Deployment Script for V10.7 Paper Trading
# Run this ON the droplet after SSH'ing in

set -e

echo "=== V10.7 Paper Trading - DigitalOcean Setup ==="

# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11+ and pip
sudo apt install -y python3 python3-pip python3-venv git

# Clone or update repo
REPO_DIR="$HOME/tradovate-futures-bot"
if [ -d "$REPO_DIR" ]; then
    echo "Updating existing repo..."
    cd "$REPO_DIR"
    git pull
else
    echo "Cloning repo..."
    git clone https://github.com/prashanth116-ui/PS-Futs-bot.git "$REPO_DIR"
    cd "$REPO_DIR"
fi

# Create virtual environment
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Create config directory
mkdir -p config
mkdir -p logs

# Create .env file template if not exists
if [ ! -f "config/.env" ]; then
    echo "Creating config/.env template..."
    cat > config/.env << 'EOF'
# TradingView credentials (optional - can use cookie auth)
TV_USERNAME=
TV_PASSWORD=

# Tradovate credentials (for live trading only)
TRADOVATE_USERNAME=
TRADOVATE_PASSWORD=
TRADOVATE_APP_ID=
TRADOVATE_APP_VERSION=
TRADOVATE_CID=
TRADOVATE_SEC=
EOF
    echo "IMPORTANT: Edit config/.env with your credentials"
fi

echo ""
echo "=== Setup Complete ==="
echo "Next steps:"
echo "1. Edit config/.env with your TradingView credentials"
echo "2. Run: ./deploy/start_paper.sh"
echo ""
