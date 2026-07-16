from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.api.routes.dashboard import get_dashboard
from backend.core.artwork import CENTRAL_PLACEHOLDER_POSTER_URL
from backend.database import Base
from backend.database.models import Movie, ReclaimCandidate, Series, TaskRun, User
from backend.enums import MediaType, Task, TaskStatus, UserRole
from backend.services.mie.operations_service import OperationsService


def _admin_user() -> User:
    return User(username="admin", password_hash="x", role=UserRole.ADMIN)


@pytest.mark.anyio
async def test_dashboard_totals_exclude_soft_deleted_media() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        user = _admin_user()
        removed_movie = Movie(title="Removed Movie", tmdb_id=2, size=200)
        removed_movie.removed_at = datetime.now(UTC)
        removed_series = Series(title="Removed Series", tmdb_id=4, size=400)
        removed_series.removed_at = datetime.now(UTC)
        db.add_all(
            [
                user,
                Movie(title="Active Movie", tmdb_id=1, size=100),
                removed_movie,
                Series(title="Active Series", tmdb_id=3, size=300),
                removed_series,
            ]
        )
        await db.flush()

        response = await get_dashboard(current_user=user, db=db)

    await engine.dispose()

    assert response.kpis.total_movies == 1
    assert response.kpis.total_series == 1
    assert response.kpis.total_movies_size_bytes == 100
    assert response.kpis.total_series_size_bytes == 300


@pytest.mark.anyio
async def test_dashboard_materializes_provider_rating_task_history() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        user = _admin_user()
        db.add_all(
            [
                user,
                TaskRun(
                    task=Task.MDBLIST_RATINGS_REFRESH,
                    status=TaskStatus.COMPLETED,
                ),
            ]
        )
        await db.flush()

        response = await get_dashboard(current_user=user, db=db)

    await engine.dispose()

    assert any(
        item.title == "Refresh MDBList Ratings completed"
        for item in response.activity
    )


@pytest.mark.anyio
async def test_dashboard_decision_summary_resolves_opportunity_posters() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        user = _admin_user()
        with_poster = Movie(
            title="With Poster",
            tmdb_id=8001,
            poster_url="/poster-with.jpg",
            size=1,
        )
        without_poster = Movie(
            title="Without Poster",
            tmdb_id=8002,
            poster_url=None,
            size=1,
        )
        db.add_all([user, with_poster, without_poster])
        await db.flush()

        db.add_all(
            [
                ReclaimCandidate(
                    media_type=MediaType.MOVIE,
                    matched_rule_ids=[1],
                    matched_criteria={"r": 1},
                    movie_id=with_poster.id,
                    reason="with poster",
                    estimated_space_bytes=100,
                ),
                ReclaimCandidate(
                    media_type=MediaType.MOVIE,
                    matched_rule_ids=[2],
                    matched_criteria={"r": 2},
                    movie_id=without_poster.id,
                    reason="without poster",
                    estimated_space_bytes=50,
                ),
            ]
        )
        await db.flush()

        response = await get_dashboard(current_user=user, db=db)

    await engine.dispose()

    posters = {
        item.title: item.poster_url
        for item in response.decision_summary.recently_reclaimable
    }
    assert posters["With Poster"] == "https://image.tmdb.org/t/p/w342/poster-with.jpg"
    assert posters["Without Poster"] == CENTRAL_PLACEHOLDER_POSTER_URL


@pytest.mark.anyio
async def test_dashboard_decision_summary_uses_operations_engine_counts() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        user = _admin_user()
        movie = Movie(title="Ops Driven", tmdb_id=9101, size=10)
        db.add_all([user, movie])
        await db.flush()
        db.add(
            ReclaimCandidate(
                media_type=MediaType.MOVIE,
                matched_rule_ids=[1],
                matched_criteria={"rule": "ops"},
                movie_id=movie.id,
                reason="ops candidate",
                estimated_space_bytes=4096,
            )
        )
        await db.commit()

        dashboard = await get_dashboard(current_user=user, db=db)
        workspace = await OperationsService(db).workspace()

    await engine.dispose()

    card_by_key = {card.key: card for card in workspace.overview.cards}
    assert dashboard.decision_summary.recoverable_space_bytes == card_by_key["space_recovery"].count
    assert dashboard.decision_summary.blocked.waiting == card_by_key["import_pending"].count
    assert dashboard.decision_summary.ready_today.movies == card_by_key["ready_to_detach"].count
    assert {item.operation_key for item in dashboard.decision_summary.top_opportunities if item.operation_key} <= {
        card.key for card in workspace.overview.cards if card.count > 0
    }
