from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event, select

from backend.api.routes.dashboard import build_dashboard_response
from backend.database import async_db, engine
from backend.database.models import User
from backend.services.mie.correlation_engine import CorrelationEngine
from backend.services.mie.correlation_service import CorrelationService
from backend.services.mie.downloads_intelligence import DownloadsIntelligenceService
from backend.services.mie.operations_service import OperationsService
from backend.services.mie.request_context import MieRequestContext


@dataclass
class Metrics:
    duration_ms: float = 0.0
    sql_query_count: int = 0
    duplicate_sql_queries: int = 0
    graph_build_count: int = 0
    provider_execution_count: int = 0
    downloads_intelligence_runs: int = 0
    filesystem_scan_count: int = 0


class SqlTracker:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def handler(
        self,
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        self.statements.append(" ".join(statement.strip().split()))

    def snapshot(self) -> int:
        return len(self.statements)

    def delta(self, start: int) -> tuple[int, int]:
        segment = self.statements[start:]
        counter = Counter(segment)
        duplicates = sum(count - 1 for count in counter.values() if count > 1)
        return len(segment), duplicates


async def _profile_once(kind: str, use_context: bool) -> Metrics:
    tracker = SqlTracker()
    graph_build_count = 0
    provider_execution_count = 0
    downloads_runs = 0
    filesystem_scans = 0

    original_media_graph = CorrelationService.media_graph
    original_engine_run = CorrelationEngine.run
    original_downloads_run = DownloadsIntelligenceService.run
    original_downloads_roots = DownloadsIntelligenceService._downloads_roots

    async def wrapped_media_graph(self: CorrelationService, *args: Any, **kwargs: Any):
        nonlocal graph_build_count
        graph_build_count += 1
        return await original_media_graph(self, *args, **kwargs)

    async def wrapped_engine_run(self: CorrelationEngine, *args: Any, **kwargs: Any):
        nonlocal provider_execution_count
        provider_execution_count += len(self.providers)
        return await original_engine_run(self, *args, **kwargs)

    async def wrapped_downloads_run(
        self: DownloadsIntelligenceService, *args: Any, **kwargs: Any
    ):
        nonlocal downloads_runs
        downloads_runs += 1
        return await original_downloads_run(self, *args, **kwargs)

    async def wrapped_downloads_roots(
        self: DownloadsIntelligenceService, *args: Any, **kwargs: Any
    ):
        nonlocal filesystem_scans
        filesystem_scans += 1
        return await original_downloads_roots(self, *args, **kwargs)

    CorrelationService.media_graph = wrapped_media_graph  # type: ignore[assignment]
    CorrelationEngine.run = wrapped_engine_run  # type: ignore[assignment]
    DownloadsIntelligenceService.run = wrapped_downloads_run  # type: ignore[assignment]
    DownloadsIntelligenceService._downloads_roots = wrapped_downloads_roots  # type: ignore[assignment]

    event.listen(engine.sync_engine, "before_cursor_execute", tracker.handler)

    try:
        async with async_db() as db:
            user = (
                (await db.execute(select(User).order_by(User.id.asc()).limit(1)))
                .scalars()
                .first()
            )
            if user is None:
                raise RuntimeError("No user available for profiling")

            context = MieRequestContext() if use_context else None
            start_query = tracker.snapshot()
            started = time.perf_counter()

            if kind == "dashboard":
                await build_dashboard_response(user, db, request_context=context)
            elif kind == "operations":
                await OperationsService(db, request_context=context).workspace()
            elif kind == "identity":
                await OperationsService(db, request_context=context).workspace()
                # Identity path is measured via identity health contribution in workspace.
            else:
                raise ValueError(f"Unsupported profile kind: {kind}")

            elapsed = (time.perf_counter() - started) * 1000
            query_count, duplicate_queries = tracker.delta(start_query)

            metrics = Metrics(
                duration_ms=round(elapsed, 2),
                sql_query_count=query_count,
                duplicate_sql_queries=duplicate_queries,
                graph_build_count=graph_build_count,
                provider_execution_count=provider_execution_count,
                downloads_intelligence_runs=downloads_runs,
                filesystem_scan_count=filesystem_scans,
            )
            if context is not None:
                metrics.graph_build_count = int(
                    context.telemetry.get(
                        "graph_build_count", metrics.graph_build_count
                    )
                )
                metrics.provider_execution_count = int(
                    context.telemetry.get(
                        "provider_execution_count", metrics.provider_execution_count
                    )
                )
                metrics.downloads_intelligence_runs = int(
                    context.telemetry.get(
                        "downloads_intelligence_runs",
                        metrics.downloads_intelligence_runs,
                    )
                )
                metrics.filesystem_scan_count = int(
                    context.telemetry.get(
                        "filesystem_scan_count", metrics.filesystem_scan_count
                    )
                )
            return metrics
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", tracker.handler)
        CorrelationService.media_graph = original_media_graph  # type: ignore[assignment]
        CorrelationEngine.run = original_engine_run  # type: ignore[assignment]
        DownloadsIntelligenceService.run = original_downloads_run  # type: ignore[assignment]
        DownloadsIntelligenceService._downloads_roots = original_downloads_roots  # type: ignore[assignment]


async def main() -> None:
    report: dict[str, Any] = {"dashboard": {}, "operations": {}}
    for scope in ("dashboard", "operations"):
        before = await _profile_once(scope, use_context=False)
        after = await _profile_once(scope, use_context=True)
        report[scope] = {
            "before": before.__dict__,
            "after": after.__dict__,
        }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
