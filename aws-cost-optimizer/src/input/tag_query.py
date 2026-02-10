"""AWS tag-based server discovery."""

import logging
from typing import Any, Dict, List, Optional

from ..clients.aws_client import AWSClient

logger = logging.getLogger(__name__)


class TagQuery:
    """Query AWS instances by tags.

    Provides flexible tag-based filtering for instance discovery.
    """

    def __init__(
        self,
        aws_client: AWSClient,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        profile_name: Optional[str] = None
    ):
        """Initialize the tag query.

        Args:
            aws_client: Configured AWS client
            access_key_id: AWS access key ID for regional queries
            secret_access_key: AWS secret access key for regional queries
            profile_name: AWS CLI profile name for regional queries
        """
        self.aws_client = aws_client
        # Store credentials for creating regional clients
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._profile_name = profile_name

    def _create_regional_client(self, region: str) -> AWSClient:
        """Create an AWS client for a specific region.

        Args:
            region: AWS region

        Returns:
            AWSClient configured for the region
        """
        return AWSClient(
            access_key_id=self._access_key_id,
            secret_access_key=self._secret_access_key,
            region=region,
            profile_name=self._profile_name
        )

    def query(
        self,
        tags: Dict[str, str],
        include_stopped: bool = False,
        regions: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Query instances by tags.

        Args:
            tags: Tag key-value pairs to filter by
            include_stopped: Include stopped instances
            regions: List of regions to query (default: client region)

        Returns:
            List of matching instances
        """
        all_instances = []
        regions = regions or [self.aws_client.region]

        for region in regions:
            # Create region-specific client with proper credentials
            region_client = self._create_regional_client(region)

            # Build filters
            filters = []
            for key, value in tags.items():
                filters.append({
                    "Name": f"tag:{key}",
                    "Values": [value] if isinstance(value, str) else value
                })

            if not include_stopped:
                filters.append({
                    "Name": "instance-state-name",
                    "Values": ["running"]
                })

            try:
                instances = region_client.get_instances(filters=filters)
                for instance in instances:
                    instance["region"] = region
                all_instances.extend(instances)
            except Exception as e:
                logger.warning(f"Failed to query region {region}: {e}")

        logger.info(f"Found {len(all_instances)} instances matching tags: {tags}")
        return all_instances

    def query_by_gsi(
        self,
        gsi_values: List[str],
        tag_key: str = "GSI"
    ) -> List[Dict[str, Any]]:
        """Query instances by GSI (or similar cost center tag).

        Args:
            gsi_values: List of GSI values to query
            tag_key: Tag key for GSI (default: "GSI")

        Returns:
            List of matching instances
        """
        return self.query(tags={tag_key: gsi_values})

    def query_by_environment(
        self,
        environments: List[str],
        tag_key: str = "Environment"
    ) -> List[Dict[str, Any]]:
        """Query instances by environment.

        Args:
            environments: List of environment values (e.g., ["Production", "Staging"])
            tag_key: Tag key for environment

        Returns:
            List of matching instances
        """
        return self.query(tags={tag_key: environments})

    def query_by_multiple_tags(
        self,
        tag_filters: List[Dict[str, str]],
        match_all: bool = True
    ) -> List[Dict[str, Any]]:
        """Query instances by multiple tag combinations.

        Args:
            tag_filters: List of tag dictionaries
            match_all: If True, instance must match all filters.
                       If False, match any filter.

        Returns:
            List of matching instances
        """
        if match_all:
            # Combine all tags into single query
            combined_tags = {}
            for tags in tag_filters:
                combined_tags.update(tags)
            return self.query(tags=combined_tags)
        else:
            # Query each filter separately and deduplicate
            seen_ids = set()
            all_instances = []

            for tags in tag_filters:
                instances = self.query(tags=tags)
                for instance in instances:
                    if instance["instance_id"] not in seen_ids:
                        seen_ids.add(instance["instance_id"])
                        all_instances.append(instance)

            return all_instances

    def get_available_tag_values(
        self,
        tag_key: str,
        sample_size: int = 1000
    ) -> List[str]:
        """Get distinct values for a tag key.

        Args:
            tag_key: Tag key to query
            sample_size: Maximum number of instances to sample

        Returns:
            List of distinct tag values
        """
        try:
            # Get all instances and collect unique tag values
            instances = self.aws_client.get_instances()

            values = set()
            for instance in instances[:sample_size]:
                value = instance.get("tags", {}).get(tag_key)
                if value:
                    values.add(value)

            return sorted(list(values))

        except Exception as e:
            logger.error(f"Failed to get tag values for {tag_key}: {e}")
            return []

    def get_instance_counts_by_tag(
        self,
        tag_key: str
    ) -> Dict[str, int]:
        """Get instance counts grouped by tag value.

        Args:
            tag_key: Tag key to group by

        Returns:
            Dictionary mapping tag values to instance counts
        """
        try:
            instances = self.aws_client.get_instances()

            counts: Dict[str, int] = {}
            for instance in instances:
                value = instance.get("tags", {}).get(tag_key, "(untagged)")
                counts[value] = counts.get(value, 0) + 1

            return dict(sorted(counts.items(), key=lambda x: -x[1]))

        except Exception as e:
            logger.error(f"Failed to get counts for {tag_key}: {e}")
            return {}


def query_servers_by_tag(
    aws_client: AWSClient,
    tag_key: str,
    tag_value: str
) -> List[Dict[str, Any]]:
    """Convenience function to query servers by a single tag.

    Args:
        aws_client: Configured AWS client
        tag_key: Tag key to filter by
        tag_value: Tag value to filter by

    Returns:
        List of matching instances
    """
    query = TagQuery(aws_client)
    return query.query(tags={tag_key: tag_value})
