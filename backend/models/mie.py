from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.enums import MediaType
from backend.models.artwork import ArtworkSelection


FilesystemAccessMode = Literal["discovery", "assisted", "automated"]
SafetyLevel = Literal["safe", "low_risk", "medium_risk", "high_risk"]


class OperationsCard(BaseModel):
    key: str
    title: str
    description: str
    count: int = 0
    severity: Literal["info", "low", "medium", "high"] = "info"


class OperationsOverviewResponse(BaseModel):
    cards: list[OperationsCard] = Field(default_factory=list)
    generated_at: datetime


class OperationsRecommendation(BaseModel):
    id: str
    card_key: str
    title: str
    summary: str
    explanation: str | None = None
    reasons: list[str] = Field(default_factory=list)
    action: str
    safety_level: SafetyLevel
    target_type: str
    target_id: str | None = None
    estimated_recovery_bytes: int = 0
    poster_url: str | None = None
    artwork: ArtworkSelection | None = None


class ArtworkIssuesSummary(BaseModel):
    coverage_percent: float = 0.0
    healthy_count: int = 0
    missing_count: int = 0
    placeholder_count: int = 0
    invalid_count: int = 0
    stale_count: int = 0
    needs_refresh_count: int = 0
    collision_count: int = 0
    last_refresh_at: datetime | None = None


class OperationWorkflowPreview(BaseModel):
    target_count: int = 0
    estimated_recovery_bytes: int = 0
    details: list[str] = Field(default_factory=list)


class OperationWorkflowValidationCheck(BaseModel):
    label: str
    passed: bool
    detail: str


class OperationWorkflowValidation(BaseModel):
    checks: list[OperationWorkflowValidationCheck] = Field(default_factory=list)
    valid: bool = False


class OperationWorkflowExecution(BaseModel):
    executed: bool = False
    result: str = "pending"
    message: str = ""
    operation_history_id: int | None = None


class OperationWorkflowResponse(BaseModel):
    recommendation_id: str
    preview: OperationWorkflowPreview
    validation: OperationWorkflowValidation
    execution: OperationWorkflowExecution


class OperationAuditEntryResponse(BaseModel):
    id: int
    action: str
    target_type: str
    target_id: str | None = None
    result: str
    safety_level: str
    recovery_bytes: int
    created_at: datetime


class OperationAuditListResponse(BaseModel):
    items: list[OperationAuditEntryResponse] = Field(default_factory=list)


class OperationsRecommendationsResponse(BaseModel):
    items: list[OperationsRecommendation] = Field(default_factory=list)
    total: int = 0


class FilesystemRootConfigResponse(BaseModel):
    id: int
    name: str
    path: str
    media_type: MediaType | None = None
    enabled: bool = True


class FilesystemConfigResponse(BaseModel):
    access_mode: FilesystemAccessMode = "assisted"
    roots: list[FilesystemRootConfigResponse] = Field(default_factory=list)


class FilesystemRootUpsertRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=1024)
    media_type: MediaType | None = None
    enabled: bool = True


class FilesystemConfigUpdateRequest(BaseModel):
    access_mode: FilesystemAccessMode
    roots: list[FilesystemRootUpsertRequest] = Field(default_factory=list)


class CleanupPlanSummaryResponse(BaseModel):
    id: int
    name: str
    status: str
    operation_count: int
    estimated_recovery_bytes: int
    safe_count: int
    review_required_count: int
    created_at: datetime


class CleanupPlanListResponse(BaseModel):
    plans: list[CleanupPlanSummaryResponse] = Field(default_factory=list)


class OperationsWorkspaceResponse(BaseModel):
    overview: OperationsOverviewResponse
    recommendations: OperationsRecommendationsResponse
    filesystem: FilesystemConfigResponse
    cleanup_plans: CleanupPlanListResponse
    artwork_issues: ArtworkIssuesSummary | None = None


class MieHealthFactor(BaseModel):
    key: str
    label: str
    status: Literal["good", "warn", "risk"] = "good"
    score_delta: int = 0
    detail: str


class MieAssetHealthScore(BaseModel):
    score: int = 100
    state: Literal["excellent", "good", "fair", "poor", "critical"] = "excellent"
    reasons: list[str] = Field(default_factory=list)
    factors: list[MieHealthFactor] = Field(default_factory=list)


class MieLifecycleBucket(BaseModel):
    state: str
    count: int = 0


class MieOverviewResponse(BaseModel):
    generated_at: datetime
    total_assets: int = 0
    total_movies: int = 0
    total_series: int = 0
    overseerr_pending: int = 0
    overseerr_approved: int = 0
    overseerr_completed: int = 0
    lifecycle: list[MieLifecycleBucket] = Field(default_factory=list)
    health: MieAssetHealthScore


class MieTimelineEvent(BaseModel):
    id: str
    happened_at: datetime
    event_type: str
    title: str
    summary: str
    origin: str
    severity: Literal["info", "low", "medium", "high"] = "info"
    media_type: MediaType | None = None
    media_id: int | None = None


class MieTimelineResponse(BaseModel):
    items: list[MieTimelineEvent] = Field(default_factory=list)
    total: int = 0


class MieRelationshipNode(BaseModel):
    id: str
    kind: str
    label: str
    metadata: dict[str, str] = Field(default_factory=dict)


class MieRelationshipEdge(BaseModel):
    source: str
    target: str
    relation: str


class MieRelationshipGraphResponse(BaseModel):
    generated_at: datetime
    root: str
    nodes: list[MieRelationshipNode] = Field(default_factory=list)
    edges: list[MieRelationshipEdge] = Field(default_factory=list)
