from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.encryption import fer_decrypt, fer_encrypt
from backend.core.logger import LOG
from backend.database.models import ProtectionProviderConfig

from .models import ProtectionProviderStatus, ProtectionStatistics
from .provider import ProtectionProvider
from .reclaimerr import ReclaimerrProtectionProvider
from .schemas import (
    ProtectionConfigRequest,
    ProtectionConfigResponse,
    ProtectionItemResponse,
    ProtectionProviderDefinitionResponse,
    ProtectionRuleResponse,
    ProtectionStatsResponse,
    ProtectionStatusResponse,
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
            auth_method="web_login",
            base_url=None,
            username=None,
            password=None,
            api_key=None,
            session_token=None,
            enabled=True,
            authenticated=False,
            connection_status="disconnected",
            provider_version=None,
            last_login_at=None,
            last_sync_at=None,
            last_error=None,
        )
        self._db.add(config)
        await self._db.flush()
        return config

    def _provider_from_config(
        self, config: ProtectionProviderConfig
    ) -> ProtectionProvider:
        decrypted_password = fer_decrypt(config.password) if config.password else None
        decrypted_session_token = (
            fer_decrypt(config.session_token) if config.session_token else None
        )
        provider_name = (config.provider or "reclaimerr").strip().lower()
        if provider_name != "reclaimerr":
            provider_name = "reclaimerr"

        return ReclaimerrProtectionProvider(
            self._db,
            base_url=config.base_url,
            username=config.username,
            password=decrypted_password,
            session_token=decrypted_session_token,
            authenticated=bool(config.authenticated),
            provider_version=config.provider_version,
            last_login=config.last_login_at,
            enabled=bool(config.enabled),
            last_sync=config.last_sync_at,
        )

    def _provider_from_request(
        self, req: ProtectionConfigRequest
    ) -> ProtectionProvider:
        provider_name = (req.provider or "reclaimerr").strip().lower()
        if provider_name != "reclaimerr":
            provider_name = "reclaimerr"
        return ReclaimerrProtectionProvider(
            self._db,
            base_url=req.base_url,
            username=req.username,
            password=req.password,
            session_token=None,
            authenticated=False,
            provider_version=None,
            last_login=None,
            enabled=True,
            last_sync=None,
        )

    @staticmethod
    def _to_definition_response(
        provider: ProtectionProvider,
    ) -> ProtectionProviderDefinitionResponse:
        definition = provider.getDefinition()
        return ProtectionProviderDefinitionResponse.model_validate(asdict(definition))

    @staticmethod
    def _to_status_response(
        status: ProtectionProviderStatus,
    ) -> ProtectionStatusResponse:
        return ProtectionStatusResponse(
            connected=status.connected,
            authenticated=status.authenticated,
            provider=status.provider,
            auth_method=status.auth_method,
            connection_status=status.connection_status,
            authentication_status=status.authentication_status,
            base_url=status.base_url,
            provider_version=status.provider_version,
            last_login=status.last_login,
            last_sync=status.last_sync,
            capabilities=status.capabilities,
            message=status.message,
        )

    @staticmethod
    def _update_config_from_status(
        config: ProtectionProviderConfig,
        provider: ProtectionProvider,
        status: ProtectionProviderStatus,
    ) -> None:
        config.connection_status = status.connection_status
        config.authenticated = status.authenticated
        config.provider_version = status.provider_version
        config.last_error = None if status.connected else status.message
        if status.last_login:
            config.last_login_at = datetime.fromisoformat(status.last_login)

        runtime = None
        get_runtime_state = getattr(provider, "get_runtime_auth_state", None)
        if callable(get_runtime_state):
            runtime = get_runtime_state()
        if not isinstance(runtime, dict):
            return

        token = runtime.get("session_token")
        if isinstance(token, str) and token.strip():
            config.session_token = fer_encrypt(token)
        elif token is None:
            config.session_token = None

        provider_version = runtime.get("provider_version")
        if isinstance(provider_version, str):
            config.provider_version = provider_version or None

        last_login = runtime.get("last_login")
        if isinstance(last_login, str) and last_login:
            config.last_login_at = datetime.fromisoformat(last_login)

    async def get_config(self) -> ProtectionConfigResponse:
        config = await self._get_or_create_config()
        if not config.enabled:
            config.enabled = True
            await self._db.flush()
        return ProtectionConfigResponse(
            provider="reclaimerr",
            auth_method=config.auth_method,
            base_url=config.base_url or "",
            username=config.username or "",
            password_configured=bool(config.password),
            configured_auth_fields=["password"] if config.password else [],
            enabled=bool(config.enabled),
        )

    async def get_provider_definition(self) -> ProtectionProviderDefinitionResponse:
        config = await self._get_or_create_config()
        provider = self._provider_from_config(config)
        return self._to_definition_response(provider)

    async def save_config(
        self, req: ProtectionConfigRequest
    ) -> ProtectionConfigResponse:
        config = await self._get_or_create_config()
        config.provider = "reclaimerr"
        config.auth_method = "web_login"
        config.base_url = req.base_url.strip() or None
        next_username = req.username.strip() or None
        credentials_changed = next_username != (config.username or None)
        config.username = next_username
        config.enabled = True

        next_password = req.password.strip()
        if next_password:
            encrypted_password = fer_encrypt(next_password)
            credentials_changed = (
                credentials_changed or encrypted_password != config.password
            )
            config.password = encrypted_password

        if credentials_changed:
            config.session_token = None
            config.authenticated = False
            config.last_login_at = None
            config.provider_version = None

        provider = self._provider_from_config(config)
        status = await provider.testConnection()
        self._update_config_from_status(config, provider, status)

        await self._db.flush()
        return await self.get_config()

    async def get_status(self) -> ProtectionStatusResponse:
        config = await self._get_or_create_config()
        if not config.enabled:
            config.enabled = True
        provider = self._provider_from_config(config)
        status = await provider.connect()
        if status.connected:
            status = await provider.testConnection()

        self._update_config_from_status(config, provider, status)
        await self._db.flush()

        return self._to_status_response(status)

    async def test_connection(
        self, req: ProtectionConfigRequest
    ) -> ProtectionStatusResponse:
        config = await self._get_or_create_config()
        resolved_password = req.password.strip()
        if not resolved_password and config.password:
            resolved_password = fer_decrypt(config.password)

        merged_request = ProtectionConfigRequest(
            provider=req.provider,
            auth_method=req.auth_method,
            base_url=req.base_url.strip() or (config.base_url or ""),
            username=req.username.strip() or (config.username or ""),
            password=resolved_password,
            enabled=True,
        )

        LOG.info(
            "Protection test connection request: "
            f"provider={merged_request.provider} "
            f"auth_method={merged_request.auth_method} "
            f"base_url={merged_request.base_url} "
            f"username={merged_request.username} "
            f"password_provided={bool(merged_request.password)}"
        )

        provider = self._provider_from_request(merged_request)
        status = await provider.testConnection()
        LOG.info(
            "Protection test connection response: "
            f"provider={status.provider} "
            f"status={status.connection_status} "
            f"authenticated={status.authenticated} "
            f"message={status.message}"
        )
        return self._to_status_response(status)

    async def sync(self) -> ProtectionStatusResponse:
        config = await self._get_or_create_config()
        if not config.enabled:
            config.enabled = True
        provider = self._provider_from_config(config)
        status = await provider.sync()
        self._update_config_from_status(config, provider, status)

        if status.connected and status.authenticated:
            config.last_sync_at = datetime.now(UTC)
        await self._db.flush()

        LOG.info(
            "Protection sync service result: "
            f"connected={status.connected} authenticated={status.authenticated} "
            f"connection_status={status.connection_status} last_sync={status.last_sync}"
        )

        return self._to_status_response(status)

    async def get_stats(self) -> ProtectionStatsResponse:
        config = await self._get_or_create_config()
        provider = self._provider_from_config(config)
        stats: ProtectionStatistics = await provider.getStatistics()
        # Keep files/rules counts aligned with the same source-of-truth used by
        # the items/rules endpoints to avoid UI mismatches.
        items = await provider.getProtectedItems()
        rules = await provider.getProtectionRules()
        response = ProtectionStatsResponse(
            connected=stats.connected,
            provider=stats.provider,
            protected_files=len(items),
            protected_size=stats.protected_size,
            active_rules=sum(1 for rule in rules if rule.status == "Active"),
            last_sync=stats.last_sync,
        )
        LOG.info(
            "Protection API return count: endpoint=/api/protection/stats "
            f"protected_files={response.protected_files} protected_size={response.protected_size} "
            f"active_rules={response.active_rules}"
        )
        return response

    async def get_rules(self) -> list[ProtectionRuleResponse]:
        config = await self._get_or_create_config()
        provider = self._provider_from_config(config)
        rules = await provider.getProtectionRules()
        response = [
            ProtectionRuleResponse(
                rule=rule.rule,
                source=rule.source,
                protected_items=rule.protected_items,
                status=rule.status,
                last_updated=rule.last_updated,
            )
            for rule in rules
        ]
        LOG.info(
            "Protection API return count: endpoint=/api/protection/rules "
            f"records={len(response)}"
        )
        return response

    async def get_items(self) -> list[ProtectionItemResponse]:
        config = await self._get_or_create_config()
        provider = self._provider_from_config(config)
        items = await provider.getProtectedItems()
        response = [
            ProtectionItemResponse(
                path=item.path,
                reason=item.reason,
                provider=item.provider,
                expiration=item.expiration,
                status=item.status,
            )
            for item in items
        ]
        LOG.info(
            "Protection API return count: endpoint=/api/protection/items "
            f"records={len(response)}"
        )
        return response
