from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CleanupPlanner:
    """Builds reviewable cleanup plans instead of immediate destructive actions."""

    async def preview(self) -> int:
        return 0
