from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FilesystemIndexer:
    """Filesystem discovery/indexing facade for Media Intelligence Engine."""

    cache_enabled: bool = True

    async def scan(self) -> int:
        """Run index refresh and return number of indexed entries."""
        return 0
