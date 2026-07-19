from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.service_manager import service_manager
from backend.database import Base
from backend.database.models import (
    MediaAsset,
    MediaIdentity,
    MediaIdentityExternalId,
    MediaIdentityProviderMapping,
    MediaIdentityTimelineEvent,
    Movie,
    MovieArrRef,
    MovieVersion,
    OperationHistory,
    Series,
    SeriesArrRef,
    ServiceConfig,
)
from backend.enums import MediaType, SeerrRequestStatus, Service
from backend.models.services.seerr import SeerrRequest
from backend.services.mie.correlation_service import CorrelationService


class _FakeQbitClient:
    def __init__(self, torrents: list[dict[str, object]]) -> None:
        self._torrents = torrents

    async def get_torrents(self) -> list[dict[str, object]]:
        return self._torrents


class _FakeSeerrClient:
    def __init__(
        self, movie_requests: list[SeerrRequest], tv_requests: list[SeerrRequest]
    ) -> None:
        self._movie_requests = movie_requests
        self._tv_requests = tv_requests

    async def get_movie_requests(self, _tmdb_id: int) -> list[SeerrRequest]:
        return self._movie_requests

    async def get_tv_requests(self, _tmdb_id: int) -> list[SeerrRequest]:
        return self._tv_requests


@pytest.fixture
def reset_service_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_manager, "_qbittorrent", None, raising=False)
    monkeypatch.setattr(service_manager, "_seerr", None, raising=False)


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_maker() as session:
            yield session
    finally:
        await engine.dispose()


async def _seed_movie_identity(db: AsyncSession) -> tuple[Movie, MediaIdentity]:
    movie = Movie(
        title="Correlation Movie",
        tmdb_id=1111,
        year=2022,
        imdb_id="tt0011111",
        anilist_id=777,
    )
    db.add(movie)
    await db.flush()

    db.add(
        MediaAsset(
            media_type=MediaType.MOVIE,
            movie_id=movie.id,
            lifecycle_state="imported",
            health_state="healthy",
            has_torrent=True,
            poster_url="https://img/movie-poster.jpg",
            backdrop_url="https://img/movie-backdrop.jpg",
        )
    )

    identity = MediaIdentity(
        media_type=MediaType.MOVIE,
        movie_id=movie.id,
        canonical_provider="radarr",
        canonical_title="Correlation Movie",
        canonical_year=2022,
        provider_confidence=94,
        identity_confidence=91,
    )
    db.add(identity)
    await db.flush()

    db.add_all(
        [
            MediaIdentityExternalId(
                media_identity_id=identity.id,
                provider="tmdb",
                id_type="tmdb_id",
                id_value="1111",
                is_canonical=True,
                confidence=100,
            ),
            MediaIdentityProviderMapping(
                media_identity_id=identity.id,
                provider="radarr",
                provider_item_id="999",
                confidence=95,
                is_canonical=True,
                metadata_json={"poster_url": "https://img/provider-poster.jpg"},
            ),
            MediaIdentityTimelineEvent(
                media_identity_id=identity.id,
                event_type="metadata_updated",
                summary="metadata refreshed",
                severity="info",
                source="identity",
            ),
        ]
    )

    db.add(
        OperationHistory(
            action="scan_media",
            target_type="movie",
            target_id=str(movie.id),
            result="completed",
            safety_level="safe",
        )
    )

    service_config = ServiceConfig(
        service_type=Service.RADARR,
        base_url="http://radarr",
        api_key="x",
        name="Radarr",
        enabled=True,
    )
    db.add(service_config)
    await db.flush()

    db.add(
        MovieArrRef(
            movie_id=movie.id,
            service_config_id=service_config.id,
            arr_movie_id=444,
            arr_movie_path="/media/movies/Correlation Movie (2022)",
            tmdb_id=1111,
        )
    )

    db.add(
        MovieVersion(
            movie_id=movie.id,
            service=Service.PLEX,
            service_item_id="item-1",
            service_media_id="media-1",
            library_id="library-1",
            library_name="Movies",
            path="/media/movies/Correlation Movie (2022)/Correlation Movie (2022).mkv",
            size=1024,
        )
    )

    await db.commit()
    return movie, identity


@pytest.mark.anyio
async def test_movie_graph_contains_identity_arr_and_health(
    db: AsyncSession,
) -> None:
    movie, _identity = await _seed_movie_identity(db)

    graph = await CorrelationService(db).media_graph(media_id=movie.id)

    assert graph.media_type is MediaType.MOVIE
    assert graph.identity.media_identity_id is not None
    assert graph.identity.canonical_ids.tmdb == "1111"
    assert graph.request_intelligence.request_state == "unknown"
    assert len(graph.arr_intelligence.ownership) == 1
    assert graph.arr_intelligence.ownership[0].provider == "radarr"
    assert graph.file_intelligence.total_size_bytes >= 1024
    assert graph.health.overall_health_score > 0


