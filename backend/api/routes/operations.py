from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import require_page_access
from backend.database import get_db
from backend.database.models import FilesystemRoot, MieSettings, User
from backend.enums import PageAccess
from backend.models.mie import (
    CleanupPlanListResponse,
    FilesystemConfigResponse,
    FilesystemConfigUpdateRequest,
    OperationAuditListResponse,
    OperationsOverviewResponse,
    OperationsRecommendationsResponse,
    OperationsWorkspaceResponse,
    OperationWorkflowResponse,
)
from backend.services.mie.operations_service import OperationsService

router = APIRouter(prefix="/api/operations", tags=["operations"])


@router.get("/overview", response_model=OperationsOverviewResponse)
async def get_operations_overview(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> OperationsOverviewResponse:
    return await OperationsService(db).overview()


@router.get("/workspace", response_model=OperationsWorkspaceResponse)
async def get_operations_workspace_compat(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> OperationsWorkspaceResponse:
    """Compatibility endpoint for legacy clients expecting /api/operations/workspace."""
    return await OperationsService(db).workspace()


@router.get("/recommendations", response_model=OperationsRecommendationsResponse)
async def get_operations_recommendations(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> OperationsRecommendationsResponse:
    return await OperationsService(db).recommendations()


@router.get("/filesystem", response_model=FilesystemConfigResponse)
async def get_filesystem_config(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> FilesystemConfigResponse:
    return await OperationsService(db).filesystem_config()


@router.put("/filesystem", response_model=FilesystemConfigResponse)
async def update_filesystem_config(
    payload: FilesystemConfigUpdateRequest,
    user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> FilesystemConfigResponse:
    settings = (
        (await db.execute(select(MieSettings).order_by(MieSettings.id.asc())))
        .scalars()
        .first()
    )
    if settings is None:
        settings = MieSettings(
            filesystem_access_mode=payload.access_mode,
            updated_by_user_id=user.id,
        )
        db.add(settings)
    else:
        settings.filesystem_access_mode = payload.access_mode
        settings.updated_by_user_id = user.id

    await db.execute(sql_delete(FilesystemRoot))
    for root in payload.roots:
        db.add(
            FilesystemRoot(
                name=root.name.strip(),
                path=root.path.strip(),
                media_type=root.media_type,
                enabled=root.enabled,
            )
        )
    await db.commit()

    return await OperationsService(db).filesystem_config()


@router.get("/cleanup-plans", response_model=CleanupPlanListResponse)
async def get_cleanup_plans(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> CleanupPlanListResponse:
    return await OperationsService(db).cleanup_plans()


@router.get(
    "/recommendations/{recommendation_id}/preview",
    response_model=OperationWorkflowResponse,
)
async def preview_recommendation_operation(
    recommendation_id: str,
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> OperationWorkflowResponse:
    return await OperationsService(db).recommendation_preview(recommendation_id)


@router.get(
    "/recommendations/{recommendation_id}/validate",
    response_model=OperationWorkflowResponse,
)
async def validate_recommendation_operation(
    recommendation_id: str,
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> OperationWorkflowResponse:
    return await OperationsService(db).recommendation_validate(recommendation_id)


@router.post(
    "/recommendations/{recommendation_id}/execute",
    response_model=OperationWorkflowResponse,
)
async def execute_recommendation_operation(
    recommendation_id: str,
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> OperationWorkflowResponse:
    return await OperationsService(db).recommendation_execute(recommendation_id)


@router.get("/audit", response_model=OperationAuditListResponse)
async def get_operations_audit_log(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> OperationAuditListResponse:
    return await OperationsService(db).audit_log()
