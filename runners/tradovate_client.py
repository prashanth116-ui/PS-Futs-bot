"""
Tradovate API Client for Live Trading

Handles authentication, order placement, and position management.
Supports both demo and live environments.

API Documentation: https://api.tradovate.com/
"""
import os
import json
import time
import requests
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from enum import Enum


class Environment(Enum):
    DEMO = "demo"
    LIVE = "live"


class OrderAction(Enum):
    BUY = "Buy"
    SELL = "Sell"


class OrderType(Enum):
    MARKET = "Market"
    LIMIT = "Limit"
    STOP = "Stop"
    STOP_LIMIT = "StopLimit"
    TRAILING_STOP = "TrailingStop"


class TimeInForce(Enum):
    DAY = "Day"
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


@dataclass
class TradovateConfig:
    """Configuration for Tradovate API connection."""
    username: str = ""
    password: str = ""
    app_id: str = ""
    app_version: str = "1.0"
    cid: int = 0  # Client ID
    sec: str = ""  # Client Secret
    device_id: str = ""
    environment: Environment = Environment.DEMO

    @classmethod
    def from_env(cls) -> 'TradovateConfig':
        """Load configuration from environment variables."""
        return cls(
            username=os.getenv('TRADOVATE_USERNAME', ''),
            password=os.getenv('TRADOVATE_PASSWORD', ''),
            app_id=os.getenv('TRADOVATE_APP_ID', ''),
            app_version=os.getenv('TRADOVATE_APP_VERSION', '1.0'),
            cid=int(os.getenv('TRADOVATE_CID', '0')),
            sec=os.getenv('TRADOVATE_SEC', ''),
            device_id=os.getenv('TRADOVATE_DEVICE_ID', 'tradovate-bot'),
            environment=Environment(os.getenv('TRADOVATE_ENV', 'demo')),
        )

    @classmethod
    def from_file(cls, path: str = 'config/tradovate_credentials.json') -> 'TradovateConfig':
        """Load configuration from JSON file."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, 'r') as f:
            data = json.load(f)

        return cls(
            username=data.get('username', ''),
            password=data.get('password', ''),
            app_id=data.get('app_id', ''),
            app_version=data.get('app_version', '1.0'),
            cid=data.get('cid', 0),
            sec=data.get('sec', ''),
            device_id=data.get('device_id', 'tradovate-bot'),
            environment=Environment(data.get('environment', 'demo')),
        )


@dataclass
class Order:
    """Represents a trading order."""
    id: int = 0
    account_id: int = 0
    contract_id: int = 0
    action: OrderAction = OrderAction.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: int = 1
    price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: TimeInForce = TimeInForce.DAY
    status: str = ""
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Position:
    """Represents a trading position."""
    id: int = 0
    account_id: int = 0
    contract_id: int = 0
    net_pos: int = 0
    net_price: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)


class TradovateClient:
    """
    Tradovate API Client for order execution and position management.

    Usage:
        client = TradovateClient(config)
        client.connect()

        # Place a market order
        order = client.place_order(
            symbol='ESH5',
            action=OrderAction.BUY,
            quantity=1,
            order_type=OrderType.MARKET
        )

        # Get positions
        positions = client.get_positions()
    """

    # API endpoints
    DEMO_URL = "https://demo.tradovateapi.com/v1"
    LIVE_URL = "https://live.tradovateapi.com/v1"

    # Contract IDs (updated periodically)
    CONTRACT_MAP = {
        'ES': 'ESH5',  # E-mini S&P 500
        'NQ': 'NQH5',  # E-mini Nasdaq 100
        'MES': 'MESH5',  # Micro E-mini S&P 500
        'MNQ': 'MNQH5',  # Micro E-mini Nasdaq 100
    }

    def __init__(self, config: Optional[TradovateConfig] = None):
        """Initialize the Tradovate client."""
        self.config = config or TradovateConfig.from_env()
        self.base_url = self.DEMO_URL if self.config.environment == Environment.DEMO else self.LIVE_URL

        # Authentication state
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self.account_id: Optional[int] = None
        self.user_id: Optional[int] = None

        # Contract cache
        self._contract_cache: Dict[str, int] = {}

        # Session
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })

        # Lock for thread safety
        self._lock = threading.Lock()

        # Connection status
        self.connected = False

    def connect(self) -> bool:
        """
        Authenticate with Tradovate API.

        Returns:
            True if authentication successful, False otherwise.
        """
        try:
            auth_payload = {
                'name': self.config.username,
                'password': self.config.password,
                'appId': self.config.app_id,
                'appVersion': self.config.app_version,
                'cid': self.config.cid,
                'sec': self.config.sec,
                'deviceId': self.config.device_id,
            }

            response = self.session.post(
                f"{self.base_url}/auth/accesstokenrequest",
                json=auth_payload,
                timeout=30
            )

            if response.status_code != 200:
                print(f"Authentication failed: {response.status_code} - {response.text}")
                return False

            data = response.json()

            if 'errorText' in data:
                print(f"Authentication error: {data['errorText']}")
                return False

            self.access_token = data.get('accessToken')
            self.user_id = data.get('userId')

            # Token expires in 'expirationTime' (ISO format)
            expiry_str = data.get('expirationTime')
            if expiry_str:
                self.token_expiry = datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
            else:
                # Default to 1 hour
                self.token_expiry = datetime.now() + timedelta(hours=1)

            # Update session headers with token
            self.session.headers.update({
                'Authorization': f'Bearer {self.access_token}'
            })

            # Get account info
            self._fetch_account_info()

            self.connected = True
            print(f"Connected to Tradovate ({self.config.environment.value})")
            print(f"Account ID: {self.account_id}")

            return True

        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def _fetch_account_info(self):
        """Fetch and cache account information."""
        response = self.session.get(f"{self.base_url}/account/list", timeout=30)

        if response.status_code == 200:
            accounts = response.json()
            if accounts:
                # Use first active account
                for acc in accounts:
                    if acc.get('active', False):
                        self.account_id = acc['id']
                        break
                if not self.account_id and accounts:
                    self.account_id = accounts[0]['id']

    def _ensure_connected(self):
        """Ensure we have a valid connection, refresh if needed."""
        if not self.connected or not self.access_token:
            raise RuntimeError("Not connected. Call connect() first.")

        # Check token expiry
        if self.token_expiry and datetime.now() >= self.token_expiry - timedelta(minutes=5):
            print("Token expiring soon, reconnecting...")
            self.connect()

    def get_contract_id(self, symbol: str) -> Optional[int]:
        """
        Get the contract ID for a symbol.

        Args:
            symbol: Contract symbol (e.g., 'ESH5' or 'ES')

        Returns:
            Contract ID or None if not found.
        """
        self._ensure_connected()

        # Map generic symbols to specific contracts
        if symbol in self.CONTRACT_MAP:
            symbol = self.CONTRACT_MAP[symbol]

        # Check cache
        if symbol in self._contract_cache:
            return self._contract_cache[symbol]

        # Fetch from API
        response = self.session.get(
            f"{self.base_url}/contract/find",
            params={'name': symbol},
            timeout=30
        )

        if response.status_code == 200:
            contract = response.json()
            if contract and 'id' in contract:
                self._contract_cache[symbol] = contract['id']
                return contract['id']

        return None

    def place_order(
        self,
        symbol: str,
        action: OrderAction,
        quantity: int,
        order_type: OrderType = OrderType.MARKET,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: TimeInForce = TimeInForce.DAY,
        bracket: Optional[Dict] = None,
    ) -> Optional[Order]:
        """
        Place an order.

        Args:
            symbol: Contract symbol (e.g., 'ES', 'NQ', 'ESH5')
            action: Buy or Sell
            quantity: Number of contracts
            order_type: Market, Limit, Stop, etc.
            price: Limit price (required for Limit orders)
            stop_price: Stop price (required for Stop orders)
            time_in_force: Day, GTC, IOC, FOK
            bracket: Optional bracket order params {profit_target, stop_loss}

        Returns:
            Order object or None if failed.
        """
        self._ensure_connected()

        contract_id = self.get_contract_id(symbol)
        if not contract_id:
            print(f"Contract not found: {symbol}")
            return None

        order_payload = {
            'accountSpec': self.config.username,
            'accountId': self.account_id,
            'action': action.value,
            'symbol': symbol,
            'orderQty': quantity,
            'orderType': order_type.value,
            'timeInForce': time_in_force.value,
            'isAutomated': True,
        }

        if price is not None:
            order_payload['price'] = price

        if stop_price is not None:
            order_payload['stopPrice'] = stop_price

        # Add bracket orders if specified
        if bracket:
            if 'profit_target' in bracket:
                order_payload['bracket1'] = {
                    'action': 'Sell' if action == OrderAction.BUY else 'Buy',
                    'orderType': 'Limit',
                    'price': bracket['profit_target'],
                }
            if 'stop_loss' in bracket:
                order_payload['bracket2'] = {
                    'action': 'Sell' if action == OrderAction.BUY else 'Buy',
                    'orderType': 'Stop',
                    'stopPrice': bracket['stop_loss'],
                }

        with self._lock:
            response = self.session.post(
                f"{self.base_url}/order/placeorder",
                json=order_payload,
                timeout=30
            )

        if response.status_code == 200:
            data = response.json()

            if 'errorText' in data:
                print(f"Order error: {data['errorText']}")
                return None

            order = Order(
                id=data.get('orderId', 0),
                account_id=self.account_id,
                contract_id=contract_id,
                action=action,
                order_type=order_type,
                quantity=quantity,
                price=price,
                stop_price=stop_price,
                time_in_force=time_in_force,
                status=data.get('orderStatus', {}).get('status', 'Unknown'),
            )

            print(f"Order placed: {action.value} {quantity} {symbol} @ {order_type.value}")
            return order
        else:
            print(f"Order failed: {response.status_code} - {response.text}")
            return None

    def place_bracket_order(
        self,
        symbol: str,
        action: OrderAction,
        quantity: int,
        entry_price: Optional[float] = None,
        stop_loss: float = None,
        take_profit: float = None,
        order_type: OrderType = OrderType.LIMIT,
    ) -> Optional[Order]:
        """
        Place a bracket order with stop loss and take profit.

        Args:
            symbol: Contract symbol
            action: Buy or Sell
            quantity: Number of contracts
            entry_price: Entry price (None for market)
            stop_loss: Stop loss price
            take_profit: Take profit price
            order_type: Entry order type (Limit or Market)

        Returns:
            Entry order or None if failed.
        """
        bracket = {}
        if take_profit:
            bracket['profit_target'] = take_profit
        if stop_loss:
            bracket['stop_loss'] = stop_loss

        return self.place_order(
            symbol=symbol,
            action=action,
            quantity=quantity,
            order_type=order_type,
            price=entry_price,
            bracket=bracket if bracket else None,
        )

    def cancel_order(self, order_id: int) -> bool:
        """
        Cancel an open order.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if cancelled successfully.
        """
        self._ensure_connected()

        with self._lock:
            response = self.session.post(
                f"{self.base_url}/order/cancelorder",
                json={'orderId': order_id},
                timeout=30
            )

        if response.status_code == 200:
            data = response.json()
            if 'errorText' not in data:
                print(f"Order {order_id} cancelled")
                return True
            print(f"Cancel error: {data['errorText']}")

        return False

    def modify_order(
        self,
        order_id: int,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        quantity: Optional[int] = None,
    ) -> bool:
        """
        Modify an existing order.

        Args:
            order_id: Order ID to modify
            price: New limit price
            stop_price: New stop price
            quantity: New quantity

        Returns:
            True if modified successfully.
        """
        self._ensure_connected()

        payload = {'orderId': order_id}
        if price is not None:
            payload['price'] = price
        if stop_price is not None:
            payload['stopPrice'] = stop_price
        if quantity is not None:
            payload['orderQty'] = quantity

        with self._lock:
            response = self.session.post(
                f"{self.base_url}/order/modifyorder",
                json=payload,
                timeout=30
            )

        if response.status_code == 200:
            data = response.json()
            if 'errorText' not in data:
                print(f"Order {order_id} modified")
                return True
            print(f"Modify error: {data['errorText']}")

        return False

    def get_orders(self) -> List[Order]:
        """Get all open orders."""
        self._ensure_connected()

        response = self.session.get(
            f"{self.base_url}/order/list",
            timeout=30
        )

        orders = []
        if response.status_code == 200:
            for o in response.json():
                orders.append(Order(
                    id=o.get('id', 0),
                    account_id=o.get('accountId', 0),
                    contract_id=o.get('contractId', 0),
                    action=OrderAction(o.get('action', 'Buy')),
                    order_type=OrderType(o.get('orderType', 'Market')),
                    quantity=o.get('orderQty', 0),
                    price=o.get('price'),
                    stop_price=o.get('stopPrice'),
                    status=o.get('ordStatus', ''),
                    filled_qty=o.get('filledQty', 0),
                    avg_fill_price=o.get('avgPx', 0),
                ))

        return orders

    def get_positions(self) -> List[Position]:
        """Get all open positions."""
        self._ensure_connected()

        response = self.session.get(
            f"{self.base_url}/position/list",
            timeout=30
        )

        positions = []
        if response.status_code == 200:
            for p in response.json():
                if p.get('netPos', 0) != 0:  # Only open positions
                    positions.append(Position(
                        id=p.get('id', 0),
                        account_id=p.get('accountId', 0),
                        contract_id=p.get('contractId', 0),
                        net_pos=p.get('netPos', 0),
                        net_price=p.get('netPrice', 0),
                    ))

        return positions

    def flatten_position(self, symbol: str) -> bool:
        """
        Close all positions for a symbol.

        Args:
            symbol: Contract symbol

        Returns:
            True if positions closed.
        """
        self._ensure_connected()

        contract_id = self.get_contract_id(symbol)
        if not contract_id:
            return False

        positions = self.get_positions()
        for pos in positions:
            if pos.contract_id == contract_id and pos.net_pos != 0:
                action = OrderAction.SELL if pos.net_pos > 0 else OrderAction.BUY
                quantity = abs(pos.net_pos)

                self.place_order(
                    symbol=symbol,
                    action=action,
                    quantity=quantity,
                    order_type=OrderType.MARKET,
                )
                print(f"Flattened {symbol}: {action.value} {quantity}")

        return True

    def flatten_all(self) -> bool:
        """Close all positions."""
        self._ensure_connected()

        positions = self.get_positions()
        for pos in positions:
            if pos.net_pos != 0:
                # Get symbol for contract
                response = self.session.get(
                    f"{self.base_url}/contract/item",
                    params={'id': pos.contract_id},
                    timeout=30
                )
                if response.status_code == 200:
                    contract = response.json()
                    symbol = contract.get('name', '')
                    if symbol:
                        self.flatten_position(symbol)

        return True

    def get_account_balance(self) -> Dict[str, float]:
        """Get account balance and margin info."""
        self._ensure_connected()

        response = self.session.get(
            f"{self.base_url}/cashBalance/getcashbalancesnapshot",
            params={'accountId': self.account_id},
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            return {
                'cash_balance': data.get('cashBalance', 0),
                'open_pnl': data.get('openPnl', 0),
                'realized_pnl': data.get('realizedPnl', 0),
                'margin_used': data.get('marginUsed', 0),
                'available_margin': data.get('availableForTrading', 0),
            }

        return {}

    def disconnect(self):
        """Disconnect and cleanup."""
        self.connected = False
        self.access_token = None
        self.session.close()
        print("Disconnected from Tradovate")


# Convenience function for quick setup
def create_client(environment: str = 'demo') -> TradovateClient:
    """
    Create a Tradovate client with configuration from file or environment.

    Args:
        environment: 'demo' or 'live'

    Returns:
        Configured TradovateClient instance.
    """
    config_path = 'config/tradovate_credentials.json'

    if os.path.exists(config_path):
        config = TradovateConfig.from_file(config_path)
    else:
        config = TradovateConfig.from_env()

    config.environment = Environment(environment)
    return TradovateClient(config)


if __name__ == '__main__':
    # Test connection
    print("Tradovate API Client Test")
    print("=" * 50)

    # Check for credentials
    config_path = 'config/tradovate_credentials.json'
    if not os.path.exists(config_path):
        print(f"\nCredentials file not found: {config_path}")
        print("\nCreate the file with the following structure:")
        print(json.dumps({
            "username": "your_username",
            "password": "your_password",
            "app_id": "your_app_id",
            "cid": 0,
            "sec": "your_client_secret",
            "device_id": "tradovate-bot",
            "environment": "demo"
        }, indent=2))
    else:
        client = create_client('demo')
        if client.connect():
            print("\nAccount Balance:")
            balance = client.get_account_balance()
            for k, v in balance.items():
                print(f"  {k}: ${v:,.2f}")

            print("\nOpen Positions:")
            positions = client.get_positions()
            if positions:
                for p in positions:
                    print(f"  Contract {p.contract_id}: {p.net_pos} @ {p.net_price}")
            else:
                print("  No open positions")

            client.disconnect()
