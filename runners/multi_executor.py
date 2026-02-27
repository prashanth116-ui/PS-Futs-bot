"""
Multi-Executor — Fans out trade lifecycle calls to multiple backends in parallel.

Enables running personal (direct API) + prop firm (webhook) simultaneously.
All executors receive the same calls; failures in one don't block others.

Usage:
    direct = TradovateExecutor("config/tradovate_direct.json")
    webhook = WebhookExecutor("config/pickmytrade_accounts.json")
    executor = MultiExecutor([direct, webhook])
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from runners.executor_interface import ExecutorInterface

logger = logging.getLogger(__name__)


class MultiExecutor(ExecutorInterface):
    """Wraps multiple executors, fanning out calls in parallel."""

    def __init__(self, executors: List[ExecutorInterface]):
        if not executors:
            raise ValueError("MultiExecutor requires at least one executor")
        self.executors = executors
        self._pool = ThreadPoolExecutor(max_workers=len(executors))
        logger.info("MultiExecutor initialized with %d backend(s)", len(executors))

    def get_account_count(self) -> int:
        return sum(e.get_account_count() for e in self.executors)

    def _fan_out(self, method_name: str, *args, **kwargs) -> Dict:
        """Call a method on all executors in parallel, collect results."""
        futures_map = {}
        for i, executor in enumerate(self.executors):
            method = getattr(executor, method_name)
            future = self._pool.submit(method, *args, **kwargs)
            futures_map[future] = f"{type(executor).__name__}[{i}]"

        results = {}
        for future in as_completed(futures_map, timeout=30):
            name = futures_map[future]
            try:
                results[name] = future.result()
            except Exception as e:
                logger.error("[MULTI] %s.%s failed: %s", name, method_name, e)
                results[name] = {"success": False, "error": str(e)}

        return results

    def open_position(
        self,
        symbol: str,
        direction: str,
        contracts: int,
        stop_price: float,
        entry_price: float,
        paper_trade_id: str = "",
    ) -> Dict:
        return self._fan_out(
            "open_position",
            symbol=symbol, direction=direction, contracts=contracts,
            stop_price=stop_price, entry_price=entry_price,
            paper_trade_id=paper_trade_id,
        )

    def partial_close(
        self,
        symbol: str,
        direction: str,
        contracts: int,
        paper_trade_id: str = "",
    ) -> Dict:
        return self._fan_out(
            "partial_close",
            symbol=symbol, direction=direction, contracts=contracts,
            paper_trade_id=paper_trade_id,
        )

    def update_stop(
        self,
        symbol: str,
        direction: str,
        new_stop_price: float,
        entry_price: float,
        paper_trade_id: str = "",
    ) -> Dict:
        return self._fan_out(
            "update_stop",
            symbol=symbol, direction=direction,
            new_stop_price=new_stop_price, entry_price=entry_price,
            paper_trade_id=paper_trade_id,
        )

    def close_position(
        self,
        symbol: str,
        direction: str,
        paper_trade_id: str = "",
    ) -> Dict:
        return self._fan_out(
            "close_position",
            symbol=symbol, direction=direction,
            paper_trade_id=paper_trade_id,
        )

    def close_all(self, symbol: Optional[str] = None) -> Dict:
        return self._fan_out("close_all", symbol=symbol)
