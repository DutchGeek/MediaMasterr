from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.artwork import resolve_backdrop_url, resolve_poster_url
from backend.database.models import Movie, Series
from backend.enums import MediaType


@dataclass(slots=True)
class ArtworkIdentity:
    media_type: MediaType | None = None
    media_id: int | None = None
    tmdb_id: int | None = None
    tvdb_id: str | None = None
    imdb_id: str | None = None


class ArtworkService:
    """Single identity-based artwork resolver used across API surfaces."""

    def __init__(self) -> None:
        self._poster_cache: dict[str, str] = {}
        self._backdrop_cache: dict[str, str | None] = {}

    @staticmethod
    def _identity_key(identity: ArtworkIdentity, *, scope: str) -> str | None:
        if identity.media_type is not None and identity.media_id is not None:
            return f"{scope}:media:{identity.media_type.value}:{identity.media_id}"
        if identity.tmdb_id is not None:
            return f"{scope}:tmdb:{identity.tmdb_id}"
        if identity.tvdb_id:
            return f"{scope}:tvdb:{identity.tvdb_id.strip().lower()}"
        if identity.imdb_id:
            return f"{scope}:imdb:{identity.imdb_id.strip().lower()}"
        return None

    async def _resolve_exact_media_identity(
        self,
        db: AsyncSession,
        identity: ArtworkIdentity,
    ) -> tuple[str | None, str | None]:
        if identity.media_type is MediaType.MOVIE and identity.media_id is not None:
            row = (
                await db.execute(
                    select(Movie.poster_url, Movie.backdrop_url).where(
                        Movie.id == identity.media_id
                    )
                )
            ).first()
            if row is not None:
                return row[0], row[1]

        if identity.media_type is MediaType.SERIES and identity.media_id is not None:
            row = (
                await db.execute(
                    select(Series.poster_url, Series.backdrop_url).where(
                        Series.id == identity.media_id
                    )
                )
            ).first()
            if row is not None:
                return row[0], row[1]

        return (None, None)

    async def _resolve_exact_external_identity(
        self,
        db: AsyncSession,
        identity: ArtworkIdentity,
    ) -> tuple[str | None, str | None, MediaType | None, int | None]:
        if identity.tmdb_id is not None:
            movie_row = (
                await db.execute(
                    select(Movie.id, Movie.poster_url, Movie.backdrop_url).where(
                        Movie.tmdb_id == identity.tmdb_id,
                        Movie.removed_at.is_(None),
                    )
                )
            ).first()
            if movie_row is not None:
                return movie_row[1], movie_row[2], MediaType.MOVIE, movie_row[0]

            series_row = (
                await db.execute(
                    select(Series.id, Series.poster_url, Series.backdrop_url).where(
                        Series.tmdb_id == identity.tmdb_id,
                        Series.removed_at.is_(None),
                    )
                )
            ).first()
            if series_row is not None:
                return series_row[1], series_row[2], MediaType.SERIES, series_row[0]

        if identity.tvdb_id:
            series_row = (
                await db.execute(
                    select(Series.id, Series.poster_url, Series.backdrop_url).where(
                        Series.tvdb_id == identity.tvdb_id,
                        Series.removed_at.is_(None),
                    )
                )
            ).first()
            if series_row is not None:
                return series_row[1], series_row[2], MediaType.SERIES, series_row[0]

        if identity.imdb_id:
            movie_row = (
                await db.execute(
                    select(Movie.id, Movie.poster_url, Movie.backdrop_url).where(
                        Movie.imdb_id == identity.imdb_id,
                        Movie.removed_at.is_(None),
                    )
                )
            ).first()
            if movie_row is not None:
                return movie_row[1], movie_row[2], MediaType.MOVIE, movie_row[0]

            series_row = (
                await db.execute(
                    select(Series.id, Series.poster_url, Series.backdrop_url).where(
                        Series.imdb_id == identity.imdb_id,
                        Series.removed_at.is_(None),
                    )
                )
            ).first()
            if series_row is not None:
                return series_row[1], series_row[2], MediaType.SERIES, series_row[0]

        return (None, None, None, None)

    async def resolve(
        self,
        db: AsyncSession,
        *,
        context: str,
        identity: ArtworkIdentity | None = None,
        poster_url: str | None = None,
        backdrop_url: str | None = None,
        fallback_reason: str | None = None,
    ) -> tuple[str, str | None, ArtworkIdentity]:
        identity = identity or ArtworkIdentity()
        bind = db.get_bind()
        scope = str(id(bind))
        key = self._identity_key(identity, scope=scope)

        if key and key in self._poster_cache:
            return (
                self._poster_cache[key],
                self._backdrop_cache.get(key),
                identity,
            )

        resolved_poster = poster_url
        resolved_backdrop = backdrop_url

        exact_poster, exact_backdrop = await self._resolve_exact_media_identity(db, identity)
        if exact_poster:
            resolved_poster = exact_poster
        if exact_backdrop:
            resolved_backdrop = exact_backdrop

        if not resolved_poster:
            ext_poster, ext_backdrop, resolved_media_type, resolved_media_id = await self._resolve_exact_external_identity(
                db,
                identity,
            )
            if ext_poster:
                resolved_poster = ext_poster
                if resolved_media_type is not None and resolved_media_id is not None:
                    identity.media_type = resolved_media_type
                    identity.media_id = resolved_media_id
            if ext_backdrop:
                resolved_backdrop = ext_backdrop

        # Step 3 (ARR provider mapping) intentionally remains identity-only:
        # the model identities above are synced from ARR and media-server mappings.

        poster = resolve_poster_url(
            resolved_poster,
            context=context,
            media_type=identity.media_type.value if identity.media_type is not None else None,
            media_id=identity.media_id,
            fallback_reason=fallback_reason,
        )
        backdrop = resolve_backdrop_url(resolved_backdrop)

        key = self._identity_key(identity, scope=scope)
        if key:
            self._poster_cache[key] = poster
            self._backdrop_cache[key] = backdrop

        return (poster, backdrop, identity)


artwork_service = ArtworkService()
