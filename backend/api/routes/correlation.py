from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import require_admin
from backend.core.service_manager import service_manager
from backend.database import get_db
from backend.database.models import User
from backend.models.correlation import CorrelationDetailResponse, CorrelationTorrentsResponse
from backend.services.correlation import MediaCorrelationService

router = APIRouter(prefix="/api/correlation", tags=["correlation"])

_correlation_service = MediaCorrelationService()


def _require_qbittorrent_client() -> object:
    client = service_manager.qbittorrent
    if client is None:
        raise HTTPException(
            status_code=404,
            detail="qBittorrent is not configured or not enabled",
        )
    return client


@router.get("/torrents", response_model=CorrelationTorrentsResponse)
async def list_correlation_torrents(
    _current_user: Annotated[User, Depends(require_admin)],
) -> CorrelationTorrentsResponse:
    client = _require_qbittorrent_client()
    torrents_raw = await client.get_torrents()  # type: ignore[attr-defined]
    items = _correlation_service.build_torrent_summaries(torrents_raw)
    return CorrelationTorrentsResponse(items=items)


@router.get("/torrents/{torrent_id}", response_model=CorrelationDetailResponse)
async def get_torrent_correlation(
    torrent_id: str,
    _current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CorrelationDetailResponse:
    client = _require_qbittorrent_client()
    torrents_raw = await client.get_torrents()  # type: ignore[attr-defined]
    items = _correlation_service.build_torrent_summaries(torrents_raw)
    selected = next((item for item in items if item.id == torrent_id.lower()), None)
    if selected is None:
        raise HTTPException(status_code=404, detail="Torrent not found")
    return await _correlation_service.correlate_torrent(db, selected)
