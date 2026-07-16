from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import pytest

from backend.api.routes.correlation import (
    get_torrent_correlation,
    list_correlation_torrents,
)
from backend.core.service_manager import service_manager
from backend.database import Base
from backend.database.models import Movie, MovieVersion, ProtectedMedia, User
from backend.enums import MediaType, Service, UserRole
from backend.models.correlation import CorrelationTorrentSummary
from backend.services.correlation import MediaCorrelationService


correlation_service = MediaCorrelationService()


class _FakeQBClient:
    async def get_torrents(self) -> list[dict[str, object]]:
        return [
            {
                "hash": "ABC123",
                "name": "The Matrix 1999 1080p",
                "category": "radarr",
                "state": "uploading",
                "save_path": "/downloads/movies",
            },
            {
                "hash": "DEF456",
                "name": "Unmapped Item",
                "category": "misc",
                "state": "pausedUP",
                "save_path": "/downloads/other",
            },
        ]


def _admin_user() -> User:
    return User(username="admin", password_hash="x", role=UserRole.ADMIN, permissions=[])


@pytest.mark.anyio
async def test_correlation_torrents_list_and_unknown_detail() -> None:
    previous = service_manager._qbittorrent
    service_manager._qbittorrent = _FakeQBClient()  # type: ignore[assignment]
    try:
        response = await list_correlation_torrents(_admin_user())
        assert len(response.items) == 2
        first_id = response.items[0].id

        engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_maker = async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )
        try:
            async with session_maker() as db_session:
                detail = await get_torrent_correlation(first_id, _admin_user(), db_session)
                assert detail.fields.torrent
                assert detail.fields.provider == Service.QBITTORRENT.value
                assert detail.fields.import_status == "Unknown"
                assert all(node.value for node in detail.nodes)
        finally:
            await engine.dispose()
    finally:
        service_manager._qbittorrent = previous


@pytest.mark.anyio
async def test_correlation_detail_resolves_movie_relationships() -> None:
    previous = service_manager._qbittorrent
    service_manager._qbittorrent = _FakeQBClient()  # type: ignore[assignment]

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_maker() as db_session:
            movie = Movie(title="The Matrix", tmdb_id=603, year=1999, view_count=1)
            db_session.add(movie)
            await db_session.flush()

            version = MovieVersion(
                movie_id=movie.id,
                service=Service.PLEX,
                service_item_id="9001",
                service_media_id="9001-1",
                library_id="lib-movie",
                library_name="Movies",
                path="/downloads/movies/The Matrix (1999)/The.Matrix.1999.mkv",
                size=100,
            )
            db_session.add(version)
            await db_session.flush()

            db_session.add(
                ProtectedMedia(
                    media_type=MediaType.MOVIE,
                    movie_id=movie.id,
                    movie_version_id=version.id,
                    source="manual",
                )
            )
            await db_session.commit()

            detail = await get_torrent_correlation("abc123", _admin_user(), db_session)
            assert detail.fields.movie.startswith("The Matrix")
            assert detail.fields.file.endswith("The.Matrix.1999.mkv")
            assert detail.fields.media_server.startswith(Service.PLEX.value)
            assert detail.fields.watch_status == "Watched"
            assert detail.fields.protection_status == "Protected"
            assert detail.fields.import_status == "Imported"
            assert detail.fields.provider == Service.PLEX.value
    finally:
        service_manager._qbittorrent = previous
        await engine.dispose()


@pytest.mark.anyio
async def test_correlation_requires_qbittorrent_runtime_client() -> None:
    previous = service_manager._qbittorrent
    service_manager._qbittorrent = None

    try:
        with pytest.raises(HTTPException) as exc:
            await list_correlation_torrents(_admin_user())
        assert exc.value.status_code == 404
    finally:
        service_manager._qbittorrent = previous


@pytest.mark.anyio
async def test_correlation_prefers_strong_path_identity_and_avoids_cross_title_collision() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_maker() as db_session:
        wrong_movie = Movie(title="Matrix Revisited", tmdb_id=999001, year=2001, poster_url="/wrong.jpg")
        right_movie = Movie(title="The Matrix", tmdb_id=603, year=1999, poster_url="/right.jpg")
        db_session.add_all([wrong_movie, right_movie])
        await db_session.flush()

        # Wrong candidate shares token noise but no stable path overlap.
        db_session.add(
            MovieVersion(
                movie_id=wrong_movie.id,
                service=Service.PLEX,
                service_item_id="wrong-1",
                service_media_id="wrong-1",
                library_id="movies",
                library_name="Movies",
                path="/library/other/Matrix.Revisited.2001.1080p.mkv",
                size=100,
            )
        )
        # Right candidate has deterministic save_path/path overlap.
        db_session.add(
            MovieVersion(
                movie_id=right_movie.id,
                service=Service.PLEX,
                service_item_id="right-1",
                service_media_id="right-1",
                library_id="movies",
                library_name="Movies",
                path="/downloads/movies/The Matrix (1999)/The.Matrix.1999.1080p.mkv",
                size=100,
            )
        )
        await db_session.commit()

        summary = CorrelationTorrentSummary(
            id="hash-matrix",
            hash="hash-matrix",
            name="The Matrix 1999 1080p",
            category="radarr",
            state="uploading",
            save_path="/downloads/movies/The Matrix (1999)",
            provider=Service.QBITTORRENT.value,
        )
        resolved = await correlation_service.resolve_torrent_artwork(db_session, summary)
        assert resolved.media_id == right_movie.id
        assert resolved.poster_url == "/right.jpg"

    await engine.dispose()
