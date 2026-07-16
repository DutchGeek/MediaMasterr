from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import require_admin
from backend.core.service_manager import service_manager
from backend.database import get_db
from backend.database.models import User
from backend.models.qbittorrent import (
    QBittorrentMetrics,
    QBittorrentOverviewResponse,
    QBittorrentTorrentItem,
)
from backend.services.correlation import MediaCorrelationService
from backend.services.media_asset_artwork import media_asset_artwork_resolver

router = APIRouter(prefix="/api/qbittorrent", tags=["qbittorrent"])
_correlation_service = MediaCorrelationService()


def _state_is_active_download(state: str, download_speed: int) -> bool:
    lowered = state.lower()
    return download_speed > 0 or "down" in lowered


def _state_is_active_upload(state: str, upload_speed: int) -> bool:
    lowered = state.lower()
    return upload_speed > 0 or "up" in lowered or "seed" in lowered


def _state_is_paused(state: str) -> bool:
    return state.lower().startswith("paused")


def _state_is_stalled(state: str) -> bool:
    return "stalled" in state.lower()


def _state_is_seeding(state: str) -> bool:
    lowered = state.lower()
    return "upload" in lowered or "seed" in lowered


@router.get("/overview", response_model=QBittorrentOverviewResponse)
async def get_qbittorrent_overview(
    _current_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> QBittorrentOverviewResponse:
    client = service_manager.qbittorrent
    if client is None:
        raise HTTPException(
            status_code=404,
            detail="qBittorrent is not configured or not enabled",
        )

    app_version = await client.get_app_version()
    webapi_version = await client.get_webapi_version()
    transfer_info = await client.get_transfer_info()
    torrents_raw = await client.get_torrents()

    torrents: list[QBittorrentTorrentItem] = []
    active_downloads = 0
    active_uploads = 0
    seeding = 0
    paused = 0
    completed = 0
    stalled = 0

    torrent_rows: list[tuple[dict[str, Any], Any, Any]] = []
    for index, item in enumerate(torrents_raw):
        if not isinstance(item, dict):
            continue
        torrent_summary = _correlation_service.torrent_summary_from_raw(item, index=index)
        correlated_artwork = await _correlation_service.resolve_torrent_artwork(
            db,
            torrent_summary,
        )
        torrent_rows.append((item, torrent_summary, correlated_artwork))

    for item, torrent_summary, correlated_artwork in torrent_rows:
        state = str(item.get("state") or "")
        progress = float(item.get("progress") or 0)
        download_speed = int(item.get("dlspeed") or 0)
        upload_speed = int(item.get("upspeed") or 0)

        if _state_is_active_download(state, download_speed):
            active_downloads += 1
        if _state_is_active_upload(state, upload_speed):
            active_uploads += 1
        if _state_is_seeding(state):
            seeding += 1
        if _state_is_paused(state):
            paused += 1
        if progress >= 1:
            completed += 1
        if _state_is_stalled(state):
            stalled += 1

        size_value = item.get("size") or item.get("total_size") or 0
        resolved_artwork = await media_asset_artwork_resolver.resolve(
            db,
            context="qbittorrent.overview",
            media_type=correlated_artwork.media_type,
            media_id=correlated_artwork.media_id,
            provider_poster_url=correlated_artwork.poster_url,
            provider_backdrop_url=correlated_artwork.backdrop_url,
            fallback_reason=correlated_artwork.reason,
        )

        torrents.append(
            QBittorrentTorrentItem(
                id=torrent_summary.id,
                name=str(item.get("name") or ""),
                category=str(item.get("category") or ""),
                state=state,
                progress=progress,
                size=int(size_value or 0),
                ratio=float(item.get("ratio") or 0),
                eta=int(item.get("eta") or 0),
                download_speed=download_speed,
                upload_speed=upload_speed,
                tracker=(
                    str(item.get("tracker") or item.get("tracker_domain"))
                    if isinstance(item.get("tracker") or item.get("tracker_domain"), str)
                    else None
                ),
                save_path=(
                    str(item.get("save_path"))
                    if isinstance(item.get("save_path"), str)
                    else None
                ),
                imported_status=(
                    "Imported"
                    if correlated_artwork.media_id is not None and progress >= 0.999
                    else "Correlated"
                    if correlated_artwork.media_id is not None
                    else "Pending"
                    if progress < 0.999
                    else "Unmapped"
                ),
                correlation_reason=correlated_artwork.reason or "unmapped",
                poster_url=resolved_artwork.poster_url,
                backdrop_url=resolved_artwork.backdrop_url,
            )
        )

    metrics = QBittorrentMetrics(
        active_downloads=active_downloads,
        active_uploads=active_uploads,
        seeding=seeding,
        paused=paused,
        completed=completed,
        stalled=stalled,
        download_speed=int(transfer_info.get("dl_info_speed") or 0),
        upload_speed=int(transfer_info.get("up_info_speed") or 0),
    )

    torrents.sort(key=lambda row: (row.state.lower(), row.name.lower()))

    return QBittorrentOverviewResponse(
        app_version=app_version,
        webapi_version=webapi_version,
        metrics=metrics,
        torrents=torrents,
    )
