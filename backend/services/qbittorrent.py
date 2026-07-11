from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import niquests
from niquests.exceptions import ReadTimeout
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.core.utils.request import should_retry_on_status


class QBittorrentClient:
    """Read-only qBittorrent API client.

    This client intentionally performs only GET requests to avoid modifying the
    qBittorrent server state.
    """

    __slots__ = (
        "base_url",
        "username",
        "password",
        "timeout",
        "session",
        "_session_initialized",
    )

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        use_https: bool = False,
        timeout: int = 30,
    ) -> None:
        self.base_url = self._normalize_base_url(base_url, use_https)
        self.username = username.strip()
        self.password = password
        self.timeout = timeout
        self.session = niquests.AsyncSession()
        self._session_initialized = False

    @staticmethod
    def _normalize_base_url(base_url: str, use_https: bool) -> str:
        normalized = (base_url or "").strip().rstrip("/")
        if normalized.startswith("http://") or normalized.startswith("https://"):
            return normalized
        scheme = "https" if use_https else "http"
        return f"{scheme}://{normalized}"

    async def _initialize_session(self) -> None:
        if self._session_initialized:
            return
        # qBittorrent normally expects POST for /auth/login, but this integration
        # is strictly GET-only by design. We still attempt to establish cookies for
        # environments that permit GET auth handshakes (for example proxy wrappers).
        await self.session.get(
            f"{self.base_url}/api/v2/auth/login",
            params={"username": self.username, "password": self.password},
            timeout=self.timeout,
            auth=(self.username, self.password),
        )
        self._session_initialized = True

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=(
            retry_if_exception_type((ConnectionError, TimeoutError, ReadTimeout))
            | retry_if_exception(should_retry_on_status)
        ),
    )
    async def _get(
        self,
        endpoint: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> niquests.Response:
        await self._initialize_session()
        response = await self.session.get(
            f"{self.base_url}/api/v2/{endpoint.lstrip('/')}",
            params=params,
            timeout=self.timeout,
            auth=(self.username, self.password),
        )
        response.raise_for_status()
        return response

    async def health(self) -> bool:
        try:
            await self.get_webapi_version()
            return True
        except Exception:
            return False

    async def get_webapi_version(self) -> str:
        response = await self._get("app/webapiVersion")
        return response.text.strip()

    async def get_app_version(self) -> str:
        response = await self._get("app/version")
        return response.text.strip()

    async def get_transfer_info(self) -> dict[str, Any]:
        response = await self._get("transfer/info")
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def get_torrents(self) -> list[dict[str, Any]]:
        response = await self._get("torrents/info")
        payload = response.json()
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    async def get_sync_maindata(self, rid: int = 0) -> dict[str, Any]:
        response = await self._get("sync/maindata", params={"rid": rid})
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    async def test_service(
        url: str,
        password: str,
        extra_settings: dict[str, Any] | None = None,
    ) -> bool:
        settings = extra_settings or {}
        username = str(settings.get("username") or "").strip()
        use_https = bool(settings.get("use_https", False))
        if not username:
            raise ValueError("Username is required")

        base_url = QBittorrentClient._normalize_base_url(url, use_https)
        async with niquests.AsyncSession() as session:
            await session.get(
                f"{base_url}/api/v2/auth/login",
                params={"username": username, "password": password},
                timeout=10,
                auth=(username, password),
            )
            response = await session.get(
                f"{base_url}/api/v2/app/webapiVersion",
                timeout=10,
                auth=(username, password),
            )
            response.raise_for_status()
            return bool(response.text.strip())
