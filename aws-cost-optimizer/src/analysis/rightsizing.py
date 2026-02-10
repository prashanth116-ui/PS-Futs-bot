"""Instance rightsizing recommendation engine."""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from ..utils.helpers import load_instance_types, parse_instance_type

logger = logging.getLogger(__name__)


class SizingClassification(Enum):
    """Classification of instance sizing."""

    OVERSIZED = "oversized"
    RIGHT_SIZED = "right_sized"
    UNDERSIZED = "undersized"
    UNKNOWN = "unknown"


@dataclass
class SizingRecommendation:
    """Rightsizing recommendation for an instance."""

    server_id: str
    hostname: Optional[str]
    current_instance_type: str
    current_vcpu: int
    current_memory_gb: float
    classification: SizingClassification
    recommended_instance_type: Optional[str]
    recommended_vcpu: Optional[int]
    recommended_memory_gb: Optional[float]
    confidence: float  # 0.0 to 1.0
    risk_level: str  # low, medium, high
    reason: str
    cpu_p95: Optional[float]
    memory_p95: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "server_id": self.server_id,
            "hostname": self.hostname,
            "current_instance_type": self.current_instance_type,
            "current_vcpu": self.current_vcpu,
            "current_memory_gb": self.current_memory_gb,
            "classification": self.classification.value,
            "recommended_instance_type": self.recommended_instance_type,
            "recommended_vcpu": self.recommended_vcpu,
            "recommended_memory_gb": self.recommended_memory_gb,
            "confidence": round(self.confidence, 2),
            "risk_level": self.risk_level,
            "reason": self.reason,
            "cpu_p95": round(self.cpu_p95, 1) if self.cpu_p95 else None,
            "memory_p95": round(self.memory_p95, 1) if self.memory_p95 else None,
        }


