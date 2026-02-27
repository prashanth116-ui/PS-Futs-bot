"""
Session timing filters for TTFM.

Restricts entries to high-probability time windows during RTH,
with a lunch lull no-entry zone.
"""

from datetime import time as dt_time, datetime


def in_session(
    timestamp: datetime,
    session_start: str = "04:00",
    session_end: str = "16:00",
    no_entry_start: str = "12:00",
    no_entry_end: str = "14:00",
) -> bool:
    """Check if timestamp is within an allowed entry window.

    Args:
        timestamp: Bar timestamp (must be timezone-aware or naive ET).
        session_start: Session start time (HH:MM).
        session_end: Session end time (HH:MM).
        no_entry_start: Start of no-entry zone (HH:MM).
        no_entry_end: End of no-entry zone (HH:MM).

    Returns:
        True if entries are allowed at this time.
    """
    t = timestamp.time()

    start = _parse_time(session_start)
    end = _parse_time(session_end)
    no_start = _parse_time(no_entry_start)
    no_end = _parse_time(no_entry_end)

    if t < start or t > end:
        return False

    if no_start <= t < no_end:
        return False

    return True


def _parse_time(s: str) -> dt_time:
    parts = s.split(":")
    return dt_time(int(parts[0]), int(parts[1]))
