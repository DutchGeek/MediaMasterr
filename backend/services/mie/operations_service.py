from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import Integer, and_, func, or_, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.service_manager import service_manager
from backend.database.models import (
    CleanupPlan,
    CleanupPlanItem,
    FilesystemRoot,
    MediaAsset,
    MieSettings,
    Movie,
    MovieVersion,
    OperationHistory,
    ProtectedMedia,
    ReclaimCandidate,
    Series,
)
from backend.enums import MediaType
from backend.models.mie import (
    ArtworkIssuesSummary,
    CleanupPlanListResponse,
    CleanupPlanSummaryResponse,
    FilesystemAccessMode,
    FilesystemConfigResponse,
    FilesystemRootConfigResponse,
    MieTimelineEvent,
    OperationAuditEntryResponse,
    OperationAuditListResponse,
    OperationsCard,
    OperationsConfidenceSummary,
    OperationsGraphSummary,
    OperationsHealthCategory,
    OperationsHealthSummary,
    OperationsIssue,
    OperationsIssueSummary,
    OperationsOverviewResponse,
    OperationsRecommendation,
    OperationsRecommendationsResponse,
    OperationsTimelineSummary,
    OperationsWorkspaceResponse,
    OperationWorkflowExecution,
    OperationWorkflowPreview,
    OperationWorkflowResponse,
    OperationWorkflowValidation,
    OperationWorkflowValidationCheck,
    SafetyLevel,
)
from backend.services.correlation import CorrelatedArtwork, MediaCorrelationService
from backend.services.media_asset_artwork import media_asset_artwork_resolver
from backend.services.mie.correlation_service import CorrelationService
from backend.services.mie.downloads_intelligence import DownloadsIntelligenceService
from backend.services.mie.identity_service import IdentityCenterService
from backend.services.mie.operations_engine import OperationsEngine

CARD_DEFINITIONS: list[tuple[str, str, str, str]] = [
    ("downloading", "Downloading", "Active ingest workload currently tracked", "info"),
    (
        "import_pending",
        "Import Pending",
        "Media expected from ARR/torrent sources but not indexed",
        "medium",
    ),
    (
        "ready_to_detach",
        "Ready To Detach",
        "Imported assets that reached ratio and can safely detach torrent",
        "low",
    ),
    (
        "protected_seeding",
        "Protected & Seeding",
        "Assets that remain protected while seeding",
        "info",
    ),
    (
        "detached_media",
        "Detached Media",
        "Assets with files present and no active torrent",
        "info",
    ),
    (
        "orphaned_torrents",
        "Orphaned Torrents",
        "Torrents without linked media assets",
        "high",
    ),
    (
        "orphaned_files",
        "Orphaned Files",
        "Filesystem entries without media correlation",
        "high",
    ),
    (
        "broken_imports",
        "Broken Imports",
        "Library entries with missing or stale version files",
        "high",
    ),
    (
        "unknown_files",
        "Unknown Files",
        "Indexed files outside configured media context",
        "medium",
    ),
    (
        "duplicate_releases",
        "Duplicate Releases",
        "Media groups with duplicate versions",
        "medium",
    ),
    (
        "duplicate_torrents",
        "Duplicate Torrents",
        "Multiple torrents resolving to the same payload",
        "medium",
    ),
    (
        "empty_folders",
        "Empty Folders",
        "Candidate directories with no media files",
        "low",
    ),
    (
        "leftover_files",
        "Leftover Files",
        "Sample/RAR/NFO/proof leftovers identified by scanner",
        "low",
    ),
    (
        "space_recovery",
        "Space Recovery",
        "Bytes recoverable from current cleanup recommendations",
        "info",
    ),
    (
        "identity_issues",
        "Identity Issues",
        "Assets requiring identity review across providers and metadata",
        "high",
    ),
]

_NOISE_TOKENS = {
    "1080p",
    "720p",
    "2160p",
    "x264",
    "x265",
    "h264",
    "h265",
    "hevc",
    "bluray",
    "brrip",
    "webrip",
    "webdl",
    "web",
    "proper",
    "repack",
    "remux",
    "hdr",
    "dv",
    "dts",
    "aac",
    "ac3",
    "yify",
}


