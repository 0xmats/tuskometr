from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .config import Settings
from .db import SessionLocal
from .models import Occurrence, PipelineState, SourceSession
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

RANGES = (1, 7, 30)
PAGE_SIZE = 30


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class Snapshot:
    generated_at: datetime
    dashboards: Mapping[int, bytes]
    stats: Mapping[int, bytes]
    status: bytes
    occurrences: Mapping[int, tuple[OccurrenceDto, ...]]
    negative_ids: Mapping[int, tuple[int, ...]]

    def page(self, days: int, cursor: int | None = None) -> OccurrencePage:
        rows = self.occurrences[days]
        start = bisect_right(self.negative_ids[days], -cursor) if cursor is not None else 0
        items = rows[start : start + PAGE_SIZE]
        return OccurrencePage(
            items=list(items),
            next_cursor=items[-1].id if items and start + PAGE_SIZE < len(rows) else None,
        )


def build_snapshot(
    settings: Settings,
    factory=SessionLocal,
    now: datetime | None = None,
) -> Snapshot:
    now = now or datetime.now(UTC)
    zone = ZoneInfo(settings.app_timezone)
    # Two reads per refresh, independent of visitors; only the last 30 days.
    with factory() as db:
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
            .order_by(Occurrence.id.desc())
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
        today=sum(item.occurred_at >= today for item in items),
        last_24_hours=sum(item.occurred_at >= now - timedelta(days=1) for item in items),
        last_7_days=sum(item.occurred_at >= now - timedelta(days=7) for item in items),
    )
    dashboards: dict[int, bytes] = {}
    stats: dict[int, bytes] = {}
    occurrences = {
        days: tuple(item for item in items if item.occurred_at >= now - timedelta(days=days))
        for days in RANGES
    }
    snapshot = Snapshot(
        generated_at=now,
        dashboards=MappingProxyType(dashboards),
        stats=MappingProxyType(stats),
        status=status.model_dump_json(by_alias=True).encode(),
        occurrences=MappingProxyType(occurrences),
        negative_ids=MappingProxyType(
            {days: tuple(-item.id for item in selected) for days, selected in occurrences.items()}
        ),
    )
    for days, selected in occurrences.items():
        # UTC keys distinguish repeated hours at the autumn DST transition.
        buckets: Counter[datetime] = Counter()
        forms = Counter(item.form for item in selected)
        for item in selected:
            local = item.occurred_at.astimezone(zone)
            floor = local.replace(minute=0, second=0, microsecond=0)
            if days != 1:
                floor = floor.replace(hour=0, fold=0)
            buckets[floor.astimezone(UTC)] += 1
        response = StatsResponse(
            summary=summary,
            range=StatRange(from_=now - timedelta(days=days), to=now, total=len(selected)),
            buckets=[
                StatBucket(start=start, count=count) for start, count in sorted(buckets.items())
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
