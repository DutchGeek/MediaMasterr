from __future__ import annotations

from datetime import datetime

from backend.models.mie import MieMediaGraphResponse
from backend.services.mie.issue_detector import IssueDetector
from backend.services.mie.operations_models import (
    DetectedIssue,
    HealthCategoryResult,
    OperationsConfidenceResult,
    OperationsGraphSummaryResult,
    OperationsIntelligenceResult,
)


class OperationsEngine:
    """Build operations intelligence from correlation graph snapshots only."""

    def __init__(self, detector: IssueDetector | None = None) -> None:
        self._detector = detector or IssueDetector()

    def run(self, graphs: list[MieMediaGraphResponse]) -> OperationsIntelligenceResult:
        all_issues = []
        graph_summary = OperationsGraphSummaryResult(total_media=len(graphs))
        timeline_rows: list[tuple[datetime, str, str, int]] = []
        confidence_factors: list[str] = []

        for graph in graphs:
            if graph.media_type.value == "movie":
                graph_summary.movies += 1
            else:
                graph_summary.series += 1

            if graph.request_intelligence.requests:
                graph_summary.with_requests += 1
            if graph.torrent_intelligence.torrents:
                graph_summary.with_torrents += 1
            if graph.file_intelligence.missing_files > 0:
                graph_summary.with_missing_files += 1
            has_poster = any(
                row.artwork_type == "poster"
                for row in graph.artwork_intelligence.references
            )
            if not has_poster:
                graph_summary.with_artwork_gaps += 1

            issue_result = self._detector.evaluate(graph)
            all_issues.extend(issue_result.issues)

            for event in graph.timeline[:2]:
                timeline_rows.append(
                    (
                        event.timestamp,
                        event.event,
                        f"{event.source} • confidence {event.confidence}",
                        graph.media_id,
                    )
                )

            confidence_factors.append(f"health:{graph.health.overall_health_score}")
            confidence_factors.append(f"issues:{len(issue_result.issues)}")

        overall_health, categories = self._compute_health(all_issues, len(graphs))

        timeline_rows.sort(key=lambda row: row[0], reverse=True)
        timeline_rows = timeline_rows[:10]

        confidence = self._compute_confidence(graphs, all_issues, confidence_factors)

        return OperationsIntelligenceResult(
            issues=all_issues,
            health_categories=categories,
            overall_health=overall_health,
            graph_summary=graph_summary,
            confidence=confidence,
            timeline_highlights=timeline_rows,
        )

    def _compute_health(
        self,
        issues: list[DetectedIssue],
        total_graphs: int,
    ) -> tuple[int, list[HealthCategoryResult]]:
        if total_graphs == 0:
            return (
                100,
                [
                    HealthCategoryResult(
                        key="coverage",
                        score=100,
                        reasons=["No media assets available for operations review."],
                    )
                ],
            )

        critical_count = sum(1 for issue in issues if issue.severity == "critical")
        high_count = sum(1 for issue in issues if issue.severity == "high")
        medium_count = sum(1 for issue in issues if issue.severity == "medium")
        low_count = sum(1 for issue in issues if issue.severity == "low")

        penalty = (
            critical_count * 28 + high_count * 18 + medium_count * 10 + low_count * 5
        )
        baseline = max(10, 100 - min(90, penalty // max(total_graphs, 1)))

        categories = [
            HealthCategoryResult(
                key="integrity",
                score=baseline,
                reasons=[
                    f"Detected {len(issues)} issue(s) across {total_graphs} assets."
                ],
                warnings=[
                    f"{medium_count} medium severity issues"
                    if medium_count
                    else "No medium severity issues"
                ],
                critical_failures=[
                    f"{critical_count} critical issue(s) present"
                    if critical_count
                    else "None"
                ],
            ),
            HealthCategoryResult(
                key="stability",
                score=max(0, baseline - high_count * 3),
                reasons=[
                    "Health score derived from graph issue severity distribution."
                ],
            ),
        ]
        return baseline, categories

    def _compute_confidence(
        self,
        graphs: list[MieMediaGraphResponse],
        issues: list[DetectedIssue],
        factors: list[str],
    ) -> OperationsConfidenceResult:
        if not graphs:
            return OperationsConfidenceResult(score=100, factors=["empty-dataset"])

        avg_health = sum(graph.health.overall_health_score for graph in graphs) // len(
            graphs
        )
        issue_penalty = min(35, len(issues) * 2)
        score = max(20, min(100, avg_health - issue_penalty + 10))
        uniq_factors = list(dict.fromkeys(factors))
        return OperationsConfidenceResult(score=score, factors=uniq_factors[:12])
