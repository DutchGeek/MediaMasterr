"""add updated_by_user_id to query_filters

Revision ID: c3f7a2b1d9e0
Revises: b9d3f1a6e2c4
Create Date: 2026-07-13 11:50:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f7a2b1d9e0"
down_revision: str | None = "b9d3f1a6e2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "query_filters",
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_query_filters_updated_by_user_id"),
        "query_filters",
        ["updated_by_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_query_filters_updated_by_user_id"),
        table_name="query_filters",
    )
    op.drop_column("query_filters", "updated_by_user_id")
