from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import (
    CleanupPlan,
    CleanupPlanItem,
    FilesystemRoot,
    MieSettings,
    Movie,
    MovieVersion,
    OperationHistory,
    ReclaimCandidate,
    Series,
)
from backend.models.mie import (
    CleanupPlanListResponse,
    CleanupPlanSummaryResponse,
    FilesystemAccessMode,
    FilesystemConfigResponse,
    FilesystemRootConfigResponse,
    OperationsCard,
    OperationsOverviewResponse,
    OperationsRecommendation,
    OperationsRecommendationsResponse,
)

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
        "Imported and protected assets that can detach torrents",
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
        "Multiple torrents resolving to same payload",
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


class OperationsService:
    """Facade for Operations page data sourced from MIE state and existing models."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def overview(self) -> OperationsOverviewResponse:
        reclaim_count = int(
            (
                await self.db.execute(
                    select(func.count()).select_from(ReclaimCandidate)
                )
            ).scalar()
            or 0
        )

        # Best-effort heuristics until deep provider correlations are persisted.
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

        counts: dict[str, int] = {
            "downloading": 0,
            "import_pending": movie_without_versions,
            "ready_to_detach": 0,
            "protected_seeding": 0,
            "detached_media": 0,
            "orphaned_torrents": 0,
            "orphaned_files": 0,
            "broken_imports": movie_without_versions,
            "unknown_files": 0,
            "duplicate_releases": duplicate_releases,
            "duplicate_torrents": 0,
            "empty_folders": 0,
            "leftover_files": 0,
            "space_recovery": estimated_recovery_bytes,
        }

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

    async def recommendations(self) -> OperationsRecommendationsResponse:
        rows = (
            (
                await self.db.execute(
                    select(CleanupPlanItem)
                    .order_by(CleanupPlanItem.created_at.desc())
                    .limit(250)
                )
            )
            .scalars()
            .all()
        )

        if rows:
            items = [
                OperationsRecommendation(
                    id=f"plan-item:{row.id}",
                    card_key=row.card_key,
                    title=row.title,
                    summary=row.summary,
                    action=row.action,
                    safety_level=row.safety_level,  # type: ignore[arg-type]
                    target_type=row.target_type,
                    target_id=row.target_id,
                    estimated_recovery_bytes=row.estimated_recovery_bytes,
                )
                for row in rows
            ]
            return OperationsRecommendationsResponse(items=items, total=len(items))

        fallback_rows = (
            (
                await self.db.execute(
                    select(ReclaimCandidate)
                    .order_by(ReclaimCandidate.created_at.desc())
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        items = [
            OperationsRecommendation(
                id=f"candidate:{row.id}",
                card_key="space_recovery",
                title=f"Review reclaim candidate #{row.id}",
                summary=row.reason or "Candidate queued by rule engine",
                action="review_candidate",
                safety_level="low_risk",
                target_type="reclaim_candidate",
                target_id=str(row.id),
                estimated_recovery_bytes=row.estimated_space_bytes or 0,
            )
            for row in fallback_rows
        ]
        return OperationsRecommendationsResponse(items=items, total=len(items))

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
            access_mode=cast(
                FilesystemAccessMode,
                settings.filesystem_access_mode if settings is not None else "assisted",
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
