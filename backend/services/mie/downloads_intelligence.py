from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.service_manager import service_manager
from backend.database.models import FilesystemIndexEntry, FilesystemRoot
from backend.enums import MediaType
from backend.models.mie import (
    DownloadCleanupClassification,
    DownloadLifecycleObject,
    DownloadLifecycleState,
    DownloadsHealthSummary,
    MieMediaGraphResponse,
    OperationsRecommendation,
    SafetyLevel,
)
from backend.services.mie.correlation_service import CorrelationService

_ACTIVE_STATES = {
    "metadata_download",
    "queued",
    "downloading",
    "checking",
    "moving",
    "seeding",
}


@dataclass(slots=True)
class DownloadsIntelligenceResult:
    summary: DownloadsHealthSummary
    items: list[DownloadLifecycleObject]
    recommendations: list[OperationsRecommendation]


class DownloadsIntelligenceService:
    """Classifies indexed download objects and emits cleanup intelligence."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._correlation = CorrelationService(db)
        self._graph_cache: dict[
            tuple[MediaType, int], MieMediaGraphResponse | None
        ] = {}
        self._abandoned_hours = self._load_abandoned_hours()

    @staticmethod
    def _load_abandoned_hours() -> int:
        raw = os.getenv("MIE_DOWNLOAD_ABANDONED_HOURS", "336")
        try:
            value = int(raw)
        except ValueError:
            value = 336
        return max(24, value)

    @staticmethod
    def _norm(value: str | None) -> str:
        return (value or "").strip().replace("\\", "/").lower().rstrip("/")

    @staticmethod
    def _torrent_state(raw_state: str | None, progress: float) -> str:
        state = (raw_state or "").lower()
        if "meta" in state:
            return "metadata_download"
        if "check" in state:
            return "checking"
        if "move" in state:
            return "moving"
        if "queue" in state:
            return "queued"
        if "down" in state and "stalled" not in state:
            return "downloading"
        if "seed" in state or "upload" in state or "stalledup" in state:
            return "seeding"
        if progress < 1:
            return "downloading"
        return "seeding"

    @staticmethod
    def _confidence(
        *, media: bool, request: bool, arr: bool, timeline: bool, torrent: bool
    ) -> int:
        score = 45
        if media:
            score += 20
        if request:
            score += 10
        if arr:
            score += 10
        if timeline:
            score += 8
        if torrent:
            score += 7
        return min(99, score)

    async def _downloads_roots(self) -> list[FilesystemRoot]:
        rows = (
            (
                await self.db.execute(
                    select(FilesystemRoot).where(FilesystemRoot.enabled.is_(True))
                )
            )
            .scalars()
            .all()
        )
        out: list[FilesystemRoot] = []
        for root in rows:
            name = (root.name or "").lower()
            path = (root.path or "").lower()
            if "download" in name or "/downloads" in path or "\\downloads" in path:
                out.append(root)
        return out

    async def _active_torrents(self) -> list[dict[str, Any]]:
        client = service_manager.qbittorrent
        if client is None:
            return []
        try:
            torrents = await client.get_torrents()
        except Exception:
            return []
        return [row for row in torrents if isinstance(row, dict)]

    def _torrent_for_entry(
        self,
        entry: FilesystemIndexEntry,
        torrents: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        metadata = entry.metadata_json or {}
        path = self._norm(entry.path)
        fingerprint = (entry.fingerprint or "").strip().lower()
        meta_hash = str(metadata.get("torrent_hash") or "").strip().lower()
        tokens = set(
            token
            for token in re.split(r"[^a-z0-9]+", PurePosixPath(path).name.lower())
            if len(token) > 2
        )

        best: dict[str, Any] | None = None
        best_score = -1
        for torrent in torrents:
            score = 0
            thash = str(torrent.get("hash") or "").strip().lower()
            save_path = self._norm(str(torrent.get("save_path") or ""))
            name = str(torrent.get("name") or "")
            name_tokens = set(
                token
                for token in re.split(r"[^a-z0-9]+", name.lower())
                if len(token) > 2
            )

            if thash and (thash == meta_hash or thash == fingerprint):
                score += 6
            if save_path and (path.startswith(save_path) or save_path.startswith(path)):
                score += 4
            overlap = len(tokens.intersection(name_tokens))
            if overlap:
                score += min(3, overlap)

            if score > best_score:
                best_score = score
                best = torrent

        return best if best_score >= 4 else None

    async def _graph_for(
        self,
        media_type: MediaType | None,
        media_id: int | None,
    ) -> MieMediaGraphResponse | None:
        if media_type is None or media_id is None:
            return None
        key = (media_type, media_id)
        if key in self._graph_cache:
            return self._graph_cache[key]
        try:
            graph = await self._correlation.media_graph(
                media_id=media_id, media_type=media_type
            )
        except ValueError:
            graph = None
        self._graph_cache[key] = graph
        return graph

    async def _classify_entry(
        self,
        entry: FilesystemIndexEntry,
        torrents: list[dict[str, Any]],
    ) -> DownloadLifecycleObject:
        now = datetime.now(UTC)
        metadata = entry.metadata_json or {}

        media_type: MediaType | None = None
        media_id: int | None = None
        if metadata.get("movie_id") is not None:
            media_type = MediaType.MOVIE
            media_id = int(metadata["movie_id"])
        elif metadata.get("series_id") is not None:
            media_type = MediaType.SERIES
            media_id = int(metadata["series_id"])
        elif metadata.get("media_type") in {"movie", "series"} and metadata.get(
            "media_id"
        ):
            media_type = (
                MediaType.MOVIE
                if metadata.get("media_type") == "movie"
                else MediaType.SERIES
            )
            media_id = int(metadata["media_id"])

        graph = await self._graph_for(media_type, media_id)
        torrent = self._torrent_for_entry(entry, torrents)
        torrent_name = str(torrent.get("name") or "") if torrent else None
        torrent_hash = str(torrent.get("hash") or "") if torrent else None
        torrent_progress = float(torrent.get("progress") or 0.0) if torrent else 0.0
        torrent_state = (
            self._torrent_state(str(torrent.get("state") or ""), torrent_progress)
            if torrent
            else None
        )

        request_known = bool(
            graph
            and (
                graph.request_intelligence.request_state != "unknown"
                or graph.request_intelligence.requests
            )
        )
        arr_known = bool(graph and graph.arr_intelligence.ownership)
        timeline = [
            f"{event.source}:{event.event}"
            for event in (graph.timeline[:4] if graph else [])
        ]
        has_import_history = any(
            token in " ".join(timeline)
            for token in ("available", "import", "added_to_arr")
        )

        import_completed = bool(
            graph
            and graph.file_intelligence.missing_files == 0
            and graph.file_intelligence.total_size_bytes > 0
        )
        import_failed = bool(
            graph
            and (
                graph.file_intelligence.missing_files > 0
                or graph.health.overall_health_score < 45
            )
            and torrent_state not in _ACTIVE_STATES
        )

        lifecycle_state: DownloadLifecycleState
        import_status: str
        if torrent_state in _ACTIVE_STATES:
            lifecycle_state = cast(DownloadLifecycleState, torrent_state)
            import_status = "in_progress"
        elif import_failed:
            lifecycle_state = "failed"
            import_status = "failed"
        elif import_completed and not torrent:
            lifecycle_state = (
                "stale" if not arr_known and not request_known else "imported"
            )
            import_status = "completed_waiting_cleanup"
        elif (
            not torrent
            and not arr_known
            and not request_known
            and not has_import_history
        ):
            if graph is None and media_type is None and media_id is None:
                lifecycle_state = "unknown"
                import_status = "undetermined"
            else:
                lifecycle_state = "orphaned"
                import_status = "no_ownership"
        elif import_completed:
            lifecycle_state = "imported"
            import_status = "completed"
        else:
            lifecycle_state = "unknown"
            import_status = "undetermined"

        last_activity = entry.modified_at or entry.indexed_at
        age_hours = 0
        if last_activity is not None:
            dt = (
                last_activity
                if last_activity.tzinfo
                else last_activity.replace(tzinfo=UTC)
            )
            age_hours = max(0, int((now - dt).total_seconds() // 3600))

        cleanup: DownloadCleanupClassification = "none"
        cleanup_reason: str | None = None
        if lifecycle_state == "failed":
            cleanup = "failed_import"
            cleanup_reason = "Download/import signals indicate a failed import path."
        elif lifecycle_state == "unknown":
            cleanup = "needs_investigation"
            cleanup_reason = "Ownership and import lineage could not be determined."
        elif lifecycle_state in {"orphaned", "stale"}:
            cleanup = "safe_to_delete"
            cleanup_reason = "No active ownership remains and object is not required for active transfer."
        elif lifecycle_state == "imported" and torrent_state == "seeding":
            cleanup = "safe_to_archive"
            cleanup_reason = (
                "Imported content still seeding; archive is safer than deletion."
            )
        elif lifecycle_state == "imported" and import_completed:
            cleanup = "duplicate_download"
            cleanup_reason = (
                "Media already exists in canonical library while download copy remains."
            )

        if cleanup == "none" and age_hours >= self._abandoned_hours and not torrent:
            cleanup = "abandoned_download"
            cleanup_reason = (
                f"No activity for {age_hours}h (threshold {self._abandoned_hours}h)."
            )

        media_identity = (
            f"{graph.identity.canonical_title} ({graph.identity.media_type.value})"
            if graph is not None
            else None
        )
        associated_request = None
        if graph and graph.request_intelligence.requests:
            first_request = graph.request_intelligence.requests[0]
            associated_request = (
                f"{first_request.request_source}:{first_request.request_id}"
            )

        associated_arr_record = None
        if graph and graph.arr_intelligence.ownership:
            arr = graph.arr_intelligence.ownership[0]
            associated_arr_record = f"{arr.provider}:{arr.internal_arr_id}"

        confidence = self._confidence(
            media=graph is not None,
            request=request_known,
            arr=arr_known,
            timeline=bool(timeline),
            torrent=torrent is not None,
        )

        owner = None
        if associated_arr_record:
            owner = associated_arr_record
        elif associated_request:
            owner = associated_request

        return DownloadLifecycleObject(
            path=entry.path,
            entry_type=entry.entry_type,
            torrent=(
                f"{torrent_name} ({torrent_hash})"
                if torrent_name and torrent_hash
                else torrent_name
            ),
            owner=owner,
            media_identity=media_identity,
            media_type=media_type,
            media_id=media_id,
            lifecycle_state=lifecycle_state,
            import_status=import_status,
            age_hours=age_hours,
            size_bytes=max(0, int(entry.size_bytes or 0)),
            last_activity_at=last_activity,
            associated_request=associated_request,
            associated_arr_record=associated_arr_record,
            associated_timeline=timeline,
            confidence_score=confidence,
            cleanup_classification=cleanup,
            cleanup_reason=cleanup_reason,
        )

    @staticmethod
    def _to_recommendation(
        item: DownloadLifecycleObject,
    ) -> OperationsRecommendation | None:
        if item.cleanup_classification == "none":
            return None

        action_map: dict[
            DownloadCleanupClassification,
            tuple[str, SafetyLevel, str],
        ] = {
            "safe_to_delete": ("delete_download_candidate", "safe", "safe_to_delete"),
            "safe_to_archive": (
                "archive_download_candidate",
                "low_risk",
                "safe_to_archive",
            ),
            "needs_investigation": (
                "investigate_download",
                "low_risk",
                "needs_investigation",
            ),
            "failed_import": (
                "repair_failed_import",
                "medium_risk",
                "failed_downloads",
            ),
            "duplicate_download": (
                "review_duplicate_download",
                "low_risk",
                "duplicate_downloads",
            ),
            "abandoned_download": (
                "review_abandoned_download",
                "low_risk",
                "orphaned_downloads",
            ),
            "none": ("monitor_download", "safe", "unknown_downloads"),
        }
        action, safety, card_key = action_map[item.cleanup_classification]

        reasons = [
            f"State: {item.lifecycle_state}",
            f"Import status: {item.import_status}",
            item.cleanup_reason or "No reason provided",
        ]

        return OperationsRecommendation(
            id=f"download:{item.path}",
            card_key=card_key,
            title=PurePosixPath(item.path).name or item.path,
            summary=item.cleanup_reason or "Download lifecycle recommendation",
            explanation=(
                f"Directory/file {item.path} is classified as {item.lifecycle_state}. "
                f"Recommendation: {item.cleanup_classification.replace('_', ' ')}."
            ),
            reasons=reasons,
            action=action,
            safety_level=safety,
            target_type="download_object",
            target_id=item.path,
            estimated_recovery_bytes=item.size_bytes
            if item.cleanup_classification in {"safe_to_delete", "duplicate_download"}
            else 0,
            poster_url=None,
            artwork=None,
            issue_key=f"download:{item.cleanup_classification}:{item.path}",
            confidence=item.confidence_score,
            graph_references=[
                "filesystem_index_entries.path",
                "qbittorrent.torrents",
                "correlation_graph.timeline",
            ],
        )

    def _summarize(
        self, items: list[DownloadLifecycleObject]
    ) -> DownloadsHealthSummary:
        summary = DownloadsHealthSummary()
        for item in items:
            summary.total_download_space += item.size_bytes

            if item.lifecycle_state in {
                "metadata_download",
                "queued",
                "downloading",
                "checking",
                "moving",
                "seeding",
            }:
                summary.active_downloads += 1

            if item.lifecycle_state in {"downloading", "queued", "checking", "moving"}:
                summary.completed_waiting_for_import += (
                    1
                    if item.import_status == "in_progress"
                    and item.confidence_score >= 60
                    else 0
                )

            if item.import_status == "completed_waiting_cleanup":
                summary.completed_waiting_for_cleanup += 1

            if item.lifecycle_state in {"imported", "stale"}:
                summary.imported_but_still_present += 1

            if item.cleanup_classification == "duplicate_download":
                summary.duplicate_downloads += 1
            if item.lifecycle_state == "failed":
                summary.failed_downloads += 1
            if item.lifecycle_state == "unknown":
                summary.unknown_downloads += 1
            if item.lifecycle_state == "orphaned":
                summary.orphaned_downloads += 1

            if item.cleanup_classification == "safe_to_delete":
                summary.safe_to_delete += 1
                summary.recoverable_space += item.size_bytes
            if item.cleanup_classification == "duplicate_download":
                summary.recoverable_space += item.size_bytes

        return summary

    async def run(self) -> DownloadsIntelligenceResult:
        roots = await self._downloads_roots()
        if not roots:
            return DownloadsIntelligenceResult(
                summary=DownloadsHealthSummary(),
                items=[],
                recommendations=[],
            )

        root_paths = {root.id: self._norm(root.path) for root in roots}
        root_ids = tuple(root_paths.keys())

        rows = (
            (
                await self.db.execute(
                    select(FilesystemIndexEntry).where(
                        FilesystemIndexEntry.root_id.in_(root_ids)
                    )
                )
            )
            .scalars()
            .all()
        )

        filtered_rows: list[FilesystemIndexEntry] = []
        for row in rows:
            root_path = root_paths.get(row.root_id)
            if not root_path:
                continue
            if self._norm(row.path).startswith(root_path):
                filtered_rows.append(row)

        torrents = await self._active_torrents()
        items: list[DownloadLifecycleObject] = []
        for row in filtered_rows:
            items.append(await self._classify_entry(row, torrents))

        items.sort(key=lambda row: (row.lifecycle_state, -row.size_bytes, row.path))
        summary = self._summarize(items)
        recommendations = [
            rec
            for rec in (self._to_recommendation(item) for item in items)
            if rec is not None
        ]
        recommendations.sort(
            key=lambda row: (
                {"high_risk": 0, "medium_risk": 1, "low_risk": 2, "safe": 3}.get(
                    row.safety_level, 9
                ),
                -(row.estimated_recovery_bytes or 0),
                row.title.lower(),
            )
        )

        return DownloadsIntelligenceResult(
            summary=summary,
            items=items[:500],
            recommendations=recommendations[:250],
        )
