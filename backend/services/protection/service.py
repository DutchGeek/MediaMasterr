from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.encryption import fer_decrypt, fer_encrypt
from backend.database.models import ProtectionProviderConfig

from .models import ProtectionProviderStatus, ProtectionStatistics
from .provider import ProtectionProvider
from .reclaimerr import ReclaimerrProtectionProvider
from .schemas import (
    ProtectionConfigRequest,
    ProtectionConfigResponse,
    ProtectionItemResponse,
    ProtectionRuleResponse,
    ProtectionStatusResponse,
    ProtectionStatsResponse,
)


class ProtectionService:
    """Application service for provider-agnostic Protection operations."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _get_or_create_config(self) -> ProtectionProviderConfig:
        result = await self._db.execute(
            select(ProtectionProviderConfig).order_by(ProtectionProviderConfig.id.asc())
        )
        config = result.scalars().first()
        if config is not None:
            return config

        config = ProtectionProviderConfig(
            provider="reclaimerr",
            base_url=None,
            api_key=None,
            enabled=False,
            connection_status="disconnected",
            last_sync_at=None,
            last_error=None,
        )
        self._db.add(config)
        await self._db.flush()
        return config

    def _provider_from_config(self, config: ProtectionProviderConfig) -> ProtectionProvider:
        decrypted_api_key = fer_decrypt(config.api_key) if config.api_key else None
        provider_name = (config.provider or "reclaimerr").strip().lower()
        if provider_name != "reclaimerr":
            provider_name = "reclaimerr"

        return ReclaimerrProtectionProvider(
            self._db,
            base_url=config.base_url,
            api_key=decrypted_api_key,
            enabled=bool(config.enabled),
            last_sync=config.last_sync_at,
        )

    def _provider_from_request(self, req: ProtectionConfigRequest) -> ProtectionProvider:
        provider_name = (req.provider or "reclaimerr").strip().lower()
        if provider_name != "reclaimerr":
            provider_name = "reclaimerr"
        return ReclaimerrProtectionProvider(
            self._db,
            base_url=req.base_url,
            api_key=req.api_key,
            enabled=req.enabled,
            last_sync=None,
        )

    @staticmethod
    def _to_status_response(status: ProtectionProviderStatus) -> ProtectionStatusResponse:
        return ProtectionStatusResponse(
            connected=status.connected,
            provider=status.provider,
            connection_status=status.connection_status,
            base_url=status.base_url,
            last_sync=status.last_sync,
            message=status.message,
        )

    async def get_config(self) -> ProtectionConfigResponse:
        config = await self._get_or_create_config()
        return ProtectionConfigResponse(
            provider="reclaimerr",
            base_url=config.base_url or "",
            api_key_configured=bool(config.api_key),
            enabled=bool(config.enabled),
        )

    async def save_config(self, req: ProtectionConfigRequest) -> ProtectionConfigResponse:
        config = await self._get_or_create_config()
        config.provider = "reclaimerr"
        config.base_url = req.base_url.strip() or None
        config.enabled = req.enabled

        api_key = req.api_key.strip()
        if api_key:
            config.api_key = fer_encrypt(api_key)

        provider = self._provider_from_config(config)
        status = await provider.connect()
        config.connection_status = status.connection_status
        config.last_error = None if status.connected else status.message

        await self._db.flush()
        return await self.get_config()

    async def get_status(self) -> ProtectionStatusResponse:
        config = await self._get_or_create_config()
        provider = self._provider_from_config(config)
        status = await provider.connect()

        config.connection_status = status.connection_status
        config.last_error = None if status.connected else status.message
        await self._db.flush()

        return self._to_status_response(status)

    async def test_connection(self, req: ProtectionConfigRequest) -> ProtectionStatusResponse:
        provider = self._provider_from_request(req)
        return self._to_status_response(await provider.testConnection())

    async def sync(self) -> ProtectionStatusResponse:
        config = await self._get_or_create_config()
        provider = self._provider_from_config(config)
        status = await provider.sync()

        config.connection_status = status.connection_status
        config.last_error = None if status.connected else status.message
        if status.connected:
            config.last_sync_at = datetime.now(UTC)
        await self._db.flush()

        return self._to_status_response(status)

    async def get_stats(self) -> ProtectionStatsResponse:
        config = await self._get_or_create_config()
        provider = self._provider_from_config(config)
        stats: ProtectionStatistics = await provider.getStatistics()
        return ProtectionStatsResponse(
            connected=stats.connected,
            provider=stats.provider,
            protected_files=stats.protected_files,
            protected_size=stats.protected_size,
            active_rules=stats.active_rules,
            last_sync=stats.last_sync,
        )

    async def get_rules(self) -> list[ProtectionRuleResponse]:
        config = await self._get_or_create_config()
        provider = self._provider_from_config(config)
        rules = await provider.getProtectionRules()
        return [
            ProtectionRuleResponse(
                rule=rule.rule,
                source=rule.source,
                protected_items=rule.protected_items,
                status=rule.status,
                last_updated=rule.last_updated,
            )
            for rule in rules
        ]

    async def get_items(self) -> list[ProtectionItemResponse]:
        config = await self._get_or_create_config()
        provider = self._provider_from_config(config)
        items = await provider.getProtectedItems()
        return [
            ProtectionItemResponse(
                path=item.path,
                reason=item.reason,
                provider=item.provider,
                expiration=item.expiration,
                status=item.status,
            )
            for item in items
        ]
