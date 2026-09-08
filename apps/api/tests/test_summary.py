from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.summary import build_summary

ZONE = ZoneInfo('Europe/Warsaw')
NOW = datetime(2026, 9, 8, 10, tzinfo=UTC)


def summary(times=(), covered=None, now=NOW):
    if covered is None:
        covered = [(now - timedelta(days=8), now)]
    return build_summary(list(times), now, ZONE, covered)


def test_same_time_yesterday_and_disjoint_24_hour_windows():
    times = [
        datetime(2026, 9, 6, 23, tzinfo=UTC),  # yesterday, before noon
        datetime(2026, 9, 7, 10, tzinfo=UTC),  # exact 24h boundary
        datetime(2026, 9, 7, 11, tzinfo=UTC),  # yesterday, after noon
        datetime(2026, 9, 7, 23, tzinfo=UTC),  # today in Warsaw
    ]
    result = summary(times)
    assert result.today == 1
    assert result.yesterday_so_far == 2
    assert result.last_24_hours == 3
    assert result.previous_24_hours == 1
    assert result.daily_average == 4 / 7


def test_short_history_and_internal_gaps_hide_captions():
    result = summary(covered=[(NOW - timedelta(hours=30), NOW)])
    assert result.yesterday_so_far is None
    assert result.previous_24_hours is None
    assert result.daily_average is None
    result = summary(covered=[
        (NOW - timedelta(days=8), NOW - timedelta(hours=4)),
        (NOW - timedelta(hours=3), NOW),
    ])
    assert result.yesterday_so_far is None
    assert result.previous_24_hours is None
    assert result.daily_average is None


def test_processing_lag_allowed_but_outage_and_missing_coverage_hidden():
    result = summary(covered=[(NOW - timedelta(days=8), NOW - timedelta(seconds=60))])
    assert result.previous_24_hours == 0
    assert result.daily_average == 0
    for covered in [[], [(NOW - timedelta(days=8), NOW - timedelta(minutes=5))]]:
        assert summary(covered=covered).previous_24_hours is None


def test_average_hides_gaps_before_available_coverage():
    result = summary(covered=[(NOW - timedelta(days=6), NOW)])
    assert result.previous_24_hours == 0
    assert result.daily_average is None


def test_average_uses_actual_elapsed_history_including_partial_days():
    start = NOW - timedelta(days=2, hours=12)
    result = build_summary([NOW] * 1250, NOW, ZONE, [(start, NOW)], start)
    assert result.daily_average == 500
    assert result.last_7_days == 1250


def test_average_remains_a_rolling_week_with_longer_history():
    start = NOW - timedelta(days=10)
    result = build_summary([NOW] * 700, NOW, ZONE, [(start, NOW)], start)
    assert result.daily_average == 100


def test_partial_history_average_still_requires_coverage_and_one_day():
    start = NOW - timedelta(days=3)
    result = build_summary([NOW], NOW, ZONE, [(start + timedelta(hours=1), NOW)], start)
    assert result.daily_average is None
    start = NOW - timedelta(hours=12)
    result = build_summary([NOW], NOW, ZONE, [(start, NOW)], start)
    assert result.daily_average is None


def test_yesterday_uses_local_wall_clock_across_dst():
    for now in [datetime(2026, 3, 29, 10, tzinfo=UTC), datetime(2026, 10, 25, 11, tzinfo=UTC)]:
        local = now.astimezone(ZONE)
        yesterday_noon = (local - timedelta(days=1)).astimezone(UTC)
        result = summary([yesterday_noon, yesterday_noon + timedelta(minutes=1)], now=now)
        assert result.yesterday_so_far == 1


def test_midnight_has_no_elapsed_day_to_compare():
    now = datetime(2026, 9, 7, 22, tzinfo=UTC)
    assert summary(now=now).yesterday_so_far is None


def test_missing_yesterday_clock_time_hides_comparison():
    now = datetime(2026, 3, 30, 0, 30, tzinfo=UTC)
    assert summary(now=now).yesterday_so_far is None
