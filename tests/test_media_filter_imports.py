from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.service_manager import service_manager
from backend.database import Base
from backend.database.models import Movie, MovieArrRef, QueryFilter, Series, SeriesArrRef, ServiceConfig, User
from backend.enums import MediaType, Service, UserRole
from backend.services.query_engine import QueryEngineSpec, apply_spec, get_filter_catalog, sync_imported_arr_filters


class _RadarrClientNoSaved:
    async def get_saved_filters(self) -> list[dict[str, object]]:
        raise ValueError("saved filters not available")

    async def get_all_tag_details(self) -> dict[str, list[int]]:
        return {
            "Marvel": [101, 202],
            "Horror": [303],
        }


class _SonarrClientNoSaved:
    async def get_saved_filters(self) -> list[dict[str, object]]:
        raise ValueError("saved filters not available")

    async def get_all_tag_details(self) -> dict[str, list[int]]:
        return {
            "Anime": [11, 12],
            "Kids": [20],
        }


@pytest.mark.anyio
async def test_sync_imported_arr_filters_falls_back_to_arr_tags() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    old_radarr_clients = service_manager.radarr_clients
    old_sonarr_clients = service_manager.sonarr_clients

    service_manager.radarr_clients = lambda: {1: _RadarrClientNoSaved()}  # type: ignore[method-assign]
    service_manager.sonarr_clients = lambda: {2: _SonarrClientNoSaved()}  # type: ignore[method-assign]

    try:
        async with session_maker() as db:
            await sync_imported_arr_filters(db)

            rows = (
                await db.execute(
                    QueryFilter.__table__.select().where(
                        QueryFilter.kind == "imported_arr",
                        QueryFilter.enabled.is_(True),
                    )
                )
            ).all()

            assert len(rows) == 4
            provider_ids = {str(row.provider_filter_id) for row in rows}
            assert "tag:marvel" in provider_ids
            assert "tag:horror" in provider_ids
            assert "tag:anime" in provider_ids
            assert "tag:kids" in provider_ids
    finally:
        service_manager.radarr_clients = old_radarr_clients  # type: ignore[method-assign]
        service_manager.sonarr_clients = old_sonarr_clients  # type: ignore[method-assign]
        await engine.dispose()


@pytest.mark.anyio
async def test_filter_catalog_prefixes_imported_provider_names() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    old_radarr_clients = service_manager.radarr_clients
    old_sonarr_clients = service_manager.sonarr_clients

    # Keep sync side-effect-free in this test and rely on seeded rows.
    service_manager.radarr_clients = lambda: {}  # type: ignore[method-assign]
    service_manager.sonarr_clients = lambda: {}  # type: ignore[method-assign]

    try:
        async with session_maker() as db:
            user = User(username="admin", password_hash="x", role=UserRole.ADMIN)
            db.add(user)
            await db.flush()

            db.add_all(
                [
                    QueryFilter(
                        name="Anime",
                        kind="imported_arr",
                        media_type=MediaType.SERIES,
                        read_only=True,
                        enabled=True,
                        provider_service=Service.SONARR,
                        provider_config_id=None,
                        provider_filter_id="tag:anime",
                        definition={"raw": {"seriesIds": [11]}},
                    ),
                    QueryFilter(
                        name="Marvel",
                        kind="imported_arr",
                        media_type=MediaType.MOVIE,
                        read_only=True,
                        enabled=True,
                        provider_service=Service.RADARR,
                        provider_config_id=None,
                        provider_filter_id="tag:marvel",
                        definition={"raw": {"movieIds": [101]}},
                    ),
                ]
            )
            await db.commit()

            series_catalog = await get_filter_catalog(
                db,
                current_user=user,
                media_type=MediaType.SERIES,
            )
            movie_catalog = await get_filter_catalog(
                db,
                current_user=user,
                media_type=MediaType.MOVIE,
            )

            series_labels = [item.label for item in series_catalog.imported]
            movie_labels = [item.label for item in movie_catalog.imported]

            assert "Sonarr - Anime" in series_labels
            assert "Radarr - Marvel" in movie_labels
    finally:
        service_manager.radarr_clients = old_radarr_clients  # type: ignore[method-assign]
        service_manager.sonarr_clients = old_sonarr_clients  # type: ignore[method-assign]
        await engine.dispose()


