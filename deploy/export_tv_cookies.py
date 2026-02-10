"""
Export TradingView cookies from local machine for server deployment.

Run this on your local PC after logging into TradingView.
Then copy the output file to your server.
"""
import json
import sys
from pathlib import Path

def export_cookies():
    """Export cookies to a file for server deployment."""

    # Check for existing cookies
    cookie_file = Path.home() / ".tvdatafeed" / "cookies.json"

    if not cookie_file.exists():
        print("No TradingView cookies found!")
        print("Run: python -m runners.tv_login")
        print("Then run this script again.")
        return None

    # Read cookies
    with open(cookie_file) as f:
        cookies = json.load(f)

    print(f"Found {len(cookies)} cookies")

    # Save to deploy folder
    export_file = Path(__file__).parent / "tv_cookies.json"
    with open(export_file, "w") as f:
        json.dump(cookies, f, indent=2)

    print(f"\nCookies exported to: {export_file}")
    print("\nTo deploy to server:")
    print(f"  scp {export_file} root@YOUR_DROPLET_IP:~/tradovate-futures-bot/deploy/")
    print("\nThen on server run:")
    print("  ./deploy/import_tv_cookies.sh")

    return export_file


if __name__ == "__main__":
    export_cookies()
