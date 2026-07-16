"""add media asset artwork columns

Revision ID: e3b5c7d9a1f2
Revises: d1a4b9c7e8f0
Create Date: 2026-07-16 11:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e3b5c7d9a1f2"
down_revision = "d1a4b9c7e8f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media_assets") as batch_op:
        batch_op.add_column(sa.Column("poster_url", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("backdrop_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("media_assets") as batch_op:
        batch_op.drop_column("backdrop_url")
        batch_op.drop_column("poster_url")
