from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.database.models import (
    MediaAsset,
    Movie,
    OperationHistory,
    SupplementalMediaMatch,
)
from backend.enums import MediaType, Service
from backend.models.mie import IdentityArtworkProviderSelectionRequest
from backend.services.mie.identity_service import IdentityCenterService


@pytest.mark.anyio
async def test_identity_workspace_uses_shared_artwork_resolver() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie = Movie(
            title="Identity Resolver Movie",
            tmdb_id=5001,
            poster_url="/movie-poster.jpg",
        )
        movie.backdrop_url = "/movie-backdrop.jpg"
        db.add(movie)
        await db.flush()
        db.add(
            MediaAsset(
                media_type=MediaType.MOVIE,
                movie_id=movie.id,
                poster_url="/asset-poster.jpg",
                backdrop_url="/asset-backdrop.jpg",
                artwork_status="VALID",
                artwork_source="radarr",
                artwork_confidence=0.95,
            )
        )
        await db.commit()

        response = await IdentityCenterService(db).workspace(media_type=MediaType.MOVIE)

    await engine.dispose()

    assert response.items
    item = response.items[0]
    assert item.poster_url == "https://image.tmdb.org/t/p/w342/asset-poster.jpg"
    assert item.backdrop_url == "https://image.tmdb.org/t/p/w1280/asset-backdrop.jpg"


@pytest.mark.anyio
async def test_identity_studio_returns_normalized_artwork_urls() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie = Movie(
            title="Identity Studio Movie",
            tmdb_id=5002,
            poster_url="/movie-poster.jpg",
        )
        movie.backdrop_url = "/movie-backdrop.jpg"
        db.add(movie)
        await db.flush()
        db.add(
            MediaAsset(
                media_type=MediaType.MOVIE,
                movie_id=movie.id,
                poster_url="/asset-poster.jpg",
                backdrop_url="/asset-backdrop.jpg",
                artwork_status="VALID",
                artwork_source="radarr",
                artwork_confidence=0.95,
            )
        )
        db.add(
            SupplementalMediaMatch(
                source_service=Service.RADARR,
                source_item_id="radarr-5002",
                media_type=MediaType.MOVIE,
                movie_id=movie.id,
                confidence=95,
                signals={
                    "poster_url": "/provider-poster.jpg",
                    "backdrop_url": "/provider-backdrop.jpg",
                },
            )
        )
        await db.commit()

        studio = await IdentityCenterService(db).studio(
            media_type=MediaType.MOVIE,
            media_id=movie.id,
        )

    await engine.dispose()

    poster_row = next(row for row in studio.artwork if row.key == "poster")
    backdrop_row = next(row for row in studio.artwork if row.key == "backdrop")

    canonical_poster = next(v for v in poster_row.values if v.provider == "current")
    radarr_poster = next(v for v in poster_row.values if v.provider == "radarr")
    radarr_backdrop = next(v for v in backdrop_row.values if v.provider == "radarr")

    assert canonical_poster.value == "https://image.tmdb.org/t/p/w342/asset-poster.jpg"
    assert radarr_poster.value == "https://image.tmdb.org/t/p/w342/provider-poster.jpg"
    assert (
        radarr_backdrop.value
        == "https://image.tmdb.org/t/p/w1280/provider-backdrop.jpg"
    )


@pytest.mark.anyio
async def test_identity_workspace_confidence_falls_back_to_health_signals() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie = Movie(
            title="Confidence Fallback Movie",
            tmdb_id=6001,
            imdb_id="tt1234567",
            overview="Healthy metadata overview.",
            original_language="en",
            poster_url="/movie-poster.jpg",
        )
        movie.backdrop_url = "/movie-backdrop.jpg"
        db.add(movie)
        await db.flush()
        db.add(
            MediaAsset(
                media_type=MediaType.MOVIE,
                movie_id=movie.id,
                poster_url="/asset-poster.jpg",
                backdrop_url="/asset-backdrop.jpg",
                artwork_status="VALID",
                artwork_source="radarr",
                artwork_confidence=0.95,
            )
        )
        await db.commit()

        response = await IdentityCenterService(db).workspace(media_type=MediaType.MOVIE)

    await engine.dispose()

    assert response.items
    item = response.items[0]
    assert item.provider_count == 0
    assert item.provider_confidence == 100
    assert item.identifier_status == "healthy"
    assert item.metadata_status == "healthy"
    assert item.artwork_status == "valid"


