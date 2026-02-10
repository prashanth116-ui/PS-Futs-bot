#!/bin/bash
# Stop paper trading service

SERVICE_NAME="paper-trading"

echo "Stopping V10.7 Paper Trading..."
sudo systemctl stop ${SERVICE_NAME}
sudo systemctl status ${SERVICE_NAME} --no-pager
