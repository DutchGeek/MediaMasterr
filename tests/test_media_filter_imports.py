from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.service_manager import service_manager
from backend.database import Base
from backend.database.models import QueryFilter, User
from backend.enums import MediaType, Service, UserRole
from backend.services.query_engine import get_filter_catalog, sync_imported_arr_filters


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
