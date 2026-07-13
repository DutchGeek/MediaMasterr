from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DecisionEngineIntegration:
    """Adapter for feeding MIE findings into recommendation/decision outcomes."""

    async def evaluate(self) -> int:
        return 0
