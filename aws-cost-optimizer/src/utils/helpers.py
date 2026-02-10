"""Utility functions for configuration, logging, and common operations."""

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load the main configuration file.

    Args:
        config_path: Optional path to config file. If not provided,
                     uses default config/config.yaml

    Returns:
        Configuration dictionary
    """
    if config_path is None:
        config_path = get_project_root() / "config" / "config.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_credentials(credentials_path: Optional[str] = None) -> Dict[str, Any]:
    """Load API credentials.

    Args:
        credentials_path: Optional path to credentials file. If not provided,
                          uses default config/credentials.yaml

    Returns:
        Credentials dictionary

    Raises:
        FileNotFoundError: If credentials file not found
    """
    if credentials_path is None:
        credentials_path = get_project_root() / "config" / "credentials.yaml"
    else:
        credentials_path = Path(credentials_path)

    if not credentials_path.exists():
        template_path = get_project_root() / "config" / "credentials.template.yaml"
        raise FileNotFoundError(
            f"Credentials file not found: {credentials_path}\n"
            f"Please copy {template_path} to {credentials_path} and fill in your credentials."
        )

    with open(credentials_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_instance_types(instance_types_path: Optional[str] = None) -> Dict[str, Any]:
    """Load the instance types catalog.

    Args:
        instance_types_path: Optional path to instance types file

    Returns:
        Instance types dictionary
    """
    if instance_types_path is None:
        instance_types_path = get_project_root() / "config" / "instance_types.yaml"
    else:
        instance_types_path = Path(instance_types_path)

    if not instance_types_path.exists():
        raise FileNotFoundError(f"Instance types file not found: {instance_types_path}")

    with open(instance_types_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(
    level: str = "INFO",
    log_format: Optional[str] = None,
    log_file: Optional[str] = None
) -> logging.Logger:
    """Set up logging configuration.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Optional custom log format
        log_file: Optional log file path

    Returns:
        Configured logger
    """
    if log_format is None:
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
        handlers=[]
    )

    logger = logging.getLogger("aws_cost_optimizer")
    logger.setLevel(getattr(logging, level.upper()))

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(log_format))
        logger.addHandler(file_handler)

    return logger


def parse_instance_type(instance_type: str) -> Dict[str, str]:
    """Parse an EC2 instance type string into family and size.

    Args:
        instance_type: EC2 instance type (e.g., "m5.xlarge")

    Returns:
        Dictionary with 'family' and 'size' keys

    Examples:
        >>> parse_instance_type("m5.xlarge")
        {'family': 'm5', 'size': 'xlarge'}
        >>> parse_instance_type("t3a.medium")
        {'family': 't3a', 'size': 'medium'}
    """
    parts = instance_type.split(".")
    if len(parts) != 2:
        raise ValueError(f"Invalid instance type format: {instance_type}")

    return {
        "family": parts[0],
        "size": parts[1]
    }


def format_currency(amount: float, currency: str = "USD") -> str:
    """Format a number as currency.

    Args:
        amount: Amount to format
        currency: Currency code (default USD)

    Returns:
        Formatted currency string
    """
    if currency == "USD":
        return f"${amount:,.2f}"
    return f"{amount:,.2f} {currency}"


def format_percentage(value: float, decimals: int = 1) -> str:
    """Format a decimal as percentage.

    Args:
        value: Value to format (0-100 or 0-1)
        decimals: Number of decimal places

    Returns:
        Formatted percentage string
    """
    # If value looks like a ratio (0-1), convert to percentage
    if 0 <= value <= 1:
        value = value * 100

    return f"{value:.{decimals}f}%"


def calculate_monthly_hours() -> float:
    """Calculate average hours in a month.

    Returns:
        Average monthly hours (730)
    """
    return 730.0  # Standard AWS calculation


def bytes_to_gb(bytes_value: float) -> float:
    """Convert bytes to gigabytes.

    Args:
        bytes_value: Value in bytes

    Returns:
        Value in gigabytes
    """
    return bytes_value / (1024 ** 3)
