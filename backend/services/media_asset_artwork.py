from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.artwork import (
    CENTRAL_PLACEHOLDER_POSTER_URL,
    is_placeholder_artwork_url,
    resolve_backdrop_url,
    resolve_poster_url,
)
from backend.database.models import MediaAsset
from backend.enums import MediaType
from backend.models.artwork import ArtworkSelection


@dataclass(slots=True)
class ResolvedArtwork:
    poster_url: str
    backdrop_url: str | None
    artwork: ArtworkSelection


class MediaAssetArtworkResolver:
    """Single artwork pipeline for all API surfaces.

    Priority:
    1) MediaAsset.poster
    2) MediaAsset.backdrop (used as poster fallback)
    3) Provider poster/backdrop
    4) Placeholder
    """

    async def resolve(
        self,
        db: AsyncSession,
        *,
        context: str,
        media_type: MediaType | None,
        media_id: int | None,
        provider_poster_url: str | None = None,
        provider_backdrop_url: str | None = None,
        fallback_reason: str | None = None,
    ) -> ResolvedArtwork:
        media_asset_poster: str | None = None
        media_asset_backdrop: str | None = None
        media_asset_row: MediaAsset | None = None

        if media_type is not None and media_id is not None:
            if media_type is MediaType.MOVIE:
                row = (
                    await db.execute(
                        select(MediaAsset).where(
                            MediaAsset.media_type == MediaType.MOVIE,
                            MediaAsset.movie_id == media_id,
                        )
                    )
                ).scalars().first()
            else:
                row = (
                    await db.execute(
                        select(MediaAsset).where(
                            MediaAsset.media_type == MediaType.SERIES,
                            MediaAsset.series_id == media_id,
                        )
                    )
                ).scalars().first()
            if row is not None:
                media_asset_row = row
                media_asset_poster = row.poster_url
                media_asset_backdrop = row.backdrop_url

        backdrop = resolve_backdrop_url(media_asset_backdrop) or resolve_backdrop_url(
            provider_backdrop_url
        )

        poster = resolve_poster_url(
            media_asset_poster,
            context=context,
            media_type=media_type.value if media_type is not None else None,
            media_id=media_id,
            fallback_reason=fallback_reason,
        )

        if poster == CENTRAL_PLACEHOLDER_POSTER_URL:
            if media_asset_backdrop:
                poster = resolve_backdrop_url(media_asset_backdrop) or poster
            elif provider_poster_url:
                poster = resolve_poster_url(
                    provider_poster_url,
                    context=context,
                    media_type=media_type.value if media_type is not None else None,
                    media_id=media_id,
                    fallback_reason=fallback_reason,
                )
            elif provider_backdrop_url:
                poster = resolve_backdrop_url(provider_backdrop_url) or poster

        source = (
            media_asset_row.artwork_source
            if media_asset_row is not None and media_asset_row.artwork_source
            else "provider"
            if provider_poster_url or provider_backdrop_url
            else "placeholder"
        )
        status = (
            media_asset_row.artwork_status
            if media_asset_row is not None and media_asset_row.artwork_status
            else "PLACEHOLDER"
            if is_placeholder_artwork_url(poster)
            else "VALID"
        )
        confidence = (
            float(media_asset_row.artwork_confidence)
            if media_asset_row is not None and media_asset_row.artwork_confidence is not None
            else 0.88
            if source == "provider"
            else 0.0
        )
        diagnostics = media_asset_row.artwork_diagnostics if media_asset_row is not None else {}

        artwork = ArtworkSelection(
            poster=poster,
            background=backdrop,
            banner=(media_asset_row.banner_url if media_asset_row is not None else None),
            logo=(media_asset_row.logo_url if media_asset_row is not None else None),
            source=source,
            confidence=confidence,
            status=status,  # type: ignore[arg-type]
            validated=status == "VALID",
            reason=(diagnostics.get("reason") if isinstance(diagnostics, dict) else None),
            last_refreshed_at=(
                media_asset_row.artwork_last_refresh_at if media_asset_row is not None else None
            ),
        )

        return ResolvedArtwork(poster_url=poster, backdrop_url=backdrop, artwork=artwork)


media_asset_artwork_resolver = MediaAssetArtworkResolver()
