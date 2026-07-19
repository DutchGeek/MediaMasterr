"""add media identity foundation phase1

Revision ID: a1e7c4f9b2d8
Revises: f6b8c2d1a4e9, bc34de56fa78
Create Date: 2026-07-19 11:00:00.000000
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1e7c4f9b2d8"
down_revision: str | Sequence[str] | None = ("f6b8c2d1a4e9", "bc34de56fa78")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=6), nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=True),
        sa.Column("series_id", sa.Integer(), nullable=True),
        sa.Column(
            "canonical_provider",
            sa.String(length=64),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("canonical_title", sa.String(length=255), nullable=True),
        sa.Column("canonical_year", sa.Integer(), nullable=True),
        sa.Column(
            "provider_confidence", sa.SmallInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "identity_confidence", sa.SmallInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "conflict_level",
            sa.String(length=16),
            nullable=False,
            server_default="none",
        ),
        sa.Column(
            "needs_review", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "health_state",
            sa.String(length=32),
            nullable=False,
            server_default="healthy",
        ),
        sa.Column(
            "lifecycle_state",
            sa.String(length=64),
            nullable=False,
            server_default="resolved",
        ),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["series_id"], ["series.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_type", "movie_id", name="uq_media_identities_movie"),
        sa.UniqueConstraint(
            "media_type", "series_id", name="uq_media_identities_series"
        ),
    )
    op.create_index(
        op.f("ix_media_identities_media_type"),
        "media_identities",
        ["media_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_identities_movie_id"),
        "media_identities",
        ["movie_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_identities_series_id"),
        "media_identities",
        ["series_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_identities_canonical_provider"),
        "media_identities",
        ["canonical_provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_identities_health_state"),
        "media_identities",
        ["health_state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_identities_lifecycle_state"),
        "media_identities",
        ["lifecycle_state"],
        unique=False,
    )

    op.create_table(
        "media_identity_provider_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_identity_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_item_id", sa.String(length=128), nullable=False),
        sa.Column("confidence", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column(
            "is_canonical", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("path_tail", sa.String(length=1024), nullable=True),
        sa.Column(
            "connection_status",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["media_identity_id"], ["media_identities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "media_identity_id",
            "provider",
            "provider_item_id",
            name="uq_media_identity_provider_mapping",
        ),
    )
    op.create_index(
        op.f("ix_media_identity_provider_mappings_media_identity_id"),
        "media_identity_provider_mappings",
        ["media_identity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_identity_provider_mappings_provider"),
        "media_identity_provider_mappings",
        ["provider"],
        unique=False,
    )

    op.create_table(
        "media_identity_external_ids",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_identity_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("id_type", sa.String(length=64), nullable=False),
        sa.Column("id_value", sa.String(length=255), nullable=False),
        sa.Column("confidence", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column(
            "is_canonical", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["media_identity_id"], ["media_identities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "media_identity_id",
            "provider",
            "id_type",
            "id_value",
            name="uq_media_identity_external_id",
        ),
    )
    op.create_index(
        op.f("ix_media_identity_external_ids_media_identity_id"),
        "media_identity_external_ids",
        ["media_identity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_identity_external_ids_provider"),
        "media_identity_external_ids",
        ["provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_identity_external_ids_id_type"),
        "media_identity_external_ids",
        ["id_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_identity_external_ids_id_value"),
        "media_identity_external_ids",
        ["id_value"],
        unique=False,
    )

    op.create_table(
        "media_identity_relationships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_identity_id", sa.Integer(), nullable=False),
        sa.Column("target_identity_id", sa.Integer(), nullable=False),
        sa.Column("relationship_type", sa.String(length=64), nullable=False),
        sa.Column(
            "provider", sa.String(length=64), nullable=False, server_default="system"
        ),
        sa.Column("confidence", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["source_identity_id"], ["media_identities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_identity_id"], ["media_identities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_identity_id",
            "target_identity_id",
            "relationship_type",
            "provider",
            name="uq_media_identity_relationship",
        ),
    )
    op.create_index(
        op.f("ix_media_identity_relationships_source_identity_id"),
        "media_identity_relationships",
        ["source_identity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_identity_relationships_target_identity_id"),
        "media_identity_relationships",
        ["target_identity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_identity_relationships_relationship_type"),
        "media_identity_relationships",
        ["relationship_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_identity_relationships_provider"),
        "media_identity_relationships",
        ["provider"],
        unique=False,
    )

    op.create_table(
        "media_identity_timeline_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_identity_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column(
            "severity", sa.String(length=16), nullable=False, server_default="info"
        ),
        sa.Column(
            "source", sa.String(length=64), nullable=False, server_default="system"
        ),
        sa.Column("details_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "happened_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["media_identity_id"], ["media_identities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_media_identity_timeline_events_media_identity_id"),
        "media_identity_timeline_events",
        ["media_identity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_media_identity_timeline_events_event_type"),
        "media_identity_timeline_events",
        ["event_type"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO media_identities (
                media_type,
                movie_id,
                series_id,
                canonical_provider,
                canonical_title,
                canonical_year,
                provider_confidence,
                identity_confidence,
                conflict_level,
                needs_review,
                health_state,
                lifecycle_state,
                last_synced_at,
                metadata_json
            )
            SELECT
                'movie',
                m.id,
                NULL,
                COALESCE(ma.artwork_source, 'radarr'),
                m.title,
                m.year,
                CAST(COALESCE(ma.artwork_confidence, 0) * 100 AS INTEGER),
                CAST(COALESCE(ma.artwork_confidence, 0) * 100 AS INTEGER),
                'none',
                CASE WHEN COALESCE(ma.artwork_status, 'unknown') IN ('missing', 'invalid', 'stale', 'needs_refresh') THEN 1 ELSE 0 END,
                CASE WHEN COALESCE(ma.artwork_status, 'unknown') IN ('missing', 'invalid') THEN 'risk' ELSE 'healthy' END,
                COALESCE(ma.lifecycle_state, 'resolved'),
                COALESCE(ma.updated_at, CURRENT_TIMESTAMP),
                '{}'
            FROM movies m
            LEFT JOIN media_assets ma ON ma.movie_id = m.id
            WHERE m.removed_at IS NULL
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO media_identities (
                media_type,
                movie_id,
                series_id,
                canonical_provider,
                canonical_title,
                canonical_year,
                provider_confidence,
                identity_confidence,
                conflict_level,
                needs_review,
                health_state,
                lifecycle_state,
                last_synced_at,
                metadata_json
            )
            SELECT
                'series',
                NULL,
                s.id,
                COALESCE(ma.artwork_source, 'sonarr'),
                s.title,
                s.year,
                CAST(COALESCE(ma.artwork_confidence, 0) * 100 AS INTEGER),
                CAST(COALESCE(ma.artwork_confidence, 0) * 100 AS INTEGER),
                'none',
                CASE WHEN COALESCE(ma.artwork_status, 'unknown') IN ('missing', 'invalid', 'stale', 'needs_refresh') THEN 1 ELSE 0 END,
                CASE WHEN COALESCE(ma.artwork_status, 'unknown') IN ('missing', 'invalid') THEN 'risk' ELSE 'healthy' END,
                COALESCE(ma.lifecycle_state, 'resolved'),
                COALESCE(ma.updated_at, CURRENT_TIMESTAMP),
                '{}'
            FROM series s
            LEFT JOIN media_assets ma ON ma.series_id = s.id
            WHERE s.removed_at IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_media_identity_timeline_events_event_type"),
        table_name="media_identity_timeline_events",
    )
    op.drop_index(
        op.f("ix_media_identity_timeline_events_media_identity_id"),
        table_name="media_identity_timeline_events",
    )
    op.drop_table("media_identity_timeline_events")

    op.drop_index(
        op.f("ix_media_identity_relationships_provider"),
        table_name="media_identity_relationships",
    )
    op.drop_index(
        op.f("ix_media_identity_relationships_relationship_type"),
        table_name="media_identity_relationships",
    )
    op.drop_index(
        op.f("ix_media_identity_relationships_target_identity_id"),
        table_name="media_identity_relationships",
    )
    op.drop_index(
        op.f("ix_media_identity_relationships_source_identity_id"),
        table_name="media_identity_relationships",
    )
    op.drop_table("media_identity_relationships")

    op.drop_index(
        op.f("ix_media_identity_external_ids_id_value"),
        table_name="media_identity_external_ids",
    )
    op.drop_index(
        op.f("ix_media_identity_external_ids_id_type"),
        table_name="media_identity_external_ids",
    )
    op.drop_index(
        op.f("ix_media_identity_external_ids_provider"),
        table_name="media_identity_external_ids",
    )
    op.drop_index(
        op.f("ix_media_identity_external_ids_media_identity_id"),
        table_name="media_identity_external_ids",
    )
    op.drop_table("media_identity_external_ids")

    op.drop_index(
        op.f("ix_media_identity_provider_mappings_provider"),
        table_name="media_identity_provider_mappings",
    )
    op.drop_index(
        op.f("ix_media_identity_provider_mappings_media_identity_id"),
        table_name="media_identity_provider_mappings",
    )
    op.drop_table("media_identity_provider_mappings")

    op.drop_index(
        op.f("ix_media_identities_lifecycle_state"), table_name="media_identities"
    )
    op.drop_index(
        op.f("ix_media_identities_health_state"), table_name="media_identities"
    )
    op.drop_index(
        op.f("ix_media_identities_canonical_provider"), table_name="media_identities"
    )
    op.drop_index(op.f("ix_media_identities_series_id"), table_name="media_identities")
    op.drop_index(op.f("ix_media_identities_movie_id"), table_name="media_identities")
    op.drop_index(op.f("ix_media_identities_media_type"), table_name="media_identities")
    op.drop_table("media_identities")
