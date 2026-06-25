"""add rule managed protections

Revision ID: d6e7f8a9b0c1
Revises: c4d5e6f7a8b9
Create Date: 2026-06-20 00:00:00.000000
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "d6e7f8a9b0c1"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("protected_media", schema=None) as batch_op:
        batch_op.alter_column(
            "protected_by_user_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column(
                "source",
                sa.String(length=16),
                nullable=False,
                server_default="manual",
            )
        )
        batch_op.add_column(sa.Column("source_rule_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            "ix_protected_media_source_rule_id",
            ["source_rule_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_protected_media_source_rule_id_reclaim_rules",
            "reclaim_rules",
            ["source_rule_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM protected_media WHERE source = 'rule'"))
    with op.batch_alter_table("protected_media", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_protected_media_source_rule_id_reclaim_rules",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_protected_media_source_rule_id")
        batch_op.drop_column("source_rule_id")
        batch_op.drop_column("source")
        batch_op.alter_column(
            "protected_by_user_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
