from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


ArtworkStatus = Literal[
    "VALID",
    "MISSING",
    "PLACEHOLDER",
    "INVALID",
    "STALE",
    "NEEDS_REFRESH",
]


class ArtworkSelection(BaseModel):
    poster: str | None = None
    background: str | None = None
    banner: str | None = None
    logo: str | None = None
    source: str = "unresolved"
    confidence: float = 0.0
    status: ArtworkStatus = "MISSING"
    validated: bool = False
    reason: str | None = None
    last_refreshed_at: datetime | None = None
