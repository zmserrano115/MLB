from datetime import date, datetime, timezone

from src.time_utils import current_app_date


def test_current_app_date_does_not_roll_over_before_denver_midnight():
    just_before_midnight = datetime(2026, 6, 9, 5, 59, tzinfo=timezone.utc)

    assert current_app_date(just_before_midnight) == date(2026, 6, 8)


def test_current_app_date_rolls_over_at_denver_midnight():
    midnight = datetime(2026, 6, 9, 6, 0, tzinfo=timezone.utc)

    assert current_app_date(midnight) == date(2026, 6, 9)


def test_current_app_date_accepts_a_deployment_timezone():
    same_instant = datetime(2026, 6, 9, 4, 30, tzinfo=timezone.utc)

    assert current_app_date(same_instant, "America/New_York") == date(2026, 6, 9)
    assert current_app_date(same_instant, "America/Denver") == date(2026, 6, 8)
