from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.api.candidate_views import normalize_reason_parts, reason_tokens
from backend.core.auth import (
    get_current_user,
    has_page_access,
    has_permission,
    require_page_access,
)
from backend.core.auto_delete import resolve_auto_delete_policy
from backend.core.utils.datetime_utils import to_utc_isoformat
from backend.core.utils.misc import normalize_genre_names
from backend.core.utils.resolution import guesstimate_resolution
from backend.database import get_db
from backend.database.models import (
    DeleteRequest,
    Episode,
    GeneralSettings,
    Movie,
    MovieArrRef,
    MovieVersion,
    ProtectedMedia,
    ProtectionRequest,
    QueryFilter,
    ReclaimCandidate,
    ReclaimHistory,
    ReclaimRule,
    Season,
    Series,
    SeriesArrRef,
    SeriesServiceRef,
    ServiceMediaLibrary,
    TaskSchedule,
    User,
)
from backend.enums import (
    CandidateFileOpOperation,
    MediaType,
    PageAccess,
    Permission,
    ProtectionRequestStatus,
    Task,
    UserRole,
)
from backend.jobs.candidate_file_ops import queue_candidate_file_op_job
from backend.models.jobs import CandidateFileOpJobItem
from backend.models.media import (
    ArrRefResponse,
    CandidateDisplayGroup,
    CandidateEntry,
    CandidateLibraryRef,
    CandidateOperationQueuedResponse,
    CandidatesPresenceResponse,
    DecisionFilterUpsertRequest,
    DeleteCandidatesRequest,
    EpisodeWithStatus,
    MediaStatusInfo,
    MoveCandidatesRequest,
    MediaFilterCatalogResponse,
    MediaFilterOptionResponse,
    MovieVersionResponse,
    MovieWithStatus,
    PaginatedCandidatesResponse,
    PaginatedMediaResponse,
    PaginatedReclaimHistoryResponse,
    QueryFilterResponse,
    ReclaimHistoryAttributes,
    ReclaimHistoryEntry,
    SeasonWithStatus,
    SeriesServiceRefResponse,
    SeriesWithStatus,
    SmartFilterUpsertRequest,
)
from backend.services.decision_engine import DecisionEngine, DecisionSignals
from backend.services.query_engine import QueryEngineSpec, apply_spec, get_filter_catalog

router = APIRouter(prefix="/api/media", tags=["media"])


def extract_genre_names(genres: Any) -> list[str] | None:
    """
    Extract genre names from TMDB genre objects.

    Comes in format [{'id': 16, 'name': 'Animation'}, ...] but we only want the names.
    """
    return normalize_genre_names(genres)


def _whole_series_scope_clause(model: Any) -> Any:
    """Clause to filter for entries that apply to a whole series (not season or episode specific)."""
    return and_(model.season_id.is_(None), model.episode_id.is_(None))


def _season_only_scope_clause(model: Any) -> Any:
    """Clause to filter for entries that apply to a season only (not whole series or episode specific)."""
    return and_(model.season_id.isnot(None), model.episode_id.is_(None))


def _episode_scope_clause(model: Any) -> Any:
    """Clause to filter for entries that apply to an episode (not whole series or season specific)."""
    return model.episode_id.isnot(None)


def _candidate_row_sort_key(
    row: Any,
) -> tuple[int, int, int, str]:
    """Keep whole-series rows first, then seasons, then episodes within each series."""
    if row.ReclaimCandidate.episode_id is not None:
        scope_rank = 2
    elif row.ReclaimCandidate.season_id is not None:
        scope_rank = 1
    else:
        scope_rank = 0
    return (
        scope_rank,
        row.season_number or 0,
        row.episode_number or 0,
        to_utc_isoformat(row.ReclaimCandidate.created_at) or "",
    )


def _candidate_effective_size_expr() -> Any:
    return func.coalesce(
        ReclaimCandidate.estimated_space_bytes,
        MovieVersion.size,
        Episode.size,
        Season.size,
        Movie.size,
        Series.size,
        0,
    )


async def _get_auto_delete_delays(db: AsyncSession) -> tuple[int, int]:
    settings = (await db.execute(select(GeneralSettings))).scalars().first()
    movie_delay = settings.auto_delete_movie_delay_days if settings is not None else 14
    series_delay = settings.auto_delete_series_delay_days if settings is not None else 7
    return movie_delay, series_delay


async def _get_rule_actions_by_ids(
    db: AsyncSession, rule_ids: set[int]
) -> dict[int, dict[str, Any] | None]:
    if not rule_ids:
        return {}
    return {
        rule.id: rule.action
        for rule in (
            await db.execute(select(ReclaimRule).where(ReclaimRule.id.in_(rule_ids)))
        )
        .scalars()
        .all()
    }


def _candidate_policy_values(
    candidate: ReclaimCandidate | None,
    *,
    media_type: MediaType,
    rule_actions_by_id: dict[int, dict[str, Any] | None],
    movie_delay_days: int,
    series_delay_days: int,
    now: datetime,
) -> tuple[datetime | None, datetime | None, int | None]:
    if candidate is None:
        return None, None, None
    policy = resolve_auto_delete_policy(
        media_type=media_type,
        matched_rule_ids=cast(list[int], candidate.matched_rule_ids or []),
        created_at=cast(datetime, candidate.created_at),
        rule_actions_by_id=rule_actions_by_id,
        movie_delay_days=movie_delay_days,
        series_delay_days=series_delay_days,
        now=now,
    )
    return candidate.created_at, policy.eligible_at, policy.delay_days


def _apply_legacy_decision_state(
    *,
    query: Any,
    count_query: Any,
    media_type: MediaType,
    decision_state: str | None,
) -> tuple[Any, Any]:
    if not decision_state:
        return query, count_query

    if media_type is MediaType.MOVIE:
        if decision_state == "safe_to_delete":
            query = query.join(ReclaimCandidate, ReclaimCandidate.movie_id == Movie.id).distinct()
            count_query = count_query.join(ReclaimCandidate, ReclaimCandidate.movie_id == Movie.id).distinct()
        elif decision_state == "protected":
            query = query.join(ProtectedMedia, ProtectedMedia.movie_id == Movie.id).distinct()
            count_query = count_query.join(ProtectedMedia, ProtectedMedia.movie_id == Movie.id).distinct()
        elif decision_state == "waiting":
            clause = and_(
                ProtectionRequest.movie_id == Movie.id,
                ProtectionRequest.status == ProtectionRequestStatus.PENDING,
            )
            query = query.join(ProtectionRequest, clause).distinct()
            count_query = count_query.join(ProtectionRequest, clause).distinct()
        elif decision_state == "unwatched":
            query = query.where(Movie.view_count <= 0, Movie.last_viewed_at.is_(None))
            count_query = count_query.where(Movie.view_count <= 0, Movie.last_viewed_at.is_(None))
        elif decision_state == "watching":
            cutoff = datetime.now(UTC).replace(microsecond=0) - timedelta(days=14)
            query = query.where(Movie.last_viewed_at.is_not(None), Movie.last_viewed_at >= cutoff)
            count_query = count_query.where(Movie.last_viewed_at.is_not(None), Movie.last_viewed_at >= cutoff)
        return query, count_query

    if decision_state == "safe_to_delete":
        query = query.join(ReclaimCandidate, ReclaimCandidate.series_id == Series.id).distinct()
        count_query = count_query.join(ReclaimCandidate, ReclaimCandidate.series_id == Series.id).distinct()
    elif decision_state == "protected":
        query = query.join(ProtectedMedia, ProtectedMedia.series_id == Series.id).distinct()
        count_query = count_query.join(ProtectedMedia, ProtectedMedia.series_id == Series.id).distinct()
    elif decision_state == "waiting":
        clause = and_(
            ProtectionRequest.series_id == Series.id,
            ProtectionRequest.status == ProtectionRequestStatus.PENDING,
        )
        query = query.join(ProtectionRequest, clause).distinct()
        count_query = count_query.join(ProtectionRequest, clause).distinct()
    elif decision_state == "unwatched":
        query = query.where(Series.view_count <= 0, Series.last_viewed_at.is_(None))
        count_query = count_query.where(Series.view_count <= 0, Series.last_viewed_at.is_(None))
    elif decision_state == "watching":
        cutoff = datetime.now(UTC).replace(microsecond=0) - timedelta(days=14)
        query = query.where(Series.last_viewed_at.is_not(None), Series.last_viewed_at >= cutoff)
        count_query = count_query.where(Series.last_viewed_at.is_not(None), Series.last_viewed_at >= cutoff)

    return query, count_query


def _apply_candidate_filters(
    query: Any, media_type: MediaType | None, search: str | None
) -> Any:
    if media_type is not None:
        query = query.where(ReclaimCandidate.media_type == media_type)

    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                Movie.title.ilike(search_term),
                Series.title.ilike(search_term),
                ReclaimCandidate.reason.ilike(search_term),
            )
        )

    return query


def _title_with_year(title: str, year: int | None) -> str:
    return f"{title} ({year})" if year is not None else title


def _quality_suffix(
    resolution: str | None,
    hdr: bool | None,
    dolby_vision: bool | None,
) -> str:
    parts: list[str] = []
    if resolution:
        parts.append(resolution)
    if hdr:
        parts.append("HDR")
    if dolby_vision:
        parts.append("DV")
    return f" - {' '.join(parts)}" if parts else ""


def _candidate_job_item_from_row(row: Any) -> CandidateFileOpJobItem | None:
    if row.media_type is MediaType.MOVIE:
        if not row.movie_title:
            return None
        resolution = (
            row.version_video_resolution if row.movie_version_id is not None else None
        )
        hdr = row.version_video_hdr if row.movie_version_id is not None else None
        dolby_vision = (
            row.version_video_dolby_vision if row.movie_version_id is not None else None
        )
        title = _title_with_year(row.movie_title, row.movie_year)
        movie_scope: Literal["movie", "version"] = (
            "version" if row.movie_version_id is not None else "movie"
        )
        return CandidateFileOpJobItem(
            candidate_id=row.candidate_id,
            media_type=MediaType.MOVIE,
            scope=movie_scope,
            title=row.movie_title,
            year=row.movie_year,
            tmdb_id=row.movie_tmdb_id,
            resolution=resolution,
            hdr=hdr,
            dolby_vision=dolby_vision,
            display_label=f"{title}{_quality_suffix(resolution, hdr, dolby_vision)}",
        )

    if not row.series_title:
        return None

    title = _title_with_year(row.series_title, row.series_year)
    resolution = guesstimate_resolution(
        row.season_max_video_width,
        row.season_max_video_height,
        None,
    )
    hdr = row.season_has_hdr
    dolby_vision = row.season_has_dolby_vision

    if row.episode_id is not None and row.episode_number is not None:
        episode_tag = (
            f"S{int(row.season_number or 0):02d}E{int(row.episode_number):02d}"
        )
        if row.episode_name:
            title = f"{title} - {episode_tag} - {row.episode_name}"
        else:
            title = f"{title} - {episode_tag}"
        scope: Literal["series", "season", "episode"] = "episode"
    elif row.season_id is not None and row.season_number is not None:
        title = f"{title} - Season {int(row.season_number)}"
        scope = "season"
    else:
        scope = "series"
        resolution = None
        hdr = None
        dolby_vision = None

    return CandidateFileOpJobItem(
        candidate_id=row.candidate_id,
        media_type=MediaType.SERIES,
        scope=scope,
        title=row.series_title,
        year=row.series_year,
        tmdb_id=row.series_tmdb_id,
        season_number=row.season_number,
        episode_number=row.episode_number,
        episode_name=row.episode_name,
        resolution=resolution,
        hdr=hdr,
        dolby_vision=dolby_vision,
        display_label=f"{title}{_quality_suffix(resolution, hdr, dolby_vision)}",
    )


