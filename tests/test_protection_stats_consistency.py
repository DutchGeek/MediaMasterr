from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.database import Base
from backend.services.protection.models import (
    ProtectionItemRecord,
    ProtectionProviderStatus,
    ProtectionRuleRecord,
    ProtectionStatistics,
)
from backend.services.protection.service import ProtectionService


class _FakeProvider:
    async def getStatistics(self) -> ProtectionStatistics:
        # Deliberately inconsistent with item/rule data; service should normalize.
        return ProtectionStatistics(
            connected=True,
            provider="Reclaimerr",
            protected_files=99,
            protected_size=123,
            active_rules=99,
            last_sync=None,
        )

    async def getProtectedItems(self) -> list[ProtectionItemRecord]:
        return [
            ProtectionItemRecord(
                path="/library/movies/A.mkv",
                reason="Rule A",
                provider="Reclaimerr",
                expiration=None,
                status="Active",
            ),
            ProtectionItemRecord(
                path="/library/movies/B.mkv",
                reason="Rule B",
                provider="Reclaimerr",
                expiration=None,
                status="Active",
            ),
        ]

    async def getProtectionRules(self) -> list[ProtectionRuleRecord]:
        return [
            ProtectionRuleRecord(
                rule="Rule A",
                source="Reclaimerr",
                protected_items=1,
                status="Active",
                last_updated=None,
            ),
            ProtectionRuleRecord(
                rule="Rule B",
                source="Reclaimerr",
                protected_items=1,
                status="Disabled",
                last_updated=None,
            ),
        ]

    async def connect(self) -> ProtectionProviderStatus:
        return ProtectionProviderStatus(
            connected=True,
            authenticated=True,
            provider="Reclaimerr",
            auth_method="web_login",
            connection_status="connected",
            authentication_status="authenticated",
            base_url=None,
            provider_version=None,
            last_login=None,
            last_sync=None,
            capabilities=[],
            message=None,
        )

    async def testConnection(self) -> ProtectionProviderStatus:
        return await self.connect()

    async def sync(self) -> ProtectionProviderStatus:
        return await self.connect()

    def get_runtime_auth_state(self) -> dict[str, str | bool | None]:
        return {
            "session_token": None,
            "authenticated": True,
            "provider_version": None,
            "last_login": None,
            "last_sync": None,
        }


@pytest.mark.anyio
async def test_protection_stats_use_same_source_of_truth_as_items_and_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_maker() as db:
        service = ProtectionService(db)
        monkeypatch.setattr(service, "_provider_from_config", lambda _cfg: _FakeProvider())

        response = await service.get_stats()

        assert response.protected_files == 2
        assert response.active_rules == 1

    await engine.dispose()
