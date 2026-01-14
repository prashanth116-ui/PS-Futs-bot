"""
Session Filter Module

Filters trades based on trading session times.
Implements ICT killzones (London, New York, Asian sessions)
and validates that trades occur during high-probability windows.

Killzones are specific time windows where institutional activity
is highest and ICT setups are most reliable:
    - London Open: 02:00-05:00 ET (European session start)
    - NY Open: 09:30-11:00 ET (US equity market open)

All times use America/New_York timezone to automatically handle
US daylight saving time transitions.

Example config (ict_es.yaml):
    killzones:
      NY_OPEN:
        enabled: true
        start: "09:30"
        end: "11:00"
      LONDON:
        enabled: true
        start: "02:00"
        end: "05:00"

Example usage:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    killzones = {
        "NY_OPEN": {"enabled": True, "start": "09:30", "end": "11:00"},
        "LONDON": {"enabled": True, "start": "02:00", "end": "05:00"},
    }

    ts = datetime(2024, 1, 15, 10, 0, tzinfo=ZoneInfo("America/New_York"))

    is_in_killzone(ts, killzones)          # True (in NY_OPEN)
    current_session_label(ts, killzones)   # "NY_OPEN"
"""

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

# Eastern Time zone - handles DST automatically
ET = ZoneInfo("America/New_York")


@dataclass
class KillzoneWindow:
    """
    Represents a single killzone time window.

    Attributes:
        name: Identifier for the killzone (e.g., "NY_OPEN", "LONDON")
        start: Start time of the window (Eastern Time)
        end: End time of the window (Eastern Time)
        enabled: Whether this killzone is active for trading
    """

    name: str
    start: time
    end: time
    enabled: bool = True

    def contains(self, t: time) -> bool:
        """
        Check if a given time falls within this killzone window.

        Handles both normal windows (start < end) and overnight windows
        (start > end, e.g., 22:00-02:00).

        Args:
            t: Time to check (should be in Eastern Time)

        Returns:
            True if time is within the window, False otherwise.

        Example:
            window = KillzoneWindow("NY_OPEN", time(9, 30), time(11, 0))
            window.contains(time(10, 15))  # True
            window.contains(time(14, 0))   # False
        """
        if not self.enabled:
            return False

        # Normal window: start and end on same day
        if self.start <= self.end:
            return self.start <= t < self.end

        # Overnight window: spans midnight (e.g., 22:00 - 02:00)
        # Time is in window if it's >= start OR < end
        return t >= self.start or t < self.end


def parse_time(time_str: str) -> time:
    """
    Parse a time string in HH:MM format to a time object.

    Args:
        time_str: Time string in "HH:MM" format (24-hour).
                  Example: "09:30", "14:00", "02:00"

    Returns:
        A datetime.time object.

    Raises:
        ValueError: If the string is not in valid HH:MM format.

    Example:
        parse_time("09:30")  # time(9, 30)
        parse_time("14:00")  # time(14, 0)
    """
    try:
        parts = time_str.strip().split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid time format: {time_str}")
        hour = int(parts[0])
        minute = int(parts[1])
        return time(hour, minute)
    except (ValueError, IndexError) as e:
        raise ValueError(f"Cannot parse time '{time_str}': expected HH:MM format") from e


def parse_killzones(config: dict) -> list[KillzoneWindow]:
    """
    Parse killzone configuration from a dictionary (typically from YAML).

    Args:
        config: Dictionary with killzone definitions.
                Expected structure:
                {
                    "KILLZONE_NAME": {
                        "enabled": bool,
                        "start": "HH:MM",
                        "end": "HH:MM"
                    },
                    ...
                }

    Returns:
        List of KillzoneWindow objects, sorted by start time.

    Example:
        config = {
            "NY_OPEN": {"enabled": True, "start": "09:30", "end": "11:00"},
            "LONDON": {"enabled": False, "start": "02:00", "end": "05:00"},
        }
        windows = parse_killzones(config)
        # Returns [KillzoneWindow("LONDON", ..., enabled=False),
        #          KillzoneWindow("NY_OPEN", ..., enabled=True)]
    """
    windows: list[KillzoneWindow] = []

    for name, settings in config.items():
        # Handle both dict-style and simple configs
        if not isinstance(settings, dict):
            continue

        enabled = settings.get("enabled", True)
        start_str = settings.get("start")
        end_str = settings.get("end")

        if not start_str or not end_str:
            # Skip incomplete killzone definitions
            continue

        window = KillzoneWindow(
            name=name,
            start=parse_time(start_str),
            end=parse_time(end_str),
            enabled=enabled,
        )
        windows.append(window)

    # Sort by start time for consistent ordering
    windows.sort(key=lambda w: (w.start.hour, w.start.minute))
    return windows


