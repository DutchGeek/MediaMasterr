from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from backend.enums import MediaType
from backend.models.media import MediaWatchSnapshot
from backend.services.plex import PlexService, _history_record_rating_key


def test_get_section_metadata_items_paginates_until_total_size(monkeypatch) -> None:
    async def run() -> None:
        calls: list[dict[str, Any]] = []
        pages = [
            {
                "MediaContainer": {
                    "size": 2,
                    "totalSize": 5,
                    "Metadata": [{"ratingKey": "1"}, {"ratingKey": "2"}],
                }
            },
            {
                "MediaContainer": {
                    "size": 2,
                    "totalSize": 5,
                    "Metadata": [{"ratingKey": "3"}, {"ratingKey": "4"}],
                }
            },
            {
                "MediaContainer": {
                    "size": 1,
                    "totalSize": 5,
                    "Metadata": [{"ratingKey": "5"}],
                }
            },
        ]

        async def fake_make_request(
            self: PlexService,
            endpoint: str,
            params: dict[str, Any] | None = None,
            **kwargs: Any,
        ) -> tuple[dict[str, Any], int]:
            assert endpoint == "library/sections/1/all"
            assert kwargs["timeout"] == 123
            assert params is not None
            calls.append(dict(params))
            return pages[len(calls) - 1], 200

        monkeypatch.setattr(PlexService, "_make_request", fake_make_request)
        service = PlexService("token", "http://plex.local")

        items = await service._get_section_metadata_items(
            section_id="1",
            params={"type": 4},
            page_size=2,
            timeout=123,
        )

        assert [item["ratingKey"] for item in items] == ["1", "2", "3", "4", "5"]
        assert calls == [
            {
                "type": 4,
                "X-Plex-Container-Start": 0,
                "X-Plex-Container-Size": 2,
            },
            {
                "type": 4,
                "X-Plex-Container-Start": 2,
                "X-Plex-Container-Size": 2,
            },
            {
                "type": 4,
                "X-Plex-Container-Start": 4,
                "X-Plex-Container-Size": 2,
            },
        ]

    asyncio.run(run())


def test_history_record_rating_key_falls_back_to_metadata_paths() -> None:
    record = {
        "key": "/library/metadata/62906",
        "parentKey": "/library/metadata/62000",
        "grandparentKey": "/library/metadata/61155",
    }

    assert _history_record_rating_key(record, "ratingKey") == "62906"
    assert _history_record_rating_key(record, "parentRatingKey") == "62000"
    assert _history_record_rating_key(record, "grandparentRatingKey") == "61155"


def test_watched_user_snapshots_accept_grandparent_key_path(monkeypatch) -> None:
    async def run() -> None:
        watched_at = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)

        async def fake_get_movies(
            self: PlexService, included_libraries: list[str] | None = None
        ) -> list[object]:
            return []

        async def fake_get_series(
            self: PlexService, included_libraries: list[str] | None = None
        ) -> list[object]:
            return [
                SimpleNamespace(
                    id="61155",
                    external_ids=SimpleNamespace(tmdb=12345),
                )
            ]

        async def fake_get_sections(self: PlexService) -> list[dict[str, str]]:
            return [{"key": "2", "title": "TV Shows", "type": "show"}]

        async def fake_get_history(
            self: PlexService, **kwargs: object
        ) -> list[dict[str, object]]:
            return [
                {
                    "type": "episode",
                    "ratingKey": "62906",
                    "grandparentKey": "/library/metadata/61155",
                    "accountID": "490001441",
                    "viewedAt": int(watched_at.timestamp()),
                }
            ]

        async def fake_get_users(self: PlexService) -> dict[str, str]:
            return {"490001441": "alice"}

        monkeypatch.setattr(PlexService, "get_movies", fake_get_movies)
        monkeypatch.setattr(PlexService, "get_series", fake_get_series)
        monkeypatch.setattr(PlexService, "get_library_sections", fake_get_sections)
        monkeypatch.setattr(PlexService, "_get_all_history_records", fake_get_history)
        monkeypatch.setattr(PlexService, "_get_plex_tv_user_map", fake_get_users)

        service = PlexService("token", "http://plex.local")
        (
            snapshots,
            max_viewed_at,
        ) = await service.get_watched_user_snapshots_with_cursor()

        assert snapshots == [
            MediaWatchSnapshot(
                media_type=MediaType.SERIES,
                tmdb_id=12345,
                watch_user_key="alice",
                last_watched_at=watched_at,
                source_item_id="62906",
            )
        ]
        assert max_viewed_at == watched_at

    asyncio.run(run())
