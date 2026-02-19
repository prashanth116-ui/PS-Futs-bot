"""
Paper Trading Wrapper Script for Windows Task Scheduler.

Features:
- Health check and TradingView Pro connectivity verification on startup
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
HEALTH_CHECK_RETRIES = 3     # Retry health check this many times before giving up


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


def run_health_check():
    """
    Run health check including TradingView Pro connectivity.

    Returns:
        tuple: (success: bool, message: str)
    """
    log("Running health check...")
    errors = []

    # Check 1: Core imports
    log("  Checking core imports...")
    core_imports = [
        ("core.types", "Signal, Direction, Bar"),
        ("strategies.ict.ict_strategy", "ICTStrategy"),
        ("runners.tradingview_loader", "fetch_futures_bars"),
        ("runners.run_live", "LiveTrader"),
    ]

    for module, names in core_imports:
        try:
            exec(f"from {module} import {names}")
        except Exception as e:
            errors.append(f"Import {module}: {e}")
            log(f"    FAILED: {module} - {e}")

    if not errors:
        log("    All imports OK")

    # Check 2: TradingView Pro connectivity
    log("  Checking TradingView Pro connection...")
    try:
        from runners.tradingview_loader import fetch_futures_bars
        bars = fetch_futures_bars("ES", interval="1m", n_bars=1, timeout=30)
        if bars:
            latest = bars[-1]
            log(f"    Connected: ES @ {latest.close:.2f} ({latest.timestamp.strftime('%H:%M')})")
        else:
            errors.append("TradingView: No data returned")
            log("    FAILED: No data returned")
    except Exception as e:
        errors.append(f"TradingView: {e}")
        log(f"    FAILED: {e}")

    # Check 3: Config files
    log("  Checking config files...")
    config_dir = Path(__file__).parent / "config" / "strategies"
    for cfg in ["ict_es.yaml", "ict_nq.yaml"]:
        cfg_path = config_dir / cfg
        if not cfg_path.exists():
            errors.append(f"Missing config: {cfg}")
            log(f"    FAILED: Missing {cfg}")

    if not any("config" in e.lower() for e in errors):
        log("    Config files OK")

    # Summary
    if errors:
        return False, f"{len(errors)} error(s): {'; '.join(errors)}"
    else:
        return True, "All checks passed"


def run_paper_trading():
    """Run the paper trading script and capture output."""
    cmd = [
        sys.executable, "-m", "runners.run_live",
        "--paper",
        "--symbols", "ES"
    ]

    log_file = get_log_file()
    start_time = datetime.now()
    last_wrapper_heartbeat = datetime.now()
    WRAPPER_HEARTBEAT_INTERVAL = 300  # 5 minutes

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

            # Wrapper heartbeat every 5 minutes
            now = datetime.now()
            if (now - last_wrapper_heartbeat).total_seconds() >= WRAPPER_HEARTBEAT_INTERVAL:
                uptime_secs = int((now - start_time).total_seconds())
                uptime_min = uptime_secs // 60
                if uptime_min >= 60:
                    uptime_str = f"{uptime_min // 60}h{uptime_min % 60}m"
                else:
                    uptime_str = f"{uptime_min}m"
                log(f"[WRAPPER] {now.strftime('%H:%M:%S')} | Bot running (PID: {process.pid}) | Uptime: {uptime_str}")
                last_wrapper_heartbeat = now

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

    # Run health check with retries
    log("")
    log("=" * 40)
    log("PRE-FLIGHT HEALTH CHECK")
    log("=" * 40)

    health_ok = False
    for attempt in range(HEALTH_CHECK_RETRIES):
        success, message = run_health_check()
        if success:
            log(f"Health check PASSED: {message}")
            health_ok = True
            break
        else:
            log(f"Health check FAILED (attempt {attempt + 1}/{HEALTH_CHECK_RETRIES}): {message}")
            if attempt < HEALTH_CHECK_RETRIES - 1:
                log("Retrying in 60 seconds...")
                time.sleep(60)

    if not health_ok:
        log("Health check failed after all retries - aborting")
        log("=" * 60)
        return

    log("=" * 40)
    log("")

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
