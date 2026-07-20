from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.enums import MediaType
from backend.models.artwork import ArtworkSelection

FilesystemAccessMode = Literal["discovery", "assisted", "automated"]
SafetyLevel = Literal["safe", "low_risk", "medium_risk", "high_risk"]
ActionManifestCategory = Literal[
    "safe",
    "maintenance",
    "recovery",
    "external",
    "destructive",
]
ActionManifestRisk = Literal["safe", "medium", "high"]


class OperationActionManifestAction(BaseModel):
    id: str
    label: str
    category: ActionManifestCategory
    risk: ActionManifestRisk
    confirmation: bool = False
    description: str | None = None
    impact_preview: list[str] = Field(default_factory=list)
    automation: Literal["manual", "automated", "hybrid"] = "automated"
    kind: Literal[
        "filesystem",
        "identity",
        "metadata",
        "artwork",
        "collections",
        "operations",
        "external",
    ] = "operations"


class OperationActionManifest(BaseModel):
    available_actions: list[OperationActionManifestAction] = Field(default_factory=list)


class OperationsFileEvidence(BaseModel):
    key: str
    label: str
    path: str | None = None
    source: str | None = None
    state: Literal["available", "missing", "partial", "duplicate", "unavailable"] = (
        "unavailable"
    )
    explanation: str | None = None


class OperationsApplicationEvidence(BaseModel):
    role: str
    application: str
    status: Literal["linked", "unavailable"] = "unavailable"
    reference: str | None = None
    explanation: str


class OperationsRelationshipEvidence(BaseModel):
    key: str
    label: str
    value: str | None = None
    status: Literal["linked", "unavailable"] = "unavailable"
    explanation: str


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
    issue_key: str | None = None
    confidence: int | None = None
    graph_references: list[str] = Field(default_factory=list)
    media_type: MediaType | None = None
    action_manifest: OperationActionManifest = Field(default_factory=OperationActionManifest)


OperationsIssueSeverity = Literal["critical", "high", "medium", "low"]


class OperationsIssue(BaseModel):
    key: str
    issue_type: str
    severity: OperationsIssueSeverity
    confidence: int = 0
    media_type: MediaType
    media_id: int
    title: str
    reason: str
    recommendation: str
    suggested_remediation: str
    graph_references: list[str] = Field(default_factory=list)


class OperationsHealthCategory(BaseModel):
    key: str
    score: int = 0
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    critical_failures: list[str] = Field(default_factory=list)


class OperationsHealthSummary(BaseModel):
    categories: list[OperationsHealthCategory] = Field(default_factory=list)
    overall_health: int = 0
    reasons: list[str] = Field(default_factory=list)


class OperationsIssueSummary(BaseModel):
    total: int = 0
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


class OperationsGraphSummary(BaseModel):
    total_media: int = 0
    movies: int = 0
    series: int = 0
    with_requests: int = 0
    with_torrents: int = 0
    with_missing_files: int = 0
    with_artwork_gaps: int = 0


class OperationsTimelineSummary(BaseModel):
    highlights: list[MieTimelineEvent] = Field(default_factory=list)


class OperationsConfidenceSummary(BaseModel):
    score: int = 0
    factors: list[str] = Field(default_factory=list)


DownloadLifecycleState = Literal[
    "metadata_download",
    "queued",
    "downloading",
    "checking",
    "moving",
    "seeding",
    "imported",
    "orphaned",
    "stale",
    "failed",
    "unknown",
]

DownloadCleanupClassification = Literal[
    "safe_to_delete",
    "safe_to_archive",
    "needs_investigation",
    "failed_import",
    "duplicate_download",
    "abandoned_download",
    "none",
]


class DownloadLifecycleObject(BaseModel):
    path: str
    entry_type: str
    torrent: str | None = None
    owner: str | None = None
    media_identity: str | None = None
    media_type: MediaType | None = None
    media_id: int | None = None
    lifecycle_state: DownloadLifecycleState = "unknown"
    import_status: str = "unknown"
    library_path: str | None = None
    torrent_state: str | None = None
    import_state: str = "unknown"
    retention_policy: str = "none"
    retention_remaining_hours: int | None = None
    age_hours: int = 0
    size_bytes: int = 0
    last_activity_at: datetime | None = None
    associated_request: str | None = None
    associated_arr_record: str | None = None
    associated_timeline: list[str] = Field(default_factory=list)
    confidence_score: int = 0
    cleanup_classification: DownloadCleanupClassification = "none"
    cleanup_reason: str | None = None
    recommendation: str = "none"
    recoverable_space_bytes: int = 0


