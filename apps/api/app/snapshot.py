from __future__ import annotations

import json
from bisect import bisect_right
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from .config import Settings
from .db import SessionLocal
from .models import Occurrence, PipelineState, SourceSession, TranscriptSegment
from .schemas import (
    DashboardResponse,
    FormCount,
    OccurrenceDto,
    OccurrencePage,
    StatBucket,
    StatRange,
    StatsResponse,
    StatSummary,
    StatusResponse,
)

RANGES = (0, 1, 7, 30)  # 0 denotes the last hour, with minute buckets.
PAGE_SIZE = 30


def range_duration(days: int) -> timedelta:
    return timedelta(hours=1) if days == 0 else timedelta(days=days)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class Snapshot:
    generated_at: datetime
    dashboards: Mapping[int, bytes]
    stats: Mapping[int, bytes]
    status: bytes
    occurrences: Mapping[int, tuple[OccurrenceDto, ...]]
    positions: Mapping[int, Mapping[int, int]]

    def page(self, days: int, cursor: int | None = None) -> OccurrencePage:
        rows = self.occurrences[days]
        start = self.positions[days][cursor] + 1 if cursor is not None else 0
        items = rows[start : start + PAGE_SIZE]
        return OccurrencePage(
            items=list(items),
            next_cursor=items[-1].id if items and start + PAGE_SIZE < len(rows) else None,
        )

    def bucket_items(self, days: int) -> dict[str, list[OccurrenceDto]]:
        buckets = json.loads(self.stats[days])["buckets"]
        starts = [datetime.fromisoformat(row["start"]).timestamp() for row in buckets]
        groups = {row["start"]: [] for row in buckets}
        for item in self.occurrences[days]:
            index = bisect_right(starts, item.occurred_at.timestamp()) - 1
            if index >= 0:
                groups[buckets[index]["start"]].append(item)
        return groups


def build_snapshot(
    settings: Settings,
    factory=SessionLocal,
    now: datetime | None = None,
) -> Snapshot:
    now = now or datetime.now(UTC)
    zone = ZoneInfo(settings.app_timezone)
    # Read history age separately; chart rows cover only the last 30 days.
    with factory() as db:
        history_dates = [
            db.scalar(select(func.min(Occurrence.occurred_at))),
            db.scalar(select(func.min(TranscriptSegment.started_at))),
        ]
        history_started_at = min((value for value in history_dates if value), default=None)
        rows = db.execute(
            select(
                Occurrence.id,
                Occurrence.occurred_at,
                Occurrence.form,
                Occurrence.quote,
                Occurrence.confidence,
                Occurrence.source_position_seconds,
                SourceSession.source_url,
            )
            .join(SourceSession, Occurrence.source_session_id == SourceSession.id)
            .where(
                Occurrence.occurred_at >= now - timedelta(days=30),
                Occurrence.occurred_at <= now,
            )
            .order_by(Occurrence.occurred_at.desc(), Occurrence.id.desc())
        ).all()
        items = tuple(
            OccurrenceDto(
                id=row.id,
                occurred_at=aware(row.occurred_at),
                form=row.form,
                quote=row.quote,
                confidence=row.confidence,
                source_url=row.source_url,
                source_position_seconds=row.source_position_seconds,
            )
            for row in rows
        )
        state = db.get(PipelineState, 1)
        status = StatusResponse(
            state=state.state if state else "offline",
            last_audio_at=aware(state.last_audio_at) if state and state.last_audio_at else None,
            last_transcript_at=(
                aware(state.last_transcript_at) if state and state.last_transcript_at else None
            ),
            lag_seconds=state.lag_seconds if state else None,
            reconnect_count=state.reconnect_count if state else 0,
            message=None,  # Do not publish internal errors in the public CDN cache.
            model_name=state.model_name if state else None,
            updated_at=aware(state.updated_at) if state else now,
        )
    if status.state == "live" and (
        status.last_audio_at is None or now - status.last_audio_at > timedelta(seconds=120)
    ):
        status.state = "offline"
    today = now.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    summary = StatSummary(
        last_hour=sum(item.occurred_at >= now - timedelta(hours=1) for item in items),
        today=sum(item.occurred_at >= today for item in items),
        last_24_hours=sum(item.occurred_at >= now - timedelta(days=1) for item in items),
        last_7_days=sum(item.occurred_at >= now - timedelta(days=7) for item in items),
    )
    dashboards: dict[int, bytes] = {}
    stats: dict[int, bytes] = {}
    occurrences = {
        days: tuple(item for item in items if item.occurred_at >= now - range_duration(days))
        for days in RANGES
    }
    snapshot = Snapshot(
        generated_at=now,
        dashboards=MappingProxyType(dashboards),
        stats=MappingProxyType(stats),
        status=status.model_dump_json(by_alias=True).encode(),
        occurrences=MappingProxyType(occurrences),
        positions=MappingProxyType(
            {
                days: {item.id: index for index, item in enumerate(selected)}
                for days, selected in occurrences.items()
            }
        ),
    )
    for days, selected in occurrences.items():
        # UTC keys distinguish repeated hours at the autumn DST transition.
        buckets: Counter[datetime] = Counter()
        if days == 0:
            minute = (now - timedelta(hours=1)).replace(second=0, microsecond=0)
            while minute <= now:
                buckets[minute] = 0
                minute += timedelta(minutes=1)
        forms = Counter(item.form for item in selected)
        for item in selected:
            local = item.occurred_at.astimezone(zone)
            floor = local.replace(second=0, microsecond=0)
            if days != 0:
                floor = floor.replace(minute=0)
            if days > 1:
                floor = floor.replace(hour=0, fold=0)
            buckets[floor.astimezone(UTC)] += 1
        response = StatsResponse(
            history_started_at=aware(history_started_at) if history_started_at else None,
            summary=summary,
            range=StatRange(from_=now - range_duration(days), to=now, total=len(selected)),
            buckets=[
                StatBucket(
                    start=start,
                    count=count,
                    end=(
                        start + timedelta(minutes=1)
                        if days == 0
                        else start + timedelta(hours=1)
                        if days == 1
                        else (start.astimezone(zone) + timedelta(days=1)).astimezone(UTC)
                    ),
                )
                for start, count in sorted(buckets.items())
            ],
            forms=[FormCount(form=form, count=count) for form, count in forms.most_common()],
        )
        stats[days] = response.model_dump_json(by_alias=True).encode()
        dashboards[days] = (
            DashboardResponse(
                generated_at=now, stats=response, status=status, occurrences=snapshot.page(days)
            )
            .model_dump_json(by_alias=True)
            .encode()
        )
    return snapshot
