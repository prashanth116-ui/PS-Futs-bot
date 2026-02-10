"""Metrics analysis for CPU, memory, and disk usage."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MetricStats:
    """Statistics for a single metric."""

    metric_name: str
    count: int
    average: float
    median: float
    min_value: float
    max_value: float
    p50: float
    p75: float
    p90: float
    p95: float
    p99: float
    std_dev: float
    data_days: int  # Number of days of data

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "metric_name": self.metric_name,
            "count": self.count,
            "average": round(self.average, 2),
            "median": round(self.median, 2),
            "min": round(self.min_value, 2),
            "max": round(self.max_value, 2),
            "p50": round(self.p50, 2),
            "p75": round(self.p75, 2),
            "p90": round(self.p90, 2),
            "p95": round(self.p95, 2),
            "p99": round(self.p99, 2),
            "std_dev": round(self.std_dev, 2),
            "data_days": self.data_days,
        }


@dataclass
class ServerMetrics:
    """Aggregated metrics for a server."""

    server_id: str
    hostname: Optional[str]
    cpu: Optional[MetricStats]
    memory: Optional[MetricStats]
    disk: Optional[MetricStats]
    data_start: Optional[datetime]
    data_end: Optional[datetime]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "server_id": self.server_id,
            "hostname": self.hostname,
            "cpu": self.cpu.to_dict() if self.cpu else None,
            "memory": self.memory.to_dict() if self.memory else None,
            "disk": self.disk.to_dict() if self.disk else None,
            "data_start": self.data_start.isoformat() if self.data_start else None,
            "data_end": self.data_end.isoformat() if self.data_end else None,
        }


class MetricsAnalyzer:
    """Analyzer for server resource metrics.

    Calculates statistics including average, peak, and percentile values
    for CPU, memory, and disk usage.
    """

    # Minimum requirements for reliable analysis
    MIN_DATA_POINTS = 10
    MIN_DATA_DAYS = 7  # At least 1 week of data

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the analyzer.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.min_data_points = self.config.get("min_data_points", self.MIN_DATA_POINTS)
        self.min_data_days = self.config.get("min_data_days", self.MIN_DATA_DAYS)

    def validate_metrics(
        self,
        metrics_data: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        """Validate metrics data quality.

        Args:
            metrics_data: Dictionary with metric data by type

        Returns:
            Validation report dictionary
        """
        report = {
            "valid": True,
            "warnings": [],
            "metrics": {}
        }

        for metric_key in ["cpu", "memory", "disk_used"]:
            data = metrics_data.get(metric_key, [])
            metric_report = {
                "has_data": len(data) > 0,
                "data_points": len(data),
                "sufficient_points": len(data) >= self.min_data_points,
                "days_of_data": 0,
                "sufficient_days": False,
            }

            if data:
                values = [dp.get("value") for dp in data if dp.get("value") is not None]
                timestamps = [dp.get("timestamp") for dp in data if dp.get("timestamp")]

                if timestamps:
                    days = (max(timestamps) - min(timestamps)).days
                    metric_report["days_of_data"] = days
                    metric_report["sufficient_days"] = days >= self.min_data_days

                metric_report["valid_values"] = len(values)

            if not metric_report["has_data"]:
                report["warnings"].append(f"No {metric_key} data available")
            elif not metric_report["sufficient_points"]:
                report["warnings"].append(
                    f"Insufficient {metric_key} data points: {metric_report['data_points']} "
                    f"(need {self.min_data_points})"
                )
            elif not metric_report["sufficient_days"]:
                report["warnings"].append(
                    f"Short {metric_key} data period: {metric_report['days_of_data']} days "
                    f"(recommend {self.min_data_days})"
                )

            report["metrics"][metric_key] = metric_report

        # Overall validity
        cpu_valid = report["metrics"].get("cpu", {}).get("sufficient_points", False)
        memory_valid = report["metrics"].get("memory", {}).get("sufficient_points", False)

        if not cpu_valid and not memory_valid:
            report["valid"] = False
            report["warnings"].append("Neither CPU nor memory data available for analysis")

        return report

    def calculate_stats(
        self,
        data_points: List[Dict[str, Any]],
        metric_name: str
    ) -> Optional[MetricStats]:
        """Calculate statistics for a set of data points.

        Args:
            data_points: List of {timestamp, value} dictionaries
            metric_name: Name of the metric

        Returns:
            MetricStats object or None if insufficient data
        """
        if not data_points:
            return None

        values = [dp["value"] for dp in data_points if dp.get("value") is not None]

        if len(values) < 10:  # Minimum data points for meaningful stats
            logger.warning(f"Insufficient data points for {metric_name}: {len(values)}")
            return None

        values_arr = np.array(values)

        # Calculate time span
        timestamps = [dp["timestamp"] for dp in data_points if "timestamp" in dp]
        if timestamps:
            data_days = (max(timestamps) - min(timestamps)).days
        else:
            data_days = 0

        return MetricStats(
            metric_name=metric_name,
            count=len(values),
            average=float(np.mean(values_arr)),
            median=float(np.median(values_arr)),
            min_value=float(np.min(values_arr)),
            max_value=float(np.max(values_arr)),
            p50=float(np.percentile(values_arr, 50)),
            p75=float(np.percentile(values_arr, 75)),
            p90=float(np.percentile(values_arr, 90)),
            p95=float(np.percentile(values_arr, 95)),
            p99=float(np.percentile(values_arr, 99)),
            std_dev=float(np.std(values_arr)),
            data_days=data_days,
        )

    def analyze_server(
        self,
        server_id: str,
        metrics_data: Dict[str, List[Dict[str, Any]]],
        hostname: Optional[str] = None
    ) -> ServerMetrics:
        """Analyze all metrics for a server.

        Args:
            server_id: Server identifier
            metrics_data: Dictionary with keys 'cpu', 'memory', 'disk_used'
                         containing lists of data points
            hostname: Optional hostname

        Returns:
            ServerMetrics object with all calculated statistics
        """
        cpu_stats = None
        memory_stats = None
        disk_stats = None

        # Calculate stats for each metric type
        if "cpu" in metrics_data:
            cpu_stats = self.calculate_stats(metrics_data["cpu"], "cpu")

        if "memory" in metrics_data:
            memory_stats = self.calculate_stats(metrics_data["memory"], "memory")

        if "disk_used" in metrics_data:
            disk_stats = self.calculate_stats(metrics_data["disk_used"], "disk")

        # Determine data range
        all_timestamps = []
        for metric_data in metrics_data.values():
            for dp in metric_data:
                if "timestamp" in dp:
                    all_timestamps.append(dp["timestamp"])

        data_start = min(all_timestamps) if all_timestamps else None
        data_end = max(all_timestamps) if all_timestamps else None

        return ServerMetrics(
            server_id=server_id,
            hostname=hostname,
            cpu=cpu_stats,
            memory=memory_stats,
            disk=disk_stats,
            data_start=data_start,
            data_end=data_end,
        )

    def analyze_batch(
        self,
        servers_data: Dict[str, Dict[str, List[Dict[str, Any]]]]
    ) -> List[ServerMetrics]:
        """Analyze metrics for multiple servers.

        Args:
            servers_data: Dictionary mapping server_id to metrics_data

        Returns:
            List of ServerMetrics objects
        """
        results = []

        for server_id, metrics_data in servers_data.items():
            try:
                server_metrics = self.analyze_server(server_id, metrics_data)
                results.append(server_metrics)
            except Exception as e:
                logger.error(f"Failed to analyze server {server_id}: {e}")

        logger.info(f"Analyzed metrics for {len(results)} servers")
        return results

    def get_utilization_summary(
        self,
        server_metrics: ServerMetrics
    ) -> Dict[str, str]:
        """Get a human-readable utilization summary.

        Args:
            server_metrics: Analyzed server metrics

        Returns:
            Dictionary with utilization descriptions
        """
        summary = {}

        def describe_usage(stats: Optional[MetricStats], thresholds: Dict[str, float]) -> str:
            if stats is None:
                return "No data"

            p95 = stats.p95
            if p95 < thresholds["low"]:
                return f"Low ({p95:.1f}% p95)"
            elif p95 < thresholds["medium"]:
                return f"Moderate ({p95:.1f}% p95)"
            elif p95 < thresholds["high"]:
                return f"High ({p95:.1f}% p95)"
            else:
                return f"Critical ({p95:.1f}% p95)"

        cpu_thresholds = {"low": 40, "medium": 60, "high": 80}
        memory_thresholds = {"low": 50, "medium": 70, "high": 85}
        disk_thresholds = {"low": 60, "medium": 75, "high": 90}

        summary["cpu"] = describe_usage(server_metrics.cpu, cpu_thresholds)
        summary["memory"] = describe_usage(server_metrics.memory, memory_thresholds)
        summary["disk"] = describe_usage(server_metrics.disk, disk_thresholds)

        return summary

    def compare_periods(
        self,
        current_data: List[Dict[str, Any]],
        previous_data: List[Dict[str, Any]],
        metric_name: str
    ) -> Dict[str, Any]:
        """Compare metrics between two periods.

        Args:
            current_data: Current period data points
            previous_data: Previous period data points
            metric_name: Name of the metric

        Returns:
            Comparison results
        """
        current_stats = self.calculate_stats(current_data, metric_name)
        previous_stats = self.calculate_stats(previous_data, metric_name)

        if current_stats is None or previous_stats is None:
            return {"error": "Insufficient data for comparison"}

        avg_change = current_stats.average - previous_stats.average
        avg_change_pct = (avg_change / previous_stats.average * 100) if previous_stats.average > 0 else 0

        p95_change = current_stats.p95 - previous_stats.p95
        p95_change_pct = (p95_change / previous_stats.p95 * 100) if previous_stats.p95 > 0 else 0

        return {
            "metric_name": metric_name,
            "current_avg": current_stats.average,
            "previous_avg": previous_stats.average,
            "avg_change": avg_change,
            "avg_change_pct": avg_change_pct,
            "current_p95": current_stats.p95,
            "previous_p95": previous_stats.p95,
            "p95_change": p95_change,
            "p95_change_pct": p95_change_pct,
            "trend": "increasing" if avg_change > 5 else "decreasing" if avg_change < -5 else "stable"
        }
