"""
PickMyTrade Webhook Executor

Sends trade lifecycle events (entry, partial close, trail update, close)
to PickMyTrade's webhook API for execution on Tradovate accounts.

Works alongside paper mode: the bot's paper engine is the "brain" that
manages the full trade lifecycle, and this module fires HTTP calls at
each lifecycle event.

Usage:
    executor = WebhookExecutor("config/pickmytrade_accounts.json", "ict_v10")
    executor.open_position("ES", "LONG", 3, stop_price=6100.0, entry_price=6110.0, paper_trade_id="PAPER_ES_1")
    executor.partial_close("ES", "LONG", 1, paper_trade_id="PAPER_ES_1")
    executor.update_stop("ES", "LONG", new_stop_price=6110.0, entry_price=6110.0, paper_trade_id="PAPER_ES_1")
    executor.close_position("ES", "LONG", paper_trade_id="PAPER_ES_1")
"""

import json
import math
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)

# Point values per tick for dollar_sl calculation
# dollar_sl = risk_points * point_value (PickMyTrade applies per-contract)
POINT_VALUES = {
    'ES': 50.0,   # $12.50/tick * 4 ticks/point
    'NQ': 20.0,   # $5.00/tick * 4 ticks/point
    'MES': 5.0,   # $1.25/tick * 4 ticks/point
    'MNQ': 2.0,   # $0.50/tick * 4 ticks/point
}


