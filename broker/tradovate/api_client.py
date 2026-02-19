"""
Tradovate REST API Client

Handles authentication and REST API calls to Tradovate.
"""
from __future__ import annotations
import os
import requests
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional
from pathlib import Path


@dataclass
class TradovateConfig:
    """Tradovate API configuration."""
    username: str
    password: str
    env: str = "demo"  # "demo" or "live"
    cid: Optional[str] = None
    secret: Optional[str] = None
    device_id: Optional[str] = None

    @property
    def base_url(self) -> str:
        if self.env == "live":
            return "https://live.tradovateapi.com/v1"
        return "https://demo.tradovateapi.com/v1"

    @property
    def ws_url(self) -> str:
        if self.env == "live":
            return "wss://live.tradovateapi.com/v1/websocket"
        return "wss://demo.tradovateapi.com/v1/websocket"

    @property
    def md_url(self) -> str:
        """Market data WebSocket URL."""
        if self.env == "live":
            return "wss://md.tradovateapi.com/v1/websocket"
        return "wss://md.tradovateapi.com/v1/websocket"  # Same for demo


def load_config_from_env() -> TradovateConfig:
    """Load configuration from environment variables or .env file."""
    # Try to load from .env file
    env_path = Path("config/.env")
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

    return TradovateConfig(
        username=os.environ.get("TRADOVATE_USERNAME", ""),
        password=os.environ.get("TRADOVATE_PASSWORD", ""),
        env=os.environ.get("TRADOVATE_ENV", "demo"),
        cid=os.environ.get("TRADOVATE_CID"),
        secret=os.environ.get("TRADOVATE_SECRET"),
        device_id=os.environ.get("TRADOVATE_DEVICE_ID"),
    )


class TradovateClient:
    """
    Tradovate REST API client.

    Handles authentication and API requests.
    """

    def __init__(self, config: Optional[TradovateConfig] = None):
        self.config = config or load_config_from_env()
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self.account_id: Optional[int] = None
        self.account_spec: Optional[str] = None
        self.session = requests.Session()

    def authenticate(self) -> bool:
        """
        Authenticate with Tradovate API.

        Returns True if successful, False otherwise.
        """
        url = f"{self.config.base_url}/auth/accesstokenrequest"

        payload = {
            "name": self.config.username,
            "password": self.config.password,
            "appId": "TradovateBot",
            "appVersion": "1.0.0",
            "deviceId": self.config.device_id or self._generate_device_id(),
            "cid": self.config.cid,
            "sec": self.config.secret,
        }

        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}

        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

            if "accessToken" in data:
                self.access_token = data["accessToken"]
                # Token expires in 80 minutes typically
                expires_in = data.get("expirationTime", 4800)
                self.token_expiry = datetime.now() + timedelta(seconds=expires_in)
                self.session.headers["Authorization"] = f"Bearer {self.access_token}"
                print(f"Authenticated successfully. Token expires: {self.token_expiry}")
                return True
            else:
                print(f"Authentication failed: {data}")
                return False

        except requests.exceptions.RequestException as e:
            print(f"Authentication error: {e}")
            return False

    def _generate_device_id(self) -> str:
        """Generate a unique device ID."""
        import uuid
        return str(uuid.uuid4())

    def is_authenticated(self) -> bool:
        """Check if we have a valid token."""
        if not self.access_token or not self.token_expiry:
            return False
        return datetime.now() < self.token_expiry

    def ensure_authenticated(self) -> bool:
        """Ensure we have a valid token, refreshing if needed."""
        if not self.is_authenticated():
            return self.authenticate()
        return True

    def get_accounts(self) -> list[dict]:
        """Get list of trading accounts."""
        if not self.ensure_authenticated():
            return []

        url = f"{self.config.base_url}/account/list"
        response = self.session.get(url)
        response.raise_for_status()
        accounts = response.json()

        if accounts:
            # Store first account as default
            self.account_id = accounts[0]["id"]
            self.account_spec = accounts[0]["name"]
            print(f"Using account: {self.account_spec} (ID: {self.account_id})")

        return accounts

    def get_positions(self) -> list[dict]:
        """Get current positions."""
        if not self.ensure_authenticated():
            return []

        url = f"{self.config.base_url}/position/list"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def get_orders(self) -> list[dict]:
        """Get current orders."""
        if not self.ensure_authenticated():
            return []

        url = f"{self.config.base_url}/order/list"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def get_contract(self, symbol: str) -> Optional[dict]:
        """Get contract details by symbol."""
        if not self.ensure_authenticated():
            return None

        url = f"{self.config.base_url}/contract/find"
        params = {"name": symbol}
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def place_order(
        self,
        symbol: str,
        action: str,  # "Buy" or "Sell"
        qty: int,
        order_type: str = "Market",  # "Market", "Limit", "Stop", "StopLimit"
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
    ) -> Optional[dict]:
        """
        Place an order.

        Args:
            symbol: Contract symbol (e.g., "ESH5" for ES March 2025)
            action: "Buy" or "Sell"
            qty: Number of contracts
            order_type: Order type
            price: Limit price (for Limit/StopLimit orders)
            stop_price: Stop price (for Stop/StopLimit orders)

        Returns:
            Order response dict or None if failed
        """
        if not self.ensure_authenticated():
            return None

        # Get contract ID
        contract = self.get_contract(symbol)
        if not contract:
            print(f"Contract not found: {symbol}")
            return None

        url = f"{self.config.base_url}/order/placeorder"
        payload = {
            "accountSpec": self.account_spec,
            "accountId": self.account_id,
            "action": action,
            "symbol": symbol,
            "orderQty": qty,
            "orderType": order_type,
            "isAutomated": True,
        }

        if price is not None:
            payload["price"] = price
        if stop_price is not None:
            payload["stopPrice"] = stop_price

        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            print(f"Order placed: {result}")
            return result
        except requests.exceptions.RequestException as e:
            print(f"Order failed: {e}")
            return None

    def cancel_order(self, order_id: int) -> bool:
        """Cancel an order by ID."""
        if not self.ensure_authenticated():
            return False

        url = f"{self.config.base_url}/order/cancelorder"
        payload = {"orderId": order_id}

        try:
            response = self.session.post(url, json=payload)
            response.raise_for_status()
            print(f"Order {order_id} cancelled")
            return True
        except requests.exceptions.RequestException as e:
            print(f"Cancel failed: {e}")
            return False


if __name__ == "__main__":
    # Test authentication
    client = TradovateClient()
    if client.authenticate():
        accounts = client.get_accounts()
        print(f"Accounts: {accounts}")
        positions = client.get_positions()
        print(f"Positions: {positions}")