class DownloadsHealthSummary(BaseModel):
    active_downloads: int = 0
    waiting_for_import: int = 0
    retention_active: int = 0
    retention_expired: int = 0
    completed_waiting_for_import: int = 0
    completed_waiting_for_cleanup: int = 0
    imported_but_still_present: int = 0
    duplicate_downloads: int = 0
    failed_downloads: int = 0
    unknown_downloads: int = 0
    orphaned_downloads: int = 0
    safe_to_delete: int = 0
    total_download_space: int = 0
    recoverable_space: int = 0


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


class OperationExecutionSessionRequest(BaseModel):
    recommendation_ids: list[str] = Field(default_factory=list)


class OperationExecutionStageProgress(BaseModel):
    key: str
    label: str
    status: Literal["pending", "running", "completed", "failed", "skipped"] = (
        "pending"
    )
    detail: str | None = None


class OperationExecutionItemProgress(BaseModel):
    recommendation_id: str
    title: str
    target_type: str
    target_id: str | None = None
    status: Literal["pending", "running", "completed", "failed", "blocked"] = (
        "pending"
    )
    message: str = ""
    estimated_recovery_bytes: int = 0
    stages: list[OperationExecutionStageProgress] = Field(default_factory=list)
    operation_history_id: int | None = None


class OperationExecutionSummary(BaseModel):
    successful: int = 0
    warnings: int = 0
    failed: int = 0
    recovered_space_bytes: int = 0
    elapsed_ms: int = 0


class OperationExecutionSessionResponse(BaseModel):
    session_id: str
    status: Literal["queued", "running", "completed", "failed", "partial"] = "queued"
    total: int = 0
    completed: int = 0
    failed: int = 0
    warnings: int = 0
    remaining: int = 0
    current_asset_title: str | None = None
    current_step_label: str | None = None
    elapsed_ms: int = 0
    estimated_remaining_ms: int | None = None
    history_id: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    items: list[OperationExecutionItemProgress] = Field(default_factory=list)
    summary: OperationExecutionSummary = Field(default_factory=OperationExecutionSummary)


class OperationExecutionHistoryEntry(BaseModel):
    session_id: str
    history_id: int
    action: str
    status: str
    selected_count: int = 0
    successful: int = 0
    warnings: int = 0
    failed: int = 0
    recovered_space_bytes: int = 0
    elapsed_ms: int = 0
    created_at: datetime
    completed_at: datetime | None = None
    items: list[OperationExecutionItemProgress] = Field(default_factory=list)


class OperationExecutionHistoryListResponse(BaseModel):
    items: list[OperationExecutionHistoryEntry] = Field(default_factory=list)


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


WorkflowStageKey = Literal[
    "download",
    "import",
    "organize",
    "retention",
    "cleanup",
    "completed",
]


class OperationsWorkflowFilter(BaseModel):
    key: str
    title: str
    count: int = 0


class OperationsWorkflowAsset(BaseModel):
    id: str
    title: str
    year: int | None = None
    media_type: MediaType | None = None
    poster_url: str | None = None
    risk_level: str | None = None
    target_type: str
    target_id: str | None = None
    current_stage: WorkflowStageKey
    current_status: str
    library_location: str | None = None
    download_location: str | None = None
    torrent_state: str | None = None
    import_state: str | None = None
    retention_policy: str | None = None
    retention_remaining: str | None = None
    next_action: str
    recommendation: str
    confidence: int | None = None
    estimated_space_recovery: int = 0
    reason: str
    after_action: str | None = None
    graph_references: list[str] = Field(default_factory=list)
    policy_name: str | None = None
    filters: list[str] = Field(default_factory=list)
    action_manifest: OperationActionManifest = Field(default_factory=OperationActionManifest)
    case_summary: str | None = None
    expected_destination: str | None = None
    file_evidence: list[OperationsFileEvidence] = Field(default_factory=list)
    application_evidence: list[OperationsApplicationEvidence] = Field(default_factory=list)
    relationship_evidence: list[OperationsRelationshipEvidence] = Field(default_factory=list)


class OperationsWorkflowStage(BaseModel):
    key: WorkflowStageKey
    title: str
    description: str
    count: int = 0
    assets: list[OperationsWorkflowAsset] = Field(default_factory=list)


