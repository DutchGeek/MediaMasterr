from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import niquests
import niquests.exceptions as niq_exceptions
from niquests.exceptions import ReadTimeout
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from backend.core.logger import LOG
from backend.core.utils.request import should_retry_on_status


@dataclass(frozen=True)
class QBittorrentConnectionConfig:
    base_url: str
    username: str
    password: str
    use_https: bool
    timeout: int


def parse_qbittorrent_connection_config(
    *,
    base_url: str,
    password: str,
    extra_settings: dict[str, Any] | None = None,
) -> QBittorrentConnectionConfig:
    settings = extra_settings or {}
    username = str(settings.get("username") or "").strip()
    if not username:
        raise ValueError("extra_settings.username is required")

    use_https = bool(settings.get("use_https", False))
    raw_timeout = settings.get("timeout", 30)
    try:
        timeout = int(raw_timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("extra_settings.timeout must be an integer") from exc
    if timeout < 1:
        raise ValueError("extra_settings.timeout must be greater than 0")

    normalized_base_url = QBittorrentClient._normalize_base_url(base_url, use_https)

    LOG.info(
        "qBittorrent config parsed: "
        f"base_url={normalized_base_url}, username={username}, use_https={use_https}, timeout={timeout}"
    )
    return QBittorrentConnectionConfig(
        base_url=normalized_base_url,
        username=username,
        password=password,
        use_https=use_https,
        timeout=timeout,
    )


class QBittorrentClient:
    """qBittorrent API client using cookie-based authentication."""

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
        if not normalized:
            raise ValueError("Invalid URL: base URL is empty")
        if normalized.startswith("http://") or normalized.startswith("https://"):
            candidate = normalized
        else:
            scheme = "https" if use_https else "http"
            candidate = f"{scheme}://{normalized}"
        parsed = urlsplit(candidate)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid URL: {candidate}")
        return candidate

    @staticmethod
    def _api_url(base_url: str, endpoint: str) -> str:
        return f"{base_url}/api/v2/{endpoint.lstrip('/')}"

    @staticmethod
    def _response_body(response: niquests.Response) -> str:
        try:
            return response.text.strip()
        except Exception:
            return ""

    @staticmethod
    def _log_http(method: str, url: str, response: niquests.Response) -> None:
        LOG.debug(
            f"qBittorrent HTTP {method} {url} -> {response.status_code} | body={QBittorrentClient._response_body(response)!r}"
        )

    @staticmethod
    async def _login(
        session: niquests.AsyncSession,
        *,
        base_url: str,
        username: str,
        password: str,
        timeout: int,
    ) -> None:
        login_url = QBittorrentClient._api_url(base_url, "auth/login")
        try:
            response = await session.post(
                login_url,
                data={"username": username, "password": password},
                timeout=timeout,
            )
        except niq_exceptions.InvalidURL as exc:
            raise ValueError(f"Invalid URL: {base_url}") from exc
        except (niq_exceptions.ConnectTimeout, niq_exceptions.ReadTimeout, TimeoutError) as exc:
            raise ValueError("Timeout while connecting to qBittorrent") from exc
        except niq_exceptions.ConnectionError as exc:
            raise ValueError("Connection refused or unreachable host") from exc

        QBittorrentClient._log_http("POST", login_url, response)

        if response.status_code >= 400:
            raise ValueError(
                "HTTP status code "
                f"{response.status_code} during login: "
                f"{QBittorrentClient._response_body(response) or 'empty response'}"
            )

        body = QBittorrentClient._response_body(response)
        if body.lower() not in {"ok.", "ok"}:
            raise ValueError(
                f"Authentication failed: unexpected login response body {body or '<empty>'}"
            )

    async def _initialize_session(self) -> None:
        if self._session_initialized:
            return
        await self._login(
            self.session,
            base_url=self.base_url,
            username=self.username,
            password=self.password,
            timeout=self.timeout,
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
        url = self._api_url(self.base_url, endpoint)
        response = await self.session.get(url, params=params, timeout=self.timeout)
        self._log_http("GET", url, response)
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

    @classmethod
    def from_connection_config(
        cls, config: QBittorrentConnectionConfig
    ) -> "QBittorrentClient":
        return cls(
            base_url=config.base_url,
            username=config.username,
            password=config.password,
            use_https=config.use_https,
            timeout=config.timeout,
        )

    @staticmethod
    async def test_service(
        url: str,
        password: str,
        extra_settings: dict[str, Any] | None = None,
    ) -> bool:
        config = parse_qbittorrent_connection_config(
            base_url=url,
            password=password,
            extra_settings=extra_settings,
        )
        client = QBittorrentClient.from_connection_config(config)
        try:
            await client._initialize_session()
            app_version = await client.get_app_version()
            if not app_version:
                raise ValueError("Unexpected response body from app/version: <empty>")
            return True
        finally:
            await client.session.close()
