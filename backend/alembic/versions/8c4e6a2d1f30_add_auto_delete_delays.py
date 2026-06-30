"""add auto-delete review periods

Revision ID: 8c4e6a2d1f30
Revises: 7b3d5f9a1c2e
Create Date: 2026-06-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8c4e6a2d1f30"
down_revision: str | Sequence[str] | None = "7b3d5f9a1c2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("general_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "auto_delete_movie_delay_days",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("14"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "auto_delete_series_delay_days",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("7"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("general_settings", schema=None) as batch_op:
        batch_op.drop_column("auto_delete_series_delay_days")
        batch_op.drop_column("auto_delete_movie_delay_days")
