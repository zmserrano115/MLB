from datetime import datetime, timezone
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_APP_TIMEZONE = "America/Denver"


def app_timezone_name():
    return os.getenv("APP_TIMEZONE", DEFAULT_APP_TIMEZONE).strip() or DEFAULT_APP_TIMEZONE


def current_app_datetime(now=None, timezone_name=None):
    try:
        app_timezone = ZoneInfo(timezone_name or app_timezone_name())
    except ZoneInfoNotFoundError:
        app_timezone = ZoneInfo(DEFAULT_APP_TIMEZONE)

    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    return now.astimezone(app_timezone)


def current_app_date(now=None, timezone_name=None):
    return current_app_datetime(now=now, timezone_name=timezone_name).date()
