"""Tests for analysis modules."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from src.analysis.metrics_analyzer import MetricsAnalyzer, MetricStats, ServerMetrics
from src.analysis.contention_detector import ContentionDetector, ContentionEvent, ContentionSummary
from src.analysis.rightsizing import RightsizingEngine, SizingClassification, SizingRecommendation


class TestMetricsAnalyzer:
    """Tests for MetricsAnalyzer class."""

    def test_calculate_stats_with_valid_data(self):
        """Test statistics calculation with valid data."""
        analyzer = MetricsAnalyzer()

        now = datetime.utcnow()
        data_points = [
            {"timestamp": now - timedelta(hours=i), "value": 50 + i}
            for i in range(100)
        ]

        stats = analyzer.calculate_stats(data_points, "test_metric")

        assert stats is not None
        assert stats.metric_name == "test_metric"
        assert stats.count == 100
        assert stats.average == pytest.approx(99.5, rel=0.01)
        assert stats.min_value == 50
        assert stats.max_value == 149

    def test_calculate_stats_insufficient_data(self):
        """Test that insufficient data returns None."""
        analyzer = MetricsAnalyzer()

        data_points = [{"timestamp": datetime.utcnow(), "value": 50}]
        stats = analyzer.calculate_stats(data_points, "test_metric")

        assert stats is None

    def test_calculate_stats_empty_data(self):
        """Test that empty data returns None."""
        analyzer = MetricsAnalyzer()

        stats = analyzer.calculate_stats([], "test_metric")
        assert stats is None

    def test_analyze_server(self):
        """Test full server analysis."""
        analyzer = MetricsAnalyzer()

        now = datetime.utcnow()
        metrics_data = {
            "cpu": [{"timestamp": now - timedelta(hours=i), "value": 30 + i % 20} for i in range(50)],
            "memory": [{"timestamp": now - timedelta(hours=i), "value": 50 + i % 10} for i in range(50)],
            "disk_used": [{"timestamp": now - timedelta(hours=i), "value": 60 + i % 5} for i in range(50)],
        }

        result = analyzer.analyze_server("server-1", metrics_data, hostname="test-server")

        assert isinstance(result, ServerMetrics)
        assert result.server_id == "server-1"
        assert result.hostname == "test-server"
        assert result.cpu is not None
        assert result.memory is not None
        assert result.disk is not None


class TestContentionDetector:
    """Tests for ContentionDetector class."""

    def test_detect_contention_no_events(self):
        """Test detection when no contention occurs."""
        detector = ContentionDetector()

        now = datetime.utcnow()
        data_points = [
            {"timestamp": now - timedelta(hours=i), "value": 50}
            for i in range(100)
        ]

        events = detector.detect_contention(data_points, "cpu", "server-1")
        assert len(events) == 0

    def test_detect_contention_with_events(self):
        """Test detection when contention occurs."""
        detector = ContentionDetector()

        now = datetime.utcnow()
        # Create data with a contention period
        data_points = []
        for i in range(60):
            if 20 <= i <= 40:  # 20 minutes of high usage
                value = 85
            else:
                value = 50
            data_points.append({
                "timestamp": now - timedelta(minutes=60-i),
                "value": value
            })

        events = detector.detect_contention(data_points, "cpu", "server-1")
        assert len(events) == 1
        assert events[0].resource_type == "cpu"
        assert events[0].severity == "warning"

    def test_detect_contention_critical(self):
        """Test detection of critical contention."""
        detector = ContentionDetector()

        now = datetime.utcnow()
        data_points = [
            {"timestamp": now - timedelta(minutes=60-i), "value": 98}
            for i in range(30)
        ]

        events = detector.detect_contention(data_points, "cpu", "server-1")
        assert len(events) == 1
        assert events[0].severity == "critical"

    def test_analyze_server_summary(self):
        """Test server contention summary."""
        detector = ContentionDetector()

        now = datetime.utcnow()
        metrics_data = {
            "cpu": [{"timestamp": now - timedelta(minutes=i), "value": 50} for i in range(60)],
            "memory": [{"timestamp": now - timedelta(minutes=i), "value": 40} for i in range(60)],
        }

        summary = detector.analyze_server("server-1", metrics_data)

        assert isinstance(summary, ContentionSummary)
        assert summary.server_id == "server-1"
        assert summary.has_contention is False


class TestRightsizingEngine:
    """Tests for RightsizingEngine class."""

    def test_classify_oversized(self):
        """Test classification of oversized instance."""
        engine = RightsizingEngine()

        classification = engine.classify(cpu_p95=20, memory_p95=30, has_contention=False)
        assert classification == SizingClassification.OVERSIZED

    def test_classify_undersized(self):
        """Test classification of undersized instance."""
        engine = RightsizingEngine()

        classification = engine.classify(cpu_p95=85, memory_p95=60, has_contention=False)
        assert classification == SizingClassification.UNDERSIZED

    def test_classify_undersized_with_contention(self):
        """Test that contention leads to undersized classification."""
        engine = RightsizingEngine()

        classification = engine.classify(cpu_p95=50, memory_p95=50, has_contention=True)
        assert classification == SizingClassification.UNDERSIZED

    def test_classify_right_sized(self):
        """Test classification of right-sized instance."""
        engine = RightsizingEngine()

        classification = engine.classify(cpu_p95=55, memory_p95=60, has_contention=False)
        assert classification == SizingClassification.RIGHT_SIZED

    def test_classify_unknown(self):
        """Test classification with no data."""
        engine = RightsizingEngine()

        classification = engine.classify(cpu_p95=None, memory_p95=None)
        assert classification == SizingClassification.UNKNOWN

    def test_recommend_oversized(self):
        """Test recommendation for oversized instance."""
        engine = RightsizingEngine()

        rec = engine.recommend(
            server_id="server-1",
            current_instance_type="m5.xlarge",
            cpu_p95=20,
            memory_p95=25,
            has_contention=False
        )

        assert isinstance(rec, SizingRecommendation)
        assert rec.classification == SizingClassification.OVERSIZED
        assert rec.confidence > 0.5
        assert rec.risk_level == "low"

    def test_recommend_right_sized(self):
        """Test recommendation for right-sized instance."""
        engine = RightsizingEngine()

        rec = engine.recommend(
            server_id="server-1",
            current_instance_type="m5.xlarge",
            cpu_p95=55,
            memory_p95=60,
            has_contention=False
        )

        assert rec.classification == SizingClassification.RIGHT_SIZED
        assert rec.recommended_instance_type is None

    def test_recommend_batch(self):
        """Test batch recommendation."""
        engine = RightsizingEngine()

        servers = [
            {"server_id": "s1", "instance_type": "m5.large", "cpu_p95": 20, "memory_p95": 25},
            {"server_id": "s2", "instance_type": "m5.xlarge", "cpu_p95": 55, "memory_p95": 60},
            {"server_id": "s3", "instance_type": "m5.2xlarge", "cpu_p95": 85, "memory_p95": 90},
        ]

        recommendations = engine.recommend_batch(servers)

        assert len(recommendations) == 3
        assert recommendations[0].classification == SizingClassification.OVERSIZED
        assert recommendations[1].classification == SizingClassification.RIGHT_SIZED
        assert recommendations[2].classification == SizingClassification.UNDERSIZED


class TestIntegration:
    """Integration tests combining multiple components."""

    def test_full_analysis_pipeline(self):
        """Test the full analysis pipeline."""
        metrics_analyzer = MetricsAnalyzer()
        contention_detector = ContentionDetector()
        rightsizing_engine = RightsizingEngine()

        now = datetime.utcnow()

        # Simulate data for an oversized server
        metrics_data = {
            "cpu": [{"timestamp": now - timedelta(hours=i), "value": 25 + i % 10} for i in range(100)],
            "memory": [{"timestamp": now - timedelta(hours=i), "value": 35 + i % 5} for i in range(100)],
        }

        # Analyze metrics
        server_metrics = metrics_analyzer.analyze_server("test-server", metrics_data)

        # Detect contention
        contention = contention_detector.analyze_server("test-server", metrics_data)

        # Generate recommendation
        cpu_p95 = server_metrics.cpu.p95 if server_metrics.cpu else None
        memory_p95 = server_metrics.memory.p95 if server_metrics.memory else None

        recommendation = rightsizing_engine.recommend(
            server_id="test-server",
            current_instance_type="m5.xlarge",
            cpu_p95=cpu_p95,
            memory_p95=memory_p95,
            has_contention=contention.has_contention
        )

        # Verify results
        assert server_metrics.cpu is not None
        assert server_metrics.memory is not None
        assert contention.has_contention is False
        assert recommendation.classification == SizingClassification.OVERSIZED