async def _get_candidate_job_labels(
    db: AsyncSession,
    candidate_ids: list[int],
    *,
    limit: int = 5,
) -> tuple[list[str], list[CandidateFileOpJobItem], int]:
    if not candidate_ids:
        return [], [], 0

    result = await db.execute(
        select(
            ReclaimCandidate.id.label("candidate_id"),
            ReclaimCandidate.media_type.label("media_type"),
            ReclaimCandidate.movie_version_id.label("movie_version_id"),
            ReclaimCandidate.season_id.label("season_id"),
            ReclaimCandidate.episode_id.label("episode_id"),
            Movie.title.label("movie_title"),
            Movie.year.label("movie_year"),
            Movie.tmdb_id.label("movie_tmdb_id"),
            MovieVersion.video_resolution.label("version_video_resolution"),
            MovieVersion.video_hdr.label("version_video_hdr"),
            MovieVersion.video_dolby_vision.label("version_video_dolby_vision"),
            Series.title.label("series_title"),
            Series.year.label("series_year"),
            Series.tmdb_id.label("series_tmdb_id"),
            Season.season_number.label("season_number"),
            Season.has_hdr.label("season_has_hdr"),
            Season.has_dolby_vision.label("season_has_dolby_vision"),
            Season.max_video_width.label("season_max_video_width"),
            Season.max_video_height.label("season_max_video_height"),
            Episode.episode_number.label("episode_number"),
            Episode.name.label("episode_name"),
        )
        .outerjoin(Movie, ReclaimCandidate.movie_id == Movie.id)
        .outerjoin(MovieVersion, ReclaimCandidate.movie_version_id == MovieVersion.id)
        .outerjoin(Series, ReclaimCandidate.series_id == Series.id)
        .outerjoin(Season, ReclaimCandidate.season_id == Season.id)
        .outerjoin(Episode, ReclaimCandidate.episode_id == Episode.id)
        .where(ReclaimCandidate.id.in_(candidate_ids))
    )
    details = [
        detail
        for detail in (_candidate_job_item_from_row(row) for row in result.all())
        if detail is not None
    ]
    preview_details = details[:limit]
    labels = [detail.display_label for detail in preview_details]
    return labels, details, len(details)


async def _get_candidate_page_groups(
    db: AsyncSession,
    *,
    media_type: MediaType | None,
    search: str | None,
    sort_by: str,
    sort_order: str,
    page: int,
    per_page: int,
) -> tuple[int, list[CandidateDisplayGroup]]:
    descriptor_query = (
        select(
            ReclaimCandidate.id.label("candidate_id"),
            ReclaimCandidate.media_type.label("media_type"),
            ReclaimCandidate.movie_id.label("movie_id"),
            ReclaimCandidate.movie_version_id.label("movie_version_id"),
            ReclaimCandidate.series_id.label("series_id"),
            ReclaimCandidate.season_id.label("season_id"),
            ReclaimCandidate.episode_id.label("episode_id"),
            ReclaimCandidate.created_at.label("created_at"),
            ReclaimCandidate.matched_rule_ids.label("matched_rule_ids"),
            _candidate_effective_size_expr().label("effective_size_bytes"),
            Movie.title.label("movie_title"),
            Series.title.label("series_title"),
        )
        .outerjoin(Movie, ReclaimCandidate.movie_id == Movie.id)
        .outerjoin(MovieVersion, ReclaimCandidate.movie_version_id == MovieVersion.id)
        .outerjoin(Series, ReclaimCandidate.series_id == Series.id)
        .outerjoin(Season, ReclaimCandidate.season_id == Season.id)
        .outerjoin(Episode, ReclaimCandidate.episode_id == Episode.id)
    )
    descriptor_query = _apply_candidate_filters(descriptor_query, media_type, search)
    descriptor_rows = (await db.execute(descriptor_query)).all()

    deletion_movie_delay_days = 14
    deletion_series_delay_days = 7
    deletion_rule_actions: dict[int, dict[str, Any] | None] = {}
    if sort_by == "auto_delete_eligible_at":
        settings = (await db.execute(select(GeneralSettings))).scalars().first()
        if settings is not None:
            deletion_movie_delay_days = settings.auto_delete_movie_delay_days
            deletion_series_delay_days = settings.auto_delete_series_delay_days
        rule_ids = {
            rule_id
            for row in descriptor_rows
            for rule_id in (row.matched_rule_ids or [])
        }
        if rule_ids:
            deletion_rule_actions = {
                rule.id: rule.action
                for rule in (
                    await db.execute(
                        select(ReclaimRule).where(ReclaimRule.id.in_(rule_ids))
                    )
                )
                .scalars()
                .all()
            }

    series_with_nested_scope = {
        row.series_id
        for row in descriptor_rows
        if row.series_id is not None
        and (row.season_id is not None or row.episode_id is not None)
    }

    groups_by_key: dict[tuple[str, int], CandidateDisplayGroup] = {}
    for row in descriptor_rows:
        if (
            row.media_type is MediaType.MOVIE
            and row.movie_version_id is not None
            and row.movie_id is not None
        ):
            key = ("movie_versions", row.movie_id)
            media_id = row.movie_id
        elif (
            row.media_type is MediaType.SERIES
            and row.series_id is not None
            and row.series_id in series_with_nested_scope
        ):
            key = ("series_seasons", row.series_id)
            media_id = row.series_id
        else:
            key = ("flat", row.candidate_id)
            media_id = (
                row.movie_id if row.media_type is MediaType.MOVIE else row.series_id
            )

        title = (
            row.movie_title if row.media_type is MediaType.MOVIE else row.series_title
        )
        size_bytes = int(row.effective_size_bytes or 0)
        created_at = row.created_at or datetime.min
        deletion_at = resolve_auto_delete_policy(
            media_type=row.media_type,
            matched_rule_ids=row.matched_rule_ids or [],
            created_at=created_at,
            rule_actions_by_id=deletion_rule_actions,
            movie_delay_days=deletion_movie_delay_days,
            series_delay_days=deletion_series_delay_days,
        ).eligible_at
        group = groups_by_key.get(key)
        if group is None:
            groups_by_key[key] = CandidateDisplayGroup(
                group_kind=key[0],
                media_id=media_id,
                sort_title=title or "",
                sort_created_at=created_at,
                sort_deletion_at=deletion_at,
                sort_size=size_bytes,
                candidate_ids=[row.candidate_id],
            )
            continue

        group.candidate_ids.append(row.candidate_id)
        group.sort_created_at = max(group.sort_created_at, created_at)
        group.sort_deletion_at = min(group.sort_deletion_at, deletion_at)
        group.sort_size += size_bytes

    groups = list(groups_by_key.values())
    if sort_by == "auto_delete_eligible_at":
        groups.sort(
            key=lambda group: (
                group.sort_deletion_at,
                group.sort_title.lower(),
                group.media_id or group.candidate_ids[0],
            ),
            reverse=sort_order == "desc",
        )
    elif sort_by == "media_title":
        groups.sort(
            key=lambda group: (
                group.sort_title.lower(),
                group.media_id or group.candidate_ids[0],
            ),
            reverse=sort_order == "desc",
        )
    elif sort_by == "estimated_space_bytes":
        groups.sort(
            key=lambda group: (
                group.sort_size,
                group.sort_title.lower(),
                group.media_id or group.candidate_ids[0],
            ),
            reverse=sort_order == "desc",
        )
    else:
        groups.sort(
            key=lambda group: (
                group.sort_created_at,
                group.sort_title.lower(),
                group.media_id or group.candidate_ids[0],
            ),
            reverse=sort_order == "desc",
        )

    total = len(groups)
    offset = (page - 1) * per_page
    return total, groups[offset : offset + per_page]


