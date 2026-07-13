from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DuplicateDetector:
    """Detects duplicate releases/torrents/files across indexed entities."""

    async def detect(self) -> int:
        return 0
