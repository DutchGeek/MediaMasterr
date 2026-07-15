from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.artwork import CENTRAL_PLACEHOLDER_POSTER_URL
from backend.database import Base
from backend.database.models import CleanupPlan, Movie, ReclaimCandidate
from backend.enums import MediaType
from backend.services.mie.operations_service import OperationsService


@pytest.mark.anyio
async def test_operations_overview_includes_space_recovery_card() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie = Movie(title="Example", tmdb_id=1001, size=2_000_000)
        db.add(movie)
        await db.flush()

        db.add(
            ReclaimCandidate(
                media_type=MediaType.MOVIE,
                matched_rule_ids=[1],
                matched_criteria={"rule": "test"},
                movie_id=movie.id,
                reason="Rule matched",
                estimated_space_bytes=1_500_000,
            )
        )
        await db.commit()

        overview = await OperationsService(db).overview()

    await engine.dispose()

    cards_by_key = {card.key: card for card in overview.cards}
    assert cards_by_key["space_recovery"].count == 1_500_000


@pytest.mark.anyio
async def test_operations_cleanup_plan_listing_returns_saved_plan() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        db.add(
            CleanupPlan(
                name="Weekly Cleanup",
                status="draft",
                operation_count=27,
                estimated_recovery_bytes=184 * 1024 * 1024 * 1024,
                safe_count=26,
                review_required_count=1,
            )
        )
        await db.commit()

        response = await OperationsService(db).cleanup_plans()

    await engine.dispose()

    assert len(response.plans) == 1
    assert response.plans[0].name == "Weekly Cleanup"
    assert response.plans[0].operation_count == 27


@pytest.mark.anyio
async def test_operations_recommendations_resolve_posters() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie_with_poster = Movie(
            title="With Poster",
            tmdb_id=3001,
            poster_url="/poster-a.jpg",
        )
        movie_without_poster = Movie(
            title="Without Poster",
            tmdb_id=3002,
            poster_url=None,
        )
        db.add_all([movie_with_poster, movie_without_poster])
        await db.flush()

        db.add_all(
            [
                ReclaimCandidate(
                    media_type=MediaType.MOVIE,
                    matched_rule_ids=[1],
                    matched_criteria={"rule": "poster"},
                    movie_id=movie_with_poster.id,
                    reason="Poster available",
                    estimated_space_bytes=1,
                ),
                ReclaimCandidate(
                    media_type=MediaType.MOVIE,
                    matched_rule_ids=[2],
                    matched_criteria={"rule": "placeholder"},
                    movie_id=movie_without_poster.id,
                    reason="Poster missing",
                    estimated_space_bytes=2,
                ),
            ]
        )
        await db.commit()

        response = await OperationsService(db).recommendations()

    await engine.dispose()

    posters = {item.title: item.poster_url for item in response.items}
    assert posters["Review reclaim candidate #1"] == "https://image.tmdb.org/t/p/w342/poster-a.jpg"
    assert posters["Review reclaim candidate #2"] == CENTRAL_PLACEHOLDER_POSTER_URL
