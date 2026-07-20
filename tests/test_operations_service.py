from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.artwork import CENTRAL_PLACEHOLDER_POSTER_URL
from backend.database import Base
from backend.database.models import CleanupPlan, MediaAsset, Movie, OperationHistory, ReclaimCandidate
from backend.enums import MediaType
from backend.services.mie.operations_execution import operations_execution_manager
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
                MediaAsset(
                    media_type=MediaType.MOVIE,
                    movie_id=movie_with_poster.id,
                    poster_url=movie_with_poster.poster_url,
                ),
                MediaAsset(
                    media_type=MediaType.MOVIE,
                    movie_id=movie_without_poster.id,
                    poster_url=movie_without_poster.poster_url,
                ),
            ]
        )

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
    assert posters["With Poster"] == "https://image.tmdb.org/t/p/w342/poster-a.jpg"
    assert posters["Without Poster"] == CENTRAL_PLACEHOLDER_POSTER_URL

    explainability = {item.title: item.reasons for item in response.items}
    assert explainability["With Poster"]
    assert explainability["Without Poster"]

    manifests = {item.title: item.action_manifest.available_actions for item in response.items}
    assert manifests["With Poster"]
    assert any(action.category for action in manifests["With Poster"])
    assert any(action.risk for action in manifests["With Poster"])
    assert any(action.impact_preview for action in manifests["With Poster"])


@pytest.mark.anyio
async def test_operations_workflow_validate_execute_and_audit() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie = Movie(title="Workflow Movie", tmdb_id=4001, poster_url="/wf.jpg")
        db.add(movie)
        await db.flush()

        db.add(
            ReclaimCandidate(
                media_type=MediaType.MOVIE,
                matched_rule_ids=[11],
                matched_criteria={"rule": "workflow"},
                movie_id=movie.id,
                reason="Workflow candidate",
                estimated_space_bytes=123456,
                approved_for_deletion=True,
            )
        )
        await db.commit()

        service = OperationsService(db)
        recommendations = await service.recommendations()
        assert recommendations.items

        recommendation_id = recommendations.items[0].id
        validated = await service.recommendation_validate(recommendation_id)
        assert validated.validation.valid

        executed = await service.recommendation_execute(recommendation_id)
        assert executed.execution.executed is True
        assert executed.execution.result == "completed"
        assert executed.execution.operation_history_id is not None

        audit = await service.audit_log()
        assert audit.items
        assert audit.items[0].id == executed.execution.operation_history_id

    await engine.dispose()


@pytest.mark.anyio
async def test_operations_workspace_includes_issue_health_and_confidence_sections() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        workspace = await OperationsService(db).workspace()

    await engine.dispose()

    assert workspace.health.overall_health >= 0
    assert workspace.issue_summary.total == len(workspace.issues)
    assert workspace.graph_summary.total_media >= 0
    assert workspace.confidence.score >= 0
    assert workspace.downloads_health.total_download_space >= 0
    assert isinstance(workspace.downloads, list)
    assert len(workspace.workflow.stages) == 6
    assert {stage.key for stage in workspace.workflow.stages} == {
        "download",
        "import",
        "organize",
        "retention",
        "cleanup",
        "completed",
    }
    assert workspace.media_policies
    stage_assets = [asset for stage in workspace.workflow.stages for asset in stage.assets]
    if stage_assets:
        assert stage_assets[0].action_manifest.available_actions
        assert stage_assets[0].file_evidence is not None
        assert stage_assets[0].application_evidence is not None
        assert stage_assets[0].relationship_evidence is not None


@pytest.mark.anyio
async def test_operations_execution_session_tracks_progress_and_history() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie = Movie(title="Execution Session Movie", tmdb_id=5001, poster_url="/exec.jpg")
        db.add(movie)
        await db.flush()

        db.add(
            ReclaimCandidate(
                media_type=MediaType.MOVIE,
                matched_rule_ids=[21],
                matched_criteria={"rule": "execution"},
                movie_id=movie.id,
                reason="Execution session candidate",
                estimated_space_bytes=654321,
                approved_for_deletion=True,
            )
        )
        await db.commit()

    async with session_maker() as db:
        recommendations = await OperationsService(db).recommendations()
        recommendation_id = recommendations.items[0].id

    created = await operations_execution_manager.start_session(
        service_factory=lambda db: OperationsService(db),
        session_factory=session_maker,
        recommendation_ids=[recommendation_id],
        created_by_user_id=None,
    )

    assert created.total == 1
    assert created.history_id is not None

    latest = created
    for _ in range(20):
        await asyncio.sleep(0.05)
        current = await operations_execution_manager.get_session(created.session_id)
        assert current is not None
        latest = current
        if latest.status in {"completed", "failed", "partial"}:
            break

    assert latest.status == "completed"
    assert latest.summary.successful == 1
    assert latest.items[0].operation_history_id is not None

    async with session_maker() as db:
        history_rows = (
            (
                await db.execute(
                    select(OperationHistory).where(
                        OperationHistory.target_type == "execution_session"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert history_rows

        history = await operations_execution_manager.list_history(db)

    assert history.items
    assert history.items[0].session_id == created.session_id
    assert history.items[0].successful == 1

    await engine.dispose()