def ensure_eastern_time(ts: datetime) -> datetime:
    """
    Ensure a datetime is in Eastern Time (America/New_York).

    If the datetime is naive (no timezone), it's assumed to already
    be in Eastern Time and will be localized. If it has a timezone,
    it will be converted to Eastern Time.

    Args:
        ts: A datetime object, with or without timezone info.

    Returns:
        A timezone-aware datetime in America/New_York timezone.

    Example:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        # Naive datetime - assumed to be ET
        naive = datetime(2024, 1, 15, 10, 0)
        ensure_eastern_time(naive)  # 2024-01-15 10:00:00-05:00

        # UTC datetime - converted to ET
        utc = datetime(2024, 1, 15, 15, 0, tzinfo=ZoneInfo("UTC"))
        ensure_eastern_time(utc)    # 2024-01-15 10:00:00-05:00
    """
    if ts.tzinfo is None:
        # Naive datetime: assume it's already in Eastern Time
        return ts.replace(tzinfo=ET)
    else:
        # Aware datetime: convert to Eastern Time
        return ts.astimezone(ET)


def is_in_killzone(ts: datetime, killzones: dict | list[KillzoneWindow]) -> bool:
    """
    Check if a timestamp falls within any enabled killzone.

    This is the primary function for filtering trades by session.
    Returns True if the timestamp is inside at least one active killzone.

    Args:
        ts: Timestamp to check. Can be timezone-aware or naive.
            If naive, assumed to be in Eastern Time.
            If aware, will be converted to Eastern Time.

        killzones: Either:
            - A dict of killzone configs (from YAML)
            - A list of pre-parsed KillzoneWindow objects

    Returns:
        True if timestamp is within an enabled killzone, False otherwise.

    Example:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        killzones = {
            "NY_OPEN": {"enabled": True, "start": "09:30", "end": "11:00"},
            "LONDON": {"enabled": True, "start": "02:00", "end": "05:00"},
        }

        # During NY Open
        ts1 = datetime(2024, 1, 15, 10, 0, tzinfo=ZoneInfo("America/New_York"))
        is_in_killzone(ts1, killzones)  # True

        # Outside all killzones
        ts2 = datetime(2024, 1, 15, 14, 0, tzinfo=ZoneInfo("America/New_York"))
        is_in_killzone(ts2, killzones)  # False

        # During London (disabled)
        killzones["LONDON"]["enabled"] = False
        ts3 = datetime(2024, 1, 15, 3, 0, tzinfo=ZoneInfo("America/New_York"))
        is_in_killzone(ts3, killzones)  # False (London disabled)
    """
    # Parse killzones if given as dict
    if isinstance(killzones, dict):
        windows = parse_killzones(killzones)
    else:
        windows = killzones

    # Convert timestamp to Eastern Time
    ts_et = ensure_eastern_time(ts)
    current_time = ts_et.time()

    # Check each enabled killzone
    for window in windows:
        if window.contains(current_time):
            return True

    return False


