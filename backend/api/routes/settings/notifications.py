from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio.session import AsyncSession

from backend.core.auth import require_page_access
from backend.core.logger import LOG
from backend.database import get_db
from backend.database.models import NotificationSetting, User
from backend.enums import NotificationType, PageAccess, UserRole
from backend.models.settings import (
    NotificationSettingItem,
    NotificationTestRequest,
    normalize_notification_preferences,
)
from backend.services.notifications import test_notification_url

router = APIRouter(tags=["settings", "notifications"])


@router.get("/notifications")
async def get_notification_settings(
    current_user: Annotated[User, Depends(require_page_access(PageAccess.SETTINGS))],
    db: AsyncSession = Depends(get_db),
) -> list[NotificationSettingItem]:
    """Get all notification settings for the current user."""
    result = await db.execute(
        select(NotificationSetting).where(
            NotificationSetting.user_id == current_user.id
        )
    )
    notifications = result.scalars().all()

    return [
        NotificationSettingItem(
            id=n.id,
            enabled=n.enabled,
            name=n.name,
            url=n.url,
            new_cleanup_candidates=n.new_cleanup_candidates,
            request_approved=n.request_approved,
            request_declined=n.request_declined,
            admin_message=n.admin_message,
            task_failure=n.task_failure,
            admin_new_delete_request=n.admin_new_delete_request,
            admin_new_protection_request=n.admin_new_protection_request,
            admin_request_cancelled=n.admin_request_cancelled,
            admin_delete_execution_failed=n.admin_delete_execution_failed,
            delete_request_execution_succeeded=n.delete_request_execution_succeeded,
            delete_request_execution_failed=n.delete_request_execution_failed,
            preferences=normalize_notification_preferences(n.preferences),
        )
        for n in notifications
    ]


@router.post("/notifications/test")
async def test_notification(
    data: NotificationTestRequest,
    _current_user: Annotated[User, Depends(require_page_access(PageAccess.SETTINGS))],
) -> dict[str, str]:
    """Test a notification by sending a test payload to the provided URL."""
    if not data.url:
        raise HTTPException(status_code=400, detail="Apprise URL is required to test")

    success, error_message = await test_notification_url(data.url)
    if not success:
        raise HTTPException(status_code=400, detail=error_message)

    return {"message": "Test notification sent successfully"}


@router.post("/notifications")
async def create_or_update_notification(
    data: NotificationSettingItem,
    current_user: Annotated[User, Depends(require_page_access(PageAccess.SETTINGS))],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create or update a notification setting."""
    # validate that non-admin users cannot enable admin-only notifications
    if current_user.role is not UserRole.ADMIN:
        enabled_types = (
            (NotificationType.ADMIN_MESSAGE, data.admin_message),
            (NotificationType.TASK_FAILURE, data.task_failure),
            (NotificationType.ADMIN_NEW_DELETE_REQUEST, data.admin_new_delete_request),
            (
                NotificationType.ADMIN_NEW_PROTECTION_REQUEST,
                data.admin_new_protection_request,
            ),
            (NotificationType.ADMIN_REQUEST_CANCELLED, data.admin_request_cancelled),
            (
                NotificationType.ADMIN_DELETE_EXECUTION_FAILED,
                data.admin_delete_execution_failed,
            ),
        )
        if any(
            enabled and notification_type.is_admin_only()
            for notification_type, enabled in enabled_types
        ):
            raise HTTPException(
                status_code=403,
                detail="Only administrators can enable admin-only notifications",
            )

    if data.id:
        # update existing notification
        result = await db.execute(
            select(NotificationSetting).where(NotificationSetting.id == data.id)
        )
        notification = result.scalar_one_or_none()

        if not notification:
            raise HTTPException(
                status_code=404, detail="Notification setting not found"
            )

        # ensure user owns this notification
        if notification.user_id != current_user.id:
            raise HTTPException(
                status_code=403, detail="Not authorized to modify this notification"
            )

        # update fields
        notification.enabled = data.enabled
        notification.name = data.name
        notification.url = data.url
        notification.new_cleanup_candidates = data.new_cleanup_candidates
        notification.request_approved = data.request_approved
        notification.request_declined = data.request_declined
        notification.admin_message = data.admin_message
        notification.task_failure = data.task_failure
        notification.admin_new_delete_request = data.admin_new_delete_request
        notification.admin_new_protection_request = data.admin_new_protection_request
        notification.admin_request_cancelled = data.admin_request_cancelled
        notification.admin_delete_execution_failed = data.admin_delete_execution_failed
        notification.delete_request_execution_succeeded = (
            data.delete_request_execution_succeeded
        )
        notification.delete_request_execution_failed = (
            data.delete_request_execution_failed
        )
        notification.preferences = normalize_notification_preferences(data.preferences)

        await db.commit()
        await db.refresh(notification)

        LOG.info(
            f"Updated notification setting {notification.id} for user {current_user.username}"
        )
        message = "Notification setting updated successfully"
    else:
        # create new notification
        notification = NotificationSetting(
            user_id=current_user.id,
            enabled=data.enabled,
            name=data.name,
            url=data.url,
            new_cleanup_candidates=data.new_cleanup_candidates,
            request_approved=data.request_approved,
            request_declined=data.request_declined,
            admin_message=data.admin_message,
            task_failure=data.task_failure,
            admin_new_delete_request=data.admin_new_delete_request,
            admin_new_protection_request=data.admin_new_protection_request,
            admin_request_cancelled=data.admin_request_cancelled,
            admin_delete_execution_failed=data.admin_delete_execution_failed,
            delete_request_execution_succeeded=data.delete_request_execution_succeeded,
            delete_request_execution_failed=data.delete_request_execution_failed,
            preferences=normalize_notification_preferences(data.preferences),
        )
        db.add(notification)
        await db.commit()
        await db.refresh(notification)

        LOG.info(
            f"Created notification setting {notification.id} for user {current_user.username}"
        )
        message = "Notification setting created successfully"

    return {
        "message": message,
        "data": NotificationSettingItem(
            id=notification.id,
            enabled=notification.enabled,
            name=notification.name,
            url=notification.url,
            new_cleanup_candidates=notification.new_cleanup_candidates,
            request_approved=notification.request_approved,
            request_declined=notification.request_declined,
            admin_message=notification.admin_message,
            task_failure=notification.task_failure,
            admin_new_delete_request=notification.admin_new_delete_request,
            admin_new_protection_request=notification.admin_new_protection_request,
            admin_request_cancelled=notification.admin_request_cancelled,
            admin_delete_execution_failed=notification.admin_delete_execution_failed,
            delete_request_execution_succeeded=notification.delete_request_execution_succeeded,
            delete_request_execution_failed=notification.delete_request_execution_failed,
            preferences=normalize_notification_preferences(notification.preferences),
        ),
    }


@router.delete("/notifications/{notification_id}")
async def delete_notification(
    notification_id: int,
    current_user: Annotated[User, Depends(require_page_access(PageAccess.SETTINGS))],
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Remove a notification setting."""
    result = await db.execute(
        select(NotificationSetting).where(NotificationSetting.id == notification_id)
    )
    notification = result.scalar_one_or_none()

    if not notification:
        raise HTTPException(status_code=404, detail="Notification setting not found")

    # ensure user owns this notification
    if notification.user_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to delete this notification"
        )

    await db.delete(notification)
    await db.commit()

    LOG.info(
        f"Deleted notification setting {notification_id} for user {current_user.username}"
    )

    return {"message": "Notification setting deleted successfully"}
