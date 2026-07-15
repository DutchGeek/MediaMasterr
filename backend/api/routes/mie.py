from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.routes.dashboard import build_dashboard_response
from backend.core.auth import require_page_access
from backend.database import get_db
from backend.database.models import User
from backend.enums import PageAccess
from backend.models.dashboard import DashboardResponse
from backend.models.mie import (
    OperationsRecommendationsResponse,
    OperationsWorkspaceResponse,
)
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