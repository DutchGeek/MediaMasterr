from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.encryption import fer_encrypt
from backend.database import Base
from backend.database.models import (
    Movie,
    MovieVersion,
    ProtectedMedia,
    ProtectionProviderConfig,
    ReclaimRule,
)
from backend.enums import MediaType, Service
from backend.services.protection.schemas import ProtectionConfigRequest
from backend.services.protection.service import ProtectionService


@pytest.mark.anyio
async def test_protection_service_stats_include_protected_files_and_rules() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie = Movie(title="Protected Movie", tmdb_id=10001, size=1_024)
        db.add(movie)
        await db.flush()

        version = MovieVersion(
            movie_id=movie.id,
            service=Service.PLEX,
            service_item_id="rk-1",
            service_media_id="media-1",
            library_id="1",
            library_name="Movies",
            path="/library/movies/protected.mkv",
            size=2_048,
        )
        rule = ReclaimRule(
            name="Keep Top Rated",
            media_type=MediaType.MOVIE,
            enabled=True,
            target_scope="movie_version",
            definition={
                "version": 1,
                "root": {
                    "type": "group",
                    "op": "and",
                    "children": [
                        {
                            "type": "condition",
                            "field": "media.vote_average",
                            "operator": "greater_than",
                            "value": 8,
                        }
                    ],
                },
            },
            action={"outcome": "protect"},
        )
        db.add_all([version, rule])
        await db.flush()

        db.add(
            ProtectedMedia(
                media_type=MediaType.MOVIE,
                movie_id=movie.id,
                movie_version_id=version.id,
                source="rule",
                source_rule_id=rule.id,
                reason="Matched rule",
            )
        )

        db.add(
            ProtectionProviderConfig(
                provider="reclaimerr",
                base_url="https://reclaimerr.local",
                api_key=fer_encrypt("secret"),
                enabled=True,
                connection_status="connected",
            )
        )
        await db.commit()

        stats = await ProtectionService(db).get_stats()

    await engine.dispose()

    assert stats.connected is True
    assert stats.provider == "Reclaimerr"
    assert stats.protected_files == 1
    assert stats.protected_size == 2_048
    assert stats.active_rules == 1


@pytest.mark.anyio
async def test_protection_test_connection_requires_url_and_key() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        service = ProtectionService(db)
        status = await service.test_connection(
            ProtectionConfigRequest(
                provider="reclaimerr",
                base_url="",
                api_key="",
                enabled=True,
            )
        )

    await engine.dispose()

    assert status.connected is False
    assert status.connection_status == "error"
