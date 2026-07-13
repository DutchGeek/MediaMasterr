from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from backend.core.utils.datetime_utils import to_utc_isoformat
from backend.enums import MediaType
from backend.models.media import DecisionBadgeInfo, DecisionInfo, DecisionTimelineStep


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _remaining_label(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    if seconds <= 0:
        return "Ready now"
    days, remainder = divmod(seconds, 86400)
    hours = remainder // 3600
    if days > 0:
        return f"{days}d {hours}h remaining"
    minutes = max(1, remainder // 60)
    return f"{minutes}m remaining"


def _clamp_progress(progress: int | None) -> int | None:
    if progress is None:
        return None
    return max(0, min(100, progress))


def _derive_library_group(tags: list[str] | None, library_names: list[str] | None) -> str | None:
    cleaned_tags = [tag.strip() for tag in tags or [] if isinstance(tag, str) and tag.strip()]
    if cleaned_tags:
        return cleaned_tags[0]
    cleaned_libraries = [
        name.strip() for name in library_names or [] if isinstance(name, str) and name.strip()
    ]
    if cleaned_libraries:
        return cleaned_libraries[0]
    return None


@dataclass(slots=True, frozen=True)
class DecisionSignals:
    media_type: MediaType
    title: str
    size_bytes: int | None
    view_count: int
    last_viewed_at: datetime | None
    added_at: datetime | None
    arr_added_at: datetime | None
    is_candidate: bool
    candidate_reason: str | None
    candidate_space_bytes: int | None
    candidate_created_at: datetime | None
    candidate_eligible_at: datetime | None
    candidate_delay_days: int | None
    is_protected: bool
    protected_reason: str | None
    protected_permanent: bool
    protected_source: str | None
    protected_rule_name: str | None
    protected_created_at: datetime | None
    protected_expires_at: datetime | None
    has_pending_request: bool
    request_reason: str | None
    has_pending_delete_request: bool
    delete_request_reason: str | None
    child_candidate_count: int = 0
    child_candidate_space_bytes: int | None = None
    tags: list[str] | None = None
    library_names: list[str] | None = None


class DecisionEngine:
    _META: dict[str, dict[str, str | int]] = {
        "superseding": {"label": "Superseding", "icon": "rocket", "tone": "purple", "priority": 100},
        "protected": {"label": "Protected", "icon": "shield", "tone": "blue", "priority": 90},
        "seeding": {"label": "Seeding", "icon": "sprout", "tone": "orange", "priority": 80},
        "waiting": {"label": "Waiting", "icon": "hourglass", "tone": "yellow", "priority": 70},
        "incomplete": {"label": "Incomplete", "icon": "download", "tone": "gray", "priority": 60},
        "unwatched": {"label": "Unwatched", "icon": "play", "tone": "teal", "priority": 50},
        "watching": {"label": "Watching", "icon": "monitor-play", "tone": "teal", "priority": 40},
        "safe_to_delete": {"label": "Safe to Delete", "icon": "trash-2", "tone": "green", "priority": 30},
        "attention_required": {"label": "Attention Required", "icon": "triangle-alert", "tone": "red", "priority": 20},
    }

    @classmethod
    def _badge(cls, state: str) -> DecisionBadgeInfo:
        meta = cls._META[state]
        return DecisionBadgeInfo(
            state=state,
            label=str(meta["label"]),
            icon=str(meta["icon"]),
            tone=str(meta["tone"]),
        )

    @classmethod
    def _timeline(
        cls,
        signals: DecisionSignals,
        *,
        state: str,
        explanation: str,
        progress_percent: int | None = None,
    ) -> list[DecisionTimelineStep]:
        imported_at = _ensure_utc(signals.arr_added_at) or _ensure_utc(signals.added_at)
        watched = signals.view_count > 0 or signals.last_viewed_at is not None
        protected = signals.is_protected

        reclaim_status = "blocked"
        if state == "safe_to_delete":
            reclaim_status = "current"
        elif state in {"watching", "unwatched", "waiting"}:
            reclaim_status = "pending"

        return [
            DecisionTimelineStep(
                key="downloaded",
                label="Downloaded",
                status="complete" if imported_at is not None else "pending",
                detail=to_utc_isoformat(imported_at),
            ),
            DecisionTimelineStep(
                key="watching",
                label="Watching",
                status="complete" if watched else "pending",
                detail=to_utc_isoformat(_ensure_utc(signals.last_viewed_at)),
            ),
            DecisionTimelineStep(
                key="protected",
                label="Protection",
                status="current" if protected else "pending",
                detail=signals.protected_rule_name or signals.protected_reason,
            ),
            DecisionTimelineStep(
                key="reclaim",
                label="Safe to Delete",
                status=reclaim_status,
                detail=explanation,
                progress_percent=_clamp_progress(progress_percent),
            ),
        ]

    @classmethod
    def evaluate(cls, signals: DecisionSignals, *, now: datetime | None = None) -> DecisionInfo:
        current = _ensure_utc(now) or datetime.now(UTC)
        library_group = _derive_library_group(signals.tags, signals.library_names)
        reclaimable_size = (
            signals.candidate_space_bytes
            if signals.candidate_space_bytes is not None
            else signals.child_candidate_space_bytes
            if signals.child_candidate_space_bytes is not None
            else signals.size_bytes
        )

        state = "attention_required"
        explanation = "MediaMasterr needs more provider evidence before it can recommend reclamation."
        recommended_action = "Review providers and refresh media signals"
        remaining_seconds: int | None = None
        progress_percent: int | None = None

        if signals.is_protected:
            state = "protected"
            label = signals.protected_rule_name or signals.protected_reason or "Protected by Reclaimerr"
            explanation = f"Protected by {label}" if signals.protected_source == "rule" else label
            recommended_action = "No action required"
        elif signals.has_pending_delete_request:
            state = "waiting"
            explanation = signals.delete_request_reason or "Deletion request is pending approval or execution."
            recommended_action = "Wait for deletion workflow to complete"
        elif signals.has_pending_request:
            state = "waiting"
            explanation = signals.request_reason or "Protection request is pending review."
            recommended_action = "Wait for request review"
        elif signals.is_candidate:
            eligible_at = _ensure_utc(signals.candidate_eligible_at)
            if eligible_at is not None and eligible_at > current:
                state = "waiting"
                remaining_seconds = int((eligible_at - current).total_seconds())
                explanation = signals.candidate_reason or "Retention window has not expired yet."
                recommended_action = "Wait until retention expires"
                if signals.candidate_created_at is not None and signals.candidate_delay_days:
                    total_seconds = max(signals.candidate_delay_days * 86400, 1)
                    elapsed_seconds = int(
                        max(0, (current - _ensure_utc(signals.candidate_created_at)).total_seconds())
                    )
                    progress_percent = int((elapsed_seconds / total_seconds) * 100)
            else:
                state = "safe_to_delete"
                explanation = signals.candidate_reason or "All reclaim conditions are satisfied."
                recommended_action = "Queue deletion"
        elif signals.child_candidate_count > 0:
            state = "safe_to_delete"
            explanation = f"{signals.child_candidate_count} child item(s) are reclaimable."
            recommended_action = (
                "Review reclaimable seasons or episodes"
                if signals.media_type is MediaType.SERIES
                else "Review reclaimable children"
            )
        elif signals.size_bytes is None:
            state = "incomplete"
            explanation = "Media size is missing, so reclaimable space cannot be estimated yet."
            recommended_action = "Refresh media sync"
        elif signals.view_count <= 0 and signals.last_viewed_at is None:
            state = "unwatched"
            explanation = "This media has not been watched yet."
            recommended_action = "Keep until watched"
        elif signals.last_viewed_at is not None:
            last_viewed_at = _ensure_utc(signals.last_viewed_at)
            assert last_viewed_at is not None
            seconds_since_watch = int((current - last_viewed_at).total_seconds())
            if seconds_since_watch <= 14 * 86400:
                state = "watching"
                explanation = "This media was watched recently and is still in an active viewing window."
                recommended_action = "Wait for viewing activity to settle"
            else:
                explanation = "Watch history exists, but no reclaim candidate has been generated yet."
                recommended_action = "Review rules or run candidate scan"

        badge = cls._badge(state)
        return DecisionInfo(
            state=state,
            priority=int(cls._META[state]["priority"]),
            badge=badge,
            display_name=badge.label,
            explanation=explanation,
            remaining_label=_remaining_label(remaining_seconds),
            remaining_seconds=remaining_seconds,
            reclaimable_size_bytes=reclaimable_size,
            recommended_action=recommended_action,
            library_group=library_group,
            timeline=cls._timeline(
                signals,
                state=state,
                explanation=explanation,
                progress_percent=progress_percent,
            ),
        )