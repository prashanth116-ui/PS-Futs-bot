@echo off
schtasks /create /tn "Tradovate Paper Trading" /tr "C:\Users\vkudu\claude-projects\tradovate-futures-bot\start_paper_trading.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 03:55 /f
echo.
echo Task created! Verifying...
schtasks /query /tn "Tradovate Paper Trading"