@router.get("/movies", response_model=PaginatedMediaResponse)
async def get_movies(
    _user: Annotated[User, Depends(require_page_access(PageAccess.MOVIES))],
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort_by: str = Query(
        "title", pattern="^(title|added_at|arr_added_at|size|vote_average|year)$"
    ),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    search: str | None = Query(None, max_length=200),
    candidates_only: bool = Query(False),
    monitored: Annotated[bool | None, Query()] = None,
    status_filter: Annotated[str | None, Query(max_length=50)] = None,
    arr_tag: str | None = Query(None, max_length=100),
    decision_state: str | None = Query(None, max_length=50),
    arr_filter_ids: list[int] = Query(default_factory=list),
    decision_filter_ids: list[int] = Query(default_factory=list),
    smart_filter_ids: list[int] = Query(default_factory=list),
) -> PaginatedMediaResponse:
    """
    Get all movies with status information.

    Includes whether each movie is:
    - A deletion candidate
    - Protected
    - Has pending exception request
    """
    arr_tag = arr_tag if isinstance(arr_tag, str) and arr_tag.strip() else None
    decision_state = (
        decision_state
        if isinstance(decision_state, str) and decision_state.strip()
        else None
    )
    arr_filter_ids = [int(v) for v in arr_filter_ids] if isinstance(arr_filter_ids, list) else []
    decision_filter_ids = [int(v) for v in decision_filter_ids] if isinstance(decision_filter_ids, list) else []
    smart_filter_ids = [int(v) for v in smart_filter_ids] if isinstance(smart_filter_ids, list) else []
    # build base query
    query = (
        select(Movie)
        .where(Movie.removed_at.is_(None))
        .options(selectinload(Movie.versions))
    )
    count_query = (
        select(func.count()).select_from(Movie).where(Movie.removed_at.is_(None))
    )

    if arr_tag:
        legacy = await db.scalar(
            select(QueryFilter.id).where(
                QueryFilter.kind == "imported_arr",
                QueryFilter.media_type == MediaType.MOVIE,
                QueryFilter.name == arr_tag,
                QueryFilter.enabled.is_(True),
            )
        )
        if legacy is not None:
            arr_filter_ids.append(int(legacy))

    query, count_query = await apply_spec(
        db,
        spec=QueryEngineSpec(
            media_type=MediaType.MOVIE,
            search=search,
            candidates_only=candidates_only,
            monitored=monitored,
            media_status=status_filter,
            imported_filter_ids=arr_filter_ids,
            decision_filter_ids=decision_filter_ids,
            smart_filter_ids=smart_filter_ids,
        ),
        query=query,
        count_query=count_query,
    )
    query, count_query = _apply_legacy_decision_state(
        query=query,
        count_query=count_query,
        media_type=MediaType.MOVIE,
        decision_state=decision_state,
    )

    # apply sorting
    order_column = getattr(Movie, sort_by)
    if sort_order == "desc":
        query = query.order_by(order_column.desc())
    else:
        query = query.order_by(order_column.asc())

    # get total count
    total = (await db.execute(count_query)).scalar_one()

    # apply pagination
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    # execute query
    result = await db.execute(query)
    movies = result.scalars().all()

    # fetch status information for all movies
    movie_ids = [m.id for m in movies]
    movie_delay_days, series_delay_days = await _get_auto_delete_delays(db)

    # get candidates
    candidates_result = await db.execute(
        select(ReclaimCandidate).where(ReclaimCandidate.movie_id.in_(movie_ids))
    )
    candidates = {c.movie_id: c for c in candidates_result.scalars().all()}
    movie_rule_actions_by_id = await _get_rule_actions_by_ids(
        db,
        {
            rule_id
            for candidate in candidates.values()
            for rule_id in (candidate.matched_rule_ids or [])
            if isinstance(rule_id, int)
        },
    )

    # get protected entries
    now = datetime.now(UTC)
    protected_result = await db.execute(
        select(ProtectedMedia).where(
            ProtectedMedia.movie_id.in_(movie_ids),
            or_(
                ProtectedMedia.permanent.is_(True),
                ProtectedMedia.expires_at.is_(None),
                ProtectedMedia.expires_at > now,
            ),
        )
    )
    protected = {b.movie_id: b for b in protected_result.scalars().all()}

    # get exception requests
    requests_result = await db.execute(
        select(ProtectionRequest).where(
            ProtectionRequest.movie_id.in_(movie_ids),
            ProtectionRequest.status == ProtectionRequestStatus.PENDING,
        )
    )
    requests = {r.movie_id: r for r in requests_result.scalars().all()}

    delete_requests_result = await db.execute(
        select(DeleteRequest).where(
            DeleteRequest.movie_id.in_(movie_ids),
            DeleteRequest.status == ProtectionRequestStatus.PENDING,
        )
    )
    delete_requests = {r.movie_id: r for r in delete_requests_result.scalars().all()}

    # build response with status
    items: list[MovieWithStatus | SeriesWithStatus] = []
    for movie in movies:
        candidate = candidates.get(movie.id)
        protection_entry = protected.get(movie.id)
        request = requests.get(movie.id)
        delete_request = delete_requests.get(movie.id)
        candidate_created_at, candidate_eligible_at, candidate_delay_days = (
            _candidate_policy_values(
                candidate,
                media_type=MediaType.MOVIE,
                rule_actions_by_id=movie_rule_actions_by_id,
                movie_delay_days=movie_delay_days,
                series_delay_days=series_delay_days,
                now=now,
            )
        )
        movie_library_names = [
            version.library_name for version in movie.versions if version.library_name
        ]

        status = MediaStatusInfo(
            is_candidate=candidate is not None,
            candidate_id=candidate.id if candidate else None,
            candidate_reason=candidate.reason if candidate else None,
            candidate_space_bytes=candidate.estimated_space_bytes
            if candidate
            else None,
            candidate_created_at=to_utc_isoformat(candidate_created_at),
            candidate_eligible_at=to_utc_isoformat(candidate_eligible_at),
            candidate_delay_days=candidate_delay_days,
            is_protected=protection_entry is not None,
            protected_reason=protection_entry.reason if protection_entry else None,
            protected_permanent=protection_entry.permanent
            if protection_entry
            else True,
            protected_created_at=(
                to_utc_isoformat(protection_entry.created_at) if protection_entry else None
            ),
            protected_expires_at=(
                to_utc_isoformat(protection_entry.expires_at) if protection_entry else None
            ),
            protected_source=protection_entry.source if protection_entry else None,
            has_pending_request=request is not None,
            request_id=request.id if request else None,
            request_status=request.status if request else None,
            request_reason=request.reason if request else None,
            has_pending_delete_request=delete_request is not None,
            delete_request_id=delete_request.id if delete_request else None,
            delete_request_status=delete_request.status if delete_request else None,
            delete_request_reason=delete_request.reason if delete_request else None,
        )
        status.decision = DecisionEngine.evaluate(
            DecisionSignals(
                media_type=MediaType.MOVIE,
                title=movie.title,
                size_bytes=movie.size,
                view_count=movie.view_count,
                last_viewed_at=movie.last_viewed_at,
                added_at=movie.added_at,
                arr_added_at=movie.arr_added_at,
                is_candidate=status.is_candidate,
                candidate_reason=status.candidate_reason,
                candidate_space_bytes=status.candidate_space_bytes,
                candidate_created_at=candidate_created_at,
                candidate_eligible_at=candidate_eligible_at,
                candidate_delay_days=status.candidate_delay_days,
                is_protected=status.is_protected,
                protected_reason=status.protected_reason,
                protected_permanent=status.protected_permanent,
                protected_source=status.protected_source,
                protected_rule_name=status.protected_rule_name,
                protected_created_at=protection_entry.created_at if protection_entry else None,
                protected_expires_at=protection_entry.expires_at if protection_entry else None,
                has_pending_request=status.has_pending_request,
                request_reason=status.request_reason,
                has_pending_delete_request=status.has_pending_delete_request,
                delete_request_reason=status.delete_request_reason,
                tags=movie.arr_tags,
                library_names=movie_library_names,
            ),
            now=now,
        )

        movie_arr_refs_result = await db.execute(
            select(MovieArrRef).where(MovieArrRef.movie_id == movie.id)
        )
        movie_arr_refs = movie_arr_refs_result.scalars().all()

        movie_dict: dict[str, Any] = {
            "id": movie.id,
            "title": movie.title,
            "year": movie.year,
            "tmdb_id": movie.tmdb_id,
            "size": movie.size,
            "versions": [
                MovieVersionResponse(
                    id=v.id,
                    service=v.service.value,
                    service_item_id=v.service_item_id,
                    service_media_id=v.service_media_id,
                    library_id=v.library_id,
                    library_name=v.library_name,
                    path=v.path,
                    size=v.size,
                    added_at=to_utc_isoformat(v.added_at),
                    arr_added_at=to_utc_isoformat(v.arr_added_at),
                    file_name=v.file_name,
                    container=v.container,
                    duration=v.duration,
                    video_track_count=v.video_track_count,
                    video_codec=v.video_codec,
                    video_codec_family=v.video_codec_family,
                    video_hdr=v.video_hdr,
                    video_dolby_vision=v.video_dolby_vision,
                    video_dolby_vision_profile=v.video_dolby_vision_profile,
                    video_bitrate=v.video_bitrate,
                    video_bit_depth=v.video_bit_depth,
                    video_width=v.video_width,
                    video_height=v.video_height,
                    video_resolution=v.video_resolution,
                    video_color_primaries=v.video_color_primaries,
                    video_color_space=v.video_color_space,
                    video_color_transfer=v.video_color_transfer,
                    video_fps=v.video_fps,
                    audio_count=v.audio_count,
                    audio_languages=v.audio_languages,
                    audio_codec=v.audio_codec,
                    audio_codec_family=v.audio_codec_family,
                    audio_title=v.audio_title,
                    audio_language=v.audio_language,
                    audio_channels=v.audio_channels,
                    audio_channel_layout=v.audio_channel_layout,
                    audio_bitrate=v.audio_bitrate,
                    audio_sample_rate=v.audio_sample_rate,
                    subtitle_count=v.subtitle_count,
                    subtitle_has_forced=v.subtitle_has_forced,
                    subtitle_languages=v.subtitle_languages,
                    has_chapters=v.has_chapters,
                )
                for v in movie.versions
            ],
            "arr_refs": [
                ArrRefResponse(
                    service_type="radarr",
                    service_config_id=ref.service_config_id,
                    arr_id=ref.arr_movie_id,
                )
                for ref in movie_arr_refs
            ],
            "imdb_id": movie.imdb_id,
            "imdb_rating": movie.imdb_rating,
            "imdb_vote_count": movie.imdb_vote_count,
            "imdb_ratings_refreshed_at": to_utc_isoformat(
                movie.imdb_ratings_refreshed_at
            ),
            "anilist_id": movie.anilist_id,
            "anilist_score": movie.anilist_score,
            "anilist_popularity": movie.anilist_popularity,
            "anilist_favourites": movie.anilist_favourites,
            "anilist_refreshed_at": to_utc_isoformat(movie.anilist_refreshed_at),
            "rottentomatoes_tomato_meter": movie.rottentomatoes_tomato_meter,
            "rottentomatoes_tomato_vote_count": (
                movie.rottentomatoes_tomato_vote_count
            ),
            "rottentomatoes_popcorn_meter": movie.rottentomatoes_popcorn_meter,
            "rottentomatoes_popcorn_vote_count": (
                movie.rottentomatoes_popcorn_vote_count
            ),
            "metacritic_metascore": movie.metacritic_metascore,
            "metacritic_vote_count": movie.metacritic_vote_count,
            "metacritic_user_score": movie.metacritic_user_score,
            "metacritic_user_vote_count": movie.metacritic_user_vote_count,
            "trakt_rating": movie.trakt_rating,
            "trakt_vote_count": movie.trakt_vote_count,
            "letterboxd_score": movie.letterboxd_score,
            "letterboxd_vote_count": movie.letterboxd_vote_count,
            "external_ratings_source": movie.external_ratings_source,
            "external_ratings_refreshed_at": to_utc_isoformat(
                movie.external_ratings_refreshed_at
            ),
            "tmdb_title": movie.tmdb_title,
            "original_title": movie.original_title,
            "tmdb_release_date": to_utc_isoformat(movie.tmdb_release_date),
            "tmdb_collection_id": movie.tmdb_collection_id,
            "tmdb_collection_name": movie.tmdb_collection_name,
            "tmdb_in_collection": (
                movie.tmdb_collection_id is not None
                if movie.tmdb_collection_checked
                else None
            ),
            "original_language": movie.original_language,
            "poster_url": movie.poster_url,
            "backdrop_url": movie.backdrop_url,
            "overview": movie.overview,
            "genres": extract_genre_names(movie.genres),
            "popularity": movie.popularity,
            "vote_average": movie.vote_average,
            "vote_count": movie.vote_count,
            "runtime": movie.runtime,
            "tagline": movie.tagline,
            "last_viewed_at": to_utc_isoformat(movie.last_viewed_at),
            "view_count": movie.view_count,
            "status": status,
            "arr_tags": movie.arr_tags,
            "added_at": to_utc_isoformat(movie.added_at),
            "arr_added_at": to_utc_isoformat(movie.arr_added_at),
        }
        items.append(MovieWithStatus(**movie_dict))

    total_pages = (total + per_page - 1) // per_page

    return PaginatedMediaResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.get("/series", response_model=PaginatedMediaResponse)
