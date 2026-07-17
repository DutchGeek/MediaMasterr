from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.artwork import CENTRAL_PLACEHOLDER_POSTER_URL
from backend.database import Base
from backend.database.models import MediaAsset, Movie
from backend.enums import MediaType
from backend.services.media_asset_artwork import media_asset_artwork_resolver
from backend.services.mie.artwork_integrity_service import ArtworkIntegrityService


@pytest.mark.anyio
async def test_artwork_integrity_migration_cleans_placeholder_and_marks_refresh() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie = Movie(title="Placeholder Movie", tmdb_id=8001)
        db.add(movie)
        await db.flush()

        db.add(
            MediaAsset(
                media_type=MediaType.MOVIE,
                movie_id=movie.id,
                poster_url=CENTRAL_PLACEHOLDER_POSTER_URL,
                backdrop_url="/placeholder-backdrop.jpg",
                artwork_source="cache",
            )
        )
        await db.commit()

        summary = await ArtworkIntegrityService(db).scan_and_repair(migration_mode=True)
        await db.commit()

        updated_asset = (
            await db.execute(select(MediaAsset).order_by(MediaAsset.id.asc()))
        ).scalars().first()

    await engine.dispose()

    assert summary.total_assets == 1
    assert summary.status_counts.get("NEEDS_REFRESH", 0) == 1
    assert updated_asset is not None
    assert updated_asset.poster_url is None


@pytest.mark.anyio
async def test_artwork_integrity_detects_collisions() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie_a = Movie(title="Movie A", tmdb_id=8101)
        movie_b = Movie(title="Movie B", tmdb_id=8102)
        db.add_all([movie_a, movie_b])
        await db.flush()

        db.add_all(
            [
                MediaAsset(
                    media_type=MediaType.MOVIE,
                    movie_id=movie_a.id,
                    poster_url="/same-poster.jpg",
                    backdrop_url="/a-backdrop.jpg",
                    artwork_source="radarr",
                ),
                MediaAsset(
                    media_type=MediaType.MOVIE,
                    movie_id=movie_b.id,
                    poster_url="/same-poster.jpg",
                    backdrop_url="/b-backdrop.jpg",
                    artwork_source="sonarr",
                ),
            ]
        )
        await db.commit()

        summary = await ArtworkIntegrityService(db).scan_and_repair(migration_mode=False)
        await db.commit()

        assets = (
            await db.execute(select(MediaAsset).order_by(MediaAsset.id.asc()))
        ).scalars().all()

    await engine.dispose()

    assert summary.collision_count == 1
    assert all(row.artwork_status == "NEEDS_REFRESH" for row in assets)


@pytest.mark.anyio
async def test_unified_artwork_resolver_provider_fallback_and_confidence() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        resolved = await media_asset_artwork_resolver.resolve(
            db,
            context="tests.provider_fallback",
            media_type=MediaType.MOVIE,
            media_id=9999,
            provider_poster_url="/provider-poster.jpg",
            provider_backdrop_url="/provider-backdrop.jpg",
            fallback_reason="test",
        )

    await engine.dispose()

    assert resolved.poster_url.endswith("/provider-poster.jpg")
    assert resolved.backdrop_url is not None
    assert resolved.artwork.source == "provider"
    assert resolved.artwork.confidence > 0.8
