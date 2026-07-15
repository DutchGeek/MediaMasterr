from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import niquests.exceptions as niq_exceptions
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.api.routes.qbittorrent import get_qbittorrent_overview
from backend.api.routes.settings import services
from backend.api.routes.settings.services import set_service_settings
from backend.core.service_manager import service_manager
from backend.database import Base
from backend.core.artwork import CENTRAL_PLACEHOLDER_POSTER_URL
from backend.database.models import Movie, MovieVersion, User
from backend.enums import Service, UserRole
from backend.models.settings import ServiceConfigUpdate
from backend.services.qbittorrent import QBittorrentClient


class _FakeQBClient:
    async def get_app_version(self) -> str:
        return "4.6.7"

    async def get_webapi_version(self) -> str:
        return "2.9.3"

    async def get_transfer_info(self) -> dict[str, int]:
        return {"dl_info_speed": 1234, "up_info_speed": 456}

    async def get_torrents(self) -> list[dict[str, object]]:
        return [
            {
                "name": "Ubuntu ISO",
                "category": "linux",
                "state": "downloading",
                "progress": 0.5,
                "size": 1000,
                "ratio": 0.3,
                "eta": 3600,
                "dlspeed": 100,
                "upspeed": 0,
                "tracker": "tracker.example",
                "save_path": "/downloads",
            },
            {
                "name": "Fedora",
                "category": "",
                "state": "uploading",
                "progress": 1.0,
                "size": 2000,
                "ratio": 2.1,
                "eta": -1,
                "dlspeed": 0,
                "upspeed": 20,
                "tracker": "tracker.example",
                "save_path": "/downloads",
            },
            {
                "name": "Archive",
                "category": "misc",
                "state": "pausedUP",
                "progress": 1.0,
                "size": 3000,
                "ratio": 1.0,
                "eta": 0,
                "dlspeed": 0,
                "upspeed": 0,
                "tracker": "",
                "save_path": "/downloads/archive",
            },
            {
                "name": "Old Torrent",
                "category": "misc",
                "state": "stalledDL",
                "progress": 0.2,
                "size": 4000,
                "ratio": 0.0,
                "eta": 999,
                "dlspeed": 0,
                "upspeed": 0,
                "tracker": "",
                "save_path": "/downloads/archive",
            },
        ]


def _admin_user() -> User:
    return User(username="admin", password_hash="x", role=UserRole.ADMIN, permissions=[])


class _FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise niq_exceptions.HTTPError(f"status {self.status_code}")


class _FakeSession:
    def __init__(self, login: _FakeResponse, version: _FakeResponse) -> None:
        self._login = login
        self._version = version

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(self, _url: str, **_kwargs: object) -> _FakeResponse:
        return self._login

    async def get(self, _url: str, **_kwargs: object) -> _FakeResponse:
        return self._version

    async def close(self) -> None:
        return None


@pytest.mark.anyio
async def test_qbittorrent_overview_is_read_only_summary() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    previous = service_manager._qbittorrent
    service_manager._qbittorrent = _FakeQBClient()  # type: ignore[assignment]
    try:
        async with session_maker() as db:
            payload = await get_qbittorrent_overview(_admin_user(), db=db)
    finally:
        service_manager._qbittorrent = previous
        await engine.dispose()

    assert payload.app_version == "4.6.7"
    assert payload.webapi_version == "2.9.3"
    assert payload.metrics.active_downloads == 1
    assert payload.metrics.active_uploads == 2
    assert payload.metrics.seeding == 1
    assert payload.metrics.paused == 1
    assert payload.metrics.completed == 2
    assert payload.metrics.stalled == 1
    assert payload.metrics.download_speed == 1234
    assert payload.metrics.upload_speed == 456
    assert len(payload.torrents) == 4
    assert all(row.poster_url == CENTRAL_PLACEHOLDER_POSTER_URL for row in payload.torrents)


