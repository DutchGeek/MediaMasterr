from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.enums import MediaType
from backend.models.mie import MieMediaGraphResponse


@dataclass(slots=True)
class MieRequestContext:
    """Per-request cache and counters for MIE service orchestration."""

    graph_cache: dict[tuple[MediaType, int], MieMediaGraphResponse] = field(
        default_factory=dict
    )
    graph_subjects: list[tuple[MediaType, int]] | None = None
    graph_intelligence: tuple[list[Any], Any] | None = None
    downloads_intelligence: Any | None = None
    identity_health_summary: dict[str, int | float] | None = None
    telemetry: dict[str, int] = field(
        default_factory=lambda: {
            "graph_build_count": 0,
            "provider_execution_count": 0,
            "downloads_intelligence_runs": 0,
            "filesystem_scan_count": 0,
        }
    )

    def increment(self, key: str, amount: int = 1) -> None:
        self.telemetry[key] = int(self.telemetry.get(key, 0)) + amount
