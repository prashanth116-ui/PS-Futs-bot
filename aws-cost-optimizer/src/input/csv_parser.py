"""CSV/Excel input parser for server lists."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)


class CSVParser:
    """Parser for CSV and Excel files containing server information.

    Supports various column naming conventions and auto-detects format.
    """

    # Common column name mappings
    COLUMN_MAPPINGS = {
        # Hostname mappings
        "hostname": ["hostname", "host", "server", "server_name", "servername", "name", "host_name"],
        # Instance ID mappings
        "instance_id": ["instance_id", "instanceid", "instance", "ec2_instance", "aws_instance_id"],
        # IP address mappings
        "ip_address": ["ip_address", "ip", "private_ip", "ipaddress", "internal_ip"],
        # Tags/Labels
        "gsi": ["gsi", "cost_center", "costcenter", "project", "application", "app"],
        "environment": ["environment", "env", "stage"],
        "team": ["team", "owner", "group"],
        # Instance type
        "instance_type": ["instance_type", "instancetype", "type", "size", "ec2_type"],
    }

    def __init__(self, file_path: Union[str, Path]):
        """Initialize the parser.

        Args:
            file_path: Path to CSV or Excel file
        """
        self.file_path = Path(file_path)

        if not self.file_path.exists():
            raise FileNotFoundError(f"Input file not found: {self.file_path}")

        self.df: Optional[pd.DataFrame] = None
        self._column_map: Dict[str, str] = {}

    def parse(self, sheet_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Parse the input file.

        Args:
            sheet_name: Sheet name for Excel files (default: first sheet)

        Returns:
            List of server dictionaries
        """
        # Read file based on extension
        suffix = self.file_path.suffix.lower()

        if suffix == ".csv":
            self.df = pd.read_csv(self.file_path)
        elif suffix in [".xlsx", ".xls"]:
            self.df = pd.read_excel(self.file_path, sheet_name=sheet_name or 0)
        else:
            raise ValueError(f"Unsupported file format: {suffix}")

        # Normalize column names
        self.df.columns = [str(c).lower().strip() for c in self.df.columns]

        # Map columns to standard names
        self._map_columns()

        # Convert to list of dictionaries
        servers = self._convert_to_servers()

        logger.info(f"Parsed {len(servers)} servers from {self.file_path.name}")
        return servers

    def _map_columns(self) -> None:
        """Map actual column names to standard names."""
        actual_columns = set(self.df.columns)

        for standard_name, variants in self.COLUMN_MAPPINGS.items():
            for variant in variants:
                if variant in actual_columns:
                    self._column_map[standard_name] = variant
                    break

        # Log mapping results
        mapped = list(self._column_map.keys())
        unmapped = [c for c in actual_columns if c not in self._column_map.values()]

        logger.debug(f"Mapped columns: {mapped}")
        if unmapped:
            logger.debug(f"Additional columns (unmapped): {unmapped}")

    def _get_column_value(self, row: pd.Series, standard_name: str) -> Optional[str]:
        """Get a value from a row using standard column name.

        Args:
            row: DataFrame row
            standard_name: Standard column name

        Returns:
            Column value or None if not found
        """
        if standard_name in self._column_map:
            value = row.get(self._column_map[standard_name])
            if pd.notna(value):
                return str(value).strip()
        return None

    def _convert_to_servers(self) -> List[Dict[str, Any]]:
        """Convert DataFrame to list of server dictionaries.

        Returns:
            List of server dictionaries
        """
        servers = []

        for _, row in self.df.iterrows():
            server = {
                "hostname": self._get_column_value(row, "hostname"),
                "instance_id": self._get_column_value(row, "instance_id"),
                "ip_address": self._get_column_value(row, "ip_address"),
                "instance_type": self._get_column_value(row, "instance_type"),
                "tags": {}
            }

            # Add tag fields
            for tag_field in ["gsi", "environment", "team"]:
                value = self._get_column_value(row, tag_field)
                if value:
                    server["tags"][tag_field.upper()] = value

            # Include any additional columns as metadata
            for col in self.df.columns:
                if col not in self._column_map.values():
                    value = row.get(col)
                    if pd.notna(value):
                        server["tags"][col.upper()] = str(value).strip()

            # Skip rows without identifier
            if not server["hostname"] and not server["instance_id"] and not server["ip_address"]:
                continue

            servers.append(server)

        return servers

    def validate(self) -> Dict[str, Any]:
        """Validate the parsed data.

        Returns:
            Validation results with counts and issues
        """
        if self.df is None:
            raise RuntimeError("Call parse() before validate()")

        issues = []

        # Check for required columns
        if "hostname" not in self._column_map and "instance_id" not in self._column_map:
            issues.append("No hostname or instance_id column found")

        # Check for duplicates
        if "hostname" in self._column_map:
            hostname_col = self._column_map["hostname"]
            duplicates = self.df[hostname_col].dropna().duplicated().sum()
            if duplicates > 0:
                issues.append(f"Found {duplicates} duplicate hostnames")

        if "instance_id" in self._column_map:
            instance_col = self._column_map["instance_id"]
            duplicates = self.df[instance_col].dropna().duplicated().sum()
            if duplicates > 0:
                issues.append(f"Found {duplicates} duplicate instance IDs")

        # Check for missing values
        missing_counts = {}
        for standard_name, actual_col in self._column_map.items():
            missing = self.df[actual_col].isna().sum()
            if missing > 0:
                missing_counts[standard_name] = missing

        return {
            "total_rows": len(self.df),
            "valid_rows": len(self.df) - sum(missing_counts.values()),
            "mapped_columns": list(self._column_map.keys()),
            "missing_values": missing_counts,
            "issues": issues,
            "is_valid": len(issues) == 0
        }

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics of the parsed data.

        Returns:
            Summary statistics
        """
        if self.df is None:
            raise RuntimeError("Call parse() before get_summary()")

        summary = {
            "total_servers": len(self.df),
            "columns": list(self.df.columns),
            "mapped_columns": dict(self._column_map),
        }

        # Count by GSI if available
        if "gsi" in self._column_map:
            gsi_col = self._column_map["gsi"]
            summary["by_gsi"] = self.df[gsi_col].value_counts().to_dict()

        # Count by environment if available
        if "environment" in self._column_map:
            env_col = self._column_map["environment"]
            summary["by_environment"] = self.df[env_col].value_counts().to_dict()

        return summary


def parse_server_list(
    file_path: Union[str, Path],
    sheet_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Convenience function to parse a server list file.

    Args:
        file_path: Path to CSV or Excel file
        sheet_name: Sheet name for Excel files

    Returns:
        List of server dictionaries
    """
    parser = CSVParser(file_path)
    return parser.parse(sheet_name=sheet_name)
