from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import MediaAsset, Movie, Series
from backend.enums import MediaType
from backend.models.mie import MieMediaGraphResponse
from backend.services.mie.correlation_engine import CorrelationEngine
from backend.services.mie.correlation_models import (
    CorrelationBuildContext,
    CorrelationSubject,
)
from backend.services.mie.request_context import MieRequestContext


@dataclass(slots=True)
class CorrelationService:
    db: AsyncSession
    engine: CorrelationEngine = field(default_factory=CorrelationEngine)
    request_context: MieRequestContext | None = None

    async def _resolve_subject(
        self,
        *,
        media_id: int,
        media_type: MediaType | None,
    ) -> CorrelationSubject:
        movie: Movie | None = await self.db.get(Movie, media_id)
        series: Series | None = await self.db.get(Series, media_id)

        if media_type is MediaType.MOVIE:
            if movie is None:
                raise ValueError(f"Movie {media_id} not found")
            return CorrelationSubject(
                media_type=MediaType.MOVIE,
                media_id=movie.id,
                title=movie.title,
                year=movie.year,
                tmdb_id=movie.tmdb_id,
                imdb_id=movie.imdb_id,
                tvdb_id=None,
                anilist_id=movie.anilist_id,
                trakt_rating=movie.trakt_rating,
                movie=movie,
            )

        if media_type is MediaType.SERIES:
            if series is None:
                raise ValueError(f"Series {media_id} not found")
            return CorrelationSubject(
                media_type=MediaType.SERIES,
                media_id=series.id,
                title=series.title,
                year=series.year,
                tmdb_id=series.tmdb_id,
                imdb_id=series.imdb_id,
                tvdb_id=series.tvdb_id,
                anilist_id=series.anilist_id,
                trakt_rating=series.trakt_rating,
                series=series,
            )

        if movie is not None and series is not None:
            raise ValueError(
                "Ambiguous media id exists in both movies and series. "
                "Specify media_type query parameter."
            )
        if movie is not None:
            return CorrelationSubject(
                media_type=MediaType.MOVIE,
                media_id=movie.id,
                title=movie.title,
                year=movie.year,
                tmdb_id=movie.tmdb_id,
                imdb_id=movie.imdb_id,
                tvdb_id=None,
                anilist_id=movie.anilist_id,
                trakt_rating=movie.trakt_rating,
                movie=movie,
            )
        if series is not None:
            return CorrelationSubject(
                media_type=MediaType.SERIES,
                media_id=series.id,
                title=series.title,
                year=series.year,
                tmdb_id=series.tmdb_id,
                imdb_id=series.imdb_id,
                tvdb_id=series.tvdb_id,
                anilist_id=series.anilist_id,
                trakt_rating=series.trakt_rating,
                series=series,
            )

        raise ValueError(f"Media id {media_id} not found")

    async def _load_media_asset(
        self, *, subject: CorrelationSubject
    ) -> MediaAsset | None:
        stmt = select(MediaAsset).where(
            MediaAsset.movie_id == subject.media_id
            if subject.media_type is MediaType.MOVIE
            else MediaAsset.series_id == subject.media_id
        )
        return (await self.db.execute(stmt)).scalars().first()

    async def media_graph(
        self,
        *,
        media_id: int,
        media_type: MediaType | None = None,
    ) -> MieMediaGraphResponse:
        subject = await self._resolve_subject(media_id=media_id, media_type=media_type)
        cache_key = (subject.media_type, subject.media_id)
        if self.request_context is not None:
            cached = self.request_context.graph_cache.get(cache_key)
            if cached is not None:
                return cached

        media_asset = await self._load_media_asset(subject=subject)

        ctx = CorrelationBuildContext(subject=subject, media_asset=media_asset)
        if self.request_context is not None:
            self.request_context.increment("graph_build_count")
            self.request_context.increment(
                "provider_execution_count", len(self.engine.providers)
            )
        ctx = await self.engine.run(self.db, ctx)

        identity = ctx.identity if ctx.identity is not None else ctx.fallback_identity()
        health = ctx.health
        if health is None:
            raise ValueError("Correlation health summary was not produced")

        graph = MieMediaGraphResponse(
            media_id=subject.media_id,
            media_type=subject.media_type,
            title=subject.title,
            graph_generated_at=datetime.now(UTC),
            identity=identity,
            request_intelligence=ctx.request_intelligence,
            arr_intelligence=ctx.arr_intelligence,
            torrent_intelligence=ctx.torrent_intelligence,
            file_intelligence=ctx.file_intelligence,
            artwork_intelligence=ctx.artwork_intelligence,
            timeline=ctx.timeline,
            health=health,
        )
        if self.request_context is not None:
            self.request_context.graph_cache[cache_key] = graph
        return graph
