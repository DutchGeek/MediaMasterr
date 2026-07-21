from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.utils.mie_request_context import get_mie_request_context
from backend.core.auth import require_page_access
from backend.database import get_db
from backend.database.models import User
from backend.enums import PageAccess
from backend.models.mie import (
    MigrationDiscoveryRequest,
    MigrationDiscoveryResponse,
    MigrationPlanRequest,
    MigrationPlanResponse,
    MigrationWorkspaceResponse,
)
from backend.services.mie.request_context import MieRequestContext
from backend.services.migration_center import MigrationCenterService

router = APIRouter(prefix="/api/migration-center", tags=["migration-center"])


@router.get("/workspace", response_model=MigrationWorkspaceResponse)
async def get_migration_center_workspace(
    _user: Annotated[
        User, Depends(require_page_access(PageAccess.MIGRATION_CENTER))
    ],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> MigrationWorkspaceResponse:
    return await MigrationCenterService(
        db, request_context=request_context
    ).workspace()


@router.post("/discovery", response_model=MigrationDiscoveryResponse)
async def post_migration_center_discovery(
    payload: MigrationDiscoveryRequest,
    _user: Annotated[
        User, Depends(require_page_access(PageAccess.MIGRATION_CENTER))
    ],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> MigrationDiscoveryResponse:
    return await MigrationCenterService(
        db, request_context=request_context
    ).discover(payload)


@router.post("/plan", response_model=MigrationPlanResponse)
async def post_migration_center_plan(
    payload: MigrationPlanRequest,
    _user: Annotated[
        User, Depends(require_page_access(PageAccess.MIGRATION_CENTER))
    ],
    db: AsyncSession = Depends(get_db),
    request_context: MieRequestContext = Depends(get_mie_request_context),
) -> MigrationPlanResponse:
    return await MigrationCenterService(db, request_context=request_context).plan(
        payload
    )