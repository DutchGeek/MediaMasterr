from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.service_manager import service_manager
from backend.database.models import (
    FilesystemIndexEntry,
    MediaAsset,
    MediaIdentity,
    MediaIdentityExternalId,
    MediaIdentityProviderMapping,
    MediaIdentityTimelineEvent,
    MovieArrRef,
    MovieVersion,
    OperationHistory,
    Season,
    SeriesArrRef,
    SeriesServiceRef,
    SupplementalMediaMatch,
)
from backend.enums import MediaType, SeerrRequestStatus, Service
from backend.models.mie import (
    CorrelationTorrentState,
    MieCorrelationArrOwnershipRecord,
    MieCorrelationArtworkRecord,
    MieCorrelationExternalIds,
    MieCorrelationFileRecord,
    MieCorrelationHealthCategory,
    MieCorrelationHealthSummary,
    MieCorrelationIdentity,
    MieCorrelationRequestRecord,
    MieCorrelationTimelineEvent,
    MieCorrelationTorrentRecord,
)
from backend.services.mie.correlation_models import CorrelationBuildContext, utcnow


class CorrelationProvider(Protocol):
    async def contribute(
        self, db: AsyncSession, ctx: CorrelationBuildContext
    ) -> None: ...


def _normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _norm_path(value: str | None) -> str:
    raw = (value or "").strip().replace("\\", "/")
    return raw.rstrip("/").lower()


def _file_ext(path: str) -> str:
    ext = PurePosixPath(path).suffix.lower()
    return ext.lstrip(".")


