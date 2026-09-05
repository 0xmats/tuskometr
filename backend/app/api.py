from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from .config import get_settings
from .db import SessionLocal, get_db
from .models import Occurrence, PipelineState
from .schemas import (
    FormCount,
    OccurrenceDto,
    OccurrencePage,
    StatBucket,
    StatRange,
    StatsResponse,
    StatSummary,
    StatusResponse,
)

router = APIRouter(prefix="/api")


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def occurrence_to_dto(row: Occurrence) -> OccurrenceDto:
    return OccurrenceDto(
        id=row.id,
        occurred_at=ensure_aware(row.occurred_at),
        form=row.form,
        quote=row.quote,
        confidence=row.confidence,
        source_url=row.source_session.source_url,
        source_position_seconds=row.source_position_seconds,
    )


def state_to_dto(state: PipelineState) -> StatusResponse:
    return StatusResponse(
        state=state.state,
        last_audio_at=ensure_aware(state.last_audio_at) if state.last_audio_at else None,
        last_transcript_at=(
            ensure_aware(state.last_transcript_at) if state.last_transcript_at else None
        ),
        lag_seconds=state.lag_seconds,
        reconnect_count=state.reconnect_count,
        message=state.last_error,
        model_name=state.model_name,
        updated_at=ensure_aware(state.updated_at),
    )


@router.get("/occurrences", response_model=OccurrencePage, response_model_by_alias=True)
def list_occurrences(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=30, ge=1, le=100),
    form: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> OccurrencePage:
    query = (
        select(Occurrence)
        .options(joinedload(Occurrence.source_session))
        .order_by(Occurrence.id.desc())
        .limit(limit + 1)
    )
    if from_:
        query = query.where(Occurrence.occurred_at >= ensure_aware(from_))
    if to:
        query = query.where(Occurrence.occurred_at <= ensure_aware(to))
    if cursor:
        query = query.where(Occurrence.id < cursor)
    if form:
        query = query.where(Occurrence.normalized_form == form.casefold())

    rows = list(db.scalars(query).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return OccurrencePage(
        items=[occurrence_to_dto(row) for row in rows],
        next_cursor=rows[-1].id if has_more and rows else None,
    )


def _floor_bucket(value: datetime, bucket: str, zone: ZoneInfo) -> datetime:
    local = ensure_aware(value).astimezone(zone)
    if bucket == "day":
        local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        local = local.replace(minute=0, second=0, microsecond=0)
    return local


@router.get("/stats", response_model=StatsResponse, response_model_by_alias=True)
def get_stats(
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    bucket: str = Query(default="hour", pattern="^(hour|day)$"),
    db: Session = Depends(get_db),
) -> StatsResponse:
    settings = get_settings()
    zone = ZoneInfo(settings.app_timezone)
    now = datetime.now(UTC)
    range_to = ensure_aware(to) if to else now
    range_from = ensure_aware(from_) if from_ else range_to - timedelta(days=7)
    if range_from >= range_to:
        raise HTTPException(status_code=422, detail="Parametr from musi być wcześniejszy niż to")
    if range_to - range_from > timedelta(days=366):
        raise HTTPException(status_code=422, detail="Maksymalny zakres wynosi 366 dni")

    rows = db.scalars(
        select(Occurrence)
        .where(Occurrence.occurred_at >= range_from, Occurrence.occurred_at <= range_to)
        .order_by(Occurrence.occurred_at)
    ).all()
    grouped: dict[datetime, int] = defaultdict(int)
    forms: Counter[str] = Counter()
    for row in rows:
        grouped[_floor_bucket(row.occurred_at, bucket, zone)] += 1
        forms[row.form] += 1

    local_now = now.astimezone(zone)
    today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    summary_counts = {
        "today": db.scalar(
            select(func.count(Occurrence.id)).where(Occurrence.occurred_at >= today_start)
        )
        or 0,
        "last24": db.scalar(
            select(func.count(Occurrence.id)).where(
                Occurrence.occurred_at >= now - timedelta(hours=24)
            )
        )
        or 0,
        "last7": db.scalar(
            select(func.count(Occurrence.id)).where(
                Occurrence.occurred_at >= now - timedelta(days=7)
            )
        )
        or 0,
    }
    return StatsResponse(
        summary=StatSummary(
            today=summary_counts["today"],
            last_24_hours=summary_counts["last24"],
            last_7_days=summary_counts["last7"],
        ),
        range=StatRange(from_=range_from, to=range_to, total=len(rows)),
        buckets=[StatBucket(start=start, count=count) for start, count in sorted(grouped.items())],
        forms=[FormCount(form=form, count=count) for form, count in forms.most_common()],
    )


@router.get("/status", response_model=StatusResponse, response_model_by_alias=True)
def get_status(db: Session = Depends(get_db)) -> StatusResponse:
    state = db.get(PipelineState, 1)
    if state is None:
        raise HTTPException(status_code=503, detail="Pipeline nie został zainicjalizowany")
    return state_to_dto(state)


async def event_stream(request: Request, after_id: int) -> AsyncGenerator[str, None]:
    settings = get_settings()
    last_id = after_id
    status_counter = 0
    while not await request.is_disconnected():
        with SessionLocal() as db:
            rows = db.scalars(
                select(Occurrence)
                .options(joinedload(Occurrence.source_session))
                .where(Occurrence.id > last_id)
                .order_by(Occurrence.id)
                .limit(100)
            ).all()
            for row in rows:
                dto = occurrence_to_dto(row)
                payload = dto.model_dump_json(by_alias=True)
                yield f"id: {row.id}\nevent: occurrence\ndata: {payload}\n\n"
                last_id = row.id

            if status_counter % 5 == 0:
                state = db.get(PipelineState, 1)
                if state:
                    payload = state_to_dto(state).model_dump_json(by_alias=True)
                    yield f"event: status\ndata: {payload}\n\n"
            else:
                yield ": keep-alive\n\n"
        status_counter += 1
        await asyncio.sleep(settings.api_poll_seconds)


@router.get("/events")
async def events(
    request: Request,
    after_id: int | None = Query(default=None, alias="afterId", ge=0),
):
    if after_id is None:
        last_event_id = request.headers.get("last-event-id")
        if last_event_id and last_event_id.isdigit():
            after_id = int(last_event_id)
        else:
            with SessionLocal() as db:
                after_id = db.scalar(select(func.max(Occurrence.id))) or 0
    return StreamingResponse(
        event_stream(request, after_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
