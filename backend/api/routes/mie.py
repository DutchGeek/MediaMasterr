from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.dashboard import build_dashboard_response
from backend.api.utils.mie_request_context import get_mie_request_context
from backend.core.auth import require_page_access
from backend.database import get_db
from backend.database.models import User
from backend.enums import MediaType, PageAccess
from backend.models.dashboard import DashboardResponse
from backend.models.mie import (
    IdentityActionResponse,
    IdentityArtworkProviderSelectionRequest,
    IdentityCanonicalSelectionRequest,
    IdentityOverrideUpsertRequest,
    IdentityStudioResponse,
    IdentitySyncHistoryResponse,
    IdentitySyncJobResponse,
    IdentitySyncPreviewResponse,
    IdentityWorkspaceResponse,
    MediaIdentityDetailResponse,
    MediaIdentityExternalIdListResponse,
    MediaIdentityListResponse,
    MediaIdentityProviderMappingListResponse,
    MieMediaGraphResponse,
    MieOverviewResponse,
    MieRelationshipGraphResponse,
    MieTimelineResponse,
    OperationsRecommendationsResponse,
    OperationsWorkspaceResponse,
)
from backend.services.mie.correlation_service import CorrelationService
from backend.services.mie.identity_service import IdentityCenterService
from backend.services.mie.intelligence_service import MediaIntelligenceService
from backend.services.mie.operations_service import OperationsService
from backend.services.mie.request_context import MieRequestContext

router = APIRouter(prefix="/api/mie", tags=["mie"])


