from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.database.models import OperationHistory
from backend.models.mie import (
    OperationExecutionHistoryEntry,
    OperationExecutionHistoryListResponse,
    OperationExecutionItemProgress,
    OperationExecutionSessionResponse,
    OperationExecutionStageProgress,
    OperationExecutionSummary,
)

_PIPELINE_LABELS = {
    "filesystem": "Filesystem",
    "identity": "Identity",
    "metadata": "Metadata",
    "artwork": "Artwork",
    "collections": "Collections",
    "tags": "Tags",
    "plex_refresh": "Plex Refresh",
    "sonarr_update": "Sonarr Update",
    "radarr_update": "Radarr Update",
    "cleanup": "Cleanup",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _elapsed_ms(started_at: datetime | None, completed_at: datetime | None = None) -> int:
    if started_at is None:
        return 0
    end_time = completed_at or _utcnow()
    return max(0, int((end_time - started_at).total_seconds() * 1000))


def _pipeline_keys_for_recommendation(recommendation: Any) -> list[str]:
    action = str(getattr(recommendation, "action", "") or "").lower()
    card_key = str(getattr(recommendation, "card_key", "") or "").lower()
    target_type = str(getattr(recommendation, "target_type", "") or "").lower()

    steps = ["filesystem"]
    if target_type != "download_object":
        steps.append("identity")
    if any(token in card_key for token in ["artwork", "poster"]):
        steps.extend(["metadata", "artwork"])
    elif any(token in action for token in ["metadata", "rename", "repair", "match"]):
        steps.extend(["metadata", "artwork"])
    if any(token in action for token in ["collection", "library"]):
        steps.append("collections")
    if any(token in action for token in ["tag", "label"]):
        steps.append("tags")
    if target_type in {"series", "season", "episode"}:
        steps.append("sonarr_update")
    if target_type == "movie":
        steps.append("radarr_update")
    if target_type in {"movie", "series", "season", "episode"}:
        steps.append("plex_refresh")
    if any(token in action for token in ["delete", "remove", "detach", "cleanup"]):
        steps.append("cleanup")

    deduped: list[str] = []
    for step in steps:
        if step not in deduped:
            deduped.append(step)
    return deduped


def _stage_rows(keys: list[str]) -> list[OperationExecutionStageProgress]:
    return [
        OperationExecutionStageProgress(key=key, label=_PIPELINE_LABELS[key])
        for key in keys
    ]


@dataclass(slots=True)
class _SessionState:
    session_id: str
    history_id: int
    action: str
    created_at: datetime
    selected_ids: list[str]
    items: list[OperationExecutionItemProgress]
    status: str = "queued"
    completed: int = 0
    failed: int = 0
    warnings: int = 0
    current_asset_title: str | None = None
    current_step_label: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    recovered_space_bytes: int = 0
    task: asyncio.Task[None] | None = field(default=None, repr=False)


class OperationsExecutionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, _SessionState] = {}
        self._lock = asyncio.Lock()

    async def start_session(
        self,
        *,
        service_factory: Any,
        session_factory: async_sessionmaker[AsyncSession],
        recommendation_ids: list[str],
        created_by_user_id: int | None,
    ) -> OperationExecutionSessionResponse:
        async with session_factory() as db:
            service = service_factory(db)
            recommendations = await service.recommendations()
            by_id = {row.id: row for row in recommendations.items}
            selected = [by_id[row_id] for row_id in recommendation_ids if row_id in by_id]
            if not selected:
                raise ValueError("No matching recommendations found for execution")

            session_id = str(uuid4())
            created_at = _utcnow()
            items = [
                OperationExecutionItemProgress(
                    recommendation_id=row.id,
                    title=row.title,
                    target_type=row.target_type,
                    target_id=row.target_id,
                    estimated_recovery_bytes=row.estimated_recovery_bytes,
                    stages=_stage_rows(_pipeline_keys_for_recommendation(row)),
                )
                for row in selected
            ]
            history = OperationHistory(
                action="bulk_execute",
                target_type="execution_session",
                target_id=session_id,
                result="running",
                safety_level="mixed",
                recovery_bytes=sum(int(row.estimated_recovery_bytes or 0) for row in selected),
                created_by_user_id=created_by_user_id,
                metadata_json={
                    "session_id": session_id,
                    "selected_ids": recommendation_ids,
                    "selected_count": len(recommendation_ids),
                    "status": "running",
                    "successful": 0,
                    "warnings": 0,
                    "failed": 0,
                    "elapsed_ms": 0,
                    "items": [item.model_dump(mode="json") for item in items],
                },
            )
            db.add(history)
            await db.commit()
            await db.refresh(history)

        state = _SessionState(
            session_id=session_id,
            history_id=int(history.id),
            action="bulk_execute",
            created_at=created_at,
            selected_ids=list(recommendation_ids),
            items=items,
        )

        async with self._lock:
            self._sessions[session_id] = state

        state.task = asyncio.create_task(
            self._run_session(
                state=state,
                service_factory=service_factory,
                session_factory=session_factory,
                created_by_user_id=created_by_user_id,
            )
        )
        return self._to_response(state)

    async def get_session(self, session_id: str) -> OperationExecutionSessionResponse | None:
        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return None
            return self._to_response(state)

    async def list_history(
        self, db: AsyncSession, *, limit: int = 50
    ) -> OperationExecutionHistoryListResponse:
        rows = (
            (
                await db.execute(
                    select(OperationHistory)
                    .where(OperationHistory.target_type == "execution_session")
                    .order_by(OperationHistory.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        items: list[OperationExecutionHistoryEntry] = []
        for row in rows:
            metadata = row.metadata_json or {}
            item_rows = [
                OperationExecutionItemProgress.model_validate(item)
                for item in list(metadata.get("items", []))
                if isinstance(item, dict)
            ]
            completed_at = None
            completed_raw = metadata.get("completed_at")
            if isinstance(completed_raw, str):
                try:
                    completed_at = datetime.fromisoformat(completed_raw)
                except ValueError:
                    completed_at = None
            items.append(
                OperationExecutionHistoryEntry(
                    session_id=str(metadata.get("session_id") or row.target_id or row.id),
                    history_id=int(row.id),
                    action=row.action,
                    status=str(metadata.get("status") or row.result),
                    selected_count=int(metadata.get("selected_count") or 0),
                    successful=int(metadata.get("successful") or 0),
                    warnings=int(metadata.get("warnings") or 0),
                    failed=int(metadata.get("failed") or 0),
                    recovered_space_bytes=int(row.recovery_bytes or 0),
                    elapsed_ms=int(metadata.get("elapsed_ms") or 0),
                    created_at=row.created_at,
                    completed_at=completed_at,
                    items=item_rows,
                )
            )
        return OperationExecutionHistoryListResponse(items=items)

    async def _run_session(
        self,
        *,
        state: _SessionState,
        service_factory: Any,
        session_factory: async_sessionmaker[AsyncSession],
        created_by_user_id: int | None,
    ) -> None:
        state.status = "running"
        state.started_at = _utcnow()
        started_timer = perf_counter()

        async with session_factory() as db:
            service = service_factory(db)
            for item in state.items:
                item.status = "running"
                state.current_asset_title = item.title
                try:
                    await self._advance_step(state, item, 0, "Scanning filesystem...")
                    preview = await service.recommendation_preview(item.recommendation_id)
                    await self._complete_step(item, 0, preview.preview.details[0] if preview.preview.details else "Filesystem scan complete")

                    validation_index = 1 if len(item.stages) > 1 else 0
                    await self._advance_step(state, item, validation_index, "Matching identity...")
                    validated = await service.recommendation_validate(item.recommendation_id)
                    if not validated.validation.valid:
                        await self._fail_step(item, validation_index, "Validation blocked execution")
                        item.status = "blocked"
                        item.message = "Validation blocked execution"
                        state.failed += 1
                        state.warnings += sum(1 for check in validated.validation.checks if not check.passed)
                        await self._skip_remaining_steps(item, validation_index + 1)
                        continue
                    await self._complete_step(item, validation_index, "Identity matched")

                    execute_index = min(validation_index + 1, max(0, len(item.stages) - 1))
                    execute_label = self._execution_label_for_item(item)
                    await self._advance_step(state, item, execute_index, execute_label)
                    executed = await service.recommendation_execute(item.recommendation_id)
                    item.operation_history_id = executed.execution.operation_history_id
                    item.message = executed.execution.message
                    state.warnings += sum(1 for check in executed.validation.checks if not check.passed)
                    if executed.execution.executed:
                        await self._complete_step(item, execute_index, executed.execution.message)
                        await self._complete_remaining_steps(item, execute_index + 1)
                        item.status = "completed"
                        state.completed += 1
                        state.recovered_space_bytes += int(item.estimated_recovery_bytes or 0)
                    else:
                        await self._fail_step(item, execute_index, executed.execution.message)
                        await self._skip_remaining_steps(item, execute_index + 1)
                        item.status = "failed"
                        state.failed += 1
                except Exception as exc:
                    item.status = "failed"
                    item.message = str(exc)
                    state.failed += 1
                    await self._fail_first_open_step(item, str(exc))
                finally:
                    state.current_asset_title = item.title
                    state.current_step_label = item.message or self._execution_label_for_item(item)

            state.completed_at = _utcnow()
            elapsed_ms = max(0, int((perf_counter() - started_timer) * 1000))
            state.current_asset_title = None
            state.current_step_label = "Completed."
            if state.failed == 0:
                state.status = "completed"
            elif state.completed == 0:
                state.status = "failed"
            else:
                state.status = "partial"

            history = await db.get(OperationHistory, state.history_id)
            if history is not None:
                history.result = state.status
                history.recovery_bytes = state.recovered_space_bytes
                history.created_by_user_id = created_by_user_id
                history.metadata_json = {
                    "session_id": state.session_id,
                    "selected_ids": state.selected_ids,
                    "selected_count": len(state.selected_ids),
                    "status": state.status,
                    "successful": state.completed,
                    "warnings": state.warnings,
                    "failed": state.failed,
                    "elapsed_ms": elapsed_ms,
                    "completed_at": state.completed_at.isoformat() if state.completed_at else None,
                    "items": [item.model_dump(mode="json") for item in state.items],
                }
                await db.commit()

    async def _advance_step(
        self, state: _SessionState, item: OperationExecutionItemProgress, index: int, label: str
    ) -> None:
        if 0 <= index < len(item.stages):
            item.stages[index].status = "running"
            item.stages[index].detail = label
            state.current_step_label = label

    async def _complete_step(
        self, item: OperationExecutionItemProgress, index: int, detail: str
    ) -> None:
        if 0 <= index < len(item.stages):
            item.stages[index].status = "completed"
            item.stages[index].detail = detail

    async def _fail_step(
        self, item: OperationExecutionItemProgress, index: int, detail: str
    ) -> None:
        if 0 <= index < len(item.stages):
            item.stages[index].status = "failed"
            item.stages[index].detail = detail

    async def _skip_remaining_steps(self, item: OperationExecutionItemProgress, start: int) -> None:
        for stage in item.stages[start:]:
            if stage.status == "pending":
                stage.status = "skipped"

    async def _complete_remaining_steps(self, item: OperationExecutionItemProgress, start: int) -> None:
        for stage in item.stages[start:]:
            if stage.status == "pending":
                stage.status = "completed"
                stage.detail = "Completed"

    async def _fail_first_open_step(
        self, item: OperationExecutionItemProgress, detail: str
    ) -> None:
        for stage in item.stages:
            if stage.status in {"pending", "running"}:
                stage.status = "failed"
                stage.detail = detail
                break
        await self._skip_remaining_steps(
            item,
            next(
                (index + 1 for index, stage in enumerate(item.stages) if stage.status == "failed"),
                len(item.stages),
            ),
        )

    def _execution_label_for_item(self, item: OperationExecutionItemProgress) -> str:
        keys = [stage.key for stage in item.stages]
        if "artwork" in keys:
            return "Resolving artwork..."
        if "identity" in keys:
            return "Updating identity..."
        if "cleanup" in keys:
            return "Cleaning downloads..."
        if "plex_refresh" in keys:
            return "Refreshing Plex..."
        return "Applying operation..."

    def _to_response(self, state: _SessionState) -> OperationExecutionSessionResponse:
        total = len(state.items)
        completed_count = sum(1 for item in state.items if item.status in {"completed", "failed", "blocked"})
        average_per_item = _elapsed_ms(state.started_at) / completed_count if state.started_at and completed_count else 0
        remaining = max(0, total - completed_count)
        estimated_remaining_ms = (
            int(average_per_item * remaining)
            if completed_count > 0 and remaining > 0
            else None
        )
        elapsed_ms = _elapsed_ms(state.started_at, state.completed_at)
        return OperationExecutionSessionResponse(
            session_id=state.session_id,
            status=state.status,  # type: ignore[arg-type]
            total=total,
            completed=completed_count,
            failed=state.failed,
            warnings=state.warnings,
            remaining=remaining,
            current_asset_title=state.current_asset_title,
            current_step_label=state.current_step_label,
            elapsed_ms=elapsed_ms,
            estimated_remaining_ms=estimated_remaining_ms,
            history_id=state.history_id,
            started_at=state.started_at,
            completed_at=state.completed_at,
            items=[item.model_copy(deep=True) for item in state.items],
            summary=OperationExecutionSummary(
                successful=sum(1 for item in state.items if item.status == "completed"),
                warnings=state.warnings,
                failed=sum(1 for item in state.items if item.status in {"failed", "blocked"}),
                recovered_space_bytes=state.recovered_space_bytes,
                elapsed_ms=elapsed_ms,
            ),
        )


operations_execution_manager = OperationsExecutionManager()