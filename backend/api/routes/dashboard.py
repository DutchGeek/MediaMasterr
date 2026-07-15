from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio.session import AsyncSession

from backend.core.artwork import resolve_poster_url
from backend.core.auth import require_page_access
from backend.core.utils.datetime_utils import to_utc_isoformat
from backend.database import get_db
from backend.database.models import (
    Movie,
    ProtectedMedia,
    ProtectionRequest,
    ReclaimCandidate,
    ReclaimHistory,
    Series,
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
from backend.user_types import MEDIA_SERVERS

router = APIRouter(prefix="/api", tags=["dashboard"])


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

    services: list[DashboardServiceSummary] = []
    if is_admin:
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

        services = [
            DashboardServiceSummary(
                service_type=service_type.value,
                name=name or service_type.value.title(),
                url=base_url or "",
                enabled=enabled,
                last_sync_at=to_utc_isoformat(last_sync_at)
                if service_type in MEDIA_SERVERS
                else None,
            )
            for service_type, name, enabled, base_url in sorted(
                service_config_rows,
                key=lambda r: (r[0].value, (r[1] or "").lower()),
            )
        ]

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
        reclaimable_movies_bytes=int(movie_size_total),
        reclaimable_series_bytes=int(series_size_total),
        reclaimable_total_bytes=int(movie_size_total + series_size_total),
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
    candidate_rows = (
        await db.execute(
            select(
                ReclaimCandidate.media_type,
                ReclaimCandidate.season_id,
                ReclaimCandidate.episode_id,
                ReclaimCandidate.estimated_space_bytes,
                ReclaimCandidate.created_at,
                Movie.title.label("movie_title"),
                Movie.poster_url.label("movie_poster_url"),
                Movie.arr_tags.label("movie_tags"),
                Series.title.label("series_title"),
                Series.poster_url.label("series_poster_url"),
                Series.arr_tags.label("series_tags"),
            )
            .outerjoin(Movie, Movie.id == ReclaimCandidate.movie_id)
            .outerjoin(Series, Series.id == ReclaimCandidate.series_id)
        )
    ).all()

    def _bucket_label(row: object) -> str:
        tags = []
        movie_tags = getattr(row, "movie_tags", None)
        series_tags = getattr(row, "series_tags", None)
        if isinstance(movie_tags, list):
            tags.extend([str(tag).strip() for tag in movie_tags if str(tag).strip()])
        if isinstance(series_tags, list):
            tags.extend([str(tag).strip() for tag in series_tags if str(tag).strip()])
        return tags[0] if tags else "Ungrouped"

    def _scope_label(row: object) -> str:
        if getattr(row, "episode_id", None) is not None:
            return "Episode"
        if getattr(row, "season_id", None) is not None:
            return "Season"
        if getattr(row, "media_type", None) is MediaType.MOVIE:
            return "Movie"
        return "Series"

    def _title(row: object) -> str:
        return str(
            getattr(row, "movie_title", None)
            or getattr(row, "series_title", None)
            or "Unknown"
        )

    def _poster_url(row: object) -> str | None:
        return resolve_poster_url(
            getattr(row, "movie_poster_url", None)
            or getattr(row, "series_poster_url", None),
            context="dashboard.opportunities",
            media_type=(
                "movie"
                if getattr(row, "movie_poster_url", None)
                else "series"
            ),
        )

    ready_today_movies = 0
    ready_today_seasons = 0
    ready_today_episodes = 0
    library_buckets: dict[str, tuple[int, int]] = {}
    candidate_opportunities: list[DashboardOpportunity] = []
    recent_opportunities: list[DashboardOpportunity] = []
    sorted_by_size = sorted(
        candidate_rows,
        key=lambda row: int(getattr(row, "estimated_space_bytes", 0) or 0),
        reverse=True,
    )
    sorted_by_recent = sorted(
        candidate_rows,
        key=lambda row: getattr(row, "created_at", now) or now,
        reverse=True,
    )
    for row in candidate_rows:
        if getattr(row, "episode_id", None) is not None:
            ready_today_episodes += 1
        elif getattr(row, "season_id", None) is not None:
            ready_today_seasons += 1
        elif getattr(row, "media_type", None) is MediaType.MOVIE:
            ready_today_movies += 1

        label = _bucket_label(row)
        size = int(getattr(row, "estimated_space_bytes", 0) or 0)
        current_size, current_count = library_buckets.get(label, (0, 0))
        library_buckets[label] = (current_size + size, current_count + 1)

    for row in sorted_by_size[:5]:
        candidate_opportunities.append(
            DashboardOpportunity(
                title=_title(row),
                media_type=getattr(row, "media_type", MediaType.MOVIE).value,
                scope=_scope_label(row),
                reclaimable_size_bytes=int(
                    getattr(row, "estimated_space_bytes", 0) or 0
                ),
                poster_url=_poster_url(row),
            )
        )

    for row in sorted_by_recent[:5]:
        recent_opportunities.append(
            DashboardOpportunity(
                title=_title(row),
                media_type=getattr(row, "media_type", MediaType.MOVIE).value,
                scope=_scope_label(row),
                reclaimable_size_bytes=int(
                    getattr(row, "estimated_space_bytes", 0) or 0
                ),
                poster_url=_poster_url(row),
            )
        )

    decision_summary = DashboardDecisionSummary(
        recoverable_space_bytes=int(movie_size_total + series_size_total),
        ready_today=DashboardReadyToday(
            movies=ready_today_movies,
            tv_seasons=ready_today_seasons,
            episodes=ready_today_episodes,
        ),
        blocked=DashboardBlockedSummary(
            protected=active_protected_count,
            waiting=pending_requests,
            attention_required=0,
        ),
        top_opportunities=candidate_opportunities,
        libraries=[
            DashboardLibraryBucket(
                label=label,
                reclaimable_size_bytes=size,
                item_count=count,
            )
            for label, (size, count) in sorted(
                library_buckets.items(),
                key=lambda item: item[1][0],
                reverse=True,
            )[:6]
        ],
        recently_reclaimable=recent_opportunities,
    )
    viewer = DashboardViewer(
        role=current_user.role.value,
        can_view_admin_panels=is_admin,
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
    )


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    current_user: Annotated[User, Depends(require_page_access(PageAccess.DASHBOARD))],
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    return await build_dashboard_response(current_user, db)
