@echo off
:: V10.8 Paper Trading Launcher for Windows Task Scheduler
:: Features: Auto-restart on crash, market hours only, daily logging

cd /d C:\Users\vkudu\claude-projects\tradovate-futures-bot

:: Create logs directory if not exists
if not exist "logs\paper_trading" mkdir logs\paper_trading

:: Run the wrapper script (handles restarts, logging, market hours)
python run_paper_trading.py
