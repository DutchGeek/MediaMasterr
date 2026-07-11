"""add protection provider auth/session columns

Revision ID: a8d4e2c9b7f1
Revises: f4c6e8a1b3d5
Create Date: 2026-07-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "a8d4e2c9b7f1"
down_revision: str | Sequence[str] | None = "f4c6e8a1b3d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("protection_provider_configs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "auth_method",
                sa.String(length=64),
                nullable=False,
                server_default="web_login",
            )
        )
        batch_op.add_column(sa.Column("username", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("password", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("session_token", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("authenticated", sa.Boolean(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(sa.Column("provider_version", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("last_login_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("protection_provider_configs", schema=None) as batch_op:
        batch_op.drop_column("last_login_at")
        batch_op.drop_column("provider_version")
        batch_op.drop_column("authenticated")
        batch_op.drop_column("session_token")
        batch_op.drop_column("password")
        batch_op.drop_column("username")
        batch_op.drop_column("auth_method")
