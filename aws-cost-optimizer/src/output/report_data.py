"""Prepare data for report generation."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..analysis.contention_detector import ContentionSummary
from ..analysis.metrics_analyzer import ServerMetrics
from ..analysis.rightsizing import SizingRecommendation
from ..cost.projections import SavingsProjection

logger = logging.getLogger(__name__)


@dataclass
class ServerReport:
    """Complete report data for a single server."""

    server_id: str
    hostname: Optional[str]
    instance_id: Optional[str]
    instance_type: str
    vcpu: int
    memory_gb: float
    region: str
    tags: Dict[str, str]

    # Metrics
    cpu_avg: Optional[float]
    cpu_p95: Optional[float]
    memory_avg: Optional[float]
    memory_p95: Optional[float]
    disk_avg: Optional[float]
    disk_p95: Optional[float]
    data_days: int

    # Contention
    has_contention: bool
    contention_events: int
    contention_hours: float

    # Recommendation
    classification: str
    recommended_type: Optional[str]
    confidence: float
    risk_level: str
    reason: str

    # Cost
    current_monthly: float
    recommended_monthly: float
    monthly_savings: float
    yearly_savings: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "server_id": self.server_id,
            "hostname": self.hostname,
            "instance_id": self.instance_id,
            "instance_type": self.instance_type,
            "vcpu": self.vcpu,
            "memory_gb": self.memory_gb,
            "region": self.region,
            # Flatten common tags as top-level columns
            "GSI": self.tags.get("GSI", ""),
            "Environment": self.tags.get("Environment", ""),
            "Team": self.tags.get("Team", ""),
            "cpu_avg": round(self.cpu_avg, 1) if self.cpu_avg else None,
            "cpu_p95": round(self.cpu_p95, 1) if self.cpu_p95 else None,
            "memory_avg": round(self.memory_avg, 1) if self.memory_avg else None,
            "memory_p95": round(self.memory_p95, 1) if self.memory_p95 else None,
            "disk_avg": round(self.disk_avg, 1) if self.disk_avg else None,
            "disk_p95": round(self.disk_p95, 1) if self.disk_p95 else None,
            "data_days": self.data_days,
            "has_contention": self.has_contention,
            "contention_events": self.contention_events,
            "contention_hours": round(self.contention_hours, 1),
            "classification": self.classification,
            "recommended_type": self.recommended_type,
            "confidence": round(self.confidence, 2),
            "risk_level": self.risk_level,
            "reason": self.reason,
            "current_monthly": round(self.current_monthly, 2),
            "recommended_monthly": round(self.recommended_monthly, 2),
            "monthly_savings": round(self.monthly_savings, 2),
            "yearly_savings": round(self.yearly_savings, 2),
        }
        return result


class ReportDataBuilder:
    """Build comprehensive report data from analysis results."""

    def __init__(self):
        """Initialize the builder."""
        self.servers: List[ServerReport] = []
        self.generated_at = datetime.utcnow()

    def build_server_report(
        self,
        instance: Dict[str, Any],
        metrics: Optional[ServerMetrics],
        contention: Optional[ContentionSummary],
        recommendation: Optional[SizingRecommendation],
        projection: Optional[SavingsProjection]
    ) -> ServerReport:
        """Build a complete server report.

        Args:
            instance: Instance details from AWS
            metrics: Analyzed metrics
            contention: Contention summary
            recommendation: Rightsizing recommendation
            projection: Savings projection

        Returns:
            ServerReport object
        """
        server_id = instance.get("instance_id", "")

        return ServerReport(
            server_id=server_id,
            hostname=instance.get("name"),
            instance_id=instance.get("instance_id"),
            instance_type=instance.get("instance_type", ""),
            vcpu=recommendation.current_vcpu if recommendation else 0,
            memory_gb=recommendation.current_memory_gb if recommendation else 0,
            region=instance.get("availability_zone", "")[:len(instance.get("availability_zone", "")) - 1] if instance.get("availability_zone") else "",
            tags=instance.get("tags", {}),

            # Metrics
            cpu_avg=metrics.cpu.average if metrics and metrics.cpu else None,
            cpu_p95=metrics.cpu.p95 if metrics and metrics.cpu else None,
            memory_avg=metrics.memory.average if metrics and metrics.memory else None,
            memory_p95=metrics.memory.p95 if metrics and metrics.memory else None,
            disk_avg=metrics.disk.average if metrics and metrics.disk else None,
            disk_p95=metrics.disk.p95 if metrics and metrics.disk else None,
            data_days=metrics.cpu.data_days if metrics and metrics.cpu else 0,

            # Contention
            has_contention=contention.has_contention if contention else False,
            contention_events=contention.total_events if contention else 0,
            contention_hours=contention.total_contention_hours if contention else 0,

            # Recommendation
            classification=recommendation.classification.value if recommendation else "unknown",
            recommended_type=recommendation.recommended_instance_type if recommendation else None,
            confidence=recommendation.confidence if recommendation else 0,
            risk_level=recommendation.risk_level if recommendation else "unknown",
            reason=recommendation.reason if recommendation else "",

            # Cost
            current_monthly=projection.current_monthly if projection else 0,
            recommended_monthly=projection.recommended_monthly if projection else 0,
            monthly_savings=projection.monthly_savings if projection else 0,
            yearly_savings=projection.yearly_savings if projection else 0,
        )

    def add_server(self, server_report: ServerReport) -> None:
        """Add a server report.

        Args:
            server_report: ServerReport to add
        """
        self.servers.append(server_report)

    def build_summary(self) -> Dict[str, Any]:
        """Build executive summary.

        Returns:
            Summary dictionary
        """
        total_current = sum(s.current_monthly for s in self.servers)
        total_savings = sum(s.monthly_savings for s in self.servers if s.monthly_savings > 0)

        oversized = [s for s in self.servers if s.classification == "oversized"]
        undersized = [s for s in self.servers if s.classification == "undersized"]
        right_sized = [s for s in self.servers if s.classification == "right_sized"]
        with_contention = [s for s in self.servers if s.has_contention]

        return {
            "generated_at": self.generated_at.isoformat(),
            "total_servers": len(self.servers),
            "total_current_monthly": round(total_current, 2),
            "total_monthly_savings": round(total_savings, 2),
            "total_yearly_savings": round(total_savings * 12, 2),
            "savings_percentage": round((total_savings / total_current * 100) if total_current > 0 else 0, 1),

            "oversized_count": len(oversized),
            "undersized_count": len(undersized),
            "right_sized_count": len(right_sized),
            "contention_count": len(with_contention),

            "top_10_savings": sorted(
                [s.to_dict() for s in self.servers if s.monthly_savings > 0],
                key=lambda x: x["monthly_savings"],
                reverse=True
            )[:10],
        }

    def build_by_tag(self, tag_key: str) -> Dict[str, Dict[str, Any]]:
        """Build summary grouped by tag.

        Args:
            tag_key: Tag key to group by

        Returns:
            Dictionary mapping tag values to summaries
        """
        by_tag: Dict[str, Dict[str, Any]] = {}

        for server in self.servers:
            tag_value = server.tags.get(tag_key, "(untagged)")

            if tag_value not in by_tag:
                by_tag[tag_value] = {
                    "count": 0,
                    "current_monthly": 0,
                    "monthly_savings": 0,
                    "oversized": 0,
                    "undersized": 0,
                    "right_sized": 0,
                }

            by_tag[tag_value]["count"] += 1
            by_tag[tag_value]["current_monthly"] += server.current_monthly
            if server.monthly_savings > 0:
                by_tag[tag_value]["monthly_savings"] += server.monthly_savings

            if server.classification == "oversized":
                by_tag[tag_value]["oversized"] += 1
            elif server.classification == "undersized":
                by_tag[tag_value]["undersized"] += 1
            elif server.classification == "right_sized":
                by_tag[tag_value]["right_sized"] += 1

        # Round values
        for tag_value in by_tag:
            by_tag[tag_value]["current_monthly"] = round(by_tag[tag_value]["current_monthly"], 2)
            by_tag[tag_value]["monthly_savings"] = round(by_tag[tag_value]["monthly_savings"], 2)

        return dict(sorted(by_tag.items(), key=lambda x: -x[1]["monthly_savings"]))

    def build_contention_report(self) -> Dict[str, Any]:
        """Build contention-focused report.

        Returns:
            Contention report dictionary
        """
        with_contention = [s for s in self.servers if s.has_contention]

        return {
            "total_with_contention": len(with_contention),
            "total_contention_hours": sum(s.contention_hours for s in with_contention),
            "total_contention_events": sum(s.contention_events for s in with_contention),
            "servers": sorted(
                [s.to_dict() for s in with_contention],
                key=lambda x: x["contention_events"],
                reverse=True
            ),
        }

    def get_all_data(self) -> Dict[str, Any]:
        """Get all report data.

        Returns:
            Complete report data dictionary
        """
        return {
            "summary": self.build_summary(),
            "servers": [s.to_dict() for s in self.servers],
            "by_gsi": self.build_by_tag("GSI"),
            "by_environment": self.build_by_tag("Environment"),
            "by_team": self.build_by_tag("Team"),
            "contention": self.build_contention_report(),
        }

    def export_to_dataframe(self):
        """Export server data to pandas DataFrame.

        Returns:
            pandas DataFrame
        """
        import pandas as pd
        return pd.DataFrame([s.to_dict() for s in self.servers])
