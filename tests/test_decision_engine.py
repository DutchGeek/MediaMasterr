from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.enums import MediaType
from backend.services.decision_engine import DecisionEngine, DecisionSignals


def _signals(**overrides: object) -> DecisionSignals:
    now = datetime(2026, 7, 13, tzinfo=UTC)
    defaults: dict[str, object] = {
        "media_type": MediaType.MOVIE,
        "title": "Example Movie",
        "size_bytes": 50 * 1024 * 1024 * 1024,
        "view_count": 0,
        "last_viewed_at": None,
        "added_at": now - timedelta(days=40),
        "arr_added_at": now - timedelta(days=35),
        "is_candidate": False,
        "candidate_reason": None,
        "candidate_space_bytes": None,
        "candidate_created_at": None,
        "candidate_eligible_at": None,
        "candidate_delay_days": None,
        "is_protected": False,
        "protected_reason": None,
        "protected_permanent": True,
        "protected_source": None,
        "protected_rule_name": None,
        "protected_created_at": None,
        "protected_expires_at": None,
        "has_pending_request": False,
        "request_reason": None,
        "has_pending_delete_request": False,
        "delete_request_reason": None,
        "child_candidate_count": 0,
        "child_candidate_space_bytes": None,
        "tags": ["Movies American"],
        "library_names": ["Movies"],
    }
    defaults.update(overrides)
    return DecisionSignals(**defaults)


def test_protected_state_has_priority() -> None:
    decision = DecisionEngine.evaluate(
        _signals(
            is_candidate=True,
            candidate_reason="Matched cleanup rule",
            is_protected=True,
            protected_reason="Manual protection",
        ),
        now=datetime(2026, 7, 13, tzinfo=UTC),
    )

    assert decision.state == "protected"
    assert decision.display_name == "Protected"
    assert decision.recommended_action == "No action required"


def test_candidate_before_eligibility_waits() -> None:
    now = datetime(2026, 7, 13, tzinfo=UTC)
    decision = DecisionEngine.evaluate(
        _signals(
            is_candidate=True,
            candidate_reason="Retention window active",
            candidate_created_at=now - timedelta(days=2),
            candidate_eligible_at=now + timedelta(days=5),
            candidate_delay_days=7,
        ),
        now=now,
    )

    assert decision.state == "waiting"
    assert decision.remaining_seconds is not None
    assert decision.remaining_seconds > 0
    assert decision.timeline[-1].progress_percent is not None


def test_series_with_child_candidates_is_safe_to_delete() -> None:
    decision = DecisionEngine.evaluate(
        _signals(
            media_type=MediaType.SERIES,
            title="Example Series",
            child_candidate_count=3,
            child_candidate_space_bytes=84 * 1024 * 1024 * 1024,
            view_count=12,
            last_viewed_at=datetime(2026, 6, 1, tzinfo=UTC),
            tags=["TV Korean"],
        ),
        now=datetime(2026, 7, 13, tzinfo=UTC),
    )

    assert decision.state == "safe_to_delete"
    assert decision.library_group == "TV Korean"
    assert decision.reclaimable_size_bytes == 84 * 1024 * 1024 * 1024