from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.artwork import (
    CENTRAL_PLACEHOLDER_POSTER_URL,
    is_placeholder_artwork_url,
    normalize_artwork_url_for_hash,
)
from backend.database.models import MediaAsset
from backend.models.artwork import ArtworkSelection, ArtworkStatus


@dataclass(slots=True)
class ArtworkIntegrityScanSummary:
    total_assets: int
    status_counts: dict[str, int]
    collision_count: int


class ArtworkIntegrityService:
    """Validates and repairs MediaAsset artwork assignments inside MIE sync."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _classify_status(asset: MediaAsset) -> tuple[ArtworkStatus, str, float]:
        poster = (asset.poster_url or "").strip()
        backdrop = (asset.backdrop_url or "").strip()

        if not poster and not backdrop:
            return ("MISSING", "No poster/background assigned", 0.0)

        if is_placeholder_artwork_url(poster):
            return ("PLACEHOLDER", "Poster points to placeholder artwork", 0.05)

        if poster and poster.lower().startswith("javascript:"):
            return ("INVALID", "Poster URL uses invalid scheme", 0.0)

        if poster and len(poster) < 4:
            return ("INVALID", "Poster URL is malformed", 0.0)

        if not poster and backdrop:
            return (
                "NEEDS_REFRESH",
                "Backdrop exists but poster is unresolved",
                0.35,
            )

        if poster and not backdrop:
            return (
                "STALE",
                "Poster exists without backdrop; enrichment recommended",
                0.75,
            )

        confidence = 0.92
        if asset.artwork_source in {"plex", "sonarr", "radarr", "overseerr"}:
            confidence = 0.97
        if poster.startswith("/"):
            confidence = max(confidence, 0.95)
        return ("VALID", "Artwork validated", confidence)

    async def scan_and_repair(
        self,
        *,
        migration_mode: bool = False,
    ) -> ArtworkIntegrityScanSummary:
        rows = (await self.db.execute(select(MediaAsset).order_by(MediaAsset.id.asc()))).scalars().all()

        poster_to_assets: dict[str, list[MediaAsset]] = defaultdict(list)
        for asset in rows:
            normalized = normalize_artwork_url_for_hash(asset.poster_url)
            if normalized:
                poster_to_assets[normalized].append(asset)

        collisions = {
            key: assets
            for key, assets in poster_to_assets.items()
            if len(
                {
                    (asset.media_type.value, asset.movie_id or asset.series_id)
                    for asset in assets
                    if (asset.movie_id or asset.series_id) is not None
                }
            )
            > 1
        }

        now = datetime.now(UTC)
        status_counts: dict[str, int] = defaultdict(int)

        for asset in rows:
            status, reason, confidence = self._classify_status(asset)
            normalized = normalize_artwork_url_for_hash(asset.poster_url)
            in_collision = normalized in collisions if normalized else False

            if in_collision and status == "VALID":
                status = "NEEDS_REFRESH"
                reason = "Detected artwork cache collision across unrelated assets"
                confidence = min(confidence, 0.3)

            if migration_mode and status in {"PLACEHOLDER", "INVALID", "MISSING", "NEEDS_REFRESH"}:
                asset.poster_url = None
                asset.backdrop_url = None if status in {"PLACEHOLDER", "INVALID"} else asset.backdrop_url
                status = "NEEDS_REFRESH"
                reason = "Artwork assignment cleared during integrity migration"
                confidence = 0.0

            if not asset.artwork_source:
                asset.artwork_source = "cache" if asset.poster_url else "unresolved"

            asset.artwork_status = status
            asset.artwork_confidence = float(round(confidence, 4))
            asset.artwork_hash = normalized
            asset.artwork_validated_at = now
            if asset.artwork_last_refresh_at is None:
                asset.artwork_last_refresh_at = now
            asset.artwork_diagnostics = {
                "reason": reason,
                "collision": in_collision,
                "poster": asset.poster_url,
                "background": asset.backdrop_url,
                "source": asset.artwork_source,
            }
            status_counts[status] += 1

        await self.db.flush()
        return ArtworkIntegrityScanSummary(
            total_assets=len(rows),
            status_counts=dict(status_counts),
            collision_count=len(collisions),
        )

    @staticmethod
    def to_artwork_selection(asset: MediaAsset | None) -> ArtworkSelection:
        if asset is None:
            return ArtworkSelection(
                poster=CENTRAL_PLACEHOLDER_POSTER_URL,
                source="unresolved",
                confidence=0.0,
                status="MISSING",
                validated=False,
                reason="No media asset found",
            )

        diagnostics = asset.artwork_diagnostics or {}
        return ArtworkSelection(
            poster=asset.poster_url or CENTRAL_PLACEHOLDER_POSTER_URL,
            background=asset.backdrop_url,
            banner=asset.banner_url,
            logo=asset.logo_url,
            source=asset.artwork_source or "cache",
            confidence=float(asset.artwork_confidence or 0.0),
            status=(asset.artwork_status or "MISSING"),
            validated=(asset.artwork_status == "VALID"),
            reason=diagnostics.get("reason") if isinstance(diagnostics, dict) else None,
            last_refreshed_at=asset.artwork_last_refresh_at,
        )
