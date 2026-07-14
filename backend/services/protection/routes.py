from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import get_current_user, require_admin
from backend.database import get_db
from backend.database.models import User

from .schemas import (
    ProtectionConfigRequest,
    ProtectionConfigResponse,
    ProtectionItemResponse,
    ProtectionProviderDefinitionResponse,
    ProtectionRuleResponse,
    ProtectionStatsResponse,
    ProtectionStatusResponse,
)
from .service import ProtectionService

router = APIRouter(prefix="/api/protection", tags=["protection"])


@router.get("/provider", response_model=ProtectionProviderDefinitionResponse)
async def get_protection_provider_definition(
    _admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> ProtectionProviderDefinitionResponse:
    return await ProtectionService(db).get_provider_definition()


@router.get("/config", response_model=ProtectionConfigResponse)
async def get_protection_config(
    _admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> ProtectionConfigResponse:
    return await ProtectionService(db).get_config()


@router.post("/config", response_model=ProtectionConfigResponse)
async def save_protection_config(
    body: ProtectionConfigRequest,
    _admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> ProtectionConfigResponse:
    return await ProtectionService(db).save_config(body)


@router.get("/status", response_model=ProtectionStatusResponse)
async def get_protection_status(
    _user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ProtectionStatusResponse:
    return await ProtectionService(db).get_status()


@router.get("/stats", response_model=ProtectionStatsResponse)
async def get_protection_stats(
    _user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> ProtectionStatsResponse:
    return await ProtectionService(db).get_stats()


@router.get("/rules", response_model=list[ProtectionRuleResponse])
async def get_protection_rules(
    _user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[ProtectionRuleResponse]:
    return await ProtectionService(db).get_rules()


@router.get("/items", response_model=list[ProtectionItemResponse])
async def get_protection_items(
    _user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> list[ProtectionItemResponse]:
    return await ProtectionService(db).get_items()


@router.post("/test", response_model=ProtectionStatusResponse)
async def test_protection_connection(
    body: ProtectionConfigRequest,
    _admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> ProtectionStatusResponse:
    return await ProtectionService(db).test_connection(body)


@router.post("/sync", response_model=ProtectionStatusResponse)
async def sync_protection_provider(
    _admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> ProtectionStatusResponse:
    return await ProtectionService(db).sync()
