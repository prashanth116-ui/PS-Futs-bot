"""Tests for API client modules."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, Mock

from src.clients.dynatrace_client import DynatraceClient
from src.clients.aws_client import AWSClient
from src.clients.cloudwatch_client import CloudWatchClient


class TestDynatraceClient:
    """Tests for DynatraceClient class."""

    @patch('src.clients.dynatrace_client.requests.Session')
    def test_initialization(self, mock_session):
        """Test client initialization."""
        client = DynatraceClient(
            environment_url="https://test.live.dynatrace.com",
            api_token="test-token"
        )

        assert client.environment_url == "https://test.live.dynatrace.com"
        assert client.api_token == "test-token"

    @patch('src.clients.dynatrace_client.requests.Session')
    def test_make_request(self, mock_session_class):
        """Test API request handling."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_response = MagicMock()
        mock_response.json.return_value = {"result": "success"}
        mock_response.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_response

        client = DynatraceClient(
            environment_url="https://test.live.dynatrace.com",
            api_token="test-token"
        )

        result = client._make_request("entities")
        assert result == {"result": "success"}

    @patch('src.clients.dynatrace_client.requests.Session')
    def test_get_hosts(self, mock_session_class):
        """Test host retrieval."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "entities": [
                {"entityId": "HOST-123", "displayName": "test-host-1"},
                {"entityId": "HOST-456", "displayName": "test-host-2"},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_response

        client = DynatraceClient(
            environment_url="https://test.live.dynatrace.com",
            api_token="test-token"
        )

        hosts = client.get_hosts()
        assert len(hosts) == 2
        assert hosts[0]["entityId"] == "HOST-123"

    @patch('src.clients.dynatrace_client.requests.Session')
    def test_test_connection_success(self, mock_session_class):
        """Test successful connection test."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_response = MagicMock()
        mock_response.json.return_value = {"entities": []}
        mock_response.raise_for_status = MagicMock()
        mock_session.request.return_value = mock_response

        client = DynatraceClient(
            environment_url="https://test.live.dynatrace.com",
            api_token="test-token"
        )

        assert client.test_connection() is True

    @patch('src.clients.dynatrace_client.requests.Session')
    def test_test_connection_failure(self, mock_session_class):
        """Test failed connection test."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.request.side_effect = Exception("Connection failed")

        client = DynatraceClient(
            environment_url="https://test.live.dynatrace.com",
            api_token="test-token"
        )

        assert client.test_connection() is False


class TestAWSClient:
    """Tests for AWSClient class."""

    @patch('src.clients.aws_client.boto3.Session')
    def test_initialization(self, mock_session):
        """Test client initialization."""
        client = AWSClient(region="us-east-1")
        assert client.region == "us-east-1"

    @patch('src.clients.aws_client.boto3.Session')
    def test_get_instances(self, mock_session_class):
        """Test instance retrieval."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_ec2 = MagicMock()
        mock_session.client.return_value = mock_ec2

        mock_paginator = MagicMock()
        mock_ec2.get_paginator.return_value = mock_paginator

        mock_paginator.paginate.return_value = [
            {
                "Reservations": [
                    {
                        "Instances": [
                            {
                                "InstanceId": "i-12345",
                                "InstanceType": "t3.micro",
                                "State": {"Name": "running"},
                                "Tags": [{"Key": "Name", "Value": "test-instance"}]
                            }
                        ]
                    }
                ]
            }
        ]

        client = AWSClient(region="us-east-1")
        client.ec2 = mock_ec2

        instances = client.get_instances()
        assert len(instances) == 1
        assert instances[0]["instance_id"] == "i-12345"
        assert instances[0]["instance_type"] == "t3.micro"

    @patch('src.clients.aws_client.boto3.Session')
    def test_parse_instance(self, mock_session):
        """Test instance parsing."""
        client = AWSClient(region="us-east-1")

        raw_instance = {
            "InstanceId": "i-12345",
            "InstanceType": "m5.large",
            "State": {"Name": "running"},
            "Placement": {"AvailabilityZone": "us-east-1a"},
            "PrivateIpAddress": "10.0.0.1",
            "Tags": [
                {"Key": "Name", "Value": "my-server"},
                {"Key": "Environment", "Value": "Production"}
            ]
        }

        parsed = client._parse_instance(raw_instance)

        assert parsed["instance_id"] == "i-12345"
        assert parsed["instance_type"] == "m5.large"
        assert parsed["state"] == "running"
        assert parsed["name"] == "my-server"
        assert parsed["tags"]["Environment"] == "Production"

    @patch('src.clients.aws_client.boto3.Session')
    def test_get_instance_type_info(self, mock_session_class):
        """Test instance type info retrieval."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_ec2 = MagicMock()
        mock_session.client.return_value = mock_ec2

        mock_ec2.describe_instance_types.return_value = {
            "InstanceTypes": [
                {
                    "InstanceType": "m5.xlarge",
                    "VCpuInfo": {"DefaultVCpus": 4},
                    "MemoryInfo": {"SizeInMiB": 16384}
                }
            ]
        }

        client = AWSClient(region="us-east-1")
        client.ec2 = mock_ec2

        info = client.get_instance_type_info("m5.xlarge")

        assert info["instance_type"] == "m5.xlarge"
        assert info["vcpu"] == 4
        assert info["memory_mb"] == 16384


class TestCloudWatchClient:
    """Tests for CloudWatchClient class."""

    @patch('src.clients.cloudwatch_client.boto3.Session')
    def test_initialization(self, mock_session):
        """Test client initialization."""
        client = CloudWatchClient(region="us-east-1")
        assert client.region == "us-east-1"

    @patch('src.clients.cloudwatch_client.boto3.Session')
    def test_get_metric_statistics(self, mock_session_class):
        """Test metric statistics retrieval."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_cw = MagicMock()
        mock_session.client.return_value = mock_cw

        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [
                {"Timestamp": datetime.utcnow(), "Average": 45.5},
                {"Timestamp": datetime.utcnow() - timedelta(hours=1), "Average": 50.2},
            ]
        }

        client = CloudWatchClient(region="us-east-1")
        client.cloudwatch = mock_cw

        now = datetime.utcnow()
        data = client.get_metric_statistics(
            instance_id="i-12345",
            metric_key="cpu",
            start_time=now - timedelta(hours=24),
            end_time=now
        )

        assert len(data) == 2

    @patch('src.clients.cloudwatch_client.boto3.Session')
    def test_check_cloudwatch_agent(self, mock_session_class):
        """Test CloudWatch agent check."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_cw = MagicMock()
        mock_session.client.return_value = mock_cw

        # Test when agent metrics are available
        mock_cw.get_metric_statistics.return_value = {
            "Datapoints": [{"Timestamp": datetime.utcnow(), "Average": 50.0}]
        }

        client = CloudWatchClient(region="us-east-1")
        client.cloudwatch = mock_cw

        assert client.check_cloudwatch_agent("i-12345") is True

        # Test when agent metrics are not available
        mock_cw.get_metric_statistics.return_value = {"Datapoints": []}
        assert client.check_cloudwatch_agent("i-12345") is False
