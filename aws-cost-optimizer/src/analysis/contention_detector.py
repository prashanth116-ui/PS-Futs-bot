"""Resource contention detection."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ContentionEvent:
    """A detected contention event."""

    server_id: str
    resource_type: str  # cpu, memory, disk
    start_time: datetime
    end_time: Optional[datetime]
    duration_minutes: int
    peak_value: float
    avg_value: float
    threshold: float
    severity: str  # warning, critical

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "server_id": self.server_id,
            "resource_type": self.resource_type,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_minutes": self.duration_minutes,
            "peak_value": round(self.peak_value, 2),
            "avg_value": round(self.avg_value, 2),
            "threshold": self.threshold,
            "severity": self.severity,
        }


@dataclass
class ContentionSummary:
    """Summary of contention for a server."""

    server_id: str
    has_contention: bool
    total_events: int
    cpu_events: int
    memory_events: int
    disk_events: int
    total_contention_hours: float
    most_severe: Optional[str]
    events: List[ContentionEvent]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "server_id": self.server_id,
            "has_contention": self.has_contention,
            "total_events": self.total_events,
            "cpu_events": self.cpu_events,
            "memory_events": self.memory_events,
            "disk_events": self.disk_events,
            "total_contention_hours": round(self.total_contention_hours, 1),
            "most_severe": self.most_severe,
            "events": [e.to_dict() for e in self.events],
        }


class ContentionDetector:
    """Detect resource contention events from metrics data.

    Contention thresholds:
    - CPU: > 80% for warning, > 95% for critical
    - Memory: > 85% for warning, > 95% for critical
    - Disk: > 90% for warning, > 95% for critical
    """

    DEFAULT_THRESHOLDS = {
        "cpu": {"warning": 80, "critical": 95},
        "memory": {"warning": 85, "critical": 95},
        "disk": {"warning": 90, "critical": 95},
    }

    # Minimum duration (minutes) to consider as contention
    MIN_DURATION_MINUTES = 5

    def __init__(
        self,
        thresholds: Optional[Dict[str, Dict[str, float]]] = None,
        min_duration: int = 5
    ):
        """Initialize the detector.

        Args:
            thresholds: Custom thresholds for each resource type
            min_duration: Minimum duration in minutes to classify as contention
        """
        self.thresholds = thresholds or self.DEFAULT_THRESHOLDS
        self.min_duration = min_duration

    def detect_contention(
        self,
        data_points: List[Dict[str, Any]],
        resource_type: str,
        server_id: str
    ) -> List[ContentionEvent]:
        """Detect contention events in metric data.

        Args:
            data_points: List of {timestamp, value} dictionaries
            resource_type: Type of resource (cpu, memory, disk)
            server_id: Server identifier

        Returns:
            List of ContentionEvent objects
        """
        if not data_points or resource_type not in self.thresholds:
            return []

        # Sort by timestamp
        sorted_points = sorted(data_points, key=lambda x: x.get("timestamp", datetime.min))

        thresholds = self.thresholds[resource_type]
        warning_threshold = thresholds["warning"]
        critical_threshold = thresholds["critical"]

        events = []
        current_event: Optional[Dict] = None

        for point in sorted_points:
            value = point.get("value")
            timestamp = point.get("timestamp")

            if value is None or timestamp is None:
                continue

            is_warning = value >= warning_threshold
            is_critical = value >= critical_threshold

            if is_warning:
                if current_event is None:
                    # Start new event
                    current_event = {
                        "start_time": timestamp,
                        "values": [value],
                        "is_critical": is_critical,
                    }
                else:
                    # Continue event
                    current_event["values"].append(value)
                    if is_critical:
                        current_event["is_critical"] = True
            else:
                if current_event is not None:
                    # End current event
                    event = self._finalize_event(
                        current_event,
                        end_time=timestamp,
                        resource_type=resource_type,
                        server_id=server_id,
                        threshold=warning_threshold
                    )
                    if event:
                        events.append(event)
                    current_event = None

        # Handle event at end of data
        if current_event is not None:
            event = self._finalize_event(
                current_event,
                end_time=sorted_points[-1].get("timestamp"),
                resource_type=resource_type,
                server_id=server_id,
                threshold=warning_threshold
            )
            if event:
                events.append(event)

        return events

    def _finalize_event(
        self,
        event_data: Dict,
        end_time: datetime,
        resource_type: str,
        server_id: str,
        threshold: float
    ) -> Optional[ContentionEvent]:
        """Create a ContentionEvent from accumulated data.

        Args:
            event_data: Dictionary with start_time, values, is_critical
            end_time: End timestamp
            resource_type: Resource type
            server_id: Server identifier
            threshold: Warning threshold

        Returns:
            ContentionEvent or None if too short
        """
        start_time = event_data["start_time"]
        values = event_data["values"]
        is_critical = event_data["is_critical"]

        duration = (end_time - start_time).total_seconds() / 60

        # Skip if too short
        if duration < self.min_duration:
            return None

        return ContentionEvent(
            server_id=server_id,
            resource_type=resource_type,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=int(duration),
            peak_value=max(values),
            avg_value=sum(values) / len(values),
            threshold=threshold,
            severity="critical" if is_critical else "warning",
        )

    def analyze_server(
        self,
        server_id: str,
        metrics_data: Dict[str, List[Dict[str, Any]]]
    ) -> ContentionSummary:
        """Analyze contention for a server.

        Args:
            server_id: Server identifier
            metrics_data: Dictionary with metric data by type

        Returns:
            ContentionSummary object
        """
        all_events: List[ContentionEvent] = []

        # Map Dynatrace metric names to our resource types
        metric_mapping = {
            "cpu": "cpu",
            "memory": "memory",
            "disk_used": "disk",
        }

        for metric_key, resource_type in metric_mapping.items():
            if metric_key in metrics_data:
                events = self.detect_contention(
                    data_points=metrics_data[metric_key],
                    resource_type=resource_type,
                    server_id=server_id
                )
                all_events.extend(events)

        # Calculate summary
        cpu_events = [e for e in all_events if e.resource_type == "cpu"]
        memory_events = [e for e in all_events if e.resource_type == "memory"]
        disk_events = [e for e in all_events if e.resource_type == "disk"]

        total_minutes = sum(e.duration_minutes for e in all_events)

        # Determine most severe
        critical_events = [e for e in all_events if e.severity == "critical"]
        if critical_events:
            most_severe = "critical"
        elif all_events:
            most_severe = "warning"
        else:
            most_severe = None

        return ContentionSummary(
            server_id=server_id,
            has_contention=len(all_events) > 0,
            total_events=len(all_events),
            cpu_events=len(cpu_events),
            memory_events=len(memory_events),
            disk_events=len(disk_events),
            total_contention_hours=total_minutes / 60,
            most_severe=most_severe,
            events=all_events,
        )

    def analyze_batch(
        self,
        servers_data: Dict[str, Dict[str, List[Dict[str, Any]]]]
    ) -> List[ContentionSummary]:
        """Analyze contention for multiple servers.

        Args:
            servers_data: Dictionary mapping server_id to metrics_data

        Returns:
            List of ContentionSummary objects
        """
        results = []

        for server_id, metrics_data in servers_data.items():
            try:
                summary = self.analyze_server(server_id, metrics_data)
                results.append(summary)
            except Exception as e:
                logger.error(f"Failed to analyze contention for {server_id}: {e}")

        # Sort by total events (descending)
        results.sort(key=lambda x: x.total_events, reverse=True)

        logger.info(f"Analyzed contention for {len(results)} servers, "
                   f"{sum(1 for r in results if r.has_contention)} with events")
        return results

    def get_contention_report(
        self,
        summaries: List[ContentionSummary]
    ) -> Dict[str, Any]:
        """Generate a high-level contention report.

        Args:
            summaries: List of ContentionSummary objects

        Returns:
            Report dictionary
        """
        servers_with_contention = [s for s in summaries if s.has_contention]
        critical_servers = [s for s in summaries if s.most_severe == "critical"]

        total_events = sum(s.total_events for s in summaries)
        total_hours = sum(s.total_contention_hours for s in summaries)

        return {
            "total_servers": len(summaries),
            "servers_with_contention": len(servers_with_contention),
            "critical_servers": len(critical_servers),
            "total_events": total_events,
            "total_contention_hours": round(total_hours, 1),
            "cpu_events": sum(s.cpu_events for s in summaries),
            "memory_events": sum(s.memory_events for s in summaries),
            "disk_events": sum(s.disk_events for s in summaries),
            "top_offenders": [
                {
                    "server_id": s.server_id,
                    "events": s.total_events,
                    "hours": s.total_contention_hours
                }
                for s in servers_with_contention[:10]
            ]
        }
