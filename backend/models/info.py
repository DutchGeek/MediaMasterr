from pydantic import BaseModel


class VersionInfoResponse(BaseModel):
    application_version: str
    git_sha: str | None
    short_sha: str | None
    branch: str | None
    tag: str | None
    build_date: str | None
    build_time: str | None
    build_timestamp: str | None
    github_workflow_run: str | None
    github_run_number: str | None
    github_repository: str | None
    docker_image_tag: str | None
    docker_image_digest: str | None
    python_version: str
    backend_version: str
    frontend_version: str | None
    startup_time: str
    environment: str
    container_id: str
    hostname: str
    running_sha: str | None
    latest_built_sha: str | None
    frontend_sha: str | None
    backend_sha: str | None
    status: str


class SidebarIndicatorsResponse(BaseModel):
    has_candidates: bool
    has_pending_requests: bool
    has_pending_protection_requests: bool
    has_pending_delete_requests: bool


class UiIndicatorsResponse(BaseModel):
    has_candidates: bool
    has_pending_requests: bool
    has_pending_protection_requests: bool
    has_pending_delete_requests: bool
    update_available: bool
    latest_version: str | None
    latest_release_url: str | None
    last_checked_at: str | None
    has_unread_notices: bool


class AdminNoticeResponse(BaseModel):
    id: int
    kind: str
    severity: str
    title: str
    message: str
    action_label: str | None
    action_href: str | None
    is_read: bool
    is_active: bool
    read_at: str | None
    last_occurred_at: str | None
    created_at: str
    updated_at: str


class AdminNoticesResponse(BaseModel):
    unread_count: int
    items: list[AdminNoticeResponse]
