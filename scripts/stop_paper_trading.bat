@echo off
:: Stop Paper Trading

echo Stopping paper trading...
taskkill /f /im python.exe 2>nul

if %errorlevel%==0 (
    echo Paper trading stopped.
) else (
    echo No paper trading process found.
)
