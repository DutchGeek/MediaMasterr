import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.database.models import Episode, Season, Series
from backend.enums import MediaType, Service
from backend.models.media import MediaWatchSnapshot
from backend.services.media_watch_snapshot_cache import MediaWatchSnapshotCache


def test_legacy_plex_sync_state_requires_full_rebuild() -> None:
    now = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    recent = (now - timedelta(hours=1)).isoformat()
    legacy_state = {
        "plex_last_viewed_at": recent,
        "plex_last_full_sync_at": recent,
    }

    assert MediaWatchSnapshotCache._plex_sync_state_requires_full_rebuild(
        legacy_state, now
    )


def test_current_plex_sync_state_remains_incremental_until_interval_expires() -> None:
    now = datetime(2026, 7, 5, 12, 0, tzinfo=UTC)
    recent = (now - timedelta(hours=1)).isoformat()
    current_state = {
        "format_version": MediaWatchSnapshotCache._PLEX_FORMAT_VERSION,
        "plex_last_viewed_at": recent,
        "plex_last_full_sync_at": recent,
    }

    assert not MediaWatchSnapshotCache._plex_sync_state_requires_full_rebuild(
        current_state, now
    )


def test_current_plex_sync_state_rebuilds_after_interval() -> None:
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    old = (now - MediaWatchSnapshotCache._PLEX_FULL_REBUILD_INTERVAL).isoformat()
    current_state = {
        "format_version": MediaWatchSnapshotCache._PLEX_FORMAT_VERSION,
        "plex_last_viewed_at": old,
        "plex_last_full_sync_at": old,
    }

    assert MediaWatchSnapshotCache._plex_sync_state_requires_full_rebuild(
        current_state, now
    )


def test_episode_watch_rows_resolve_provider_episode_ids(tmp_path) -> None:
    async def run() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'watch.db'}")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            series = Series(title="Example", tmdb_id=5920)
            session.add(series)
            await session.flush()
            season = Season(series_id=series.id, season_number=3)
            session.add(season)
            await session.flush()
            session.add(
                Episode(
                    season_id=season.id,
                    episode_number=2,
                    plex_rating_key="62906",
                )
            )
            await session.flush()

            rows, unmatched = await MediaWatchSnapshotCache._build_episode_watch_rows(
                session=session,
                source_service=Service.PLEX,
                source_service_config_id=4,
                snapshots=[
                    MediaWatchSnapshot(
                        media_type=MediaType.SERIES,
                        tmdb_id=5920,
                        watch_user_key="Alice",
                        last_watched_at=datetime(2026, 7, 4, tzinfo=UTC),
                        source_item_id="62906",
                    )
                ],
            )

        await engine.dispose()
        assert unmatched == 0
        assert len(rows) == 1
        assert rows[0].series_tmdb_id == 5920
        assert rows[0].season_number == 3
        assert rows[0].episode_number == 2
        assert rows[0].watch_user_key_normalized == "alice"

    asyncio.run(run())
