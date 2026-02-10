"""Dynatrace API client for retrieving host metrics."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class DynatraceClient:
    """Client for interacting with the Dynatrace API.

    This client handles authentication and provides methods to retrieve
    host metrics including CPU, memory, and disk usage.
    """

    # Dynatrace metric IDs
    METRICS = {
        "cpu": "builtin:host.cpu.usage",
        "memory": "builtin:host.mem.usage",
        "disk_used": "builtin:host.disk.used.pct",
        "disk_iops": "builtin:host.disk.iops",
    }

    def __init__(
        self,
        environment_url: str,
        api_token: str,
        timeout: int = 30,
        max_retries: int = 3
    ):
        """Initialize the Dynatrace client.

        Args:
            environment_url: Dynatrace environment URL
                             (e.g., https://xyz.live.dynatrace.com)
            api_token: Dynatrace API token with metrics.read scope
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
        """
        self.environment_url = environment_url.rstrip("/")
        self.api_token = api_token
        self.timeout = timeout

        # Set up session with retry logic
        self.session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # Set default headers
        self.session.headers.update({
            "Authorization": f"Api-Token {self.api_token}",
            "Content-Type": "application/json",
        })

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[Dict] = None,
        data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make an API request to Dynatrace.

        Args:
            endpoint: API endpoint path
            method: HTTP method
            params: Query parameters
            data: Request body data

        Returns:
            JSON response data

        Raises:
            requests.exceptions.RequestException: On API errors
        """
        url = f"{self.environment_url}/api/v2/{endpoint}"

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=data,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            logger.error(f"Dynatrace API error: {e.response.status_code} - {e.response.text}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Dynatrace request failed: {e}")
            raise

    def get_hosts(self, entity_selector: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get list of monitored hosts.

        Args:
            entity_selector: Optional entity selector to filter hosts
                             (e.g., "type(HOST),tag(environment:production)")

        Returns:
            List of host entities
        """
        params = {
            "entitySelector": entity_selector or "type(HOST)",
            "fields": "+properties,+tags",
            "pageSize": 500
        }

        all_hosts = []
        next_page_key = None

        while True:
            if next_page_key:
                params["nextPageKey"] = next_page_key

            response = self._make_request("entities", params=params)
            all_hosts.extend(response.get("entities", []))

            next_page_key = response.get("nextPageKey")
            if not next_page_key:
                break

        logger.info(f"Retrieved {len(all_hosts)} hosts from Dynatrace")
        return all_hosts

    def get_host_by_name(self, hostname: str) -> Optional[Dict[str, Any]]:
        """Get a specific host by hostname.

        Args:
            hostname: Hostname to search for

        Returns:
            Host entity or None if not found
        """
        selector = f'type(HOST),entityName.equals("{hostname}")'
        hosts = self.get_hosts(entity_selector=selector)
        return hosts[0] if hosts else None

    def get_metrics(
        self,
        host_ids: List[str],
        metric_key: str,
        start_time: datetime,
        end_time: datetime,
        resolution: str = "1h"
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get metrics for specified hosts.

        Args:
            host_ids: List of Dynatrace host entity IDs
            metric_key: Metric key (cpu, memory, disk_used, disk_iops)
            start_time: Start of analysis period
            end_time: End of analysis period
            resolution: Metric resolution (e.g., "1h", "1d")

        Returns:
            Dictionary mapping host_id to list of metric data points
        """
        if metric_key not in self.METRICS:
            raise ValueError(f"Unknown metric key: {metric_key}. "
                           f"Valid keys: {list(self.METRICS.keys())}")

        metric_selector = self.METRICS[metric_key]

        # Build entity selector for specified hosts
        entity_selector = ",".join([f'entityId("{host_id}")' for host_id in host_ids])

        params = {
            "metricSelector": metric_selector,
            "entitySelector": f"type(HOST),({entity_selector})",
            "from": start_time.isoformat() + "Z",
            "to": end_time.isoformat() + "Z",
            "resolution": resolution,
        }

        response = self._make_request("metrics/query", params=params)

        # Parse response into per-host data
        results = {host_id: [] for host_id in host_ids}

        for metric_result in response.get("result", []):
            for data_point in metric_result.get("data", []):
                entity_id = data_point.get("dimensions", [None])[0]
                if entity_id in results:
                    timestamps = data_point.get("timestamps", [])
                    values = data_point.get("values", [])

                    for ts, val in zip(timestamps, values):
                        if val is not None:
                            results[entity_id].append({
                                "timestamp": datetime.fromtimestamp(ts / 1000),
                                "value": val
                            })

        return results

    def get_host_metrics(
        self,
        host_id: str,
        months: int = 3,
        resolution: str = "1h"
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Get all metrics for a single host.

        Args:
            host_id: Dynatrace host entity ID
            months: Number of months of historical data
            resolution: Metric resolution

        Returns:
            Dictionary with keys 'cpu', 'memory', 'disk_used', 'disk_iops'
            each containing list of {timestamp, value} dicts
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=months * 30)

        metrics = {}
        for metric_key in self.METRICS.keys():
            try:
                result = self.get_metrics(
                    host_ids=[host_id],
                    metric_key=metric_key,
                    start_time=start_time,
                    end_time=end_time,
                    resolution=resolution
                )
                metrics[metric_key] = result.get(host_id, [])
            except Exception as e:
                logger.warning(f"Failed to get {metric_key} for {host_id}: {e}")
                metrics[metric_key] = []

        return metrics

    def get_problems(
        self,
        host_id: str,
        start_time: datetime,
        end_time: datetime,
        problem_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get problems/events for a host.

        Args:
            host_id: Dynatrace host entity ID
            start_time: Start of analysis period
            end_time: End of analysis period
            problem_filter: Optional problem filter string

        Returns:
            List of problem records
        """
        params = {
            "from": start_time.isoformat() + "Z",
            "to": end_time.isoformat() + "Z",
            "entitySelector": f'entityId("{host_id}")',
            "pageSize": 500
        }

        if problem_filter:
            params["problemSelector"] = problem_filter

        response = self._make_request("problems", params=params)
        return response.get("problems", [])

    def get_contention_events(
        self,
        host_id: str,
        months: int = 3
    ) -> List[Dict[str, Any]]:
        """Get resource contention events for a host.

        Args:
            host_id: Dynatrace host entity ID
            months: Number of months to look back

        Returns:
            List of contention events
        """
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=months * 30)

        # Filter for resource-related problems
        problem_filter = (
            'severityLevel("RESOURCE_CONTENTION","AVAILABILITY")'
        )

        return self.get_problems(
            host_id=host_id,
            start_time=start_time,
            end_time=end_time,
            problem_filter=problem_filter
        )

    def test_connection(self) -> bool:
        """Test the API connection.

        Returns:
            True if connection successful
        """
        try:
            self._make_request("entities", params={"pageSize": 1})
            logger.info("Dynatrace connection successful")
            return True
        except Exception as e:
            logger.error(f"Dynatrace connection failed: {e}")
            return False
