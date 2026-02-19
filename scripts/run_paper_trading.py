"""
Paper Trading Wrapper Script for Windows Task Scheduler.

Features:
- Auto-restarts on crash (up to 5 times per day)
- Logs output to daily log files
- Only runs during market hours (4:00 AM - 4:30 PM ET)
- Graceful shutdown at market close
- Skips weekends automatically
"""

import subprocess
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path

# Configuration
MAX_RESTARTS_PER_DAY = 5
LOG_DIR = Path(__file__).parent / "logs" / "paper_trading"
MARKET_OPEN = dtime(4, 0)    # 4:00 AM ET (futures pre-market)
MARKET_CLOSE = dtime(16, 30)  # 4:30 PM ET (buffer after close)

def is_weekday():
    """Check if today is a weekday (Mon-Fri)."""
    return datetime.now().weekday() < 5

def is_market_hours():
    """Check if current time is within market hours."""
    now = datetime.now().time()
    return MARKET_OPEN <= now <= MARKET_CLOSE

def get_log_file():
    """Get today's log file path."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    return LOG_DIR / f"paper_trading_{today}.log"

def log(message: str):
    """Log message to console and file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line, flush=True)

    with open(get_log_file(), "a") as f:
        f.write(line + "\n")

def run_paper_trading():
    """Run the paper trading script and capture output."""
    cmd = [
        sys.executable, "-m", "runners.run_live",
        "--paper",
        "--symbols", "ES", "NQ", "MES", "MNQ", "SPY", "QQQ"
    ]

    log_file = get_log_file()

    with open(log_file, "a") as f:
        process = subprocess.Popen(
            cmd,
            stdout=f,
            stderr=subprocess.STDOUT,
            cwd=Path(__file__).parent,
            bufsize=1,
            universal_newlines=True
        )

        # Monitor the process
        while process.poll() is None:
            # Check if market is still open
            if not is_market_hours():
                log("Market closed - stopping paper trading")
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                return 0

            time.sleep(30)  # Check every 30 seconds

        return process.returncode

def main():
    """Main entry point with auto-restart logic."""
    log("=" * 60)
    log("Paper Trading Wrapper Started")
    log("=" * 60)

    # Check if it's a weekday
    if not is_weekday():
        log("Weekend detected - exiting")
        return

    # Wait for market to open if started early
    while not is_market_hours():
        now = datetime.now()
        if now.time() > MARKET_CLOSE:
            log("Market already closed for today - exiting")
            return

        log(f"Waiting for market open ({MARKET_OPEN})...")
        time.sleep(60)

    # Run with auto-restart
    restart_count = 0

    while restart_count < MAX_RESTARTS_PER_DAY and is_market_hours():
        log(f"Starting paper trading (attempt {restart_count + 1}/{MAX_RESTARTS_PER_DAY})")

        try:
            exit_code = run_paper_trading()

            if exit_code == 0:
                log("Paper trading exited normally")
                break
            else:
                log(f"Paper trading crashed with exit code {exit_code}")
                restart_count += 1

                if restart_count < MAX_RESTARTS_PER_DAY and is_market_hours():
                    log("Restarting in 30 seconds...")
                    time.sleep(30)

        except KeyboardInterrupt:
            log("Keyboard interrupt - stopping")
            break
        except Exception as e:
            log(f"Error: {e}")
            restart_count += 1
            time.sleep(30)

    if restart_count >= MAX_RESTARTS_PER_DAY:
        log(f"Max restarts ({MAX_RESTARTS_PER_DAY}) reached - stopping for today")

    log("Paper Trading Wrapper Finished")
    log("=" * 60)

if __name__ == "__main__":
    main()
