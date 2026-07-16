from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Integer, and_, cast as sql_cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.artwork import resolve_poster_url
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
    CleanupPlanListResponse,
    CleanupPlanSummaryResponse,
    FilesystemAccessMode,
    FilesystemConfigResponse,
    FilesystemRootConfigResponse,
    OperationAuditEntryResponse,
    OperationAuditListResponse,
    OperationsCard,
    OperationsOverviewResponse,
    OperationsRecommendation,
    OperationsRecommendationsResponse,
    OperationsWorkspaceResponse,
    OperationWorkflowExecution,
    OperationWorkflowPreview,
    OperationWorkflowResponse,
    OperationWorkflowValidation,
    OperationWorkflowValidationCheck,
)
from backend.services.correlation import CorrelatedArtwork, MediaCorrelationService

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
            correlated[summary.id] = await self._correlation_service.resolve_torrent_artwork(
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
        protected_movies = {int(movie_id) for movie_id, _ in rows if movie_id is not None}
        protected_series = {int(series_id) for _, series_id in rows if series_id is not None}
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
            await self.db.execute(select(MediaAsset).order_by(MediaAsset.id.asc()))
        ).scalars().all()
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
            await self.db.execute(
                select(Movie).where(Movie.removed_at.is_(None)).order_by(Movie.id.asc())
            )
        ).scalars().all()

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
            asset.recommendation = recommendation
            asset.last_indexed_at = datetime.now(UTC)

        series_rows = (
            await self.db.execute(
                select(Series).where(Series.removed_at.is_(None)).order_by(Series.id.asc())
            )
        ).scalars().all()
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
            asset.recommendation = recommendation
            asset.last_indexed_at = datetime.now(UTC)

        await self.db.flush()

    async def _overview_counts(self) -> dict[str, int]:
        reclaim_count = int((await self.db.execute(select(func.count()).select_from(ReclaimCandidate))).scalar() or 0)

        movie_without_versions = int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(Movie)
                    .where(Movie.removed_at.is_(None))
                    .where(
                        ~Movie.id.in_(
                            select(MovieVersion.movie_id).where(MovieVersion.movie_id.is_not(None))
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
                    select(func.count()).select_from(MovieVersion).where(
                        or_(MovieVersion.path.is_(None), MovieVersion.path == "")
                    )
                )
            ).scalar()
            or 0
        )

        estimated_recovery_bytes = int(
            (
                await self.db.execute(
                    select(func.coalesce(func.sum(ReclaimCandidate.estimated_space_bytes), 0))
                )
            ).scalar()
            or 0
        )

        torrents_raw, correlated = await self._load_torrent_state()
        await self._refresh_media_assets_snapshot(correlated)

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
            self._correlation_service.torrent_summary_from_raw(item, index=index).id: item
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

        duplicate_torrents = sum(max(0, count - 1) for count in normalized_names.values() if count > 1)

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
        }
        return counts

    async def overview(self) -> OperationsOverviewResponse:
        counts = await self._overview_counts()
        cards = [
            OperationsCard(
                key=key,
                title=title,
                description=description,
                count=counts.get(key, 0),
                severity=severity,  # type: ignore[arg-type]
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
                    Movie.poster_url.label("movie_poster_url"),
                    Series.title.label("series_title"),
                    Series.poster_url.label("series_poster_url"),
                )
                .outerjoin(Movie, Movie.id == sql_cast(CleanupPlanItem.target_id, Integer))
                .outerjoin(Series, Series.id == sql_cast(CleanupPlanItem.target_id, Integer))
                .order_by(CleanupPlanItem.created_at.desc())
                .limit(250)
            )
        ).all()

        items: list[OperationsRecommendation] = []
        for row in rows:
            item = row.CleanupPlanItem
            title = row.movie_title or row.series_title or item.title
            reasons = [r.strip() for r in item.summary.split(";") if r.strip()] if item.summary else []
            if not reasons and item.summary:
                reasons = [item.summary]
            items.append(
                OperationsRecommendation(
                    id=f"plan-item:{item.id}",
                    card_key=item.card_key,
                    title=title,
                    summary=item.summary,
                    explanation=item.summary,
                    reasons=reasons,
                    action=item.action,
                    safety_level=item.safety_level,  # type: ignore[arg-type]
                    target_type=item.target_type,
                    target_id=item.target_id,
                    estimated_recovery_bytes=item.estimated_recovery_bytes,
                    poster_url=resolve_poster_url(
                        row.movie_poster_url or row.series_poster_url,
                        context="operations.recommendations.cleanup_plan",
                        media_type="movie" if row.movie_poster_url else "series",
                    ),
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
                .order_by(ReclaimCandidate.estimated_space_bytes.desc(), ReclaimCandidate.created_at.desc())
                .limit(150)
            )
        ).all()

        items: list[OperationsRecommendation] = []
        for row in rows:
            candidate = row.ReclaimCandidate
            target_title = row.movie_title or row.series_title or f"Candidate #{candidate.id}"
            reasons = [candidate.reason] if candidate.reason else ["Rule engine matched candidate."]
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
                    poster_url=resolve_poster_url(
                        row.movie_poster_url or row.series_poster_url,
                        context="operations.recommendations.reclaim_candidate",
                        media_type="movie" if candidate.movie_id is not None else "series",
                        media_id=candidate.movie_id or candidate.series_id,
                    ),
                )
            )

        duplicate_rows = (
            await self.db.execute(
                select(Movie.id, Movie.title, Movie.poster_url, func.count(MovieVersion.id).label("version_count"))
                .join(MovieVersion, MovieVersion.movie_id == Movie.id)
                .where(Movie.removed_at.is_(None))
                .group_by(Movie.id)
                .having(func.count(MovieVersion.id) > 1)
                .order_by(func.count(MovieVersion.id).desc())
                .limit(30)
            )
        ).all()
        for movie_id, movie_title, movie_poster, version_count in duplicate_rows:
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
                    poster_url=resolve_poster_url(
                        movie_poster,
                        context="operations.recommendations.duplicate_release",
                        media_type="movie",
                        media_id=movie_id,
                    ),
                )
            )

        torrents_raw, correlated = await self._load_torrent_state()
        summary_by_id = {
            self._correlation_service.torrent_summary_from_raw(item, index=index).id: item
            for index, item in enumerate(torrents_raw)
            if isinstance(item, dict)
        }

        for torrent_id, artwork in correlated.items():
            raw = summary_by_id.get(torrent_id, {})
            name = str(raw.get("name") or torrent_id)
            progress = float(raw.get("progress") or 0)
            ratio = float(raw.get("ratio") or 0)

            if artwork.media_id is None:
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
                        poster_url=resolve_poster_url(
                            None,
                            context="operations.recommendations.orphaned_torrent",
                            fallback_reason="orphaned_torrent",
                        ),
                    )
                )
                continue

            if self._is_completed(progress) and ratio >= 1:
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
                        poster_url=resolve_poster_url(
                            artwork.poster_url,
                            context="operations.recommendations.detach_torrent",
                            media_type=artwork.media_type.value if artwork.media_type is not None else None,
                            media_id=artwork.media_id,
                        ),
                    )
                )

        if not items:
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
                    poster_url=resolve_poster_url(None, context="operations.recommendations.healthy"),
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
        if not items:
            items = await self._fallback_recommendations()
        return OperationsRecommendationsResponse(items=items, total=len(items))

    async def _find_recommendation(self, recommendation_id: str) -> OperationsRecommendation | None:
        response = await self.recommendations()
        for item in response.items:
            if item.id == recommendation_id:
                return item
        return None

    async def recommendation_preview(self, recommendation_id: str) -> OperationWorkflowResponse:
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

        preview = OperationWorkflowPreview(
            target_count=1,
            estimated_recovery_bytes=recommendation.estimated_recovery_bytes,
            details=[
                recommendation.summary,
                *(recommendation.reasons[:3] if recommendation.reasons else []),
            ],
        )
        validation = await self.recommendation_validate(recommendation_id)
        return OperationWorkflowResponse(
            recommendation_id=recommendation_id,
            preview=preview,
            validation=validation.validation,
            execution=OperationWorkflowExecution(executed=False, result="pending", message="Ready"),
        )

    async def recommendation_validate(self, recommendation_id: str) -> OperationWorkflowResponse:
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
                execution=OperationWorkflowExecution(executed=False, result="pending", message="Not validated"),
            )

        checks: list[OperationWorkflowValidationCheck] = [
            OperationWorkflowValidationCheck(
                label="Target identity present",
                passed=bool(recommendation.target_id or recommendation.target_type == "system"),
                detail="Target identifier resolved" if recommendation.target_id else "No specific target id",
            ),
            OperationWorkflowValidationCheck(
                label="Safety level is explainable",
                passed=bool(recommendation.reasons),
                detail="Reasons provided" if recommendation.reasons else "Missing recommendation reasons",
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
                    "monitor",
                },
                detail=f"Action={recommendation.action}",
            ),
        ]

        if recommendation.target_type == "reclaim_candidate" and recommendation.target_id is not None:
            candidate = (
                await self.db.execute(
                    select(ReclaimCandidate.id).where(ReclaimCandidate.id == int(recommendation.target_id))
                )
            ).scalar_one_or_none()
            checks.append(
                OperationWorkflowValidationCheck(
                    label="Candidate row exists",
                    passed=candidate is not None,
                    detail="Reclaim candidate located" if candidate is not None else "Candidate missing",
                )
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
            execution=OperationWorkflowExecution(executed=False, result="pending", message="Validated" if valid else "Validation failed"),
        )

    async def recommendation_execute(self, recommendation_id: str) -> OperationWorkflowResponse:
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
            await self.db.execute(
                select(OperationHistory)
                .order_by(OperationHistory.created_at.desc())
                .limit(200)
            )
        ).scalars().all()
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
        return OperationsWorkspaceResponse(
            overview=overview,
            recommendations=recommendations,
            filesystem=filesystem,
            cleanup_plans=cleanup_plans,
        )

    async def filesystem_config(self) -> FilesystemConfigResponse:
        settings = (
            (await self.db.execute(select(MieSettings).order_by(MieSettings.id.asc())))
            .scalars()
            .first()
        )
        roots = (
            (await self.db.execute(select(FilesystemRoot).order_by(FilesystemRoot.name.asc())))
            .scalars()
            .all()
        )

        return FilesystemConfigResponse(
            access_mode=(
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
                    select(CleanupPlan).order_by(CleanupPlan.created_at.desc()).limit(100)
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
        return int((await self.db.execute(select(func.count()).select_from(OperationHistory))).scalar() or 0)
