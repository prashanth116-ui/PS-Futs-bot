#!/bin/bash
# Deploy script - run from local machine (Git Bash on Windows)
# Usage: ./deploy/deploy.sh <droplet-ip> [username]
#
# Example: ./deploy/deploy.sh 164.92.xxx.xxx root

set -e

DROPLET_IP="${1:?Usage: deploy.sh <droplet-ip> [username]}"
DROPLET_USER="${2:-root}"
APP_DIR="/opt/tradovate-bot"

echo "Deploying to $DROPLET_USER@$DROPLET_IP..."

# Files/folders to sync
rsync -avz --progress \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.git' \
    --exclude 'logs' \
    --exclude '*.png' \
    --exclude 'data/*.csv' \
    --exclude 'venv' \
    --exclude '.env' \
    core/ \
    config/ \
    runners/ \
    risk/ \
    strategies/ \
    tests/ \
    run_paper_trading.py \
    health_check.py \
    requirements.txt \
    "$DROPLET_USER@$DROPLET_IP:$APP_DIR/"

# Sync TradingView cookies
echo "Syncing TradingView session..."
rsync -avz ~/.tvdatafeed/ "$DROPLET_USER@$DROPLET_IP:~/.tvdatafeed/"

echo ""
echo "Deploy complete!"
echo ""
echo "SSH into droplet and run:"
echo "  cd $APP_DIR"
echo "  source venv/bin/activate"
echo "  python health_check.py"
