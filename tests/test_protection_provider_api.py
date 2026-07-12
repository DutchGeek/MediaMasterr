from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.encryption import fer_decrypt, fer_encrypt
from backend.database import Base
from backend.database.models import (
    Movie,
    MovieVersion,
    ProtectedMedia,
    ProtectionProviderConfig,
    ReclaimRule,
)
from backend.enums import MediaType, Service
from backend.services.protection.models import ProtectionProviderStatus
from backend.services.protection.reclaimerr import ReclaimerrProtectionProvider
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
                username="admin",
                password=fer_encrypt("secret"),
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
async def test_protection_test_connection_requires_url_and_credentials() -> None:
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
                auth_method="web_login",
                base_url="",
                username="",
                password="",
                enabled=True,
            )
        )

    await engine.dispose()

    assert status.connected is False
    assert status.connection_status == "error"


@pytest.mark.anyio
async def test_protection_provider_definition_exposes_auth_metadata() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        definition = await ProtectionService(db).get_provider_definition()

    await engine.dispose()

    assert definition.provider == "reclaimerr"
    assert definition.display_name == "Reclaimerr"
    assert definition.authentication.type == "web_login"
    assert [field.name for field in definition.authentication.fields] == [
        "base_url",
        "username",
        "password",
    ]
    assert definition.authentication.fields[2].secret is True


@pytest.mark.anyio
async def test_protection_get_config_self_heals_disabled_flag() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        config = ProtectionProviderConfig(
            provider="reclaimerr",
            auth_method="web_login",
            base_url="https://reclaimerr.local",
            username="admin",
            password=fer_encrypt("secret"),
            enabled=False,
        )
        db.add(config)
        await db.commit()

        response = await ProtectionService(db).get_config()
        await db.refresh(config)

    await engine.dispose()

    assert response.enabled is True
    assert config.enabled is True


@pytest.mark.anyio
async def test_protection_save_config_persists_authenticated_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def fake_test_connection(self: ReclaimerrProtectionProvider) -> ProtectionProviderStatus:
        self._session_token = "session=abc123"
        self._authenticated = True
        self._provider_version = "0.1.11"
        self._last_login = datetime.now(UTC)
        return ProtectionProviderStatus(
            connected=True,
            authenticated=True,
            provider="Reclaimerr",
            auth_method="web_login",
            connection_status="connected",
            authentication_status="authenticated",
            base_url=self._base_url,
            provider_version=self._provider_version,
            last_login=self._last_login.isoformat(),
            last_sync=None,
            capabilities=["Rules", "Protected Items", "Statistics"],
            message="Authenticated",
        )

    monkeypatch.setattr(
        ReclaimerrProtectionProvider,
        "testConnection",
        fake_test_connection,
    )

    async with session_maker() as db:
        service = ProtectionService(db)
        await service.save_config(
            ProtectionConfigRequest(
                provider="reclaimerr",
                auth_method="web_login",
                base_url="https://reclaimerr.local",
                username="admin",
                password="secret",
                enabled=False,
            )
        )

        status = await service.get_status()
        config = await service._get_or_create_config()

    await engine.dispose()

    assert status.authenticated is True
    assert status.connection_status == "connected"
    assert status.last_login is not None
    assert config.enabled is True
    assert config.session_token is not None
    assert fer_decrypt(config.session_token) == "session=abc123"
