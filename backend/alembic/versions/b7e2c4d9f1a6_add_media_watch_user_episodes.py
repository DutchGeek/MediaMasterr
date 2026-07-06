"""Add per-user episode watch snapshots.

Revision ID: b7e2c4d9f1a6
Revises: a6f1d3c8e2b4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2c4d9f1a6"
down_revision: str | Sequence[str] | None = "a6f1d3c8e2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_watch_user_episodes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("series_tmdb_id", sa.Integer(), nullable=False),
        sa.Column("season_number", sa.SmallInteger(), nullable=False),
        sa.Column("episode_number", sa.Integer(), nullable=False),
        sa.Column("watch_user_key", sa.String(length=255), nullable=False),
        sa.Column("watch_user_key_normalized", sa.String(length=255), nullable=False),
        sa.Column(
            "source_service",
            sa.Enum(
                "SONARR",
                "RADARR",
                "JELLYFIN",
                "EMBY",
                "PLEX",
                "SEERR",
                "TAUTULLI",
                "MDBLIST",
                "OMDB",
                name="service",
            ),
            nullable=False,
        ),
        sa.Column("source_service_config_id", sa.Integer(), nullable=False),
        sa.Column("last_watched_at", sa.DateTime(), nullable=False),
        sa.Column("play_count", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_service_config_id"], ["service_configs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "series_tmdb_id",
            "season_number",
            "episode_number",
            "watch_user_key_normalized",
            "source_service",
            "source_service_config_id",
            name="uq_media_watch_user_episode_identity",
        ),
    )
    for column in (
        "series_tmdb_id",
        "season_number",
        "episode_number",
        "watch_user_key_normalized",
        "source_service",
        "source_service_config_id",
        "last_watched_at",
    ):
        op.create_index(
            f"ix_media_watch_user_episodes_{column}",
            "media_watch_user_episodes",
            [column],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("media_watch_user_episodes")
