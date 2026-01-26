"""
ICT_Sweep_OTE_MSS_FVG_Long_v1 - Alerts & Notifications

Provides alert mechanisms for:
- Sweep detection
- MSS confirmation
- Entry signals
- Trade management events
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable
from enum import Enum
import logging
import json


class AlertLevel(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    SIGNAL = "SIGNAL"
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ERROR = "ERROR"


@dataclass
class Alert:
    """Represents an alert to be sent."""
    timestamp: datetime
    level: AlertLevel
    title: str
    message: str
    symbol: str = ""
    price: float = 0.0
    metadata: dict = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.value,
            "title": self.title,
            "message": self.message,
            "symbol": self.symbol,
            "price": self.price,
            "metadata": self.metadata or {},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class AlertHandler(ABC):
    """Abstract base class for alert handlers."""

    @abstractmethod
    def send(self, alert: Alert):
        """Send an alert."""
        pass


class ConsoleAlertHandler(AlertHandler):
    """Print alerts to console."""

    def __init__(self, level_filter: AlertLevel = None):
        self.level_filter = level_filter
        self.logger = logging.getLogger("Alerts")

    def send(self, alert: Alert):
        if self.level_filter and alert.level != self.level_filter:
            return

        emoji = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.SIGNAL: "🎯",
            AlertLevel.ENTRY: "🟢",
            AlertLevel.EXIT: "🔴",
            AlertLevel.ERROR: "❌",
        }.get(alert.level, "")

        msg = f"{emoji} [{alert.level.value}] {alert.title}"
        if alert.symbol:
            msg += f" | {alert.symbol}"
        if alert.price:
            msg += f" @ {alert.price:.2f}"
        msg += f"\n   {alert.message}"

        print(msg)


class FileAlertHandler(AlertHandler):
    """Write alerts to file."""

    def __init__(self, filepath: str):
        self.filepath = filepath

    def send(self, alert: Alert):
        with open(self.filepath, "a") as f:
            f.write(alert.to_json() + "\n")


class WebhookAlertHandler(AlertHandler):
    """Send alerts to webhook (Discord, Slack, etc.)."""

    def __init__(self, webhook_url: str, format_func: Callable[[Alert], dict] = None):
        self.webhook_url = webhook_url
        self.format_func = format_func or self._default_format

    def _default_format(self, alert: Alert) -> dict:
        """Default webhook format (Discord compatible)."""
        color_map = {
            AlertLevel.INFO: 3447003,      # Blue
            AlertLevel.WARNING: 16776960,  # Yellow
            AlertLevel.SIGNAL: 15105570,   # Orange
            AlertLevel.ENTRY: 3066993,     # Green
            AlertLevel.EXIT: 15158332,     # Red
            AlertLevel.ERROR: 10038562,    # Dark red
        }

        return {
            "embeds": [{
                "title": alert.title,
                "description": alert.message,
                "color": color_map.get(alert.level, 0),
                "fields": [
                    {"name": "Symbol", "value": alert.symbol or "N/A", "inline": True},
                    {"name": "Price", "value": f"{alert.price:.2f}" if alert.price else "N/A", "inline": True},
                    {"name": "Level", "value": alert.level.value, "inline": True},
                ],
                "timestamp": alert.timestamp.isoformat(),
            }]
        }

    def send(self, alert: Alert):
        try:
            import requests
            payload = self.format_func(alert)
            requests.post(self.webhook_url, json=payload, timeout=5)
        except Exception as e:
            logging.error(f"Webhook alert failed: {e}")


class AlertManager:
    """Manages multiple alert handlers."""

    def __init__(self):
        self.handlers: list[AlertHandler] = []
        self.enabled = True

    def add_handler(self, handler: AlertHandler):
        """Add an alert handler."""
        self.handlers.append(handler)

    def remove_handler(self, handler: AlertHandler):
        """Remove an alert handler."""
        if handler in self.handlers:
            self.handlers.remove(handler)

    def send(self, alert: Alert):
        """Send alert to all handlers."""
        if not self.enabled:
            return

        for handler in self.handlers:
            try:
                handler.send(alert)
            except Exception as e:
                logging.error(f"Alert handler error: {e}")

    def send_sweep_alert(
        self,
        symbol: str,
        swept_price: float,
        sweep_low: float,
        timestamp: datetime,
    ):
        """Send sweep detection alert."""
        alert = Alert(
            timestamp=timestamp,
            level=AlertLevel.SIGNAL,
            title="SSL SWEEP DETECTED",
            message=f"Sell-side liquidity swept. Previous low {swept_price:.2f} taken, "
                    f"sweep low {sweep_low:.2f}",
            symbol=symbol,
            price=sweep_low,
            metadata={"swept_price": swept_price},
        )
        self.send(alert)

    def send_mss_alert(
        self,
        symbol: str,
        break_price: float,
        lh_price: float,
        timestamp: datetime,
    ):
        """Send MSS confirmation alert."""
        alert = Alert(
            timestamp=timestamp,
            level=AlertLevel.SIGNAL,
            title="MSS CONFIRMED",
            message=f"Market structure shift confirmed. Broke above LH at {lh_price:.2f}",
            symbol=symbol,
            price=break_price,
            metadata={"lh_price": lh_price},
        )
        self.send(alert)

    def send_entry_alert(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_price: float,
        targets: list[float],
        contracts: int,
        timestamp: datetime,
    ):
        """Send entry signal alert."""
        tp_str = ", ".join([f"{t:.2f}" for t in targets])
        alert = Alert(
            timestamp=timestamp,
            level=AlertLevel.ENTRY,
            title=f"ENTRY SIGNAL: {direction}",
            message=f"Entry: {entry_price:.2f} | Stop: {stop_price:.2f} | "
                    f"Targets: {tp_str} | Size: {contracts} contracts",
            symbol=symbol,
            price=entry_price,
            metadata={
                "direction": direction,
                "stop": stop_price,
                "targets": targets,
                "contracts": contracts,
            },
        )
        self.send(alert)

    def send_exit_alert(
        self,
        symbol: str,
        exit_type: str,  # "TP1", "TP2", "TP3", "STOP"
        exit_price: float,
        pnl: float,
        timestamp: datetime,
    ):
        """Send trade exit alert."""
        pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
        alert = Alert(
            timestamp=timestamp,
            level=AlertLevel.EXIT,
            title=f"EXIT: {exit_type}",
            message=f"Exited at {exit_price:.2f} | P&L: {pnl_str}",
            symbol=symbol,
            price=exit_price,
            metadata={"exit_type": exit_type, "pnl": pnl},
        )
        self.send(alert)


# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

def setup_logging(
    log_level: str = "INFO",
    log_file: str = None,
    console: bool = True,
) -> logging.Logger:
    """
    Setup logging for the strategy.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path for log output
        console: Whether to output to console

    Returns:
        Configured logger
    """
    logger = logging.getLogger("ICT_Strategy")
    logger.setLevel(getattr(logging, log_level.upper()))

    formatter = logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