@router.get("/dashboard", response_model=DashboardResponse)
async def get_mie_dashboard(
    current_user: Annotated[User, Depends(require_page_access(PageAccess.DASHBOARD))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> DashboardResponse:
    return await build_dashboard_response(
        current_user,
        db,
        request_context=request_context,
    )


@router.get("/operations", response_model=OperationsWorkspaceResponse)
async def get_mie_operations(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
    candidates_only: bool = False,
    arr_filter_ids: list[int] = Query(default_factory=list),
    decision_filter_ids: list[int] = Query(default_factory=list),
    smart_filter_ids: list[int] = Query(default_factory=list),
) -> OperationsWorkspaceResponse:
    return await OperationsService(db, request_context=request_context).workspace_filtered(
        candidates_only=candidates_only,
        imported_filter_ids=arr_filter_ids,
        decision_filter_ids=decision_filter_ids,
        smart_filter_ids=smart_filter_ids,
    )


@router.get("/recommendations", response_model=OperationsRecommendationsResponse)
async def get_mie_recommendations(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> OperationsRecommendationsResponse:
    return await OperationsService(
        db, request_context=request_context
    ).recommendations()


@router.get("/intelligence", response_model=MieOverviewResponse)
async def get_mie_intelligence_overview(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> MieOverviewResponse:
    return await MediaIntelligenceService(
        db, request_context=request_context
    ).overview()


@router.get("/timeline", response_model=MieTimelineResponse)
async def get_mie_timeline(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
    limit: int = 80,
) -> MieTimelineResponse:
    return await MediaIntelligenceService(
        db, request_context=request_context
    ).timeline(limit=limit)


@router.get(
    "/relationships/{media_type}/{media_id}",
    response_model=MieRelationshipGraphResponse,
)
async def get_mie_relationship_graph(
    media_type: MediaType,
    media_id: int,
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> MieRelationshipGraphResponse:
    return await MediaIntelligenceService(db, request_context=request_context).relationships(
        media_type=media_type,
        media_id=media_id,
    )


@router.get("/media/{media_id}/graph", response_model=MieMediaGraphResponse)
async def get_mie_media_graph(
    media_id: int,
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
    media_type: MediaType | None = None,
) -> MieMediaGraphResponse:
    try:
        return await CorrelationService(
            db, request_context=request_context
        ).media_graph(
            media_id=media_id,
            media_type=media_type,
        )
    except ValueError as exc:
        status_code = 409 if "Ambiguous media id" in str(exc) else 404
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/identity", response_model=IdentityWorkspaceResponse)
async def get_identity_workspace(
    _user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
    page: int = 1,
    per_page: int = 24,
    search: str | None = None,
    media_type: MediaType | None = None,
    sort_by: str = "title",
    sort_order: str = "asc",
    candidates_only: bool = False,
    arr_filter_ids: list[int] = Query(default_factory=list),
    decision_filter_ids: list[int] = Query(default_factory=list),
    smart_filter_ids: list[int] = Query(default_factory=list),
    min_confidence: int | None = None,
    max_confidence: int | None = None,
    canonical_provider: str | None = None,
    sync_status: str | None = None,
    artwork_status: str | None = None,
    metadata_status: str | None = None,
    identifier_status: str | None = None,
    override_status: str | None = None,
    conflict_level: str | None = None,
    needs_review: bool | None = None,
) -> IdentityWorkspaceResponse:
    return await IdentityCenterService(db, request_context=request_context).workspace(
        page=page,
        per_page=per_page,
        search=search,
        media_type=media_type,
        sort_by=sort_by,
        sort_order=sort_order,
        candidates_only=candidates_only,
        imported_filter_ids=arr_filter_ids,
        decision_filter_ids=decision_filter_ids,
        smart_filter_ids=smart_filter_ids,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        canonical_provider=canonical_provider,
        sync_status=sync_status,
        artwork_status=artwork_status,
        metadata_status=metadata_status,
        identifier_status=identifier_status,
        override_status=override_status,
        conflict_level=conflict_level,
        needs_review=needs_review,
    )


@router.get("/identity-canonical", response_model=MediaIdentityListResponse)
async def get_canonical_identity_rows(
    _user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
    page: int = 1,
    per_page: int = 50,
    media_type: MediaType | None = None,
    search: str | None = None,
) -> MediaIdentityListResponse:
    return await IdentityCenterService(
        db, request_context=request_context
    ).canonical_identities(
        page=page,
        per_page=per_page,
        media_type=media_type,
        search=search,
    )


@router.get("/identity/{identity_id}", response_model=MediaIdentityDetailResponse)
async def get_canonical_identity_detail(
    identity_id: int,
    _user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> MediaIdentityDetailResponse:
    try:
        return await IdentityCenterService(
            db, request_context=request_context
        ).canonical_identity_detail(
            identity_id=identity_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/providers", response_model=MediaIdentityProviderMappingListResponse)
async def get_canonical_identity_providers(
    _user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
    identity_id: int | None = None,
    provider: str | None = None,
) -> MediaIdentityProviderMappingListResponse:
    return await IdentityCenterService(
        db, request_context=request_context
    ).canonical_providers(
        identity_id=identity_id,
        provider=provider,
    )


@router.get("/external-ids", response_model=MediaIdentityExternalIdListResponse)
async def get_canonical_identity_external_ids(
    _user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
    identity_id: int | None = None,
    provider: str | None = None,
    id_type: str | None = None,
) -> MediaIdentityExternalIdListResponse:
    return await IdentityCenterService(
        db, request_context=request_context
    ).canonical_external_ids(
        identity_id=identity_id,
        provider=provider,
        id_type=id_type,
    )


@router.get(
    "/identity/{media_type}/{media_id}/studio",
    response_model=IdentityStudioResponse,
)
async def get_identity_studio(
    media_type: MediaType,
    media_id: int,
    _user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> IdentityStudioResponse:
    return await IdentityCenterService(db, request_context=request_context).studio(
        media_type=media_type,
        media_id=media_id,
    )


@router.post(
    "/identity/{media_type}/{media_id}/canonical",
    response_model=IdentityActionResponse,
)
async def set_identity_canonical_provider(
    media_type: MediaType,
    media_id: int,
    payload: IdentityCanonicalSelectionRequest,
    current_user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> IdentityActionResponse:
    return await IdentityCenterService(
        db, request_context=request_context
    ).set_canonical_provider(
        media_type=media_type,
        media_id=media_id,
        payload=payload,
        user_id=current_user.id,
    )


@router.post(
    "/identity/{media_type}/{media_id}/artwork-provider",
    response_model=IdentityActionResponse,
)
async def set_identity_artwork_provider(
    media_type: MediaType,
    media_id: int,
    payload: IdentityArtworkProviderSelectionRequest,
    current_user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> IdentityActionResponse:
    return await IdentityCenterService(
        db, request_context=request_context
    ).set_artwork_provider(
        media_type=media_type,
        media_id=media_id,
        payload=payload,
        user_id=current_user.id,
    )


@router.post(
    "/identity/{media_type}/{media_id}/overrides",
    response_model=IdentityActionResponse,
)
async def upsert_identity_override(
    media_type: MediaType,
    media_id: int,
    payload: IdentityOverrideUpsertRequest,
    current_user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> IdentityActionResponse:
    return await IdentityCenterService(
        db, request_context=request_context
    ).upsert_override(
        media_type=media_type,
        media_id=media_id,
        payload=payload,
        user_id=current_user.id,
    )


@router.get("/identity/sync-preview", response_model=IdentitySyncPreviewResponse)
async def get_identity_sync_preview(
    _user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> IdentitySyncPreviewResponse:
    return await IdentityCenterService(
        db, request_context=request_context
    ).sync_preview()


@router.post("/identity/sync", response_model=IdentitySyncJobResponse)
async def start_identity_sync(
    current_user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> IdentitySyncJobResponse:
    return await IdentityCenterService(
        db, request_context=request_context
    ).start_sync(user_id=current_user.id)


@router.get("/identity/sync-history", response_model=IdentitySyncHistoryResponse)
async def get_identity_sync_history(
    _user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
    limit: int = 50,
) -> IdentitySyncHistoryResponse:
    return await IdentityCenterService(
        db, request_context=request_context
    ).sync_history(limit=limit)
