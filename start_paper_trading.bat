@echo off
:: V10.7 Paper Trading Launcher
:: Runs paper trading in background with logging

cd /d C:\Users\vkudu\claude-projects\tradovate-futures-bot

:: Create logs directory if not exists
if not exist "logs" mkdir logs

:: Get today's date for log file
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /format:list') do set datetime=%%I
set logdate=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2%

:: Start paper trading with logging
echo Starting V10.7 Paper Trading at %time%...
echo Log file: logs\paper_trade_%logdate%.log

start /min cmd /c "python -u -m runners.run_live --paper --symbols ES NQ SPY QQQ > logs\paper_trade_%logdate%.log 2>&1"

echo Paper trading started in background.
echo To view live output: type logs\paper_trade_%logdate%.log
echo To stop: taskkill /f /im python.exe
