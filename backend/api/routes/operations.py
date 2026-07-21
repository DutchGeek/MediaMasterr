from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.utils.mie_request_context import get_mie_request_context
from backend.core.auth import require_page_access
from backend.database import async_db, get_db
from backend.database.models import FilesystemRoot, MieSettings, User
from backend.enums import PageAccess
from backend.models.mie import (
    CleanupPlanListResponse,
    FilesystemConfigResponse,
    FilesystemConfigUpdateRequest,
    OperationAuditListResponse,
    OperationExecutionHistoryListResponse,
    OperationExecutionSessionRequest,
    OperationExecutionSessionResponse,
    OperationsOverviewResponse,
    OperationsRecommendationsResponse,
    OperationsWorkspaceResponse,
    OperationWorkflowResponse,
)
from backend.services.mie.operations_execution import operations_execution_manager
from backend.services.mie.operations_service import OperationsService
from backend.services.mie.request_context import MieRequestContext

router = APIRouter(prefix="/api/operations", tags=["operations"])


@router.get("/overview", response_model=OperationsOverviewResponse)
async def get_operations_overview(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> OperationsOverviewResponse:
    return await OperationsService(db, request_context=request_context).overview()


@router.get("/workspace", response_model=OperationsWorkspaceResponse)
async def get_operations_workspace_compat(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
    candidates_only: bool = False,
    arr_filter_ids: list[int] = Query(default_factory=list),
    decision_filter_ids: list[int] = Query(default_factory=list),
    smart_filter_ids: list[int] = Query(default_factory=list),
) -> OperationsWorkspaceResponse:
    """Compatibility endpoint for legacy clients expecting /api/operations/workspace."""
    return await OperationsService(
        db, request_context=request_context
    ).workspace_filtered(
        candidates_only=candidates_only,
        imported_filter_ids=arr_filter_ids,
        decision_filter_ids=decision_filter_ids,
        smart_filter_ids=smart_filter_ids,
    )


@router.get("/recommendations", response_model=OperationsRecommendationsResponse)
async def get_operations_recommendations(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> OperationsRecommendationsResponse:
    return await OperationsService(
        db, request_context=request_context
    ).recommendations()


@router.get("/filesystem", response_model=FilesystemConfigResponse)
async def get_filesystem_config(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> FilesystemConfigResponse:
    return await OperationsService(
        db, request_context=request_context
    ).filesystem_config()


@router.put("/filesystem", response_model=FilesystemConfigResponse)
async def update_filesystem_config(
    payload: FilesystemConfigUpdateRequest,
    user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
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

    return await OperationsService(
        db, request_context=request_context
    ).filesystem_config()


@router.get("/cleanup-plans", response_model=CleanupPlanListResponse)
async def get_cleanup_plans(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> CleanupPlanListResponse:
    return await OperationsService(db, request_context=request_context).cleanup_plans()


@router.get(
    "/recommendations/{recommendation_id}/preview",
    response_model=OperationWorkflowResponse,
)
async def preview_recommendation_operation(
    recommendation_id: str,
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> OperationWorkflowResponse:
    return await OperationsService(
        db, request_context=request_context
    ).recommendation_preview(recommendation_id)


@router.get(
    "/recommendations/{recommendation_id}/validate",
    response_model=OperationWorkflowResponse,
)
async def validate_recommendation_operation(
    recommendation_id: str,
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> OperationWorkflowResponse:
    return await OperationsService(
        db, request_context=request_context
    ).recommendation_validate(recommendation_id)


@router.post(
    "/recommendations/{recommendation_id}/execute",
    response_model=OperationWorkflowResponse,
)
async def execute_recommendation_operation(
    recommendation_id: str,
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> OperationWorkflowResponse:
    return await OperationsService(
        db, request_context=request_context
    ).recommendation_execute(recommendation_id)


@router.post("/executions", response_model=OperationExecutionSessionResponse)
async def create_execution_session(
    payload: OperationExecutionSessionRequest,
    user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> OperationExecutionSessionResponse:
    return await operations_execution_manager.start_session(
        service_factory=lambda session: OperationsService(
            session,
            request_context=request_context,
        ),
        session_factory=async_db,
        recommendation_ids=payload.recommendation_ids,
        created_by_user_id=user.id,
    )


@router.get("/executions/history", response_model=OperationExecutionHistoryListResponse)
async def get_execution_history(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
) -> OperationExecutionHistoryListResponse:
    return await operations_execution_manager.list_history(db)


@router.get(
    "/executions/{session_id}", response_model=OperationExecutionSessionResponse
)
async def get_execution_session(
    session_id: str,
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
) -> OperationExecutionSessionResponse:
    session = await operations_execution_manager.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown execution session '{session_id}'"
        )
    return session


@router.get("/audit", response_model=OperationAuditListResponse)
async def get_operations_audit_log(
    _user: Annotated[User, Depends(require_page_access(PageAccess.OPERATIONS))],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> OperationAuditListResponse:
    return await OperationsService(db, request_context=request_context).audit_log()
