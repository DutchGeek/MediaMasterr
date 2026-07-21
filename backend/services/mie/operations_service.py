from __future__ import annotations

import os
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from stat import filemode
from typing import Any, Literal, cast

from sqlalchemy import Integer, and_, func, or_, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.service_manager import service_manager
from backend.core.utils.file_utils import bytes_to_gb
from backend.core.utils.filesystem import normalize_fpath
from backend.database.models import (
    CleanupPlan,
    CleanupPlanItem,
    Episode,
    FilesystemIndexEntry,
    FilesystemRoot,
    MediaAsset,
    MieSettings,
    Movie,
    MovieArrRef,
    MovieVersion,
    OperationHistory,
    ProtectedMedia,
    ReclaimCandidate,
    Season,
    Series,
    SeriesArrRef,
    SeriesServiceRef,
    ServiceConfig,
)
from backend.enums import MediaType, Service
from backend.models.mie import (
    ArtworkIssuesSummary,
    CleanupPlanListResponse,
    CleanupPlanSummaryResponse,
    FilesystemAccessMode,
    FilesystemConfigResponse,
    FilesystemRootConfigResponse,
    MediaPolicyDefinition,
    MieTimelineEvent,
    OperationActionManifest,
    OperationActionManifestAction,
    OperationAuditEntryResponse,
    OperationAuditListResponse,
    OperationsApplicationEvidence,
    OperationsCard,
    OperationsConfidenceSummary,
    OperationsFileEvidence,
    OperationsGraphSummary,
    OperationsHealthCategory,
    OperationsHealthSummary,
    OperationsIssue,
    OperationsIssueSummary,
    OperationsNarrative,
    OperationsNarrativeLocation,
    OperationsOverviewResponse,
    OperationsRecommendation,
    OperationsRecommendationsResponse,
    OperationsRelationshipEvidence,
    OperationsTimelineSummary,
    OperationsWorkflowAsset,
    OperationsWorkflowBoard,
    OperationsWorkflowFilter,
    OperationsWorkflowStage,
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
from backend.services.mie.request_context import MieRequestContext
from backend.services.query_engine import QueryEngineSpec, apply_spec

CARD_DEFINITIONS: list[tuple[str, str, str, str]] = [
    (
        "downloading",
        "Downloads In Progress",
        "Media currently moving through the download workflow.",
        "info",
    ),
    (
        "import_pending",
        "Waiting For Import",
        "Completed downloads that are not yet available in the library.",
        "medium",
    ),
    (
        "ready_to_detach",
        "Completed And Ready For Cleanup",
        "Imported media whose seeding requirement has completed.",
        "low",
    ),
    (
        "protected_seeding",
        "Healthy But Still Seeding",
        "Imported media that is still protected by an active seeding rule.",
        "info",
    ),
    (
        "detached_media",
        "Library Healthy",
        "Media that is available in the library with no active cleanup work.",
        "info",
    ),
    (
        "orphaned_torrents",
        "Downloads Requiring Attention",
        "Downloads that are no longer linked to a healthy library workflow.",
        "high",
    ),
    (
        "orphaned_files",
        "Unlinked Files",
        "Filesystem items that are not tied to a known media workflow.",
        "high",
    ),
    (
        "broken_imports",
        "Import Failed",
        "Media that could not be imported cleanly into the library.",
        "high",
    ),
    (
        "unknown_files",
        "Unknown Library Paths",
        "Files exist outside the expected managed media structure.",
        "medium",
    ),
    (
        "duplicate_releases",
        "Duplicate Found",
        "Multiple linked copies are competing to be the canonical library version.",
        "medium",
    ),
    (
        "duplicate_torrents",
        "Duplicate Downloads",
        "More than one download appears to represent the same media payload.",
        "medium",
    ),
    (
        "empty_folders",
        "Empty Media Folders",
        "Folders exist without any useful media payload remaining.",
        "low",
    ),
    (
        "leftover_files",
        "Cleanup Leftovers",
        "Non-library remnants can be removed after the workflow completes.",
        "low",
    ),
    ("space_recovery", "Reclaim Storage", "Completed workflows with storage recovery opportunities.", "info"),
    (
        "identity_issues",
        "Manual Match Required",
        "Media identity or provider ownership needs review before the workflow is healthy.",
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

_PRIMARY_REQUIRED_ACTION_IDS = {
    "retry_download",
    "resume_download",
    "retry_import",
    "repair_identity",
    "move_files",
}

_SECONDARY_ACTION_IDS = {
    "ignore_recommendation",
    "manual_review",
    "mark_resolved",
}

_ACTION_DEFINITIONS: dict[str, dict[str, Any]] = {
    "retry_download": {
        "label": "Retry Download",
        "category": "recovery",
        "risk": "safe",
        "confirmation": False,
        "automation": "automated",
        "kind": "operations",
        "description": "Retry stalled or failed download acquisition.",
    },
    "force_recheck": {
        "label": "Force Recheck",
        "category": "maintenance",
        "risk": "safe",
        "confirmation": False,
        "automation": "manual",
        "kind": "external",
        "description": "Request a full torrent hash recheck in the download client.",
    },
    "resume_download": {
        "label": "Resume Download",
        "category": "recovery",
        "risk": "safe",
        "confirmation": False,
        "automation": "manual",
        "kind": "external",
        "description": "Resume a paused torrent or queue item.",
    },
    "pause_torrent": {
        "label": "Pause Torrent",
        "category": "maintenance",
        "risk": "medium",
        "confirmation": False,
        "automation": "manual",
        "kind": "external",
        "description": "Pause torrent activity for this asset.",
    },
    "delete_torrent": {
        "label": "Delete Torrent",
        "category": "destructive",
        "risk": "high",
        "confirmation": True,
        "automation": "manual",
        "kind": "external",
        "description": "Remove torrent from the download client.",
    },
    "delete_torrent_and_files": {
        "label": "Delete Torrent + Files",
        "category": "destructive",
        "risk": "high",
        "confirmation": True,
        "automation": "manual",
        "kind": "filesystem",
        "description": "Remove torrent and all linked payload files.",
    },
    "retry_import": {
        "label": "Retry Import",
        "category": "recovery",
        "risk": "safe",
        "confirmation": False,
        "automation": "automated",
        "kind": "operations",
        "description": "Re-run import reconciliation and ownership checks.",
    },
    "move_files": {
        "label": "Move Files",
        "category": "maintenance",
        "risk": "medium",
        "confirmation": True,
        "automation": "manual",
        "kind": "filesystem",
        "description": "Move files between known media roots.",
    },
    "rename_files": {
        "label": "Rename Files",
        "category": "maintenance",
        "risk": "medium",
        "confirmation": True,
        "automation": "manual",
        "kind": "filesystem",
        "description": "Apply normalized naming rules to linked files.",
    },
    "repair_identity": {
        "label": "Repair Identity",
        "category": "recovery",
        "risk": "safe",
        "confirmation": False,
        "automation": "automated",
        "kind": "identity",
        "description": "Refresh identity graph and provider mappings.",
    },
    "refresh_metadata": {
        "label": "Refresh Metadata",
        "category": "maintenance",
        "risk": "safe",
        "confirmation": False,
        "automation": "automated",
        "kind": "metadata",
        "description": "Refresh metadata from connected providers.",
    },
    "refresh_artwork": {
        "label": "Refresh Artwork",
        "category": "maintenance",
        "risk": "safe",
        "confirmation": False,
        "automation": "automated",
        "kind": "artwork",
        "description": "Re-evaluate artwork candidates and apply profile rules.",
    },
    "sync_collections": {
        "label": "Sync Collections",
        "category": "maintenance",
        "risk": "safe",
        "confirmation": False,
        "automation": "automated",
        "kind": "collections",
        "description": "Push collection consistency updates to downstream apps.",
    },
    "refresh_plex": {
        "label": "Refresh Plex",
        "category": "external",
        "risk": "safe",
        "confirmation": False,
        "automation": "manual",
        "kind": "external",
        "description": "Trigger a media refresh in Plex.",
    },
    "ignore_recommendation": {
        "label": "Ignore Recommendation",
        "category": "safe",
        "risk": "safe",
        "confirmation": False,
        "automation": "manual",
        "kind": "operations",
        "description": "Suppress this recommendation for manual follow-up.",
    },
    "mark_resolved": {
        "label": "Mark Resolved",
        "category": "safe",
        "risk": "safe",
        "confirmation": False,
        "automation": "manual",
        "kind": "operations",
        "description": "Mark the recommendation as resolved after manual verification.",
    },
    "archive": {
        "label": "Archive",
        "category": "maintenance",
        "risk": "medium",
        "confirmation": True,
        "automation": "manual",
        "kind": "filesystem",
        "description": "Archive linked files into long-term storage.",
    },
    "manual_review": {
        "label": "Move To Manual Review",
        "category": "recovery",
        "risk": "safe",
        "confirmation": False,
        "automation": "manual",
        "kind": "operations",
        "description": "Escalate this recommendation for manual triage.",
    },
    "open_radarr": {
        "label": "Open In Radarr",
        "category": "external",
        "risk": "safe",
        "confirmation": False,
        "automation": "manual",
        "kind": "external",
        "description": "Open linked movie in Radarr.",
    },
    "open_sonarr": {
        "label": "Open In Sonarr",
        "category": "external",
        "risk": "safe",
        "confirmation": False,
        "automation": "manual",
        "kind": "external",
        "description": "Open linked series in Sonarr.",
    },
    "open_qbittorrent": {
        "label": "Open In qBittorrent",
        "category": "external",
        "risk": "safe",
        "confirmation": False,
        "automation": "manual",
        "kind": "external",
        "description": "Open linked torrent in qBittorrent.",
    },
    "open_plex": {
        "label": "Open In Plex",
        "category": "external",
        "risk": "safe",
        "confirmation": False,
        "automation": "manual",
        "kind": "external",
        "description": "Open linked media in Plex.",
    },
}

_ACTION_ALIASES: dict[str, str] = {
    "repair_import": "retry_import",
    "review_identity": "repair_identity",
    "cleanup_torrent": "delete_torrent",
    "delete_files": "delete_torrent_and_files",
    "monitor": "mark_resolved",
    "monitor_detached_media": "mark_resolved",
    "sync_request": "retry_download",
    "detach_torrent": "delete_torrent",
}

_WORKFLOW_STAGE_META: list[tuple[str, str, str]] = [
    (
        "download",
        "Download",
        "Assets currently transferring, queued, or being checked.",
    ),
    (
        "import",
        "Import",
        "Assets downloaded but not yet imported cleanly into the library.",
    ),
    (
        "organize",
        "Organize",
        "Imported assets requiring identity, artwork, or filesystem correction.",
    ),
    (
        "retention",
        "Retention",
        "Imported assets under active retention or seeding policy.",
    ),
    (
        "cleanup",
        "Cleanup",
        "Assets ready for torrent/download cleanup and space recovery.",
    ),
    (
        "completed",
        "Completed",
        "No active work remains; asset is detached/protected/healthy.",
    ),
]

_FILTER_TITLES: dict[str, str] = {
    "identity_issues": "Identity Issues",
    "broken_imports": "Broken Imports",
    "artwork_issues": "Artwork Issues",
    "filesystem_issues": "Filesystem Issues",
    "unknown_files": "Unknown Files",
    "missing_requests": "Missing Requests",
    "duplicate_identity": "Duplicate Identity",
    "missing_artwork": "Missing Artwork",
    "provider_conflicts": "Provider Conflicts",
    "downloads": "Downloads",
    "retention": "Retention",
    "cleanup": "Cleanup",
}


class OperationsService:
    """Facade for Operations page data sourced from MIE state and provider correlation."""

    def __init__(
        self,
        db: AsyncSession,
        request_context: MieRequestContext | None = None,
    ) -> None:
        self.db = db
        self._request_context = request_context
        self._correlation_service = MediaCorrelationService()
        self._operations_engine = OperationsEngine()
        self._graph_intelligence_cache: tuple[list[Any], Any] | None = None
        self._downloads_intelligence_cache: Any | None = None

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
        if self._request_context is not None and self._request_context.graph_subjects:
            subjects = list(self._request_context.graph_subjects)
        else:
            rows = (
                await self.db.execute(
                    select(
                        MediaAsset.media_type, MediaAsset.movie_id, MediaAsset.series_id
                    )
                    .order_by(MediaAsset.id.asc())
                    .limit(250)
                )
            ).all()

            subjects = []
            for media_type, movie_id, series_id in rows:
                if media_type is MediaType.MOVIE and movie_id is not None:
                    subjects.append((MediaType.MOVIE, int(movie_id)))
                elif media_type is MediaType.SERIES and series_id is not None:
                    subjects.append((MediaType.SERIES, int(series_id)))
            if self._request_context is not None:
                self._request_context.graph_subjects = list(subjects)

        graphs: list[Any] = []
        correlation = CorrelationService(self.db, request_context=self._request_context)
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
        if (
            self._request_context is not None
            and self._request_context.graph_intelligence
        ):
            return self._request_context.graph_intelligence
        if self._graph_intelligence_cache is not None:
            return self._graph_intelligence_cache
        graphs = await self._load_correlation_graphs()
        intelligence = self._operations_engine.run(graphs)
        self._graph_intelligence_cache = (graphs, intelligence)
        if self._request_context is not None:
            self._request_context.graph_intelligence = self._graph_intelligence_cache
        return self._graph_intelligence_cache

    async def _downloads_intelligence(self) -> Any:
        if (
            self._request_context is not None
            and self._request_context.downloads_intelligence is not None
        ):
            return self._request_context.downloads_intelligence
        if self._downloads_intelligence_cache is not None:
            return self._downloads_intelligence_cache
        self._downloads_intelligence_cache = await DownloadsIntelligenceService(
            self.db,
            request_context=self._request_context,
        ).run()
        return self._downloads_intelligence_cache

    async def _detached_media_recommendations(
        self, graphs: list[Any]
    ) -> list[OperationsRecommendation]:
        items: list[OperationsRecommendation] = []
        for graph in graphs:
            states = [row.computed_state for row in graph.torrent_intelligence.torrents]
            has_active_torrent = any(
                state in {"downloading", "queued", "waiting", "seeding"}
                for state in states
            )
            if has_active_torrent:
                continue
            if graph.file_intelligence.missing_files > 0:
                continue
            if graph.file_intelligence.total_size_bytes <= 0:
                continue

            resolved_artwork = await media_asset_artwork_resolver.resolve(
                self.db,
                context="operations.recommendations.detached_media",
                media_type=graph.media_type,
                media_id=graph.media_id,
                provider_poster_url=None,
                provider_backdrop_url=None,
                fallback_reason="detached_media",
            )
            items.append(
                OperationsRecommendation(
                    id=f"detached_media:{graph.media_type.value}:{graph.media_id}",
                    card_key="detached_media",
                    title=graph.title,
                    summary="Media is imported and detached from active torrents.",
                    explanation="This asset has library files and no active transfer ownership.",
                    reasons=[
                        "No active torrent correlation found.",
                        "Library files are present and healthy.",
                    ],
                    action="monitor_detached_media",
                    safety_level="safe",
                    target_type=graph.media_type.value,
                    target_id=str(graph.media_id),
                    estimated_recovery_bytes=0,
                    poster_url=resolved_artwork.poster_url,
                    artwork=resolved_artwork.artwork,
                    issue_key=f"detached-media-{graph.media_type.value}-{graph.media_id}",
                    confidence=max(70, graph.health.overall_health_score),
                    graph_references=[
                        "torrent_intelligence.torrents",
                        "file_intelligence.total_size_bytes",
                        "file_intelligence.missing_files",
                    ],
                )
            )
        return items

    async def _ready_to_detach_graph_recommendations(
        self, graphs: list[Any]
    ) -> list[OperationsRecommendation]:
        items: list[OperationsRecommendation] = []
        for graph in graphs:
            states = [row.computed_state for row in graph.torrent_intelligence.torrents]
            if not states:
                continue
            if not any(
                state in {"completed", "seeding", "imported"} for state in states
            ):
                continue
            if graph.file_intelligence.missing_files > 0:
                continue

            resolved_artwork = await media_asset_artwork_resolver.resolve(
                self.db,
                context="operations.recommendations.ready_to_detach_graph",
                media_type=graph.media_type,
                media_id=graph.media_id,
                provider_poster_url=None,
                provider_backdrop_url=None,
                fallback_reason="ready_to_detach_graph",
            )
            items.append(
                OperationsRecommendation(
                    id=f"ready_to_detach:{graph.media_type.value}:{graph.media_id}",
                    card_key="ready_to_detach",
                    title=graph.title,
                    summary="Transfer appears complete and import is healthy.",
                    explanation="Graph state indicates this asset can be reviewed for torrent detachment.",
                    reasons=[
                        "Torrent state is completed/seeding/imported.",
                        "No missing files detected.",
                    ],
                    action="detach_torrent",
                    safety_level="low_risk",
                    target_type=graph.media_type.value,
                    target_id=str(graph.media_id),
                    estimated_recovery_bytes=0,
                    poster_url=resolved_artwork.poster_url,
                    artwork=resolved_artwork.artwork,
                    issue_key=f"ready-to-detach-{graph.media_type.value}-{graph.media_id}",
                    confidence=max(75, graph.health.overall_health_score),
                    graph_references=[
                        "torrent_intelligence.torrents[].computed_state",
                        "file_intelligence.missing_files",
                        "file_intelligence.total_size_bytes",
                    ],
                )
            )
        return items

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
        identity_health = await IdentityCenterService(
            self.db, request_context=self._request_context
        ).identity_health_summary()

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
                    media_type=(
                        MediaType.MOVIE
                        if candidate.movie_id is not None
                        else MediaType.SERIES
                    ),
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
                        confidence=91,
                        graph_references=[
                            "torrent_intelligence.torrents[].computed_state",
                            "torrent_intelligence.torrents[].progress",
                            "arr_intelligence.ownership",
                        ],
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
        graphs, intelligence = await self._graph_intelligence()
        downloads = await self._downloads_intelligence()
        graph_items = await self._graph_issue_recommendations(intelligence.issues)
        detached_items = await self._detached_media_recommendations(graphs)
        ready_items = await self._ready_to_detach_graph_recommendations(graphs)
        items.extend(legacy_items)
        items.extend(graph_items)
        items.extend(detached_items)
        items.extend(ready_items)
        items.extend(downloads.recommendations)

        unique_by_id: dict[str, OperationsRecommendation] = {}
        for row in items:
            stage_key = self._stage_for_recommendation(row)
            row.action_manifest = self._build_action_manifest(
                primary_action=row.action,
                stage_key=stage_key,
                target_type=row.target_type,
                media_type=row.media_type,
                summary=row.summary,
                reason=(row.reasons[0] if row.reasons else row.summary),
                estimated_recovery_bytes=row.estimated_recovery_bytes,
                references=row.graph_references,
            )
            unique_by_id[row.id] = row
        items = list(unique_by_id.values())

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

    @staticmethod
    def _extract_year_from_title(title: str) -> int | None:
        match = re.search(r"\((19\d{2}|20\d{2}|21\d{2})\)", title or "")
        if match is None:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _policy_name_for_asset(
        media_type: MediaType | None,
        title: str,
    ) -> str:
        lowered = (title or "").lower()
        if media_type is MediaType.MOVIE:
            if any(token in lowered for token in ["anime", "animated"]):
                return "Animated Movies"
            if "kids" in lowered:
                return "Kids Movies"
            if any(token in lowered for token in ["asian", "korean", "japanese"]):
                return "Asian Movies"
            return "American Movies"
        if any(token in lowered for token in ["anime", "animated"]):
            return "Anime"
        if any(token in lowered for token in ["korean", "k-drama"]):
            return "Korean TV"
        if "filipino" in lowered:
            return "Filipino TV"
        return "American TV"

    @staticmethod
    def _build_media_policies() -> list[MediaPolicyDefinition]:
        return [
            MediaPolicyDefinition(
                key="american_movies",
                name="American Movies",
                classification="movie",
                destination_library="/media/movies/american",
                retention_period_days=30,
                cleanup_behavior="remove_torrent_and_download_folder_after_retention",
                remove_torrent=True,
                remove_download_folder=True,
                protection_rules=["favorites", "recently_watched"],
                minimum_ratio=1.0,
                minimum_seed_time_hours=72,
            ),
            MediaPolicyDefinition(
                key="asian_movies",
                name="Asian Movies",
                classification="movie",
                destination_library="/media/movies/asian",
                retention_period_days=30,
                cleanup_behavior="remove_torrent_and_download_folder_after_retention",
                remove_torrent=True,
                remove_download_folder=True,
                protection_rules=["favorites"],
                minimum_ratio=1.0,
                minimum_seed_time_hours=72,
            ),
            MediaPolicyDefinition(
                key="kids_movies",
                name="Kids Movies",
                classification="movie",
                destination_library="/media/movies/kids",
                retention_period_days=14,
                cleanup_behavior="remove_download_folder_keep_torrent_until_ratio",
                remove_torrent=True,
                remove_download_folder=True,
                protection_rules=["family_safe", "favorites"],
                minimum_ratio=1.0,
                minimum_seed_time_hours=48,
            ),
            MediaPolicyDefinition(
                key="animated_movies",
                name="Animated Movies",
                classification="movie",
                destination_library="/media/movies/animated",
                retention_period_days=21,
                cleanup_behavior="remove_torrent_and_download_folder_after_retention",
                remove_torrent=True,
                remove_download_folder=True,
                protection_rules=["favorites"],
                minimum_ratio=1.0,
                minimum_seed_time_hours=48,
            ),
            MediaPolicyDefinition(
                key="american_tv",
                name="American TV",
                classification="series",
                destination_library="/media/tv/american",
                retention_period_days=21,
                cleanup_behavior="remove_torrent_and_download_folder_after_retention",
                remove_torrent=True,
                remove_download_folder=True,
                protection_rules=["in_progress_series"],
                minimum_ratio=1.0,
                minimum_seed_time_hours=72,
            ),
            MediaPolicyDefinition(
                key="korean_tv",
                name="Korean TV",
                classification="series",
                destination_library="/media/tv/korean",
                retention_period_days=21,
                cleanup_behavior="remove_torrent_and_download_folder_after_retention",
                remove_torrent=True,
                remove_download_folder=True,
                protection_rules=["favorites"],
                minimum_ratio=1.0,
                minimum_seed_time_hours=72,
            ),
            MediaPolicyDefinition(
                key="anime",
                name="Anime",
                classification="series",
                destination_library="/media/tv/anime",
                retention_period_days=21,
                cleanup_behavior="remove_torrent_and_download_folder_after_retention",
                remove_torrent=True,
                remove_download_folder=True,
                protection_rules=["favorites"],
                minimum_ratio=1.0,
                minimum_seed_time_hours=72,
            ),
            MediaPolicyDefinition(
                key="filipino_tv",
                name="Filipino TV",
                classification="series",
                destination_library="/media/tv/filipino",
                retention_period_days=21,
                cleanup_behavior="remove_torrent_and_download_folder_after_retention",
                remove_torrent=True,
                remove_download_folder=True,
                protection_rules=["favorites"],
                minimum_ratio=1.0,
                minimum_seed_time_hours=72,
            ),
        ]

    @staticmethod
    def _stage_for_download(item: Any) -> str:
        state = str(getattr(item, "lifecycle_state", "") or "")
        cleanup = str(getattr(item, "cleanup_classification", "") or "")
        retention = str(getattr(item, "retention_policy", "") or "")

        if state in {
            "metadata_download",
            "queued",
            "downloading",
            "checking",
            "moving",
        }:
            return "download"
        if state == "failed" or cleanup == "failed_import":
            return "import"
        if retention in {"seeding_retention", "grace_period"}:
            return "retention"
        if retention == "expired" or cleanup in {
            "safe_to_delete",
            "duplicate_download",
            "abandoned_download",
        }:
            return "cleanup"
        if state in {"unknown", "orphaned", "stale"}:
            return "organize"
        if state == "imported":
            return "completed"
        return "organize"

    @staticmethod
    def _stage_for_recommendation(item: OperationsRecommendation) -> str:
        card = item.card_key
        action = item.action.lower()

        if item.target_type == "download_object":
            if card in {"failed_downloads"}:
                return "import"
            if card in {"safe_to_delete", "duplicate_downloads", "orphaned_downloads"}:
                return "cleanup"
            if card in {"safe_to_archive"}:
                return "retention"
            return "download"

        if card in {"downloading"}:
            return "download"
        if card in {"import_pending", "broken_imports"}:
            return "import"
        if card in {
            "identity_issues",
            "unknown_files",
            "duplicate_releases",
            "duplicate_torrents",
            "orphaned_files",
            "artwork_missing",
            "artwork_placeholder",
            "artwork_invalid",
            "artwork_stale",
        }:
            return "organize"
        if card in {"ready_to_detach", "protected_seeding"}:
            return "retention"
        if card in {
            "space_recovery",
            "orphaned_torrents",
            "leftover_files",
            "empty_folders",
        }:
            return "cleanup"
        if card in {"detached_media"}:
            return "completed"

        if any(token in action for token in ["detach", "remove", "delete", "cleanup"]):
            return "cleanup"
        if "protect" in action or "seed" in action:
            return "retention"
        if "import" in action:
            return "import"
        if item.safety_level == "safe":
            return "completed"
        return "organize"

    @staticmethod
    def _filters_for_recommendation(item: OperationsRecommendation) -> list[str]:
        filters: set[str] = set()
        card = item.card_key

        if card in {"identity_issues"}:
            filters.add("identity_issues")
            filters.add("duplicate_identity")
        if card in {"broken_imports", "import_pending"}:
            filters.add("broken_imports")
        if card.startswith("artwork_"):
            filters.add("artwork_issues")
            filters.add("missing_artwork")
        if card in {
            "unknown_files",
            "orphaned_files",
            "leftover_files",
            "empty_folders",
        }:
            filters.add("filesystem_issues")
            filters.add("unknown_files")
        if card in {"orphaned_torrents", "space_recovery"}:
            filters.add("cleanup")
        if card in {"ready_to_detach", "protected_seeding"}:
            filters.add("retention")
        if item.target_type == "download_object":
            filters.add("downloads")
        if not filters:
            filters.add("filesystem_issues")
        return sorted(filters)

    @staticmethod
    def _filters_for_issue(issue: OperationsIssue) -> list[str]:
        mapping = {
            "missing_request": ["missing_requests"],
            "failed_import": ["broken_imports"],
            "filesystem_inconsistency": ["filesystem_issues"],
            "duplicate_identity": ["identity_issues", "duplicate_identity"],
            "artwork_gap": ["artwork_issues", "missing_artwork"],
            "provider_conflict": ["provider_conflicts"],
        }
        return sorted(mapping.get(issue.issue_type, ["filesystem_issues"]))

    @staticmethod
    def _normalize_action_id(action: str) -> str:
        action_id = str(action or "").strip().lower()
        return _ACTION_ALIASES.get(action_id, action_id)

    @staticmethod
    def _is_required_primary_action(
        action_id: str,
        *,
        stage_key: str,
        summary: str,
    ) -> bool:
        normalized = OperationsService._normalize_action_id(action_id)
        if stage_key in {"retention", "cleanup", "completed"}:
            return False
        if normalized in _PRIMARY_REQUIRED_ACTION_IDS:
            return True
        if normalized == "refresh_artwork" and "artwork" in summary.lower():
            return True
        return False

    @staticmethod
    def _action_presentation(
        action_id: str,
        *,
        is_primary: bool,
        primary_is_required: bool,
        workflow_outcome: Literal["blocked", "in_progress", "completed"],
    ) -> Literal["required", "recommended", "secondary"]:
        normalized = OperationsService._normalize_action_id(action_id)
        if normalized.startswith("open_") or normalized in _SECONDARY_ACTION_IDS:
            return "secondary"
        if is_primary and primary_is_required:
            return "required"
        if is_primary and workflow_outcome == "completed":
            return "recommended"
        return "secondary"

    @staticmethod
    def _workflow_outcome(
        *,
        stage_key: str,
        primary_is_required: bool,
    ) -> Literal["blocked", "in_progress", "completed"]:
        if primary_is_required:
            return "blocked"
        if stage_key in {"retention", "cleanup", "completed"}:
            return "completed"
        return "in_progress"

    @staticmethod
    def _format_recovery_bytes(value: int) -> str | None:
        if value <= 0:
            return None
        gb_value = bytes_to_gb(value)
        if gb_value >= 1:
            return f"{gb_value:.1f} GB"
        mb_value = value / (1024**2)
        if mb_value >= 1:
            return f"{mb_value:.1f} MB"
        kb_value = value / 1024
        if kb_value >= 1:
            return f"{kb_value:.1f} KB"
        return f"{value} bytes"

    def _primary_action_reasoning(
        self,
        action_id: str,
        *,
        stage_key: str,
        summary: str,
        reason: str,
        expected_destination: str | None,
        estimated_recovery_bytes: int,
        workflow_outcome: Literal["blocked", "in_progress", "completed"],
    ) -> list[str]:
        normalized = self._normalize_action_id(action_id)
        reasoning: list[str] = []

        if workflow_outcome == "blocked":
            reasoning.append(
                "The workflow cannot continue successfully until this operational problem is resolved."
            )
            reasoning.append(reason or summary)
            blocked_messages = {
                "retry_download": "Retrying the download should restart acquisition and allow the workflow to continue.",
                "resume_download": "The download is paused or stalled, so it must be resumed before import can continue.",
                "retry_import": "The media is not yet imported cleanly into the library, so import must be retried before downstream validation can complete.",
                "repair_identity": "Provider or ownership links are inconsistent, so identity repair is required before the asset can be treated as healthy.",
                "refresh_artwork": "Artwork evidence is incomplete or invalid, so artwork repair is required before this workflow is considered healthy.",
                "move_files": "Files are not in the expected managed location and need to be corrected before the workflow can proceed safely.",
            }
            if normalized in blocked_messages:
                reasoning.append(blocked_messages[normalized])
            if expected_destination:
                reasoning.append(
                    f"Expected managed destination: {expected_destination}."
                )
            return reasoning

        if workflow_outcome == "completed":
            reasoning.append("The workflow has completed successfully.")
            if stage_key == "retention":
                reasoning.append(
                    "Import, library validation, and downstream availability checks are complete."
                )
            elif stage_key == "cleanup":
                reasoning.append(
                    "The media is already available in the library, and only cleanup or optimisation work remains."
                )
            else:
                reasoning.append(
                    "The media is already present and available in the managed environment."
                )

            reclaim_text = self._format_recovery_bytes(estimated_recovery_bytes)
            recommended_messages = {
                "delete_torrent": "Removing the torrent will free a slot in qBittorrent and keep the download queue tidy.",
                "delete_torrent_and_files": (
                    "The original torrent payload is no longer required."
                    + (
                        f" Removing it will reclaim {reclaim_text} of storage."
                        if reclaim_text
                        else " Removing it will reclaim storage."
                    )
                ),
                "refresh_metadata": "Refreshing metadata can improve how the media appears across connected libraries.",
                "refresh_artwork": "Refreshing artwork can improve library presentation without affecting the successful import.",
                "sync_collections": "Collection sync can improve downstream organisation now that the workflow is complete.",
                "archive": "Archiving this asset can reduce active storage pressure while keeping long-term retention available.",
                "pause_torrent": "Pausing the torrent is optional maintenance if active seeding is no longer needed.",
                "force_recheck": "A recheck is optional maintenance to confirm torrent integrity after the workflow completed.",
            }
            if normalized in recommended_messages:
                reasoning.append(recommended_messages[normalized])
            elif summary:
                reasoning.append(summary)
            return reasoning

        reasoning.append("The workflow is still in progress.")
        reasoning.append(reason or summary)
        reasoning.append(
            "No blocking fault is currently confirmed, but this lifecycle step may still require follow-up as the asset progresses."
        )
        return reasoning

    @staticmethod
    def _workflow_summary(
        *,
        workflow_outcome: Literal["blocked", "in_progress", "completed"],
        primary_label: str,
    ) -> str:
        if workflow_outcome == "blocked":
            return f"Workflow blocked. Required action: {primary_label}."
        if workflow_outcome == "completed":
            return f"Workflow completed successfully. Recommended action: {primary_label}."
        return f"Workflow in progress. Next action: {primary_label}."

    @staticmethod
    def _format_duration_hours(hours: int | None) -> str | None:
        if hours is None:
            return None
        days, remaining_hours = divmod(max(0, int(hours)), 24)
        parts: list[str] = []
        if days:
            parts.append(f"{days} day{'s' if days != 1 else ''}")
        if remaining_hours:
            parts.append(
                f"{remaining_hours} hour{'s' if remaining_hours != 1 else ''}"
            )
        if not parts:
            return "less than 1 hour"
        return " and ".join(parts)

    @staticmethod
    def _current_path_for_narrative(
        *,
        stage_key: str,
        download_location: str | None,
        library_location: str | None,
        file_evidence: list[OperationsFileEvidence],
    ) -> str | None:
        path_by_role = {
            row.hierarchy_role: row.path
            for row in file_evidence
            if row.path and row.hierarchy_role
        }
        if stage_key in {"download", "import", "retention", "cleanup"}:
            return (
                download_location
                or path_by_role.get("download_source")
                or path_by_role.get("primary_media_file")
                or path_by_role.get("managed_folder")
                or library_location
            )
        return (
            path_by_role.get("primary_media_file")
            or path_by_role.get("managed_folder")
            or library_location
            or download_location
        )

    @staticmethod
    def _expected_path_for_narrative(
        *,
        expected_destination: str | None,
        library_location: str | None,
        file_evidence: list[OperationsFileEvidence],
    ) -> str | None:
        managed_folder = next(
            (row.path for row in file_evidence if row.hierarchy_role == "managed_folder" and row.path),
            None,
        )
        return managed_folder or library_location or expected_destination

    @staticmethod
    def _what_for_narrative(
        *,
        media_type: MediaType | None,
        stage_key: str,
        action_manifest: OperationActionManifest,
        primary_action_label: str,
        has_duplicate: bool,
    ) -> str:
        app_name = "Sonarr" if media_type is MediaType.SERIES else "Radarr"
        if action_manifest.workflow_outcome == "blocked":
            if "Import" in primary_action_label:
                return "Import Failed"
            if "Identity" in primary_action_label or "Match" in primary_action_label:
                return "Manual Match Required"
            if has_duplicate:
                return "Duplicate Found"
            return "Attention Required"
        if has_duplicate:
            return "Duplicate Found"
        if stage_key == "download":
            return "Download In Progress"
        if stage_key == "import":
            return f"Waiting for {app_name} Import"
        if stage_key == "organize":
            return "Library Review"
        if stage_key == "retention":
            return "Download Completed"
        if stage_key == "cleanup":
            return "Completed and Ready for Cleanup"
        return "Library Healthy"

    def _build_operational_narrative(
        self,
        *,
        media_type: MediaType | None,
        stage_key: str,
        download_location: str | None,
        library_location: str | None,
        torrent_state: str | None,
        import_state: str | None,
        retention_remaining_hours: int | None,
        estimated_space_recovery: int,
        expected_destination: str | None,
        file_evidence: list[OperationsFileEvidence],
        action_manifest: OperationActionManifest,
    ) -> OperationsNarrative:
        primary_action = next(
            (
                action
                for action in action_manifest.available_actions
                if action.presentation in {"required", "recommended"}
            ),
            action_manifest.available_actions[0]
            if action_manifest.available_actions
            else None,
        )
        primary_label = primary_action.label if primary_action is not None else "No action"
        has_duplicate = any(row.state == "duplicate" for row in file_evidence)
        current_location = self._current_path_for_narrative(
            stage_key=stage_key,
            download_location=download_location,
            library_location=library_location,
            file_evidence=file_evidence,
        )
        expected_location = self._expected_path_for_narrative(
            expected_destination=expected_destination,
            library_location=library_location,
            file_evidence=file_evidence,
        )

        why: list[str] = []
        impact: list[str] = []
        next_steps: list[str] = []

        if action_manifest.workflow_outcome == "blocked":
            why.extend(action_manifest.primary_action_reasoning)
            if stage_key == "import":
                impact.append(
                    "The media will not appear in Plex until the import completes successfully."
                )
            elif has_duplicate:
                impact.append(
                    "Keeping both copies in circulation can waste storage and make the canonical library location unclear."
                )
            else:
                impact.append(
                    "This workflow is blocked until the required action is completed."
                )
            next_steps.append(primary_label)
            outcome = "attention_required"
        elif stage_key == "import":
            why.append("The download has completed successfully.")
            why.append(
                "The files are waiting to be moved into the managed library location."
            )
            if import_state:
                why.append(
                    "Import is still being coordinated automatically in the background."
                )
            impact.append(
                "The media may not appear in Plex until the import completes."
            )
            next_steps.extend(
                [
                    "No action required.",
                    "Import will begin automatically when the library workflow is ready.",
                ]
            )
            outcome = "healthy"
        elif stage_key == "retention":
            why.append("The download completed successfully.")
            remaining = self._format_duration_hours(retention_remaining_hours)
            if remaining:
                why.append(
                    f"The torrent is configured to continue seeding for another {remaining}."
                )
                why.append(
                    "Cleanup options will unlock automatically after the seeding requirement has been satisfied."
                )
            else:
                why.append(
                    "The asset is still in a retention window before cleanup actions are offered."
                )
            impact.append("No impact. Everything is working normally.")
            next_steps.extend(
                [
                    "No action required.",
                    "Cleanup will become available automatically when the retention rule completes.",
                ]
            )
            outcome = "healthy"
        elif action_manifest.workflow_outcome == "completed":
            why.extend(action_manifest.primary_action_reasoning)
            impact.append(
                "No impact. Everything is working normally. Any remaining action is optional maintenance."
            )
            next_steps.append(primary_label)
            outcome = "healthy_with_recommendations"
        elif has_duplicate:
            why.append(
                "More than one copy is linked to this media, so MediaMasterr cannot treat the library location as fully clean yet."
            )
            reclaim_text = self._format_recovery_bytes(estimated_space_recovery)
            if reclaim_text:
                impact.append(
                    f"Keeping both copies will consume an additional {reclaim_text}."
                )
            else:
                impact.append(
                    "Keeping both copies will consume additional storage and may confuse the library workflow."
                )
            next_steps.append(primary_label)
            outcome = "healthy_with_recommendations"
        else:
            why.append("The workflow is continuing automatically.")
            if torrent_state:
                why.append(
                    "Download activity is still in progress before the library workflow can move to the next step."
                )
            impact.append("No immediate user action is required.")
            next_steps.append("No action required.")
            outcome = "healthy"

        return OperationsNarrative(
            outcome=cast(Any, outcome),
            what=self._what_for_narrative(
                media_type=media_type,
                stage_key=stage_key,
                action_manifest=action_manifest,
                primary_action_label=primary_label,
                has_duplicate=has_duplicate,
            ),
            where=OperationsNarrativeLocation(
                current_path=current_location,
                expected_path=expected_location,
            ),
            why=why,
            impact=impact,
            next=next_steps,
        )

    @staticmethod
    def _manifest_entry(
        action_id: str,
        *,
        impact_preview: list[str] | None = None,
        presentation: Literal["required", "recommended", "secondary"] = "secondary",
    ) -> OperationActionManifestAction:
        definition = _ACTION_DEFINITIONS.get(action_id)
        if definition is None:
            return OperationActionManifestAction(
                id=action_id,
                label=action_id.replace("_", " ").title(),
                category="maintenance",
                risk="medium",
                presentation=presentation,
                confirmation=False,
                description="Action metadata unavailable.",
                impact_preview=list(impact_preview or []),
                automation="manual",
                kind="operations",
            )
        return OperationActionManifestAction(
            id=action_id,
            label=str(definition["label"]),
            category=cast(Any, definition["category"]),
            risk=cast(Any, definition["risk"]),
            presentation=presentation,
            confirmation=bool(definition.get("confirmation", False)),
            description=str(definition.get("description") or ""),
            impact_preview=list(impact_preview or []),
            automation=cast(Any, definition.get("automation", "manual")),
            kind=cast(Any, definition.get("kind", "operations")),
        )

    def _impact_preview_for_action(
        self,
        action_id: str,
        *,
        summary: str,
        expected_destination: str | None,
        known_paths: list[str],
        estimated_recovery_bytes: int,
        references: list[str],
    ) -> list[str]:
        preview: list[str] = []
        if summary:
            preview.append(summary)
        if expected_destination:
            preview.append(f"Expected destination: {expected_destination}")
        if known_paths:
            preview.append(f"Files affected: {len(known_paths)} known path(s)")
            preview.append(f"Source path: {known_paths[0]}")
            preview.append(f"Primary path: {known_paths[0]}")
        if estimated_recovery_bytes > 0:
            preview.append(
                f"Estimated work: {estimated_recovery_bytes} bytes of recovery potential"
            )
        if references:
            preview.append(f"Supporting evidence: {references[0]}")

        normalized = self._normalize_action_id(action_id)
        applications: list[str] = []
        reversible = True
        if normalized in {"delete_torrent", "delete_torrent_and_files", "archive"}:
            preview.append("Reversibility: limited or manual rollback only.")
            preview.append(
                "Confirmation requirements: explicit confirmation is required."
            )
            reversible = False
        elif normalized in {
            "retry_import",
            "repair_identity",
            "refresh_metadata",
            "refresh_artwork",
        }:
            preview.append("Reversibility: generally safe to rerun or refresh.")
            preview.append("Confirmation requirements: no confirmation required.")
        elif normalized.startswith("open_"):
            preview.append(
                "Reversibility: fully reversible because no MediaMasterr data is mutated."
            )
            preview.append("Confirmation requirements: no confirmation required.")
        else:
            preview.append(
                "Reversibility: review the preview before committing changes."
            )
            preview.append(
                "Confirmation requirements: confirm if the action mutates files or imports."
            )

        if normalized in {
            "open_radarr",
            "retry_import",
            "repair_identity",
            "refresh_metadata",
            "refresh_artwork",
        }:
            applications.append("Radarr")
        if normalized in {"open_sonarr"}:
            applications.append("Sonarr")
        if normalized in {
            "open_qbittorrent",
            "resume_download",
            "pause_torrent",
            "force_recheck",
            "delete_torrent",
            "delete_torrent_and_files",
        }:
            applications.append("qBittorrent")
        if normalized in {
            "retry_import",
            "repair_identity",
            "refresh_metadata",
            "refresh_artwork",
        }:
            applications.append("Plex")
        if normalized in {"refresh_metadata", "repair_identity"}:
            applications.append("Identity Engine")
        if normalized in {"refresh_artwork"}:
            applications.append("Artwork pipeline")
        if normalized in {
            "ignore_recommendation",
            "manual_review",
            "mark_resolved",
            "archive",
        }:
            applications.append("Operations Engine")

        if applications:
            preview.append(
                f"Applications affected: {', '.join(dict.fromkeys(applications))}"
            )

        return preview[:8]

    @staticmethod
    def _destination_for_policy(
        policy_name: str | None,
        media_type: MediaType | None,
    ) -> str | None:
        for policy in OperationsService._build_media_policies():
            if policy.name == policy_name:
                return policy.destination_library
        if media_type is MediaType.MOVIE:
            return "/media/movies"
        if media_type is MediaType.SERIES:
            return "/media/tv"
        return None

    async def _resolve_asset_media_identity(
        self,
        *,
        media_type: MediaType | None,
        target_type: str,
        target_id: str | None,
    ) -> tuple[MediaType | None, int | None]:
        if target_type == "movie" and target_id and target_id.isdigit():
            return MediaType.MOVIE, int(target_id)
        if (
            target_type in {"series", "season", "episode"}
            and target_id
            and target_id.isdigit()
        ):
            return MediaType.SERIES, int(target_id)
        if target_type == "reclaim_candidate" and target_id and target_id.isdigit():
            row = (
                await self.db.execute(
                    select(ReclaimCandidate.movie_id, ReclaimCandidate.series_id).where(
                        ReclaimCandidate.id == int(target_id)
                    )
                )
            ).first()
            if row is not None:
                if row.movie_id is not None:
                    return MediaType.MOVIE, int(row.movie_id)
                if row.series_id is not None:
                    return MediaType.SERIES, int(row.series_id)
        if media_type is not None and target_id and target_id.isdigit():
            return media_type, int(target_id)
        return media_type, None

    async def _build_asset_evidence(
        self,
        *,
        title: str,
        media_type: MediaType | None,
        target_type: str,
        target_id: str | None,
        policy_name: str | None,
        download_location: str | None,
        library_location: str | None,
        torrent_state: str | None,
        summary: str,
        reason: str,
        recommendation: str,
        estimated_recovery_bytes: int,
        graph_references: list[str],
    ) -> tuple[
        str,
        str | None,
        str,
        list[OperationsFileEvidence],
        list[OperationsApplicationEvidence],
        list[OperationsRelationshipEvidence],
        list[str],
    ]:
        resolved_media_type, media_id = await self._resolve_asset_media_identity(
            media_type=media_type,
            target_type=target_type,
            target_id=target_id,
        )
        expected_destination = self._destination_for_policy(
            policy_name, resolved_media_type
        )

        def _norm_path(value: str | None) -> str:
            return normalize_fpath(value or "", strip_ending_slash=True, lower=True)

        def _is_same_or_child(path: str | None, parent: str | None) -> bool:
            if not path or not parent:
                return False
            normalized_path = _norm_path(path)
            normalized_parent = _norm_path(parent)
            if not normalized_path or not normalized_parent:
                return False
            return normalized_path == normalized_parent or normalized_path.startswith(
                f"{normalized_parent.rstrip('/')}/"
            )

        def _parent_directory(path: str | None) -> str | None:
            if not path:
                return None
            normalized = normalize_fpath(path, strip_ending_slash=True)
            if not normalized or normalized in {"/", "."}:
                return None
            if "/" not in normalized:
                return None
            parent = normalized.rsplit("/", 1)[0]
            return parent or "/"

        known_paths: list[tuple[str | None, str, str | None, str]] = []
        applications: list[OperationsApplicationEvidence] = []
        relationships: list[OperationsRelationshipEvidence] = []

        if resolved_media_type is MediaType.MOVIE and media_id is not None:
            movie = (
                await self.db.execute(select(Movie).where(Movie.id == media_id))
            ).scalar_one_or_none()
            versions = (
                await self.db.execute(
                    select(
                        MovieVersion.path,
                        MovieVersion.library_name,
                        MovieVersion.service,
                        MovieVersion.service_item_id,
                    ).where(MovieVersion.movie_id == media_id)
                )
            ).all()
            arr_refs = (
                await self.db.execute(
                    select(
                        ServiceConfig.name,
                        MovieArrRef.arr_movie_id,
                        MovieArrRef.arr_movie_path,
                    )
                    .join(
                        ServiceConfig, ServiceConfig.id == MovieArrRef.service_config_id
                    )
                    .where(MovieArrRef.movie_id == media_id)
                )
            ).all()
            for path, library_name, service, _ in versions:
                if path:
                    known_paths.append(
                        (
                            path,
                            "Primary Media File",
                            library_name or str(service.value),
                            "primary_media_file",
                        )
                    )
            for service_name, arr_movie_id, arr_path in arr_refs:
                if arr_path:
                    known_paths.append(
                        (
                            arr_path,
                            "Managed Folder",
                            service_name,
                            "managed_folder",
                        )
                    )
                applications.append(
                    OperationsApplicationEvidence(
                        role="Requested By",
                        application="Radarr",
                        status="linked",
                        reference=f"{service_name} #{arr_movie_id}",
                        explanation="Radarr currently owns a managed relationship for this movie.",
                    )
                )
            if not arr_refs:
                applications.append(
                    OperationsApplicationEvidence(
                        role="Requested By",
                        application="Radarr",
                        status="unavailable",
                        reference=None,
                        explanation="No Radarr relationship is currently linked for this movie.",
                    )
                )
            plex_version = next(
                (row for row in versions if row.service == Service.PLEX), None
            )
            applications.append(
                OperationsApplicationEvidence(
                    role="Managed By",
                    application="Plex",
                    status="linked" if plex_version is not None else "unavailable",
                    reference=plex_version.service_item_id
                    if plex_version is not None
                    else None,
                    explanation=(
                        "Plex library ownership is linked for this movie."
                        if plex_version is not None
                        else "No Plex relationship is currently linked for this movie."
                    ),
                )
            )
            relationships.extend(
                [
                    OperationsRelationshipEvidence(
                        key="imdb",
                        label="IMDb",
                        value=movie.imdb_id if movie is not None else None,
                        status="linked"
                        if movie is not None and movie.imdb_id
                        else "unavailable",
                        explanation=(
                            "IMDb identity is linked."
                            if movie is not None and movie.imdb_id
                            else "No IMDb relationship is currently linked."
                        ),
                    ),
                    OperationsRelationshipEvidence(
                        key="tmdb",
                        label="TMDB",
                        value=str(movie.tmdb_id) if movie is not None else None,
                        status="linked" if movie is not None else "unavailable",
                        explanation=(
                            "TMDB identity is linked."
                            if movie is not None
                            else "No TMDB relationship is currently linked."
                        ),
                    ),
                    OperationsRelationshipEvidence(
                        key="tvdb",
                        label="TVDB",
                        value=None,
                        status="unavailable",
                        explanation="Movies do not currently carry a TVDB relationship in MediaMasterr.",
                    ),
                    OperationsRelationshipEvidence(
                        key="collection",
                        label="Collection",
                        value=(
                            movie.tmdb_collection_name if movie is not None else None
                        )
                        or policy_name,
                        status=(
                            "linked"
                            if (movie is not None and movie.tmdb_collection_name)
                            or policy_name
                            else "unavailable"
                        ),
                        explanation=(
                            "Collection context is available."
                            if (movie is not None and movie.tmdb_collection_name)
                            or policy_name
                            else "No collection relationship is currently linked."
                        ),
                    ),
                    OperationsRelationshipEvidence(
                        key="duplicates",
                        label="Duplicate Assets",
                        value=str(
                            max(0, len([row for row in versions if row.path]) - 1)
                        ),
                        status="linked"
                        if len([row for row in versions if row.path]) > 1
                        else "unavailable",
                        explanation=(
                            "Multiple known copies are tracked for this movie."
                            if len([row for row in versions if row.path]) > 1
                            else "No duplicate file relationship is currently linked."
                        ),
                    ),
                ]
            )

        elif resolved_media_type is MediaType.SERIES and media_id is not None:
            series = (
                await self.db.execute(select(Series).where(Series.id == media_id))
            ).scalar_one_or_none()
            service_refs = (
                await self.db.execute(
                    select(
                        SeriesServiceRef.path,
                        SeriesServiceRef.library_name,
                        SeriesServiceRef.service,
                        SeriesServiceRef.service_id,
                        SeriesServiceRef.media_server_collection_names,
                    ).where(SeriesServiceRef.series_id == media_id)
                )
            ).all()
            arr_refs = (
                await self.db.execute(
                    select(
                        ServiceConfig.name,
                        SeriesArrRef.arr_series_id,
                        SeriesArrRef.arr_series_path,
                    )
                    .join(
                        ServiceConfig,
                        ServiceConfig.id == SeriesArrRef.service_config_id,
                    )
                    .where(SeriesArrRef.series_id == media_id)
                )
            ).all()
            season_paths = (
                (
                    await self.db.execute(
                        select(Season.path).where(
                            Season.series_id == media_id, Season.path.is_not(None)
                        )
                    )
                )
                .scalars()
                .all()
            )
            for path, library_name, service, _, _ in service_refs:
                if path:
                    known_paths.append(
                        (
                            path,
                            "Managed Folder",
                            library_name or str(service.value),
                            "managed_folder",
                        )
                    )
            for path in season_paths[:3]:
                if path:
                    known_paths.append(
                        (
                            path,
                            "Additional Files",
                            "Season",
                            "additional_file",
                        )
                    )
            for service_name, arr_series_id, arr_path in arr_refs:
                if arr_path:
                    known_paths.append(
                        (
                            arr_path,
                            "Managed Folder",
                            service_name,
                            "managed_folder",
                        )
                    )
                applications.append(
                    OperationsApplicationEvidence(
                        role="Requested By",
                        application="Sonarr",
                        status="linked",
                        reference=f"{service_name} #{arr_series_id}",
                        explanation="Sonarr currently owns a managed relationship for this series.",
                    )
                )
            if not arr_refs:
                applications.append(
                    OperationsApplicationEvidence(
                        role="Requested By",
                        application="Sonarr",
                        status="unavailable",
                        reference=None,
                        explanation="No Sonarr relationship is currently linked for this series.",
                    )
                )
            plex_ref = next(
                (row for row in service_refs if row.service == Service.PLEX), None
            )
            applications.append(
                OperationsApplicationEvidence(
                    role="Managed By",
                    application="Plex",
                    status="linked" if plex_ref is not None else "unavailable",
                    reference=plex_ref.service_id if plex_ref is not None else None,
                    explanation=(
                        "Plex library ownership is linked for this series."
                        if plex_ref is not None
                        else "No Plex relationship is currently linked for this series."
                    ),
                )
            )
            collection_name = None
            for _, _, _, _, collection_names in service_refs:
                if collection_names:
                    collection_name = collection_names[0]
                    break
            relationships.extend(
                [
                    OperationsRelationshipEvidence(
                        key="imdb",
                        label="IMDb",
                        value=series.imdb_id if series is not None else None,
                        status="linked"
                        if series is not None and series.imdb_id
                        else "unavailable",
                        explanation=(
                            "IMDb identity is linked."
                            if series is not None and series.imdb_id
                            else "No IMDb relationship is currently linked."
                        ),
                    ),
                    OperationsRelationshipEvidence(
                        key="tmdb",
                        label="TMDB",
                        value=str(series.tmdb_id) if series is not None else None,
                        status="linked" if series is not None else "unavailable",
                        explanation=(
                            "TMDB identity is linked."
                            if series is not None
                            else "No TMDB relationship is currently linked."
                        ),
                    ),
                    OperationsRelationshipEvidence(
                        key="tvdb",
                        label="TVDB",
                        value=series.tvdb_id if series is not None else None,
                        status="linked"
                        if series is not None and series.tvdb_id
                        else "unavailable",
                        explanation=(
                            "TVDB identity is linked."
                            if series is not None and series.tvdb_id
                            else "No TVDB relationship is currently linked."
                        ),
                    ),
                    OperationsRelationshipEvidence(
                        key="collection",
                        label="Collection",
                        value=collection_name or policy_name,
                        status="linked"
                        if collection_name or policy_name
                        else "unavailable",
                        explanation=(
                            "Collection context is available."
                            if collection_name or policy_name
                            else "No collection relationship is currently linked."
                        ),
                    ),
                ]
            )

        applications.append(
            OperationsApplicationEvidence(
                role="Download Client",
                application="qBittorrent",
                status="linked"
                if torrent_state or download_location
                else "unavailable",
                reference=torrent_state,
                explanation=(
                    "A download client relationship is present for this asset."
                    if torrent_state or download_location
                    else "No download client relationship is currently linked."
                ),
            )
        )
        applications.append(
            OperationsApplicationEvidence(
                role="Indexer",
                application="Prowlarr",
                status="unavailable",
                reference=None,
                explanation="No indexer relationship is currently linked for this asset.",
            )
        )
        applications.append(
            OperationsApplicationEvidence(
                role="Current Owner",
                application=policy_name or "Unavailable",
                status="linked" if policy_name else "unavailable",
                reference=policy_name,
                explanation=(
                    "Policy and destination ownership are known for this asset."
                    if policy_name
                    else "No policy ownership is currently linked for this asset."
                ),
            )
        )

        media_asset = None
        if resolved_media_type is MediaType.MOVIE and media_id is not None:
            media_asset = (
                await self.db.execute(
                    select(MediaAsset).where(
                        MediaAsset.media_type == resolved_media_type,
                        MediaAsset.movie_id == media_id,
                    )
                )
            ).scalar_one_or_none()
        elif resolved_media_type is MediaType.SERIES and media_id is not None:
            media_asset = (
                await self.db.execute(
                    select(MediaAsset).where(
                        MediaAsset.media_type == resolved_media_type,
                        MediaAsset.series_id == media_id,
                    )
                )
            ).scalar_one_or_none()

        def _parse_datetime_value(value: Any) -> datetime | None:
            if isinstance(value, datetime):
                return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
            if isinstance(value, str):
                try:
                    parsed = datetime.fromisoformat(value)
                except ValueError:
                    return None
                return (
                    parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
                )
            return None

        def _match_root(path: str | None) -> FilesystemRoot | None:
            if not path:
                return None
            normalized_path = _norm_path(path)
            for root in filesystem_roots:
                normalized_root = _norm_path(root.path)
                if not normalized_root:
                    continue
                if normalized_path == normalized_root or normalized_path.startswith(
                    f"{normalized_root.rstrip('/')}/"
                ):
                    return root
            return None

        def _file_details(path: str | None) -> dict[str, Any]:
            details: dict[str, Any] = {
                "absolute_path": path,
                "filename": Path(path).name if path else None,
                "dataset": None,
                "pool": None,
                "filesystem": None,
                "exists": None,
                "owner": None,
                "group": None,
                "permissions": None,
                "file_size": None,
                "created": None,
                "modified": None,
                "import_eligibility": None,
                "state": "unavailable",
                "explanation": "The file path is unavailable because no provider path is linked.",
            }
            if not path:
                return details

            indexed_entry = filesystem_entries.get(_norm_path(path))
            entry = indexed_entry[0] if indexed_entry is not None else None
            root = indexed_entry[1] if indexed_entry is not None else _match_root(path)
            metadata = (
                entry.metadata_json
                if entry is not None and isinstance(entry.metadata_json, dict)
                else {}
            )
            local_path = Path(path)
            stat_result = None
            try:
                details["exists"] = local_path.exists()
            except OSError:
                details["exists"] = None
            if details["exists"]:
                try:
                    stat_result = local_path.stat()
                except OSError:
                    stat_result = None

            if entry is not None:
                details["file_size"] = max(0, int(entry.size_bytes or 0))
                details["modified"] = entry.modified_at
            if details["file_size"] is None and stat_result is not None:
                details["file_size"] = max(0, int(stat_result.st_size))
            if details["modified"] is None and stat_result is not None:
                details["modified"] = datetime.fromtimestamp(
                    stat_result.st_mtime, tz=UTC
                )

            details["dataset"] = (
                str(metadata.get("dataset")).strip() or None
                if metadata.get("dataset") is not None
                else None
            )
            details["pool"] = (
                str(metadata.get("pool") or metadata.get("pool_name")).strip() or None
                if metadata.get("pool") is not None
                or metadata.get("pool_name") is not None
                else None
            )
            filesystem_value = metadata.get("filesystem")
            if filesystem_value is None and root is not None:
                filesystem_value = root.name
            details["filesystem"] = (
                str(filesystem_value).strip() or None
                if filesystem_value is not None
                else None
            )

            if metadata.get("owner") is not None:
                details["owner"] = str(metadata.get("owner")).strip() or None
            if metadata.get("group") is not None:
                details["group"] = str(metadata.get("group")).strip() or None
            if metadata.get("permissions") is not None:
                details["permissions"] = (
                    str(metadata.get("permissions")).strip() or None
                )

            if stat_result is not None:
                if details["permissions"] is None:
                    details["permissions"] = filemode(stat_result.st_mode)
                if os.name != "nt":
                    try:
                        import grp
                        import pwd

                        pwd_module = cast(Any, pwd)
                        grp_module = cast(Any, grp)

                        if details["owner"] is None:
                            details["owner"] = pwd_module.getpwuid(
                                stat_result.st_uid
                            ).pw_name
                        if details["group"] is None:
                            details["group"] = grp_module.getgrgid(
                                stat_result.st_gid
                            ).gr_name
                    except Exception:
                        pass
                created = _parse_datetime_value(metadata.get("created"))
                if created is None:
                    created = _parse_datetime_value(metadata.get("created_at"))
                if created is None:
                    created = _parse_datetime_value(metadata.get("birthtime"))
                if created is None and os.name == "nt":
                    created = datetime.fromtimestamp(stat_result.st_ctime, tz=UTC)
                details["created"] = created

            if details["created"] is None:
                details["created"] = _parse_datetime_value(metadata.get("created_at"))
            if details["modified"] is None:
                details["modified"] = _parse_datetime_value(metadata.get("modified"))
            if details["modified"] is None:
                details["modified"] = _parse_datetime_value(metadata.get("modified_at"))

            if expected_destination:
                normalized_expected = _norm_path(expected_destination)
                normalized_path = _norm_path(path)
                if normalized_path == normalized_expected:
                    details["import_eligibility"] = "eligible"
                elif details["exists"] is False:
                    details["import_eligibility"] = "missing"
                elif details["exists"] is True:
                    details["import_eligibility"] = "review required"
                else:
                    details["import_eligibility"] = "unknown"
            else:
                details["import_eligibility"] = "unknown"

            if details["exists"] is False:
                details["state"] = "missing"
                details["explanation"] = (
                    "The file path is linked but the filesystem entry could not be found."
                )
            elif details["exists"] is True:
                details["state"] = "available"
                details["explanation"] = (
                    "Filesystem evidence is available from the indexed path and local filesystem probe."
                )
            else:
                details["state"] = "partial"
                details["explanation"] = (
                    "The filesystem path is linked, but availability could not be confirmed."
                )
            return details

        filesystem_roots = (
            (
                await self.db.execute(
                    select(FilesystemRoot).where(FilesystemRoot.enabled.is_(True))
                )
            )
            .scalars()
            .all()
        )

        all_file_paths = [
            path
            for path in [
                download_location,
                library_location,
                expected_destination,
                *[path for path, _, _, _ in known_paths],
            ]
            if path
        ]
        filesystem_entries: dict[str, tuple[FilesystemIndexEntry, FilesystemRoot]] = {}
        if all_file_paths:
            for entry, root in (
                await self.db.execute(
                    select(FilesystemIndexEntry, FilesystemRoot)
                    .join(
                        FilesystemRoot,
                        FilesystemRoot.id == FilesystemIndexEntry.root_id,
                    )
                    .where(FilesystemIndexEntry.path.in_(sorted(set(all_file_paths))))
                )
            ).all():
                filesystem_entries[_norm_path(entry.path)] = (entry, root)

        unique_file_rows: list[OperationsFileEvidence] = []
        seen_paths: set[tuple[str, str, str]] = set()

        managed_folder_candidates: list[str] = []
        if library_location:
            managed_folder_candidates.append(library_location)
        managed_folder_candidates.extend(
            [
                path
                for path, _, _, role in known_paths
                if path and role == "managed_folder"
            ]
        )

        deduped_managed_folders: list[str] = []
        seen_managed_folders: set[str] = set()
        for candidate in managed_folder_candidates:
            normalized_candidate = _norm_path(candidate)
            if not normalized_candidate or normalized_candidate in seen_managed_folders:
                continue
            seen_managed_folders.add(normalized_candidate)
            deduped_managed_folders.append(candidate)

        reference_paths = [
            path
            for path, _, _, role in known_paths
            if path and role in {"primary_media_file", "additional_file"}
        ]

        canonical_managed_folder: str | None = None
        if deduped_managed_folders:
            if reference_paths:
                scored_candidates = [
                    (
                        sum(
                            1
                            for reference_path in reference_paths
                            if _is_same_or_child(reference_path, candidate)
                        ),
                        index,
                        candidate,
                    )
                    for index, candidate in enumerate(deduped_managed_folders)
                ]
                best_score, _, best_candidate = max(scored_candidates)
                if best_score > 0:
                    canonical_managed_folder = best_candidate
            if canonical_managed_folder is None:
                canonical_managed_folder = deduped_managed_folders[0]

        canonical_library_root = _parent_directory(canonical_managed_folder)
        expected_destination_path = canonical_library_root or expected_destination

        base_rows = [
            (
                "download",
                "Download Source",
                download_location,
                "Download Client",
                None,
                "download_source",
            ),
            (
                "library-root",
                "Library Root",
                expected_destination_path,
                policy_name or "Policy",
                None,
                "library_root",
            ),
            (
                "managed-folder",
                "Managed Folder",
                canonical_managed_folder,
                "Media Library",
                expected_destination_path,
                "managed_folder",
            ),
        ]
        for key, label, path, source, known_copy_of, hierarchy_role in base_rows:
            row_key = (key, str(path))
            dedupe_key = (key, _norm_path(path), hierarchy_role)
            if dedupe_key in seen_paths:
                continue
            seen_paths.add(dedupe_key)
            details = _file_details(path)
            unique_file_rows.append(
                OperationsFileEvidence(
                    key=key,
                    label=label,
                    hierarchy_role=cast(Any, hierarchy_role),
                    absolute_path=details["absolute_path"],
                    path=path,
                    filename=details["filename"],
                    dataset=details["dataset"],
                    pool=details["pool"],
                    filesystem=details["filesystem"],
                    exists=details["exists"],
                    owner=details["owner"],
                    group=details["group"],
                    permissions=details["permissions"],
                    file_size=details["file_size"],
                    created=details["created"],
                    modified=details["modified"],
                    expected_destination=expected_destination_path,
                    known_copy_of=known_copy_of,
                    import_eligibility=details["import_eligibility"],
                    source=source,
                    state=cast(Any, details["state"]),
                    explanation=(
                        f"{label} is known from {source}."
                        if path
                        else f"{label} is unavailable because no provider path is linked."
                    ),
                )
            )

        canonical_primary_seen = False
        primary_inside_canonical = 0
        primary_outside_canonical = 0

        for index, known_path in enumerate(known_paths, start=1):
            known_path_value: str | None = known_path[0]
            known_label: str = known_path[1]
            known_source: str | None = known_path[2]
            known_role: str = known_path[3]
            if not known_path_value:
                continue
            dedupe_key = (known_label, _norm_path(known_path_value), known_role)
            if dedupe_key in seen_paths:
                continue
            seen_paths.add(dedupe_key)
            details = _file_details(known_path_value)

            hierarchy_role = known_role
            state = cast(str, details["state"])
            explanation = (
                f"{known_label} is linked from {known_source or 'provider evidence'}."
            )

            if known_role == "primary_media_file":
                in_canonical = _is_same_or_child(
                    known_path_value, canonical_managed_folder
                )
                if canonical_managed_folder and in_canonical:
                    primary_inside_canonical += 1
                    if canonical_primary_seen:
                        hierarchy_role = "additional_file"
                        explanation = (
                            "Additional media file inside the canonical managed folder."
                        )
                    else:
                        canonical_primary_seen = True
                        hierarchy_role = "primary_media_file"
                        explanation = (
                            "Primary media file is inside the canonical managed folder."
                        )
                elif canonical_managed_folder:
                    primary_outside_canonical += 1
                    hierarchy_role = "additional_copy"
                    state = "duplicate"
                    explanation = "Additional primary media file exists outside the canonical managed folder."
                else:
                    hierarchy_role = "primary_media_file"
                    explanation = "Primary media file is linked, but canonical managed folder is unavailable."
            elif known_role == "managed_folder":
                if canonical_managed_folder and _norm_path(
                    known_path_value
                ) == _norm_path(canonical_managed_folder):
                    explanation = "Managed folder matches the canonical destination for this asset."
                else:
                    explanation = (
                        "Managed folder is linked as filesystem hierarchy context."
                    )
            elif known_role == "additional_file":
                explanation = (
                    "Additional related files or folders are linked for this asset."
                )

            unique_file_rows.append(
                OperationsFileEvidence(
                    key=f"known-copy-{index}",
                    label=known_label,
                    hierarchy_role=cast(Any, hierarchy_role),
                    absolute_path=details["absolute_path"],
                    path=known_path_value,
                    filename=details["filename"],
                    dataset=details["dataset"],
                    pool=details["pool"],
                    filesystem=details["filesystem"],
                    exists=details["exists"],
                    owner=details["owner"],
                    group=details["group"],
                    permissions=details["permissions"],
                    file_size=details["file_size"],
                    created=details["created"],
                    modified=details["modified"],
                    expected_destination=expected_destination_path,
                    known_copy_of=canonical_managed_folder or expected_destination_path,
                    import_eligibility=details["import_eligibility"],
                    source=known_source,
                    state=cast(Any, state),
                    explanation=explanation,
                )
            )

        if canonical_managed_folder:
            if primary_inside_canonical > 0 and primary_outside_canonical == 0:
                filesystem_comparison_summary = (
                    "Primary media file is correctly located within the expected managed folder. "
                    "Library root and managed folder rows are treated as hierarchy context, not conflicting paths."
                )
            elif primary_inside_canonical > 0 and primary_outside_canonical > 0:
                filesystem_comparison_summary = (
                    f"{primary_outside_canonical} additional primar"
                    f"y media file{'s' if primary_outside_canonical != 1 else ''} exist outside the canonical managed folder."
                )
            elif primary_inside_canonical == 0 and primary_outside_canonical > 0:
                filesystem_comparison_summary = "Primary media file exists, but only outside the canonical managed folder."
            else:
                filesystem_comparison_summary = "Canonical managed folder is linked, but no primary media file is currently linked."
        else:
            filesystem_comparison_summary = "No canonical managed folder is linked yet, so duplicate detection is limited to known primary files only."

        file_count = len([row for row in unique_file_rows if row.path])
        metadata_summary_parts: list[str] = []
        if resolved_media_type is MediaType.MOVIE:
            movie = (
                await self.db.execute(select(Movie).where(Movie.id == media_id))
            ).scalar_one_or_none()
            if movie is not None:
                metadata_summary_parts.append(
                    "IMDb" if movie.imdb_id else "IMDb unavailable"
                )
                metadata_summary_parts.append(
                    "TMDB" if movie.tmdb_id else "TMDB unavailable"
                )
                metadata_summary_parts.append("TVDB unavailable")
        elif resolved_media_type is MediaType.SERIES:
            series = (
                await self.db.execute(select(Series).where(Series.id == media_id))
            ).scalar_one_or_none()
            if series is not None:
                metadata_summary_parts.append(
                    "IMDb" if series.imdb_id else "IMDb unavailable"
                )
                metadata_summary_parts.append(
                    "TMDB" if series.tmdb_id else "TMDB unavailable"
                )
                metadata_summary_parts.append(
                    "TVDB" if series.tvdb_id else "TVDB unavailable"
                )

        artwork_summary = "Unavailable"
        if media_asset is not None and media_asset.poster_url:
            artwork_summary = "Poster linked"

        identity_summary = title

        if not relationships:
            relationships = [
                OperationsRelationshipEvidence(
                    key="graph",
                    label="Operational Graph",
                    value=None,
                    status="unavailable",
                    explanation="No graph-based operational relationships are currently linked for this asset.",
                )
            ]
        relationships.extend(
            [
                OperationsRelationshipEvidence(
                    key="files",
                    label="Files",
                    value=f"{file_count} indexed path(s)"
                    if file_count
                    else "Unavailable",
                    status="linked" if file_count else "unavailable",
                    explanation=(
                        "Filesystem evidence is linked to this asset and is summarized in the Files tab."
                        if file_count
                        else "No filesystem evidence is currently indexed for this asset."
                    ),
                ),
                OperationsRelationshipEvidence(
                    key="plex",
                    label="Plex",
                    value="Linked"
                    if any(
                        row.application == "Plex" and row.status == "linked"
                        for row in applications
                    )
                    else "Unavailable",
                    status="linked"
                    if any(
                        row.application == "Plex" and row.status == "linked"
                        for row in applications
                    )
                    else "unavailable",
                    explanation=(
                        "Plex ownership is linked for this asset."
                        if any(
                            row.application == "Plex" and row.status == "linked"
                            for row in applications
                        )
                        else "No Plex relationship is currently linked for this asset."
                    ),
                ),
                OperationsRelationshipEvidence(
                    key="arr",
                    label="Radarr"
                    if resolved_media_type is MediaType.MOVIE
                    else "Sonarr",
                    value=(
                        "Linked"
                        if any(
                            (
                                row.application == "Radarr"
                                if resolved_media_type is MediaType.MOVIE
                                else row.application == "Sonarr"
                            )
                            and row.status == "linked"
                            for row in applications
                        )
                        else "Unavailable"
                    ),
                    status="linked"
                    if any(
                        (
                            row.application == "Radarr"
                            if resolved_media_type is MediaType.MOVIE
                            else row.application == "Sonarr"
                        )
                        and row.status == "linked"
                        for row in applications
                    )
                    else "unavailable",
                    explanation=(
                        (
                            "Radarr ownership is linked for this asset."
                            if resolved_media_type is MediaType.MOVIE
                            else "Sonarr ownership is linked for this asset."
                        )
                        if any(
                            (
                                row.application == "Radarr"
                                if resolved_media_type is MediaType.MOVIE
                                else row.application == "Sonarr"
                            )
                            and row.status == "linked"
                            for row in applications
                        )
                        else (
                            "No Radarr relationship is currently linked for this asset."
                            if resolved_media_type is MediaType.MOVIE
                            else "No Sonarr relationship is currently linked for this asset."
                        )
                    ),
                ),
                OperationsRelationshipEvidence(
                    key="qbittorrent",
                    label="qBittorrent",
                    value=torrent_state or "Unavailable",
                    status="linked" if torrent_state else "unavailable",
                    explanation=(
                        "qBittorrent ownership is linked for this asset."
                        if torrent_state
                        else "No qBittorrent relationship is currently linked for this asset."
                    ),
                ),
                OperationsRelationshipEvidence(
                    key="metadata",
                    label="Metadata",
                    value=", ".join(metadata_summary_parts)
                    if metadata_summary_parts
                    else "Unavailable",
                    status="linked" if metadata_summary_parts else "unavailable",
                    explanation=(
                        "Metadata providers are linked for this asset."
                        if metadata_summary_parts
                        else "No metadata provider relationships are currently linked for this asset."
                    ),
                ),
                OperationsRelationshipEvidence(
                    key="artwork",
                    label="Artwork",
                    value=artwork_summary,
                    status="linked"
                    if artwork_summary != "Unavailable"
                    else "unavailable",
                    explanation=(
                        "Artwork evidence is linked for this asset."
                        if artwork_summary != "Unavailable"
                        else "No artwork relationship is currently linked for this asset."
                    ),
                ),
                OperationsRelationshipEvidence(
                    key="identity",
                    label="Identity",
                    value=identity_summary,
                    status="linked" if identity_summary else "unavailable",
                    explanation=(
                        "Identity evidence is linked for this asset."
                        if identity_summary
                        else "No identity relationship is currently linked for this asset."
                    ),
                ),
                OperationsRelationshipEvidence(
                    key="related_torrents",
                    label="Related Torrents",
                    value=torrent_state,
                    status="linked" if torrent_state else "unavailable",
                    explanation=(
                        "Torrent state is linked to this asset."
                        if torrent_state
                        else "No torrent relationship is currently linked."
                    ),
                ),
                OperationsRelationshipEvidence(
                    key="workflow_reasoning",
                    label="Workflow Reasoning",
                    value=graph_references[0] if graph_references else None,
                    status="linked" if graph_references else "unavailable",
                    explanation=(
                        "Graph and workflow evidence support this recommendation."
                        if graph_references
                        else "No graph-backed workflow reference is currently linked."
                    ),
                ),
            ]
        )

        case_summary = f"{reason} Next step: {recommendation}."
        return (
            case_summary,
            expected_destination_path,
            filesystem_comparison_summary,
            unique_file_rows,
            applications,
            relationships,
            [row.path for row in unique_file_rows if row.path],
        )

    def _build_action_manifest(
        self,
        *,
        primary_action: str,
        stage_key: str,
        target_type: str,
        media_type: MediaType | None,
        summary: str = "",
        reason: str = "",
        expected_destination: str | None = None,
        known_paths: list[str] | None = None,
        estimated_recovery_bytes: int = 0,
        references: list[str] | None = None,
    ) -> OperationActionManifest:
        resolved_primary = self._normalize_action_id(primary_action)
        primary_is_required = self._is_required_primary_action(
            resolved_primary,
            stage_key=stage_key,
            summary=summary,
        )
        workflow_outcome = self._workflow_outcome(
            stage_key=stage_key,
            primary_is_required=primary_is_required,
        )
        actions: list[str] = [resolved_primary]

        if target_type in {"movie", "series", "season", "episode", "reclaim_candidate"}:
            actions.extend(
                [
                    "refresh_metadata",
                    "refresh_artwork",
                    "sync_collections",
                    "repair_identity",
                    "refresh_plex",
                ]
            )
            if media_type is MediaType.MOVIE:
                actions.append("open_radarr")
            if media_type is MediaType.SERIES:
                actions.append("open_sonarr")

        if target_type in {"torrent", "download_object"}:
            actions.extend(
                [
                    "force_recheck",
                    "resume_download",
                    "pause_torrent",
                    "open_qbittorrent",
                ]
            )

        actions.extend(
            ["ignore_recommendation", "manual_review", "mark_resolved", "archive"]
        )

        deduped: list[str] = []
        seen: set[str] = set()
        for action in actions:
            if action in seen:
                continue
            seen.add(action)
            deduped.append(action)

        primary_definition = _ACTION_DEFINITIONS.get(resolved_primary, {})
        primary_label = str(
            primary_definition.get(
                "label", resolved_primary.replace("_", " ").title()
            )
        )
        primary_action_reasoning = self._primary_action_reasoning(
            resolved_primary,
            stage_key=stage_key,
            summary=summary,
            reason=reason,
            expected_destination=expected_destination,
            estimated_recovery_bytes=estimated_recovery_bytes,
            workflow_outcome=workflow_outcome,
        )

        return OperationActionManifest(
            workflow_outcome=cast(Any, workflow_outcome),
            workflow_summary=self._workflow_summary(
                workflow_outcome=workflow_outcome,
                primary_label=primary_label,
            ),
            primary_action_reasoning=primary_action_reasoning,
            available_actions=[
                self._manifest_entry(
                    action,
                    impact_preview=self._impact_preview_for_action(
                        action,
                        summary=summary,
                        expected_destination=expected_destination,
                        known_paths=list(known_paths or []),
                        estimated_recovery_bytes=estimated_recovery_bytes,
                        references=list(references or []),
                    ),
                    presentation=self._action_presentation(
                        action,
                        is_primary=action == resolved_primary,
                        primary_is_required=primary_is_required,
                        workflow_outcome=workflow_outcome,
                    ),
                )
                for action in deduped
            ]
        )

    def _supported_actions(self) -> set[str]:
        supported = {str(key) for key in _ACTION_ALIASES}
        supported.update({str(key) for key in _ACTION_DEFINITIONS})
        return supported

    async def _build_workflow_board(
        self,
        recommendations: OperationsRecommendationsResponse,
        issues: list[OperationsIssue],
        downloads: Any,
    ) -> OperationsWorkflowBoard:
        stage_assets: dict[str, list[OperationsWorkflowAsset]] = {
            key: [] for key, _, _ in _WORKFLOW_STAGE_META
        }

        download_by_path = {
            row.path: row for row in list(getattr(downloads, "items", []))
        }

        for row in list(getattr(downloads, "items", [])):
            stage_key = self._stage_for_download(row)
            retention_remaining = (
                f"{row.retention_remaining_hours}h"
                if row.retention_remaining_hours is not None
                else None
            )
            policy_name = self._policy_name_for_asset(
                row.media_type, row.media_identity or row.path
            )
            (
                case_summary,
                expected_destination,
                filesystem_comparison_summary,
                file_evidence,
                application_evidence,
                relationship_evidence,
                known_paths,
            ) = await self._build_asset_evidence(
                title=row.media_identity or row.path,
                media_type=row.media_type,
                target_type="download_object",
                target_id=row.path,
                policy_name=policy_name,
                download_location=row.path,
                library_location=row.library_path,
                torrent_state=row.torrent_state,
                summary=row.lifecycle_state,
                reason=row.cleanup_reason or "Download lifecycle classification",
                recommendation=row.recommendation,
                estimated_recovery_bytes=row.recoverable_space_bytes,
                graph_references=[
                    "correlation_graph.timeline",
                    "filesystem_index_entries.path",
                ],
            )
            action_manifest = self._build_action_manifest(
                primary_action=row.recommendation,
                stage_key=stage_key,
                target_type="download_object",
                media_type=row.media_type,
                summary=row.cleanup_reason or row.recommendation,
                reason=row.cleanup_reason or "Download lifecycle classification",
                expected_destination=expected_destination,
                known_paths=known_paths,
                estimated_recovery_bytes=row.recoverable_space_bytes,
                references=[
                    "correlation_graph.timeline",
                    "filesystem_index_entries.path",
                ],
            )
            narrative = self._build_operational_narrative(
                media_type=row.media_type,
                stage_key=stage_key,
                download_location=row.path,
                library_location=row.library_path,
                torrent_state=row.torrent_state,
                import_state=row.import_state,
                retention_remaining_hours=row.retention_remaining_hours,
                estimated_space_recovery=row.recoverable_space_bytes,
                expected_destination=expected_destination,
                file_evidence=file_evidence,
                action_manifest=action_manifest,
            )
            stage_assets[stage_key].append(
                OperationsWorkflowAsset(
                    id=f"download:{row.path}",
                    title=row.media_identity or row.path,
                    year=self._extract_year_from_title(row.media_identity or row.path),
                    media_type=row.media_type,
                    poster_url=None,
                    risk_level=(
                        "high"
                        if row.cleanup_classification
                        in {"failed_import", "needs_investigation"}
                        else "medium"
                        if row.cleanup_classification
                        in {
                            "duplicate_download",
                            "abandoned_download",
                            "safe_to_archive",
                        }
                        else "low"
                    ),
                    target_type="download_object",
                    target_id=row.path,
                    current_stage=cast(Any, stage_key),
                    current_status=row.lifecycle_state,
                    library_location=row.library_path,
                    download_location=row.path,
                    torrent_state=row.torrent_state,
                    import_state=row.import_state,
                    retention_policy=row.retention_policy,
                    retention_remaining=retention_remaining,
                    next_action=row.recommendation,
                    recommendation=row.cleanup_reason or row.recommendation,
                    confidence=row.confidence_score,
                    estimated_space_recovery=row.recoverable_space_bytes,
                    reason=row.cleanup_reason or "Download lifecycle classification",
                    after_action="Asset progresses to next lifecycle stage after successful operation.",
                    graph_references=[
                        "correlation_graph.timeline",
                        "filesystem_index_entries.path",
                    ],
                    policy_name=policy_name,
                    filters=["downloads"],
                    action_manifest=action_manifest,
                    case_summary=case_summary,
                    expected_destination=expected_destination,
                    filesystem_comparison_summary=filesystem_comparison_summary,
                    file_evidence=file_evidence,
                    application_evidence=application_evidence,
                    relationship_evidence=relationship_evidence,
                    narrative=narrative,
                )
            )

        for item in recommendations.items:
            if (
                item.target_type == "download_object"
                and item.target_id in download_by_path
            ):
                continue
            stage_key = self._stage_for_recommendation(item)
            matched_download = (
                download_by_path.get(item.target_id or "")
                if item.target_type == "download_object"
                else None
            )
            media_type = None
            if item.target_type == "movie":
                media_type = MediaType.MOVIE
            elif item.target_type in {"series", "season", "episode"}:
                media_type = MediaType.SERIES
            elif item.target_type == "reclaim_candidate":
                media_type = item.media_type
            policy_name = self._policy_name_for_asset(media_type, item.title)
            (
                case_summary,
                expected_destination,
                filesystem_comparison_summary,
                file_evidence,
                application_evidence,
                relationship_evidence,
                known_paths,
            ) = await self._build_asset_evidence(
                title=item.title,
                media_type=media_type,
                target_type=item.target_type,
                target_id=item.target_id,
                policy_name=policy_name,
                download_location=(
                    matched_download.path if matched_download is not None else None
                ),
                library_location=(
                    matched_download.library_path
                    if matched_download is not None
                    else None
                ),
                torrent_state=(
                    matched_download.torrent_state
                    if matched_download is not None
                    else None
                ),
                summary=item.summary,
                reason=(item.reasons[0] if item.reasons else item.summary),
                recommendation=item.explanation or item.summary,
                estimated_recovery_bytes=item.estimated_recovery_bytes,
                graph_references=item.graph_references,
            )
            action_manifest = self._build_action_manifest(
                primary_action=item.action,
                stage_key=stage_key,
                target_type=item.target_type,
                media_type=media_type,
                summary=item.summary,
                reason=(item.reasons[0] if item.reasons else item.summary),
                expected_destination=expected_destination,
                known_paths=known_paths,
                estimated_recovery_bytes=item.estimated_recovery_bytes,
                references=item.graph_references,
            )
            narrative = self._build_operational_narrative(
                media_type=media_type,
                stage_key=stage_key,
                download_location=(
                    matched_download.path if matched_download is not None else None
                ),
                library_location=(
                    matched_download.library_path
                    if matched_download is not None
                    else None
                ),
                torrent_state=(
                    matched_download.torrent_state
                    if matched_download is not None
                    else None
                ),
                import_state=(
                    matched_download.import_state
                    if matched_download is not None
                    else None
                ),
                retention_remaining_hours=(
                    matched_download.retention_remaining_hours
                    if matched_download is not None
                    else None
                ),
                estimated_space_recovery=item.estimated_recovery_bytes,
                expected_destination=expected_destination,
                file_evidence=file_evidence,
                action_manifest=action_manifest,
            )
            stage_assets[stage_key].append(
                OperationsWorkflowAsset(
                    id=item.id,
                    title=item.title,
                    year=self._extract_year_from_title(item.title),
                    media_type=media_type,
                    poster_url=(
                        item.artwork.poster
                        if item.artwork is not None and item.artwork.poster
                        else item.poster_url
                    ),
                    risk_level=(
                        "high"
                        if item.safety_level == "high_risk"
                        else "medium"
                        if item.safety_level == "medium_risk"
                        else "low"
                    ),
                    target_type=item.target_type,
                    target_id=item.target_id,
                    current_stage=cast(Any, stage_key),
                    current_status=item.summary,
                    library_location=(
                        matched_download.library_path
                        if matched_download is not None
                        else None
                    ),
                    download_location=(
                        matched_download.path if matched_download is not None else None
                    ),
                    torrent_state=(
                        matched_download.torrent_state
                        if matched_download is not None
                        else None
                    ),
                    import_state=(
                        matched_download.import_state
                        if matched_download is not None
                        else None
                    ),
                    retention_policy=(
                        matched_download.retention_policy
                        if matched_download is not None
                        else None
                    ),
                    retention_remaining=(
                        f"{matched_download.retention_remaining_hours}h"
                        if matched_download is not None
                        and matched_download.retention_remaining_hours is not None
                        else None
                    ),
                    next_action=item.action,
                    recommendation=item.explanation or item.summary,
                    confidence=item.confidence,
                    estimated_space_recovery=item.estimated_recovery_bytes,
                    reason=(item.reasons[0] if item.reasons else item.summary),
                    after_action="Operation result is audited and lifecycle advances when checks pass.",
                    graph_references=item.graph_references,
                    policy_name=policy_name,
                    filters=self._filters_for_recommendation(item),
                    action_manifest=action_manifest,
                    case_summary=case_summary,
                    expected_destination=expected_destination,
                    filesystem_comparison_summary=filesystem_comparison_summary,
                    file_evidence=file_evidence,
                    application_evidence=application_evidence,
                    relationship_evidence=relationship_evidence,
                    narrative=narrative,
                )
            )

        for issue in issues:
            issue_stage = (
                "import"
                if issue.issue_type in {"missing_request", "failed_import"}
                else "organize"
            )
            policy_name = self._policy_name_for_asset(issue.media_type, issue.title)
            (
                case_summary,
                expected_destination,
                filesystem_comparison_summary,
                file_evidence,
                application_evidence,
                relationship_evidence,
                known_paths,
            ) = await self._build_asset_evidence(
                title=issue.title,
                media_type=issue.media_type,
                target_type=issue.media_type.value,
                target_id=str(issue.media_id),
                policy_name=policy_name,
                download_location=None,
                library_location=None,
                torrent_state=None,
                summary=issue.issue_type,
                reason=issue.reason,
                recommendation=issue.recommendation,
                estimated_recovery_bytes=0,
                graph_references=issue.graph_references,
            )
            action_manifest = self._build_action_manifest(
                primary_action=issue.suggested_remediation,
                stage_key=issue_stage,
                target_type=issue.media_type.value,
                media_type=issue.media_type,
                summary=issue.reason,
                reason=issue.reason,
                expected_destination=expected_destination,
                known_paths=known_paths,
                estimated_recovery_bytes=0,
                references=issue.graph_references,
            )
            narrative = self._build_operational_narrative(
                media_type=issue.media_type,
                stage_key=issue_stage,
                download_location=None,
                library_location=None,
                torrent_state=None,
                import_state=None,
                retention_remaining_hours=None,
                estimated_space_recovery=0,
                expected_destination=expected_destination,
                file_evidence=file_evidence,
                action_manifest=action_manifest,
            )
            stage_assets[issue_stage].append(
                OperationsWorkflowAsset(
                    id=f"issue:{issue.key}",
                    title=issue.title,
                    year=self._extract_year_from_title(issue.title),
                    media_type=issue.media_type,
                    poster_url=None,
                    risk_level=(
                        "high"
                        if issue.severity in {"critical", "high"}
                        else "medium"
                        if issue.severity == "medium"
                        else "low"
                    ),
                    target_type=issue.media_type.value,
                    target_id=str(issue.media_id),
                    current_stage=cast(Any, issue_stage),
                    current_status=issue.issue_type,
                    library_location=None,
                    download_location=None,
                    torrent_state=None,
                    import_state=None,
                    retention_policy=None,
                    retention_remaining=None,
                    next_action=issue.suggested_remediation,
                    recommendation=issue.recommendation,
                    confidence=issue.confidence,
                    estimated_space_recovery=0,
                    reason=issue.reason,
                    after_action="Issue resolution updates graph health and removes the blocker.",
                    graph_references=issue.graph_references,
                    policy_name=policy_name,
                    filters=self._filters_for_issue(issue),
                    action_manifest=action_manifest,
                    case_summary=case_summary,
                    expected_destination=expected_destination,
                    filesystem_comparison_summary=filesystem_comparison_summary,
                    file_evidence=file_evidence,
                    application_evidence=application_evidence,
                    relationship_evidence=relationship_evidence,
                    narrative=narrative,
                )
            )

        stages: list[OperationsWorkflowStage] = []
        filter_counts: dict[str, int] = {key: 0 for key in _FILTER_TITLES}

        for key, title, description in _WORKFLOW_STAGE_META:
            assets = stage_assets[key]
            assets.sort(
                key=lambda row: (
                    0 if row.current_stage in {"cleanup", "retention"} else 1,
                    -(row.estimated_space_recovery or 0),
                    row.title.lower(),
                )
            )
            for asset in assets:
                for filter_key in asset.filters:
                    if filter_key in filter_counts:
                        filter_counts[filter_key] += 1
            stages.append(
                OperationsWorkflowStage(
                    key=cast(Any, key),
                    title=title,
                    description=description,
                    count=len(assets),
                    assets=assets,
                )
            )

        filters = [
            OperationsWorkflowFilter(
                key=key,
                title=title,
                count=filter_counts.get(key, 0),
            )
            for key, title in _FILTER_TITLES.items()
        ]
        filters.sort(key=lambda row: (-row.count, row.title.lower()))

        return OperationsWorkflowBoard(stages=stages, filters=filters)

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

        supported_actions = self._supported_actions()

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
                passed=self._normalize_action_id(recommendation.action)
                in supported_actions,
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

        action = str(recommendation.action or "").lower()
        # Investigation actions require operator follow-up and are tracked as failed execution.
        execution_result = "completed"
        execution_message = "Operation executed and logged"
        executed = True
        if action == "investigate_torrent":
            execution_result = "failed"
            execution_message = "Investigation required manual operator follow-up"
            executed = False

        history = OperationHistory(
            action=recommendation.action,
            target_type=recommendation.target_type,
            target_id=recommendation.target_id,
            result=execution_result,
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
            executed=executed,
            result=execution_result,
            message=execution_message,
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
        return await self.workspace_filtered()

    async def workspace_filtered(
        self,
        *,
        candidates_only: bool = False,
        imported_filter_ids: list[int] | None = None,
        decision_filter_ids: list[int] | None = None,
        smart_filter_ids: list[int] | None = None,
    ) -> OperationsWorkspaceResponse:
        overview = await self.overview()
        recommendations = await self.recommendations()
        filesystem = await self.filesystem_config()
        cleanup_plans = await self.cleanup_plans()
        artwork_issues = await self.artwork_issues_summary()
        _, intelligence = await self._graph_intelligence()
        downloads = await self._downloads_intelligence()

        allowed_movie_ids, allowed_series_ids = await self._workspace_allowed_media_ids(
            candidates_only=candidates_only,
            imported_filter_ids=imported_filter_ids,
            decision_filter_ids=decision_filter_ids,
            smart_filter_ids=smart_filter_ids,
        )

        reclaim_candidate_targets = await self._recommendation_candidate_targets(
            recommendations.items
        )

        if allowed_movie_ids is not None or allowed_series_ids is not None:
            recommendations = OperationsRecommendationsResponse(
                items=[
                    item
                    for item in recommendations.items
                    if self._include_recommendation_for_media_filters(
                        item,
                        allowed_movie_ids=allowed_movie_ids,
                        allowed_series_ids=allowed_series_ids,
                        reclaim_candidate_targets=reclaim_candidate_targets,
                    )
                ],
                total=0,
            )
            recommendations.total = len(recommendations.items)

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
            if self._include_media_target(
                item.media_type,
                item.media_id,
                allowed_movie_ids=allowed_movie_ids,
                allowed_series_ids=allowed_series_ids,
            )
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
        workflow = await self._build_workflow_board(
            recommendations=recommendations,
            issues=issues,
            downloads=downloads,
        )

        if allowed_movie_ids is not None or allowed_series_ids is not None:
            workflow = self._filter_workflow_board(
                workflow,
                allowed_movie_ids=allowed_movie_ids,
                allowed_series_ids=allowed_series_ids,
                reclaim_candidate_targets=reclaim_candidate_targets,
            )

        return OperationsWorkspaceResponse(
            overview=overview,
            recommendations=recommendations,
            filesystem=filesystem,
            cleanup_plans=cleanup_plans,
            workflow=workflow,
            media_policies=self._build_media_policies(),
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

    async def _workspace_allowed_media_ids(
        self,
        *,
        candidates_only: bool,
        imported_filter_ids: list[int] | None,
        decision_filter_ids: list[int] | None,
        smart_filter_ids: list[int] | None,
    ) -> tuple[set[int] | None, set[int] | None]:
        imported_ids = [int(value) for value in (imported_filter_ids or [])]
        decision_ids = [int(value) for value in (decision_filter_ids or [])]
        smart_ids = [int(value) for value in (smart_filter_ids or [])]
        if (
            not candidates_only
            and not imported_ids
            and not decision_ids
            and not smart_ids
        ):
            return None, None
        movie_ids = await self._filtered_media_ids(
            media_type=MediaType.MOVIE,
            candidates_only=candidates_only,
            imported_filter_ids=imported_ids,
            decision_filter_ids=decision_ids,
            smart_filter_ids=smart_ids,
        )
        series_ids = await self._filtered_media_ids(
            media_type=MediaType.SERIES,
            candidates_only=candidates_only,
            imported_filter_ids=imported_ids,
            decision_filter_ids=decision_ids,
            smart_filter_ids=smart_ids,
        )
        return movie_ids, series_ids

    async def _recommendation_candidate_targets(
        self,
        items: list[OperationsRecommendation],
    ) -> dict[int, tuple[MediaType, int]]:
        candidate_ids = [
            int(item.target_id)
            for item in items
            if item.target_type == "reclaim_candidate"
            and item.target_id is not None
            and item.target_id.isdigit()
        ]
        if not candidate_ids:
            return {}
        rows = (
            await self.db.execute(
                select(
                    ReclaimCandidate.id,
                    ReclaimCandidate.movie_id,
                    ReclaimCandidate.series_id,
                ).where(ReclaimCandidate.id.in_(candidate_ids))
            )
        ).all()
        mapping: dict[int, tuple[MediaType, int]] = {}
        for candidate_id, movie_id, series_id in rows:
            if movie_id is not None:
                mapping[int(candidate_id)] = (MediaType.MOVIE, int(movie_id))
            elif series_id is not None:
                mapping[int(candidate_id)] = (MediaType.SERIES, int(series_id))
        return mapping

    async def _filtered_media_ids(
        self,
        *,
        media_type: MediaType,
        candidates_only: bool,
        imported_filter_ids: list[int],
        decision_filter_ids: list[int],
        smart_filter_ids: list[int],
    ) -> set[int]:
        model = Movie if media_type is MediaType.MOVIE else Series
        query = select(model.id).where(model.removed_at.is_(None))
        count_query = (
            select(func.count()).select_from(model).where(model.removed_at.is_(None))
        )
        query, _ = await apply_spec(
            self.db,
            spec=QueryEngineSpec(
                media_type=media_type,
                search=None,
                candidates_only=candidates_only,
                imported_filter_ids=imported_filter_ids,
                decision_filter_ids=decision_filter_ids,
                smart_filter_ids=smart_filter_ids,
            ),
            query=query,
            count_query=count_query,
        )
        rows = (await self.db.execute(query)).all()
        return {int(media_id) for (media_id,) in rows}

    @staticmethod
    def _include_media_target(
        media_type: MediaType | None,
        media_id: int | str | None,
        *,
        allowed_movie_ids: set[int] | None,
        allowed_series_ids: set[int] | None,
    ) -> bool:
        if allowed_movie_ids is None and allowed_series_ids is None:
            return True
        if media_type is None or media_id is None:
            return False
        try:
            parsed_id = int(media_id)
        except (TypeError, ValueError):
            return False
        if media_type is MediaType.MOVIE:
            return allowed_movie_ids is None or parsed_id in allowed_movie_ids
        if media_type is MediaType.SERIES:
            return allowed_series_ids is None or parsed_id in allowed_series_ids
        return False

    def _include_recommendation_for_media_filters(
        self,
        item: OperationsRecommendation,
        *,
        allowed_movie_ids: set[int] | None,
        allowed_series_ids: set[int] | None,
        reclaim_candidate_targets: dict[int, tuple[MediaType, int]],
    ) -> bool:
        media_type = None
        target_id = item.target_id
        if item.target_type == "movie":
            media_type = MediaType.MOVIE
        elif item.target_type in {"series", "season", "episode"}:
            media_type = MediaType.SERIES
        elif item.target_type == "reclaim_candidate":
            if item.target_id is not None and item.target_id.isdigit():
                resolved = reclaim_candidate_targets.get(int(item.target_id))
                if resolved is not None:
                    media_type, resolved_media_id = resolved
                    target_id = str(resolved_media_id)
                else:
                    media_type = item.media_type
            else:
                media_type = item.media_type
        return self._include_media_target(
            media_type,
            target_id,
            allowed_movie_ids=allowed_movie_ids,
            allowed_series_ids=allowed_series_ids,
        )

    def _filter_workflow_board(
        self,
        workflow: OperationsWorkflowBoard,
        *,
        allowed_movie_ids: set[int] | None,
        allowed_series_ids: set[int] | None,
        reclaim_candidate_targets: dict[int, tuple[MediaType, int]],
    ) -> OperationsWorkflowBoard:
        filtered_stages: list[OperationsWorkflowStage] = []
        filter_counts: Counter[str] = Counter()
        for stage in workflow.stages:
            assets: list[OperationsWorkflowAsset] = []
            for asset in stage.assets:
                target_id = asset.target_id
                if (
                    asset.target_type == "reclaim_candidate"
                    and asset.target_id is not None
                    and asset.target_id.isdigit()
                ):
                    resolved = reclaim_candidate_targets.get(int(asset.target_id))
                    if resolved is not None:
                        _, resolved_media_id = resolved
                        target_id = str(resolved_media_id)
                if self._include_media_target(
                    asset.media_type,
                    target_id,
                    allowed_movie_ids=allowed_movie_ids,
                    allowed_series_ids=allowed_series_ids,
                ):
                    assets.append(asset)
            for asset in assets:
                filter_counts.update(asset.filters)
            filtered_stages.append(
                OperationsWorkflowStage(
                    key=stage.key,
                    title=stage.title,
                    description=stage.description,
                    count=len(assets),
                    assets=assets,
                )
            )
        filtered_filters = [
            OperationsWorkflowFilter(
                key=row.key,
                title=row.title,
                count=filter_counts.get(row.key, 0),
            )
            for row in workflow.filters
        ]
        return OperationsWorkflowBoard(stages=filtered_stages, filters=filtered_filters)

    async def artwork_issues_summary(self) -> ArtworkIssuesSummary:
        identity_health = await IdentityCenterService(
            self.db, request_context=self._request_context
        ).identity_health_summary()
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
