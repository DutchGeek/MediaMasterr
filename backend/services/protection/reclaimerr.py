from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    ProtectionItemRecord,
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
        api_key: str | None,
        enabled: bool,
        last_sync: datetime | None,
    ) -> None:
        self._db = db
        self._base_url = (base_url or "").strip() or None
        self._api_key = (api_key or "").strip() or None
        self._enabled = enabled
        self._last_sync = last_sync

    def _is_connected(self) -> bool:
        return bool(self._enabled and self._base_url and self._api_key)

    async def connect(self) -> ProtectionProviderStatus:
        connected = self._is_connected()
        return ProtectionProviderStatus(
            connected=connected,
            provider="Reclaimerr",
            connection_status="connected" if connected else "disconnected",
            base_url=self._base_url,
            last_sync=to_utc_isoformat(self._last_sync),
            message=None
            if connected
            else "Configure URL and API key to connect the Reclaimerr provider",
        )

    async def testConnection(self) -> ProtectionProviderStatus:
        connected = self._is_connected()
        return ProtectionProviderStatus(
            connected=connected,
            provider="Reclaimerr",
            connection_status="connected" if connected else "error",
            base_url=self._base_url,
            last_sync=to_utc_isoformat(self._last_sync),
            message="Connection successful" if connected else "URL and API key are required",
        )

    async def sync(self) -> ProtectionProviderStatus:
        if not self._is_connected():
            return ProtectionProviderStatus(
                connected=False,
                provider="Reclaimerr",
                connection_status="error",
                base_url=self._base_url,
                last_sync=to_utc_isoformat(self._last_sync),
                message="Provider is not connected",
            )

        await scan_cleanup_candidates()
        self._last_sync = datetime.now(UTC)
        return ProtectionProviderStatus(
            connected=True,
            provider="Reclaimerr",
            connection_status="connected",
            base_url=self._base_url,
            last_sync=to_utc_isoformat(self._last_sync),
            message="Synchronization completed",
        )

    async def getProtectionRules(self) -> list[ProtectionRuleRecord]:
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
        return rows

    async def getStatistics(self) -> ProtectionStatistics:
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

        return ProtectionStatistics(
            connected=status.connected,
            provider=status.provider,
            protected_files=len(items),
            protected_size=protected_size,
            active_rules=sum(1 for rule in rules if rule.status == "Active"),
            last_sync=status.last_sync,
        )
