"""Savings projections based on rightsizing recommendations."""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..analysis.rightsizing import SizingClassification, SizingRecommendation
from .current_spend import CurrentSpendCalculator

logger = logging.getLogger(__name__)


@dataclass
class SavingsProjection:
    """Projected savings for a single instance."""

    server_id: str
    hostname: Optional[str]
    current_type: str
    recommended_type: Optional[str]
    current_monthly: float
    recommended_monthly: float
    monthly_savings: float
    yearly_savings: float
    savings_pct: float
    confidence: float
    risk_level: str
    classification: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "server_id": self.server_id,
            "hostname": self.hostname,
            "current_type": self.current_type,
            "recommended_type": self.recommended_type,
            "current_monthly": round(self.current_monthly, 2),
            "recommended_monthly": round(self.recommended_monthly, 2),
            "monthly_savings": round(self.monthly_savings, 2),
            "yearly_savings": round(self.yearly_savings, 2),
            "savings_pct": round(self.savings_pct, 1),
            "confidence": round(self.confidence, 2),
            "risk_level": self.risk_level,
            "classification": self.classification,
        }


class SavingsProjector:
    """Project cost savings from rightsizing recommendations.

    Calculates expected savings based on current costs and
    recommended instance types.
    """

    def __init__(self, spend_calculator: CurrentSpendCalculator):
        """Initialize the projector.

        Args:
            spend_calculator: Current spend calculator instance
        """
        self.spend_calculator = spend_calculator

    def project_savings(
        self,
        recommendation: SizingRecommendation,
        operating_system: str = "Linux"
    ) -> SavingsProjection:
        """Project savings for a single recommendation.

        Args:
            recommendation: Rightsizing recommendation
            operating_system: OS type for pricing

        Returns:
            SavingsProjection object
        """
        # Get current cost
        current_cost = self.spend_calculator.estimate_instance_cost(
            recommendation.current_instance_type,
            operating_system
        )
        current_monthly = current_cost["monthly_cost"]

        # Get recommended cost (if applicable)
        if recommendation.recommended_instance_type:
            recommended_cost = self.spend_calculator.estimate_instance_cost(
                recommendation.recommended_instance_type,
                operating_system
            )
            recommended_monthly = recommended_cost["monthly_cost"]
        else:
            recommended_monthly = current_monthly

        # Calculate savings (positive = money saved)
        if recommendation.classification == SizingClassification.OVERSIZED:
            monthly_savings = current_monthly - recommended_monthly
        elif recommendation.classification == SizingClassification.UNDERSIZED:
            # Undersized = cost increase (negative savings)
            monthly_savings = current_monthly - recommended_monthly
        else:
            monthly_savings = 0

        yearly_savings = monthly_savings * 12

        savings_pct = (monthly_savings / current_monthly * 100) if current_monthly > 0 else 0

        return SavingsProjection(
            server_id=recommendation.server_id,
            hostname=recommendation.hostname,
            current_type=recommendation.current_instance_type,
            recommended_type=recommendation.recommended_instance_type,
            current_monthly=current_monthly,
            recommended_monthly=recommended_monthly,
            monthly_savings=monthly_savings,
            yearly_savings=yearly_savings,
            savings_pct=savings_pct,
            confidence=recommendation.confidence,
            risk_level=recommendation.risk_level,
            classification=recommendation.classification.value,
        )

    def project_batch(
        self,
        recommendations: List[SizingRecommendation],
        operating_system: str = "Linux"
    ) -> List[SavingsProjection]:
        """Project savings for multiple recommendations.

        Args:
            recommendations: List of recommendations
            operating_system: OS type for pricing

        Returns:
            List of SavingsProjection objects
        """
        projections = []

        for rec in recommendations:
            try:
                projection = self.project_savings(rec, operating_system)
                projections.append(projection)
            except Exception as e:
                logger.error(f"Failed to project savings for {rec.server_id}: {e}")

        return projections

    def get_total_savings(
        self,
        projections: List[SavingsProjection],
        min_confidence: float = 0.0,
        risk_levels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Calculate total projected savings.

        Args:
            projections: List of savings projections
            min_confidence: Minimum confidence threshold
            risk_levels: Filter by risk levels (e.g., ["low", "medium"])

        Returns:
            Summary of total savings
        """
        filtered = projections

        # Apply confidence filter
        if min_confidence > 0:
            filtered = [p for p in filtered if p.confidence >= min_confidence]

        # Apply risk level filter
        if risk_levels:
            filtered = [p for p in filtered if p.risk_level in risk_levels]

        # Calculate totals
        total_current = sum(p.current_monthly for p in filtered)
        total_recommended = sum(p.recommended_monthly for p in filtered)
        total_monthly_savings = sum(p.monthly_savings for p in filtered if p.monthly_savings > 0)
        total_yearly_savings = total_monthly_savings * 12

        # Breakdown by classification
        by_classification = {}
        for p in filtered:
            if p.classification not in by_classification:
                by_classification[p.classification] = {
                    "count": 0,
                    "monthly_savings": 0,
                }
            by_classification[p.classification]["count"] += 1
            if p.monthly_savings > 0:
                by_classification[p.classification]["monthly_savings"] += p.monthly_savings

        return {
            "total_instances": len(projections),
            "filtered_instances": len(filtered),
            "total_current_monthly": round(total_current, 2),
            "total_recommended_monthly": round(total_recommended, 2),
            "total_monthly_savings": round(total_monthly_savings, 2),
            "total_yearly_savings": round(total_yearly_savings, 2),
            "savings_pct": round((total_monthly_savings / total_current * 100) if total_current > 0 else 0, 1),
            "by_classification": by_classification,
            "avg_confidence": sum(p.confidence for p in filtered) / len(filtered) if filtered else 0,
        }

    def get_savings_by_tag(
        self,
        projections: List[SavingsProjection],
        instances: List[Dict[str, Any]],
        tag_key: str = "GSI"
    ) -> Dict[str, Dict[str, float]]:
        """Get savings grouped by a tag.

        Args:
            projections: List of savings projections
            instances: List of instance dictionaries with tags
            tag_key: Tag key to group by

        Returns:
            Dictionary mapping tag values to savings
        """
        # Build instance lookup
        instance_tags = {}
        for instance in instances:
            server_id = instance.get("instance_id")
            tags = instance.get("tags", {})
            instance_tags[server_id] = tags.get(tag_key, "(untagged)")

        # Aggregate savings
        by_tag: Dict[str, Dict[str, float]] = {}

        for projection in projections:
            tag_value = instance_tags.get(projection.server_id, "(untagged)")

            if tag_value not in by_tag:
                by_tag[tag_value] = {
                    "count": 0,
                    "current_monthly": 0,
                    "recommended_monthly": 0,
                    "monthly_savings": 0,
                }

            by_tag[tag_value]["count"] += 1
            by_tag[tag_value]["current_monthly"] += projection.current_monthly
            by_tag[tag_value]["recommended_monthly"] += projection.recommended_monthly
            if projection.monthly_savings > 0:
                by_tag[tag_value]["monthly_savings"] += projection.monthly_savings

        # Round values
        for tag_value in by_tag:
            by_tag[tag_value]["current_monthly"] = round(by_tag[tag_value]["current_monthly"], 2)
            by_tag[tag_value]["recommended_monthly"] = round(by_tag[tag_value]["recommended_monthly"], 2)
            by_tag[tag_value]["monthly_savings"] = round(by_tag[tag_value]["monthly_savings"], 2)

        return dict(sorted(by_tag.items(), key=lambda x: -x[1]["monthly_savings"]))

    def get_top_savings_opportunities(
        self,
        projections: List[SavingsProjection],
        limit: int = 10
    ) -> List[SavingsProjection]:
        """Get top savings opportunities.

        Args:
            projections: List of savings projections
            limit: Maximum number to return

        Returns:
            Top N savings opportunities by monthly savings
        """
        # Filter to only positive savings
        savings = [p for p in projections if p.monthly_savings > 0]

        # Sort by monthly savings (descending)
        savings.sort(key=lambda x: x.monthly_savings, reverse=True)

        return savings[:limit]

    def generate_timeline(
        self,
        projections: List[SavingsProjection],
        months: int = 12
    ) -> List[Dict[str, Any]]:
        """Generate a savings timeline projection.

        Args:
            projections: List of savings projections
            months: Number of months to project

        Returns:
            List of monthly projections
        """
        total_savings = sum(p.monthly_savings for p in projections if p.monthly_savings > 0)

        timeline = []
        cumulative = 0

        for month in range(1, months + 1):
            cumulative += total_savings
            timeline.append({
                "month": month,
                "monthly_savings": round(total_savings, 2),
                "cumulative_savings": round(cumulative, 2),
            })

        return timeline

    def get_implementation_phases(
        self,
        projections: List[SavingsProjection]
    ) -> Dict[str, List[SavingsProjection]]:
        """Organize recommendations into implementation phases.

        Args:
            projections: List of savings projections

        Returns:
            Dictionary with phases (quick_wins, medium_term, long_term)
        """
        phases = {
            "quick_wins": [],      # Low risk, high confidence
            "medium_term": [],     # Medium risk or confidence
            "long_term": [],       # High risk or low confidence
        }

        for projection in projections:
            if projection.monthly_savings <= 0:
                continue

            if projection.risk_level == "low" and projection.confidence >= 0.7:
                phases["quick_wins"].append(projection)
            elif projection.risk_level == "high" or projection.confidence < 0.5:
                phases["long_term"].append(projection)
            else:
                phases["medium_term"].append(projection)

        # Sort each phase by savings
        for phase in phases:
            phases[phase].sort(key=lambda x: x.monthly_savings, reverse=True)

        return phases