async def get_series(
    _user: Annotated[User, Depends(require_page_access(PageAccess.SERIES))],
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort_by: str = Query(
        "title", pattern="^(title|added_at|arr_added_at|size|vote_average|year)$"
    ),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    search: str | None = Query(None, max_length=200),
    candidates_only: bool = Query(False),
    monitored: Annotated[bool | None, Query()] = None,
    status_filter: Annotated[str | None, Query(max_length=50)] = None,
    arr_tag: str | None = Query(None, max_length=100),
    decision_state: str | None = Query(None, max_length=50),
    arr_filter_ids: list[int] = Query(default_factory=list),
    decision_filter_ids: list[int] = Query(default_factory=list),
    smart_filter_ids: list[int] = Query(default_factory=list),
) -> PaginatedMediaResponse:
    """
    Get all series with status information.

    Includes whether each series is:
    - A deletion candidate
    - Protected
    - Has pending exception request
    """
    arr_tag = arr_tag if isinstance(arr_tag, str) and arr_tag.strip() else None
    decision_state = (
        decision_state
        if isinstance(decision_state, str) and decision_state.strip()
        else None
    )
    arr_filter_ids = [int(v) for v in arr_filter_ids] if isinstance(arr_filter_ids, list) else []
    decision_filter_ids = [int(v) for v in decision_filter_ids] if isinstance(decision_filter_ids, list) else []
    smart_filter_ids = [int(v) for v in smart_filter_ids] if isinstance(smart_filter_ids, list) else []
    # build base query
    query = (
        select(Series)
        .where(Series.removed_at.is_(None))
        .options(selectinload(Series.service_refs))
    )
    count_query = (
        select(func.count()).select_from(Series).where(Series.removed_at.is_(None))
    )

    if arr_tag:
        legacy = await db.scalar(
            select(QueryFilter.id).where(
                QueryFilter.kind == "imported_arr",
                QueryFilter.media_type == MediaType.SERIES,
                QueryFilter.name == arr_tag,
                QueryFilter.enabled.is_(True),
            )
        )
        if legacy is not None:
            arr_filter_ids.append(int(legacy))

    query, count_query = await apply_spec(
        db,
        spec=QueryEngineSpec(
            media_type=MediaType.SERIES,
            search=search,
            candidates_only=candidates_only,
            monitored=monitored,
            media_status=status_filter,
            imported_filter_ids=arr_filter_ids,
            decision_filter_ids=decision_filter_ids,
            smart_filter_ids=smart_filter_ids,
        ),
        query=query,
        count_query=count_query,
    )
    query, count_query = _apply_legacy_decision_state(
        query=query,
        count_query=count_query,
        media_type=MediaType.SERIES,
        decision_state=decision_state,
    )

    # apply sorting
    order_column = getattr(Series, sort_by)
    if sort_order == "desc":
        query = query.order_by(order_column.desc())
    else:
        query = query.order_by(order_column.asc())

    # get total count
    total = (await db.execute(count_query)).scalar_one()

    # apply pagination
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    # execute query
    result = await db.execute(query)
    series_list = result.scalars().all()

    # fetch status information for all series
    series_ids = [s.id for s in series_list]
    movie_delay_days, series_delay_days = await _get_auto_delete_delays(db)

    # count library seasons per series (one GROUP BY query for the whole page)
    season_counts_result = await db.execute(
        select(Season.series_id, func.count(Season.id))
        .where(Season.series_id.in_(series_ids))
        .group_by(Season.series_id)
    )
    season_counts: dict[int, int] = {
        int(k): int(v) for k, v in season_counts_result.all()
    }
    episode_counts_result = await db.execute(
        select(Season.series_id, func.coalesce(func.sum(Season.episode_count), 0))
        .where(Season.series_id.in_(series_ids))
        .group_by(Season.series_id)
    )
    episode_counts: dict[int, int] = {
        int(k): int(v) for k, v in episode_counts_result.all()
    }

    # get series level candidates (no season)
    candidates_result = await db.execute(
        select(ReclaimCandidate).where(
            ReclaimCandidate.series_id.in_(series_ids),
            ReclaimCandidate.season_id.is_(None),
        )
    )
    candidates = {c.series_id: c for c in candidates_result.scalars().all()}
    series_rule_actions_by_id = await _get_rule_actions_by_ids(
        db,
        {
            rule_id
            for candidate in candidates.values()
            for rule_id in (candidate.matched_rule_ids or [])
            if isinstance(rule_id, int)
        },
    )

    # collect series_ids that have at least one season level candidate
    season_cands_result = await db.execute(
        select(ReclaimCandidate.series_id).where(
            ReclaimCandidate.series_id.in_(series_ids),
            _season_only_scope_clause(ReclaimCandidate),
        )
    )
    series_with_season_cands: set[int] = {
        row[0] for row in season_cands_result.all() if row[0] is not None
    }
    series_child_candidate_stats_result = await db.execute(
        select(
            ReclaimCandidate.series_id,
            func.count(ReclaimCandidate.id),
            func.coalesce(func.sum(ReclaimCandidate.estimated_space_bytes), 0),
        )
        .where(
            ReclaimCandidate.series_id.in_(series_ids),
            or_(
                ReclaimCandidate.season_id.is_not(None),
                ReclaimCandidate.episode_id.is_not(None),
            ),
        )
        .group_by(ReclaimCandidate.series_id)
    )
    series_child_candidate_stats: dict[int, tuple[int, int]] = {
        int(series_id): (int(count), int(space_bytes or 0))
        for series_id, count, space_bytes in series_child_candidate_stats_result.all()
        if series_id is not None
    }

    # get protected entries
    now = datetime.now(UTC)
    protected_result = await db.execute(
        select(ProtectedMedia).where(
            ProtectedMedia.series_id.in_(series_ids),
            _whole_series_scope_clause(ProtectedMedia),
            or_(
                ProtectedMedia.permanent.is_(True),
                ProtectedMedia.expires_at.is_(None),
                ProtectedMedia.expires_at > now,
            ),
        )
    )
    protected = {b.series_id: b for b in protected_result.scalars().all()}

    # get exception requests
    requests_result = await db.execute(
        select(ProtectionRequest).where(
            ProtectionRequest.series_id.in_(series_ids),
            _whole_series_scope_clause(ProtectionRequest),
            ProtectionRequest.status == ProtectionRequestStatus.PENDING,
        )
    )
    requests = {r.series_id: r for r in requests_result.scalars().all()}

    delete_requests_result = await db.execute(
        select(DeleteRequest).where(
            DeleteRequest.series_id.in_(series_ids),
            _whole_series_scope_clause(DeleteRequest),
            DeleteRequest.status == ProtectionRequestStatus.PENDING,
        )
    )
    delete_requests = {r.series_id: r for r in delete_requests_result.scalars().all()}

    # build response with status
    items: list[MovieWithStatus | SeriesWithStatus] = []
    for series in series_list:
        candidate = candidates.get(series.id)
        protection_entry = protected.get(series.id)
        request = requests.get(series.id)
        delete_request = delete_requests.get(series.id)
        candidate_created_at, candidate_eligible_at, candidate_delay_days = (
            _candidate_policy_values(
                candidate,
                media_type=MediaType.SERIES,
                rule_actions_by_id=series_rule_actions_by_id,
                movie_delay_days=movie_delay_days,
                series_delay_days=series_delay_days,
                now=now,
            )
        )
        child_candidate_count, child_candidate_space_bytes = series_child_candidate_stats.get(
            series.id, (0, 0)
        )
        library_names = [
            ref.library_name for ref in series.service_refs if ref.library_name
        ]

        status = MediaStatusInfo(
            is_candidate=candidate is not None,
            candidate_id=candidate.id if candidate else None,
            candidate_reason=candidate.reason if candidate else None,
            candidate_space_bytes=candidate.estimated_space_bytes
            if candidate
            else None,
            candidate_created_at=to_utc_isoformat(candidate_created_at),
            candidate_eligible_at=to_utc_isoformat(candidate_eligible_at),
            candidate_delay_days=candidate_delay_days,
            is_protected=protection_entry is not None,
            protected_reason=protection_entry.reason if protection_entry else None,
            protected_permanent=protection_entry.permanent
            if protection_entry
            else True,
            protected_created_at=(
                to_utc_isoformat(protection_entry.created_at) if protection_entry else None
            ),
            protected_expires_at=(
                to_utc_isoformat(protection_entry.expires_at) if protection_entry else None
            ),
            protected_source=protection_entry.source if protection_entry else None,
            has_pending_request=request is not None,
            request_id=request.id if request else None,
            request_status=request.status if request else None,
            request_reason=request.reason if request else None,
            has_pending_delete_request=delete_request is not None,
            delete_request_id=delete_request.id if delete_request else None,
            delete_request_status=delete_request.status if delete_request else None,
            delete_request_reason=delete_request.reason if delete_request else None,
            child_candidate_count=child_candidate_count,
            child_candidate_space_bytes=child_candidate_space_bytes,
        )
        status.decision = DecisionEngine.evaluate(
            DecisionSignals(
                media_type=MediaType.SERIES,
                title=series.title,
                size_bytes=series.size,
                view_count=series.view_count,
                last_viewed_at=series.last_viewed_at,
                added_at=series.added_at,
                arr_added_at=series.arr_added_at,
                is_candidate=status.is_candidate,
                candidate_reason=status.candidate_reason,
                candidate_space_bytes=status.candidate_space_bytes,
                candidate_created_at=candidate_created_at,
                candidate_eligible_at=candidate_eligible_at,
                candidate_delay_days=status.candidate_delay_days,
                is_protected=status.is_protected,
                protected_reason=status.protected_reason,
                protected_permanent=status.protected_permanent,
                protected_source=status.protected_source,
                protected_rule_name=status.protected_rule_name,
                protected_created_at=protection_entry.created_at if protection_entry else None,
                protected_expires_at=protection_entry.expires_at if protection_entry else None,
                has_pending_request=status.has_pending_request,
                request_reason=status.request_reason,
                has_pending_delete_request=status.has_pending_delete_request,
                delete_request_reason=status.delete_request_reason,
                child_candidate_count=child_candidate_count,
                child_candidate_space_bytes=child_candidate_space_bytes,
                tags=series.arr_tags,
                library_names=library_names,
            ),
            now=now,
        )

        series_arr_refs_result = await db.execute(
            select(SeriesArrRef).where(SeriesArrRef.series_id == series.id)
        )
        series_arr_refs = series_arr_refs_result.scalars().all()

        series_dict: dict[str, Any] = {
            "id": series.id,
            "title": series.title,
            "year": series.year,
            "tmdb_id": series.tmdb_id,
            "size": series.size,
            "service_refs": [
                SeriesServiceRefResponse(
                    service=ref.service.value,
                    service_id=ref.service_id,
                    library_id=ref.library_id,
                    library_name=ref.library_name,
                    path=ref.path,
                )
                for ref in series.service_refs
            ],
            "arr_refs": [
                ArrRefResponse(
                    service_type="sonarr",
                    service_config_id=ref.service_config_id,
                    arr_id=ref.arr_series_id,
                )
                for ref in series_arr_refs
            ],
            "imdb_id": series.imdb_id,
            "imdb_rating": series.imdb_rating,
            "imdb_vote_count": series.imdb_vote_count,
            "imdb_ratings_refreshed_at": to_utc_isoformat(
                series.imdb_ratings_refreshed_at
            ),
            "anilist_id": series.anilist_id,
            "anilist_score": series.anilist_score,
            "anilist_popularity": series.anilist_popularity,
            "anilist_favourites": series.anilist_favourites,
            "anilist_refreshed_at": to_utc_isoformat(series.anilist_refreshed_at),
            "rottentomatoes_tomato_meter": series.rottentomatoes_tomato_meter,
            "rottentomatoes_tomato_vote_count": (
                series.rottentomatoes_tomato_vote_count
            ),
            "rottentomatoes_popcorn_meter": series.rottentomatoes_popcorn_meter,
            "rottentomatoes_popcorn_vote_count": (
                series.rottentomatoes_popcorn_vote_count
            ),
            "metacritic_metascore": series.metacritic_metascore,
            "metacritic_vote_count": series.metacritic_vote_count,
            "metacritic_user_score": series.metacritic_user_score,
            "metacritic_user_vote_count": series.metacritic_user_vote_count,
            "trakt_rating": series.trakt_rating,
            "trakt_vote_count": series.trakt_vote_count,
            "letterboxd_score": series.letterboxd_score,
            "letterboxd_vote_count": series.letterboxd_vote_count,
            "external_ratings_source": series.external_ratings_source,
            "external_ratings_refreshed_at": to_utc_isoformat(
                series.external_ratings_refreshed_at
            ),
            "tvdb_id": series.tvdb_id,
            "tmdb_title": series.tmdb_title,
            "original_title": series.original_title,
            "tmdb_first_air_date": to_utc_isoformat(series.tmdb_first_air_date),
            "tmdb_last_air_date": to_utc_isoformat(series.tmdb_last_air_date),
            "original_language": series.original_language,
            "poster_url": series.poster_url,
            "backdrop_url": series.backdrop_url,
            "overview": series.overview,
            "genres": extract_genre_names(series.genres),
            "popularity": series.popularity,
            "vote_average": series.vote_average,
            "vote_count": series.vote_count,
            "season_count": series.season_count,
            "tagline": series.tagline,
            "last_viewed_at": to_utc_isoformat(series.last_viewed_at),
            "view_count": series.view_count,
            "has_hdr": series.has_hdr,
            "has_dolby_vision": series.has_dolby_vision,
            "max_video_width": series.max_video_width,
            "max_video_height": series.max_video_height,
            "video_codec_families": series.video_codec_families,
            "audio_codec_families": series.audio_codec_families,
            "max_audio_channels": series.max_audio_channels,
            "subtitle_languages": series.subtitle_languages,
            "status": status,
            "arr_tags": series.arr_tags,
            "has_season_candidates": series.id in series_with_season_cands
            and candidate is None,
            "library_season_count": season_counts.get(series.id, 0),
            "library_episode_count": episode_counts.get(series.id, 0),
            "added_at": to_utc_isoformat(series.added_at),
            "arr_added_at": to_utc_isoformat(series.arr_added_at),
        }
        items.append(SeriesWithStatus(**series_dict))

    total_pages = (total + per_page - 1) // per_page

    return PaginatedMediaResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.get("/filters", response_model=MediaFilterCatalogResponse)
async def get_media_filters(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    media_type: MediaType = Query(MediaType.MOVIE),
) -> MediaFilterCatalogResponse:
    required_page = (
        PageAccess.MOVIES if media_type is MediaType.MOVIE else PageAccess.SERIES
    )
    if not has_page_access(current_user, required_page):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{required_page.value.replace('_', ' ').title()} page access required",
        )
    return await get_filter_catalog(
        db,
        current_user=current_user,
        media_type=media_type,
    )


def _query_filter_to_response(row: QueryFilter) -> QueryFilterResponse:
    return QueryFilterResponse(
        id=row.id,
        name=row.name,
        kind=row.kind,
        media_type=row.media_type,
        read_only=row.read_only,
        provider_service=row.provider_service.value if row.provider_service else None,
        provider_filter_id=row.provider_filter_id,
        definition=row.definition or {},
    )


@router.get("/query/decision-filters", response_model=list[QueryFilterResponse])
async def list_decision_filters(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    media_type: MediaType = Query(MediaType.MOVIE),
) -> list[QueryFilterResponse]:
    rows = (
        await db.execute(
            select(QueryFilter).where(
                QueryFilter.kind == "decision",
                QueryFilter.user_id == current_user.id,
                QueryFilter.media_type == media_type,
                QueryFilter.enabled.is_(True),
            )
        )
    ).scalars().all()
    return [_query_filter_to_response(row) for row in rows]


