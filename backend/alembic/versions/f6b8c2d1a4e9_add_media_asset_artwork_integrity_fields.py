"""add media asset artwork integrity fields

Revision ID: f6b8c2d1a4e9
Revises: e3b5c7d9a1f2
Create Date: 2026-07-17 16:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "f6b8c2d1a4e9"
down_revision = "e3b5c7d9a1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media_assets") as batch_op:
        batch_op.add_column(sa.Column("banner_url", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("logo_url", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("artwork_source", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("artwork_status", sa.String(length=32), nullable=False, server_default="MISSING")
        )
        batch_op.add_column(
            sa.Column("artwork_confidence", sa.Float(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("artwork_validated_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("artwork_last_refresh_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("artwork_hash", sa.String(length=128), nullable=True))
        batch_op.add_column(
            sa.Column("artwork_diagnostics", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.create_index("ix_media_assets_artwork_status", ["artwork_status"], unique=False)
        batch_op.create_index("ix_media_assets_artwork_hash", ["artwork_hash"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("media_assets") as batch_op:
        batch_op.drop_index("ix_media_assets_artwork_hash")
        batch_op.drop_index("ix_media_assets_artwork_status")
        batch_op.drop_column("artwork_diagnostics")
        batch_op.drop_column("artwork_hash")
        batch_op.drop_column("artwork_last_refresh_at")
        batch_op.drop_column("artwork_validated_at")
        batch_op.drop_column("artwork_confidence")
        batch_op.drop_column("artwork_status")
        batch_op.drop_column("artwork_source")
        batch_op.drop_column("logo_url")
        batch_op.drop_column("banner_url")
