from __future__ import annotations

from collections.abc import Callable

from backend.models.mie import MieMediaGraphResponse
from backend.services.mie.issue_rules import (
    detect_artwork_gap,
    detect_duplicate_identity,
    detect_failed_import,
    detect_filesystem_inconsistency,
    detect_missing_request,
    detect_torrent_health,
)
from backend.services.mie.operations_models import DetectedIssue, IssueEvaluationResult

IssueRule = Callable[[MieMediaGraphResponse], DetectedIssue | None]


class IssueDetector:
    """Evaluates graph snapshots and emits explainable operations issues."""

    def __init__(self) -> None:
        self._rules: tuple[IssueRule, ...] = (
            detect_missing_request,
            detect_artwork_gap,
            detect_failed_import,
            detect_torrent_health,
            detect_filesystem_inconsistency,
            detect_duplicate_identity,
        )

    def evaluate(self, graph: MieMediaGraphResponse) -> IssueEvaluationResult:
        issues: list[DetectedIssue] = []
        for rule in self._rules:
            issue = rule(graph)
            if issue is not None:
                issues.append(issue)
        return IssueEvaluationResult(issues=issues)
