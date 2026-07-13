"""add mie foundation tables

Revision ID: d1a4b9c7e8f0
Revises: c3f7a2b1d9e0
Create Date: 2026-07-13 17:35:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d1a4b9c7e8f0"
down_revision = "c3f7a2b1d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "filesystem_roots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("media_type", sa.String(length=6), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path"),
    )
    op.create_index(op.f("ix_filesystem_roots_media_type"), "filesystem_roots", ["media_type"], unique=False)

    op.create_table(
        "mie_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filesystem_access_mode", sa.String(length=32), nullable=False, server_default="assisted"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "media_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=6), nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=True),
        sa.Column("series_id", sa.Integer(), nullable=True),
        sa.Column("lifecycle_state", sa.String(length=64), nullable=False, server_default="imported"),
        sa.Column("health_state", sa.String(length=32), nullable=False, server_default="healthy"),
        sa.Column("has_torrent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("has_filesystem_objects", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_protected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recommendation", sa.String(length=255), nullable=True),
        sa.Column("last_indexed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_type", "movie_id", name="uq_media_assets_movie"),
        sa.UniqueConstraint("media_type", "series_id", name="uq_media_assets_series"),
    )
    op.create_index(op.f("ix_media_assets_media_type"), "media_assets", ["media_type"], unique=False)
    op.create_index(op.f("ix_media_assets_movie_id"), "media_assets", ["movie_id"], unique=False)
    op.create_index(op.f("ix_media_assets_series_id"), "media_assets", ["series_id"], unique=False)
    op.create_index(op.f("ix_media_assets_lifecycle_state"), "media_assets", ["lifecycle_state"], unique=False)

    op.create_table(
        "filesystem_index_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("root_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.Column("entry_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("modified_at", sa.DateTime(), nullable=True),
        sa.Column("fingerprint", sa.String(length=128), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("indexed_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["root_id"], ["filesystem_roots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_filesystem_index_entries_root_id"), "filesystem_index_entries", ["root_id"], unique=False)
    op.create_index(op.f("ix_filesystem_index_entries_path"), "filesystem_index_entries", ["path"], unique=False)
    op.create_index(op.f("ix_filesystem_index_entries_entry_type"), "filesystem_index_entries", ["entry_type"], unique=False)
    op.create_index(op.f("ix_filesystem_index_entries_fingerprint"), "filesystem_index_entries", ["fingerprint"], unique=False)

    op.create_table(
        "cleanup_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("operation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_recovery_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("safe_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_required_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("executed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cleanup_plans_status"), "cleanup_plans", ["status"], unique=False)

    op.create_table(
        "cleanup_plan_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cleanup_plan_id", sa.Integer(), nullable=False),
        sa.Column("card_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("action", sa.String(length=120), nullable=False, server_default="review"),
        sa.Column("safety_level", sa.String(length=32), nullable=False, server_default="safe"),
        sa.Column("target_type", sa.String(length=64), nullable=False, server_default="unknown"),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        sa.Column("target_path", sa.String(length=2048), nullable=True),
        sa.Column("estimated_recovery_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["cleanup_plan_id"], ["cleanup_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cleanup_plan_items_cleanup_plan_id"), "cleanup_plan_items", ["cleanup_plan_id"], unique=False)
    op.create_index(op.f("ix_cleanup_plan_items_card_key"), "cleanup_plan_items", ["card_key"], unique=False)

    op.create_table(
        "operation_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False, server_default="unknown"),
        sa.Column("target_id", sa.String(length=128), nullable=True),
        sa.Column("target_path", sa.String(length=2048), nullable=True),
        sa.Column("result", sa.String(length=32), nullable=False, server_default="success"),
        sa.Column("safety_level", sa.String(length=32), nullable=False, server_default="safe"),
        sa.Column("recovery_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_operation_history_action"), "operation_history", ["action"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_operation_history_action"), table_name="operation_history")
    op.drop_table("operation_history")

    op.drop_index(op.f("ix_cleanup_plan_items_card_key"), table_name="cleanup_plan_items")
    op.drop_index(op.f("ix_cleanup_plan_items_cleanup_plan_id"), table_name="cleanup_plan_items")
    op.drop_table("cleanup_plan_items")

    op.drop_index(op.f("ix_cleanup_plans_status"), table_name="cleanup_plans")
    op.drop_table("cleanup_plans")

    op.drop_index(op.f("ix_filesystem_index_entries_fingerprint"), table_name="filesystem_index_entries")
    op.drop_index(op.f("ix_filesystem_index_entries_entry_type"), table_name="filesystem_index_entries")
    op.drop_index(op.f("ix_filesystem_index_entries_path"), table_name="filesystem_index_entries")
    op.drop_index(op.f("ix_filesystem_index_entries_root_id"), table_name="filesystem_index_entries")
    op.drop_table("filesystem_index_entries")

    op.drop_index(op.f("ix_media_assets_lifecycle_state"), table_name="media_assets")
    op.drop_index(op.f("ix_media_assets_series_id"), table_name="media_assets")
    op.drop_index(op.f("ix_media_assets_movie_id"), table_name="media_assets")
    op.drop_index(op.f("ix_media_assets_media_type"), table_name="media_assets")
    op.drop_table("media_assets")

    op.drop_table("mie_settings")

    op.drop_index(op.f("ix_filesystem_roots_media_type"), table_name="filesystem_roots")
    op.drop_table("filesystem_roots")
