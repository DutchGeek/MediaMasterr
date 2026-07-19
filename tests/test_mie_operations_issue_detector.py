from __future__ import annotations

from datetime import UTC, datetime

from backend.enums import MediaType
from backend.models.mie import (
    MieCorrelationArrIntelligence,
    MieCorrelationArrOwnershipRecord,
    MieCorrelationArtworkIntelligence,
    MieCorrelationArtworkRecord,
    MieCorrelationExternalIds,
    MieCorrelationFileIntelligence,
    MieCorrelationHealthCategory,
    MieCorrelationHealthSummary,
    MieCorrelationIdentity,
    MieCorrelationRequestIntelligence,
    MieCorrelationTimelineEvent,
    MieCorrelationTorrentIntelligence,
    MieCorrelationTorrentRecord,
    MieMediaGraphResponse,
)
from backend.services.mie.issue_detector import IssueDetector
from backend.services.mie.operations_engine import OperationsEngine


def _graph(
    *,
    media_id: int = 101,
    request_state: str = "unknown",
    has_arr: bool = False,
    missing_files: int = 0,
    torrent_state: str | None = None,
    raw_torrent_state: str | None = None,
    with_poster: bool = True,
    health_score: int = 85,
) -> MieMediaGraphResponse:
    torrents = []
    if torrent_state is not None:
        torrents.append(
            MieCorrelationTorrentRecord(
                torrent_hash="abc",
                torrent_name="Example",
                category=None,
                download_client="qbittorrent",
                progress=0.5,
                download_speed=100,
                upload_speed=0,
                eta_seconds=120,
                raw_state=raw_torrent_state,
                computed_state=torrent_state,
            )
        )

    artwork_refs = (
        [
            MieCorrelationArtworkRecord(
                source="tmdb",
                artwork_type="poster",
                url="https://image.tmdb.org/t/p/w342/example.jpg",
            )
        ]
        if with_poster
        else []
    )

    arr_ownership = []
    if has_arr:
        arr_ownership.append(
            MieCorrelationArrOwnershipRecord(
                provider="radarr",
                internal_arr_id="123",
                root_folder="/movies",
                quality_profile=None,
                tags=[],
                monitored=True,
                import_status="unknown",
            )
        )

    return MieMediaGraphResponse(
        media_id=media_id,
        media_type=MediaType.MOVIE,
        title="Example Movie",
        graph_generated_at=datetime.now(UTC),
        identity=MieCorrelationIdentity(
            media_identity_id=1,
            canonical_title="Example Movie",
            canonical_ids=MieCorrelationExternalIds(tmdb="101"),
            media_type=MediaType.MOVIE,
            release_year=2024,
            canonical_provider="tmdb",
        ),
        request_intelligence=MieCorrelationRequestIntelligence(
            request_state=request_state,
            requests=[],
        ),
        arr_intelligence=MieCorrelationArrIntelligence(ownership=arr_ownership),
        torrent_intelligence=MieCorrelationTorrentIntelligence(torrents=torrents),
        file_intelligence=MieCorrelationFileIntelligence(
            media_files=[],
            missing_files=missing_files,
        ),
        artwork_intelligence=MieCorrelationArtworkIntelligence(references=artwork_refs),
        timeline=[
            MieCorrelationTimelineEvent(
                timestamp=datetime.now(UTC),
                source="test",
                event="created",
                confidence=90,
            )
        ],
        health=MieCorrelationHealthSummary(
            categories=[
                MieCorrelationHealthCategory(
                    key="integrity",
                    status="warn" if health_score < 80 else "good",
                    score=health_score,
                    reasons=[],
                )
            ],
            overall_health_score=health_score,
        ),
    )


def test_issue_detector_detects_missing_request_and_artwork_gap() -> None:
    graph = _graph(request_state="unknown", with_poster=False)

    issues = IssueDetector().evaluate(graph).issues
    issue_types = {item.issue_type for item in issues}

    assert "missing_request" in issue_types
    assert "artwork_gap" in issue_types


def test_issue_detector_detects_failed_import_and_filesystem_inconsistency() -> None:
    graph = _graph(missing_files=1, torrent_state="failed", raw_torrent_state="error")

    issues = IssueDetector().evaluate(graph).issues
    issue_types = {item.issue_type for item in issues}

    assert "failed_import" in issue_types
    assert "filesystem_inconsistency" in issue_types


def test_issue_detector_detects_torrent_stalled() -> None:
    graph = _graph(torrent_state="queued", raw_torrent_state="stalledDL")

    issues = IssueDetector().evaluate(graph).issues
    issue_types = {item.issue_type for item in issues}

    assert "torrent_stalled" in issue_types


def test_issue_detector_detects_duplicate_identity_pattern() -> None:
    graph = _graph(request_state="unknown", has_arr=True)

    issues = IssueDetector().evaluate(graph).issues
    issue_types = {item.issue_type for item in issues}

    assert "duplicate_identity" in issue_types


def test_operations_engine_health_and_graph_summary() -> None:
    graphs = [
        _graph(request_state="unknown", missing_files=1, with_poster=False),
        _graph(media_id=202, request_state="known", with_poster=True),
    ]

    result = OperationsEngine().run(graphs)

    assert result.graph_summary.total_media == 2
    assert result.graph_summary.movies == 2
    assert result.graph_summary.with_missing_files == 1
    assert result.overall_health < 100
    assert result.confidence.score > 0