@pytest.mark.anyio
async def test_qbittorrent_overview_requires_runtime_client() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    previous = service_manager._qbittorrent
    service_manager._qbittorrent = None
    try:
        with pytest.raises(HTTPException) as exc:
            async with session_maker() as db:
                await get_qbittorrent_overview(_admin_user(), db=db)
    finally:
        service_manager._qbittorrent = previous
        await engine.dispose()

    assert exc.value.status_code == 404


@pytest.mark.anyio
async def test_qbittorrent_overview_uses_correlated_media_poster() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    previous = service_manager._qbittorrent
    service_manager._qbittorrent = _FakeQBClient()  # type: ignore[assignment]
    try:
        async with session_maker() as db:
            movie = Movie(title="Ubuntu ISO", tmdb_id=99123, poster_url="/u.jpg")
            db.add(movie)
            await db.flush()

            db.add(
                MovieVersion(
                    movie_id=movie.id,
                    service=Service.PLEX,
                    service_item_id="mv-1",
                    service_media_id="media-1",
                    library_id="lib-1",
                    library_name="Movies",
                    path="/downloads/ubuntu-iso/movie.mkv",
                )
            )
            await db.commit()

            payload = await get_qbittorrent_overview(_admin_user(), db=db)
    finally:
        service_manager._qbittorrent = previous
        await engine.dispose()

    ubuntu_row = next(row for row in payload.torrents if row.name == "Ubuntu ISO")
    assert ubuntu_row.poster_url == "https://image.tmdb.org/t/p/w342/u.jpg"


@pytest.mark.anyio
async def test_qbittorrent_settings_pass_extra_settings_to_connection_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    try:
        async with session_maker() as db_session:
            test_mock = AsyncMock(return_value=(True, ""))
            enqueue_mock = AsyncMock(return_value=SimpleNamespace(id=321))
            monkeypatch.setattr(service_manager, "test_service", test_mock)
            monkeypatch.setattr(services, "enqueue_background_job", enqueue_mock)

            response = await set_service_settings(
                ServiceConfigUpdate(
                    service_type=Service.QBITTORRENT,
                    name="qBittorrent",
                    base_url="localhost:8080",
                    api_key="secret-password",
                    enabled=True,
                    extra_settings={"username": "qb-user", "use_https": True},
                ),
                _admin_user(),
                db_session,
            )

            assert response["data"]["service_type"] == Service.QBITTORRENT
            test_mock.assert_awaited_once_with(
                Service.QBITTORRENT,
                "localhost:8080",
                "secret-password",
                {"username": "qb-user", "use_https": True},
            )
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_qbittorrent_test_service_uses_post_login_and_get_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.qbittorrent.niquests.AsyncSession",
        lambda: _FakeSession(
            login=_FakeResponse(200, "Ok."),
            version=_FakeResponse(200, "4.6.7"),
        ),
    )

    result = await QBittorrentClient.test_service(
        "localhost:8080",
        "password",
        {"username": "qb-user", "use_https": False},
    )

    assert result is True


@pytest.mark.anyio
async def test_qbittorrent_test_service_reports_authentication_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.services.qbittorrent.niquests.AsyncSession",
        lambda: _FakeSession(
            login=_FakeResponse(200, "Fails."),
            version=_FakeResponse(200, "4.6.7"),
        ),
    )

    with pytest.raises(ValueError, match="Authentication failed"):
        await QBittorrentClient.test_service(
            "localhost:8080",
            "password",
            {"username": "qb-user", "use_https": False},
        )


@pytest.mark.anyio
async def test_qbittorrent_test_service_reports_connection_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ConnectionRefusedSession(_FakeSession):
        async def post(self, _url: str, **_kwargs: object) -> _FakeResponse:
            raise niq_exceptions.ConnectionError("refused")

    monkeypatch.setattr(
        "backend.services.qbittorrent.niquests.AsyncSession",
        lambda: _ConnectionRefusedSession(
            login=_FakeResponse(200, "Ok."),
            version=_FakeResponse(200, "4.6.7"),
        ),
    )

    with pytest.raises(ValueError, match="Connection refused"):
        await QBittorrentClient.test_service(
            "localhost:8080",
            "password",
            {"username": "qb-user", "use_https": False},
        )
