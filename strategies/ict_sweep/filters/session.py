"""
Session Filter Module

Filters trades based on time of day. Best setups occur during
high-volume sessions (NY Open, London) and should avoid lunch lull.
"""
from datetime import datetime, time as dt_time

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo


# Eastern Time zone
ET = ZoneInfo('America/New_York')


def get_et_time(timestamp: datetime) -> dt_time:
    """
    Get the time in Eastern Time from a timestamp.

    Args:
        timestamp: Datetime object (naive assumed ET, aware converted)

    Returns:
        time object in ET
    """
    if timestamp.tzinfo is None:
        # Naive datetime - assume already ET
        return timestamp.time()
    else:
        # Aware datetime - convert to ET
        return timestamp.astimezone(ET).time()


def is_valid_session(
    timestamp: datetime,
    session_start: dt_time = dt_time(9, 30),
    session_end: dt_time = dt_time(16, 0)
) -> bool:
    """
    Check if timestamp is within valid trading session.

    Args:
        timestamp: Bar timestamp
        session_start: Session start time (default 9:30 AM ET)
        session_end: Session end time (default 4:00 PM ET)

    Returns:
        True if within session
    """
    bar_time = get_et_time(timestamp)
    return session_start <= bar_time <= session_end


def is_lunch_lull(
    timestamp: datetime,
    lunch_start: dt_time = dt_time(12, 0),
    lunch_end: dt_time = dt_time(13, 0)
) -> bool:
    """
    Check if timestamp is during lunch lull (low volume period).

    Args:
        timestamp: Bar timestamp
        lunch_start: Lunch lull start (default 12:00 PM ET)
        lunch_end: Lunch lull end (default 1:00 PM ET)

    Returns:
        True if during lunch lull
    """
    bar_time = get_et_time(timestamp)
    return lunch_start <= bar_time <= lunch_end


def is_ny_open(
    timestamp: datetime,
    start: dt_time = dt_time(9, 30),
    end: dt_time = dt_time(11, 0)
) -> bool:
    """
    Check if timestamp is during NY Open killzone.

    Args:
        timestamp: Bar timestamp
        start: Killzone start (default 9:30 AM ET)
        end: Killzone end (default 11:00 AM ET)

    Returns:
        True if during NY Open
    """
    bar_time = get_et_time(timestamp)
    return start <= bar_time <= end


def is_ny_pm(
    timestamp: datetime,
    start: dt_time = dt_time(13, 30),
    end: dt_time = dt_time(16, 0)
) -> bool:
    """
    Check if timestamp is during NY PM session.

    Args:
        timestamp: Bar timestamp
        start: PM session start (default 1:30 PM ET)
        end: PM session end (default 4:00 PM ET)

    Returns:
        True if during NY PM
    """
    bar_time = get_et_time(timestamp)
    return start <= bar_time <= end


def is_london_session(
    timestamp: datetime,
    start: dt_time = dt_time(2, 0),
    end: dt_time = dt_time(5, 0)
) -> bool:
    """
    Check if timestamp is during London session (pre-market for US).

    Args:
        timestamp: Bar timestamp
        start: London start (default 2:00 AM ET)
        end: London end (default 5:00 AM ET)

    Returns:
        True if during London session
    """
    bar_time = get_et_time(timestamp)
    return start <= bar_time <= end


def get_session_name(timestamp: datetime) -> str:
    """
    Get the name of the current session.

    Args:
        timestamp: Bar timestamp

    Returns:
        Session name string
    """
    if is_london_session(timestamp):
        return "LONDON"
    elif is_ny_open(timestamp):
        return "NY_OPEN"
    elif is_lunch_lull(timestamp):
        return "LUNCH"
    elif is_ny_pm(timestamp):
        return "NY_PM"
    elif is_valid_session(timestamp):
        return "RTH"
    else:
        return "OVERNIGHT"


def should_trade(
    timestamp: datetime,
    allow_lunch: bool = False,
    require_killzone: bool = False
) -> bool:
    """
    Determine if trading is allowed at this time.

    Args:
        timestamp: Bar timestamp
        allow_lunch: Allow trades during lunch lull
        require_killzone: Only trade during killzones (NY Open, NY PM)

    Returns:
        True if trading allowed
    """
    # Must be in valid session
    if not is_valid_session(timestamp):
        return False

    # Check lunch lull
    if not allow_lunch and is_lunch_lull(timestamp):
        return False

    # Check killzone requirement
    if require_killzone:
        return is_ny_open(timestamp) or is_ny_pm(timestamp)

    return True
