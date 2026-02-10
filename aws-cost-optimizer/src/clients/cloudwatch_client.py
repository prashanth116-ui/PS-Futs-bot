"""CloudWatch client for fallback metrics when Dynatrace is unavailable."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class CloudWatchClient:
    """Client for retrieving EC2 metrics from CloudWatch.

    This is a fallback when Dynatrace metrics are unavailable.
    Note: CloudWatch has less granular data than Dynatrace.
    """

    # CloudWatch metric mappings
    METRICS = {
        "cpu": {
            "namespace": "AWS/EC2",
            "metric_name": "CPUUtilization",
            "statistic": "Average",
            "unit": "Percent"
        },
        "network_in": {
            "namespace": "AWS/EC2",
            "metric_name": "NetworkIn",
            "statistic": "Average",
            "unit": "Bytes"
        },
        "network_out": {
            "namespace": "AWS/EC2",
            "metric_name": "NetworkOut",
            "statistic": "Average",
            "unit": "Bytes"
        },
        "disk_read_ops": {
            "namespace": "AWS/EC2",
            "metric_name": "DiskReadOps",
            "statistic": "Average",
            "unit": "Count"
        },
        "disk_write_ops": {
            "namespace": "AWS/EC2",
            "metric_name": "DiskWriteOps",
            "statistic": "Average",
            "unit": "Count"
        },
        # Note: Memory metrics require CloudWatch agent
        "memory": {
            "namespace": "CWAgent",
            "metric_name": "mem_used_percent",
            "statistic": "Average",
            "unit": "Percent"
        },
        "disk_used": {
            "namespace": "CWAgent",
            "metric_name": "disk_used_percent",
            "statistic": "Average",
            "unit": "Percent"
        }
    }

    def __init__(
        self,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        region: str = "us-east-1",
        profile_name: Optional[str] = None
    ):
        """Initialize the CloudWatch client.

        Args:
            access_key_id: AWS access key ID
            secret_access_key: AWS secret access key
            region: AWS region
            profile_name: AWS CLI profile name
        """
        self.region = region

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

        session = boto3.Session(**session_kwargs)
        self.cloudwatch = session.client("cloudwatch", region_name=region, config=config)

    def get_metric_statistics(
        self,
        instance_id: str,
        metric_key: str,
        start_time: datetime,
        end_time: datetime,
        period: int = 3600  # 1 hour in seconds
    ) -> List[Dict[str, Any]]:
        """Get metric statistics for an instance.

        Args:
            instance_id: EC2 instance ID
            metric_key: Metric key (cpu, memory, disk_used, etc.)
            start_time: Start of analysis period
            end_time: End of analysis period
            period: Aggregation period in seconds

        Returns:
            List of metric data points
        """
        if metric_key not in self.METRICS:
            raise ValueError(f"Unknown metric key: {metric_key}")

        metric_config = self.METRICS[metric_key]

        try:
            response = self.cloudwatch.get_metric_statistics(
                Namespace=metric_config["namespace"],
                MetricName=metric_config["metric_name"],
                Dimensions=[
                    {"Name": "InstanceId", "Value": instance_id}
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=[metric_config["statistic"]],
                Unit=metric_config["unit"]
            )

            data_points = []
            for point in response.get("Datapoints", []):
                data_points.append({
                    "timestamp": point["Timestamp"],
                    "value": point.get(metric_config["statistic"], 0)
                })

            # Sort by timestamp
            data_points.sort(key=lambda x: x["timestamp"])
            return data_points

        except ClientError as e:
            logger.warning(f"Failed to get {metric_key} metrics for {instance_id}: {e}")
            return []

    def get_instance_metrics(
        self,
        instance_id: str,
        months: int = 3,
        period: int = 3600
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get all available metrics for an instance.

        Args:
            instance_id: EC2 instance ID
            months: Number of months of historical data
            period: Aggregation period in seconds

        Returns:
            Dictionary with metric keys mapping to data points
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=months * 30)

        metrics = {}
        for metric_key in self.METRICS.keys():
            try:
                data = self.get_metric_statistics(
                    instance_id=instance_id,
                    metric_key=metric_key,
                    start_time=start_time,
                    end_time=end_time,
                    period=period
                )
                metrics[metric_key] = data
            except Exception as e:
                logger.warning(f"Failed to get {metric_key} for {instance_id}: {e}")
                metrics[metric_key] = []

        return metrics

    def check_cloudwatch_agent(self, instance_id: str) -> bool:
        """Check if CloudWatch agent metrics are available for an instance.

        Args:
            instance_id: EC2 instance ID

        Returns:
            True if agent metrics are available
        """
        # Try to get memory metric (requires agent)
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(hours=1)

        try:
            response = self.cloudwatch.get_metric_statistics(
                Namespace="CWAgent",
                MetricName="mem_used_percent",
                Dimensions=[
                    {"Name": "InstanceId", "Value": instance_id}
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=300,
                Statistics=["Average"]
            )
            return len(response.get("Datapoints", [])) > 0

        except ClientError:
            return False

    def test_connection(self) -> bool:
        """Test the CloudWatch connection.

        Returns:
            True if connection successful
        """
        try:
            self.cloudwatch.list_metrics(Namespace="AWS/EC2", Limit=1)
            logger.info("CloudWatch connection successful")
            return True
        except ClientError as e:
            logger.error(f"CloudWatch connection failed: {e}")
            return False
