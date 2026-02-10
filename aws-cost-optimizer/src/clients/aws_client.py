"""AWS client for EC2 instance details and Cost Explorer data."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class AWSClient:
    """Client for interacting with AWS EC2 and Cost Explorer APIs.

    Provides methods to retrieve instance details, costs, and pricing information.
    """

    def __init__(
        self,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        region: str = "us-east-1",
        profile_name: Optional[str] = None
    ):
        """Initialize the AWS client.

        Args:
            access_key_id: AWS access key ID (optional if using profile or IAM role)
            secret_access_key: AWS secret access key
            region: AWS region
            profile_name: AWS CLI profile name to use
        """
        self.region = region

        # Configure boto3 session
        config = Config(
            retries={"max_attempts": 3, "mode": "adaptive"},
            connect_timeout=10,
            read_timeout=30
        )

        session_kwargs = {}
        if profile_name:
            session_kwargs["profile_name"] = profile_name
        elif access_key_id and secret_access_key:
            session_kwargs["aws_access_key_id"] = access_key_id
            session_kwargs["aws_secret_access_key"] = secret_access_key

        self.session = boto3.Session(**session_kwargs)

        # Initialize clients
        self.ec2 = self.session.client("ec2", region_name=region, config=config)
        self.cost_explorer = self.session.client("ce", region_name="us-east-1", config=config)
        self.pricing = self.session.client("pricing", region_name="us-east-1", config=config)

        # Cache for instance type info
        self._instance_type_cache: Dict[str, Dict] = {}

    def get_instances(
        self,
        instance_ids: Optional[List[str]] = None,
        tags: Optional[Dict[str, str]] = None,
        filters: Optional[List[Dict]] = None
    ) -> List[Dict[str, Any]]:
        """Get EC2 instance details.

        Args:
            instance_ids: Optional list of specific instance IDs
            tags: Optional tag filters (e.g., {"GSI": "MyProject"})
            filters: Optional raw EC2 filters

        Returns:
            List of instance details
        """
        ec2_filters = filters or []

        # Add tag filters
        if tags:
            for key, value in tags.items():
                ec2_filters.append({
                    "Name": f"tag:{key}",
                    "Values": [value] if isinstance(value, str) else value
                })

        # Only get running instances by default
        ec2_filters.append({
            "Name": "instance-state-name",
            "Values": ["running"]
        })

        kwargs = {"Filters": ec2_filters}
        if instance_ids:
            kwargs["InstanceIds"] = instance_ids

        instances = []
        paginator = self.ec2.get_paginator("describe_instances")

        try:
            for page in paginator.paginate(**kwargs):
                for reservation in page.get("Reservations", []):
                    for instance in reservation.get("Instances", []):
                        instances.append(self._parse_instance(instance))

            logger.info(f"Retrieved {len(instances)} EC2 instances")
            return instances

        except ClientError as e:
            logger.error(f"Failed to describe instances: {e}")
            raise

    def _parse_instance(self, instance: Dict) -> Dict[str, Any]:
        """Parse EC2 instance response into simplified format.

        Args:
            instance: Raw EC2 instance data

        Returns:
            Parsed instance dictionary
        """
        # Extract tags into a dictionary
        tags = {}
        for tag in instance.get("Tags", []):
            tags[tag["Key"]] = tag["Value"]

        return {
            "instance_id": instance["InstanceId"],
            "instance_type": instance["InstanceType"],
            "state": instance["State"]["Name"],
            "availability_zone": instance.get("Placement", {}).get("AvailabilityZone"),
            "private_ip": instance.get("PrivateIpAddress"),
            "public_ip": instance.get("PublicIpAddress"),
            "launch_time": instance.get("LaunchTime"),
            "tags": tags,
            "name": tags.get("Name", instance["InstanceId"]),
            "platform": instance.get("Platform", "linux"),
            "architecture": instance.get("Architecture"),
            "vpc_id": instance.get("VpcId"),
            "subnet_id": instance.get("SubnetId"),
        }

    def get_instance_type_info(self, instance_type: str) -> Dict[str, Any]:
        """Get details about an instance type.

        Args:
            instance_type: EC2 instance type (e.g., "m5.xlarge")

        Returns:
            Instance type specifications
        """
        if instance_type in self._instance_type_cache:
            return self._instance_type_cache[instance_type]

        try:
            response = self.ec2.describe_instance_types(
                InstanceTypes=[instance_type]
            )

            if response.get("InstanceTypes"):
                info = response["InstanceTypes"][0]
                parsed = {
                    "instance_type": instance_type,
                    "vcpu": info.get("VCpuInfo", {}).get("DefaultVCpus", 0),
                    "memory_mb": info.get("MemoryInfo", {}).get("SizeInMiB", 0),
                    "memory_gb": info.get("MemoryInfo", {}).get("SizeInMiB", 0) / 1024,
                    "architecture": info.get("ProcessorInfo", {}).get("SupportedArchitectures", []),
                    "network_performance": info.get("NetworkInfo", {}).get("NetworkPerformance"),
                    "storage": info.get("InstanceStorageInfo"),
                }
                self._instance_type_cache[instance_type] = parsed
                return parsed

        except ClientError as e:
            logger.warning(f"Failed to get instance type info for {instance_type}: {e}")

        return {
            "instance_type": instance_type,
            "vcpu": 0,
            "memory_mb": 0,
            "memory_gb": 0,
        }

    def get_instance_cost(
        self,
        instance_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, float]:
        """Get cost data for a specific instance.

        Args:
            instance_id: EC2 instance ID
            start_date: Start of cost period (default: 30 days ago)
            end_date: End of cost period (default: today)

        Returns:
            Dictionary with cost information
        """
        if end_date is None:
            end_date = datetime.utcnow()
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        try:
            response = self.cost_explorer.get_cost_and_usage(
                TimePeriod={
                    "Start": start_date.strftime("%Y-%m-%d"),
                    "End": end_date.strftime("%Y-%m-%d")
                },
                Granularity="MONTHLY",
                Metrics=["UnblendedCost", "UsageQuantity"],
                Filter={
                    "Dimensions": {
                        "Key": "RESOURCE_ID",
                        "Values": [instance_id]
                    }
                },
                GroupBy=[
                    {"Type": "DIMENSION", "Key": "USAGE_TYPE"}
                ]
            )

            total_cost = 0.0
            for result in response.get("ResultsByTime", []):
                for group in result.get("Groups", []):
                    cost = float(group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", 0))
                    total_cost += cost

            return {
                "instance_id": instance_id,
                "total_cost": total_cost,
                "period_days": (end_date - start_date).days,
                "monthly_estimate": total_cost * 30 / max((end_date - start_date).days, 1)
            }

        except ClientError as e:
            logger.warning(f"Failed to get cost for {instance_id}: {e}")
            return {
                "instance_id": instance_id,
                "total_cost": 0.0,
                "period_days": 0,
                "monthly_estimate": 0.0
            }

    def get_costs_by_tag(
        self,
        tag_key: str,
        tag_values: Optional[List[str]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, float]:
        """Get costs grouped by tag value.

        Args:
            tag_key: Tag key to group by (e.g., "GSI")
            tag_values: Optional list of specific tag values to filter
            start_date: Start of cost period
            end_date: End of cost period

        Returns:
            Dictionary mapping tag values to costs
        """
        if end_date is None:
            end_date = datetime.utcnow()
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        filter_config = {
            "Dimensions": {
                "Key": "SERVICE",
                "Values": ["Amazon Elastic Compute Cloud - Compute"]
            }
        }

        if tag_values:
            filter_config = {
                "And": [
                    filter_config,
                    {"Tags": {"Key": tag_key, "Values": tag_values}}
                ]
            }

        try:
            response = self.cost_explorer.get_cost_and_usage(
                TimePeriod={
                    "Start": start_date.strftime("%Y-%m-%d"),
                    "End": end_date.strftime("%Y-%m-%d")
                },
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                Filter=filter_config,
                GroupBy=[
                    {"Type": "TAG", "Key": tag_key}
                ]
            )

            costs = {}
            for result in response.get("ResultsByTime", []):
                for group in result.get("Groups", []):
                    tag_value = group.get("Keys", [""])[0].replace(f"{tag_key}$", "")
                    cost = float(group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", 0))
                    costs[tag_value] = costs.get(tag_value, 0) + cost

            return costs

        except ClientError as e:
            logger.error(f"Failed to get costs by tag: {e}")
            raise

    def get_instance_pricing(
        self,
        instance_type: str,
        region: Optional[str] = None,
        operating_system: str = "Linux"
    ) -> Optional[float]:
        """Get on-demand hourly price for an instance type.

        Args:
            instance_type: EC2 instance type
            region: AWS region (default: client region)
            operating_system: OS type (Linux, Windows)

        Returns:
            Hourly price in USD or None if not found
        """
        if region is None:
            region = self.region

        # Map region code to AWS region name
        region_map = {
            "us-east-1": "US East (N. Virginia)",
            "us-east-2": "US East (Ohio)",
            "us-west-1": "US West (N. California)",
            "us-west-2": "US West (Oregon)",
            "eu-west-1": "EU (Ireland)",
            "eu-central-1": "EU (Frankfurt)",
            "ap-southeast-1": "Asia Pacific (Singapore)",
            "ap-southeast-2": "Asia Pacific (Sydney)",
            "ap-northeast-1": "Asia Pacific (Tokyo)",
        }

        region_name = region_map.get(region, region)

        try:
            response = self.pricing.get_products(
                ServiceCode="AmazonEC2",
                Filters=[
                    {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
                    {"Type": "TERM_MATCH", "Field": "location", "Value": region_name},
                    {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": operating_system},
                    {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
                    {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
                    {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
                ],
                MaxResults=1
            )

            if response.get("PriceList"):
                import json
                price_data = json.loads(response["PriceList"][0])

                # Navigate the pricing structure
                on_demand = price_data.get("terms", {}).get("OnDemand", {})
                for term in on_demand.values():
                    for price_dimension in term.get("priceDimensions", {}).values():
                        price_per_unit = price_dimension.get("pricePerUnit", {})
                        if "USD" in price_per_unit:
                            return float(price_per_unit["USD"])

        except ClientError as e:
            logger.warning(f"Failed to get pricing for {instance_type}: {e}")

        return None

    def get_all_regions(self) -> List[str]:
        """Get list of all available AWS regions.

        Returns:
            List of region codes
        """
        try:
            response = self.ec2.describe_regions()
            return [r["RegionName"] for r in response.get("Regions", [])]
        except ClientError as e:
            logger.error(f"Failed to get regions: {e}")
            return [self.region]

    def test_connection(self) -> bool:
        """Test the AWS connection.

        Returns:
            True if connection successful
        """
        try:
            self.ec2.describe_regions(DryRun=False)
            logger.info("AWS connection successful")
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "DryRunOperation":
                logger.info("AWS connection successful (DryRun)")
                return True
            logger.error(f"AWS connection failed: {e}")
            return False
