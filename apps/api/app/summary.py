"""Comparable source-time windows for dashboard captions."""
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .history import uncovered_ranges
from .schemas import StatSummary


def build_summary(timestamps: list[datetime], now: datetime, zone: ZoneInfo, covered) -> StatSummary:
    now = now.astimezone(UTC)
    local = now.astimezone(zone)
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    yesterday_local = (local - timedelta(days=1)).replace(fold=0)
    yesterday_end = yesterday_local.astimezone(UTC)
    # A skipped spring clock time has no comparable instant on the previous day.
    comparable_clock = yesterday_end.astimezone(zone).replace(tzinfo=None) == yesterday_local.replace(tzinfo=None)
    day = timedelta(days=1)

    def count(start, end=now, *, include_end=True):
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        return sum(start <= t and (t <= end if include_end else t < end) for t in timestamps)

    def complete(start, end=now):
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        if start >= end:
            return False
        for left, right in uncovered_ranges(start, end, covered):
            # Allow timestamp rounding, and normal processing lag only at the live edge.
            tolerance = 120 if right == now and left > start else 1
            if (right - left).total_seconds() > tolerance:
                return False
        return True

    last_week = count(now - 7 * day)
    return StatSummary(
        last_hour=count(now - timedelta(hours=1)),
        today=count(today),
        last_24_hours=count(now - day),
        last_7_days=last_week,
        yesterday_so_far=(count(yesterday, yesterday_end)
                          if comparable_clock and complete(today) and complete(yesterday, yesterday_end) else None),
        previous_24_hours=(count(now - 2 * day, now - day, include_end=False)
                           if complete(now - 2 * day) else None),
        daily_average=last_week / 7 if complete(now - 7 * day) else None,
    )
