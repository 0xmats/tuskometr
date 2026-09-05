from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class OccurrenceDto(ApiModel):
    id: int
    occurred_at: datetime = Field(serialization_alias="occurredAt")
    form: str
    quote: str
    confidence: float
    source_url: str = Field(serialization_alias="sourceUrl")
    source_position_seconds: float | None = Field(
        default=None, serialization_alias="sourcePositionSeconds"
    )


class OccurrencePage(ApiModel):
    items: list[OccurrenceDto]
    next_cursor: int | None = Field(default=None, serialization_alias="nextCursor")


class StatSummary(ApiModel):
    today: int
    last_24_hours: int = Field(serialization_alias="last24Hours")
    last_7_days: int = Field(serialization_alias="last7Days")


class StatRange(ApiModel):
    from_: datetime = Field(serialization_alias="from")
    to: datetime
    total: int


class StatBucket(ApiModel):
    start: datetime
    count: int


class FormCount(ApiModel):
    form: str
    count: int


class StatsResponse(ApiModel):
    summary: StatSummary
    range: StatRange
    buckets: list[StatBucket]
    forms: list[FormCount]


class StatusResponse(ApiModel):
    state: str
    last_audio_at: datetime | None = Field(default=None, serialization_alias="lastAudioAt")
    last_transcript_at: datetime | None = Field(
        default=None, serialization_alias="lastTranscriptAt"
    )
    lag_seconds: float | None = Field(default=None, serialization_alias="lagSeconds")
    reconnect_count: int = Field(serialization_alias="reconnectCount")
    message: str | None = None
    model_name: str | None = Field(default=None, serialization_alias="modelName")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class DashboardResponse(ApiModel):
    generated_at: datetime = Field(serialization_alias="generatedAt")
    stats: StatsResponse
    status: StatusResponse
    occurrences: OccurrencePage