class OperationsWorkflowBoard(BaseModel):
    stages: list[OperationsWorkflowStage] = Field(default_factory=list)
    filters: list[OperationsWorkflowFilter] = Field(default_factory=list)


class MediaPolicyDefinition(BaseModel):
    key: str
    name: str
    classification: str
    destination_library: str
    retention_period_days: int
    cleanup_behavior: str
    remove_torrent: bool = True
    remove_download_folder: bool = True
    protection_rules: list[str] = Field(default_factory=list)
    minimum_ratio: float = 1.0
    minimum_seed_time_hours: int = 0


class OperationsWorkspaceResponse(BaseModel):
    overview: OperationsOverviewResponse
    recommendations: OperationsRecommendationsResponse
    filesystem: FilesystemConfigResponse
    cleanup_plans: CleanupPlanListResponse
    workflow: OperationsWorkflowBoard = Field(default_factory=OperationsWorkflowBoard)
    media_policies: list[MediaPolicyDefinition] = Field(default_factory=list)
    artwork_issues: ArtworkIssuesSummary | None = None
    health: OperationsHealthSummary = Field(default_factory=OperationsHealthSummary)
    issues: list[OperationsIssue] = Field(default_factory=list)
    issue_summary: OperationsIssueSummary = Field(default_factory=OperationsIssueSummary)
    graph_summary: OperationsGraphSummary = Field(default_factory=OperationsGraphSummary)
    timeline_summary: OperationsTimelineSummary = Field(default_factory=OperationsTimelineSummary)
    confidence: OperationsConfidenceSummary = Field(default_factory=OperationsConfidenceSummary)
    downloads_health: DownloadsHealthSummary = Field(default_factory=DownloadsHealthSummary)
    downloads: list[DownloadLifecycleObject] = Field(default_factory=list)


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


IdentityConflictLevel = Literal["none", "low", "medium", "high"]
IdentityStudioTab = Literal[
    "overview",
    "providers",
    "artwork",
    "metadata",
    "external_ids",
    "overrides",
    "history",
    "synchronization",
    "diagnostics",
]
IdentityArtworkState = Literal["present", "missing", "pending", "error"]


class IdentityWorkspaceItem(BaseModel):
    media_type: MediaType
    media_id: int
    title: str
    year: int | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    canonical_provider: str
    provider_count: int = 0
    provider_confidence: int = 0
    conflict_level: IdentityConflictLevel = "none"
    needs_review: bool = False
    artwork_status: str = "unknown"
    metadata_status: str = "unknown"
    identifier_status: str = "unknown"
    override_status: str = "none"
    last_synced_at: datetime | None = None
    status: str = "ready"


class IdentityWorkspaceResponse(BaseModel):
    items: list[IdentityWorkspaceItem] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    per_page: int = 24
    total_pages: int = 1
    generated_at: datetime


class IdentityProviderMatch(BaseModel):
    provider: str
    provider_item_id: str
    confidence: int = 0
    path_tail: str | None = None
    artwork_preview_url: str | None = None
    metadata_quality: str = "unknown"
    external_ids_count: int = 0
    collection_count: int = 0
    connection_status: str = "unknown"
    signals: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime | None = None
    is_canonical: bool = False


class IdentityFieldValue(BaseModel):
    provider: str
    value: str | None = None
    confidence: int = 0
    is_canonical: bool = False


class IdentityComparisonField(BaseModel):
    key: str
    label: str
    values: list[IdentityFieldValue] = Field(default_factory=list)


class IdentityArtworkProviderOption(BaseModel):
    provider: str
    image_url: str
    resolution: str | None = None
    last_updated: datetime | None = None
    confidence: int = 0
    selected: bool = False


class IdentityArtworkCard(BaseModel):
    key: str
    label: str
    state: IdentityArtworkState = "missing"
    selected_provider: str | None = None
    shared_across_providers: bool = False
    providers: list[IdentityArtworkProviderOption] = Field(default_factory=list)
    message: str | None = None


class IdentityArtworkProfileEntry(BaseModel):
    key: str
    label: str
    provider: str | None = None


class IdentityProviderComparisonRow(BaseModel):
    provider: str
    connection_status: str = "unknown"
    matched: bool = False
    identifiers: str
    metadata: str
    artwork: str
    health: str
    differences: list[str] = Field(default_factory=list)


class IdentityOverrideEntry(BaseModel):
    field: str
    value: str
    scope: Literal["media", "global"] = "media"
    reason: str | None = None
    created_at: datetime
    created_by_user_id: int | None = None


