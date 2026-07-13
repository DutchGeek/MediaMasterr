from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MediaIndex:
    """Unified media object index from ARR/media-server sources."""

    async def refresh(self) -> int:
        return 0
