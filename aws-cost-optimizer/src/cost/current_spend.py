"""Calculate current AWS spending for instances."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..clients.aws_client import AWSClient

logger = logging.getLogger(__name__)


class CurrentSpendCalculator:
    """Calculate current AWS EC2 spending.

    Retrieves actual costs from AWS Cost Explorer and estimates
    costs using pricing data when historical data is unavailable.
    """

    # Standard hours in a month (AWS standard)
    MONTHLY_HOURS = 730

    def __init__(
        self,
        aws_client: AWSClient,
        region: str = "us-east-1"
    ):
        """Initialize the calculator.

        Args:
            aws_client: Configured AWS client
            region: Default region for pricing
        """
        self.aws_client = aws_client
        self.region = region
        self._pricing_cache: Dict[str, float] = {}

    def get_instance_cost(
        self,
        instance_id: str,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get cost for a specific instance.

        Args:
            instance_id: EC2 instance ID
            days: Number of days to look back

        Returns:
            Dictionary with cost information
        """
        return self.aws_client.get_instance_cost(
            instance_id=instance_id,
            start_date=datetime.utcnow() - timedelta(days=days),
            end_date=datetime.utcnow()
        )

    def estimate_instance_cost(
        self,
        instance_type: str,
        operating_system: str = "Linux",
        region: Optional[str] = None
    ) -> Dict[str, float]:
        """Estimate monthly cost for an instance type.

        Args:
            instance_type: EC2 instance type
            operating_system: OS type (Linux, Windows)
            region: AWS region

        Returns:
            Dictionary with estimated costs
        """
        region = region or self.region
        cache_key = f"{instance_type}:{operating_system}:{region}"

        if cache_key not in self._pricing_cache:
            hourly_rate = self.aws_client.get_instance_pricing(
                instance_type=instance_type,
                region=region,
                operating_system=operating_system
            )
            self._pricing_cache[cache_key] = hourly_rate or 0.0

        hourly_rate = self._pricing_cache[cache_key]

        return {
            "instance_type": instance_type,
            "hourly_rate": hourly_rate,
            "daily_cost": hourly_rate * 24,
            "monthly_cost": hourly_rate * self.MONTHLY_HOURS,
            "yearly_cost": hourly_rate * self.MONTHLY_HOURS * 12,
        }

    def calculate_total_spend(
        self,
        instances: List[Dict[str, Any]],
        days: int = 30
    ) -> Dict[str, Any]:
        """Calculate total spend across instances.

        Args:
            instances: List of instance dictionaries with instance_id
            days: Number of days for cost calculation

        Returns:
            Dictionary with total costs and breakdown
        """
        total_cost = 0.0
        instance_costs = []
        by_type: Dict[str, float] = {}
        by_tag: Dict[str, Dict[str, float]] = {}

        for instance in instances:
            instance_id = instance.get("instance_id")
            instance_type = instance.get("instance_type")
            tags = instance.get("tags", {})

            if not instance_id:
                continue

            # Get actual cost from Cost Explorer
            cost_data = self.get_instance_cost(instance_id, days)
            monthly_cost = cost_data.get("monthly_estimate", 0)

            # If no actual cost, estimate from pricing
            if monthly_cost == 0 and instance_type:
                estimated = self.estimate_instance_cost(instance_type)
                monthly_cost = estimated["monthly_cost"]

            instance_costs.append({
                "instance_id": instance_id,
                "instance_type": instance_type,
                "name": instance.get("name", instance_id),
                "monthly_cost": monthly_cost,
                "tags": tags,
            })

            total_cost += monthly_cost

            # Aggregate by type
            if instance_type:
                by_type[instance_type] = by_type.get(instance_type, 0) + monthly_cost

            # Aggregate by common tags
            for tag_key in ["GSI", "Environment", "Team", "Application"]:
                tag_value = tags.get(tag_key)
                if tag_value:
                    if tag_key not in by_tag:
                        by_tag[tag_key] = {}
                    by_tag[tag_key][tag_value] = by_tag[tag_key].get(tag_value, 0) + monthly_cost

        # Sort instance costs by monthly cost (descending)
        instance_costs.sort(key=lambda x: x["monthly_cost"], reverse=True)

        return {
            "total_monthly_cost": total_cost,
            "total_yearly_cost": total_cost * 12,
            "instance_count": len(instances),
            "instances": instance_costs,
            "by_instance_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
            "by_tag": by_tag,
            "top_10_costly": instance_costs[:10],
        }

    def get_costs_by_gsi(
        self,
        gsi_values: Optional[List[str]] = None,
        days: int = 30
    ) -> Dict[str, float]:
        """Get costs grouped by GSI tag.

        Args:
            gsi_values: Optional list of specific GSI values
            days: Number of days for calculation

        Returns:
            Dictionary mapping GSI values to costs
        """
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        return self.aws_client.get_costs_by_tag(
            tag_key="GSI",
            tag_values=gsi_values,
            start_date=start_date,
            end_date=end_date
        )

    def get_reserved_instance_coverage(
        self,
        instances: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze Reserved Instance coverage for instances.

        Args:
            instances: List of instance dictionaries

        Returns:
            RI coverage analysis
        """
        # Note: This requires ce:GetReservationCoverage permission
        try:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=30)

            response = self.aws_client.cost_explorer.get_reservation_coverage(
                TimePeriod={
                    "Start": start_date.strftime("%Y-%m-%d"),
                    "End": end_date.strftime("%Y-%m-%d")
                },
                Granularity="MONTHLY",
                Filter={
                    "Dimensions": {
                        "Key": "SERVICE",
                        "Values": ["Amazon Elastic Compute Cloud - Compute"]
                    }
                }
            )

            coverage = response.get("Total", {}).get("CoverageHours", {})
            return {
                "covered_hours": float(coverage.get("CoverageHoursPercentage", 0)),
                "on_demand_hours": float(coverage.get("OnDemandHours", 0)),
                "reserved_hours": float(coverage.get("ReservedHours", 0)),
                "total_hours": float(coverage.get("TotalRunningHours", 0)),
            }

        except Exception as e:
            logger.warning(f"Failed to get RI coverage: {e}")
            return {
                "covered_hours": 0,
                "on_demand_hours": 0,
                "reserved_hours": 0,
                "total_hours": 0,
                "error": str(e)
            }

    def compare_instance_costs(
        self,
        current_type: str,
        recommended_type: str,
        operating_system: str = "Linux"
    ) -> Dict[str, Any]:
        """Compare costs between two instance types.

        Args:
            current_type: Current instance type
            recommended_type: Recommended instance type
            operating_system: OS type

        Returns:
            Cost comparison
        """
        current = self.estimate_instance_cost(current_type, operating_system)
        recommended = self.estimate_instance_cost(recommended_type, operating_system)

        monthly_savings = current["monthly_cost"] - recommended["monthly_cost"]
        yearly_savings = monthly_savings * 12

        return {
            "current_type": current_type,
            "recommended_type": recommended_type,
            "current_monthly": current["monthly_cost"],
            "recommended_monthly": recommended["monthly_cost"],
            "monthly_savings": monthly_savings,
            "yearly_savings": yearly_savings,
            "savings_pct": (monthly_savings / current["monthly_cost"] * 100) if current["monthly_cost"] > 0 else 0,
        }
