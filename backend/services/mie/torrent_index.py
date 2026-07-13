from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TorrentIndex:
    """Provider-agnostic torrent state index."""

    async def refresh(self) -> int:
        return 0
