from __future__ import annotations

from backend.core.artwork import CENTRAL_PLACEHOLDER_POSTER_URL
from backend.enums import MediaType
from backend.models.mie import (
    MieMediaGraphResponse,
)
from backend.services.mie.operations_models import DetectedIssue, IssueSeverity


def _base_key(graph: MieMediaGraphResponse, suffix: str) -> str:
    return f"{graph.media_type.value}-{graph.media_id}:{suffix}"


def _media_label(graph: MieMediaGraphResponse) -> str:
    return graph.title or f"{graph.media_type.value} {graph.media_id}"


def _file_missing(graph: MieMediaGraphResponse) -> bool:
    return graph.file_intelligence.missing_files > 0


def _torrent_failed(graph: MieMediaGraphResponse) -> bool:
    for torrent in graph.torrent_intelligence.torrents:
        state = (torrent.computed_state or "").lower()
        if state in {"failed", "blocked", "missing"}:
            return True
    return False


def _torrent_stalled(graph: MieMediaGraphResponse) -> bool:
    for torrent in graph.torrent_intelligence.torrents:
        raw_state = (torrent.raw_state or "").lower()
        state = (torrent.computed_state or "").lower()
        if "stalled" in raw_state or state == "queued":
            return True
    return False


def detect_missing_request(graph: MieMediaGraphResponse) -> DetectedIssue | None:
    if graph.request_intelligence.request_state != "unknown":
        return None
    return DetectedIssue(
        key=_base_key(graph, "missing_request"),
        issue_type="missing_request",
        severity="medium",
        confidence=88,
        media_type=graph.media_type,
        media_id=graph.media_id,
        title=f"Missing request: {_media_label(graph)}",
        reason="No request was linked to this media asset.",
        recommendation="Create or sync a request entry to restore request lineage.",
        remediation="Trigger request sync and verify external request identifier mapping.",
        graph_references=[
            "request_intelligence.request_state",
            "request_intelligence.requests",
            "media_id",
        ],
        action="sync_request",
        safety_level="safe",
    )


def detect_artwork_gap(graph: MieMediaGraphResponse) -> DetectedIssue | None:
    poster_urls = [
        row.url
        for row in graph.artwork_intelligence.references
        if row.artwork_type == "poster"
    ]
    if poster_urls and not any(
        url == CENTRAL_PLACEHOLDER_POSTER_URL for url in poster_urls
    ):
        return None
    return DetectedIssue(
        key=_base_key(graph, "artwork_gap"),
        issue_type="artwork_gap",
        severity="low",
        confidence=84,
        media_type=graph.media_type,
        media_id=graph.media_id,
        title=f"Artwork gap: {_media_label(graph)}",
        reason="Poster artwork is missing or still using placeholder art.",
        recommendation="Refresh artwork metadata for this title.",
        remediation="Run artwork ingestion and verify selected artwork source.",
        graph_references=["artwork_intelligence.references"],
        action="refresh_artwork",
        safety_level="safe",
    )


def detect_failed_import(graph: MieMediaGraphResponse) -> DetectedIssue | None:
    has_missing_file = _file_missing(graph)
    has_failed_torrent = _torrent_failed(graph)
    if not has_missing_file and not has_failed_torrent:
        return None
    refs = ["files.items", "torrents.items", "health.factors"]
    reason = "Import appears unhealthy due to missing files or failed torrent state."
    return DetectedIssue(
        key=_base_key(graph, "failed_import"),
        issue_type="failed_import",
        severity="high",
        confidence=92,
        media_type=graph.media_type,
        media_id=graph.media_id,
        title=f"Failed import risk: {_media_label(graph)}",
        reason=reason,
        recommendation="Inspect importer status and repair missing files before retry.",
        remediation="Recheck path mappings, then re-run import or force recheck in client.",
        graph_references=["file_intelligence", "torrent_intelligence", *refs],
        action="repair_import",
        safety_level="low_risk",
    )


def detect_torrent_health(graph: MieMediaGraphResponse) -> DetectedIssue | None:
    if not graph.torrent_intelligence.torrents:
        return None
    if _torrent_failed(graph):
        return None
    if not _torrent_stalled(graph):
        return None
    return DetectedIssue(
        key=_base_key(graph, "torrent_stalled"),
        issue_type="torrent_stalled",
        severity="medium",
        confidence=79,
        media_type=graph.media_type,
        media_id=graph.media_id,
        title=f"Torrent stalled: {_media_label(graph)}",
        reason="Torrent state indicates stalled or queued download without progress.",
        recommendation="Check tracker reachability and queue constraints.",
        remediation="Validate tracker status and increase download slot priority if needed.",
        graph_references=[
            "torrent_intelligence.torrents[].raw_state",
            "torrent_intelligence.torrents[].eta_seconds",
        ],
        action="investigate_torrent",
        safety_level="safe",
    )


def detect_filesystem_inconsistency(
    graph: MieMediaGraphResponse,
) -> DetectedIssue | None:
    files_total = len(graph.file_intelligence.media_files)
    missing = int(graph.file_intelligence.missing_files)
    if files_total == 0 and missing == 0:
        return None
    total = max(1, files_total)
    if missing == 0:
        return None
    severity: IssueSeverity = "critical" if missing == total else "high"
    confidence = 94 if missing == total else 87
    return DetectedIssue(
        key=_base_key(graph, "filesystem_inconsistency"),
        issue_type="filesystem_inconsistency",
        severity=severity,
        confidence=confidence,
        media_type=graph.media_type,
        media_id=graph.media_id,
        title=f"Filesystem inconsistency: {_media_label(graph)}",
        reason=f"{missing}/{total} expected files are missing on disk.",
        recommendation="Reconcile filesystem paths and rerun media scan.",
        remediation="Validate root mappings and trigger rescan/import for affected paths.",
        graph_references=[
            "file_intelligence.media_files",
            "file_intelligence.missing_files",
        ],
        action="repair_filesystem",
        safety_level="medium_risk",
    )


def detect_duplicate_identity(graph: MieMediaGraphResponse) -> DetectedIssue | None:
    has_arr = len(graph.arr_intelligence.ownership) > 0
    if not has_arr:
        return None
    if graph.media_type != MediaType.MOVIE:
        return None
    # For phase-2 consumer checks, treat stale missing request linkage as potential identity mismatch.
    if graph.request_intelligence.request_state != "unknown":
        return None
    return DetectedIssue(
        key=_base_key(graph, "duplicate_identity"),
        issue_type="duplicate_identity",
        severity="medium",
        confidence=71,
        media_type=graph.media_type,
        media_id=graph.media_id,
        title=f"Potential duplicate identity: {_media_label(graph)}",
        reason="ARR ownership exists while synchronized request state is still unknown.",
        recommendation="Validate provider identity mapping and reconcile duplicated candidates.",
        remediation="Compare external IDs and merge incorrect duplicate mappings.",
        graph_references=[
            "identity",
            "arr_intelligence.ownership",
            "request_intelligence.request_state",
        ],
        action="review_identity",
        safety_level="safe",
    )
