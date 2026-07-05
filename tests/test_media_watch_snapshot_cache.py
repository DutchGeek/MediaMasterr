from datetime import UTC, datetime, timedelta

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
