from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.core.artwork import CENTRAL_PLACEHOLDER_POSTER_URL
from backend.database import Base
from backend.database.models import (
    CleanupPlan,
    MediaAsset,
    Movie,
    MovieArrRef,
    MovieVersion,
    OperationHistory,
    ReclaimCandidate,
    Season,
    Series,
    SeriesArrRef,
    SeriesServiceRef,
    ServiceConfig,
)
from backend.enums import MediaType, Service
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
        assert stage_assets[0].narrative is not None
        assert stage_assets[0].narrative.what


@pytest.mark.anyio
async def test_action_manifest_distinguishes_required_and_recommended_actions() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        service = OperationsService(db)

        required_manifest = service._build_action_manifest(
            primary_action="retry_import",
            stage_key="import",
            target_type="download_object",
            media_type=MediaType.MOVIE,
            summary="Import failed",
            reason="The library import did not complete cleanly.",
            expected_destination="/media/movies/korean",
        )
        required_primary = required_manifest.available_actions[0]

        recommended_manifest = service._build_action_manifest(
            primary_action="delete_torrent_and_files",
            stage_key="cleanup",
            target_type="download_object",
            media_type=MediaType.MOVIE,
            summary="Imported successfully",
            reason="The files have already been copied into the media library.",
            expected_destination="/media/movies/korean",
            estimated_recovery_bytes=18_400_000_000,
        )
        recommended_primary = recommended_manifest.available_actions[0]

    await engine.dispose()

    assert required_manifest.workflow_outcome == "blocked"
    assert required_manifest.workflow_summary is not None
    assert "Required action" in required_manifest.workflow_summary
    assert required_primary.presentation == "required"
    assert any(
        "cannot continue successfully" in line.lower()
        for line in required_manifest.primary_action_reasoning
    )

    assert recommended_manifest.workflow_outcome == "completed"
    assert recommended_manifest.workflow_summary is not None
    assert "Workflow completed successfully" in recommended_manifest.workflow_summary
    assert recommended_primary.presentation == "recommended"
    assert any(
        "workflow has completed successfully" in line.lower()
        for line in recommended_manifest.primary_action_reasoning
    )
    assert any(
        "reclaim" in line.lower() or "remove" in line.lower()
        for line in recommended_manifest.primary_action_reasoning
    )


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


@pytest.mark.anyio
async def test_file_evidence_hierarchy_and_duplicate_detection_is_semantic() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie = Movie(title="Hierarchy Movie", tmdb_id=9901)
        db.add(movie)
        await db.flush()

        radarr = ServiceConfig(
            service_type=Service.RADARR,
            base_url="http://radarr.local",
            api_key="test",
            name="Radarr Main",
            enabled=True,
        )
        db.add(radarr)
        await db.flush()

        db.add(
            MovieArrRef(
                movie_id=movie.id,
                service_config_id=radarr.id,
                arr_movie_id=123,
                arr_movie_path="/media/movies/american/A Minecraft Movie (2025)",
            )
        )
        db.add_all(
            [
                MovieVersion(
                    movie_id=movie.id,
                    service=Service.PLEX,
                    service_item_id="plex-1",
                    service_media_id="plex-media-1",
                    library_id="lib-1",
                    library_name="American Movies",
                    path="/media/movies/american/A Minecraft Movie (2025)/A Minecraft Movie (2025).mkv",
                ),
                MovieVersion(
                    movie_id=movie.id,
                    service=Service.JELLYFIN,
                    service_item_id="jf-1",
                    service_media_id="jf-media-1",
                    library_id="lib-2",
                    library_name="Backup Movies",
                    path="/media/backup/movies/A Minecraft Movie (2025).mkv",
                ),
            ]
        )

        db.add(
            ReclaimCandidate(
                media_type=MediaType.MOVIE,
                matched_rule_ids=[42],
                matched_criteria={"rule": "hierarchy"},
                movie_id=movie.id,
                reason="Hierarchy verification",
                estimated_space_bytes=0,
            )
        )
        await db.commit()

        workspace = await OperationsService(db).workspace()

    await engine.dispose()

    assets = [asset for stage in workspace.workflow.stages for asset in stage.assets]
    target = next((asset for asset in assets if "Hierarchy Movie" in asset.title), None)
    assert target is not None

    assert target.filesystem_comparison_summary is not None
    assert "outside the canonical managed folder" in target.filesystem_comparison_summary

    rows = target.file_evidence
    library_root = next((row for row in rows if row.hierarchy_role == "library_root"), None)
    managed_folder = next((row for row in rows if row.hierarchy_role == "managed_folder"), None)
    primary_inside = next(
        (
            row
            for row in rows
            if row.hierarchy_role == "primary_media_file"
            and row.path
            and "/media/movies/american/A Minecraft Movie (2025)/" in row.path
        ),
        None,
    )
    outside_copy = next((row for row in rows if row.hierarchy_role == "additional_copy"), None)

    assert library_root is not None
    assert managed_folder is not None
    assert primary_inside is not None
    assert outside_copy is not None
    assert outside_copy.state == "duplicate"


