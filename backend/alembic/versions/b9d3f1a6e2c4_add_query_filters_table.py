"""add query_filters table

Revision ID: b9d3f1a6e2c4
Revises: a8d4e2c9b7f1
Create Date: 2026-07-13 10:05:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9d3f1a6e2c4"
down_revision: str | None = "a8d4e2c9b7f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SERVICE_ENUM = sa.Enum(
    "JELLYFIN",
    "EMBY",
    "PLEX",
    "RADARR",
    "SONARR",
    "SEERR",
    "QBITTORRENT",
    "TAUTULLI",
    "ANILIST",
    "IMDB",
    "MDBLIST",
    "OMDB",
    name="service",
)

MEDIA_TYPE_ENUM = sa.Enum("MOVIE", "SERIES", name="media_type")


def upgrade() -> None:
    bind = op.get_bind()
    SERVICE_ENUM.create(bind, checkfirst=True)
    MEDIA_TYPE_ENUM.create(bind, checkfirst=True)

    op.create_table(
        "query_filters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="decision"),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("media_type", MEDIA_TYPE_ENUM, nullable=True),
        sa.Column("read_only", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_service", SERVICE_ENUM, nullable=True),
        sa.Column("provider_config_id", sa.Integer(), nullable=True),
        sa.Column("provider_filter_id", sa.String(length=128), nullable=True),
        sa.Column("definition", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["provider_config_id"], ["service_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_service",
            "provider_config_id",
            "provider_filter_id",
            name="uq_query_filters_provider_key",
        ),
    )
    op.create_index(op.f("ix_query_filters_kind"), "query_filters", ["kind"], unique=False)
    op.create_index(op.f("ix_query_filters_user_id"), "query_filters", ["user_id"], unique=False)
    op.create_index(op.f("ix_query_filters_media_type"), "query_filters", ["media_type"], unique=False)
    op.create_index(op.f("ix_query_filters_provider_service"), "query_filters", ["provider_service"], unique=False)
    op.create_index(op.f("ix_query_filters_provider_config_id"), "query_filters", ["provider_config_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_query_filters_provider_config_id"), table_name="query_filters")
    op.drop_index(op.f("ix_query_filters_provider_service"), table_name="query_filters")
    op.drop_index(op.f("ix_query_filters_media_type"), table_name="query_filters")
    op.drop_index(op.f("ix_query_filters_user_id"), table_name="query_filters")
    op.drop_index(op.f("ix_query_filters_kind"), table_name="query_filters")
    op.drop_table("query_filters")