@pytest.mark.anyio
async def test_series_graph_supports_missing_ids(db: AsyncSession) -> None:
    series = Series(title="Series Without IDs", tmdb_id=2222, year=2020)
    db.add(series)
    await db.flush()

    db.add(
        MediaAsset(
            media_type=MediaType.SERIES,
            series_id=series.id,
            lifecycle_state="resolved",
            health_state="healthy",
            has_torrent=False,
        )
    )

    service_config = ServiceConfig(
        service_type=Service.SONARR,
        base_url="http://sonarr",
        api_key="x",
        name="Sonarr",
        enabled=True,
    )
    db.add(service_config)
    await db.flush()

    db.add(
        SeriesArrRef(
            series_id=series.id,
            service_config_id=service_config.id,
            arr_series_id=555,
            arr_series_path="/media/series/Series Without IDs",
            tmdb_id=2222,
        )
    )
    await db.commit()

    graph = await CorrelationService(db).media_graph(
        media_id=series.id,
        media_type=MediaType.SERIES,
    )

    assert graph.media_type is MediaType.SERIES
    assert graph.identity.canonical_ids.imdb is None
    assert graph.identity.canonical_ids.tvdb is None
    assert graph.request_intelligence.request_state == "unknown"


@pytest.mark.anyio
async def test_multiple_torrents_are_correlated_and_state_mapped(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    movie, _identity = await _seed_movie_identity(db)
    monkeypatch.setattr(
        service_manager,
        "_qbittorrent",
        _FakeQbitClient(
            [
                {
                    "hash": "A1",
                    "name": "Correlation Movie 2022 1080p",
                    "category": "radarr",
                    "state": "downloading",
                    "progress": 0.5,
                    "dlspeed": 2048,
                    "upspeed": 0,
                    "eta": 120,
                    "save_path": "/media/movies/Correlation Movie (2022)",
                },
                {
                    "hash": "A2",
                    "name": "Correlation Movie 2022 REPACK",
                    "category": "radarr",
                    "state": "uploading",
                    "progress": 1.0,
                    "dlspeed": 0,
                    "upspeed": 500,
                    "eta": 0,
                    "save_path": "/media/movies/Correlation Movie (2022)",
                },
            ]
        ),
        raising=False,
    )

    graph = await CorrelationService(db).media_graph(media_id=movie.id)

    assert len(graph.torrent_intelligence.torrents) == 2
    states = {row.computed_state for row in graph.torrent_intelligence.torrents}
    assert "downloading" in states
    assert "seeding" in states


@pytest.mark.anyio
async def test_request_intelligence_and_timeline_include_overseerr(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    movie, _identity = await _seed_movie_identity(db)

    seerr_request = SeerrRequest(
        id=900,
        status=SeerrRequestStatus.APPROVED,
        media_id=321,
        media_type=MediaType.MOVIE,
        tmdb_id=1111,
        created_at=datetime.now(UTC),
        requested_by_id=77,
        is_4k=False,
        raw={"modifiedAt": datetime.now(UTC).isoformat()},
    )
    monkeypatch.setattr(
        service_manager,
        "_seerr",
        _FakeSeerrClient(movie_requests=[seerr_request], tv_requests=[]),
        raising=False,
    )

    graph = await CorrelationService(db).media_graph(media_id=movie.id)

    assert graph.request_intelligence.request_state == "known"
    assert len(graph.request_intelligence.requests) == 1
    assert any(event.event == "requested" for event in graph.timeline)
    assert any(event.event == "approved" for event in graph.timeline)


@pytest.mark.anyio
async def test_health_flags_missing_artwork(
    db: AsyncSession,
) -> None:
    movie = Movie(title="No Artwork Movie", tmdb_id=3333, year=2021)
    db.add(movie)
    await db.flush()

    db.add(
        MediaAsset(
            media_type=MediaType.MOVIE,
            movie_id=movie.id,
            lifecycle_state="imported",
            health_state="healthy",
            has_torrent=False,
        )
    )
    await db.commit()

    graph = await CorrelationService(db).media_graph(media_id=movie.id)

    artwork_category = next(
        category for category in graph.health.categories if category.key == "artwork"
    )
    assert artwork_category.status == "risk"
    assert artwork_category.reasons


@pytest.mark.anyio
async def test_ambiguous_media_id_requires_media_type(db: AsyncSession) -> None:
    movie = Movie(title="Dup ID Movie", tmdb_id=4444)
    series = Series(title="Dup ID Series", tmdb_id=5555)
    db.add_all([movie, series])
    await db.commit()

    assert movie.id == series.id

    with pytest.raises(ValueError, match="Ambiguous media id"):
        await CorrelationService(db).media_graph(media_id=movie.id)
