"""
Timezone Service
Unified timezone handling and conversion between UTC database timestamps
and user-local display times throughout the WakeWise platform.
"""

import os
import datetime
import logging
from typing import Optional, Dict
from fastapi import Request

logger = logging.getLogger("timezone_service")

# In-memory cache mapping user_id -> timezone offset in minutes (e.g., +330 for Asia/Kolkata)
_user_timezone_offsets: Dict[int, int] = {}


def get_default_timezone_offset() -> int:
    """
    Returns the server's default fallback timezone offset in minutes.
    Defaults to 330 (+05:30 IST) if not configured.
    """
    env_offset = os.getenv("DEFAULT_TIMEZONE_OFFSET")
    if env_offset:
        try:
            return int(env_offset.strip())
        except ValueError:
            pass

    tz_env = os.getenv("TZ", "").strip()
    if tz_env in {"Asia/Kolkata", "Asia/Calcutta", "IST"}:
        return 330

    return 330


def set_user_timezone(user_id: int, offset_minutes: int) -> None:
    """Stores the latest client timezone offset for a specific user."""
    try:
        val = int(offset_minutes)
        if -840 <= val <= 840:
            _user_timezone_offsets[user_id] = val
    except (ValueError, TypeError):
        pass


def get_user_timezone(user_id: Optional[int] = None) -> int:
    """Retrieves the cached timezone offset for a user, or default fallback."""
    if user_id is not None and user_id in _user_timezone_offsets:
        return _user_timezone_offsets[user_id]
    return get_default_timezone_offset()


def extract_timezone_offset_from_request(request: Optional[Request] = None, user_id: Optional[int] = None) -> int:
    """
    Extracts timezone offset in minutes from request headers (X-Timezone-Offset),
    falling back to the user cache, then server default.
    """
    if request is not None:
        raw_header = request.headers.get("x-timezone-offset") or request.headers.get("X-Timezone-Offset")
        if raw_header is not None:
            try:
                offset_val = int(raw_header.strip())
                if -840 <= offset_val <= 840:
                    if user_id is not None:
                        set_user_timezone(user_id, offset_val)
                    return offset_val
            except (ValueError, TypeError):
                pass

    return get_user_timezone(user_id)


def to_user_datetime(dt: Optional[datetime.datetime], offset_minutes: Optional[int] = None) -> Optional[datetime.datetime]:
    """
    Converts a UTC or naive datetime to the user's localized timezone.
    If the datetime is naive, it is assumed to be in UTC (standard for PostgreSQL/SQLite UTC timestamps).
    """
    if dt is None:
        return None

    offset = offset_minutes if offset_minutes is not None else get_default_timezone_offset()

    # Ensure tz-aware in UTC
    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        utc_dt = dt.astimezone(datetime.timezone.utc)

    user_tz = datetime.timezone(datetime.timedelta(minutes=offset))
    return utc_dt.astimezone(user_tz)


def to_user_hhmm(dt: Optional[datetime.datetime], offset_minutes: Optional[int] = None) -> Optional[str]:
    """Formats a datetime as 'HH:MM' in the user's local timezone."""
    udt = to_user_datetime(dt, offset_minutes)
    if udt is None:
        return None
    return udt.strftime("%H:%M")


def to_user_date_str(dt: Optional[datetime.datetime], offset_minutes: Optional[int] = None) -> Optional[str]:
    """Formats a datetime as 'YYYY-MM-DD' in the user's local timezone."""
    udt = to_user_datetime(dt, offset_minutes)
    if udt is None:
        return None
    return udt.strftime("%Y-%m-%d")


def get_user_now(offset_minutes: Optional[int] = None) -> datetime.datetime:
    """Returns the current moment in the user's localized timezone."""
    offset = offset_minutes if offset_minutes is not None else get_default_timezone_offset()
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    user_tz = datetime.timezone(datetime.timedelta(minutes=offset))
    return utc_now.astimezone(user_tz)