class IdentityHistoryEntry(BaseModel):
    id: int
    action: str
    result: str
    summary: str
    created_at: datetime


class IdentityStudioResponse(BaseModel):
    media_type: MediaType
    media_id: int
    title: str
    year: int | None = None
    canonical_provider: str
    overview: list[IdentityComparisonField] = Field(default_factory=list)
    providers: list[IdentityProviderMatch] = Field(default_factory=list)
    artwork: list[IdentityComparisonField] = Field(default_factory=list)
    artwork_cards: list[IdentityArtworkCard] = Field(default_factory=list)
    canonical_artwork_profile: list[IdentityArtworkProfileEntry] = Field(
        default_factory=list
    )
    provider_comparison: list[IdentityProviderComparisonRow] = Field(
        default_factory=list
    )
    metadata: list[IdentityComparisonField] = Field(default_factory=list)
    external_ids: list[IdentityComparisonField] = Field(default_factory=list)
    overrides: list[IdentityOverrideEntry] = Field(default_factory=list)
    history: list[IdentityHistoryEntry] = Field(default_factory=list)
    synchronization: list[IdentityComparisonField] = Field(default_factory=list)
    diagnostics: list[IdentityComparisonField] = Field(default_factory=list)
    override_field_options: list[str] = Field(default_factory=list)
    generated_at: datetime


class IdentityCanonicalSelectionRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=500)


class IdentityArtworkProviderSelectionRequest(BaseModel):
    artwork_field: Literal["poster", "backdrop", "logo", "banner"]
    provider: str = Field(min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=500)


class IdentityOverrideUpsertRequest(BaseModel):
    field: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=2048)
    scope: Literal["media", "global"] = "media"
    reason: str | None = Field(default=None, max_length=500)


class IdentityActionResponse(BaseModel):
    accepted: bool = True
    action: str
    message: str


class IdentitySyncPreviewResponse(BaseModel):
    target_count: int = 0
    changed_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    details: list[str] = Field(default_factory=list)


class IdentitySyncJobResponse(BaseModel):
    accepted: bool = True
    status: str = "queued"
    message: str
    operation_history_id: int | None = None


class IdentitySyncHistoryResponse(BaseModel):
    items: list[IdentityHistoryEntry] = Field(default_factory=list)


class MediaIdentitySummaryResponse(BaseModel):
    id: int
    media_type: MediaType
    media_id: int
    title: str
    year: int | None = None
    canonical_provider: str
    provider_confidence: int = 0
    identity_confidence: int = 0
    conflict_level: str = "none"
    needs_review: bool = False
    health_state: str = "healthy"
    lifecycle_state: str = "resolved"
    last_synced_at: datetime | None = None
    updated_at: datetime


