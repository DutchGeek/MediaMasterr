"""Add qBittorrent to service enum.

Revision ID: f2c4b6d8e0a1
Revises: e2b7c9d4a1f8
Create Date: 2026-07-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f2c4b6d8e0a1"
down_revision: str | Sequence[str] | None = "e2b7c9d4a1f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_SERVICE = sa.Enum(
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
)

_NEW_SERVICE = sa.Enum(
    "SONARR",
    "RADARR",
    "QBITTORRENT",
    "JELLYFIN",
    "EMBY",
    "PLEX",
    "SEERR",
    "TAUTULLI",
    "MDBLIST",
    "OMDB",
    name="service",
)

_SERVICE_COLUMNS = (
    ("service_configs", "service_type", False),
    ("media_user_identities", "source_service", False),
    ("movie_versions", "service", False),
    ("series_service_refs", "service", False),
    ("supplemental_media_matches", "source_service", False),
    ("media_favorites", "source_service", False),
    ("media_watch_users", "source_service", False),
    ("playback_history_events", "source_service", False),
)


def _cols(table: str) -> set[str]:
    bind = op.get_bind()
    return {row[1] for row in bind.execute(sa.text(f"PRAGMA table_info({table})"))}


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table},
    ).first()
    return result is not None


def _alter_service_enum(existing_type: sa.Enum, new_type: sa.Enum) -> None:
    for table, column, nullable in _SERVICE_COLUMNS:
        if _table_exists(table) and column in _cols(table):
            with op.batch_alter_table(table, schema=None) as batch_op:
                batch_op.alter_column(
                    column,
                    existing_type=existing_type,
                    type_=new_type,
                    existing_nullable=nullable,
                )


def upgrade() -> None:
    _alter_service_enum(_OLD_SERVICE, _NEW_SERVICE)


def downgrade() -> None:
    _alter_service_enum(_NEW_SERVICE, _OLD_SERVICE)
