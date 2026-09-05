"""Initial Tuskometr schema.

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "pipeline_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("last_audio_at", sa.DateTime(timezone=True)),
        sa.Column("last_transcript_at", sa.DateTime(timezone=True)),
        sa.Column("lag_seconds", sa.Float()),
        sa.Column("reconnect_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("model_name", sa.String(length=128)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_session_id", sa.Integer(), sa.ForeignKey("source_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_sample", sa.Integer(), nullable=False),
        sa.Column("end_sample", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("average_confidence", sa.Float(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_session_id", "start_sample", "end_sample", name="uq_segment_samples"),
    )
    op.create_index("ix_transcript_segments_started_at", "transcript_segments", ["started_at"])
    op.create_index("ix_transcript_segments_expires_at", "transcript_segments", ["expires_at"])
    op.create_table(
        "occurrences",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_session_id", sa.Integer(), sa.ForeignKey("source_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_id", sa.Integer(), sa.ForeignKey("transcript_segments.id", ondelete="SET NULL")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_sample", sa.Integer(), nullable=False),
        sa.Column("form", sa.String(length=32), nullable=False),
        sa.Column("normalized_form", sa.String(length=32), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_position_seconds", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_occurrences_occurred_at", "occurrences", ["occurred_at"])
    op.create_index("ix_occurrences_form", "occurrences", ["normalized_form"])
    op.create_index("ix_occurrences_session_sample", "occurrences", ["source_session_id", "source_sample"])
    op.execute(
        "INSERT INTO pipeline_state (id, state, reconnect_count, updated_at) "
        "VALUES (1, 'offline', 0, CURRENT_TIMESTAMP)"
    )


def downgrade() -> None:
    op.drop_table("occurrences")
    op.drop_table("transcript_segments")
    op.drop_table("pipeline_state")
    op.drop_table("source_sessions")