@pytest.mark.anyio
async def test_filter_catalog_supports_combined_movie_and_series_context() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    old_radarr_clients = service_manager.radarr_clients
    old_sonarr_clients = service_manager.sonarr_clients
    service_manager.radarr_clients = lambda: {}  # type: ignore[method-assign]
    service_manager.sonarr_clients = lambda: {}  # type: ignore[method-assign]

    try:
        async with session_maker() as db:
            user = User(username="admin", password_hash="x", role=UserRole.ADMIN)
            db.add(user)
            await db.flush()

            db.add_all(
                [
                    QueryFilter(
                        name="Kids",
                        kind="imported_arr",
                        media_type=MediaType.SERIES,
                        read_only=True,
                        enabled=True,
                        provider_service=Service.SONARR,
                        provider_filter_id="tag:kids",
                        definition={"raw": {"seriesIds": [11]}},
                    ),
                    QueryFilter(
                        name="Marvel",
                        kind="imported_arr",
                        media_type=MediaType.MOVIE,
                        read_only=True,
                        enabled=True,
                        provider_service=Service.RADARR,
                        provider_filter_id="tag:marvel",
                        definition={"raw": {"movieIds": [101]}},
                    ),
                ]
            )
            await db.commit()

            catalog = await get_filter_catalog(
                db,
                current_user=user,
                media_type=MediaType.MOVIE,
                media_types=[MediaType.MOVIE, MediaType.SERIES],
            )

        labels = [item.label for item in catalog.imported]
        assert "Radarr - Marvel" in labels
        assert "Sonarr - Kids" in labels
    finally:
        service_manager.radarr_clients = old_radarr_clients  # type: ignore[method-assign]
        service_manager.sonarr_clients = old_sonarr_clients  # type: ignore[method-assign]
        await engine.dispose()


@pytest.mark.anyio
async def test_imported_arr_filters_apply_only_to_matching_media_type() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie = Movie(title="Kids Movie", tmdb_id=101)
        series = Series(title="Kids Show", tmdb_id=202)
        radarr_config = ServiceConfig(
            service_type=Service.RADARR,
            base_url="http://radarr",
            api_key="k",
            name="RadarrMain",
            enabled=True,
        )
        sonarr_config = ServiceConfig(
            service_type=Service.SONARR,
            base_url="http://sonarr",
            api_key="k",
            name="SonarrMain",
            enabled=True,
        )
        db.add_all([movie, series, radarr_config, sonarr_config])
        await db.flush()

        db.add_all(
            [
                MovieArrRef(
                    movie_id=movie.id,
                    service_config_id=radarr_config.id,
                    arr_movie_id=101,
                ),
                SeriesArrRef(
                    series_id=series.id,
                    service_config_id=sonarr_config.id,
                    arr_series_id=202,
                ),
            ]
        )

        sonarr_filter = QueryFilter(
            name="Kids",
            kind="imported_arr",
            media_type=MediaType.SERIES,
            read_only=True,
            enabled=True,
            provider_service=Service.SONARR,
            provider_filter_id="tag:kids",
            definition={"raw": {"seriesIds": [202]}},
        )
        db.add(sonarr_filter)
        await db.commit()

        movie_query = select(Movie.id).where(Movie.removed_at.is_(None))
        movie_count_query = (
            select(func.count()).select_from(Movie).where(Movie.removed_at.is_(None))
        )
        movie_query, _ = await apply_spec(
            db,
            spec=QueryEngineSpec(
                media_type=MediaType.MOVIE,
                imported_filter_ids=[int(sonarr_filter.id)],
            ),
            query=movie_query,
            count_query=movie_count_query,
        )
        movie_rows = (await db.execute(movie_query)).all()

        series_query = select(Series.id).where(Series.removed_at.is_(None))
        series_count_query = (
            select(func.count())
            .select_from(Series)
            .where(Series.removed_at.is_(None))
        )
        series_query, _ = await apply_spec(
            db,
            spec=QueryEngineSpec(
                media_type=MediaType.SERIES,
                imported_filter_ids=[int(sonarr_filter.id)],
            ),
            query=series_query,
            count_query=series_count_query,
        )
        series_rows = (await db.execute(series_query)).all()

    await engine.dispose()

    assert movie_rows == []
    assert [int(row[0]) for row in series_rows] == [int(series.id)]
