from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

CorrelationStatus = Literal["known", "unknown"]


class CorrelationTorrentSummary(BaseModel):
    id: str
    hash: str | None
    name: str
    category: str | None
    state: str | None
    save_path: str | None
    provider: str


class CorrelationNode(BaseModel):
    stage: str
    label: str
    status: CorrelationStatus
    value: str
    provider: str | None = None
    path: str | None = None
    metadata: dict[str, Any] | None = None


class CorrelationResolvedFields(BaseModel):
    torrent: str
    series: str
    episode: str
    movie: str
    file: str
    media_server: str
    protection_status: str
    watch_status: str
    import_status: str
    provider: str
    storage_path: str


class CorrelationTorrentsResponse(BaseModel):
    items: list[CorrelationTorrentSummary]


class CorrelationDetailResponse(BaseModel):
    torrent: CorrelationTorrentSummary
    fields: CorrelationResolvedFields
    nodes: list[CorrelationNode]
