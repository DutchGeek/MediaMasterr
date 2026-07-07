"""Add provider-native completion state to playback events.

Revision ID: c8f3a1d6e2b9
Revises: b7e2c4d9f1a6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8f3a1d6e2b9"
down_revision: str | Sequence[str] | None = "b7e2c4d9f1a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("playback_history_events") as batch_op:
        batch_op.add_column(sa.Column("completed", sa.Boolean(), nullable=True))
        batch_op.create_index(
            "ix_playback_history_events_completed", ["completed"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("playback_history_events") as batch_op:
        batch_op.drop_index("ix_playback_history_events_completed")
        batch_op.drop_column("completed")
