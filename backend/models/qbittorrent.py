from __future__ import annotations

from pydantic import BaseModel


class QBittorrentMetrics(BaseModel):
    active_downloads: int
    active_uploads: int
    seeding: int
    paused: int
    completed: int
    stalled: int
    download_speed: int
    upload_speed: int


class QBittorrentTorrentItem(BaseModel):
    name: str
    category: str
    state: str
    progress: float
    size: int
    ratio: float
    eta: int
    download_speed: int
    upload_speed: int
    tracker: str | None
    save_path: str | None
    poster_url: str | None = None
    backdrop_url: str | None = None


class QBittorrentOverviewResponse(BaseModel):
    app_version: str
    webapi_version: str
    metrics: QBittorrentMetrics
    torrents: list[QBittorrentTorrentItem]
