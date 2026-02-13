@echo off
:: Setup auto-start paper trading on Windows startup
:: Run this as Administrator

schtasks /create /tn "V10.7 Paper Trading" /tr "cmd /c cd /d C:\Users\vkudu\claude-projects\tradovate-futures-bot && python -u -m runners.run_live --paper --symbols ES NQ SPY QQQ > logs\paper_trade_auto.log 2>&1" /sc onstart /ru "%USERNAME%" /rl highest /f

echo.
echo Task created! Paper trading will auto-start when Windows boots.
echo To remove: schtasks /delete /tn "V10.7 Paper Trading" /f
pause
