from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from backend.enums import MediaType
from backend.models.mie import MieMediaGraphResponse

IssueSeverity = Literal["critical", "high", "medium", "low"]


@dataclass(slots=True)
class GraphEnvelope:
    graph: MieMediaGraphResponse


@dataclass(slots=True)
class DetectedIssue:
    key: str
    issue_type: str
    severity: IssueSeverity
    confidence: int
    media_type: MediaType
    media_id: int
    title: str
    reason: str
    recommendation: str
    remediation: str
    graph_references: list[str] = field(default_factory=list)
    estimated_recovery_bytes: int = 0
    action: str = "monitor"
    safety_level: Literal["safe", "low_risk", "medium_risk", "high_risk"] = "low_risk"


@dataclass(slots=True)
class IssueEvaluationResult:
    issues: list[DetectedIssue] = field(default_factory=list)


@dataclass(slots=True)
class HealthCategoryResult:
    key: str
    score: int
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    critical_failures: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OperationsGraphSummaryResult:
    total_media: int = 0
    movies: int = 0
    series: int = 0
    with_requests: int = 0
    with_torrents: int = 0
    with_missing_files: int = 0
    with_artwork_gaps: int = 0


@dataclass(slots=True)
class OperationsConfidenceResult:
    score: int = 0
    factors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OperationsIntelligenceResult:
    issues: list[DetectedIssue] = field(default_factory=list)
    health_categories: list[HealthCategoryResult] = field(default_factory=list)
    overall_health: int = 0
    graph_summary: OperationsGraphSummaryResult = field(
        default_factory=OperationsGraphSummaryResult
    )
    confidence: OperationsConfidenceResult = field(
        default_factory=OperationsConfidenceResult
    )
    timeline_highlights: list[tuple[datetime, str, str, int]] = field(
        default_factory=list
    )
