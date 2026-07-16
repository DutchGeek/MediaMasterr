from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.artwork import (
    CENTRAL_PLACEHOLDER_POSTER_URL,
    resolve_backdrop_url,
    resolve_poster_url,
)
from backend.database.models import MediaAsset
from backend.enums import MediaType


@dataclass(slots=True)
class ResolvedArtwork:
    poster_url: str
    backdrop_url: str | None


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

        if media_type is not None and media_id is not None:
            if media_type is MediaType.MOVIE:
                row = (
                    await db.execute(
                        select(MediaAsset.poster_url, MediaAsset.backdrop_url).where(
                            MediaAsset.media_type == MediaType.MOVIE,
                            MediaAsset.movie_id == media_id,
                        )
                    )
                ).first()
            else:
                row = (
                    await db.execute(
                        select(MediaAsset.poster_url, MediaAsset.backdrop_url).where(
                            MediaAsset.media_type == MediaType.SERIES,
                            MediaAsset.series_id == media_id,
                        )
                    )
                ).first()
            if row is not None:
                media_asset_poster = row[0]
                media_asset_backdrop = row[1]

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

        return ResolvedArtwork(poster_url=poster, backdrop_url=backdrop)


media_asset_artwork_resolver = MediaAssetArtworkResolver()
