from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.enums import MediaType


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