class MediaIdentityListResponse(BaseModel):
    items: list[MediaIdentitySummaryResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    per_page: int = 50


class MediaIdentityProviderMappingResponse(BaseModel):
    id: int
    media_identity_id: int
    provider: str
    provider_item_id: str
    confidence: int = 0
    is_canonical: bool = False
    path_tail: str | None = None
    connection_status: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime


class MediaIdentityProviderMappingListResponse(BaseModel):
    items: list[MediaIdentityProviderMappingResponse] = Field(default_factory=list)
    total: int = 0


class MediaIdentityExternalIdResponse(BaseModel):
    id: int
    media_identity_id: int
    provider: str
    id_type: str
    id_value: str
    confidence: int = 0
    is_canonical: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime


class MediaIdentityExternalIdListResponse(BaseModel):
    items: list[MediaIdentityExternalIdResponse] = Field(default_factory=list)
    total: int = 0


class MediaIdentityRelationshipResponse(BaseModel):
    id: int
    source_identity_id: int
    target_identity_id: int
    relationship_type: str
    provider: str
    confidence: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime


class MediaIdentityTimelineEventResponse(BaseModel):
    id: int
    media_identity_id: int
    event_type: str
    summary: str
    severity: str
    source: str
    details: dict[str, Any] = Field(default_factory=dict)
    happened_at: datetime


class MediaIdentityDetailResponse(BaseModel):
    identity: MediaIdentitySummaryResponse
    providers: list[MediaIdentityProviderMappingResponse] = Field(default_factory=list)
    external_ids: list[MediaIdentityExternalIdResponse] = Field(default_factory=list)
    relationships: list[MediaIdentityRelationshipResponse] = Field(default_factory=list)
    timeline: list[MediaIdentityTimelineEventResponse] = Field(default_factory=list)


CorrelationHealthStatus = Literal["good", "warn", "risk"]
CorrelationTorrentState = Literal[
    "waiting",
    "queued",
    "downloading",
    "paused",
    "import_pending",
    "imported",
    "completed",
    "seeding",
    "missing",
    "failed",
    "orphaned",
    "blocked",
]


class MieCorrelationExternalIds(BaseModel):
    tmdb: str | None = None
    tvdb: str | None = None
    imdb: str | None = None
    anidb: str | None = None
    tvmaze: str | None = None
    trakt: str | None = None
    additional: dict[str, str] = Field(default_factory=dict)


class MieCorrelationIdentity(BaseModel):
    media_identity_id: int | None = None
    canonical_title: str
    canonical_ids: MieCorrelationExternalIds
    media_type: MediaType
    release_year: int | None = None
    canonical_provider: str | None = None


class MieCorrelationRequestRecord(BaseModel):
    request_id: str
    request_status: str
    request_user: str | None = None
    request_date: datetime | None = None
    approval_date: datetime | None = None
    request_source: str


class MieCorrelationRequestIntelligence(BaseModel):
    request_state: str = "unknown"
    requests: list[MieCorrelationRequestRecord] = Field(default_factory=list)


class MieCorrelationArrOwnershipRecord(BaseModel):
    provider: str
    internal_arr_id: str
    root_folder: str | None = None
    quality_profile: str | None = None
    tags: list[str] = Field(default_factory=list)
    monitored: bool | None = None
    import_status: str = "unknown"


class MieCorrelationArrIntelligence(BaseModel):
    ownership: list[MieCorrelationArrOwnershipRecord] = Field(default_factory=list)


class MieCorrelationTorrentRecord(BaseModel):
    torrent_hash: str | None = None
    torrent_name: str
    category: str | None = None
    download_client: str
    progress: float = 0.0
    download_speed: int = 0
    upload_speed: int = 0
    eta_seconds: int | None = None
    raw_state: str | None = None
    computed_state: CorrelationTorrentState


class MieCorrelationTorrentIntelligence(BaseModel):
    torrents: list[MieCorrelationTorrentRecord] = Field(default_factory=list)


class MieCorrelationFileRecord(BaseModel):
    path: str
    file_type: str
    size_bytes: int = 0
    last_modified: datetime | None = None


class MieCorrelationFileIntelligence(BaseModel):
    media_files: list[MieCorrelationFileRecord] = Field(default_factory=list)
    subtitles: list[MieCorrelationFileRecord] = Field(default_factory=list)
    nfo: list[MieCorrelationFileRecord] = Field(default_factory=list)
    artwork: list[MieCorrelationFileRecord] = Field(default_factory=list)
    extras: list[MieCorrelationFileRecord] = Field(default_factory=list)
    missing_files: int = 0
    unexpected_files: int = 0
    duplicate_files: int = 0
    total_size_bytes: int = 0
    last_modified: datetime | None = None


class MieCorrelationArtworkRecord(BaseModel):
    source: str
    artwork_type: str
    url: str


class MieCorrelationArtworkIntelligence(BaseModel):
    references: list[MieCorrelationArtworkRecord] = Field(default_factory=list)


class MieCorrelationTimelineEvent(BaseModel):
    timestamp: datetime
    source: str
    event: str
    confidence: int = 0


class MieCorrelationHealthCategory(BaseModel):
    key: str
    status: CorrelationHealthStatus
    score: int = 0
    reasons: list[str] = Field(default_factory=list)


class MieCorrelationHealthSummary(BaseModel):
    categories: list[MieCorrelationHealthCategory] = Field(default_factory=list)
    overall_health_score: int = 0


class MieMediaGraphResponse(BaseModel):
    media_id: int
    media_type: MediaType
    title: str
    graph_generated_at: datetime
    identity: MieCorrelationIdentity
    request_intelligence: MieCorrelationRequestIntelligence
    arr_intelligence: MieCorrelationArrIntelligence
    torrent_intelligence: MieCorrelationTorrentIntelligence
    file_intelligence: MieCorrelationFileIntelligence
    artwork_intelligence: MieCorrelationArtworkIntelligence
    timeline: list[MieCorrelationTimelineEvent] = Field(default_factory=list)
    health: MieCorrelationHealthSummary
