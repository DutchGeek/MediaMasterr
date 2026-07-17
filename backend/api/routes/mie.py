from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.dashboard import build_dashboard_response
from backend.core.auth import require_page_access
from backend.database import get_db
from backend.database.models import User
from backend.enums import MediaType, PageAccess
from backend.models.dashboard import DashboardResponse
from backend.models.mie import (
    IdentityActionResponse,
    IdentityCanonicalSelectionRequest,
    IdentityOverrideUpsertRequest,
    IdentityStudioResponse,
    IdentitySyncHistoryResponse,
    IdentitySyncJobResponse,
    IdentitySyncPreviewResponse,
    IdentityWorkspaceResponse,
    MieOverviewResponse,
    MieRelationshipGraphResponse,
    MieTimelineResponse,
    OperationsRecommendationsResponse,
    OperationsWorkspaceResponse,
)
from backend.services.mie.identity_service import IdentityCenterService
from backend.services.mie.intelligence_service import MediaIntelligenceService
from backend.services.mie.operations_service import OperationsService

router = APIRouter(prefix="/api/mie", tags=["mie"])


@router.get("/dashboard", response_model=DashboardResponse)
async def get_mie_dashboard(
    current_user: Annotated[User, Depends(require_page_access(PageAccess.DASHBOARD))],
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    return await build_dashboard_response(current_user, db)


@router.get("/operations", response_model=OperationsWorkspaceResponse)
async def get_mie_operations(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> OperationsWorkspaceResponse:
    return await OperationsService(db).workspace()


@router.get("/recommendations", response_model=OperationsRecommendationsResponse)
async def get_mie_recommendations(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> OperationsRecommendationsResponse:
    return await OperationsService(db).recommendations()


@router.get("/intelligence", response_model=MieOverviewResponse)
async def get_mie_intelligence_overview(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> MieOverviewResponse:
    return await MediaIntelligenceService(db).overview()


@router.get("/timeline", response_model=MieTimelineResponse)
async def get_mie_timeline(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    limit: int = 80,
) -> MieTimelineResponse:
    return await MediaIntelligenceService(db).timeline(limit=limit)


@router.get(
    "/relationships/{media_type}/{media_id}",
    response_model=MieRelationshipGraphResponse,
)
async def get_mie_relationship_graph(
    media_type: MediaType,
    media_id: int,
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> MieRelationshipGraphResponse:
    return await MediaIntelligenceService(db).relationships(
        media_type=media_type,
        media_id=media_id,
    )


@router.get("/identity", response_model=IdentityWorkspaceResponse)
async def get_identity_workspace(
    _user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
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
    return await IdentityCenterService(db).workspace(
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


@router.get(
    "/identity/{media_type}/{media_id}/studio",
    response_model=IdentityStudioResponse,
)
async def get_identity_studio(
    media_type: MediaType,
    media_id: int,
    _user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
) -> IdentityStudioResponse:
    return await IdentityCenterService(db).studio(
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
) -> IdentityActionResponse:
    return await IdentityCenterService(db).set_canonical_provider(
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
) -> IdentityActionResponse:
    return await IdentityCenterService(db).upsert_override(
        media_type=media_type,
        media_id=media_id,
        payload=payload,
        user_id=current_user.id,
    )


@router.get("/identity/sync-preview", response_model=IdentitySyncPreviewResponse)
async def get_identity_sync_preview(
    _user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
) -> IdentitySyncPreviewResponse:
    return await IdentityCenterService(db).sync_preview()


@router.post("/identity/sync", response_model=IdentitySyncJobResponse)
async def start_identity_sync(
    current_user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
) -> IdentitySyncJobResponse:
    return await IdentityCenterService(db).start_sync(user_id=current_user.id)


@router.get("/identity/sync-history", response_model=IdentitySyncHistoryResponse)
async def get_identity_sync_history(
    _user: Annotated[User, Depends(require_page_access(PageAccess.IDENTITY))],
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
) -> IdentitySyncHistoryResponse:
    return await IdentityCenterService(db).sync_history(limit=limit)
