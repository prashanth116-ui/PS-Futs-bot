#!/bin/bash
# Import TradingView cookies on server

REPO_DIR="$HOME/tradovate-futures-bot"
COOKIE_SRC="$REPO_DIR/deploy/tv_cookies.json"
COOKIE_DST="$HOME/.tvdatafeed/cookies.json"

if [ ! -f "$COOKIE_SRC" ]; then
    echo "ERROR: tv_cookies.json not found in deploy folder!"
    echo ""
    echo "On your local PC, run:"
    echo "  python deploy/export_tv_cookies.py"
    echo ""
    echo "Then copy to server:"
    echo "  scp deploy/tv_cookies.json root@YOUR_DROPLET_IP:~/tradovate-futures-bot/deploy/"
    exit 1
fi

# Create target directory
mkdir -p "$HOME/.tvdatafeed"

# Copy cookies
cp "$COOKIE_SRC" "$COOKIE_DST"

echo "TradingView cookies imported successfully!"
echo "Location: $COOKIE_DST"
