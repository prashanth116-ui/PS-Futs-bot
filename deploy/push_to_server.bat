@echo off
:: Push TradingView cookies and code to DigitalOcean server
:: Usage: push_to_server.bat YOUR_DROPLET_IP

if "%1"=="" (
    echo Usage: push_to_server.bat YOUR_DROPLET_IP
    echo Example: push_to_server.bat 167.99.123.45
    exit /b 1
)

set SERVER=%1
set REPO_DIR=C:\Users\vkudu\claude-projects\tradovate-futures-bot

echo === Pushing to DigitalOcean Server: %SERVER% ===

:: Export cookies first
echo.
echo Step 1: Exporting TradingView cookies...
python "%REPO_DIR%\deploy\export_tv_cookies.py"

:: Push cookies to server
echo.
echo Step 2: Uploading cookies to server...
scp "%REPO_DIR%\deploy\tv_cookies.json" root@%SERVER%:~/tradovate-futures-bot/deploy/

:: Update code on server and restart
echo.
echo Step 3: Updating code and restarting paper trading...
ssh root@%SERVER% "cd ~/tradovate-futures-bot && git pull && ./deploy/start_paper.sh"

echo.
echo === Done! Paper trading running on server ===
echo.
echo View logs: ssh root@%SERVER% "tail -f ~/tradovate-futures-bot/logs/paper_trading.log"
pause
