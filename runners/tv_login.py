"""
TradingView browser-based login utility.

Opens Chrome browser for manual login to bypass CAPTCHA.
Session is cached for future use by tvDatafeed.
"""
import json
import sys
import time
from pathlib import Path

def browser_login():
    """Open browser for TradingView login and save session."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    print("\n" + "="*60)
    print("TradingView Browser Login")
    print("="*60)
    print("\nA Chrome browser window will open.")
    print("1. Log in to TradingView with your credentials")
    print("2. Complete any CAPTCHA if prompted")
    print("3. Once logged in, return here and press ENTER")
    print("\n" + "="*60 + "\n")

    # Setup Chrome - keep it open and visible
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    # Prevent browser from closing immediately
    options.add_experimental_option("detach", True)

    print("Starting Chrome browser...")
    try:
        driver = webdriver.Chrome(options=options)
        print("Chrome started successfully!")
    except Exception as e:
        print(f"ERROR starting Chrome: {e}")
        print("\nTrying alternative method...")
        # Try without options
        driver = webdriver.Chrome()

    # Navigate to TradingView signin
    print("Navigating to TradingView...")
    driver.get("https://www.tradingview.com/accounts/signin/")
    print(f"Current URL: {driver.current_url}")

    print("\n>>> Browser opened. Please log in to TradingView...")
    print(">>> Press ENTER here after you've logged in successfully...")
    sys.stdout.flush()

    try:
        input()
    except EOFError:
        print("Waiting 60 seconds for manual login...")
        time.sleep(60)

    # Get cookies after login
    cookies = driver.get_cookies()
    print(f"Got {len(cookies)} cookies")

    # Save cookies for tvDatafeed
    cache_dir = Path.home() / ".tvdatafeed"
    cache_dir.mkdir(exist_ok=True)
    cookie_file = cache_dir / "cookies.json"

    with open(cookie_file, "w") as f:
        json.dump(cookies, f, indent=2)

    print(f"\nSession saved to: {cookie_file}")

    # Also save in a format tvDatafeed can use
    token_file = cache_dir / "tv_session.json"
    session_data = {}
    for cookie in cookies:
        if cookie["name"] in ["sessionid", "sessionid_sign", "device_t", "png", "cachec"]:
            session_data[cookie["name"]] = cookie["value"]

    with open(token_file, "w") as f:
        json.dump(session_data, f, indent=2)

    print(f"Token data saved to: {token_file}")

    # Verify login by checking for user menu
    try:
        driver.get("https://www.tradingview.com/chart/")
        time.sleep(2)
        page_source = driver.page_source
        if "Sign in" not in page_source or "user-menu" in page_source:
            print("\nLogin verified successfully!")
        else:
            print("\nWarning: Login may not have been successful.")
    except Exception as e:
        print(f"Verification skipped: {e}")

    print("\nYou can now close the browser manually or it will stay open.")
    print("Run your trading scripts - they will use the saved session.")

    return cookies


def get_session_token():
    """Get session token from saved cookies."""
    cache_dir = Path.home() / ".tvdatafeed"
    cookie_file = cache_dir / "cookies.json"

    if not cookie_file.exists():
        print("No saved session found. Run browser_login() first.")
        return None

    with open(cookie_file) as f:
        cookies = json.load(f)

    # Find session cookies
    session_cookies = {}
    for cookie in cookies:
        if cookie["name"] in ["sessionid", "sessionid_sign", "device_t"]:
            session_cookies[cookie["name"]] = cookie["value"]

    return session_cookies


if __name__ == "__main__":
    browser_login()
