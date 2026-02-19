"""Project health check script."""
import sys

def main():
    errors = []
    print("Running health check...\n")

    # Check Python version
    print(f"Python: {sys.version.split()[0]}")

    # Check core imports
    checks = [
        ("core.types", "Signal, Direction, Bar"),
        ("strategies.ict.ict_strategy", "ICTStrategy"),
        ("strategies.factory", "build_ict_from_yaml"),
        ("config.loader", "load_yaml"),
        ("runners.data_loader", "load_csv_bars"),
        ("runners.replay", "ReplayEngine"),
        ("risk.risk_manager", "RiskManager"),
    ]

    print("\nImports:")
    for module, names in checks:
        try:
            exec(f"from {module} import {names}")
            print(f"  {module}: OK")
        except Exception as e:
            print(f"  {module}: FAILED - {e}")
            errors.append(f"{module}: {e}")

    # Check config files
    print("\nConfig files:")
    from pathlib import Path
    configs = ["config/strategies/ict_es.yaml", "config/strategies/ict_nq.yaml"]
    for cfg in configs:
        if Path(cfg).exists():
            print(f"  {cfg}: OK")
        else:
            print(f"  {cfg}: MISSING")
            errors.append(f"Missing: {cfg}")

    # Check data files
    print("\nData files:")
    data_files = list(Path("data").glob("*.csv")) if Path("data").exists() else []
    if data_files:
        for f in data_files:
            print(f"  {f.name}: OK")
    else:
        print("  No CSV files found")

    # Check TradingView Pro connection
    print("\nTradingView Pro:")
    try:
        from runners.tradingview_loader import fetch_futures_bars
        bars = fetch_futures_bars("ES", interval="1m", n_bars=1, timeout=15)
        if bars:
            latest = bars[-1]
            print("  Connection: OK (Pro account verified)")
            print(f"  Latest ES: {latest.timestamp.strftime('%Y-%m-%d %H:%M')} @ {latest.close:.2f}")
        else:
            print("  Connection: FAILED - No data returned")
            print("  Run: python -m runners.tv_login")
            errors.append("TradingView: No data - run tv_login")
    except Exception as e:
        err_msg = str(e)
        if "nologin" in err_msg.lower() or "login" in err_msg.lower():
            print("  Connection: FAILED - Session expired")
            print("  Run: python -m runners.tv_login")
            errors.append("TradingView: Session expired - run tv_login")
        else:
            print(f"  Connection: FAILED - {e}")
            errors.append(f"TradingView: {e}")

    # Check droplet
    import subprocess
    import platform
    is_droplet = platform.system() == "Linux" and Path("/opt/tradovate-bot").exists()

    if is_droplet:
        # Running on the droplet - check service locally
        print("\nPaper Trading Service:")
        try:
            result = subprocess.run(["systemctl", "is-active", "paper-trading"],
                                    capture_output=True, text=True, timeout=15)
            status = result.stdout.strip()
            if result.returncode == 0 and status == "active":
                print("  Service: ACTIVE")
                detail = subprocess.run(
                    ["systemctl", "show", "paper-trading", "--property=ActiveEnterTimestamp,MemoryCurrent"],
                    capture_output=True, text=True, timeout=15)
                for line in detail.stdout.strip().split("\n"):
                    if "ActiveEnterTimestamp=" in line:
                        print(f"  Started: {line.split('=', 1)[1].strip()}")
                    elif "MemoryCurrent=" in line:
                        try:
                            mem_mb = int(line.split("=", 1)[1].strip()) / (1024 * 1024)
                            print(f"  Memory: {mem_mb:.1f} MB")
                        except ValueError:
                            pass
            else:
                print(f"  Service: {status.upper() if status else 'UNKNOWN'}")
                errors.append(f"Paper trading service: {status or 'unknown'}")
        except Exception as e:
            print(f"  Service: ERROR - {e}")
            errors.append(f"Service check: {e}")
    else:
        # Running locally - SSH into droplet for full health check
        DROPLET = "root@107.170.74.154"
        SSH_OPTS = ["-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no"]

        print("\n" + "=" * 40)
        print("DROPLET (107.170.74.154)")
        print("=" * 40)

        try:
            result = subprocess.run(
                ["ssh"] + SSH_OPTS + [DROPLET,
                 "cd /opt/tradovate-bot && source venv/bin/activate && python health_check.py"],
                capture_output=True, text=True, timeout=120
            )
            # Indent droplet output
            for line in result.stdout.strip().split("\n"):
                print(f"  {line}")
            if result.returncode != 0:
                errors.append("Droplet health check failed")
                if result.stderr.strip():
                    print(f"  STDERR: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            print("  UNREACHABLE (SSH timeout)")
            errors.append("Droplet unreachable")
        except FileNotFoundError:
            print("  SKIPPED (no SSH client)")
        except Exception as e:
            print(f"  ERROR - {e}")
            errors.append(f"Droplet check: {e}")

    # Run tests
    print("\nTests:")
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no"],
            capture_output=True, text=True, timeout=60
        )
        # Extract pass/fail count from pytest output
        for line in result.stdout.split("\n"):
            if "passed" in line or "failed" in line:
                print(f"  {line.strip()}")
                break
        if result.returncode != 0:
            errors.append("Some tests failed")
    except Exception as e:
        print(f"  Could not run tests: {e}")

    # Summary
    print("\n" + "=" * 40)
    if errors:
        print(f"ISSUES FOUND: {len(errors)}")
        for e in errors:
            print(f"  - {e}")
    else:
        print("ALL CHECKS PASSED")

if __name__ == "__main__":
    main()
