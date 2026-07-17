from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, TypedDict

from fastapi import APIRouter, Depends
from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio.session import AsyncSession

from backend.core.auth import require_page_access
from backend.core.service_manager import service_manager
from backend.core.utils.datetime_utils import to_utc_isoformat
from backend.database import get_db
from backend.database.models import (
    Movie,
    MovieVersion,
    ProtectedMedia,
    ProtectionRequest,
    ReclaimCandidate,
    ReclaimHistory,
    Series,
    SeriesServiceRef,
    ServiceConfig,
    TaskRun,
    User,
)
from backend.enums import (
    MediaType,
    PageAccess,
    ProtectionRequestStatus,
    Task,
    TaskStatus,
    UserRole,
)
from backend.models.dashboard import (
    DashboardActivityItem,
    DashboardArtworkHealth,
    DashboardBlockedSummary,
    DashboardDecisionSummary,
    DashboardKpis,
    DashboardLibraryBucket,
    DashboardOpportunity,
    DashboardReadyToday,
    DashboardRequestsSummary,
    DashboardResponse,
    DashboardServiceSummary,
    DashboardViewer,
)
from backend.services.event_engine import EventEngine
from backend.services.media_asset_artwork import media_asset_artwork_resolver
from backend.services.mie.operations_service import OperationsService
from backend.user_types import MEDIA_SERVERS

router = APIRouter(prefix="/api", tags=["dashboard"])


class _LibraryStateEntry(TypedDict):
    label: str
    library_size_bytes: int
    title_count: int
    reclaimable_size_bytes: int
    reclaimable_ids: set[str]


def _empty_library_entry(label: str) -> _LibraryStateEntry:
    return {
        "label": label,
        "library_size_bytes": 0,
        "title_count": 0,
        "reclaimable_size_bytes": 0,
        "reclaimable_ids": set(),
    }