class WebhookExecutor:
    """Sends trade events to PickMyTrade webhook API.

    Fires HTTP calls to all enabled accounts in parallel using a thread pool.
    Paper mode continues regardless of webhook success/failure.
    """

    def __init__(self, config_path: str, strategy_group: str = "ict_v10"):
        config_file = Path(config_path)
        if not config_file.exists():
            raise FileNotFoundError(f"PickMyTrade config not found: {config_path}")

        with open(config_file) as f:
            self.config = json.load(f)

        self.api_url = self.config["api_url"]
        self.retry_max = self.config.get("retry_max", 2)
        self.retry_delay = self.config.get("retry_delay_sec", 1.0)
        self.contract_months = self.config["contract_months"]

        # Load strategy group accounts
        group = self.config["strategy_groups"].get(strategy_group)
        if not group:
            raise ValueError(f"Strategy group '{strategy_group}' not found in config")

        self.primary = group["primary_account"]
        self.mirrors = group.get("mirror_accounts", [])

        # Thread pool for parallel account execution
        account_count = self.get_account_count()
        self._pool = ThreadPoolExecutor(max_workers=max(account_count, 1))

        logger.info(
            "WebhookExecutor initialized: %d account(s), strategy=%s",
            account_count, strategy_group,
        )

    def get_account_count(self) -> int:
        """Return number of enabled accounts."""
        count = 1 if self.primary.get("enabled", True) else 0
        count += sum(1 for m in self.mirrors if m.get("enabled", True))
        return count

    def _get_pmt_symbol(self, symbol: str) -> str:
        """Map base symbol (ES) to contract month symbol (ESM6)."""
        return self.contract_months.get(symbol, symbol)

    def _get_enabled_accounts(self) -> List[Dict]:
        """Return list of all enabled accounts."""
        accounts = []
        if self.primary.get("enabled", True):
            accounts.append(self.primary)
        for m in self.mirrors:
            if m.get("enabled", True):
                accounts.append(m)
        return accounts

    def _build_multiple_accounts(self, exclude_primary: bool = False) -> List[Dict]:
        """Build the multiple_accounts array for mirror accounts.

        PickMyTrade's multiple_accounts field sends the same order to
        additional accounts. The primary account is specified at the
        top level of the payload.
        """
        mirrors = []
        for m in self.mirrors:
            if not m.get("enabled", True):
                continue
            mirrors.append({
                "token": m["token"],
                "account_id": m["account_id"],
                "quantity_multiplier": m.get("qty_multiplier", 1.0),
            })
        return mirrors

    def _calculate_dollar_sl(self, symbol: str, entry_price: float, stop_price: float) -> float:
        """Calculate dollar_sl for PickMyTrade.

        PickMyTrade interprets dollar_sl as per-contract dollar risk from entry.
        dollar_sl = abs(entry - stop) * point_value
        """
        point_value = POINT_VALUES.get(symbol)
        if not point_value:
            raise ValueError(f"No point value for symbol: {symbol}")

        risk_points = abs(entry_price - stop_price)
        return round(risk_points * point_value, 2)

    def _send_webhook(self, payload: Dict, account_name: str) -> Dict:
        """Send a single webhook request with retries.

        Returns:
            {"success": bool, "status_code": int, "error": str or None, "account": str}
        """
        body = json.dumps(payload).encode("utf-8")

        for attempt in range(self.retry_max + 1):
            try:
                req = Request(
                    self.api_url,
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(req, timeout=10) as resp:
                    status = resp.status
                    resp_body = resp.read().decode("utf-8", errors="replace")

                logger.info(
                    "[WEBHOOK] %s: %s (status=%d)",
                    account_name, payload.get("data", "?"), status,
                )
                return {
                    "success": True,
                    "status_code": status,
                    "error": None,
                    "account": account_name,
                    "response": resp_body,
                }

            except HTTPError as e:
                status = e.code
                err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
                logger.warning(
                    "[WEBHOOK] %s: HTTP %d - %s (attempt %d)",
                    account_name, status, err_body[:200], attempt + 1,
                )
                # Don't retry 4xx (bad payload)
                if 400 <= status < 500:
                    return {
                        "success": False,
                        "status_code": status,
                        "error": f"HTTP {status}: {err_body[:200]}",
                        "account": account_name,
                    }

            except (URLError, OSError) as e:
                logger.warning(
                    "[WEBHOOK] %s: Network error - %s (attempt %d)",
                    account_name, str(e), attempt + 1,
                )

            # Retry delay (skip on last attempt)
            if attempt < self.retry_max:
                time.sleep(self.retry_delay)

        return {
            "success": False,
            "status_code": 0,
            "error": f"Failed after {self.retry_max + 1} attempts",
            "account": account_name,
        }

    def _fire_all_accounts(self, build_payload_fn) -> Dict[str, Dict]:
        """Fire webhooks to all enabled accounts in parallel.

        Args:
            build_payload_fn: callable(account) -> payload dict

        Returns:
            {account_name: result_dict}
        """
        accounts = self._get_enabled_accounts()
        if not accounts:
            logger.warning("[WEBHOOK] No enabled accounts")
            return {}

        futures_map = {}
        for acct in accounts:
            payload = build_payload_fn(acct)
            future = self._pool.submit(self._send_webhook, payload, acct["name"])
            futures_map[future] = acct["name"]

        results = {}
        for future in as_completed(futures_map, timeout=30):
            name = futures_map[future]
            try:
                results[name] = future.result()
            except Exception as e:
                logger.error("[WEBHOOK] %s: Exception - %s", name, e)
                results[name] = {
                    "success": False,
                    "status_code": 0,
                    "error": str(e),
                    "account": name,
                }

        # Log summary
        ok = sum(1 for r in results.values() if r["success"])
        fail = len(results) - ok
        if fail > 0:
            logger.warning("[WEBHOOK] Results: %d ok, %d failed", ok, fail)
        else:
            logger.info("[WEBHOOK] Results: %d ok", ok)

        return results

    def open_position(
        self,
        symbol: str,
        direction: str,
        contracts: int,
        stop_price: float,
        entry_price: float,
        paper_trade_id: str = "",
    ) -> Dict[str, Dict]:
        """Open a new position on all accounts.

        Sends a market order with an initial protective stop.
        The stop is a safety net — the bot manages all exits.
        """
        pmt_symbol = self._get_pmt_symbol(symbol)
        action = "buy" if direction == "LONG" else "sell"
        dollar_sl = self._calculate_dollar_sl(symbol, entry_price, stop_price)

        logger.info(
            "[WEBHOOK] ENTRY: %s %s %d @ %.2f stop=%.2f sl=$%.2f [%s]",
            action.upper(), pmt_symbol, contracts, entry_price, stop_price, dollar_sl, paper_trade_id,
        )

        def build(acct):
            qty = max(1, math.floor(contracts * acct.get("qty_multiplier", 1.0)))
            payload = {
                "token": acct["token"],
                "account_id": acct["account_id"],
                "symbol": pmt_symbol,
                "data": action,
                "quantity": qty,
                "advance_tp_sl": [{
                    "quantity": qty,
                    "dollar_tp": 0,
                    "dollar_sl": dollar_sl,
                    "trail": 0,
                }],
            }
            # Add mirror accounts only for primary
            mirrors = self._build_multiple_accounts()
            if mirrors and acct["name"] == self.primary["name"]:
                payload["multiple_accounts"] = mirrors
            return payload

        return self._fire_all_accounts(build)

    def partial_close(
        self,
        symbol: str,
        direction: str,
        contracts: int,
        paper_trade_id: str = "",
    ) -> Dict[str, Dict]:
        """Close part of a position (T1/T2 exits).

        Sends an opposing market order for the specified number of contracts.
        """
        pmt_symbol = self._get_pmt_symbol(symbol)
        # Opposing direction to close
        action = "sell" if direction == "LONG" else "buy"

        logger.info(
            "[WEBHOOK] PARTIAL CLOSE: %s %s %d [%s]",
            action.upper(), pmt_symbol, contracts, paper_trade_id,
        )

        def build(acct):
            qty = max(1, math.floor(contracts * acct.get("qty_multiplier", 1.0)))
            payload = {
                "token": acct["token"],
                "account_id": acct["account_id"],
                "symbol": pmt_symbol,
                "data": action,
                "quantity": qty,
            }
            mirrors = self._build_multiple_accounts()
            if mirrors and acct["name"] == self.primary["name"]:
                payload["multiple_accounts"] = mirrors
            return payload

        return self._fire_all_accounts(build)

    def update_stop(
        self,
        symbol: str,
        direction: str,
        new_stop_price: float,
        entry_price: float,
        paper_trade_id: str = "",
    ) -> Dict[str, Dict]:
        """Update the broker-side stop loss.

        Uses PickMyTrade's update_sl to move the protective stop.
        dollar_sl is recalculated from the new stop relative to entry.
        """
        pmt_symbol = self._get_pmt_symbol(symbol)
        # update_sl uses the entry direction (not opposing)
        action = "buy" if direction == "LONG" else "sell"
        dollar_sl = self._calculate_dollar_sl(symbol, entry_price, new_stop_price)

        logger.info(
            "[WEBHOOK] UPDATE STOP: %s %s new_stop=%.2f sl=$%.2f [%s]",
            action.upper(), pmt_symbol, new_stop_price, dollar_sl, paper_trade_id,
        )

        def build(acct):
            payload = {
                "token": acct["token"],
                "account_id": acct["account_id"],
                "symbol": pmt_symbol,
                "data": action,
                "update_sl": True,
                "dollar_sl": dollar_sl,
            }
            mirrors = self._build_multiple_accounts()
            if mirrors and acct["name"] == self.primary["name"]:
                payload["multiple_accounts"] = mirrors
            return payload

        return self._fire_all_accounts(build)

    def close_position(
        self,
        symbol: str,
        direction: str,
        paper_trade_id: str = "",
    ) -> Dict[str, Dict]:
        """Close entire remaining position for a symbol.

        Used for: runner exit, EOD close, full stop-out.
        """
        pmt_symbol = self._get_pmt_symbol(symbol)

        logger.info(
            "[WEBHOOK] CLOSE: %s %s [%s]",
            direction, pmt_symbol, paper_trade_id,
        )

        def build(acct):
            payload = {
                "token": acct["token"],
                "account_id": acct["account_id"],
                "symbol": pmt_symbol,
                "data": "close",
            }
            mirrors = self._build_multiple_accounts()
            if mirrors and acct["name"] == self.primary["name"]:
                payload["multiple_accounts"] = mirrors
            return payload

        return self._fire_all_accounts(build)

    def close_all(self, symbol: Optional[str] = None) -> Dict[str, Dict]:
        """Close all positions, optionally filtered by symbol.

        Emergency/EOD catch-all.
        """
        if symbol:
            pmt_symbol = self._get_pmt_symbol(symbol)
            logger.info("[WEBHOOK] CLOSE ALL: %s", pmt_symbol)
        else:
            pmt_symbol = None
            logger.info("[WEBHOOK] CLOSE ALL positions")

        def build(acct):
            payload = {
                "token": acct["token"],
                "account_id": acct["account_id"],
                "data": "close",
            }
            if pmt_symbol:
                payload["symbol"] = pmt_symbol
            mirrors = self._build_multiple_accounts()
            if mirrors and acct["name"] == self.primary["name"]:
                payload["multiple_accounts"] = mirrors
            return payload

        return self._fire_all_accounts(build)
