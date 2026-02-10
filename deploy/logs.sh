#!/bin/bash
# View paper trading logs

REPO_DIR="$HOME/tradovate-futures-bot"
tail -f "$REPO_DIR/logs/paper_trading.log"