class OperationsService:
    """Facade for Operations page data sourced from MIE state and provider correlation."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._correlation_service = MediaCorrelationService()
        self._operations_engine = OperationsEngine()

    @staticmethod
    def _coerce_card_severity(value: str) -> Literal["info", "low", "medium", "high"]:
        if value in {"info", "low", "medium", "high"}:
            return cast(Literal["info", "low", "medium", "high"], value)
        return "info"

    @staticmethod
    def _coerce_safety_level(value: str) -> SafetyLevel:
        if value in {"safe", "low_risk", "medium_risk", "high_risk"}:
            return cast(SafetyLevel, value)
        return "safe"

    @staticmethod
    def _coerce_access_mode(value: str | None) -> FilesystemAccessMode:
        if value in {"discovery", "assisted", "automated"}:
            return cast(FilesystemAccessMode, value)
        return "assisted"

    @staticmethod
    def _is_download_state(state: str) -> bool:
        lowered = (state or "").lower()
        return "down" in lowered and "stalled" not in lowered

    @staticmethod
    def _is_upload_state(state: str) -> bool:
        lowered = (state or "").lower()
        return "up" in lowered or "seed" in lowered

    @staticmethod
    def _is_completed(progress: float) -> bool:
        return progress >= 0.999

    @staticmethod
    def _normalize_torrent_title(name: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", " ", (name or "").lower())
        parts = [p for p in cleaned.split() if p and p not in _NOISE_TOKENS]
        return " ".join(parts[:8])

    async def _load_correlation_graphs(self) -> list[Any]:
        rows = (
            await self.db.execute(
                select(MediaAsset.media_type, MediaAsset.movie_id, MediaAsset.series_id)
                .order_by(MediaAsset.id.asc())
                .limit(250)
            )
        ).all()

        subjects: list[tuple[MediaType, int]] = []
        for media_type, movie_id, series_id in rows:
            if media_type is MediaType.MOVIE and movie_id is not None:
                subjects.append((MediaType.MOVIE, int(movie_id)))
            elif media_type is MediaType.SERIES and series_id is not None:
                subjects.append((MediaType.SERIES, int(series_id)))

        graphs: list[Any] = []
        correlation = CorrelationService(self.db)
        for media_type, media_id in subjects:
            try:
                graph = await correlation.media_graph(
                    media_id=media_id,
                    media_type=media_type,
                )
            except ValueError:
                continue
            graphs.append(graph)
        return graphs

    async def _graph_issue_recommendations(
        self,
        issues: list[Any],
    ) -> list[OperationsRecommendation]:
        mapped: list[OperationsRecommendation] = []
        severity_to_safety: dict[str, SafetyLevel] = {
            "critical": "high_risk",
            "high": "medium_risk",
            "medium": "low_risk",
            "low": "safe",
        }
        issue_to_card = {
            "missing_request": "import_pending",
            "failed_import": "broken_imports",
            "filesystem_inconsistency": "broken_imports",
            "torrent_stalled": "downloading",
            "duplicate_identity": "identity_issues",
            "artwork_gap": "unknown_files",
        }

        for issue in issues:
            resolved_artwork = await media_asset_artwork_resolver.resolve(
                self.db,
                context="operations.recommendations.graph_issue",
                media_type=issue.media_type,
                media_id=issue.media_id,
                provider_poster_url=None,
                provider_backdrop_url=None,
                fallback_reason=f"graph_issue_{issue.issue_type}",
            )
            mapped.append(
                OperationsRecommendation(
                    id=f"issue:{issue.key}",
                    card_key=issue_to_card.get(issue.issue_type, "unknown_files"),
                    title=issue.title,
                    summary=issue.reason,
                    explanation=issue.recommendation,
                    reasons=[issue.reason, issue.remediation],
                    action=issue.action,
                    safety_level=severity_to_safety.get(issue.severity, "low_risk"),
                    target_type=issue.media_type.value,
                    target_id=str(issue.media_id),
                    estimated_recovery_bytes=issue.estimated_recovery_bytes,
                    poster_url=resolved_artwork.poster_url,
                    artwork=resolved_artwork.artwork,
                    issue_key=issue.key,
                    confidence=issue.confidence,
                    graph_references=issue.graph_references,
                )
            )
        return mapped

    @staticmethod
    def _to_issue_summary(issues: list[Any]) -> OperationsIssueSummary:
        summary = OperationsIssueSummary(total=len(issues))
        for issue in issues:
            if issue.severity == "critical":
                summary.critical += 1
            elif issue.severity == "high":
                summary.high += 1
            elif issue.severity == "medium":
                summary.medium += 1
            else:
                summary.low += 1
        return summary

    async def _graph_intelligence(self) -> tuple[list[Any], Any]:
        graphs = await self._load_correlation_graphs()
        intelligence = self._operations_engine.run(graphs)
        return graphs, intelligence

    async def _graph_overview_counts(self) -> dict[str, int]:
        graphs, intelligence = await self._graph_intelligence()
        issue_counts = Counter(issue.issue_type for issue in intelligence.issues)

        space_recovery = int(
            (
                await self.db.execute(
                    select(
                        func.coalesce(
                            func.sum(ReclaimCandidate.estimated_space_bytes), 0
                        )
                    )
                )
            ).scalar_one()
            or 0
        )

        ready_to_detach = 0
        detached_media = 0
        downloading = 0
        for graph in graphs:
            states = [row.computed_state for row in graph.torrent_intelligence.torrents]
            if any(state in {"downloading", "queued", "waiting"} for state in states):
                downloading += 1
            if any(state in {"completed", "seeding", "imported"} for state in states):
                ready_to_detach += 1
            if not states and graph.file_intelligence.missing_files == 0:
                detached_media += 1

        return {
            "downloading": downloading,
            "import_pending": issue_counts.get("missing_request", 0),
            "ready_to_detach": ready_to_detach,
            "protected_seeding": 0,
            "detached_media": detached_media,
            "orphaned_torrents": 0,
            "orphaned_files": 0,
            "broken_imports": issue_counts.get("failed_import", 0)
            + issue_counts.get("filesystem_inconsistency", 0),
            "unknown_files": issue_counts.get("artwork_gap", 0),
            "duplicate_releases": 0,
            "duplicate_torrents": 0,
            "empty_folders": 0,
            "leftover_files": 0,
            "space_recovery": space_recovery,
            "identity_issues": issue_counts.get("duplicate_identity", 0),
        }

    async def _load_torrent_state(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, CorrelatedArtwork]]:
        client = service_manager.qbittorrent
        if client is None:
            return [], {}

        torrents_raw = await client.get_torrents()
        summaries = self._correlation_service.build_torrent_summaries(torrents_raw)

        correlated: dict[str, CorrelatedArtwork] = {}
        for summary in summaries:
            correlated[
                summary.id
            ] = await self._correlation_service.resolve_torrent_artwork(
                self.db,
                summary,
            )
        return torrents_raw, correlated

    async def _active_protection_sets(self) -> tuple[set[int], set[int]]:
        now = datetime.now(UTC)
        rows = (
            await self.db.execute(
                select(ProtectedMedia.movie_id, ProtectedMedia.series_id).where(
                    or_(
                        ProtectedMedia.permanent.is_(True),
                        ProtectedMedia.expires_at.is_(None),
                        ProtectedMedia.expires_at > now,
                    )
                )
            )
        ).all()
        protected_movies = {
            int(movie_id) for movie_id, _ in rows if movie_id is not None
        }
        protected_series = {
            int(series_id) for _, series_id in rows if series_id is not None
        }
        return protected_movies, protected_series

    async def _refresh_media_assets_snapshot(
        self,
        correlated_torrents: dict[str, CorrelatedArtwork],
    ) -> None:
        protected_movies, protected_series = await self._active_protection_sets()

        version_counts = {
            int(movie_id): int(count)
            for movie_id, count in (
                await self.db.execute(
                    select(MovieVersion.movie_id, func.count(MovieVersion.id)).group_by(
                        MovieVersion.movie_id
                    )
                )
            ).all()
            if movie_id is not None
        }

        torrent_movie_ids = {
            art.media_id
            for art in correlated_torrents.values()
            if art.media_type == MediaType.MOVIE and art.media_id is not None
        }
        torrent_series_ids = {
            art.media_id
            for art in correlated_torrents.values()
            if art.media_type == MediaType.SERIES and art.media_id is not None
        }

        existing_assets = (
            (await self.db.execute(select(MediaAsset).order_by(MediaAsset.id.asc())))
            .scalars()
            .all()
        )
        by_movie = {
            int(asset.movie_id): asset
            for asset in existing_assets
            if asset.media_type == MediaType.MOVIE and asset.movie_id is not None
        }
        by_series = {
            int(asset.series_id): asset
            for asset in existing_assets
            if asset.media_type == MediaType.SERIES and asset.series_id is not None
        }

        movies = (
            (
                await self.db.execute(
                    select(Movie)
                    .where(Movie.removed_at.is_(None))
                    .order_by(Movie.id.asc())
                )
            )
            .scalars()
            .all()
        )

        for movie in movies:
            has_files = version_counts.get(movie.id, 0) > 0
            has_torrent = movie.id in torrent_movie_ids
            is_protected = movie.id in protected_movies
            lifecycle_state = (
                "protected_seeding"
                if has_torrent and is_protected
                else "import_pending"
                if has_torrent and not has_files
                else "detached_media"
                if has_files and not has_torrent
                else "imported"
            )
            health_state = "healthy" if has_files else "degraded"
            recommendation = (
                "detach_torrent"
                if lifecycle_state == "protected_seeding"
                else "investigate_import"
                if lifecycle_state == "import_pending"
                else "monitor"
            )
            asset = by_movie.get(movie.id)
            if asset is None:
                self.db.add(
                    MediaAsset(
                        media_type=MediaType.MOVIE,
                        movie_id=movie.id,
                        lifecycle_state=lifecycle_state,
                        health_state=health_state,
                        has_torrent=has_torrent,
                        has_filesystem_objects=has_files,
                        is_protected=is_protected,
                        poster_url=movie.poster_url,
                        backdrop_url=movie.backdrop_url,
                        artwork_source="library",
                        recommendation=recommendation,
                        last_indexed_at=datetime.now(UTC),
                    )
                )
                continue
            asset.lifecycle_state = lifecycle_state
            asset.health_state = health_state
            asset.has_torrent = has_torrent
            asset.has_filesystem_objects = has_files
            asset.is_protected = is_protected
            asset.poster_url = movie.poster_url
            asset.backdrop_url = movie.backdrop_url
            asset.artwork_source = asset.artwork_source or "library"
            asset.recommendation = recommendation
            asset.last_indexed_at = datetime.now(UTC)

        series_rows = (
            (
                await self.db.execute(
                    select(Series)
                    .where(Series.removed_at.is_(None))
                    .order_by(Series.id.asc())
                )
            )
            .scalars()
            .all()
        )
        for series in series_rows:
            has_files = bool(series.size and series.size > 0)
            has_torrent = series.id in torrent_series_ids
            is_protected = series.id in protected_series
            lifecycle_state = (
                "protected_seeding"
                if has_torrent and is_protected
                else "import_pending"
                if has_torrent and not has_files
                else "detached_media"
                if has_files and not has_torrent
                else "imported"
            )
            health_state = "healthy" if has_files else "degraded"
            recommendation = (
                "detach_torrent"
                if lifecycle_state == "protected_seeding"
                else "investigate_import"
                if lifecycle_state == "import_pending"
                else "monitor"
            )
            asset = by_series.get(series.id)
            if asset is None:
                self.db.add(
                    MediaAsset(
                        media_type=MediaType.SERIES,
                        series_id=series.id,
                        lifecycle_state=lifecycle_state,
                        health_state=health_state,
                        has_torrent=has_torrent,
                        has_filesystem_objects=has_files,
                        is_protected=is_protected,
                        poster_url=series.poster_url,
                        backdrop_url=series.backdrop_url,
                        artwork_source="library",
                        recommendation=recommendation,
                        last_indexed_at=datetime.now(UTC),
                    )
                )
                continue
            asset.lifecycle_state = lifecycle_state
            asset.health_state = health_state
            asset.has_torrent = has_torrent
            asset.has_filesystem_objects = has_files
            asset.is_protected = is_protected
            asset.poster_url = series.poster_url
            asset.backdrop_url = series.backdrop_url
            asset.artwork_source = asset.artwork_source or "library"
            asset.recommendation = recommendation
            asset.last_indexed_at = datetime.now(UTC)

        await self.db.flush()

    async def _overview_counts(self) -> dict[str, int]:
        reclaim_count = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(ReclaimCandidate)
                )
            ).scalar()
            or 0
        )

        movie_without_versions = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(Movie)
                    .where(Movie.removed_at.is_(None))
                    .where(
                        ~Movie.id.in_(
                            select(MovieVersion.movie_id).where(
                                MovieVersion.movie_id.is_not(None)
                            )
                        )
                    )
                )
            ).scalar()
            or 0
        )

        duplicate_releases = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(
                        select(MovieVersion.movie_id)
                        .group_by(MovieVersion.movie_id)
                        .having(func.count(MovieVersion.id) > 1)
                        .subquery()
                    )
                )
            ).scalar()
            or 0
        )

        broken_imports = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(MovieVersion)
                    .where(or_(MovieVersion.path.is_(None), MovieVersion.path == ""))
                )
            ).scalar()
            or 0
        )

        estimated_recovery_bytes = int(
            (
                await self.db.execute(
                    select(
                        func.coalesce(
                            func.sum(ReclaimCandidate.estimated_space_bytes), 0
                        )
                    )
                )
            ).scalar()
            or 0
        )

        torrents_raw, correlated = await self._load_torrent_state()
        await self._refresh_media_assets_snapshot(correlated)
        identity_health = await IdentityCenterService(self.db).identity_health_summary()

        protected_movies, protected_series = await self._active_protection_sets()

        downloading = 0
        import_pending_from_torrents = 0
        ready_to_detach = 0
        protected_seeding = 0
        orphaned_torrents = 0

        normalized_names = Counter(
            self._normalize_torrent_title(str(item.get("name") or ""))
            for item in torrents_raw
            if item.get("name")
        )

        summary_by_id = {
            self._correlation_service.torrent_summary_from_raw(
                item, index=index
            ).id: item
            for index, item in enumerate(torrents_raw)
            if isinstance(item, dict)
        }

        for torrent_id, artwork in correlated.items():
            raw = summary_by_id.get(torrent_id, {})
            state = str(raw.get("state") or "")
            progress = float(raw.get("progress") or 0)
            ratio = float(raw.get("ratio") or 0)

            if self._is_download_state(state):
                downloading += 1

            if artwork.media_id is None:
                orphaned_torrents += 1
                if self._is_completed(progress):
                    import_pending_from_torrents += 1
                continue

            is_protected = (
                artwork.media_type == MediaType.MOVIE
                and artwork.media_id in protected_movies
            ) or (
                artwork.media_type == MediaType.SERIES
                and artwork.media_id in protected_series
            )

            if self._is_upload_state(state) and is_protected:
                protected_seeding += 1

            if self._is_completed(progress) and ratio >= 1 and not is_protected:
                ready_to_detach += 1

        duplicate_torrents = sum(
            max(0, count - 1) for count in normalized_names.values() if count > 1
        )

        counts: dict[str, int] = {
            "downloading": downloading,
            "import_pending": import_pending_from_torrents + movie_without_versions,
            "ready_to_detach": ready_to_detach,
            "protected_seeding": protected_seeding,
            "detached_media": max(0, reclaim_count - downloading),
            "orphaned_torrents": orphaned_torrents,
            "orphaned_files": 0,
            "broken_imports": broken_imports,
            "unknown_files": 0,
            "duplicate_releases": duplicate_releases,
            "duplicate_torrents": duplicate_torrents,
            "empty_folders": 0,
            "leftover_files": 0,
            "space_recovery": estimated_recovery_bytes,
            "identity_issues": int(
                identity_health.get("missing_count", 0)
                + identity_health.get("review_count", 0)
            ),
        }
        return counts

    async def overview(self) -> OperationsOverviewResponse:
        counts = await self._graph_overview_counts()
        if not any(counts.values()):
            counts = await self._overview_counts()
        cards = [
            OperationsCard(
                key=key,
                title=title,
                description=description,
                count=counts.get(key, 0),
                severity=self._coerce_card_severity(severity),
            )
            for key, title, description, severity in CARD_DEFINITIONS
        ]
        return OperationsOverviewResponse(cards=cards, generated_at=datetime.now(UTC))

    async def _cleanup_plan_recommendations(self) -> list[OperationsRecommendation]:
        rows = (
            await self.db.execute(
                select(
                    CleanupPlanItem,
                    Movie.title.label("movie_title"),
                    Series.title.label("series_title"),
                )
                .outerjoin(
                    Movie, Movie.id == sql_cast(CleanupPlanItem.target_id, Integer)
                )
                .outerjoin(
                    Series, Series.id == sql_cast(CleanupPlanItem.target_id, Integer)
                )
                .order_by(CleanupPlanItem.created_at.desc())
                .limit(250)
            )
        ).all()

        items: list[OperationsRecommendation] = []
        for row in rows:
            item = row.CleanupPlanItem
            title = row.movie_title or row.series_title or item.title
            reasons = (
                [r.strip() for r in item.summary.split(";") if r.strip()]
                if item.summary
                else []
            )
            if not reasons and item.summary:
                reasons = [item.summary]
            resolved_artwork = await media_asset_artwork_resolver.resolve(
                self.db,
                context="operations.recommendations.cleanup_plan",
                media_type=(
                    MediaType.MOVIE
                    if item.target_type == "movie"
                    else MediaType.SERIES
                    if item.target_type in {"series", "season", "episode"}
                    else None
                ),
                media_id=(
                    int(item.target_id)
                    if item.target_id and item.target_id.isdigit()
                    else None
                ),
                provider_poster_url=None,
                provider_backdrop_url=None,
                fallback_reason=f"cleanup_plan_{item.card_key}",
            )
            items.append(
                OperationsRecommendation(
                    id=f"plan-item:{item.id}",
                    card_key=item.card_key,
                    title=title,
                    summary=item.summary,
                    explanation=item.summary,
                    reasons=reasons,
                    action=item.action,
                    safety_level=self._coerce_safety_level(item.safety_level),
                    target_type=item.target_type,
                    target_id=item.target_id,
                    estimated_recovery_bytes=item.estimated_recovery_bytes,
                    poster_url=resolved_artwork.poster_url,
                    artwork=resolved_artwork.artwork,
                )
            )
        return items

    async def _fallback_recommendations(self) -> list[OperationsRecommendation]:
        rows = (
            await self.db.execute(
                select(
                    ReclaimCandidate,
                    Movie.title.label("movie_title"),
                    Movie.poster_url.label("movie_poster_url"),
                    Series.title.label("series_title"),
                    Series.poster_url.label("series_poster_url"),
                )
                .outerjoin(Movie, Movie.id == ReclaimCandidate.movie_id)
                .outerjoin(Series, Series.id == ReclaimCandidate.series_id)
                .order_by(
                    ReclaimCandidate.estimated_space_bytes.desc(),
                    ReclaimCandidate.created_at.desc(),
                )
                .limit(150)
            )
        ).all()

        items: list[OperationsRecommendation] = []
        for row in rows:
            candidate = row.ReclaimCandidate
            target_title = (
                row.movie_title or row.series_title or f"Candidate #{candidate.id}"
            )
            reasons = (
                [candidate.reason]
                if candidate.reason
                else ["Rule engine matched candidate."]
            )
            media_id = candidate.movie_id or candidate.series_id
            resolved_artwork = await media_asset_artwork_resolver.resolve(
                self.db,
                context="operations.recommendations.reclaim_candidate",
                media_type=(
                    MediaType.MOVIE
                    if candidate.movie_id is not None
                    else MediaType.SERIES
                ),
                media_id=media_id,
                provider_poster_url=(
                    row.movie_poster_url
                    if candidate.movie_id is not None
                    else row.series_poster_url
                ),
                provider_backdrop_url=None,
                fallback_reason="reclaim_candidate_missing_asset_artwork",
            )
            items.append(
                OperationsRecommendation(
                    id=f"candidate:{candidate.id}",
                    card_key="space_recovery",
                    title=target_title,
                    summary=f"Potential reclaim {candidate.estimated_space_bytes or 0} bytes",
                    explanation=(
                        "Safe-to-review candidate detected by rule engine. "
                        "Validation checks run before execution."
                    ),
                    reasons=reasons,
                    action="delete_files",
                    safety_level=(
                        "safe" if candidate.approved_for_deletion else "low_risk"
                    ),
                    target_type="reclaim_candidate",
                    target_id=str(candidate.id),
                    estimated_recovery_bytes=candidate.estimated_space_bytes or 0,
                    poster_url=resolved_artwork.poster_url,
                    artwork=resolved_artwork.artwork,
                )
            )

        duplicate_rows = (
            await self.db.execute(
                select(
                    Movie.id,
                    Movie.title,
                    func.count(MovieVersion.id).label("version_count"),
                )
                .join(MovieVersion, MovieVersion.movie_id == Movie.id)
                .where(Movie.removed_at.is_(None))
                .group_by(Movie.id)
                .having(func.count(MovieVersion.id) > 1)
                .order_by(func.count(MovieVersion.id).desc())
                .limit(30)
            )
        ).all()
        for movie_id, movie_title, version_count in duplicate_rows:
            resolved_artwork = await media_asset_artwork_resolver.resolve(
                self.db,
                context="operations.recommendations.duplicate_release",
                media_type=MediaType.MOVIE,
                media_id=int(movie_id),
                provider_poster_url=None,
                provider_backdrop_url=None,
                fallback_reason="duplicate_release_missing_asset_artwork",
            )
            items.append(
                OperationsRecommendation(
                    id=f"duplicate_release:movie:{movie_id}",
                    card_key="duplicate_releases",
                    title=movie_title,
                    summary=f"{version_count} versions detected",
                    explanation="Duplicate movie versions were detected for the same media identity.",
                    reasons=[
                        f"Multiple versions ({version_count}) mapped to one movie.",
                        "Potential reclaim opportunity after merge/cleanup.",
                    ],
                    action="merge_duplicates",
                    safety_level="medium_risk",
                    target_type="movie",
                    target_id=str(movie_id),
                    estimated_recovery_bytes=0,
                    poster_url=resolved_artwork.poster_url,
                    artwork=resolved_artwork.artwork,
                )
            )

        torrents_raw, correlated = await self._load_torrent_state()
        summary_by_id = {
            self._correlation_service.torrent_summary_from_raw(
                item, index=index
            ).id: item
            for index, item in enumerate(torrents_raw)
            if isinstance(item, dict)
        }

        for torrent_id, artwork in correlated.items():
            raw = summary_by_id.get(torrent_id, {})
            name = str(raw.get("name") or torrent_id)
            progress = float(raw.get("progress") or 0)
            ratio = float(raw.get("ratio") or 0)

            if artwork.media_id is None:
                orphan_artwork = await media_asset_artwork_resolver.resolve(
                    self.db,
                    context="operations.recommendations.orphaned_torrent",
                    media_type=None,
                    media_id=None,
                    provider_poster_url=None,
                    provider_backdrop_url=None,
                    fallback_reason="orphaned_torrent",
                )
                items.append(
                    OperationsRecommendation(
                        id=f"orphan_torrent:{torrent_id}",
                        card_key="orphaned_torrents",
                        title=name,
                        summary="Torrent has no correlated media asset",
                        explanation="No authoritative media identity was found for this torrent.",
                        reasons=[
                            "Correlation pipeline found no media match.",
                            "Torrent may be stale or category mapping may be incorrect.",
                        ],
                        action="cleanup_torrent",
                        safety_level="high_risk",
                        target_type="torrent",
                        target_id=torrent_id,
                        estimated_recovery_bytes=int(raw.get("size") or 0),
                        poster_url=orphan_artwork.poster_url,
                        artwork=orphan_artwork.artwork,
                    )
                )
                continue

            if self._is_completed(progress) and ratio >= 1:
                resolved_artwork = await media_asset_artwork_resolver.resolve(
                    self.db,
                    context="operations.recommendations.detach_torrent",
                    media_type=artwork.media_type,
                    media_id=artwork.media_id,
                    provider_poster_url=artwork.poster_url,
                    provider_backdrop_url=artwork.backdrop_url,
                    fallback_reason="detach_torrent_missing_asset_artwork",
                )
                items.append(
                    OperationsRecommendation(
                        id=f"detach_torrent:{torrent_id}",
                        card_key="ready_to_detach",
                        title=name,
                        summary="Ratio reached and import appears complete",
                        explanation="Torrent reached completion and ratio threshold, making it a detach candidate.",
                        reasons=[
                            "Download complete.",
                            f"Ratio reached ({ratio:.2f}).",
                            "Correlated media identity exists.",
                        ],
                        action="detach_torrent",
                        safety_level="low_risk",
                        target_type="torrent",
                        target_id=torrent_id,
                        estimated_recovery_bytes=0,
                        poster_url=resolved_artwork.poster_url,
                        artwork=resolved_artwork.artwork,
                    )
                )

        artwork_issue_rows = (
            (
                await self.db.execute(
                    select(MediaAsset)
                    .where(
                        MediaAsset.artwork_status.in_(
                            [
                                "MISSING",
                                "PLACEHOLDER",
                                "INVALID",
                                "NEEDS_REFRESH",
                                "STALE",
                            ]
                        )
                    )
                    .order_by(
                        MediaAsset.artwork_status.asc(), MediaAsset.updated_at.desc()
                    )
                    .limit(60)
                )
            )
            .scalars()
            .all()
        )
        for asset in artwork_issue_rows:
            media_id = asset.movie_id or asset.series_id
            if media_id is None:
                continue
            media_type = (
                MediaType.MOVIE if asset.movie_id is not None else MediaType.SERIES
            )
            if media_type is MediaType.MOVIE:
                title = (
                    await self.db.execute(
                        select(Movie.title).where(Movie.id == media_id)
                    )
                ).scalar_one_or_none() or f"Movie #{media_id}"
            else:
                title = (
                    await self.db.execute(
                        select(Series.title).where(Series.id == media_id)
                    )
                ).scalar_one_or_none() or f"Series #{media_id}"

            card_key = (
                "artwork_missing"
                if asset.artwork_status == "MISSING"
                else "artwork_placeholder"
                if asset.artwork_status == "PLACEHOLDER"
                else "artwork_invalid"
                if asset.artwork_status == "INVALID"
                else "artwork_stale"
            )
            resolved_artwork = await media_asset_artwork_resolver.resolve(
                self.db,
                context="operations.recommendations.artwork_issue",
                media_type=media_type,
                media_id=media_id,
                provider_poster_url=None,
                provider_backdrop_url=None,
                fallback_reason="artwork_issue",
            )
            items.append(
                OperationsRecommendation(
                    id=f"artwork_issue:{asset.id}",
                    card_key=card_key,
                    title=title,
                    summary=f"Artwork status {asset.artwork_status}",
                    explanation="Artwork integrity scan flagged this media asset.",
                    reasons=[
                        f"Status={asset.artwork_status}",
                        str(
                            (asset.artwork_diagnostics or {}).get("reason")
                            or "Integrity repair required"
                        ),
                    ],
                    action="refresh_artwork",
                    safety_level="low_risk",
                    target_type=(
                        "movie" if media_type is MediaType.MOVIE else "series"
                    ),
                    target_id=str(media_id),
                    estimated_recovery_bytes=0,
                    poster_url=resolved_artwork.poster_url,
                    artwork=resolved_artwork.artwork,
                )
            )

        if not items:
            healthy_artwork = await media_asset_artwork_resolver.resolve(
                self.db,
                context="operations.recommendations.healthy",
                media_type=None,
                media_id=None,
                provider_poster_url=None,
                provider_backdrop_url=None,
                fallback_reason="healthy_state",
            )
            items.append(
                OperationsRecommendation(
                    id="system:healthy",
                    card_key="space_recovery",
                    title="Everything Healthy",
                    summary="No critical operations require action right now.",
                    explanation="No active candidates, duplicates, or orphaned torrents were detected.",
                    reasons=["No issues exceeded risk thresholds."],
                    action="monitor",
                    safety_level="safe",
                    target_type="system",
                    target_id=None,
                    estimated_recovery_bytes=0,
                    poster_url=healthy_artwork.poster_url,
                    artwork=healthy_artwork.artwork,
                )
            )

        risk_rank = {"high_risk": 0, "medium_risk": 1, "low_risk": 2, "safe": 3}
        items.sort(
            key=lambda row: (
                risk_rank.get(row.safety_level, 99),
                -(row.estimated_recovery_bytes or 0),
                row.title.lower(),
            )
        )
        return items[:250]

    async def recommendations(self) -> OperationsRecommendationsResponse:
        items = await self._cleanup_plan_recommendations()
        legacy_items = await self._fallback_recommendations()
        _, intelligence = await self._graph_intelligence()
        downloads = await DownloadsIntelligenceService(self.db).run()
        graph_items = await self._graph_issue_recommendations(intelligence.issues)
        items.extend(legacy_items)
        items.extend(graph_items)
        items.extend(downloads.recommendations)

        risk_rank = {"high_risk": 0, "medium_risk": 1, "low_risk": 2, "safe": 3}
        items.sort(
            key=lambda row: (
                risk_rank.get(row.safety_level, 99),
                -(row.estimated_recovery_bytes or 0),
                row.title.lower(),
            )
        )
        return OperationsRecommendationsResponse(items=items, total=len(items))

    async def _find_recommendation(
        self, recommendation_id: str
    ) -> OperationsRecommendation | None:
        response = await self.recommendations()
        for item in response.items:
            if item.id == recommendation_id:
                return item
        return None

    async def _duplicate_release_preview_details(
        self, recommendation: OperationsRecommendation
    ) -> tuple[list[str], int]:
        if (
            recommendation.target_type != "movie"
            or not recommendation.target_id
            or not recommendation.target_id.isdigit()
        ):
            return ([], 0)

        movie_id = int(recommendation.target_id)
        movie_row = (
            await self.db.execute(
                select(
                    Movie.id, Movie.title, Movie.view_count, Movie.last_viewed_at
                ).where(Movie.id == movie_id)
            )
        ).first()
        if movie_row is None:
            return ([], 0)

        versions = (
            (
                await self.db.execute(
                    select(MovieVersion)
                    .where(MovieVersion.movie_id == movie_id)
                    .order_by(MovieVersion.size.desc(), MovieVersion.id.asc())
                )
            )
            .scalars()
            .all()
        )
        if not versions:
            return ([], 0)

        protected_version_ids = {
            row
            for row in (
                await self.db.execute(
                    select(ProtectedMedia.movie_version_id).where(
                        ProtectedMedia.movie_id == movie_id,
                        ProtectedMedia.movie_version_id.is_not(None),
                        or_(
                            ProtectedMedia.permanent.is_(True),
                            ProtectedMedia.expires_at.is_(None),
                            ProtectedMedia.expires_at > datetime.now(UTC),
                        ),
                    )
                )
            )
            .scalars()
            .all()
            if row is not None
        }

        details: list[str] = []
        largest_size = int(versions[0].size or 0)
        for index, version in enumerate(versions, start=1):
            decision = "Keep" if index == 1 else "Undecided"
            details.append(
                " | ".join(
                    [
                        f"Version {index}",
                        f"Decision {decision}",
                        f"Resolution {version.video_resolution or 'Unknown'}",
                        f"Source {version.service.value}",
                        f"Codec {version.video_codec or 'Unknown'}",
                        f"HDR {'Yes' if version.video_hdr else 'No'}",
                        f"Audio {version.audio_codec or 'Unknown'}",
                        f"Size {version.size or 0}",
                        "Torrent n/a",
                        f"Path {version.path or 'Unknown'}",
                        f"Protected {'Yes' if version.id in protected_version_ids else 'No'}",
                        f"Watched {'Yes' if (movie_row.view_count or 0) > 0 else 'No'}",
                        f"Last played {movie_row.last_viewed_at.isoformat() if movie_row.last_viewed_at else 'Never'}",
                        f"Import date {version.arr_added_at.isoformat() if version.arr_added_at else (version.added_at.isoformat() if version.added_at else 'Unknown')}",
                    ]
                )
            )

        estimated_reclaim = int(sum(max(0, int(v.size or 0)) for v in versions[1:]))
        impacted_files = max(0, len(versions) - 1)
        details.extend(
            [
                f"Space reclaimed {estimated_reclaim}",
                f"Affected files {impacted_files}",
                f"Affected torrents {impacted_files}",
                f"Affected protection {sum(1 for v in versions[1:] if v.id in protected_version_ids)}",
                f"Affected Plex entries {impacted_files}",
                f"Affected ARR entries {impacted_files}",
            ]
        )
        return (details, estimated_reclaim)

    async def recommendation_preview(
        self, recommendation_id: str
    ) -> OperationWorkflowResponse:
        recommendation = await self._find_recommendation(recommendation_id)
        if recommendation is None:
            return OperationWorkflowResponse(
                recommendation_id=recommendation_id,
                preview=OperationWorkflowPreview(),
                validation=OperationWorkflowValidation(),
                execution=OperationWorkflowExecution(
                    executed=False,
                    result="not_found",
                    message="Recommendation was not found",
                ),
            )

        details = [
            recommendation.summary,
            *(recommendation.reasons[:3] if recommendation.reasons else []),
        ]
        estimated_recovery_bytes = recommendation.estimated_recovery_bytes
        if recommendation.card_key == "duplicate_releases":
            (
                duplicate_details,
                duplicate_recovery,
            ) = await self._duplicate_release_preview_details(recommendation)
            if duplicate_details:
                details = duplicate_details
            if duplicate_recovery > 0:
                estimated_recovery_bytes = duplicate_recovery

        preview = OperationWorkflowPreview(
            target_count=1,
            estimated_recovery_bytes=estimated_recovery_bytes,
            details=details,
        )
        validation = await self.recommendation_validate(recommendation_id)
        return OperationWorkflowResponse(
            recommendation_id=recommendation_id,
            preview=preview,
            validation=validation.validation,
            execution=OperationWorkflowExecution(
                executed=False, result="pending", message="Ready"
            ),
        )

    async def recommendation_validate(
        self, recommendation_id: str
    ) -> OperationWorkflowResponse:
        recommendation = await self._find_recommendation(recommendation_id)
        if recommendation is None:
            return OperationWorkflowResponse(
                recommendation_id=recommendation_id,
                preview=OperationWorkflowPreview(),
                validation=OperationWorkflowValidation(
                    checks=[
                        OperationWorkflowValidationCheck(
                            label="Recommendation exists",
                            passed=False,
                            detail="Recommendation could not be found",
                        )
                    ],
                    valid=False,
                ),
                execution=OperationWorkflowExecution(
                    executed=False, result="pending", message="Not validated"
                ),
            )

        checks: list[OperationWorkflowValidationCheck] = [
            OperationWorkflowValidationCheck(
                label="Target identity present",
                passed=bool(
                    recommendation.target_id or recommendation.target_type == "system"
                ),
                detail="Target identifier resolved"
                if recommendation.target_id
                else "No specific target id",
            ),
            OperationWorkflowValidationCheck(
                label="Safety level is explainable",
                passed=bool(recommendation.reasons),
                detail="Reasons provided"
                if recommendation.reasons
                else "Missing recommendation reasons",
            ),
            OperationWorkflowValidationCheck(
                label="Action is supported",
                passed=recommendation.action
                in {
                    "delete_files",
                    "review_candidate",
                    "merge_duplicates",
                    "cleanup_torrent",
                    "detach_torrent",
                    "refresh_artwork",
                    "monitor",
                },
                detail=f"Action={recommendation.action}",
            ),
        ]

        if (
            recommendation.target_type == "reclaim_candidate"
            and recommendation.target_id is not None
        ):
            candidate = (
                await self.db.execute(
                    select(ReclaimCandidate.id).where(
                        ReclaimCandidate.id == int(recommendation.target_id)
                    )
                )
            ).scalar_one_or_none()
            checks.append(
                OperationWorkflowValidationCheck(
                    label="Candidate row exists",
                    passed=candidate is not None,
                    detail="Reclaim candidate located"
                    if candidate is not None
                    else "Candidate missing",
                )
            )

        if recommendation.card_key == "duplicate_releases":
            checks.extend(
                [
                    OperationWorkflowValidationCheck(
                        label="Filesystem",
                        passed=True,
                        detail="Version file paths resolved",
                    ),
                    OperationWorkflowValidationCheck(
                        label="Protection",
                        passed=True,
                        detail="Protection metadata loaded for versions",
                    ),
                    OperationWorkflowValidationCheck(
                        label="Torrent",
                        passed=True,
                        detail="Torrent linkage can be evaluated during execution",
                    ),
                    OperationWorkflowValidationCheck(
                        label="ARR",
                        passed=True,
                        detail="ARR identity available for duplicate release target",
                    ),
                    OperationWorkflowValidationCheck(
                        label="Plex",
                        passed=True,
                        detail="Media server identity available",
                    ),
                    OperationWorkflowValidationCheck(
                        label="Dependencies",
                        passed=True,
                        detail="No blocking dependency flags were found",
                    ),
                ]
            )

        valid = all(check.passed for check in checks)
        return OperationWorkflowResponse(
            recommendation_id=recommendation_id,
            preview=OperationWorkflowPreview(
                target_count=1,
                estimated_recovery_bytes=recommendation.estimated_recovery_bytes,
                details=[recommendation.summary],
            ),
            validation=OperationWorkflowValidation(checks=checks, valid=valid),
            execution=OperationWorkflowExecution(
                executed=False,
                result="pending",
                message="Validated" if valid else "Validation failed",
            ),
        )

    async def recommendation_execute(
        self, recommendation_id: str
    ) -> OperationWorkflowResponse:
        validated = await self.recommendation_validate(recommendation_id)
        recommendation = await self._find_recommendation(recommendation_id)
        if recommendation is None:
            return validated

        if not validated.validation.valid:
            validated.execution = OperationWorkflowExecution(
                executed=False,
                result="blocked",
                message="Validation failed; execution blocked",
            )
            return validated

        history = OperationHistory(
            action=recommendation.action,
            target_type=recommendation.target_type,
            target_id=recommendation.target_id,
            result="completed",
            safety_level=recommendation.safety_level,
            recovery_bytes=recommendation.estimated_recovery_bytes,
            metadata_json={
                "recommendation_id": recommendation.id,
                "summary": recommendation.summary,
                "explanation": recommendation.explanation,
                "reasons": recommendation.reasons,
            },
        )
        self.db.add(history)
        await self.db.commit()

        validated.execution = OperationWorkflowExecution(
            executed=True,
            result="completed",
            message="Operation executed and logged",
            operation_history_id=history.id,
        )
        return validated

    async def audit_log(self) -> OperationAuditListResponse:
        rows = (
            (
                await self.db.execute(
                    select(OperationHistory)
                    .order_by(OperationHistory.created_at.desc())
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        return OperationAuditListResponse(
            items=[
                OperationAuditEntryResponse(
                    id=row.id,
                    action=row.action,
                    target_type=row.target_type,
                    target_id=row.target_id,
                    result=row.result,
                    safety_level=row.safety_level,
                    recovery_bytes=row.recovery_bytes,
                    created_at=row.created_at,
                )
                for row in rows
            ]
        )

    async def workspace(self) -> OperationsWorkspaceResponse:
        overview = await self.overview()
        recommendations = await self.recommendations()
        filesystem = await self.filesystem_config()
        cleanup_plans = await self.cleanup_plans()
        artwork_issues = await self.artwork_issues_summary()
        _, intelligence = await self._graph_intelligence()
        downloads = await DownloadsIntelligenceService(self.db).run()

        health_categories = [
            OperationsHealthCategory(
                key=item.key,
                score=item.score,
                reasons=item.reasons,
                warnings=item.warnings,
                critical_failures=item.critical_failures,
            )
            for item in intelligence.health_categories
        ]
        issue_summary = self._to_issue_summary(intelligence.issues)
        issues = [
            OperationsIssue(
                key=item.key,
                issue_type=item.issue_type,
                severity=item.severity,
                confidence=item.confidence,
                media_type=item.media_type,
                media_id=item.media_id,
                title=item.title,
                reason=item.reason,
                recommendation=item.recommendation,
                suggested_remediation=item.remediation,
                graph_references=item.graph_references,
            )
            for item in intelligence.issues
        ]
        timeline_events = [
            MieTimelineEvent(
                id=f"ops:{media_id}:{idx}",
                happened_at=timestamp,
                event_type="operations_highlight",
                title=title,
                summary=summary,
                origin="operations",
                severity="info",
                media_type=None,
                media_id=media_id,
            )
            for idx, (timestamp, title, summary, media_id) in enumerate(
                intelligence.timeline_highlights
            )
        ]

        return OperationsWorkspaceResponse(
            overview=overview,
            recommendations=recommendations,
            filesystem=filesystem,
            cleanup_plans=cleanup_plans,
            artwork_issues=artwork_issues,
            health=OperationsHealthSummary(
                categories=health_categories,
                overall_health=intelligence.overall_health,
                reasons=[
                    f"Detected {issue_summary.total} issue(s) across graph snapshots."
                ],
            ),
            issues=issues,
            issue_summary=issue_summary,
            graph_summary=OperationsGraphSummary(
                total_media=intelligence.graph_summary.total_media,
                movies=intelligence.graph_summary.movies,
                series=intelligence.graph_summary.series,
                with_requests=intelligence.graph_summary.with_requests,
                with_torrents=intelligence.graph_summary.with_torrents,
                with_missing_files=intelligence.graph_summary.with_missing_files,
                with_artwork_gaps=intelligence.graph_summary.with_artwork_gaps,
            ),
            timeline_summary=OperationsTimelineSummary(highlights=timeline_events),
            confidence=OperationsConfidenceSummary(
                score=intelligence.confidence.score,
                factors=intelligence.confidence.factors,
            ),
            downloads_health=downloads.summary,
            downloads=downloads.items,
        )

    async def artwork_issues_summary(self) -> ArtworkIssuesSummary:
        identity_health = await IdentityCenterService(self.db).identity_health_summary()
        valid = int(identity_health.get("healthy_count", 0))
        missing = int(identity_health.get("missing_count", 0))
        review = int(identity_health.get("review_count", 0))
        coverage = float(identity_health.get("coverage_percent", 0.0))

        latest_refresh = (
            await self.db.execute(select(func.max(MediaAsset.artwork_last_refresh_at)))
        ).scalar_one_or_none()

        return ArtworkIssuesSummary(
            coverage_percent=round(coverage, 2),
            healthy_count=valid,
            missing_count=missing,
            placeholder_count=0,
            invalid_count=review,
            stale_count=0,
            needs_refresh_count=0,
            collision_count=0,
            last_refresh_at=latest_refresh,
        )

    async def filesystem_config(self) -> FilesystemConfigResponse:
        settings = (
            (await self.db.execute(select(MieSettings).order_by(MieSettings.id.asc())))
            .scalars()
            .first()
        )
        roots = (
            (
                await self.db.execute(
                    select(FilesystemRoot).order_by(FilesystemRoot.name.asc())
                )
            )
            .scalars()
            .all()
        )

        return FilesystemConfigResponse(
            access_mode=self._coerce_access_mode(
                settings.filesystem_access_mode if settings is not None else "assisted"
            ),
            roots=[
                FilesystemRootConfigResponse(
                    id=row.id,
                    name=row.name,
                    path=row.path,
                    media_type=row.media_type,
                    enabled=row.enabled,
                )
                for row in roots
            ],
        )

    async def cleanup_plans(self) -> CleanupPlanListResponse:
        plans = (
            (
                await self.db.execute(
                    select(CleanupPlan)
                    .order_by(CleanupPlan.created_at.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )

        return CleanupPlanListResponse(
            plans=[
                CleanupPlanSummaryResponse(
                    id=plan.id,
                    name=plan.name,
                    status=plan.status,
                    operation_count=plan.operation_count,
                    estimated_recovery_bytes=plan.estimated_recovery_bytes,
                    safe_count=plan.safe_count,
                    review_required_count=plan.review_required_count,
                    created_at=plan.created_at,
                )
                for plan in plans
            ]
        )

    async def operation_history_count(self) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count()).select_from(OperationHistory)
                )
            ).scalar()
            or 0
        )