@pytest.mark.anyio
async def test_series_library_root_uses_canonical_managed_folder_parent_with_multi_sonarr_roots() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        series = Series(title="Series Name", tmdb_id=61001)
        db.add(series)
        await db.flush()

        sonarr_american = ServiceConfig(
            service_type=Service.SONARR,
            base_url="http://sonarr-american.local",
            api_key="test",
            name="Sonarr American",
            enabled=True,
        )
        sonarr_korean = ServiceConfig(
            service_type=Service.SONARR,
            base_url="http://sonarr-korean.local",
            api_key="test",
            name="Sonarr Korean",
            enabled=True,
        )
        sonarr_korean_4k = ServiceConfig(
            service_type=Service.SONARR,
            base_url="http://sonarr-korean-4k.local",
            api_key="test",
            name="Sonarr Korean 4K",
            enabled=True,
        )
        db.add_all([sonarr_american, sonarr_korean, sonarr_korean_4k])
        await db.flush()

        db.add_all(
            [
                SeriesServiceRef(
                    series_id=series.id,
                    service=Service.PLEX,
                    service_id="plex-series-1",
                    library_id="plex-korean",
                    library_name="Korean TV",
                    path="/media/tv/korean/Series Name",
                ),
                Season(
                    series_id=series.id,
                    season_number=1,
                    path="/media/tv/korean/Series Name/Season 01",
                ),
                SeriesArrRef(
                    series_id=series.id,
                    service_config_id=sonarr_american.id,
                    arr_series_id=101,
                    arr_series_path="/media/tv/american/Series Name",
                ),
                SeriesArrRef(
                    series_id=series.id,
                    service_config_id=sonarr_korean.id,
                    arr_series_id=202,
                    arr_series_path="/media/tv/korean/Series Name",
                ),
                SeriesArrRef(
                    series_id=series.id,
                    service_config_id=sonarr_korean_4k.id,
                    arr_series_id=303,
                    arr_series_path="/media/tv/korean-4k/Series Name",
                ),
                ReclaimCandidate(
                    media_type=MediaType.SERIES,
                    matched_rule_ids=[77],
                    matched_criteria={"rule": "multi-root-series"},
                    series_id=series.id,
                    reason="Series hierarchy verification",
                    estimated_space_bytes=0,
                ),
            ]
        )
        await db.commit()

        workspace = await OperationsService(db).workspace()

    await engine.dispose()

    assets = [asset for stage in workspace.workflow.stages for asset in stage.assets]
    target = next((asset for asset in assets if asset.title == "Series Name"), None)
    assert target is not None

    rows = target.file_evidence
    library_root = next((row for row in rows if row.hierarchy_role == "library_root"), None)
    managed_folder = next((row for row in rows if row.hierarchy_role == "managed_folder"), None)

    assert managed_folder is not None
    assert managed_folder.path == "/media/tv/korean/Series Name"
    assert library_root is not None
    assert library_root.path == "/media/tv/korean"
    assert library_root.path != "/media/tv/american"


@pytest.mark.anyio
async def test_movie_library_root_uses_canonical_managed_folder_parent_with_multi_radarr_roots() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    session_maker = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_maker() as db:
        movie = Movie(title="Catalog Movie", tmdb_id=62001)
        db.add(movie)
        await db.flush()

        radarr_american = ServiceConfig(
            service_type=Service.RADARR,
            base_url="http://radarr-american.local",
            api_key="test",
            name="Radarr American",
            enabled=True,
        )
        radarr_korean = ServiceConfig(
            service_type=Service.RADARR,
            base_url="http://radarr-korean.local",
            api_key="test",
            name="Radarr Korean",
            enabled=True,
        )
        radarr_korean_4k = ServiceConfig(
            service_type=Service.RADARR,
            base_url="http://radarr-korean-4k.local",
            api_key="test",
            name="Radarr Korean 4K",
            enabled=True,
        )
        db.add_all([radarr_american, radarr_korean, radarr_korean_4k])
        await db.flush()

        db.add_all(
            [
                MovieVersion(
                    movie_id=movie.id,
                    service=Service.PLEX,
                    service_item_id="plex-movie-1",
                    service_media_id="plex-media-1",
                    library_id="lib-korean-movies",
                    library_name="Korean Movies",
                    path="/media/movies/korean/Catalog Movie (2024)/Catalog Movie (2024).mkv",
                ),
                MovieArrRef(
                    movie_id=movie.id,
                    service_config_id=radarr_american.id,
                    arr_movie_id=11,
                    arr_movie_path="/media/movies/american/Catalog Movie (2024)",
                ),
                MovieArrRef(
                    movie_id=movie.id,
                    service_config_id=radarr_korean.id,
                    arr_movie_id=22,
                    arr_movie_path="/media/movies/korean/Catalog Movie (2024)",
                ),
                MovieArrRef(
                    movie_id=movie.id,
                    service_config_id=radarr_korean_4k.id,
                    arr_movie_id=33,
                    arr_movie_path="/media/movies/korean-4k/Catalog Movie (2024)",
                ),
                ReclaimCandidate(
                    media_type=MediaType.MOVIE,
                    matched_rule_ids=[88],
                    matched_criteria={"rule": "multi-root-movie"},
                    movie_id=movie.id,
                    reason="Movie hierarchy verification",
                    estimated_space_bytes=0,
                ),
            ]
        )
        await db.commit()

        workspace = await OperationsService(db).workspace()

    await engine.dispose()

    assets = [asset for stage in workspace.workflow.stages for asset in stage.assets]
    target = next((asset for asset in assets if asset.title == "Catalog Movie"), None)
    assert target is not None

    rows = target.file_evidence
    library_root = next((row for row in rows if row.hierarchy_role == "library_root"), None)
    managed_folder = next((row for row in rows if row.hierarchy_role == "managed_folder"), None)

    assert managed_folder is not None
    assert managed_folder.path == "/media/movies/korean/Catalog Movie (2024)"
    assert library_root is not None
    assert library_root.path == "/media/movies/korean"
    assert library_root.path != "/media/movies/american"