@pytest.mark.anyio
async def test_identity_studio_artwork_cards_include_provider_comparison() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie = Movie(
            title="Artwork Card Movie",
            tmdb_id=7001,
            poster_url="/movie-poster.jpg",
        )
        movie.backdrop_url = "/movie-backdrop.jpg"
        db.add(movie)
        await db.flush()
        db.add(
            MediaAsset(
                media_type=MediaType.MOVIE,
                movie_id=movie.id,
                poster_url="/asset-poster.jpg",
                backdrop_url="/asset-backdrop.jpg",
                artwork_status="VALID",
                artwork_source="radarr",
                artwork_confidence=0.92,
            )
        )
        db.add_all(
            [
                SupplementalMediaMatch(
                    source_service=Service.RADARR,
                    source_item_id="radarr-7001",
                    media_type=MediaType.MOVIE,
                    movie_id=movie.id,
                    confidence=92,
                    signals={
                        "poster_url": "/radarr-poster.jpg",
                        "backdrop_url": "/radarr-backdrop.jpg",
                    },
                ),
                SupplementalMediaMatch(
                    source_service=Service.PLEX,
                    source_item_id="plex-7001",
                    media_type=MediaType.MOVIE,
                    movie_id=movie.id,
                    confidence=88,
                    signals={
                        "poster_url": "/plex-poster.jpg",
                        "backdrop_url": "/plex-backdrop.jpg",
                    },
                ),
            ]
        )
        await db.commit()

        studio = await IdentityCenterService(db).studio(
            media_type=MediaType.MOVIE,
            media_id=movie.id,
        )

    await engine.dispose()

    poster_card = next(card for card in studio.artwork_cards if card.key == "poster")
    backdrop_card = next(
        card for card in studio.artwork_cards if card.key == "backdrop"
    )

    assert poster_card.state == "present"
    assert len(poster_card.providers) == 2
    assert backdrop_card.state == "present"
    assert len(studio.provider_comparison) == 2


@pytest.mark.anyio
async def test_set_artwork_provider_records_history_and_queues_sync() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie = Movie(
            title="Artwork Selection Movie",
            tmdb_id=7002,
            poster_url="/movie-poster.jpg",
        )
        movie.backdrop_url = "/movie-backdrop.jpg"
        db.add(movie)
        await db.flush()
        db.add(
            SupplementalMediaMatch(
                source_service=Service.PLEX,
                source_item_id="plex-7002",
                media_type=MediaType.MOVIE,
                movie_id=movie.id,
                confidence=85,
                signals={"poster_url": "/plex-poster.jpg"},
            )
        )
        await db.commit()

        service = IdentityCenterService(db)
        action = await service.set_artwork_provider(
            media_type=MediaType.MOVIE,
            media_id=movie.id,
            payload=IdentityArtworkProviderSelectionRequest(
                artwork_field="poster",
                provider="plex",
                reason="Preferred poster",
            ),
            user_id=42,
        )

        rows = (
            (
                await db.execute(
                    select(OperationHistory)
                    .where(OperationHistory.target_id.in_([str(movie.id), "all"]))
                    .order_by(OperationHistory.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    await engine.dispose()

    assert action.accepted is True
    assert "Sync queued" in action.message
    assert any(row.action == "identity_set_artwork_provider" for row in rows)
    assert any(row.action == "identity_sync_run" for row in rows)
