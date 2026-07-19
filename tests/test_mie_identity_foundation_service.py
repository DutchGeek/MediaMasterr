from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.database.models import (
    MediaIdentity,
    MediaIdentityExternalId,
    MediaIdentityProviderMapping,
    MediaIdentityRelationship,
    MediaIdentityTimelineEvent,
    Movie,
)
from backend.enums import MediaType
from backend.services.mie.identity_service import IdentityCenterService


@pytest.mark.anyio
async def test_canonical_identity_list_returns_seeded_rows() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_maker() as db:
            movie = Movie(title="Canonical Seed", year=2020, tmdb_id=101)
            db.add(movie)
            await db.flush()

            db.add(
                MediaIdentity(
                    media_type=MediaType.MOVIE,
                    movie_id=movie.id,
                    canonical_provider="radarr",
                    canonical_title=movie.title,
                    canonical_year=movie.year,
                    provider_confidence=96,
                    identity_confidence=94,
                    conflict_level="low",
                    health_state="healthy",
                    lifecycle_state="resolved",
                    last_synced_at=datetime.now(UTC),
                )
            )
            await db.commit()

            response = await IdentityCenterService(db).canonical_identities(
                media_type=MediaType.MOVIE,
                search="canonical",
            )
    finally:
        await engine.dispose()

    assert response.total == 1
    assert response.items[0].title == "Canonical Seed"
    assert response.items[0].canonical_provider == "radarr"
    assert response.items[0].provider_confidence == 96


@pytest.mark.anyio
async def test_canonical_identity_detail_and_related_indexes() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_maker() as db:
            movie = Movie(title="Detail Seed", year=2021, tmdb_id=202)
            peer = Movie(title="Relationship Peer", year=2022, tmdb_id=303)
            db.add_all([movie, peer])
            await db.flush()

            identity = MediaIdentity(
                media_type=MediaType.MOVIE,
                movie_id=movie.id,
                canonical_provider="radarr",
                canonical_title=movie.title,
                canonical_year=movie.year,
                provider_confidence=90,
                identity_confidence=89,
            )
            peer_identity = MediaIdentity(
                media_type=MediaType.MOVIE,
                movie_id=peer.id,
                canonical_provider="radarr",
                canonical_title=peer.title,
                canonical_year=peer.year,
                provider_confidence=80,
                identity_confidence=80,
            )
            db.add_all([identity, peer_identity])
            await db.flush()

            mapping = MediaIdentityProviderMapping(
                media_identity_id=identity.id,
                provider="tmdb",
                provider_item_id="202",
                confidence=91,
                is_canonical=True,
                path_tail="/movies/202",
                connection_status="connected",
                metadata_json={"source": "seed"},
            )
            external = MediaIdentityExternalId(
                media_identity_id=identity.id,
                provider="tmdb",
                id_type="tmdb_id",
                id_value="202",
                confidence=100,
                is_canonical=True,
                metadata_json={"scope": "primary"},
            )
            relationship = MediaIdentityRelationship(
                source_identity_id=identity.id,
                target_identity_id=peer_identity.id,
                relationship_type="related",
                provider="system",
                confidence=75,
                metadata_json={"reason": "collection"},
            )
            event = MediaIdentityTimelineEvent(
                media_identity_id=identity.id,
                event_type="sync",
                summary="Seed sync",
                severity="info",
                source="tests",
                details_json={"step": "seed"},
            )
            db.add_all([mapping, external, relationship, event])
            await db.commit()

            service = IdentityCenterService(db)
            detail = await service.canonical_identity_detail(identity_id=identity.id)
            providers = await service.canonical_providers(identity_id=identity.id)
            external_ids = await service.canonical_external_ids(
                identity_id=identity.id,
                provider="tmdb",
                id_type="tmdb_id",
            )
    finally:
        await engine.dispose()

    assert detail.identity.title == "Detail Seed"
    assert len(detail.providers) == 1
    assert detail.providers[0].provider == "tmdb"
    assert len(detail.external_ids) == 1
    assert detail.external_ids[0].id_value == "202"
    assert len(detail.relationships) == 1
    assert detail.relationships[0].relationship_type == "related"
    assert len(detail.timeline) == 1
    assert detail.timeline[0].event_type == "sync"

    assert providers.total == 1
    assert providers.items[0].is_canonical is True

    assert external_ids.total == 1
    assert external_ids.items[0].id_type == "tmdb_id"
