from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class SourceSession(Base):
    __tablename__ = "source_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="starting")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    segments: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="source_session", cascade="all, delete-orphan"
    )
    occurrences: Mapped[list[Occurrence]] = relationship(
        back_populates="source_session", cascade="all, delete-orphan"
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (
        UniqueConstraint(
            "source_session_id", "start_sample", "end_sample", name="uq_segment_samples"
        ),
        Index("ix_transcript_segments_started_at", "started_at"),
        Index("ix_transcript_segments_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_session_id: Mapped[int] = mapped_column(
        ForeignKey("source_sessions.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_sample: Mapped[int] = mapped_column(Integer, nullable=False)
    end_sample: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    average_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    source_session: Mapped[SourceSession] = relationship(back_populates="segments")
    occurrences: Mapped[list[Occurrence]] = relationship(back_populates="segment")


class Occurrence(Base):
    __tablename__ = "occurrences"
    __table_args__ = (
        Index("ix_occurrences_occurred_at", "occurred_at"),
        Index("ix_occurrences_form", "normalized_form"),
        Index("ix_occurrences_session_sample", "source_session_id", "source_sample"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_session_id: Mapped[int] = mapped_column(
        ForeignKey("source_sessions.id", ondelete="CASCADE"), nullable=False
    )
    segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("transcript_segments.id", ondelete="SET NULL")
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_sample: Mapped[int] = mapped_column(Integer, nullable=False)
    form: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_form: Mapped[str] = mapped_column(String(32), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source_position_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    source_session: Mapped[SourceSession] = relationship(back_populates="occurrences")
    segment: Mapped[TranscriptSegment | None] = relationship(back_populates="occurrences")


class PipelineState(Base):
    __tablename__ = "pipeline_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="offline")
    last_audio_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_transcript_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lag_seconds: Mapped[float | None] = mapped_column(Float)
    reconnect_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
