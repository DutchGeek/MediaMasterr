from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.service_manager import service_manager
from backend.database import Base
from backend.database.models import (
    FilesystemIndexEntry,
    FilesystemRoot,
    MediaAsset,
    Movie,
    MovieVersion,
)
from backend.enums import MediaType, Service
from backend.services.mie.downloads_intelligence import DownloadsIntelligenceService


class _FakeQbitClient:
    def __init__(self, torrents: list[dict[str, object]]) -> None:
        self._torrents = torrents

    async def get_torrents(self) -> list[dict[str, object]]:
        return self._torrents


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


@pytest.mark.anyio
async def test_downloads_classification_and_health_summary(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)

    root = FilesystemRoot(name="Downloads", path="/media/downloads", enabled=True)
    db.add(root)
    await db.flush()

    movie = Movie(title="Imported Movie", tmdb_id=81001, year=2023)
    db.add(movie)
    await db.flush()

    db.add(
        MediaAsset(
            media_type=MediaType.MOVIE,
            movie_id=movie.id,
            lifecycle_state="imported",
            has_torrent=False,
        )
    )
    db.add(
        MovieVersion(
            movie_id=movie.id,
            service=Service.PLEX,
            service_item_id="x",
            service_media_id="y",
            library_id="lib",
            library_name="Movies",
            path="/media/movies/Imported Movie (2023)/Imported Movie (2023).mkv",
            size=1024,
        )
    )

    db.add_all(
        [
            FilesystemIndexEntry(
                root_id=root.id,
                path="/media/downloads/Imported Movie (2023)/Imported Movie (2023).mkv",
                entry_type="file",
                size_bytes=1000,
                modified_at=now - timedelta(hours=24),
                metadata_json={"movie_id": movie.id},
            ),
            FilesystemIndexEntry(
                root_id=root.id,
                path="/media/downloads/Unknown Blob/file.bin",
                entry_type="file",
                size_bytes=200,
                modified_at=now - timedelta(hours=50),
                metadata_json={},
            ),
            FilesystemIndexEntry(
                root_id=root.id,
                path="/media/downloads/Active Torrent/data.mkv",
                entry_type="file",
                size_bytes=300,
                modified_at=now - timedelta(hours=1),
                metadata_json={},
            ),
        ]
    )
    await db.commit()

    monkeypatch.setattr(
        service_manager,
        "_qbittorrent",
        _FakeQbitClient(
            [
                {
                    "hash": "abc",
                    "name": "Active Torrent",
                    "save_path": "/media/downloads/Active Torrent",
                    "state": "downloading",
                    "progress": 0.45,
                }
            ]
        ),
        raising=False,
    )

    result = await DownloadsIntelligenceService(db).run()

    assert result.summary.total_download_space == 1500
    assert result.summary.active_downloads >= 1
    assert result.summary.imported_but_still_present >= 1
    assert result.summary.unknown_downloads >= 1

    by_path = {item.path: item for item in result.items}
    assert (
        by_path[
            "/media/downloads/Imported Movie (2023)/Imported Movie (2023).mkv"
        ].cleanup_classification
        in {"safe_to_delete", "duplicate_download", "safe_to_archive"}
    )
    assert (
        by_path["/media/downloads/Unknown Blob/file.bin"].cleanup_classification
        == "needs_investigation"
    )


@pytest.mark.anyio
async def test_download_recommendation_contains_explainability(
    db: AsyncSession,
) -> None:
    root = FilesystemRoot(name="downloads-root", path="/media/downloads", enabled=True)
    db.add(root)
    await db.flush()

    db.add(
        FilesystemIndexEntry(
            root_id=root.id,
            path="/media/downloads/orphaned/item.mkv",
            entry_type="file",
            size_bytes=2048,
            metadata_json={},
        )
    )
    await db.commit()

    result = await DownloadsIntelligenceService(db).run()

    assert result.recommendations
    rec = result.recommendations[0]
    assert rec.explanation is not None
    assert rec.reasons
    assert rec.confidence is not None
    assert rec.graph_references
