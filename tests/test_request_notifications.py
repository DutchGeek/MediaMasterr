from backend.enums import NotificationType
from backend.models.settings import (
    default_notification_preferences,
    normalize_notification_preferences,
)
from backend.services.notifications import (
    _notification_type_to_field,
    request_scope_label,
)


def test_request_notification_types_map_to_setting_fields() -> None:
    expected = {
        NotificationType.ADMIN_NEW_DELETE_REQUEST: "admin_new_delete_request",
        NotificationType.ADMIN_NEW_PROTECTION_REQUEST: "admin_new_protection_request",
        NotificationType.ADMIN_REQUEST_CANCELLED: "admin_request_cancelled",
        NotificationType.ADMIN_DELETE_EXECUTION_FAILED: "admin_delete_execution_failed",
        NotificationType.DELETE_REQUEST_EXECUTION_SUCCEEDED: "delete_request_execution_succeeded",
        NotificationType.DELETE_REQUEST_EXECUTION_FAILED: "delete_request_execution_failed",
    }

    assert {
        notification_type: _notification_type_to_field(notification_type)
        for notification_type in expected
    } == expected


def test_admin_request_notification_types_are_admin_only() -> None:
    assert NotificationType.ADMIN_MESSAGE.is_admin_only()
    assert NotificationType.TASK_FAILURE.is_admin_only()
    assert NotificationType.ADMIN_NEW_DELETE_REQUEST.is_admin_only()
    assert NotificationType.ADMIN_NEW_PROTECTION_REQUEST.is_admin_only()
    assert NotificationType.ADMIN_REQUEST_CANCELLED.is_admin_only()
    assert NotificationType.ADMIN_DELETE_EXECUTION_FAILED.is_admin_only()
    assert not NotificationType.DELETE_REQUEST_EXECUTION_SUCCEEDED.is_admin_only()
    assert not NotificationType.DELETE_REQUEST_EXECUTION_FAILED.is_admin_only()


def test_request_notification_preferences_default_and_normalize() -> None:
    defaults = default_notification_preferences()
    assert defaults[NotificationType.ADMIN_NEW_DELETE_REQUEST.value] == {
        "detail": "standard"
    }

    normalized = normalize_notification_preferences(
        {
            NotificationType.ADMIN_NEW_DELETE_REQUEST.value: {"detail": "compact"},
            NotificationType.DELETE_REQUEST_EXECUTION_FAILED.value: {
                "detail": "invalid"
            },
        }
    )
    assert normalized[NotificationType.ADMIN_NEW_DELETE_REQUEST.value]["detail"] == (
        "compact"
    )
    assert (
        normalized[NotificationType.DELETE_REQUEST_EXECUTION_FAILED.value]["detail"]
        == "standard"
    )


def test_request_scope_labels() -> None:
    assert request_scope_label("episode", 2, 3, "Example") == "S02E03 - Example"
    assert request_scope_label("season", 2) == "Season 2"
    assert request_scope_label("movie_version") == "Movie Version"