async def build_dashboard_response(
    current_user: Annotated[User, Depends(require_page_access(PageAccess.DASHBOARD))],
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    """Role aware dashboard summary."""
    now = datetime.now(UTC)
    seven_days_ago = now - timedelta(days=7)
    is_admin = current_user.role is UserRole.ADMIN

    summary_row = (
        await db.execute(
            select(
                select(func.count())
                .select_from(Movie)
                .where(Movie.removed_at.is_(None))
                .scalar_subquery()
                .label("movie_count"),
                select(func.count())
                .select_from(Series)
                .where(Series.removed_at.is_(None))
                .scalar_subquery()
                .label("series_count"),
                select(
                    func.coalesce(func.sum(ReclaimCandidate.estimated_space_bytes), 0)
                )
                .select_from(ReclaimCandidate)
                .where(ReclaimCandidate.media_type == MediaType.MOVIE)
                .scalar_subquery()
                .label("movie_size_total"),
                select(
                    func.coalesce(func.sum(ReclaimCandidate.estimated_space_bytes), 0)
                )
                .select_from(ReclaimCandidate)
                .where(ReclaimCandidate.media_type == MediaType.SERIES)
                .scalar_subquery()
                .label("series_size_total"),
                select(func.coalesce(func.sum(Movie.size), 0))
                .select_from(Movie)
                .where(Movie.removed_at.is_(None))
                .scalar_subquery()
                .label("all_movies_size"),
                select(func.coalesce(func.sum(Series.size), 0))
                .select_from(Series)
                .where(Series.removed_at.is_(None))
                .scalar_subquery()
                .label("all_series_size"),
                select(func.count())
                .select_from(ProtectionRequest)
                .where(ProtectionRequest.status == ProtectionRequestStatus.PENDING)
                .scalar_subquery()
                .label("pending_requests"),
                select(func.count())
                .select_from(ProtectionRequest)
                .where(
                    ProtectionRequest.status == ProtectionRequestStatus.APPROVED,
                    ProtectionRequest.reviewed_at.is_not(None),
                    ProtectionRequest.reviewed_at >= seven_days_ago,
                )
                .scalar_subquery()
                .label("approved_7d"),
                select(func.count())
                .select_from(ProtectionRequest)
                .where(
                    ProtectionRequest.status == ProtectionRequestStatus.DENIED,
                    ProtectionRequest.reviewed_at.is_not(None),
                    ProtectionRequest.reviewed_at >= seven_days_ago,
                )
                .scalar_subquery()
                .label("denied_7d"),
                select(func.count())
                .select_from(ProtectionRequest)
                .where(
                    ProtectionRequest.requested_by_user_id == current_user.id,
                    ProtectionRequest.status == ProtectionRequestStatus.PENDING,
                )
                .scalar_subquery()
                .label("mine_pending"),
                select(func.count())
                .select_from(ProtectionRequest)
                .where(
                    ProtectionRequest.requested_by_user_id == current_user.id,
                    ProtectionRequest.status == ProtectionRequestStatus.APPROVED,
                    or_(
                        ProtectionRequest.requested_expires_at.is_(None),
                        ProtectionRequest.requested_expires_at >= now,
                    ),
                )
                .scalar_subquery()
                .label("mine_active"),
                select(func.count())
                .select_from(ServiceConfig)
                .where(
                    ServiceConfig.service_type.in_(MEDIA_SERVERS),
                    ServiceConfig.enabled.is_(True),
                )
                .scalar_subquery()
                .label("media_server_count"),
                select(func.count())
                .select_from(ReclaimHistory)
                .where(ReclaimHistory.media_type == MediaType.MOVIE)
                .scalar_subquery()
                .label("reclaimed_movies"),
                select(func.count())
                .select_from(ReclaimHistory)
                .where(ReclaimHistory.media_type == MediaType.SERIES)
                .scalar_subquery()
                .label("reclaimed_series"),
                select(func.coalesce(func.sum(ReclaimHistory.size), 0))
                .select_from(ReclaimHistory)
                .scalar_subquery()
                .label("reclaimed_total_size"),
                select(func.count())
                .select_from(TaskRun)
                .where(
                    TaskRun.status == TaskStatus.ERROR,
                    TaskRun.started_at.is_not(None),
                    TaskRun.started_at >= seven_days_ago,
                )
                .scalar_subquery()
                .label("failed_task_runs_7d"),
            )
        )
    ).one()

    movie_count = summary_row.movie_count or 0
    series_count = summary_row.series_count or 0
    movie_size_total = summary_row.movie_size_total or 0
    series_size_total = summary_row.series_size_total or 0
    all_movies_size = summary_row.all_movies_size or 0
    all_series_size = summary_row.all_series_size or 0
    pending_requests = summary_row.pending_requests or 0
    approved_7d = summary_row.approved_7d or 0
    denied_7d = summary_row.denied_7d or 0
    mine_pending = summary_row.mine_pending or 0
    mine_active = summary_row.mine_active or 0
    media_server_configured = (summary_row.media_server_count or 0) > 0
    reclaimed_movies = summary_row.reclaimed_movies or 0
    reclaimed_series = summary_row.reclaimed_series or 0
    reclaimed_total_size = summary_row.reclaimed_total_size or 0
    failed_task_runs_7d = summary_row.failed_task_runs_7d or 0

    operations_workspace = await OperationsService(db).workspace()
    operations_cards = operations_workspace.overview.cards
    operations_recommendations = operations_workspace.recommendations.items
    card_by_key = {card.key: card for card in operations_cards}

    def _card_count(key: str) -> int:
        card = card_by_key.get(key)
        return card.count if card is not None else 0

    def _recommendation_media_identity(
        target_type: str, target_id: str | None
    ) -> tuple[MediaType | None, int | None]:
        if not target_id or not target_id.isdigit():
            return None, None
        parsed_target_id = int(target_id)
        if target_type == "movie":
            return MediaType.MOVIE, parsed_target_id
        if target_type in {"series", "season", "episode"}:
            return MediaType.SERIES, parsed_target_id
        return None, None

    first_recommendation_poster_by_card: dict[str, str] = {}
    for item in operations_recommendations:
        if item.card_key not in first_recommendation_poster_by_card:
            recommendation_media_type, recommendation_media_id = (
                _recommendation_media_identity(item.target_type, item.target_id)
            )
            resolved_artwork = await media_asset_artwork_resolver.resolve(
                db,
                context="dashboard.operations_recommendations",
                media_type=recommendation_media_type,
                media_id=recommendation_media_id,
                provider_poster_url=item.poster_url,
                fallback_reason=f"recommendation_{item.card_key}",
            )
            first_recommendation_poster_by_card[item.card_key] = (
                resolved_artwork.poster_url
            )

    reclaimable_movies_bytes = int(
        sum(
            item.estimated_recovery_bytes
            for item in operations_recommendations
            if item.target_type == "movie"
        )
    )
    reclaimable_series_bytes = int(
        sum(
            item.estimated_recovery_bytes
            for item in operations_recommendations
            if item.target_type in {"series", "season", "episode"}
        )
    )
    if reclaimable_movies_bytes == 0:
        reclaimable_movies_bytes = int(movie_size_total)
    if reclaimable_series_bytes == 0:
        reclaimable_series_bytes = int(series_size_total)
    recoverable_space_bytes = int(
        _card_count("space_recovery")
        or (reclaimable_movies_bytes + reclaimable_series_bytes)
    )

    services: list[DashboardServiceSummary] = []
    if is_admin:
        runtime_status = await service_manager.get_status()

        def _service_runtime_health(
            service_name: str, enabled: bool
        ) -> tuple[str, str | None]:
            runtime_key = service_name.lower()
            connected = runtime_status.get(runtime_key, False)
            if not enabled:
                return "disabled", "Service disabled"
            if connected:
                return "healthy", None
            return "down", "Configured but runtime client unavailable"

        # get last completed SYNC_MEDIA run (single unified sync task)
        last_sync_result = await db.execute(
            select(func.max(TaskRun.completed_at)).where(
                TaskRun.task == Task.SYNC_MEDIA,
                TaskRun.status == TaskStatus.COMPLETED,
            )
        )
        last_sync_at: datetime | None = last_sync_result.scalar_one_or_none()

        # get all service configs
        service_config_rows = (
            await db.execute(
                select(
                    ServiceConfig.service_type,
                    ServiceConfig.name,
                    ServiceConfig.enabled,
                    ServiceConfig.base_url,
                )
            )
        ).all()

        services = []
        for service_type, name, enabled, base_url in sorted(
            service_config_rows,
            key=lambda r: (r[0].value, (r[1] or "").lower()),
        ):
            status, status_reason = _service_runtime_health(service_type.value, enabled)
            services.append(
                DashboardServiceSummary(
                    service_type=service_type.value,
                    name=name or service_type.value.title(),
                    url=base_url or "",
                    enabled=enabled,
                    last_sync_at=to_utc_isoformat(last_sync_at)
                    if service_type in MEDIA_SERVERS
                    else None,
                    status=status,
                    status_reason=status_reason,
                )
            )

    media_activity, system_activity = await EventEngine.build_dashboard_activity(
        db,
        current_user=current_user,
        is_admin=is_admin,
    )
    activity: list[DashboardActivityItem] = [
        *media_activity[:10],
        *system_activity[:10],
    ]
    activity.sort(key=lambda item: item.created_at, reverse=True)
    activity = activity[:20]

    kpis = DashboardKpis(
        total_movies=movie_count,
        total_series=series_count,
        total_movies_size_bytes=int(all_movies_size),
        total_series_size_bytes=int(all_series_size),
        reclaimable_movies_bytes=reclaimable_movies_bytes,
        reclaimable_series_bytes=reclaimable_series_bytes,
        reclaimable_total_bytes=recoverable_space_bytes,
        reclaimed_movies=reclaimed_movies,
        reclaimed_series=reclaimed_series,
        reclaimed_total_bytes=int(reclaimed_total_size),
    )
    request_summary = DashboardRequestsSummary(
        pending_count=pending_requests,
        approved_7d=approved_7d,
        denied_7d=denied_7d,
        mine_pending=mine_pending,
        mine_active=mine_active,
    )

    active_protected_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(ProtectedMedia)
                .where(
                    or_(
                        ProtectedMedia.permanent.is_(True),
                        ProtectedMedia.expires_at.is_(None),
                        ProtectedMedia.expires_at > now,
                    )
                )
            )
        ).scalar_one()
    )

    ready_to_detach_count = int(_card_count("ready_to_detach"))
    import_pending_count = int(_card_count("import_pending"))
    protected_seeding_count = int(_card_count("protected_seeding"))
    attention_required_count = int(
        sum(card.count for card in operations_cards if card.severity == "high")
        or failed_task_runs_7d
    )

    top_card_opportunities: list[DashboardOpportunity] = []

    def _card_target_path(card_key: str) -> str:
        if card_key == "identity_issues":
            return "/identity?needs_review=true"
        if card_key in {"import_pending"}:
            return "/movies?candidates_only=true"
        return f"/operations?collection={card_key}"

    for card in sorted(
        [card for card in operations_cards if card.count > 0],
        key=lambda row: (
            0 if row.severity == "high" else 1,
            -row.count,
            row.title.lower(),
        ),
    )[:6]:
        top_poster = first_recommendation_poster_by_card.get(card.key)
        if top_poster is None:
            top_artwork = await media_asset_artwork_resolver.resolve(
                db,
                context="dashboard.top_opportunity.collection",
                media_type=None,
                media_id=None,
                fallback_reason=f"collection_{card.key}",
            )
            top_poster = top_artwork.poster_url
        top_card_opportunities.append(
            DashboardOpportunity(
                title=card.title,
                media_type="collection",
                scope="Operations Collection",
                reclaimable_size_bytes=(
                    recoverable_space_bytes if card.key == "space_recovery" else 0
                ),
                poster_url=top_poster,
                operation_key=card.key,
                metric_count=card.count,
                target_path=_card_target_path(card.key),
            )
        )

    recent_opportunities: list[DashboardOpportunity] = []
    for item in operations_recommendations[:5]:
        opportunity_media_type = "movie" if item.target_type == "movie" else "series"
        rec_media_type, rec_media_id = _recommendation_media_identity(
            item.target_type, item.target_id
        )
        recent_artwork = await media_asset_artwork_resolver.resolve(
            db,
            context="dashboard.recent_operations",
            media_type=rec_media_type,
            media_id=rec_media_id,
            provider_poster_url=item.poster_url,
            fallback_reason=f"recommendation_{item.card_key}",
        )
        recent_opportunities.append(
            DashboardOpportunity(
                title=item.title,
                media_type=opportunity_media_type,
                scope="Recommendation",
                reclaimable_size_bytes=int(item.estimated_recovery_bytes or 0),
                poster_url=recent_artwork.poster_url,
                operation_key=item.card_key,
                metric_count=None,
                target_path=(
                    f"/operations?collection={item.card_key}&recommendation={item.id}"
                ),
            )
        )

    movie_library_rows = (
        await db.execute(
            select(
                MovieVersion.library_name,
                func.coalesce(func.sum(MovieVersion.size), 0),
                func.count(func.distinct(MovieVersion.movie_id)),
            )
            .where(
                MovieVersion.library_name.is_not(None), MovieVersion.library_name != ""
            )
            .group_by(MovieVersion.library_name)
        )
    ).all()
    series_library_rows = (
        await db.execute(
            select(SeriesServiceRef.library_name, Series.id, Series.size)
            .join(Series, Series.id == SeriesServiceRef.series_id)
            .where(
                Series.removed_at.is_(None),
                SeriesServiceRef.library_name.is_not(None),
                SeriesServiceRef.library_name != "",
            )
        )
    ).all()

    library_state: dict[str, _LibraryStateEntry] = {}
    for library_name, size_total, title_count in movie_library_rows:
        key = str(library_name)
        entry = library_state.setdefault(key, _empty_library_entry(key))
        entry["library_size_bytes"] += int(size_total or 0)
        entry["title_count"] += int(title_count or 0)

    series_seen_by_library: dict[str, set[int]] = {}
    for library_name, series_id, series_size in series_library_rows:
        key = str(library_name)
        entry = library_state.setdefault(key, _empty_library_entry(key))
        seen_ids = series_seen_by_library.setdefault(key, set())
        if int(series_id) in seen_ids:
            continue
        seen_ids.add(int(series_id))
        entry["library_size_bytes"] += int(series_size or 0)
        entry["title_count"] += 1

    movie_target_ids: set[int] = set()
    series_target_ids: set[int] = set()
    reclaim_candidate_target_ids: set[int] = set()
    for item in operations_recommendations:
        if item.target_id is None or not item.target_id.isdigit():
            continue
        target_id = int(item.target_id)
        if item.target_type == "movie":
            movie_target_ids.add(target_id)
        elif item.target_type in {"series", "season", "episode"}:
            series_target_ids.add(target_id)
        elif item.target_type == "reclaim_candidate":
            reclaim_candidate_target_ids.add(target_id)

    if reclaim_candidate_target_ids:
        candidate_targets = (
            await db.execute(
                select(
                    ReclaimCandidate.id,
                    ReclaimCandidate.movie_id,
                    ReclaimCandidate.series_id,
                ).where(ReclaimCandidate.id.in_(reclaim_candidate_target_ids))
            )
        ).all()
        for _candidate_id, movie_id, series_id in candidate_targets:
            if movie_id is not None:
                movie_target_ids.add(int(movie_id))
            if series_id is not None:
                series_target_ids.add(int(series_id))

    movie_libraries_by_id: dict[int, set[str]] = {}
    if movie_target_ids:
        for movie_id, library_name in (
            await db.execute(
                select(MovieVersion.movie_id, MovieVersion.library_name)
                .where(
                    MovieVersion.movie_id.in_(movie_target_ids),
                    MovieVersion.library_name.is_not(None),
                    MovieVersion.library_name != "",
                )
                .distinct()
            )
        ).all():
            movie_libraries_by_id.setdefault(int(movie_id), set()).add(
                str(library_name)
            )

    series_libraries_by_id: dict[int, set[str]] = {}
    if series_target_ids:
        for series_id, library_name in (
            await db.execute(
                select(SeriesServiceRef.series_id, SeriesServiceRef.library_name)
                .where(
                    SeriesServiceRef.series_id.in_(series_target_ids),
                    SeriesServiceRef.library_name.is_not(None),
                    SeriesServiceRef.library_name != "",
                )
                .distinct()
            )
        ).all():
            series_libraries_by_id.setdefault(int(series_id), set()).add(
                str(library_name)
            )

    for item in operations_recommendations:
        if item.target_id is None or not item.target_id.isdigit():
            continue
        target_id = int(item.target_id)
        linked_libraries: set[str] = set()
        if item.target_type == "movie":
            linked_libraries = movie_libraries_by_id.get(target_id, set())
        elif item.target_type in {"series", "season", "episode"}:
            linked_libraries = series_libraries_by_id.get(target_id, set())

        for library_name in linked_libraries:
            entry = library_state.setdefault(
                library_name, _empty_library_entry(library_name)
            )
            entry["reclaimable_size_bytes"] += int(item.estimated_recovery_bytes or 0)
            entry["reclaimable_ids"].add(f"{item.target_type}:{target_id}")

    library_buckets: list[DashboardLibraryBucket] = []
    for entry in sorted(
        library_state.values(),
        key=lambda row: (
            -row["reclaimable_size_bytes"],
            row["label"].lower(),
        ),
    ):
        reclaimable_count = len(entry["reclaimable_ids"])
        if reclaimable_count == 0:
            health = "healthy"
        elif reclaimable_count <= 3:
            health = "degraded"
        else:
            health = "attention"
        library_buckets.append(
            DashboardLibraryBucket(
                label=entry["label"] or "Unknown",
                reclaimable_size_bytes=entry["reclaimable_size_bytes"],
                item_count=reclaimable_count,
                library_size_bytes=entry["library_size_bytes"],
                title_count=entry["title_count"],
                reclaimable_count=reclaimable_count,
                health=health,
            )
        )

    decision_summary = DashboardDecisionSummary(
        recoverable_space_bytes=recoverable_space_bytes,
        ready_today=DashboardReadyToday(
            movies=ready_to_detach_count,
            tv_seasons=sum(
                1
                for item in operations_recommendations
                if item.target_type == "season"
                and item.card_key in {"ready_to_detach", "import_pending"}
            ),
            episodes=sum(
                1
                for item in operations_recommendations
                if item.target_type == "episode"
                and item.card_key in {"ready_to_detach", "import_pending"}
            ),
        ),
        blocked=DashboardBlockedSummary(
            protected=max(active_protected_count, protected_seeding_count),
            waiting=import_pending_count,
            attention_required=attention_required_count,
        ),
        top_opportunities=top_card_opportunities,
        libraries=library_buckets,
        recently_reclaimable=recent_opportunities,
    )
    viewer = DashboardViewer(
        role=current_user.role.value,
        can_view_admin_panels=is_admin,
    )

    artwork_issues = operations_workspace.artwork_issues
    artwork_health = DashboardArtworkHealth(
        coverage_percent=(artwork_issues.coverage_percent if artwork_issues else 0.0),
        status=(
            "Healthy"
            if artwork_issues and artwork_issues.coverage_percent >= 95
            else "Degraded"
            if artwork_issues and artwork_issues.coverage_percent >= 80
            else "Needs Attention"
        ),
        missing_posters=(artwork_issues.missing_count if artwork_issues else 0),
        invalid_posters=(artwork_issues.invalid_count if artwork_issues else 0),
        placeholder_posters=(artwork_issues.placeholder_count if artwork_issues else 0),
        stale_artwork=(
            (artwork_issues.stale_count + artwork_issues.needs_refresh_count)
            if artwork_issues
            else 0
        ),
        collision_count=(artwork_issues.collision_count if artwork_issues else 0),
        last_refresh_at=(
            to_utc_isoformat(artwork_issues.last_refresh_at)
            if artwork_issues and artwork_issues.last_refresh_at is not None
            else None
        ),
    )

    return DashboardResponse(
        kpis=kpis,
        requests=request_summary,
        services=services,
        activity=activity,
        media_activity=media_activity,
        system_activity=system_activity,
        viewer=viewer,
        media_server_configured=media_server_configured,
        decision_summary=decision_summary,
        artwork_health=artwork_health,
    )


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    current_user: Annotated[User, Depends(require_page_access(PageAccess.DASHBOARD))],
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    return await build_dashboard_response(current_user, db)