def _try_iso(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _compute_torrent_state(
    *,
    raw_state: str | None,
    progress: float,
    has_torrent_link: bool,
    lifecycle_state: str | None,
) -> CorrelationTorrentState:
    state = _normalize_text(raw_state)
    lifecycle = _normalize_text(lifecycle_state)

    if not has_torrent_link and not state:
        return "missing"
    if "error" in state or "missingfiles" in state:
        return "failed"
    if "paused" in state:
        return "paused"
    if "stalled" in state and progress >= 1.0:
        return "seeding"
    if "upload" in state:
        return "seeding"
    if "meta" in state or "queued" in state or "check" in state:
        return "queued"
    if "down" in state and progress < 1.0:
        return "downloading"
    if progress >= 1.0 and lifecycle in {"import_pending", "indexed", "importing"}:
        return "import_pending"
    if progress >= 1.0 and lifecycle in {"imported", "resolved", "available"}:
        return "imported"
    if progress >= 1.0:
        return "completed"
    if has_torrent_link and not state:
        return "waiting"
    return "blocked"


@dataclass(slots=True)
class IdentityCorrelationProvider:
    async def contribute(self, db: AsyncSession, ctx: CorrelationBuildContext) -> None:
        subject = ctx.subject

        identity_stmt = select(MediaIdentity).where(
            MediaIdentity.media_type == subject.media_type,
            MediaIdentity.movie_id == subject.media_id
            if subject.media_type is MediaType.MOVIE
            else MediaIdentity.series_id == subject.media_id,
        )
        ctx.media_identity = (await db.execute(identity_stmt)).scalars().first()

        ids = MieCorrelationExternalIds(
            tmdb=(str(subject.tmdb_id) if subject.tmdb_id is not None else None),
            tvdb=subject.tvdb_id,
            imdb=subject.imdb_id,
            trakt=(
                str(subject.trakt_rating) if subject.trakt_rating is not None else None
            ),
            additional=(
                {"anilist": str(subject.anilist_id)}
                if subject.anilist_id is not None
                else {}
            ),
        )

        if ctx.media_identity is not None:
            external_rows = (
                (
                    await db.execute(
                        select(MediaIdentityExternalId).where(
                            MediaIdentityExternalId.media_identity_id
                            == ctx.media_identity.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in external_rows:
                id_type = _normalize_text(row.id_type)
                if id_type == "tmdb_id":
                    ids.tmdb = row.id_value
                elif id_type == "tvdb_id":
                    ids.tvdb = row.id_value
                elif id_type == "imdb_id":
                    ids.imdb = row.id_value
                elif id_type == "anidb_id":
                    ids.anidb = row.id_value
                elif id_type == "tvmaze_id":
                    ids.tvmaze = row.id_value
                elif id_type == "trakt_id":
                    ids.trakt = row.id_value
                else:
                    ids.additional[id_type] = row.id_value

        ctx.identity = MieCorrelationIdentity(
            media_identity_id=(ctx.media_identity.id if ctx.media_identity else None),
            canonical_title=(
                ctx.media_identity.canonical_title
                if ctx.media_identity and ctx.media_identity.canonical_title
                else subject.title
            ),
            canonical_ids=ids,
            media_type=subject.media_type,
            release_year=subject.year,
            canonical_provider=(
                ctx.media_identity.canonical_provider if ctx.media_identity else None
            ),
        )


@dataclass(slots=True)
class RequestCorrelationProvider:
    async def contribute(self, db: AsyncSession, ctx: CorrelationBuildContext) -> None:
        del db
        subject = ctx.subject
        requests: list[MieCorrelationRequestRecord] = []

        seerr = service_manager.seerr
        if seerr is not None and subject.tmdb_id is not None:
            try:
                source_requests = (
                    await seerr.get_movie_requests(subject.tmdb_id)
                    if subject.media_type is MediaType.MOVIE
                    else await seerr.get_tv_requests(subject.tmdb_id)
                )
            except Exception:
                source_requests = []

            for request in source_requests:
                raw = dict(request.raw or {})
                requested_by = request.requested_by_id
                approval_date = _try_iso(raw.get("modifiedAt"))
                if request.status is SeerrRequestStatus.PENDING:
                    approval_date = None
                requests.append(
                    MieCorrelationRequestRecord(
                        request_id=str(request.id),
                        request_status=request.status.name.lower(),
                        request_user=str(requested_by),
                        request_date=_try_iso(request.created_at),
                        approval_date=approval_date,
                        request_source="overseerr",
                    )
                )

        ctx.request_intelligence.requests = sorted(
            requests,
            key=lambda item: item.request_date or datetime.fromtimestamp(0, tz=UTC),
        )
        ctx.request_intelligence.request_state = "known" if requests else "unknown"


@dataclass(slots=True)
class ArrCorrelationProvider:
    async def contribute(self, db: AsyncSession, ctx: CorrelationBuildContext) -> None:
        subject = ctx.subject
        ownership: list[MieCorrelationArrOwnershipRecord] = []

        if subject.media_type is MediaType.MOVIE:
            movie_arr_rows = (
                (
                    await db.execute(
                        select(MovieArrRef).where(
                            MovieArrRef.movie_id == subject.media_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for movie_arr_ref in movie_arr_rows:
                ownership.append(
                    MieCorrelationArrOwnershipRecord(
                        provider=Service.RADARR.value,
                        internal_arr_id=str(movie_arr_ref.arr_movie_id),
                        root_folder=movie_arr_ref.arr_movie_path,
                        quality_profile=None,
                        tags=(ctx.subject.movie.arr_tags or [])
                        if ctx.subject.movie
                        else [],
                        monitored=(
                            ctx.subject.movie.is_monitored
                            if ctx.subject.movie
                            else None
                        ),
                        import_status=(
                            (ctx.media_asset.lifecycle_state or "unknown")
                            if ctx.media_asset
                            else "unknown"
                        ),
                    )
                )
        else:
            series_arr_rows = (
                (
                    await db.execute(
                        select(SeriesArrRef).where(
                            SeriesArrRef.series_id == subject.media_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for series_arr_ref in series_arr_rows:
                ownership.append(
                    MieCorrelationArrOwnershipRecord(
                        provider=Service.SONARR.value,
                        internal_arr_id=str(series_arr_ref.arr_series_id),
                        root_folder=series_arr_ref.arr_series_path,
                        quality_profile=None,
                        tags=(ctx.subject.series.arr_tags or [])
                        if ctx.subject.series
                        else [],
                        monitored=(
                            ctx.subject.series.is_monitored
                            if ctx.subject.series
                            else None
                        ),
                        import_status=(
                            (ctx.media_asset.lifecycle_state or "unknown")
                            if ctx.media_asset
                            else "unknown"
                        ),
                    )
                )

        ctx.arr_intelligence.ownership = ownership


@dataclass(slots=True)
class TorrentCorrelationProvider:
    async def contribute(self, db: AsyncSession, ctx: CorrelationBuildContext) -> None:
        subject = ctx.subject
        client = service_manager.qbittorrent
        if client is None:
            ctx.torrent_intelligence.torrents = []
            return

        try:
            torrents_raw = await client.get_torrents()
        except Exception:
            ctx.torrent_intelligence.torrents = []
            return

        known_paths: list[str] = []
        if subject.media_type is MediaType.MOVIE:
            version_rows = (
                await db.execute(
                    select(MovieVersion.path).where(
                        MovieVersion.movie_id == subject.media_id,
                        MovieVersion.path.is_not(None),
                    )
                )
            ).all()
            known_paths.extend(_norm_path(path) for (path,) in version_rows if path)
        else:
            episode_rows = (
                await db.execute(
                    select(Season.path).where(
                        Season.series_id == subject.media_id,
                        Season.path.is_not(None),
                    )
                )
            ).all()
            known_paths.extend(_norm_path(path) for (path,) in episode_rows if path)
            ref_rows = (
                await db.execute(
                    select(SeriesServiceRef.path).where(
                        SeriesServiceRef.series_id == subject.media_id,
                        SeriesServiceRef.path.is_not(None),
                    )
                )
            ).all()
            known_paths.extend(_norm_path(path) for (path,) in ref_rows if path)

        title_key = _normalize_text(subject.title)
        tmdb_key = str(subject.tmdb_id) if subject.tmdb_id is not None else ""
        imdb_key = _normalize_text(subject.imdb_id)
        tvdb_key = _normalize_text(subject.tvdb_id)

        correlated: list[MieCorrelationTorrentRecord] = []
        for item in torrents_raw:
            name = str(item.get("name") or "").strip() or "Unknown Torrent"
            name_key = _normalize_text(name)
            category = str(item.get("category") or "").strip() or None
            save_path = _norm_path(str(item.get("save_path") or ""))
            raw_state = str(item.get("state") or "").strip() or None
            progress = float(item.get("progress") or 0.0)

            has_match = False
            if title_key and title_key in name_key:
                has_match = True
            if tmdb_key and f"tmdb {tmdb_key}" in name_key:
                has_match = True
            if imdb_key and imdb_key in name_key:
                has_match = True
            if tvdb_key and tvdb_key in name_key:
                has_match = True
            if save_path and any(
                save_path.startswith(path) or path.startswith(save_path)
                for path in known_paths
            ):
                has_match = True

            if not has_match:
                continue

            computed_state = _compute_torrent_state(
                raw_state=raw_state,
                progress=progress,
                has_torrent_link=True,
                lifecycle_state=(
                    ctx.media_asset.lifecycle_state if ctx.media_asset else None
                ),
            )
            eta_raw = item.get("eta")
            eta_seconds: int | None = None
            if eta_raw is not None:
                try:
                    eta_seconds = int(eta_raw)
                except (TypeError, ValueError):
                    eta_seconds = None
            correlated.append(
                MieCorrelationTorrentRecord(
                    torrent_hash=(str(item.get("hash") or "").strip() or None),
                    torrent_name=name,
                    category=category,
                    download_client=Service.QBITTORRENT.value,
                    progress=progress,
                    download_speed=int(item.get("dlspeed") or 0),
                    upload_speed=int(item.get("upspeed") or 0),
                    eta_seconds=eta_seconds,
                    raw_state=raw_state,
                    computed_state=computed_state,
                )
            )

        correlated.sort(key=lambda row: row.torrent_name.lower())
        ctx.torrent_intelligence.torrents = correlated


@dataclass(slots=True)
class FileCorrelationProvider:
    async def contribute(self, db: AsyncSession, ctx: CorrelationBuildContext) -> None:
        subject = ctx.subject

        fs_rows_all = (await db.execute(select(FilesystemIndexEntry))).scalars().all()
        fs_rows: list[FilesystemIndexEntry] = []
        for row in fs_rows_all:
            metadata = row.metadata_json or {}
            if not isinstance(metadata, dict):
                continue
            marker_id = metadata.get("media_id")
            movie_id = metadata.get("movie_id")
            series_id = metadata.get("series_id")
            if marker_id == subject.media_id:
                fs_rows.append(row)
                continue
            if subject.media_type is MediaType.MOVIE and movie_id == subject.media_id:
                fs_rows.append(row)
                continue
            if subject.media_type is MediaType.SERIES and series_id == subject.media_id:
                fs_rows.append(row)

        media_files: list[MieCorrelationFileRecord] = []
        subtitles: list[MieCorrelationFileRecord] = []
        nfo_files: list[MieCorrelationFileRecord] = []
        artwork_files: list[MieCorrelationFileRecord] = []
        extras: list[MieCorrelationFileRecord] = []

        unique_paths: set[str] = set()
        duplicate_count = 0
        total_size = 0
        last_modified: datetime | None = None

        def classify(
            path: str, size_bytes: int, modified: datetime | None, entry_type: str
        ) -> None:
            nonlocal duplicate_count, total_size, last_modified
            normalized = _norm_path(path)
            if normalized in unique_paths:
                duplicate_count += 1
            else:
                unique_paths.add(normalized)

            total_size += max(0, size_bytes)
            if modified is not None and (
                last_modified is None or modified > last_modified
            ):
                last_modified = modified

            ext = _file_ext(path)
            file_type = entry_type or ext or "unknown"
            record = MieCorrelationFileRecord(
                path=path,
                file_type=file_type,
                size_bytes=size_bytes,
                last_modified=modified,
            )
            if ext in {"mkv", "mp4", "avi", "m4v", "ts", "wmv"}:
                media_files.append(record)
            elif ext in {"srt", "ass", "ssa", "sub", "vtt"}:
                subtitles.append(record)
            elif ext == "nfo":
                nfo_files.append(record)
            elif ext in {"jpg", "jpeg", "png", "webp"}:
                artwork_files.append(record)
            else:
                extras.append(record)

        for row in fs_rows:
            metadata = row.metadata_json or {}
            path = str(row.path or metadata.get("path") or "").strip()
            if not path:
                continue
            classify(
                path=path,
                size_bytes=int(row.size_bytes or 0),
                modified=row.modified_at,
                entry_type=str(row.entry_type or "").strip().lower(),
            )

        if subject.media_type is MediaType.MOVIE and not media_files:
            fallback_rows = (
                (
                    await db.execute(
                        select(MovieVersion).where(
                            MovieVersion.movie_id == subject.media_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for movie_version_row in fallback_rows:
                if movie_version_row.path:
                    classify(
                        path=movie_version_row.path,
                        size_bytes=int(movie_version_row.size or 0),
                        modified=movie_version_row.updated_at,
                        entry_type="movie_version",
                    )

        ctx.file_intelligence.media_files = media_files
        ctx.file_intelligence.subtitles = subtitles
        ctx.file_intelligence.nfo = nfo_files
        ctx.file_intelligence.artwork = artwork_files
        ctx.file_intelligence.extras = extras
        ctx.file_intelligence.missing_files = 1 if not media_files else 0
        ctx.file_intelligence.unexpected_files = sum(
            1 for row in extras if row.file_type in {"unknown", "tmp", "partial"}
        )
        ctx.file_intelligence.duplicate_files = duplicate_count
        ctx.file_intelligence.total_size_bytes = total_size
        ctx.file_intelligence.last_modified = last_modified


@dataclass(slots=True)
class ArtworkCorrelationProvider:
    async def contribute(self, db: AsyncSession, ctx: CorrelationBuildContext) -> None:
        subject = ctx.subject
        references: list[MieCorrelationArtworkRecord] = []
        seen: set[tuple[str, str, str]] = set()

        def add(source: str, artwork_type: str, url: str | None) -> None:
            if not url:
                return
            key = (source, artwork_type, url)
            if key in seen:
                return
            seen.add(key)
            references.append(
                MieCorrelationArtworkRecord(
                    source=source,
                    artwork_type=artwork_type,
                    url=url,
                )
            )

        if subject.movie is not None:
            add("tmdb", "poster", subject.movie.poster_url)
            add("tmdb", "background", subject.movie.backdrop_url)
        if subject.series is not None:
            add("tmdb", "poster", subject.series.poster_url)
            add("tmdb", "background", subject.series.backdrop_url)
        if ctx.media_asset is not None:
            add("identity", "poster", ctx.media_asset.poster_url)
            add("identity", "background", ctx.media_asset.backdrop_url)
            add("identity", "logo", ctx.media_asset.logo_url)
            add("identity", "banner", ctx.media_asset.banner_url)

        if ctx.media_identity is not None:
            provider_rows = (
                (
                    await db.execute(
                        select(MediaIdentityProviderMapping).where(
                            MediaIdentityProviderMapping.media_identity_id
                            == ctx.media_identity.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for provider_row in provider_rows:
                metadata = provider_row.metadata_json or {}
                source = provider_row.provider
                add(source, "poster", metadata.get("poster_url"))
                add(source, "background", metadata.get("backdrop_url"))
                add(source, "logo", metadata.get("logo_url"))
                add(source, "banner", metadata.get("banner_url"))
                add(source, "season", metadata.get("season_poster_url"))
                add(source, "collection", metadata.get("collection_poster_url"))

        supplemental_rows = (
            (
                await db.execute(
                    select(SupplementalMediaMatch).where(
                        SupplementalMediaMatch.media_type == subject.media_type,
                        SupplementalMediaMatch.movie_id == subject.media_id
                        if subject.media_type is MediaType.MOVIE
                        else SupplementalMediaMatch.series_id == subject.media_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for supplemental_row in supplemental_rows:
            signals = supplemental_row.signals or {}
            source = str(supplemental_row.source_service)
            add(
                source,
                "poster",
                signals.get("poster_url") or signals.get("artwork_poster"),
            )
            add(
                source,
                "background",
                signals.get("backdrop_url") or signals.get("artwork_backdrop"),
            )
            add(source, "logo", signals.get("logo_url") or signals.get("artwork_logo"))
            add(
                source,
                "banner",
                signals.get("banner_url") or signals.get("artwork_banner"),
            )

        # Optional Overseerr artwork, if present in raw payload.
        if service_manager.seerr is not None and subject.tmdb_id is not None:
            try:
                reqs = (
                    await service_manager.seerr.get_movie_requests(subject.tmdb_id)
                    if subject.media_type is MediaType.MOVIE
                    else await service_manager.seerr.get_tv_requests(subject.tmdb_id)
                )
            except Exception:
                reqs = []
            for req in reqs:
                raw = dict(req.raw or {})
                media = raw.get("media")
                if not isinstance(media, dict):
                    continue
                add("overseerr", "poster", media.get("posterPath"))
                add("overseerr", "background", media.get("backdropPath"))

        references.sort(key=lambda row: (row.artwork_type, row.source, row.url))
        ctx.artwork_intelligence.references = references


@dataclass(slots=True)
class TimelineCorrelationProvider:
    async def contribute(self, db: AsyncSession, ctx: CorrelationBuildContext) -> None:
        subject = ctx.subject
        events: list[MieCorrelationTimelineEvent] = []

        if ctx.request_intelligence.requests:
            for request in ctx.request_intelligence.requests:
                if request.request_date is not None:
                    events.append(
                        MieCorrelationTimelineEvent(
                            timestamp=_as_utc(request.request_date),
                            source=request.request_source,
                            event="requested",
                            confidence=95,
                        )
                    )
                if request.approval_date is not None:
                    events.append(
                        MieCorrelationTimelineEvent(
                            timestamp=_as_utc(request.approval_date),
                            source=request.request_source,
                            event="approved",
                            confidence=80,
                        )
                    )

        if subject.media_type is MediaType.MOVIE and subject.movie is not None:
            if subject.movie.arr_added_at is not None:
                events.append(
                    MieCorrelationTimelineEvent(
                        timestamp=_as_utc(subject.movie.arr_added_at),
                        source="arr",
                        event="added_to_arr",
                        confidence=95,
                    )
                )
            if subject.movie.added_at is not None:
                events.append(
                    MieCorrelationTimelineEvent(
                        timestamp=_as_utc(subject.movie.added_at),
                        source="library",
                        event="available",
                        confidence=95,
                    )
                )

        if subject.media_type is MediaType.SERIES and subject.series is not None:
            if subject.series.arr_added_at is not None:
                events.append(
                    MieCorrelationTimelineEvent(
                        timestamp=_as_utc(subject.series.arr_added_at),
                        source="arr",
                        event="added_to_arr",
                        confidence=95,
                    )
                )
            if subject.series.added_at is not None:
                events.append(
                    MieCorrelationTimelineEvent(
                        timestamp=_as_utc(subject.series.added_at),
                        source="library",
                        event="available",
                        confidence=95,
                    )
                )

        if ctx.torrent_intelligence.torrents:
            now = utcnow()
            for torrent in ctx.torrent_intelligence.torrents:
                event_name = (
                    "torrent_started"
                    if torrent.computed_state in {"downloading", "queued", "waiting"}
                    else "download_complete"
                    if torrent.computed_state
                    in {"completed", "seeding", "import_pending", "imported"}
                    else "torrent_state_updated"
                )
                events.append(
                    MieCorrelationTimelineEvent(
                        timestamp=now,
                        source=torrent.download_client,
                        event=event_name,
                        confidence=60,
                    )
                )

        if ctx.media_identity is not None:
            timeline_rows = (
                (
                    await db.execute(
                        select(MediaIdentityTimelineEvent).where(
                            MediaIdentityTimelineEvent.media_identity_id
                            == ctx.media_identity.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for timeline_row in timeline_rows:
                events.append(
                    MieCorrelationTimelineEvent(
                        timestamp=_as_utc(timeline_row.happened_at),
                        source=timeline_row.source,
                        event=timeline_row.event_type,
                        confidence=85,
                    )
                )

        operation_rows = (
            (
                await db.execute(
                    select(OperationHistory)
                    .where(
                        OperationHistory.target_type == subject.media_type.value,
                        OperationHistory.target_id == str(subject.media_id),
                    )
                    .order_by(OperationHistory.created_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        for operation_row in operation_rows:
            events.append(
                MieCorrelationTimelineEvent(
                    timestamp=_as_utc(operation_row.created_at),
                    source="operations",
                    event=operation_row.action,
                    confidence=75,
                )
            )

        if ctx.media_asset is not None:
            events.append(
                MieCorrelationTimelineEvent(
                    timestamp=_as_utc(ctx.media_asset.updated_at),
                    source="identity",
                    event="metadata_updated",
                    confidence=80,
                )
            )

        events.sort(key=lambda item: item.timestamp)
        ctx.timeline = events


@dataclass(slots=True)
class HealthCorrelationProvider:
    async def contribute(self, db: AsyncSession, ctx: CorrelationBuildContext) -> None:
        del db
        categories: list[MieCorrelationHealthCategory] = []

        def add(
            key: str,
            ok: bool,
            reasons: list[str],
            score_good: int = 100,
            score_bad: int = 40,
        ) -> None:
            categories.append(
                MieCorrelationHealthCategory(
                    key=key,
                    status=("good" if ok else "risk"),
                    score=(score_good if ok else score_bad),
                    reasons=([] if ok else reasons),
                )
            )

        add(
            "identity",
            ctx.identity is not None and (ctx.identity.media_identity_id is not None),
            ["No canonical media identity row found"],
        )

        add(
            "metadata",
            bool(ctx.identity and ctx.identity.canonical_title),
            ["Canonical title is missing"],
        )

        has_artwork = len(ctx.artwork_intelligence.references) > 0
        add(
            "artwork",
            has_artwork,
            ["No artwork references were correlated"],
            100,
            45,
        )

        has_torrents = len(ctx.torrent_intelligence.torrents) > 0
        add(
            "torrent",
            has_torrents
            or not (ctx.media_asset.has_torrent if ctx.media_asset else False),
            ["Asset expects torrents but no correlated torrent was found"],
            90,
            35,
        )

        import_ok = not (
            ctx.media_asset
            and _normalize_text(ctx.media_asset.lifecycle_state)
            in {"import_pending", "failed"}
        )
        add(
            "import",
            import_ok,
            ["Import is pending or failed"],
            90,
            30,
        )

        add(
            "files",
            ctx.file_intelligence.missing_files == 0,
            ["No media files were correlated"],
            100,
            30,
        )

        add(
            "providers",
            len(ctx.arr_intelligence.ownership) > 0
            or len(ctx.request_intelligence.requests) > 0,
            ["No provider ownership or request signals were correlated"],
            85,
            50,
        )

        add(
            "timeline",
            len(ctx.timeline) > 0,
            ["No timeline events available"],
            90,
            45,
        )

        overall = round(
            sum(item.score for item in categories) / max(1, len(categories))
        )
        ctx.health = MieCorrelationHealthSummary(
            categories=categories,
            overall_health_score=max(0, min(100, overall)),
        )


@dataclass(slots=True)
class CorrelationEngine:
    providers: tuple[CorrelationProvider, ...] = (
        IdentityCorrelationProvider(),
        RequestCorrelationProvider(),
        ArrCorrelationProvider(),
        TorrentCorrelationProvider(),
        FileCorrelationProvider(),
        ArtworkCorrelationProvider(),
        TimelineCorrelationProvider(),
        HealthCorrelationProvider(),
    )

    async def run(
        self, db: AsyncSession, ctx: CorrelationBuildContext
    ) -> CorrelationBuildContext:
        for provider in self.providers:
            await provider.contribute(db, ctx)
        if ctx.identity is None:
            ctx.identity = ctx.fallback_identity()
        if ctx.health is None:
            ctx.health = MieCorrelationHealthSummary(
                categories=[], overall_health_score=0
            )
        return ctx
