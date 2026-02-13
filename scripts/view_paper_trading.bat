@echo off
:: View Paper Trading Logs (live tail)

cd /d C:\Users\vkudu\claude-projects\tradovate-futures-bot

:: Get today's date
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /format:list') do set datetime=%%I
set logdate=%datetime:~0,4%-%datetime:~4,2%-%datetime:~6,2%

set logfile=logs\paper_trade_%logdate%.log

if exist %logfile% (
    echo Showing last 50 lines of %logfile%
    echo Press Ctrl+C to exit
    echo ========================================
    powershell -command "Get-Content -Path '%logfile%' -Tail 50 -Wait"
) else (
    echo No log file found for today: %logfile%
    echo.
    echo Available log files:
    dir /b logs\*.log 2>nul
)
