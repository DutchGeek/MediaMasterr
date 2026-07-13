from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.utils.datetime_utils import to_utc_isoformat
from backend.database.models import (
    DeleteRequest,
    Movie,
    ProtectedMedia,
    ProtectionRequest,
    ReclaimCandidate,
    ReclaimHistory,
    Series,
    TaskRun,
    User,
)
from backend.enums import MediaType, ProtectionRequestStatus, TaskStatus, UserRole
from backend.models.dashboard import DashboardActivityItem


def _media_target_path(
    *, media_type: MediaType | None, media_id: int | None, media_title: str | None
) -> str | None:
    if media_type is None or media_id is None:
        return None
    base = "/movies" if media_type is MediaType.MOVIE else "/series"
    if media_title:
      return f"{base}?search={quote(media_title)}&open={media_id}&inspector=1"
    return f"{base}?open={media_id}&inspector=1"


class EventEngine:
    @staticmethod
    async def build_dashboard_activity(
        db: AsyncSession,
        *,
        current_user: User,
        is_admin: bool,
        limit_per_tab: int = 20,
    ) -> tuple[list[DashboardActivityItem], list[DashboardActivityItem]]:
        media_events: list[DashboardActivityItem] = []
        system_events: list[DashboardActivityItem] = []

        request_query = (
            select(
                literal("request").label("event_type"),
                ProtectionRequest.id.label("source_id"),
                ProtectionRequest.created_at.label("created_at"),
                ProtectionRequest.status.label("request_status"),
                ProtectionRequest.media_type.label("media_type"),
                ProtectionRequest.movie_id.label("movie_id"),
                ProtectionRequest.series_id.label("series_id"),
                Movie.title.label("movie_title"),
                Series.title.label("series_title"),
                User.username.label("actor_username"),
                User.display_name.label("actor_display_name"),
            )
            .outerjoin(User, User.id == ProtectionRequest.requested_by_user_id)
            .outerjoin(Movie, Movie.id == ProtectionRequest.movie_id)
            .outerjoin(Series, Series.id == ProtectionRequest.series_id)
        )
        if not is_admin:
            request_query = request_query.where(
                ProtectionRequest.requested_by_user_id == current_user.id
            )

        protected_query = select(
            literal("protected").label("event_type"),
            ProtectedMedia.id.label("source_id"),
            ProtectedMedia.created_at.label("created_at"),
            literal(None).label("request_status"),
            ProtectedMedia.media_type.label("media_type"),
            ProtectedMedia.movie_id.label("movie_id"),
            ProtectedMedia.series_id.label("series_id"),
            Movie.title.label("movie_title"),
            Series.title.label("series_title"),
            User.username.label("actor_username"),
            User.display_name.label("actor_display_name"),
        ).outerjoin(User, User.id == ProtectedMedia.protected_by_user_id).outerjoin(
            Movie, Movie.id == ProtectedMedia.movie_id
        ).outerjoin(Series, Series.id == ProtectedMedia.series_id)

        candidate_query = select(
            literal("candidate").label("event_type"),
            ReclaimCandidate.id.label("source_id"),
            ReclaimCandidate.created_at.label("created_at"),
            literal(None).label("request_status"),
            ReclaimCandidate.media_type.label("media_type"),
            ReclaimCandidate.movie_id.label("movie_id"),
            ReclaimCandidate.series_id.label("series_id"),
            Movie.title.label("movie_title"),
            Series.title.label("series_title"),
            literal(None).label("actor_username"),
            literal(None).label("actor_display_name"),
        ).outerjoin(Movie, Movie.id == ReclaimCandidate.movie_id).outerjoin(
            Series, Series.id == ReclaimCandidate.series_id
        )

        history_query = select(
            literal("reclaimed").label("event_type"),
            ReclaimHistory.id.label("source_id"),
            ReclaimHistory.created_at.label("created_at"),
            literal(None).label("request_status"),
            ReclaimHistory.media_type.label("media_type"),
            literal(None).label("movie_id"),
            literal(None).label("series_id"),
            ReclaimHistory.name.label("movie_title"),
            literal(None).label("series_title"),
            literal(None).label("actor_username"),
            literal(None).label("actor_display_name"),
        )

        media_rows = []
        for query in (request_query, protected_query, candidate_query, history_query):
            media_rows.extend((await db.execute(query.limit(limit_per_tab))).all())
        media_rows.sort(key=lambda row: row.created_at or datetime.now(UTC), reverse=True)

        for row in media_rows[:limit_per_tab]:
            media_type = row.media_type if isinstance(row.media_type, MediaType) else None
            media_id = row.movie_id if media_type is MediaType.MOVIE else row.series_id
            media_title = row.movie_title or row.series_title
            actor_display = row.actor_display_name or row.actor_username

            if row.event_type == "request" and row.request_status is not None:
                if row.request_status is ProtectionRequestStatus.APPROVED:
                    title = "Protection approved"
                elif row.request_status is ProtectionRequestStatus.DENIED:
                    title = "Protection denied"
                else:
                    title = "Protection requested"
            elif row.event_type == "protected":
                title = "Protection added"
            elif row.event_type == "candidate":
                scope = "Movie" if media_type is MediaType.MOVIE else "Item"
                title = f"{scope} became reclaimable"
            else:
                title = "Space reclaimed"

            media_events.append(
                DashboardActivityItem(
                    id=f"{row.event_type}-{row.source_id}",
                    type=str(row.event_type),
                    title=title,
                    subtitle=media_title,
                    created_at=to_utc_isoformat(row.created_at) or "",
                    actor_display=actor_display,
                    media_type=media_type.value if media_type else None,
                    media_title=media_title,
                    target_path=_media_target_path(
                        media_type=media_type,
                        media_id=media_id,
                        media_title=media_title,
                    ),
                )
            )

        task_rows = (
            await db.execute(
                select(TaskRun)
                .where(TaskRun.status.in_([TaskStatus.COMPLETED, TaskStatus.ERROR]))
                .order_by(TaskRun.created_at.desc())
                .limit(limit_per_tab)
            )
        ).scalars().all()

        for task in task_rows:
            subtitle = (
                f"Processed {task.items_processed} items"
                if task.items_processed is not None
                else None
            )
            system_events.append(
                DashboardActivityItem(
                    id=f"task-{task.id}",
                    type="task",
                    title=f"{task.task.friendly_name()} {task.status.value}",
                    subtitle=subtitle,
                    created_at=to_utc_isoformat(task.created_at) or "",
                )
            )

        return media_events, system_events