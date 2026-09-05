"""Remove the misleading permanent broadcast start timestamp.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("source_sessions", "stream_started_at")


def downgrade() -> None:
    op.add_column(
        "source_sessions",
        sa.Column("stream_started_at", sa.DateTime(timezone=True), nullable=True),
    )
