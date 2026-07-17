from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.service_manager import service_manager
from backend.database.models import (
    MediaAsset,
    Movie,
    OperationHistory,
    ProtectedMedia,
    ReclaimCandidate,
    Series,
)
from backend.enums import MediaType, SeerrRequestStatus
from backend.models.mie import (
    MieAssetHealthScore,
    MieHealthFactor,
    MieLifecycleBucket,
    MieOverviewResponse,
    MieRelationshipEdge,
    MieRelationshipGraphResponse,
    MieRelationshipNode,
    MieTimelineEvent,
    MieTimelineResponse,
)
from backend.services.mie.operations_service import OperationsService


class MediaIntelligenceService:
    """Authoritative MIE read model for overview, timeline, and relationships."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _health_state(score: int) -> str:
        if score >= 90:
            return "excellent"
        if score >= 75:
            return "good"
        if score >= 55:
            return "fair"
        if score >= 35:
            return "poor"
        return "critical"

    @staticmethod
    def _coerce_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    async def _ensure_mie_snapshot(self) -> dict[str, int]:
        overview = await OperationsService(self.db).overview()
        return {card.key: int(card.count) for card in overview.cards}

    async def overview(self) -> MieOverviewResponse:
        card_counts = await self._ensure_mie_snapshot()

        assets = (await self.db.execute(select(MediaAsset))).scalars().all()
        total_assets = len(assets)
        total_movies = sum(1 for asset in assets if asset.media_type == MediaType.MOVIE)
        total_series = sum(1 for asset in assets if asset.media_type == MediaType.SERIES)

        lifecycle_counts = Counter((asset.lifecycle_state or "unknown") for asset in assets)

        factors: list[MieHealthFactor] = []
        score = 100

        degraded_count = sum(1 for asset in assets if (asset.health_state or "") != "healthy")
        if degraded_count:
            penalty = min(40, degraded_count * 3)
            score -= penalty
            factors.append(
                MieHealthFactor(
                    key="degraded_assets",
                    label="Degraded Assets",
                    status="warn",
                    score_delta=-penalty,
                    detail=f"{degraded_count} assets have degraded health state",
                )
            )
        else:
            factors.append(
                MieHealthFactor(
                    key="degraded_assets",
                    label="Degraded Assets",
                    status="good",
                    score_delta=0,
                    detail="No degraded assets detected",
                )
            )

        orphaned_torrents = int(card_counts.get("orphaned_torrents", 0))
        if orphaned_torrents:
            penalty = min(30, orphaned_torrents * 5)
            score -= penalty
            factors.append(
                MieHealthFactor(
                    key="orphaned_torrents",
                    label="Orphaned Torrents",
                    status="risk",
                    score_delta=-penalty,
                    detail=f"{orphaned_torrents} torrents are not correlated to media",
                )
            )
        else:
            factors.append(
                MieHealthFactor(
                    key="orphaned_torrents",
                    label="Orphaned Torrents",
                    status="good",
                    score_delta=0,
                    detail="No orphaned torrents detected",
                )
            )

        import_pending = int(card_counts.get("import_pending", 0))
        if import_pending:
            penalty = min(25, import_pending * 2)
            score -= penalty
            factors.append(
                MieHealthFactor(
                    key="import_pending",
                    label="Import Pending",
                    status="warn",
                    score_delta=-penalty,
                    detail=f"{import_pending} assets are pending import completion",
                )
            )

        if total_assets == 0:
            score = min(score, 80)
            factors.append(
                MieHealthFactor(
                    key="empty_index",
                    label="Indexed Assets",
                    status="warn",
                    score_delta=0,
                    detail="No media assets indexed yet",
                )
            )

        seerr_pending = 0
        seerr_approved = 0
        seerr_completed = 0
        if service_manager.seerr is not None:
            try:
                requests = await service_manager.seerr.get_all_requests(filter="all")
                for request in requests:
                    if request.status is SeerrRequestStatus.PENDING:
                        seerr_pending += 1
                    elif request.status is SeerrRequestStatus.APPROVED:
                        seerr_approved += 1
                    elif request.status is SeerrRequestStatus.COMPLETED:
                        seerr_completed += 1
            except Exception:
                pass

        score = max(0, min(100, score))
        reasons = [factor.detail for factor in factors if factor.status != "good"]
        if not reasons:
            reasons = ["No material operational risks detected"]

        return MieOverviewResponse(
            generated_at=datetime.now(UTC),
            total_assets=total_assets,
            total_movies=total_movies,
            total_series=total_series,
            overseerr_pending=seerr_pending,
            overseerr_approved=seerr_approved,
            overseerr_completed=seerr_completed,
            lifecycle=[
                MieLifecycleBucket(state=state, count=count)
                for state, count in sorted(lifecycle_counts.items(), key=lambda pair: pair[0])
            ],
            health=MieAssetHealthScore(
                score=score,
                state=self._health_state(score),  # type: ignore[arg-type]
                reasons=reasons,
                factors=factors,
            ),
        )

    async def timeline(self, *, limit: int = 80) -> MieTimelineResponse:
        limit = max(1, min(250, limit))
        await self._ensure_mie_snapshot()

        items: list[MieTimelineEvent] = []

        history_rows = (
            await self.db.execute(
                select(OperationHistory)
                .order_by(OperationHistory.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        for row in history_rows:
            media_id = int(row.target_id) if row.target_id and row.target_id.isdigit() else None
            media_type: MediaType | None = None
            if row.target_type == "movie":
                media_type = MediaType.MOVIE
            elif row.target_type == "series":
                media_type = MediaType.SERIES
            severity = "high" if row.result != "completed" else "low"
            items.append(
                MieTimelineEvent(
                    id=f"operation:{row.id}",
                    happened_at=row.created_at,
                    event_type="operation",
                    title=f"Operation {row.action}",
                    summary=f"Result={row.result}, safety={row.safety_level}",
                    origin="operations",
                    severity=severity,  # type: ignore[arg-type]
                    media_type=media_type,
                    media_id=media_id,
                )
            )

        candidate_rows = (
            await self.db.execute(
                select(ReclaimCandidate)
                .order_by(ReclaimCandidate.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        for row in candidate_rows:
            media_id = row.movie_id or row.series_id
            media_type = MediaType.MOVIE if row.movie_id is not None else MediaType.SERIES
            summary = row.reason or "Rule engine marked candidate"
            items.append(
                MieTimelineEvent(
                    id=f"candidate:{row.id}",
                    happened_at=row.created_at,
                    event_type="candidate",
                    title="Reclaim candidate created",
                    summary=summary,
                    origin="rules",
                    severity="medium",
                    media_type=media_type,
                    media_id=media_id,
                )
            )

        protected_rows = (
            await self.db.execute(
                select(ProtectedMedia)
                .order_by(ProtectedMedia.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        for row in protected_rows:
            media_id = row.movie_id or row.series_id
            media_type = row.media_type if isinstance(row.media_type, MediaType) else None
            summary = row.reason or "Protection applied"
            items.append(
                MieTimelineEvent(
                    id=f"protected:{row.id}",
                    happened_at=row.created_at,
                    event_type="protection",
                    title="Protection applied",
                    summary=summary,
                    origin="protection",
                    severity="info",
                    media_type=media_type,
                    media_id=media_id,
                )
            )

        if service_manager.seerr is not None:
            try:
                movie_by_tmdb = {
                    int(tmdb_id): int(movie_id)
                    for tmdb_id, movie_id in (
                        await self.db.execute(select(Movie.tmdb_id, Movie.id))
                    ).all()
                }
                series_by_tmdb = {
                    int(tmdb_id): int(series_id)
                    for tmdb_id, series_id in (
                        await self.db.execute(select(Series.tmdb_id, Series.id))
                    ).all()
                }
                requests = await service_manager.seerr.get_all_requests(filter="all")
                for request in requests[:limit]:
                    if request.media_type is MediaType.MOVIE:
                        local_media_id = movie_by_tmdb.get(request.tmdb_id)
                    else:
                        local_media_id = series_by_tmdb.get(request.tmdb_id)
                    items.append(
                        MieTimelineEvent(
                            id=f"seerr:{request.id}",
                            happened_at=request.created_at,
                            event_type="overseerr_request",
                            title="Overseerr request",
                            summary=f"status={request.status.name.lower()} tmdb={request.tmdb_id}",
                            origin="overseerr",
                            severity=(
                                "medium"
                                if request.status is SeerrRequestStatus.PENDING
                                else "low"
                            ),
                            media_type=request.media_type,
                            media_id=local_media_id,
                        )
                    )
            except Exception:
                pass

        items.sort(
            key=lambda item: self._coerce_utc(item.happened_at),
            reverse=True,
        )
        trimmed = items[:limit]
        return MieTimelineResponse(items=trimmed, total=len(trimmed))

    async def relationships(
        self, *, media_type: MediaType, media_id: int
    ) -> MieRelationshipGraphResponse:
        await self._ensure_mie_snapshot()

        nodes: list[MieRelationshipNode] = []
        edges: list[MieRelationshipEdge] = []

        root_id = f"media:{media_type.value}:{media_id}"

        if media_type is MediaType.MOVIE:
            media = (
                await self.db.execute(
                    select(Movie.id, Movie.title, Movie.tmdb_id).where(Movie.id == media_id)
                )
            ).first()
        else:
            media = (
                await self.db.execute(
                    select(Series.id, Series.title, Series.tmdb_id).where(Series.id == media_id)
                )
            ).first()

        if media is None:
            return MieRelationshipGraphResponse(
                generated_at=datetime.now(UTC),
                root=root_id,
                nodes=[
                    MieRelationshipNode(
                        id=root_id,
                        kind="media",
                        label="Unknown media",
                        metadata={"media_type": media_type.value, "media_id": str(media_id)},
                    )
                ],
                edges=[],
            )

        nodes.append(
            MieRelationshipNode(
                id=root_id,
                kind="media",
                label=media.title,
                metadata={
                    "media_type": media_type.value,
                    "media_id": str(media.id),
                    "tmdb_id": str(media.tmdb_id),
                },
            )
        )

        asset = (
            await self.db.execute(
                select(MediaAsset).where(
                    MediaAsset.movie_id == media_id
                    if media_type is MediaType.MOVIE
                    else MediaAsset.series_id == media_id
                )
            )
        ).scalars().first()
        if asset is not None:
            asset_node_id = f"asset:{asset.id}"
            nodes.append(
                MieRelationshipNode(
                    id=asset_node_id,
                    kind="asset",
                    label=f"Lifecycle {asset.lifecycle_state}",
                    metadata={
                        "health_state": asset.health_state,
                        "has_torrent": str(asset.has_torrent).lower(),
                        "is_protected": str(asset.is_protected).lower(),
                    },
                )
            )
            edges.append(
                MieRelationshipEdge(
                    source=root_id,
                    target=asset_node_id,
                    relation="represented_by",
                )
            )

        candidate_rows = (
            await self.db.execute(
                select(ReclaimCandidate)
                .where(
                    ReclaimCandidate.movie_id == media_id
                    if media_type is MediaType.MOVIE
                    else ReclaimCandidate.series_id == media_id
                )
                .order_by(ReclaimCandidate.created_at.desc())
                .limit(25)
            )
        ).scalars().all()
        for candidate in candidate_rows:
            node_id = f"candidate:{candidate.id}"
            nodes.append(
                MieRelationshipNode(
                    id=node_id,
                    kind="candidate",
                    label="Reclaim candidate",
                    metadata={
                        "estimated_space_bytes": str(candidate.estimated_space_bytes or 0),
                        "approved_for_deletion": str(candidate.approved_for_deletion).lower(),
                    },
                )
            )
            edges.append(
                MieRelationshipEdge(source=root_id, target=node_id, relation="candidate")
            )

        protected_rows = (
            await self.db.execute(
                select(ProtectedMedia)
                .where(
                    ProtectedMedia.movie_id == media_id
                    if media_type is MediaType.MOVIE
                    else ProtectedMedia.series_id == media_id
                )
                .order_by(ProtectedMedia.created_at.desc())
                .limit(25)
            )
        ).scalars().all()
        for row in protected_rows:
            node_id = f"protected:{row.id}"
            nodes.append(
                MieRelationshipNode(
                    id=node_id,
                    kind="protection",
                    label="Protection rule",
                    metadata={
                        "permanent": str(row.permanent).lower(),
                        "reason": row.reason or "",
                    },
                )
            )
            edges.append(
                MieRelationshipEdge(source=root_id, target=node_id, relation="protected_by")
            )

        history_rows = (
            await self.db.execute(
                select(OperationHistory)
                .where(
                    OperationHistory.target_type == media_type.value,
                    OperationHistory.target_id == str(media_id),
                )
                .order_by(OperationHistory.created_at.desc())
                .limit(25)
            )
        ).scalars().all()
        for row in history_rows:
            node_id = f"operation:{row.id}"
            nodes.append(
                MieRelationshipNode(
                    id=node_id,
                    kind="operation",
                    label=f"Action {row.action}",
                    metadata={
                        "result": row.result,
                        "safety_level": row.safety_level,
                    },
                )
            )
            edges.append(
                MieRelationshipEdge(source=root_id, target=node_id, relation="operated_by")
            )

        if service_manager.seerr is not None:
            try:
                requests = (
                    await service_manager.seerr.get_movie_requests(media.tmdb_id)
                    if media_type is MediaType.MOVIE
                    else await service_manager.seerr.get_tv_requests(media.tmdb_id)
                )
                for request in requests[:25]:
                    node_id = f"seerr:{request.id}"
                    nodes.append(
                        MieRelationshipNode(
                            id=node_id,
                            kind="overseerr_request",
                            label="Overseerr request",
                            metadata={
                                "status": request.status.name.lower(),
                                "requested_by": str(request.requested_by_id),
                            },
                        )
                    )
                    edges.append(
                        MieRelationshipEdge(
                            source=root_id,
                            target=node_id,
                            relation="requested_via_overseerr",
                        )
                    )
            except Exception:
                pass

        return MieRelationshipGraphResponse(
            generated_at=datetime.now(UTC),
            root=root_id,
            nodes=nodes,
            edges=edges,
        )