@router.post("/query/decision-filters", response_model=QueryFilterResponse)
async def create_decision_filter(
    payload: DecisionFilterUpsertRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> QueryFilterResponse:
    row = QueryFilter(
        name=payload.name.strip() or "Decision Filter",
        kind="decision",
        user_id=current_user.id,
        media_type=payload.media_type,
        read_only=False,
        definition=payload.definition.model_dump(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _query_filter_to_response(row)


@router.put("/query/decision-filters/{filter_id}", response_model=QueryFilterResponse)
async def update_decision_filter(
    filter_id: int,
    payload: DecisionFilterUpsertRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> QueryFilterResponse:
    row = (
        await db.execute(
            select(QueryFilter).where(
                QueryFilter.id == filter_id,
                QueryFilter.kind == "decision",
                QueryFilter.user_id == current_user.id,
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Decision filter not found")
    row.name = payload.name.strip() or row.name
    row.media_type = payload.media_type
    row.definition = payload.definition.model_dump()
    await db.commit()
    await db.refresh(row)
    return _query_filter_to_response(row)


@router.delete("/query/decision-filters/{filter_id}")
async def delete_decision_filter(
    filter_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    row = (
        await db.execute(
            select(QueryFilter).where(
                QueryFilter.id == filter_id,
                QueryFilter.kind == "decision",
                QueryFilter.user_id == current_user.id,
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Decision filter not found")
    row.enabled = False
    await db.commit()
    return {"ok": True}


@router.get("/query/smart-filters", response_model=list[QueryFilterResponse])
async def list_smart_filters(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    media_type: MediaType = Query(MediaType.MOVIE),
) -> list[QueryFilterResponse]:
    rows = (
        await db.execute(
            select(QueryFilter).where(
                QueryFilter.kind == "smart",
                QueryFilter.user_id == current_user.id,
                QueryFilter.media_type == media_type,
                QueryFilter.enabled.is_(True),
            )
        )
    ).scalars().all()
    return [_query_filter_to_response(row) for row in rows]


@router.post("/query/smart-filters", response_model=QueryFilterResponse)
async def create_smart_filter(
    payload: SmartFilterUpsertRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> QueryFilterResponse:
    row = QueryFilter(
        name=payload.name.strip() or "Smart Filter",
        kind="smart",
        user_id=current_user.id,
        media_type=payload.media_type,
        read_only=False,
        definition={
            "arr_filter_ids": payload.arr_filter_ids,
            "decision_filter_ids": payload.decision_filter_ids,
            "search": payload.search,
            "candidates_only": payload.candidates_only,
            "sort_by": payload.sort_by,
            "sort_order": payload.sort_order,
            "per_page": payload.per_page,
            "poster_size": payload.poster_size,
            "view_mode": payload.view_mode,
            "page": payload.page,
        },
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _query_filter_to_response(row)


@router.put("/query/smart-filters/{filter_id}", response_model=QueryFilterResponse)
async def update_smart_filter(
    filter_id: int,
    payload: SmartFilterUpsertRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> QueryFilterResponse:
    row = (
        await db.execute(
            select(QueryFilter).where(
                QueryFilter.id == filter_id,
                QueryFilter.kind == "smart",
                QueryFilter.user_id == current_user.id,
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Smart filter not found")
    row.name = payload.name.strip() or row.name
    row.media_type = payload.media_type
    row.definition = {
        "arr_filter_ids": payload.arr_filter_ids,
        "decision_filter_ids": payload.decision_filter_ids,
        "search": payload.search,
        "candidates_only": payload.candidates_only,
        "sort_by": payload.sort_by,
        "sort_order": payload.sort_order,
        "per_page": payload.per_page,
        "poster_size": payload.poster_size,
        "view_mode": payload.view_mode,
        "page": payload.page,
    }
    await db.commit()
    await db.refresh(row)
    return _query_filter_to_response(row)


@router.delete("/query/smart-filters/{filter_id}")
async def delete_smart_filter(
    filter_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    row = (
        await db.execute(
            select(QueryFilter).where(
                QueryFilter.id == filter_id,
                QueryFilter.kind == "smart",
                QueryFilter.user_id == current_user.id,
            )
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Smart filter not found")
    row.enabled = False
    await db.commit()
    return {"ok": True}


@router.get("/series/{series_id}/seasons", response_model=list[SeasonWithStatus])
async def get_series_seasons(
    series_id: int,
    _user: Annotated[User, Depends(require_page_access(PageAccess.SERIES))],
    db: AsyncSession = Depends(get_db),
) -> list[SeasonWithStatus]:
    """Get per-season status for a series."""
    series_result = await db.execute(
        select(Series).where(Series.id == series_id, Series.removed_at.is_(None))
    )
    if series_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Series not found"
        )

    seasons_result = await db.execute(
        select(Season)
        .where(Season.series_id == series_id)
        .order_by(Season.season_number)
    )
    seasons = seasons_result.scalars().all()
    movie_delay_days, series_delay_days = await _get_auto_delete_delays(db)

    season_ids = [s.id for s in seasons]
    if not season_ids:
        return []

    # season level reclaim candidates
    cand_result = await db.execute(
        select(ReclaimCandidate).where(
            ReclaimCandidate.season_id.in_(season_ids),
            ReclaimCandidate.episode_id.is_(None),
        )
    )
    season_candidates = {c.season_id: c for c in cand_result.scalars().all()}
    season_rule_actions_by_id = await _get_rule_actions_by_ids(
        db,
        {
            rule_id
            for candidate in season_candidates.values()
            for rule_id in (candidate.matched_rule_ids or [])
            if isinstance(rule_id, int)
        },
    )

    # season level protection entries
    now = datetime.now(UTC)
    prot_result = await db.execute(
        select(ProtectedMedia).where(
            ProtectedMedia.series_id == series_id,
            or_(
                ProtectedMedia.permanent.is_(True),
                ProtectedMedia.expires_at.is_(None),
                ProtectedMedia.expires_at > now,
            ),
        )
    )
    protected_entries = prot_result.scalars().all()
    whole_series_protected = next(
        (p for p in protected_entries if p.season_id is None and p.episode_id is None),
        None,
    )
    season_protected = {
        p.season_id: p
        for p in protected_entries
        if p.season_id is not None and p.episode_id is None
    }
    request_result = await db.execute(
        select(ProtectionRequest).where(
            ProtectionRequest.series_id == series_id,
            ProtectionRequest.status == ProtectionRequestStatus.PENDING,
        )
    )
    pending_requests = request_result.scalars().all()
    whole_series_request = next(
        (r for r in pending_requests if r.season_id is None and r.episode_id is None),
        None,
    )
    season_requests = {
        r.season_id: r
        for r in pending_requests
        if r.season_id is not None and r.episode_id is None
    }
    delete_req_result = await db.execute(
        select(DeleteRequest).where(
            DeleteRequest.series_id == series_id,
            DeleteRequest.status == ProtectionRequestStatus.PENDING,
        )
    )
    pending_delete_requests = delete_req_result.scalars().all()
    whole_series_delete_request = next(
        (
            r
            for r in pending_delete_requests
            if r.season_id is None and r.episode_id is None
        ),
        None,
    )
    season_delete_requests = {
        r.season_id: r
        for r in pending_delete_requests
        if r.season_id is not None and r.episode_id is None
    }

    items: list[SeasonWithStatus] = []
    for season in seasons:
        cand = season_candidates.get(season.id)
        prot = season_protected.get(season.id) or whole_series_protected
        req = season_requests.get(season.id) or whole_series_request
        delete_req = (
            season_delete_requests.get(season.id) or whole_series_delete_request
        )
        candidate_created_at, candidate_eligible_at, candidate_delay_days = (
            _candidate_policy_values(
                cand,
                media_type=MediaType.SERIES,
                rule_actions_by_id=season_rule_actions_by_id,
                movie_delay_days=movie_delay_days,
                series_delay_days=series_delay_days,
                now=now,
            )
        )
        season_status = MediaStatusInfo(
            is_candidate=cand is not None,
            candidate_id=cand.id if cand else None,
            candidate_reason=cand.reason if cand else None,
            candidate_space_bytes=cand.estimated_space_bytes if cand else None,
            candidate_created_at=to_utc_isoformat(candidate_created_at),
            candidate_eligible_at=to_utc_isoformat(candidate_eligible_at),
            candidate_delay_days=candidate_delay_days,
            is_protected=prot is not None,
            protected_reason=prot.reason if prot else None,
            protected_permanent=prot.permanent if prot else True,
            protected_created_at=(to_utc_isoformat(prot.created_at) if prot else None),
            protected_expires_at=(to_utc_isoformat(prot.expires_at) if prot else None),
            protected_source=prot.source if prot else None,
            has_pending_request=req is not None,
            request_id=req.id if req else None,
            request_status=req.status if req else None,
            request_reason=req.reason if req else None,
            has_pending_delete_request=delete_req is not None,
            delete_request_id=delete_req.id if delete_req else None,
            delete_request_status=delete_req.status if delete_req else None,
            delete_request_reason=delete_req.reason if delete_req else None,
        )
        season_status.decision = DecisionEngine.evaluate(
            DecisionSignals(
                media_type=MediaType.SERIES,
                title=f"Season {season.season_number}",
                size_bytes=season.size,
                view_count=season.view_count or 0,
                last_viewed_at=season.last_viewed_at,
                added_at=season.added_at,
                arr_added_at=season.arr_added_at,
                is_candidate=season_status.is_candidate,
                candidate_reason=season_status.candidate_reason,
                candidate_space_bytes=season_status.candidate_space_bytes,
                candidate_created_at=candidate_created_at,
                candidate_eligible_at=candidate_eligible_at,
                candidate_delay_days=season_status.candidate_delay_days,
                is_protected=season_status.is_protected,
                protected_reason=season_status.protected_reason,
                protected_permanent=season_status.protected_permanent,
                protected_source=season_status.protected_source,
                protected_rule_name=season_status.protected_rule_name,
                protected_created_at=prot.created_at if prot else None,
                protected_expires_at=prot.expires_at if prot else None,
                has_pending_request=season_status.has_pending_request,
                request_reason=season_status.request_reason,
                has_pending_delete_request=season_status.has_pending_delete_request,
                delete_request_reason=season_status.delete_request_reason,
            ),
            now=now,
        )
        items.append(
            SeasonWithStatus(
                id=season.id,
                season_number=season.season_number,
                episode_count=season.episode_count,
                size=season.size,
                view_count=season.view_count or 0,
                added_at=to_utc_isoformat(season.added_at),
                arr_added_at=to_utc_isoformat(season.arr_added_at),
                last_viewed_at=to_utc_isoformat(season.last_viewed_at),
                air_date=to_utc_isoformat(season.air_date),
                has_hdr=season.has_hdr,
                has_dolby_vision=season.has_dolby_vision,
                max_video_width=season.max_video_width,
                max_video_height=season.max_video_height,
                video_codec_families=season.video_codec_families,
                audio_codec_families=season.audio_codec_families,
                audio_languages=season.audio_languages,
                max_audio_channels=season.max_audio_channels,
                subtitle_languages=season.subtitle_languages,
                status=season_status,
            )
        )

    return items


@router.get("/series/{series_id}/episodes", response_model=list[EpisodeWithStatus])
async def get_series_episodes(
    series_id: int,
    _user: Annotated[User, Depends(require_page_access(PageAccess.SERIES))],
    db: AsyncSession = Depends(get_db),
) -> list[EpisodeWithStatus]:
    """Get per episode status for a series."""
    series_result = await db.execute(
        select(Series).where(Series.id == series_id, Series.removed_at.is_(None))
    )
    if series_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Series not found"
        )

    episodes_result = await db.execute(
        select(Episode, Season)
        .join(Season, Episode.season_id == Season.id)
        .where(Season.series_id == series_id)
        .order_by(Season.season_number, Episode.episode_number)
    )
    rows = episodes_result.all()
    if not rows:
        return []
    movie_delay_days, series_delay_days = await _get_auto_delete_delays(db)

    episode_ids = [row.Episode.id for row in rows]

    cand_result = await db.execute(
        select(ReclaimCandidate).where(ReclaimCandidate.episode_id.in_(episode_ids))
    )
    episode_candidates = {c.episode_id: c for c in cand_result.scalars().all()}
    episode_rule_actions_by_id = await _get_rule_actions_by_ids(
        db,
        {
            rule_id
            for candidate in episode_candidates.values()
            for rule_id in (candidate.matched_rule_ids or [])
            if isinstance(rule_id, int)
        },
    )

    now = datetime.now(UTC)
    prot_result = await db.execute(
        select(ProtectedMedia).where(
            ProtectedMedia.series_id == series_id,
            or_(
                ProtectedMedia.permanent.is_(True),
                ProtectedMedia.expires_at.is_(None),
                ProtectedMedia.expires_at > now,
            ),
        )
    )
    protected_entries = prot_result.scalars().all()
    whole_series_protected = next(
        (p for p in protected_entries if p.season_id is None and p.episode_id is None),
        None,
    )
    season_protected = {
        p.season_id: p
        for p in protected_entries
        if p.season_id is not None and p.episode_id is None
    }
    episode_protected = {
        p.episode_id: p for p in protected_entries if p.episode_id is not None
    }

    request_result = await db.execute(
        select(ProtectionRequest).where(
            ProtectionRequest.series_id == series_id,
            ProtectionRequest.status == ProtectionRequestStatus.PENDING,
        )
    )
    pending_requests = request_result.scalars().all()
    whole_series_request = next(
        (r for r in pending_requests if r.season_id is None and r.episode_id is None),
        None,
    )
    season_requests = {
        r.season_id: r
        for r in pending_requests
        if r.season_id is not None and r.episode_id is None
    }
    episode_requests = {
        r.episode_id: r for r in pending_requests if r.episode_id is not None
    }

    delete_req_result = await db.execute(
        select(DeleteRequest).where(
            DeleteRequest.series_id == series_id,
            DeleteRequest.status == ProtectionRequestStatus.PENDING,
        )
    )
    pending_delete_requests = delete_req_result.scalars().all()
    whole_series_delete_request = next(
        (
            r
            for r in pending_delete_requests
            if r.season_id is None and r.episode_id is None
        ),
        None,
    )
    season_delete_requests = {
        r.season_id: r
        for r in pending_delete_requests
        if r.season_id is not None and r.episode_id is None
    }
    episode_delete_requests = {
        r.episode_id: r for r in pending_delete_requests if r.episode_id is not None
    }

    items: list[EpisodeWithStatus] = []
    for row in rows:
        episode = row.Episode
        season = row.Season
        cand = episode_candidates.get(episode.id)
        prot = (
            episode_protected.get(episode.id)
            or season_protected.get(season.id)
            or whole_series_protected
        )
        req = (
            episode_requests.get(episode.id)
            or season_requests.get(season.id)
            or whole_series_request
        )
        delete_req = (
            episode_delete_requests.get(episode.id)
            or season_delete_requests.get(season.id)
            or whole_series_delete_request
        )
        candidate_created_at, candidate_eligible_at, candidate_delay_days = (
            _candidate_policy_values(
                cand,
                media_type=MediaType.SERIES,
                rule_actions_by_id=episode_rule_actions_by_id,
                movie_delay_days=movie_delay_days,
                series_delay_days=series_delay_days,
                now=now,
            )
        )
        episode_status = MediaStatusInfo(
            is_candidate=cand is not None,
            candidate_id=cand.id if cand else None,
            candidate_reason=cand.reason if cand else None,
            candidate_space_bytes=cand.estimated_space_bytes if cand else None,
            candidate_created_at=to_utc_isoformat(candidate_created_at),
            candidate_eligible_at=to_utc_isoformat(candidate_eligible_at),
            candidate_delay_days=candidate_delay_days,
            is_protected=prot is not None,
            protected_reason=prot.reason if prot else None,
            protected_permanent=prot.permanent if prot else True,
            protected_created_at=(to_utc_isoformat(prot.created_at) if prot else None),
            protected_expires_at=(to_utc_isoformat(prot.expires_at) if prot else None),
            protected_source=prot.source if prot else None,
            has_pending_request=req is not None,
            request_id=req.id if req else None,
            request_status=req.status if req else None,
            request_reason=req.reason if req else None,
            has_pending_delete_request=delete_req is not None,
            delete_request_id=delete_req.id if delete_req else None,
            delete_request_status=delete_req.status if delete_req else None,
            delete_request_reason=delete_req.reason if delete_req else None,
        )
        episode_status.decision = DecisionEngine.evaluate(
            DecisionSignals(
                media_type=MediaType.SERIES,
                title=episode.name or f"Episode {episode.episode_number}",
                size_bytes=episode.size,
                view_count=episode.view_count,
                last_viewed_at=episode.last_viewed_at,
                added_at=episode.air_date,
                arr_added_at=episode.arr_added_at,
                is_candidate=episode_status.is_candidate,
                candidate_reason=episode_status.candidate_reason,
                candidate_space_bytes=episode_status.candidate_space_bytes,
                candidate_created_at=candidate_created_at,
                candidate_eligible_at=candidate_eligible_at,
                candidate_delay_days=episode_status.candidate_delay_days,
                is_protected=episode_status.is_protected,
                protected_reason=episode_status.protected_reason,
                protected_permanent=episode_status.protected_permanent,
                protected_source=episode_status.protected_source,
                protected_rule_name=episode_status.protected_rule_name,
                protected_created_at=prot.created_at if prot else None,
                protected_expires_at=prot.expires_at if prot else None,
                has_pending_request=episode_status.has_pending_request,
                request_reason=episode_status.request_reason,
                has_pending_delete_request=episode_status.has_pending_delete_request,
                delete_request_reason=episode_status.delete_request_reason,
            ),
            now=now,
        )
        items.append(
            EpisodeWithStatus(
                id=episode.id,
                season_id=season.id,
                season_number=season.season_number,
                episode_number=episode.episode_number,
                name=episode.name,
                size=episode.size,
                view_count=episode.view_count,
                air_date=to_utc_isoformat(episode.air_date),
                arr_added_at=to_utc_isoformat(episode.arr_added_at),
                last_viewed_at=to_utc_isoformat(episode.last_viewed_at),
                status=episode_status,
            )
        )

    return items


@router.get("/candidates", response_model=PaginatedCandidatesResponse)
async def get_candidates(
    _user: Annotated[User, Depends(require_page_access(PageAccess.CANDIDATES))],
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=200),
    sort_by: str = Query(
        "created_at",
        pattern="^(created_at|auto_delete_eligible_at|media_title|estimated_space_bytes)$",
    ),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    search: str | None = Query(None, max_length=200),
    media_type: MediaType | None = Query(None),
) -> PaginatedCandidatesResponse:
    """Get reclaim candidates paginated by display group, with media info and request status."""
    base_query = (
        select(
            ReclaimCandidate,
            #### movies ####
            Movie.title.label("movie_title"),
            Movie.year.label("movie_year"),
            Movie.size.label("movie_size"),
            # movie tmdb data
            Movie.tmdb_id.label("movie_tmdb_id"),
            Movie.tmdb_collection_id.label("movie_tmdb_collection_id"),
            Movie.tmdb_collection_name.label("movie_tmdb_collection_name"),
            Movie.tmdb_collection_checked.label("movie_tmdb_collection_checked"),
            Movie.imdb_id.label("movie_imdb_id"),
            Movie.imdb_rating.label("movie_imdb_rating"),
            Movie.imdb_vote_count.label("movie_imdb_vote_count"),
            Movie.anilist_id.label("movie_anilist_id"),
            Movie.anilist_score.label("movie_anilist_score"),
            Movie.anilist_popularity.label("movie_anilist_popularity"),
            Movie.anilist_favourites.label("movie_anilist_favourites"),
            Movie.rottentomatoes_tomato_meter.label(
                "movie_rottentomatoes_tomato_meter"
            ),
            Movie.rottentomatoes_tomato_vote_count.label(
                "movie_rottentomatoes_tomato_vote_count"
            ),
            Movie.rottentomatoes_popcorn_meter.label(
                "movie_rottentomatoes_popcorn_meter"
            ),
            Movie.rottentomatoes_popcorn_vote_count.label(
                "movie_rottentomatoes_popcorn_vote_count"
            ),
            Movie.metacritic_metascore.label("movie_metacritic_metascore"),
            Movie.metacritic_vote_count.label("movie_metacritic_vote_count"),
            Movie.metacritic_user_score.label("movie_metacritic_user_score"),
            Movie.metacritic_user_vote_count.label("movie_metacritic_user_vote_count"),
            Movie.trakt_rating.label("movie_trakt_rating"),
            Movie.trakt_vote_count.label("movie_trakt_vote_count"),
            Movie.letterboxd_score.label("movie_letterboxd_score"),
            Movie.letterboxd_vote_count.label("movie_letterboxd_vote_count"),
            Movie.external_ratings_source.label("movie_external_ratings_source"),
            Movie.external_ratings_refreshed_at.label(
                "movie_external_ratings_refreshed_at"
            ),
            Movie.poster_url.label("movie_poster_url"),
            Movie.genres.label("movie_genres"),
            Movie.popularity.label("movie_popularity"),
            Movie.vote_average.label("movie_vote_average"),
            Movie.vote_count.label("movie_vote_count"),
            Movie.status.label("movie_status"),
            Movie.added_at.label("movie_added_at"),
            Movie.arr_added_at.label("movie_arr_added_at"),
            Movie.last_viewed_at.label("movie_last_viewed_at"),
            Movie.view_count.label("movie_view_count"),
            # movie version
            MovieVersion.service.label("version_service"),
            MovieVersion.library_id.label("version_library_id"),
            MovieVersion.library_name.label("version_library_name"),
            MovieVersion.added_at.label("version_added_at"),
            MovieVersion.arr_added_at.label("version_arr_added_at"),
            MovieVersion.video_codec_family.label("version_video_codec_family"),
            MovieVersion.audio_codec_family.label("version_audio_codec_family"),
            MovieVersion.video_width.label("version_video_width"),
            MovieVersion.video_height.label("version_video_height"),
            MovieVersion.video_resolution.label("version_video_resolution"),
            MovieVersion.video_hdr.label("version_video_hdr"),
            MovieVersion.video_dolby_vision.label("version_video_dolby_vision"),
            MovieVersion.audio_channels.label("version_audio_channels"),
            MovieVersion.audio_languages.label("version_audio_languages"),
            MovieVersion.size.label("version_size"),
            MovieVersion.path.label("version_path"),
            MovieVersion.file_name.label("version_file_name"),
            MovieVersion.subtitle_languages.label("version_subtitle_languages"),
            #### series ####
            Series.title.label("series_title"),
            Series.year.label("series_year"),
            Series.size.label("series_size"),
            Series.poster_url.label("series_poster_url"),
            Season.season_number.label("season_number"),
            Season.size.label("season_size"),
            Season.has_hdr.label("season_has_hdr"),
            Season.has_dolby_vision.label("season_has_dolby_vision"),
            Season.max_video_width.label("season_max_video_width"),
            Season.max_video_height.label("season_max_video_height"),
            Season.video_codec_families.label("season_video_codec_families"),
            Season.audio_codec_families.label("season_audio_codec_families"),
            Season.audio_languages.label("season_audio_languages"),
            Season.subtitle_languages.label("season_subtitle_languages"),
            # series tmdb data
            Series.tmdb_id.label("series_tmdb_id"),
            Series.imdb_id.label("series_imdb_id"),
            Series.imdb_rating.label("series_imdb_rating"),
            Series.imdb_vote_count.label("series_imdb_vote_count"),
            Series.anilist_id.label("series_anilist_id"),
            Series.anilist_score.label("series_anilist_score"),
            Series.anilist_popularity.label("series_anilist_popularity"),
            Series.anilist_favourites.label("series_anilist_favourites"),
            Series.rottentomatoes_tomato_meter.label(
                "series_rottentomatoes_tomato_meter"
            ),
            Series.rottentomatoes_tomato_vote_count.label(
                "series_rottentomatoes_tomato_vote_count"
            ),
            Series.rottentomatoes_popcorn_meter.label(
                "series_rottentomatoes_popcorn_meter"
            ),
            Series.rottentomatoes_popcorn_vote_count.label(
                "series_rottentomatoes_popcorn_vote_count"
            ),
            Series.metacritic_metascore.label("series_metacritic_metascore"),
            Series.metacritic_vote_count.label("series_metacritic_vote_count"),
            Series.metacritic_user_score.label("series_metacritic_user_score"),
            Series.metacritic_user_vote_count.label(
                "series_metacritic_user_vote_count"
            ),
            Series.trakt_rating.label("series_trakt_rating"),
            Series.trakt_vote_count.label("series_trakt_vote_count"),
            Series.letterboxd_score.label("series_letterboxd_score"),
            Series.letterboxd_vote_count.label("series_letterboxd_vote_count"),
            Series.external_ratings_source.label("series_external_ratings_source"),
            Series.external_ratings_refreshed_at.label(
                "series_external_ratings_refreshed_at"
            ),
            Series.genres.label("series_genres"),
            Series.popularity.label("series_popularity"),
            Series.vote_average.label("series_vote_average"),
            Series.vote_count.label("series_vote_count"),
            Series.status.label("series_status"),
            Series.added_at.label("series_added_at"),
            Series.arr_added_at.label("series_arr_added_at"),
            Series.last_viewed_at.label("series_last_viewed_at"),
            Series.view_count.label("series_view_count"),
            Season.added_at.label("season_added_at"),
            Season.arr_added_at.label("season_arr_added_at"),
            Season.view_count.label("season_view_count"),
            Season.last_viewed_at.label("season_last_viewed_at"),
            # episode
            Episode.size.label("episode_size"),
            Episode.episode_number.label("episode_number"),
            Episode.name.label("episode_name"),
            Episode.arr_added_at.label("episode_arr_added_at"),
            Episode.view_count.label("episode_view_count"),
            Episode.last_viewed_at.label("episode_last_viewed_at"),
        )
        .outerjoin(Movie, ReclaimCandidate.movie_id == Movie.id)
        .outerjoin(MovieVersion, ReclaimCandidate.movie_version_id == MovieVersion.id)
        .outerjoin(Series, ReclaimCandidate.series_id == Series.id)
        .outerjoin(Season, ReclaimCandidate.season_id == Season.id)
        .outerjoin(Episode, ReclaimCandidate.episode_id == Episode.id)
    )
    base_query = _apply_candidate_filters(base_query, media_type, search)

    total, page_groups = await _get_candidate_page_groups(
        db,
        media_type=media_type,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        per_page=per_page,
    )

    if not page_groups:
        rows = []
    else:
        candidate_ids = [
            candidate_id
            for group in page_groups
            for candidate_id in group.candidate_ids
        ]
        candidate_group_position = {
            candidate_id: idx
            for idx, group in enumerate(page_groups)
            for candidate_id in group.candidate_ids
        }
        result = await db.execute(
            base_query.where(ReclaimCandidate.id.in_(candidate_ids))
        )
        rows = sorted(
            result.all(),
            key=lambda row: (
                candidate_group_position.get(row.ReclaimCandidate.id, -1),
                *_candidate_row_sort_key(row),
                row.ReclaimCandidate.id,
            ),
        )

    auto_delete_settings_row = (
        await db.execute(
            select(
                GeneralSettings,
                select(TaskSchedule.enabled)
                .where(TaskSchedule.task == Task.DELETE_CLEANUP_CANDIDATES)
                .scalar_subquery(),
            )
        )
    ).first()
    auto_delete_settings = (
        auto_delete_settings_row[0] if auto_delete_settings_row is not None else None
    )
    auto_delete_task_enabled = bool(
        auto_delete_settings_row[1] if auto_delete_settings_row is not None else False
    )
    auto_delete_is_active = bool(
        auto_delete_settings is not None
        and auto_delete_settings.auto_delete_enabled
        and auto_delete_task_enabled
    )
    auto_delete_movie_delay_days = (
        auto_delete_settings.auto_delete_movie_delay_days
        if auto_delete_settings is not None
        else 14
    )
    auto_delete_series_delay_days = (
        auto_delete_settings.auto_delete_series_delay_days
        if auto_delete_settings is not None
        else 7
    )
    candidate_rule_ids = {
        rule_id
        for row in rows
        for rule_id in (row.ReclaimCandidate.matched_rule_ids or [])
    }
    candidate_rule_actions_by_id: dict[int, dict[str, Any] | None] = {}
    if candidate_rule_ids:
        candidate_rule_actions_by_id = {
            rule.id: rule.action
            for rule in (
                await db.execute(
                    select(ReclaimRule).where(ReclaimRule.id.in_(candidate_rule_ids))
                )
            )
            .scalars()
            .all()
        }
    candidate_policy_now = datetime.now(UTC)

    # collect IDs to check for pending exception requests in one query each
    movie_ids = [
        r.ReclaimCandidate.movie_id
        for r in rows
        if r.ReclaimCandidate.media_type is MediaType.MOVIE
        and r.ReclaimCandidate.movie_id
    ]
    series_ids = [
        r.ReclaimCandidate.series_id for r in rows if r.ReclaimCandidate.series_id
    ]

    pending_movies_whole: set[int] = set()
    pending_movie_versions: set[tuple[int, int]] = set()
    pending_series: set[int] = set()
    pending_seasons: set[tuple[int, int]] = set()
    pending_episodes: set[tuple[int, int]] = set()

    if movie_ids:
        req_result = await db.execute(
            select(
                ProtectionRequest.movie_id, ProtectionRequest.movie_version_id
            ).where(
                ProtectionRequest.movie_id.in_(movie_ids),
                ProtectionRequest.status == ProtectionRequestStatus.PENDING,
            )
        )
        for movie_id, movie_version_id in req_result.all():
            if movie_id is None:
                continue
            if movie_version_id is None:
                pending_movies_whole.add(movie_id)
            else:
                pending_movie_versions.add((movie_id, movie_version_id))

    if series_ids:
        req_result = await db.execute(
            select(
                ProtectionRequest.series_id,
                ProtectionRequest.season_id,
                ProtectionRequest.episode_id,
            ).where(
                ProtectionRequest.series_id.in_(series_ids),
                ProtectionRequest.status == ProtectionRequestStatus.PENDING,
            )
        )
        for series_id, season_id, episode_id in req_result.all():
            if series_id is None:
                continue
            if episode_id is not None:
                pending_episodes.add((series_id, episode_id))
            elif season_id is not None:
                pending_seasons.add((series_id, season_id))
            else:
                pending_series.add(series_id)

    global_library_name_by_id: dict[str, str] = {}
    libraries_result = await db.execute(
        select(ServiceMediaLibrary.library_id, ServiceMediaLibrary.library_name)
    )
    for library_id, library_name in libraries_result.all():
        if not library_id or not library_name:
            continue
        if library_id not in global_library_name_by_id:
            global_library_name_by_id[library_id] = library_name

    movie_library_names_by_id: dict[int, list[str]] = {}
    if movie_ids:
        movie_versions_result = await db.execute(
            select(MovieVersion.movie_id, MovieVersion.library_name).where(
                MovieVersion.movie_id.in_(movie_ids)
            )
        )
        for movie_id, library_name in movie_versions_result.all():
            if movie_id is None or not library_name:
                continue
            names = movie_library_names_by_id.setdefault(movie_id, [])
            if library_name.casefold() not in {name.casefold() for name in names}:
                names.append(library_name)

    series_library_refs_by_id: dict[int, list[CandidateLibraryRef]] = {}
    if series_ids:
        refs_result = await db.execute(
            select(
                SeriesServiceRef.series_id,
                SeriesServiceRef.service,
                SeriesServiceRef.library_id,
                SeriesServiceRef.library_name,
            ).where(SeriesServiceRef.series_id.in_(series_ids))
        )
        for series_id, service, library_id, library_name in refs_result.all():
            if series_id is None or not library_id or not library_name:
                continue
            refs = series_library_refs_by_id.setdefault(series_id, [])
            if any(ref.library_id == library_id for ref in refs):
                continue
            refs.append(
                CandidateLibraryRef(
                    library_id=library_id,
                    library_name=library_name,
                    service=service.value if service is not None else None,
                )
            )

    items_out: list[CandidateEntry] = []
    for row in rows:
        c = row.ReclaimCandidate
        auto_delete_policy = resolve_auto_delete_policy(
            media_type=cast(MediaType, c.media_type),
            matched_rule_ids=cast(list[int], c.matched_rule_ids),
            created_at=cast(datetime, c.created_at),
            rule_actions_by_id=candidate_rule_actions_by_id,
            movie_delay_days=auto_delete_movie_delay_days,
            series_delay_days=auto_delete_series_delay_days,
            now=candidate_policy_now,
        )
        is_movie = c.media_type is MediaType.MOVIE
        media_id = c.movie_id if is_movie else c.series_id
        media_title = row.movie_title if is_movie else row.series_title
        media_year = row.movie_year if is_movie else row.series_year
        poster_url = row.movie_poster_url if is_movie else row.series_poster_url
        tmdb_id = row.movie_tmdb_id if is_movie else row.series_tmdb_id
        tmdb_collection_id = row.movie_tmdb_collection_id if is_movie else None
        tmdb_collection_name = row.movie_tmdb_collection_name if is_movie else None
        tmdb_collection_checked = (
            bool(row.movie_tmdb_collection_checked) if is_movie else False
        )
        tmdb_in_collection = (
            tmdb_collection_id is not None if tmdb_collection_checked else None
        )
        imdb_id = row.movie_imdb_id if is_movie else row.series_imdb_id
        imdb_rating = row.movie_imdb_rating if is_movie else row.series_imdb_rating
        imdb_vote_count = (
            row.movie_imdb_vote_count if is_movie else row.series_imdb_vote_count
        )
        anilist_id = row.movie_anilist_id if is_movie else row.series_anilist_id
        anilist_score = (
            row.movie_anilist_score if is_movie else row.series_anilist_score
        )
        anilist_popularity = (
            row.movie_anilist_popularity if is_movie else row.series_anilist_popularity
        )
        anilist_favourites = (
            row.movie_anilist_favourites if is_movie else row.series_anilist_favourites
        )
        rottentomatoes_tomato_meter = (
            row.movie_rottentomatoes_tomato_meter
            if is_movie
            else row.series_rottentomatoes_tomato_meter
        )
        rottentomatoes_tomato_vote_count = (
            row.movie_rottentomatoes_tomato_vote_count
            if is_movie
            else row.series_rottentomatoes_tomato_vote_count
        )
        rottentomatoes_popcorn_meter = (
            row.movie_rottentomatoes_popcorn_meter
            if is_movie
            else row.series_rottentomatoes_popcorn_meter
        )
        rottentomatoes_popcorn_vote_count = (
            row.movie_rottentomatoes_popcorn_vote_count
            if is_movie
            else row.series_rottentomatoes_popcorn_vote_count
        )
        metacritic_metascore = (
            row.movie_metacritic_metascore
            if is_movie
            else row.series_metacritic_metascore
        )
        metacritic_vote_count = (
            row.movie_metacritic_vote_count
            if is_movie
            else row.series_metacritic_vote_count
        )
        metacritic_user_score = (
            row.movie_metacritic_user_score
            if is_movie
            else row.series_metacritic_user_score
        )
        metacritic_user_vote_count = (
            row.movie_metacritic_user_vote_count
            if is_movie
            else row.series_metacritic_user_vote_count
        )
        trakt_rating = row.movie_trakt_rating if is_movie else row.series_trakt_rating
        trakt_vote_count = (
            row.movie_trakt_vote_count if is_movie else row.series_trakt_vote_count
        )
        letterboxd_score = (
            row.movie_letterboxd_score if is_movie else row.series_letterboxd_score
        )
        letterboxd_vote_count = (
            row.movie_letterboxd_vote_count
            if is_movie
            else row.series_letterboxd_vote_count
        )
        external_ratings_source = (
            row.movie_external_ratings_source
            if is_movie
            else row.series_external_ratings_source
        )
        external_ratings_refreshed_at = (
            row.movie_external_ratings_refreshed_at
            if is_movie
            else row.series_external_ratings_refreshed_at
        )
        genres = extract_genre_names(
            row.movie_genres if is_movie else row.series_genres
        )
        popularity = row.movie_popularity if is_movie else row.series_popularity
        vote_average = row.movie_vote_average if is_movie else row.series_vote_average
        vote_count = row.movie_vote_count if is_movie else row.series_vote_count
        tmdb_status = row.movie_status if is_movie else row.series_status
        if is_movie:
            media_library_names = (
                [row.version_library_name]
                if row.version_library_name
                else movie_library_names_by_id.get(c.movie_id or -1)
            )
            media_added_at = (
                row.version_added_at
                if c.movie_version_id is not None
                else row.movie_added_at
            )
            media_arr_added_at = (
                row.version_arr_added_at
                if c.movie_version_id is not None
                else row.movie_arr_added_at
            )
            media_last_viewed_at = row.movie_last_viewed_at
            media_view_count = row.movie_view_count
        else:
            media_library_names = [
                ref.library_name
                for ref in series_library_refs_by_id.get(c.series_id or -1, [])
            ] or None
            if c.episode_id is not None:
                media_added_at = None
                media_arr_added_at = row.episode_arr_added_at
                media_last_viewed_at = row.episode_last_viewed_at
                media_view_count = row.episode_view_count
            elif c.season_id is not None:
                media_added_at = row.season_added_at
                media_arr_added_at = row.season_arr_added_at
                media_last_viewed_at = row.season_last_viewed_at
                media_view_count = row.season_view_count
            else:
                media_added_at = row.series_added_at
                media_arr_added_at = row.series_arr_added_at
                media_last_viewed_at = row.series_last_viewed_at
                media_view_count = row.series_view_count
        library_name_by_id = dict(global_library_name_by_id)
        if row.version_library_id and row.version_library_name:
            library_name_by_id[row.version_library_id] = row.version_library_name
        for ref in series_library_refs_by_id.get(c.series_id or -1, []):
            library_name_by_id[ref.library_id] = ref.library_name
        reason_parts = normalize_reason_parts(c.reason_data, library_name_by_id)

        has_pending = (
            (
                (c.movie_id in pending_movies_whole)
                or (
                    c.movie_id is not None
                    and c.movie_version_id is not None
                    and (c.movie_id, c.movie_version_id) in pending_movie_versions
                )
            )
            if is_movie
            else (
                c.series_id in pending_series
                or (
                    c.series_id is not None
                    and c.episode_id is None
                    and c.season_id is not None
                    and (c.series_id, c.season_id) in pending_seasons
                )
                or (
                    c.series_id is not None
                    and c.episode_id is not None
                    and (
                        (c.series_id, c.season_id or -1) in pending_seasons
                        or (c.series_id, c.episode_id) in pending_episodes
                    )
                )
            )
        )

        if media_id is None or media_title is None:
            continue

        estimated_space_bytes = (
            c.estimated_space_bytes
            if c.estimated_space_bytes is not None
            else row.version_size
            if row.version_size is not None
            else row.episode_size
            if row.episode_size is not None
            else row.season_size
            if row.season_size is not None
            else row.movie_size
            if is_movie and row.movie_size is not None
            else row.series_size
            if (not is_movie and row.series_size is not None)
            else None
        )

        items_out.append(
            CandidateEntry(
                id=c.id,
                media_type=c.media_type.value,
                media_id=media_id,
                media_title=media_title,
                media_year=media_year,
                tmdb_id=tmdb_id,
                tmdb_collection_id=tmdb_collection_id,
                tmdb_collection_name=tmdb_collection_name,
                tmdb_in_collection=tmdb_in_collection,
                imdb_id=imdb_id,
                imdb_rating=imdb_rating,
                imdb_vote_count=imdb_vote_count,
                anilist_id=anilist_id,
                anilist_score=anilist_score,
                anilist_popularity=anilist_popularity,
                anilist_favourites=anilist_favourites,
                rottentomatoes_tomato_meter=rottentomatoes_tomato_meter,
                rottentomatoes_tomato_vote_count=(rottentomatoes_tomato_vote_count),
                rottentomatoes_popcorn_meter=rottentomatoes_popcorn_meter,
                rottentomatoes_popcorn_vote_count=(rottentomatoes_popcorn_vote_count),
                metacritic_metascore=metacritic_metascore,
                metacritic_vote_count=metacritic_vote_count,
                metacritic_user_score=metacritic_user_score,
                metacritic_user_vote_count=metacritic_user_vote_count,
                trakt_rating=trakt_rating,
                trakt_vote_count=trakt_vote_count,
                letterboxd_score=letterboxd_score,
                letterboxd_vote_count=letterboxd_vote_count,
                external_ratings_source=external_ratings_source,
                external_ratings_refreshed_at=to_utc_isoformat(
                    external_ratings_refreshed_at
                ),
                poster_url=poster_url,
                genres=genres,
                popularity=popularity,
                vote_average=vote_average,
                vote_count=vote_count,
                tmdb_status=tmdb_status,
                media_library_names=media_library_names,
                media_added_at=to_utc_isoformat(media_added_at),
                media_arr_added_at=to_utc_isoformat(media_arr_added_at),
                media_last_viewed_at=to_utc_isoformat(media_last_viewed_at),
                media_view_count=media_view_count,
                movie_version_id=c.movie_version_id,
                version_service=row.version_service
                if row.version_service is not None
                else None,
                version_library_id=row.version_library_id,
                version_library_name=row.version_library_name,
                version_video_codec_family=row.version_video_codec_family,
                version_audio_codec_family=row.version_audio_codec_family,
                version_video_width=row.version_video_width,
                version_video_height=row.version_video_height,
                version_video_resolution=row.version_video_resolution,
                version_video_hdr=row.version_video_hdr,
                version_video_dolby_vision=row.version_video_dolby_vision,
                version_audio_channels=row.version_audio_channels,
                version_audio_languages=row.version_audio_languages,
                version_size=row.version_size,
                version_path=row.version_path,
                version_file_name=row.version_file_name,
                version_subtitle_languages=row.version_subtitle_languages,
                reason_parts=reason_parts,
                reason_tokens=reason_tokens(reason_parts),
                estimated_space_bytes=estimated_space_bytes,
                has_pending_request=has_pending,
                created_at=to_utc_isoformat(c.created_at) or "",
                auto_delete_delay_days=auto_delete_policy.delay_days,
                auto_delete_eligible_at=(
                    to_utc_isoformat(auto_delete_policy.eligible_at) or ""
                ),
                auto_delete_is_eligible=auto_delete_policy.is_eligible,
                auto_delete_is_active=auto_delete_is_active,
                season_id=c.season_id,
                season_number=row.season_number,
                series_title=row.series_title if c.season_id is not None else None,
                season_has_hdr=row.season_has_hdr if c.season_id is not None else None,
                season_has_dolby_vision=row.season_has_dolby_vision
                if c.season_id is not None
                else None,
                season_max_video_width=row.season_max_video_width
                if c.season_id is not None
                else None,
                season_max_video_height=row.season_max_video_height
                if c.season_id is not None
                else None,
                season_video_codec_families=row.season_video_codec_families
                if c.season_id is not None
                else None,
                season_audio_codec_families=row.season_audio_codec_families
                if c.season_id is not None
                else None,
                season_audio_languages=row.season_audio_languages
                if c.season_id is not None
                else None,
                season_subtitle_languages=row.season_subtitle_languages
                if c.season_id is not None
                else None,
                series_library_refs=series_library_refs_by_id.get(c.series_id or -1)
                if c.season_id is not None
                else None,
                episode_id=c.episode_id,
                episode_number=row.episode_number if c.episode_id is not None else None,
                episode_name=row.episode_name if c.episode_id is not None else None,
            )
        )

    total_pages = (total + per_page - 1) // per_page if total else 0
    return PaginatedCandidatesResponse(
        items=items_out,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.get("/candidates/presence", response_model=CandidatesPresenceResponse)
async def get_candidates_presence(
    _user: Annotated[User, Depends(require_page_access(PageAccess.CANDIDATES))],
    db: AsyncSession = Depends(get_db),
) -> CandidatesPresenceResponse:
    """Return whether any reclaim candidates currently exist."""
    result = await db.execute(select(ReclaimCandidate.id).limit(1))
    return CandidatesPresenceResponse(
        has_candidates=result.scalar_one_or_none() is not None
    )


@router.post("/candidates/delete", response_model=CandidateOperationQueuedResponse)
async def delete_candidates(
    request: DeleteCandidatesRequest,
    user: Annotated[User, Depends(get_current_user)],
    _db: AsyncSession = Depends(get_db),
) -> CandidateOperationQueuedResponse:
    """Deletes specific reclaim candidates, removing them from the media server.

    Requires admin or manage_reclaim permission. Uses same deletion priority as
    the automated task: Radarr/Sonarr first, then media server fallback.
    """
    if not (
        user.role is UserRole.ADMIN or has_permission(user, Permission.MANAGE_RECLAIM)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manage reclaim permission required",
        )

    if not request.candidate_ids:
        return CandidateOperationQueuedResponse(
            job_id=None,
            status="noop",
            message="No candidates selected",
        )

    item_labels, item_details, item_label_total = await _get_candidate_job_labels(
        _db, request.candidate_ids
    )
    job = await queue_candidate_file_op_job(
        operation=CandidateFileOpOperation.DELETE,
        candidate_ids=request.candidate_ids,
        requested_by_user_id=user.id,
        requested_by_username=user.username,
        item_labels=item_labels,
        item_label_total=item_label_total,
        item_details=item_details,
    )
    return CandidateOperationQueuedResponse(
        job_id=job.id,
        status="queued",
        message="Candidate delete queued",
    )


@router.post("/candidates/move", response_model=CandidateOperationQueuedResponse)
async def move_candidates(
    request: MoveCandidatesRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> CandidateOperationQueuedResponse:
    """Move specific reclaim candidates to the configured destination instead of deleting.

    Requires admin or manage_reclaim permission and move must be enabled in General Settings.
    """
    if not (
        user.role is UserRole.ADMIN or has_permission(user, Permission.MANAGE_RECLAIM)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manage reclaim permission required",
        )

    if not request.candidate_ids:
        return CandidateOperationQueuedResponse(
            job_id=None,
            status="noop",
            message="No candidates selected",
        )

    episode_scope_result = await db.execute(
        select(ReclaimCandidate.id).where(
            ReclaimCandidate.id.in_(request.candidate_ids),
            _episode_scope_clause(ReclaimCandidate),
        )
    )
    episode_scope_ids = [row[0] for row in episode_scope_result.all()]
    if episode_scope_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Episode candidates cannot be moved yet",
        )

    item_labels, item_details, item_label_total = await _get_candidate_job_labels(
        db, request.candidate_ids
    )
    job = await queue_candidate_file_op_job(
        operation=CandidateFileOpOperation.MOVE,
        candidate_ids=request.candidate_ids,
        requested_by_user_id=user.id,
        requested_by_username=user.username,
        item_labels=item_labels,
        item_label_total=item_label_total,
        item_details=item_details,
    )
    return CandidateOperationQueuedResponse(
        job_id=job.id,
        status="queued",
        message="Candidate move queued",
    )


@router.get("/reclaim-history", response_model=PaginatedReclaimHistoryResponse)
async def get_reclaim_history(
    _user: Annotated[User, Depends(require_page_access(PageAccess.HISTORY))],
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    media_type: MediaType | None = Query(None),
    search: str | None = Query(None, max_length=200),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
) -> PaginatedReclaimHistoryResponse:
    """Get paginated reclaim history records."""
    base = select(ReclaimHistory)

    if media_type is not None:
        base = base.where(ReclaimHistory.media_type == media_type)
    if search and search.strip():
        base = base.where(ReclaimHistory.name.ilike(f"%{search.strip()}%"))

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total: int = count_result.scalar_one()

    rows_result = await db.execute(
        base.order_by(
            ReclaimHistory.created_at.asc()
            if sort_order == "asc"
            else ReclaimHistory.created_at.desc()
        )
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rows = rows_result.scalars().all()

    items = [
        ReclaimHistoryEntry(
            id=row.id,
            approved_by=row.approved_by,
            media_type=row.media_type.value,
            tmdb_id=row.tmdb_id,
            name=row.name,
            size=row.size,
            attributes=ReclaimHistoryAttributes.model_validate(row.attributes)
            if row.attributes is not None
            else None,
            action=row.action or "deleted",
            destination_path=row.destination_path,
            created_at=to_utc_isoformat(row.created_at) or "",
        )
        for row in rows
    ]

    total_pages = (total + per_page - 1) // per_page if total else 0
    return PaginatedReclaimHistoryResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )
