from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.service_manager import service_manager
from backend.database import Base
from backend.database.models import Movie, OperationHistory, ProtectedMedia, ReclaimCandidate
from backend.enums import MediaType, SeerrRequestStatus
from backend.models.services.seerr import SeerrRequest
from backend.services.mie.intelligence_service import MediaIntelligenceService


class StubSeerrClient:
    def __init__(
        self,
        *,
        requests: list[SeerrRequest] | None = None,
        movie_requests: list[SeerrRequest] | None = None,
    ) -> None:
        self._requests = requests or []
        self._movie_requests = movie_requests or []

    async def get_all_requests(self, *, filter: str = "all") -> list[SeerrRequest]:
        return list(self._requests)

    async def get_movie_requests(self, tmdb_id: int) -> list[SeerrRequest]:
        return [req for req in self._movie_requests if req.tmdb_id == tmdb_id]

    async def get_tv_requests(self, tmdb_id: int) -> list[SeerrRequest]:
        return []


@pytest.mark.anyio
async def test_mie_overview_includes_health_and_overseerr_counts() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    original_seerr = service_manager._seerr
    service_manager._seerr = StubSeerrClient(
        requests=[
            SeerrRequest(
                id=10,
                status=SeerrRequestStatus.PENDING,
                media_id=100,
                media_type=MediaType.MOVIE,
                tmdb_id=9001,
                created_at=datetime.now(UTC),
                requested_by_id=1,
                is_4k=False,
            ),
            SeerrRequest(
                id=11,
                status=SeerrRequestStatus.APPROVED,
                media_id=101,
                media_type=MediaType.MOVIE,
                tmdb_id=9002,
                created_at=datetime.now(UTC),
                requested_by_id=2,
                is_4k=False,
            ),
            SeerrRequest(
                id=12,
                status=SeerrRequestStatus.COMPLETED,
                media_id=102,
                media_type=MediaType.MOVIE,
                tmdb_id=9003,
                created_at=datetime.now(UTC),
                requested_by_id=3,
                is_4k=False,
            ),
        ]
    )

    try:
        async with session_maker() as db:
            db.add(Movie(title="Lifecycle Example", tmdb_id=9001))
            await db.commit()

            response = await MediaIntelligenceService(db).overview()
    finally:
        service_manager._seerr = original_seerr
        await engine.dispose()

    assert response.total_assets >= 1
    assert response.overseerr_pending == 1
    assert response.overseerr_approved == 1
    assert response.overseerr_completed == 1
    assert 0 <= response.health.score <= 100
    assert response.health.factors


@pytest.mark.anyio
async def test_mie_timeline_and_relationships_include_overseerr_and_operations() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    movie_request = SeerrRequest(
        id=55,
        status=SeerrRequestStatus.PENDING,
        media_id=555,
        media_type=MediaType.MOVIE,
        tmdb_id=7777,
        created_at=now,
        requested_by_id=42,
        is_4k=True,
    )
    original_seerr = service_manager._seerr
    service_manager._seerr = StubSeerrClient(
        requests=[movie_request], movie_requests=[movie_request]
    )

    try:
        async with session_maker() as db:
            movie = Movie(title="Graph Example", tmdb_id=7777)
            db.add(movie)
            await db.flush()
            movie_id = movie.id

            db.add(
                ReclaimCandidate(
                    media_type=MediaType.MOVIE,
                    matched_rule_ids=[1],
                    matched_criteria={"rule": "graph"},
                    movie_id=movie.id,
                    reason="Graph candidate",
                    estimated_space_bytes=1024,
                )
            )
            db.add(
                ProtectedMedia(
                    media_type=MediaType.MOVIE,
                    movie_id=movie.id,
                    reason="Pinned",
                    permanent=True,
                )
            )
            db.add(
                OperationHistory(
                    action="detach_torrent",
                    target_type="movie",
                    target_id=str(movie.id),
                    result="completed",
                    safety_level="safe",
                    recovery_bytes=0,
                )
            )
            await db.commit()

            service = MediaIntelligenceService(db)
            timeline = await service.timeline(limit=50)
            graph = await service.relationships(
                media_type=MediaType.MOVIE,
                media_id=movie_id,
            )
    finally:
        service_manager._seerr = original_seerr
        await engine.dispose()

    event_types = {item.event_type for item in timeline.items}
    assert "overseerr_request" in event_types
    assert "operation" in event_types

    node_kinds = {node.kind for node in graph.nodes}
    assert "overseerr_request" in node_kinds
    assert "operation" in node_kinds
    assert graph.root == f"media:{MediaType.MOVIE.value}:{movie_id}"
