"""
Unit Tests for Session Filter Module

Tests the killzone detection and session labeling functionality.
These tests verify that the session filter correctly identifies
when timestamps fall within configured trading windows.

Run with: pytest tests/test_session_filter.py -v
"""

from datetime import datetime, time

import pytest
from zoneinfo import ZoneInfo

from strategies.ict.filters.session import (
    ET,
    KillzoneWindow,
    current_session_label,
    ensure_eastern_time,
    get_default_killzones,
    get_next_killzone,
    is_in_killzone,
    parse_killzones,
    parse_time,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def default_killzones() -> dict:
    """Standard ICT killzone configuration for testing."""
    return {
        "NY_OPEN": {"enabled": True, "start": "09:30", "end": "11:00"},
        "LONDON": {"enabled": True, "start": "02:00", "end": "05:00"},
    }


@pytest.fixture
def ny_only_killzones() -> dict:
    """Configuration with only NY Open enabled."""
    return {
        "NY_OPEN": {"enabled": True, "start": "09:30", "end": "11:00"},
        "LONDON": {"enabled": False, "start": "02:00", "end": "05:00"},
    }


# =============================================================================
# Tests for parse_time()
# =============================================================================


class TestParseTime:
    """Tests for the parse_time() function."""

    def test_parse_valid_morning_time(self):
        """Parse a typical morning time like 09:30."""
        result = parse_time("09:30")
        assert result == time(9, 30)

    def test_parse_valid_afternoon_time(self):
        """Parse an afternoon time like 14:00."""
        result = parse_time("14:00")
        assert result == time(14, 0)

    def test_parse_midnight(self):
        """Parse midnight as 00:00."""
        result = parse_time("00:00")
        assert result == time(0, 0)

    def test_parse_end_of_day(self):
        """Parse end of day as 23:59."""
        result = parse_time("23:59")
        assert result == time(23, 59)

    def test_parse_with_whitespace(self):
        """Parse time with surrounding whitespace."""
        result = parse_time("  10:30  ")
        assert result == time(10, 30)

    def test_parse_invalid_format_raises(self):
        """Invalid format should raise ValueError."""
        with pytest.raises(ValueError):
            parse_time("9:30:00")  # Too many parts

    def test_parse_invalid_hour_raises(self):
        """Invalid hour should raise ValueError."""
        with pytest.raises(ValueError):
            parse_time("25:00")

    def test_parse_non_numeric_raises(self):
        """Non-numeric input should raise ValueError."""
        with pytest.raises(ValueError):
            parse_time("ab:cd")


# =============================================================================
# Tests for KillzoneWindow
# =============================================================================


class TestKillzoneWindow:
    """Tests for the KillzoneWindow dataclass."""

    def test_contains_time_within_window(self):
        """Time within normal window should return True."""
        window = KillzoneWindow("NY_OPEN", time(9, 30), time(11, 0))
        assert window.contains(time(10, 0)) is True

    def test_contains_time_at_start(self):
        """Time exactly at start should return True (inclusive)."""
        window = KillzoneWindow("NY_OPEN", time(9, 30), time(11, 0))
        assert window.contains(time(9, 30)) is True

    def test_contains_time_at_end(self):
        """Time exactly at end should return False (exclusive)."""
        window = KillzoneWindow("NY_OPEN", time(9, 30), time(11, 0))
        assert window.contains(time(11, 0)) is False

    def test_contains_time_outside_window(self):
        """Time outside window should return False."""
        window = KillzoneWindow("NY_OPEN", time(9, 30), time(11, 0))
        assert window.contains(time(14, 0)) is False

    def test_contains_disabled_window(self):
        """Disabled window should always return False."""
        window = KillzoneWindow("NY_OPEN", time(9, 30), time(11, 0), enabled=False)
        assert window.contains(time(10, 0)) is False

    def test_contains_overnight_window_before_midnight(self):
        """Overnight window should match times before midnight."""
        # Asian session example: 22:00 - 02:00
        window = KillzoneWindow("ASIAN", time(22, 0), time(2, 0))
        assert window.contains(time(23, 0)) is True

    def test_contains_overnight_window_after_midnight(self):
        """Overnight window should match times after midnight."""
        window = KillzoneWindow("ASIAN", time(22, 0), time(2, 0))
        assert window.contains(time(1, 0)) is True

    def test_contains_overnight_window_outside(self):
        """Overnight window should not match times in the middle of day."""
        window = KillzoneWindow("ASIAN", time(22, 0), time(2, 0))
        assert window.contains(time(12, 0)) is False


# =============================================================================
# Tests for parse_killzones()
# =============================================================================


class TestParseKillzones:
    """Tests for the parse_killzones() function."""

    def test_parse_valid_config(self, default_killzones):
        """Parse a valid killzone configuration."""
        windows = parse_killzones(default_killzones)
        assert len(windows) == 2

    def test_parse_sorts_by_start_time(self, default_killzones):
        """Parsed windows should be sorted by start time."""
        windows = parse_killzones(default_killzones)
        # London (02:00) should come before NY (09:30)
        assert windows[0].name == "LONDON"
        assert windows[1].name == "NY_OPEN"

    def test_parse_preserves_enabled_flag(self, ny_only_killzones):
        """Enabled flag should be preserved from config."""
        windows = parse_killzones(ny_only_killzones)
        london = next(w for w in windows if w.name == "LONDON")
        ny = next(w for w in windows if w.name == "NY_OPEN")
        assert london.enabled is False
        assert ny.enabled is True

    def test_parse_skips_incomplete_entries(self):
        """Entries without start/end should be skipped."""
        config = {
            "VALID": {"start": "09:30", "end": "11:00"},
            "MISSING_END": {"start": "02:00"},
            "MISSING_START": {"end": "05:00"},
        }
        windows = parse_killzones(config)
        assert len(windows) == 1
        assert windows[0].name == "VALID"

    def test_parse_empty_config(self):
        """Empty config should return empty list."""
        windows = parse_killzones({})
        assert windows == []


# =============================================================================
# Tests for ensure_eastern_time()
# =============================================================================


class TestEnsureEasternTime:
    """Tests for the ensure_eastern_time() function."""

    def test_naive_datetime_assumes_eastern(self):
        """Naive datetime should be assumed to be in Eastern Time."""
        naive = datetime(2024, 1, 15, 10, 0)
        result = ensure_eastern_time(naive)
        assert result.tzinfo == ET
        assert result.hour == 10

    def test_utc_datetime_converts_to_eastern(self):
        """UTC datetime should be converted to Eastern Time."""
        utc = datetime(2024, 1, 15, 15, 0, tzinfo=ZoneInfo("UTC"))
        result = ensure_eastern_time(utc)
        assert result.tzinfo == ET
        # 15:00 UTC = 10:00 ET (standard time)
        assert result.hour == 10

    def test_already_eastern_unchanged(self):
        """Eastern datetime should remain unchanged."""
        eastern = datetime(2024, 1, 15, 10, 0, tzinfo=ET)
        result = ensure_eastern_time(eastern)
        assert result == eastern


# =============================================================================
# Tests for is_in_killzone()
# =============================================================================


class TestIsInKillzone:
    """Tests for the is_in_killzone() function."""

    def test_in_ny_open(self, default_killzones):
        """Timestamp during NY Open should return True."""
        ts = datetime(2024, 1, 15, 10, 0, tzinfo=ET)
        assert is_in_killzone(ts, default_killzones) is True

    def test_in_london(self, default_killzones):
        """Timestamp during London session should return True."""
        ts = datetime(2024, 1, 15, 3, 30, tzinfo=ET)
        assert is_in_killzone(ts, default_killzones) is True

    def test_outside_all_killzones(self, default_killzones):
        """Timestamp outside all killzones should return False."""
        ts = datetime(2024, 1, 15, 14, 0, tzinfo=ET)
        assert is_in_killzone(ts, default_killzones) is False

    def test_disabled_killzone_returns_false(self, ny_only_killzones):
        """Timestamp in disabled killzone should return False."""
        ts = datetime(2024, 1, 15, 3, 30, tzinfo=ET)  # London time
        assert is_in_killzone(ts, ny_only_killzones) is False

    def test_accepts_naive_datetime(self, default_killzones):
        """Naive datetime should work (assumed to be ET)."""
        ts = datetime(2024, 1, 15, 10, 0)  # No timezone
        assert is_in_killzone(ts, default_killzones) is True

    def test_accepts_utc_datetime(self, default_killzones):
        """UTC datetime should be converted correctly."""
        # 15:00 UTC = 10:00 ET (in NY Open)
        ts = datetime(2024, 1, 15, 15, 0, tzinfo=ZoneInfo("UTC"))
        assert is_in_killzone(ts, default_killzones) is True

    def test_accepts_pre_parsed_windows(self, default_killzones):
        """Should accept list of KillzoneWindow objects."""
        windows = parse_killzones(default_killzones)
        ts = datetime(2024, 1, 15, 10, 0, tzinfo=ET)
        assert is_in_killzone(ts, windows) is True


# =============================================================================
# Tests for current_session_label()
# =============================================================================


class TestCurrentSessionLabel:
    """Tests for the current_session_label() function."""

    def test_returns_ny_open(self, default_killzones):
        """Should return 'NY_OPEN' during NY Open."""
        ts = datetime(2024, 1, 15, 10, 0, tzinfo=ET)
        assert current_session_label(ts, default_killzones) == "NY_OPEN"

    def test_returns_london(self, default_killzones):
        """Should return 'LONDON' during London session."""
        ts = datetime(2024, 1, 15, 3, 30, tzinfo=ET)
        assert current_session_label(ts, default_killzones) == "LONDON"

    def test_returns_off_outside_sessions(self, default_killzones):
        """Should return 'OFF' outside all sessions."""
        ts = datetime(2024, 1, 15, 14, 0, tzinfo=ET)
        assert current_session_label(ts, default_killzones) == "OFF"

    def test_disabled_session_returns_off(self, ny_only_killzones):
        """Should return 'OFF' for disabled session time."""
        ts = datetime(2024, 1, 15, 3, 30, tzinfo=ET)
        assert current_session_label(ts, ny_only_killzones) == "OFF"


# =============================================================================
# Tests for get_default_killzones()
# =============================================================================


class TestGetDefaultKillzones:
    """Tests for the get_default_killzones() function."""

    def test_returns_ny_open(self):
        """Should include NY_OPEN killzone."""
        killzones = get_default_killzones()
        assert "NY_OPEN" in killzones
        assert killzones["NY_OPEN"]["start"] == "09:30"
        assert killzones["NY_OPEN"]["end"] == "11:00"

    def test_returns_london(self):
        """Should include LONDON killzone."""
        killzones = get_default_killzones()
        assert "LONDON" in killzones
        assert killzones["LONDON"]["start"] == "02:00"
        assert killzones["LONDON"]["end"] == "05:00"

    def test_all_enabled_by_default(self):
        """All killzones should be enabled by default."""
        killzones = get_default_killzones()
        for name, config in killzones.items():
            assert config["enabled"] is True, f"{name} should be enabled"


# =============================================================================
# Tests for DST handling
# =============================================================================


class TestDaylightSavingTime:
    """Tests for correct handling of US daylight saving time."""

    def test_standard_time_ny_open(self):
        """NY Open during standard time (EST, UTC-5)."""
        # January 15 is in standard time
        ts = datetime(2024, 1, 15, 10, 0, tzinfo=ET)
        killzones = get_default_killzones()
        assert is_in_killzone(ts, killzones) is True
        assert current_session_label(ts, killzones) == "NY_OPEN"

    def test_daylight_time_ny_open(self):
        """NY Open during daylight time (EDT, UTC-4)."""
        # July 15 is in daylight time
        ts = datetime(2024, 7, 15, 10, 0, tzinfo=ET)
        killzones = get_default_killzones()
        assert is_in_killzone(ts, killzones) is True
        assert current_session_label(ts, killzones) == "NY_OPEN"

    def test_utc_conversion_standard_time(self):
        """UTC to ET conversion during standard time."""
        # 15:00 UTC = 10:00 EST (UTC-5)
        ts_utc = datetime(2024, 1, 15, 15, 0, tzinfo=ZoneInfo("UTC"))
        killzones = get_default_killzones()
        assert is_in_killzone(ts_utc, killzones) is True

    def test_utc_conversion_daylight_time(self):
        """UTC to ET conversion during daylight time."""
        # 14:00 UTC = 10:00 EDT (UTC-4)
        ts_utc = datetime(2024, 7, 15, 14, 0, tzinfo=ZoneInfo("UTC"))
        killzones = get_default_killzones()
        assert is_in_killzone(ts_utc, killzones) is True


# =============================================================================
# Tests for get_next_killzone() - Stub
# =============================================================================


class TestGetNextKillzone:
    """Tests for the get_next_killzone() function."""

    def test_next_killzone_later_today(self, default_killzones):
        """Should find next killzone starting later today."""
        # 08:00 ET - before NY Open
        ts = datetime(2024, 1, 15, 8, 0, tzinfo=ET)
        result = get_next_killzone(ts, default_killzones)
        assert result is not None
        name, start = result
        assert name == "NY_OPEN"
        assert start.hour == 9
        assert start.minute == 30

    def test_next_killzone_tomorrow(self, default_killzones):
        """Should find next killzone tomorrow if all passed today."""
        # 14:00 ET - after all killzones
        ts = datetime(2024, 1, 15, 14, 0, tzinfo=ET)
        result = get_next_killzone(ts, default_killzones)
        assert result is not None
        name, start = result
        assert name == "LONDON"  # First killzone tomorrow
        assert start.day == 16  # Tomorrow

    def test_no_enabled_killzones_returns_none(self):
        """Should return None if no killzones are enabled."""
        killzones = {
            "NY_OPEN": {"enabled": False, "start": "09:30", "end": "11:00"},
            "LONDON": {"enabled": False, "start": "02:00", "end": "05:00"},
        }
        ts = datetime(2024, 1, 15, 8, 0, tzinfo=ET)
        result = get_next_killzone(ts, killzones)
        assert result is None


# =============================================================================
# Integration tests - to be expanded with real data
# =============================================================================


class TestIntegration:
    """
    Integration tests with realistic scenarios.

    TODO: Add tests with actual historical bar data once available.
    """

    def test_full_trading_day_simulation(self, default_killzones):
        """Simulate checking sessions throughout a trading day."""
        test_times = [
            (datetime(2024, 1, 15, 1, 0, tzinfo=ET), "OFF"),      # Before London
            (datetime(2024, 1, 15, 2, 0, tzinfo=ET), "LONDON"),   # London start
            (datetime(2024, 1, 15, 3, 30, tzinfo=ET), "LONDON"),  # Mid London
            (datetime(2024, 1, 15, 5, 0, tzinfo=ET), "OFF"),      # After London
            (datetime(2024, 1, 15, 8, 0, tzinfo=ET), "OFF"),      # Before NY
            (datetime(2024, 1, 15, 9, 30, tzinfo=ET), "NY_OPEN"), # NY start
            (datetime(2024, 1, 15, 10, 30, tzinfo=ET), "NY_OPEN"),# Mid NY
            (datetime(2024, 1, 15, 11, 0, tzinfo=ET), "OFF"),     # After NY
            (datetime(2024, 1, 15, 14, 0, tzinfo=ET), "OFF"),     # Afternoon
        ]

        for ts, expected_label in test_times:
            actual = current_session_label(ts, default_killzones)
            assert actual == expected_label, f"At {ts.time()}: expected {expected_label}, got {actual}"
