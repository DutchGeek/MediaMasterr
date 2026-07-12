from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
import json
from urllib.parse import urlsplit

import niquests
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logger import LOG
from backend.core.rule_engine import RULE_OUTCOME_PROTECT, normalize_rule_outcome
from backend.core.utils.datetime_utils import to_utc_isoformat
from backend.database.models import (
    Episode,
    Movie,
    MovieVersion,
    ProtectedMedia,
    ReclaimRule,
    Season,
    Series,
)
from backend.enums import MediaType
from backend.tasks.cleanup import scan_cleanup_candidates

from .models import (
    ProtectionAuthenticationDefinition,
    ProtectionAuthFieldDefinition,
    ProtectionItemRecord,
    ProtectionProviderDefinition,
    ProtectionProviderStatus,
    ProtectionRuleRecord,
    ProtectionStatistics,
)
from .provider import ProtectionProvider


class ReclaimerrProtectionProvider(ProtectionProvider):
    """Protection provider backed by MediaMasterr's native reclaim engine."""

    provider_name = "reclaimerr"

    def __init__(
        self,
        db: AsyncSession,
        *,
        base_url: str | None,
        username: str | None,
        password: str | None,
        session_token: str | None,
        authenticated: bool,
        provider_version: str | None,
        last_login: datetime | None,
        enabled: bool,
        last_sync: datetime | None,
    ) -> None:
        self._db = db
        self._base_url = self._normalize_base_url(base_url)
        self._username = (username or "").strip() or None
        self._password = (password or "").strip() or None
        self._session_token = (session_token or "").strip() or None
        self._authenticated = authenticated
        self._provider_version = (provider_version or "").strip() or None
        self._last_login = last_login
        self._enabled = enabled
        self._last_sync = last_sync

    @staticmethod
    def _normalize_base_url(base_url: str | None) -> str | None:
        normalized = (base_url or "").strip().rstrip("/")
        if not normalized:
            return None
        if normalized.startswith("http://") or normalized.startswith("https://"):
            candidate = normalized
        else:
            candidate = f"http://{normalized}"
        parsed = urlsplit(candidate)
        if not parsed.scheme or not parsed.netloc:
            return None
        return candidate

    @staticmethod
    def _capabilities() -> list[str]:
        return ["Rules", "Protected Items", "Statistics"]

    def _new_session(self) -> niquests.AsyncSession:
        session = niquests.AsyncSession()
        if self._session_token:
            for pair in self._session_token.split(";"):
                if "=" not in pair:
                    continue
                key, value = pair.split("=", 1)
                key = key.strip()
                value = value.strip()
                if key:
                    session.cookies.set(key, value)
        return session

    @staticmethod
    def _serialize_session(session: niquests.AsyncSession) -> str:
        jar = session.cookies.get_dict()
        return "; ".join(f"{k}={v}" for k, v in jar.items() if k and v)

    @staticmethod
    def _response_snippet(response: niquests.Response) -> str:
        try:
            body = response.text or ""
        except Exception as exc:
            return f"<unavailable: {exc}>"
        body = body.strip()
        return body[:500] if body else "<empty>"

    async def _request_with_trace(
        self,
        session: niquests.AsyncSession,
        method: str,
        url: str,
        *,
        trace_label: str,
        **kwargs,
    ) -> tuple[niquests.Response | None, object | None, bool]:
        LOG.info(
            "Protection provider request: "
            f"label={trace_label} method={method.upper()} url={url}"
        )
        try:
            response = await session.request(method, url, **kwargs)
        except Exception as exc:
            LOG.warning(
                "Protection provider request failed: "
                f"label={trace_label} method={method.upper()} url={url} error={exc}"
            )
            return None, None, False

        payload = None
        json_ok = False
        try:
            payload = response.json()
            json_ok = True
        except Exception:
            payload = None
            json_ok = False

        LOG.info(
            "Protection provider response: "
            f"label={trace_label} method={method.upper()} url={url} status={response.status_code} "
            f"json_ok={json_ok} body_snippet={json.dumps(self._response_snippet(response))}"
        )
        return response, payload, json_ok

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.endswith("Z"):
            candidate = f"{candidate[:-1]}+00:00"
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            return None

    @staticmethod
    def _remote_error(payload: object, fallback: str) -> str:
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        return fallback

    def _status_from_remote_payload(
        self,
        payload: dict[str, object],
        *,
        fallback_message: str | None = None,
    ) -> ProtectionProviderStatus:
        connected = bool(payload.get("connected", False))
        authenticated = bool(payload.get("authenticated", False))
        provider = str(payload.get("provider") or "Reclaimerr")
        auth_method = str(payload.get("auth_method") or "web_login")
        connection_status = str(
            payload.get("connection_status") or ("connected" if connected else "error")
        )
        authentication_status = str(
            payload.get("authentication_status")
            or ("authenticated" if authenticated else "not_authenticated")
        )
        base_url = payload.get("base_url")
        provider_version = payload.get("provider_version")
        last_login = payload.get("last_login")
        last_sync = payload.get("last_sync")
        capabilities = payload.get("capabilities")
        message = payload.get("message")

        if isinstance(last_login, str):
            parsed_login = self._parse_datetime(last_login)
            if parsed_login is not None:
                self._last_login = parsed_login
        if isinstance(last_sync, str):
            parsed_sync = self._parse_datetime(last_sync)
            if parsed_sync is not None:
                self._last_sync = parsed_sync

        return ProtectionProviderStatus(
            connected=connected,
            authenticated=authenticated,
            provider=provider,
            auth_method=auth_method,
            connection_status=connection_status,
            authentication_status=authentication_status,
            base_url=base_url if isinstance(base_url, str) else self._base_url,
            provider_version=(provider_version if isinstance(provider_version, str) else self._provider_version),
            last_login=last_login if isinstance(last_login, str) else to_utc_isoformat(self._last_login),
            last_sync=last_sync if isinstance(last_sync, str) else to_utc_isoformat(self._last_sync),
            capabilities=(
                [str(item) for item in capabilities if isinstance(item, str)]
                if isinstance(capabilities, list)
                else self._capabilities()
            ),
            message=(message if isinstance(message, str) else fallback_message),
        )

    async def _fetch_remote_status(
        self,
        endpoint: str,
        *,
        trace_label: str,
        method: str = "GET",
        timeout: int = 20,
    ) -> tuple[ProtectionProviderStatus | None, str | None]:
        authenticated, auth_error = await self._ensure_authenticated()
        if not authenticated:
            return None, auth_error or "Authentication failed"

        if not self._base_url:
            return None, "Provider URL is invalid"

        session = self._new_session()
        try:
            response, payload, _json_ok = await self._request_with_trace(
                session,
                method,
                f"{self._base_url}{endpoint}",
                trace_label=trace_label,
                timeout=timeout,
            )
            if response is None:
                return None, "Provider request failed"
            if response.status_code != HTTPStatus.OK:
                return None, self._remote_error(
                    payload,
                    f"Provider returned status {response.status_code}",
                )
            if not isinstance(payload, dict):
                return None, "Provider returned non-JSON status payload"
            return self._status_from_remote_payload(payload), None
        finally:
            await session.close()

    async def _login(self, session: niquests.AsyncSession) -> tuple[bool, str | None]:
        if not self._base_url or not self._username or not self._password:
            return False, "URL, username, and password are required"
        url = f"{self._base_url}/api/auth/login"
        LOG.info(
            "Reclaimerr auth request: "
            f"method=POST url={url} payload_format=json username={self._username}"
        )
        response, payload, json_ok = await self._request_with_trace(
            session,
            "POST",
            url,
            trace_label="login",
            json={"username": self._username, "password": self._password},
            timeout=20,
        )
        if response is None:
            return False, "Unable to reach provider"

        LOG.info(
            "Reclaimerr auth response: "
            f"status={response.status_code} "
            f"set_cookie={bool(response.headers.get('set-cookie'))} "
            f"cookies_received={list(response.cookies.get_dict().keys())} "
            f"json_ok={json_ok}"
        )

        if response.status_code != HTTPStatus.OK:
            message = None
            try:
                detail = payload.get("detail") if isinstance(payload, dict) else None
                if isinstance(detail, str) and detail.strip():
                    message = detail
            except Exception:
                message = None
            LOG.warning(
                "Reclaimerr authentication failed: "
                f"status={response.status_code} "
                f"message={message or 'Authentication failed'}"
            )
            return False, message or "Authentication failed"

        self._session_token = self._serialize_session(session)
        self._authenticated = bool(self._session_token)
        self._last_login = datetime.now(UTC)
        LOG.info(
            "Protection auth session established: "
            f"authenticated={self._authenticated} session_cookie_keys={list(session.cookies.get_dict().keys())}"
        )
        return self._authenticated, None

    async def _refresh_provider_version(self, session: niquests.AsyncSession) -> None:
        if not self._base_url:
            self._provider_version = None
            return
        try:
            response, payload, _json_ok = await self._request_with_trace(
                session,
                "GET",
                f"{self._base_url}/api/info/version",
                trace_label="provider-version",
                timeout=20,
            )
            if response is None:
                self._provider_version = None
                return
            if response.status_code != HTTPStatus.OK:
                self._provider_version = None
                return
            if isinstance(payload, dict):
                version = payload.get("version")
                self._provider_version = str(version).strip() if version else None
        except Exception:
            self._provider_version = None

    async def _probe_session(self, session: niquests.AsyncSession) -> bool:
        if not self._base_url:
            return False
        try:
            response, _payload, _json_ok = await self._request_with_trace(
                session,
                "GET",
                f"{self._base_url}/api/account/me",
                trace_label="probe-session",
                timeout=20,
            )
            if response is None:
                return False
            return response.status_code == HTTPStatus.OK
        except Exception:
            return False

    async def _ensure_authenticated(self) -> tuple[bool, str | None]:
        if not self._enabled:
            return False, "Provider is disabled"
        if not self._base_url:
            return False, "Provider URL is invalid"

        session = self._new_session()
        try:
            if self._session_token and await self._probe_session(session):
                self._authenticated = True
                await self._refresh_provider_version(session)
                return True, None

            ok, message = await self._login(session)
            if not ok:
                self._authenticated = False
                self._session_token = None
                return False, message
            await self._refresh_provider_version(session)
            return True, None
        finally:
            await session.close()

    def get_runtime_auth_state(self) -> dict[str, str | bool | None]:
        return {
            "session_token": self._session_token,
            "authenticated": self._authenticated,
            "provider_version": self._provider_version,
            "last_login": to_utc_isoformat(self._last_login),
            "last_sync": to_utc_isoformat(self._last_sync),
        }

    def _is_connected(self) -> bool:
        return bool(self._enabled and self._base_url and self._username and self._password)

    def getDefinition(self) -> ProtectionProviderDefinition:
        return ProtectionProviderDefinition(
            provider="reclaimerr",
            display_name="Reclaimerr",
            authentication=ProtectionAuthenticationDefinition(
                type="web_login",
                fields=[
                    ProtectionAuthFieldDefinition(
                        name="base_url",
                        label="Server URL",
                        required=True,
                    ),
                    ProtectionAuthFieldDefinition(
                        name="username",
                        label="Username",
                        required=True,
                    ),
                    ProtectionAuthFieldDefinition(
                        name="password",
                        label="Password",
                        required=True,
                        secret=True,
                    ),
                ],
            ),
        )

    async def connect(self) -> ProtectionProviderStatus:
        connected = self._is_connected()
        authentication_status = "authenticated" if self._authenticated else "not_authenticated"
        return ProtectionProviderStatus(
            connected=connected,
            authenticated=self._authenticated,
            provider="Reclaimerr",
            auth_method="web_login",
            connection_status="connected" if connected else "disconnected",
            authentication_status=authentication_status,
            base_url=self._base_url,
            provider_version=self._provider_version,
            last_login=to_utc_isoformat(self._last_login),
            last_sync=to_utc_isoformat(self._last_sync),
            capabilities=self._capabilities(),
            message=None
            if connected
            else "Configure URL, username, and password to connect the Reclaimerr provider",
        )

    async def testConnection(self) -> ProtectionProviderStatus:
        connected, message = await self._ensure_authenticated()
        return ProtectionProviderStatus(
            connected=connected,
            authenticated=connected,
            provider="Reclaimerr",
            auth_method="web_login",
            connection_status="connected" if connected else "error",
            authentication_status="authenticated" if connected else "not_authenticated",
            base_url=self._base_url,
            provider_version=self._provider_version,
            last_login=to_utc_isoformat(self._last_login),
            last_sync=to_utc_isoformat(self._last_sync),
            capabilities=self._capabilities(),
            message="Authenticated" if connected else message,
        )

    async def sync(self) -> ProtectionProviderStatus:
        if not self._is_connected():
            return ProtectionProviderStatus(
                connected=False,
                authenticated=False,
                provider="Reclaimerr",
                auth_method="web_login",
                connection_status="error",
                authentication_status="not_authenticated",
                base_url=self._base_url,
                provider_version=self._provider_version,
                last_login=to_utc_isoformat(self._last_login),
                last_sync=to_utc_isoformat(self._last_sync),
                capabilities=self._capabilities(),
                message="Provider is not connected",
            )

        authenticated, auth_error = await self._ensure_authenticated()
        if not authenticated:
            return ProtectionProviderStatus(
                connected=False,
                authenticated=False,
                provider="Reclaimerr",
                auth_method="web_login",
                connection_status="error",
                authentication_status="not_authenticated",
                base_url=self._base_url,
                provider_version=self._provider_version,
                last_login=to_utc_isoformat(self._last_login),
                last_sync=to_utc_isoformat(self._last_sync),
                capabilities=self._capabilities(),
                message=auth_error or "Authentication failed",
            )

        remote_status, remote_error = await self._fetch_remote_status(
            "/api/protection/sync",
            trace_label="remote-sync",
            method="POST",
            timeout=60,
        )
        if remote_status is not None:
            LOG.info(
                "Protection sync database writes: provider_mode=remote records_written=0"
            )
            return remote_status
        LOG.warning(
            "Protection remote sync unavailable, falling back to local scan: "
            f"reason={remote_error}"
        )

        protected_before = await self._db.scalar(select(func.count(ProtectedMedia.id)))
        rules_before = await self._db.scalar(select(func.count(ReclaimRule.id)))
        LOG.info(
            "Protection sync local DB before scan: "
            f"protected_media={int(protected_before or 0)} rules={int(rules_before or 0)}"
        )

        await scan_cleanup_candidates()

        protected_after = await self._db.scalar(select(func.count(ProtectedMedia.id)))
        rules_after = await self._db.scalar(select(func.count(ReclaimRule.id)))
        LOG.info(
            "Protection sync local DB after scan: "
            f"protected_media={int(protected_after or 0)} rules={int(rules_after or 0)} "
            f"protected_media_written={int((protected_after or 0) - (protected_before or 0))}"
        )
        self._last_sync = datetime.now(UTC)
        return ProtectionProviderStatus(
            connected=True,
            authenticated=True,
            provider="Reclaimerr",
            auth_method="web_login",
            connection_status="connected",
            authentication_status="authenticated",
            base_url=self._base_url,
            provider_version=self._provider_version,
            last_login=to_utc_isoformat(self._last_login),
            last_sync=to_utc_isoformat(self._last_sync),
            capabilities=self._capabilities(),
            message="Synchronization completed",
        )

    async def getProtectionRules(self) -> list[ProtectionRuleRecord]:
        if self._is_connected():
            authenticated, auth_error = await self._ensure_authenticated()
            if authenticated and self._base_url:
                session = self._new_session()
                try:
                    response, payload, _json_ok = await self._request_with_trace(
                        session,
                        "GET",
                        f"{self._base_url}/api/protection/rules",
                        trace_label="remote-rules",
                        timeout=20,
                    )
                    if response is not None and response.status_code == HTTPStatus.OK and isinstance(payload, list):
                        remote_rows: list[ProtectionRuleRecord] = []
                        for item in payload:
                            if not isinstance(item, dict):
                                continue
                            remote_rows.append(
                                ProtectionRuleRecord(
                                    rule=str(item.get("rule") or "Unknown"),
                                    source=str(item.get("source") or "Reclaimerr"),
                                    protected_items=int(item.get("protected_items") or 0),
                                    status=str(item.get("status") or "Unknown"),
                                    last_updated=(
                                        str(item.get("last_updated"))
                                        if item.get("last_updated") is not None
                                        else None
                                    ),
                                )
                            )
                        LOG.info(
                            "Protection rules discovered from remote provider: "
                            f"total_rules={len(remote_rows)}"
                        )
                        return remote_rows
                    LOG.warning(
                        "Remote protection rules unavailable, using local fallback: "
                        f"auth_error={auth_error}"
                    )
                finally:
                    await session.close()

        rules_result = await self._db.execute(select(ReclaimRule).order_by(ReclaimRule.name))
        rules = rules_result.scalars().all()

        protected_counts_result = await self._db.execute(
            select(ProtectedMedia.source_rule_id, func.count(ProtectedMedia.id))
            .where(ProtectedMedia.source == "rule", ProtectedMedia.source_rule_id.is_not(None))
            .group_by(ProtectedMedia.source_rule_id)
        )
        protected_counts = {
            int(rule_id): int(count)
            for rule_id, count in protected_counts_result.all()
            if rule_id is not None
        }

        rows: list[ProtectionRuleRecord] = []
        for rule in rules:
            if normalize_rule_outcome(rule) != RULE_OUTCOME_PROTECT:
                continue
            rows.append(
                ProtectionRuleRecord(
                    rule=rule.name,
                    source="Reclaimerr",
                    protected_items=protected_counts.get(rule.id, 0),
                    status="Active" if rule.enabled else "Disabled",
                    last_updated=to_utc_isoformat(rule.updated_at),
                )
            )
        LOG.info(
            "Protection rules discovered from local DB: "
            f"total_rules={len(rows)} raw_rules={len(rules)}"
        )
        return rows

    async def _resolve_item_path_and_size(
        self, item: ProtectedMedia
    ) -> tuple[str, int | None]:
        if item.movie_version_id is not None:
            version = await self._db.get(MovieVersion, item.movie_version_id)
            if version and version.path:
                return version.path, version.size
        if item.episode_id is not None:
            episode = await self._db.get(Episode, item.episode_id)
            if episode and episode.path:
                return episode.path, episode.size
        if item.season_id is not None:
            season = await self._db.get(Season, item.season_id)
            if season and season.path:
                return season.path, season.size
        if item.media_type is MediaType.MOVIE and item.movie_id is not None:
            movie = await self._db.get(Movie, item.movie_id)
            if movie:
                return movie.title, movie.size
        if item.media_type is MediaType.SERIES and item.series_id is not None:
            series = await self._db.get(Series, item.series_id)
            if series:
                return series.title, series.size
        return "Unknown", None

    async def getProtectedItems(self) -> list[ProtectionItemRecord]:
        if self._is_connected():
            authenticated, auth_error = await self._ensure_authenticated()
            if authenticated and self._base_url:
                session = self._new_session()
                try:
                    response, payload, _json_ok = await self._request_with_trace(
                        session,
                        "GET",
                        f"{self._base_url}/api/protection/items",
                        trace_label="remote-items",
                        timeout=20,
                    )
                    if response is not None and response.status_code == HTTPStatus.OK and isinstance(payload, list):
                        remote_rows: list[ProtectionItemRecord] = []
                        for item in payload:
                            if not isinstance(item, dict):
                                continue
                            remote_rows.append(
                                ProtectionItemRecord(
                                    path=str(item.get("path") or "Unknown"),
                                    reason=str(item.get("reason") or "Protected by policy"),
                                    provider=str(item.get("provider") or "Reclaimerr"),
                                    expiration=(
                                        str(item.get("expiration"))
                                        if item.get("expiration") is not None
                                        else None
                                    ),
                                    status=str(item.get("status") or "Unknown"),
                                )
                            )
                        LOG.info(
                            "Protected files discovered from remote provider: "
                            f"total_items={len(remote_rows)}"
                        )
                        return remote_rows
                    LOG.warning(
                        "Remote protected items unavailable, using local fallback: "
                        f"auth_error={auth_error}"
                    )
                finally:
                    await session.close()

        result = await self._db.execute(
            select(ProtectedMedia).order_by(ProtectedMedia.updated_at.desc())
        )
        entries = result.scalars().all()

        rows: list[ProtectionItemRecord] = []
        now = datetime.now(UTC)
        for entry in entries:
            path, _ = await self._resolve_item_path_and_size(entry)
            expiration = to_utc_isoformat(entry.expires_at) if entry.expires_at else "Never"
            is_active = entry.permanent or entry.expires_at is None or entry.expires_at > now
            rows.append(
                ProtectionItemRecord(
                    path=path,
                    reason=(entry.reason or "Protected by policy").strip(),
                    provider="Reclaimerr",
                    expiration=expiration,
                    status="Active" if is_active else "Expired",
                )
            )
        LOG.info(
            "Protected files discovered from local DB: "
            f"total_items={len(rows)} raw_entries={len(entries)}"
        )
        return rows

    async def getStatistics(self) -> ProtectionStatistics:
        if self._is_connected():
            authenticated, auth_error = await self._ensure_authenticated()
            if authenticated and self._base_url:
                session = self._new_session()
                try:
                    response, payload, _json_ok = await self._request_with_trace(
                        session,
                        "GET",
                        f"{self._base_url}/api/protection/stats",
                        trace_label="remote-stats",
                        timeout=20,
                    )
                    if response is not None and response.status_code == HTTPStatus.OK and isinstance(payload, dict):
                        stats = ProtectionStatistics(
                            connected=bool(payload.get("connected", True)),
                            provider=str(payload.get("provider") or "Reclaimerr"),
                            protected_files=int(payload.get("protected_files") or 0),
                            protected_size=int(payload.get("protected_size") or 0),
                            active_rules=int(payload.get("active_rules") or 0),
                            last_sync=(
                                str(payload.get("last_sync"))
                                if payload.get("last_sync") is not None
                                else None
                            ),
                        )
                        LOG.info(
                            "Protection statistics discovered from remote provider: "
                            f"protected_files={stats.protected_files} protected_size={stats.protected_size} "
                            f"active_rules={stats.active_rules}"
                        )
                        return stats
                    LOG.warning(
                        "Remote protection stats unavailable, using local fallback: "
                        f"auth_error={auth_error}"
                    )
                finally:
                    await session.close()

        status = await self.connect()
        items = await self.getProtectedItems()
        rules = await self.getProtectionRules()

        protected_size = 0
        item_rows = (
            await self._db.execute(select(ProtectedMedia).order_by(ProtectedMedia.id.asc()))
        ).scalars().all()
        for entry in item_rows:
            _, size = await self._resolve_item_path_and_size(entry)
            if size:
                protected_size += int(size)

        stats = ProtectionStatistics(
            connected=status.connected,
            provider=status.provider,
            protected_files=len(items),
            protected_size=protected_size,
            active_rules=sum(1 for rule in rules if rule.status == "Active"),
            last_sync=status.last_sync,
        )
        LOG.info(
            "Protection statistics discovered from local DB: "
            f"protected_files={stats.protected_files} protected_size={stats.protected_size} "
            f"active_rules={stats.active_rules}"
        )
        return stats
