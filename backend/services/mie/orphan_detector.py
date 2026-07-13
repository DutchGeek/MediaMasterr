from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class OrphanDetector:
    """Detects orphaned torrents/files with no correlated media asset."""

    async def detect(self) -> int:
        return 0