def current_session_label(ts: datetime, killzones: dict | list[KillzoneWindow]) -> str:
    """
    Get the label of the current active killzone, or "OFF" if none.

    Returns the name of the first matching enabled killzone. If the
    timestamp falls within multiple overlapping killzones, returns
    the first one (sorted by start time).

    Args:
        ts: Timestamp to check. Can be timezone-aware or naive.
            If naive, assumed to be in Eastern Time.

        killzones: Either:
            - A dict of killzone configs (from YAML)
            - A list of pre-parsed KillzoneWindow objects

    Returns:
        The killzone name (e.g., "NY_OPEN", "LONDON") if in a killzone,
        or "OFF" if outside all killzones.

    Example:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        killzones = {
            "NY_OPEN": {"enabled": True, "start": "09:30", "end": "11:00"},
            "LONDON": {"enabled": True, "start": "02:00", "end": "05:00"},
        }

        # During NY Open
        ts1 = datetime(2024, 1, 15, 10, 0, tzinfo=ZoneInfo("America/New_York"))
        current_session_label(ts1, killzones)  # "NY_OPEN"

        # During London session
        ts2 = datetime(2024, 1, 15, 3, 30, tzinfo=ZoneInfo("America/New_York"))
        current_session_label(ts2, killzones)  # "LONDON"

        # Outside all sessions
        ts3 = datetime(2024, 1, 15, 14, 0, tzinfo=ZoneInfo("America/New_York"))
        current_session_label(ts3, killzones)  # "OFF"
    """
    # Parse killzones if given as dict
    if isinstance(killzones, dict):
        windows = parse_killzones(killzones)
    else:
        windows = killzones

    # Convert timestamp to Eastern Time
    ts_et = ensure_eastern_time(ts)
    current_time = ts_et.time()

    # Find the first matching killzone
    for window in windows:
        if window.contains(current_time):
            return window.name

    return "OFF"


def get_default_killzones() -> dict:
    """
    Return the default ICT killzone configuration.

    These are the standard killzones used in ICT methodology:
        - NY_OPEN: 09:30-11:00 ET (US equity market open)
        - LONDON: 02:00-05:00 ET (European session start)

    Returns:
        A dictionary suitable for use with is_in_killzone() and
        current_session_label(), or for inclusion in strategy config.

    Example:
        killzones = get_default_killzones()
        # Disable London if only trading NY
        killzones["LONDON"]["enabled"] = False
    """
    return {
        "NY_OPEN": {
            "enabled": True,
            "start": "09:30",
            "end": "11:00",
            "description": "New York market open - highest volume period",
        },
        "LONDON": {
            "enabled": True,
            "start": "02:00",
            "end": "05:00",
            "description": "London session open - European institutional activity",
        },
    }


# -----------------------------------------------------------------------------
# Additional utility functions
# -----------------------------------------------------------------------------


def get_next_killzone(ts: datetime, killzones: dict | list[KillzoneWindow]) -> tuple[str, datetime] | None:
    """
    Find the next upcoming killzone after the given timestamp.

    Useful for logging or UI to show when the next trading window starts.

    Args:
        ts: Current timestamp.
        killzones: Killzone configuration.

    Returns:
        A tuple of (killzone_name, start_datetime) for the next killzone,
        or None if no killzones are enabled.

    Example:
        ts = datetime(2024, 1, 15, 12, 0, tzinfo=ZoneInfo("America/New_York"))
        name, start = get_next_killzone(ts, killzones)
        # ("LONDON", datetime(2024, 1, 16, 2, 0, ...))  # Next day's London
    """
    # Parse killzones if given as dict
    if isinstance(killzones, dict):
        windows = parse_killzones(killzones)
    else:
        windows = killzones

    # Filter to only enabled killzones
    enabled_windows = [w for w in windows if w.enabled]
    if not enabled_windows:
        return None

    # Convert timestamp to Eastern Time
    ts_et = ensure_eastern_time(ts)
    current_time = ts_et.time()

    # Find the next killzone start time
    for window in enabled_windows:
        if window.start > current_time:
            # This killzone starts later today
            next_start = ts_et.replace(
                hour=window.start.hour,
                minute=window.start.minute,
                second=0,
                microsecond=0,
            )
            return (window.name, next_start)

    # All killzones have passed today; return first one tomorrow
    if enabled_windows:
        first_window = enabled_windows[0]
        from datetime import timedelta

        tomorrow = ts_et.date() + timedelta(days=1)
        next_start = datetime(
            tomorrow.year,
            tomorrow.month,
            tomorrow.day,
            first_window.start.hour,
            first_window.start.minute,
            tzinfo=ET,
        )
        return (first_window.name, next_start)

    return None