class RightsizingEngine:
    """Engine for generating instance rightsizing recommendations.

    Classification rules:
    - OVERSIZED: CPU p95 < 40% AND Memory p95 < 50% with no contention
    - RIGHT_SIZED: CPU p95 40-70% OR Memory p95 50-75%
    - UNDERSIZED: CPU p95 > 80% OR Memory p95 > 85%
    """

    def __init__(
        self,
        thresholds: Optional[Dict[str, Dict[str, float]]] = None,
        safety_buffer: float = 20.0,
        instance_types_path: Optional[str] = None
    ):
        """Initialize the rightsizing engine.

        Args:
            thresholds: Custom classification thresholds
            safety_buffer: Safety buffer percentage for recommendations
            instance_types_path: Path to instance types catalog
        """
        self.thresholds = thresholds or {
            "cpu": {
                "oversized_max": 40,
                "rightsized_max": 70,
            },
            "memory": {
                "oversized_max": 50,
                "rightsized_max": 75,
            }
        }
        self.safety_buffer = safety_buffer

        # Load instance types catalog
        try:
            self.instance_catalog = load_instance_types(instance_types_path)
        except Exception as e:
            logger.warning(f"Failed to load instance types catalog: {e}")
            self.instance_catalog = {"families": {}, "upgrade_paths": {}, "sizing_order": []}

        # Build lookup tables
        self._build_instance_lookup()

    def _build_instance_lookup(self) -> None:
        """Build lookup tables for instance types."""
        self.instance_specs: Dict[str, Dict] = {}
        self.family_types: Dict[str, List[str]] = {}

        for family_name, family_data in self.instance_catalog.get("families", {}).items():
            types_in_family = []
            for type_info in family_data.get("types", []):
                instance_type = type_info["name"]
                self.instance_specs[instance_type] = {
                    "vcpu": type_info.get("vcpu", 0),
                    "memory_gb": type_info.get("memory_gb", 0),
                    "family": family_name,
                    "burstable": family_data.get("burstable", False),
                }
                types_in_family.append(instance_type)
            self.family_types[family_name] = types_in_family

    def classify(
        self,
        cpu_p95: Optional[float],
        memory_p95: Optional[float],
        has_contention: bool = False
    ) -> SizingClassification:
        """Classify an instance's sizing.

        Args:
            cpu_p95: 95th percentile CPU usage
            memory_p95: 95th percentile memory usage
            has_contention: Whether contention events were detected

        Returns:
            SizingClassification enum value
        """
        if cpu_p95 is None and memory_p95 is None:
            return SizingClassification.UNKNOWN

        # Undersized: high usage or contention
        cpu_high = cpu_p95 is not None and cpu_p95 > self.thresholds["cpu"]["rightsized_max"]
        mem_high = memory_p95 is not None and memory_p95 > self.thresholds["memory"]["rightsized_max"]

        if cpu_high or mem_high or has_contention:
            return SizingClassification.UNDERSIZED

        # Oversized: low usage on both with no contention
        cpu_low = cpu_p95 is not None and cpu_p95 < self.thresholds["cpu"]["oversized_max"]
        mem_low = memory_p95 is not None and memory_p95 < self.thresholds["memory"]["oversized_max"]

        if cpu_low and mem_low and not has_contention:
            return SizingClassification.OVERSIZED

        # Right-sized: moderate usage
        return SizingClassification.RIGHT_SIZED

    def find_recommended_instance(
        self,
        current_type: str,
        target_vcpu: float,
        target_memory_gb: float,
        direction: str = "down"  # "down" for oversized, "up" for undersized
    ) -> Optional[str]:
        """Find an appropriate instance type for the target specs.

        Args:
            current_type: Current instance type
            target_vcpu: Target vCPU count
            target_memory_gb: Target memory in GB
            direction: "down" for downsizing, "up" for upsizing

        Returns:
            Recommended instance type or None
        """
        try:
            parsed = parse_instance_type(current_type)
            current_family = parsed["family"]
        except ValueError:
            return None

        # Get alternative families
        upgrade_paths = self.instance_catalog.get("upgrade_paths", {})
        families_to_check = upgrade_paths.get(current_family, [current_family])

        candidates = []

        for family in families_to_check:
            if family not in self.family_types:
                continue

            for instance_type in self.family_types[family]:
                specs = self.instance_specs.get(instance_type, {})
                vcpu = specs.get("vcpu", 0)
                memory = specs.get("memory_gb", 0)

                if direction == "down":
                    # For downsizing, find smaller instances that still meet requirements
                    if vcpu >= target_vcpu and memory >= target_memory_gb:
                        # Score: prefer smallest that still works
                        score = vcpu * 100 + memory
                        candidates.append((instance_type, score))
                else:
                    # For upsizing, find larger instances
                    if vcpu >= target_vcpu and memory >= target_memory_gb:
                        score = vcpu * 100 + memory
                        candidates.append((instance_type, score))

        if not candidates:
            return None

        # Sort by score (lower is better for downsizing)
        candidates.sort(key=lambda x: x[1])

        recommended = candidates[0][0]

        # Don't recommend same instance
        if recommended == current_type:
            if len(candidates) > 1:
                return candidates[1][0]
            return None

        return recommended

    def recommend(
        self,
        server_id: str,
        current_instance_type: str,
        cpu_p95: Optional[float],
        memory_p95: Optional[float],
        has_contention: bool = False,
        hostname: Optional[str] = None,
        instance_specs: Optional[Dict] = None
    ) -> SizingRecommendation:
        """Generate a rightsizing recommendation.

        Args:
            server_id: Server identifier
            current_instance_type: Current EC2 instance type
            cpu_p95: 95th percentile CPU usage
            memory_p95: 95th percentile memory usage
            has_contention: Whether contention was detected
            hostname: Optional hostname
            instance_specs: Optional current instance specs (vcpu, memory)

        Returns:
            SizingRecommendation object
        """
        # Get current specs
        if instance_specs:
            current_vcpu = instance_specs.get("vcpu", 0)
            current_memory = instance_specs.get("memory_gb", 0)
        elif current_instance_type in self.instance_specs:
            specs = self.instance_specs[current_instance_type]
            current_vcpu = specs.get("vcpu", 0)
            current_memory = specs.get("memory_gb", 0)
        else:
            current_vcpu = 0
            current_memory = 0

        # Classify
        classification = self.classify(cpu_p95, memory_p95, has_contention)

        # Generate recommendation based on classification
        recommended_type = None
        recommended_vcpu = None
        recommended_memory = None
        confidence = 0.0
        risk_level = "medium"
        reason = ""

        if classification == SizingClassification.OVERSIZED:
            # Calculate target specs with safety buffer
            cpu_needed = (cpu_p95 or 0) + self.safety_buffer
            memory_needed = (memory_p95 or 0) + self.safety_buffer

            # Convert percentage to actual resources needed
            target_vcpu = max(1, current_vcpu * (cpu_needed / 100))
            target_memory = max(1, current_memory * (memory_needed / 100))

            recommended_type = self.find_recommended_instance(
                current_instance_type,
                target_vcpu,
                target_memory,
                direction="down"
            )

            if recommended_type and recommended_type in self.instance_specs:
                specs = self.instance_specs[recommended_type]
                recommended_vcpu = specs.get("vcpu")
                recommended_memory = specs.get("memory_gb")

            # Calculate confidence based on data quality
            if cpu_p95 is not None and memory_p95 is not None:
                confidence = 0.9 if cpu_p95 < 30 and memory_p95 < 40 else 0.7
            else:
                confidence = 0.5

            risk_level = "low" if confidence > 0.7 else "medium"
            reason = f"Low utilization (CPU p95: {cpu_p95:.1f}%, Mem p95: {memory_p95:.1f}%)"

        elif classification == SizingClassification.UNDERSIZED:
            # Calculate target with headroom
            headroom = 30  # Extra capacity percentage

            if cpu_p95 and cpu_p95 > self.thresholds["cpu"]["rightsized_max"]:
                target_vcpu = current_vcpu * (1 + (100 - self.thresholds["cpu"]["rightsized_max"] + headroom) / 100)
            else:
                target_vcpu = current_vcpu

            if memory_p95 and memory_p95 > self.thresholds["memory"]["rightsized_max"]:
                target_memory = current_memory * (1 + (100 - self.thresholds["memory"]["rightsized_max"] + headroom) / 100)
            else:
                target_memory = current_memory

            recommended_type = self.find_recommended_instance(
                current_instance_type,
                target_vcpu,
                target_memory,
                direction="up"
            )

            if recommended_type and recommended_type in self.instance_specs:
                specs = self.instance_specs[recommended_type]
                recommended_vcpu = specs.get("vcpu")
                recommended_memory = specs.get("memory_gb")

            confidence = 0.8 if has_contention else 0.6
            risk_level = "high" if has_contention else "medium"

            contention_note = " with contention events" if has_contention else ""
            reason = f"High utilization{contention_note} (CPU p95: {cpu_p95:.1f}%, Mem p95: {memory_p95:.1f}%)"

        elif classification == SizingClassification.RIGHT_SIZED:
            confidence = 0.8
            risk_level = "low"
            reason = f"Adequate utilization (CPU p95: {cpu_p95:.1f}%, Mem p95: {memory_p95:.1f}%)"

        else:
            confidence = 0.0
            risk_level = "high"
            reason = "Insufficient metrics data for analysis"

        return SizingRecommendation(
            server_id=server_id,
            hostname=hostname,
            current_instance_type=current_instance_type,
            current_vcpu=current_vcpu,
            current_memory_gb=current_memory,
            classification=classification,
            recommended_instance_type=recommended_type,
            recommended_vcpu=recommended_vcpu,
            recommended_memory_gb=recommended_memory,
            confidence=confidence,
            risk_level=risk_level,
            reason=reason,
            cpu_p95=cpu_p95,
            memory_p95=memory_p95,
        )

    def recommend_batch(
        self,
        servers: List[Dict[str, Any]]
    ) -> List[SizingRecommendation]:
        """Generate recommendations for multiple servers.

        Args:
            servers: List of server dictionaries with required fields:
                     - server_id
                     - instance_type
                     - cpu_p95
                     - memory_p95
                     - has_contention (optional)
                     - hostname (optional)

        Returns:
            List of SizingRecommendation objects
        """
        recommendations = []

        for server in servers:
            try:
                rec = self.recommend(
                    server_id=server["server_id"],
                    current_instance_type=server["instance_type"],
                    cpu_p95=server.get("cpu_p95"),
                    memory_p95=server.get("memory_p95"),
                    has_contention=server.get("has_contention", False),
                    hostname=server.get("hostname"),
                    instance_specs=server.get("instance_specs"),
                )
                recommendations.append(rec)
            except Exception as e:
                logger.error(f"Failed to recommend for {server.get('server_id')}: {e}")

        # Log summary
        by_class = {}
        for rec in recommendations:
            by_class[rec.classification.value] = by_class.get(rec.classification.value, 0) + 1

        logger.info(f"Generated {len(recommendations)} recommendations: {by_class}")
        return recommendations

    def get_summary(
        self,
        recommendations: List[SizingRecommendation]
    ) -> Dict[str, Any]:
        """Get summary of recommendations.

        Args:
            recommendations: List of recommendations

        Returns:
            Summary dictionary
        """
        oversized = [r for r in recommendations if r.classification == SizingClassification.OVERSIZED]
        undersized = [r for r in recommendations if r.classification == SizingClassification.UNDERSIZED]
        right_sized = [r for r in recommendations if r.classification == SizingClassification.RIGHT_SIZED]
        unknown = [r for r in recommendations if r.classification == SizingClassification.UNKNOWN]

        return {
            "total_analyzed": len(recommendations),
            "oversized": len(oversized),
            "undersized": len(undersized),
            "right_sized": len(right_sized),
            "unknown": len(unknown),
            "oversized_pct": len(oversized) / len(recommendations) * 100 if recommendations else 0,
            "high_confidence": len([r for r in recommendations if r.confidence >= 0.7]),
            "low_risk_changes": len([r for r in oversized + undersized if r.risk_level == "low"]),
        }
