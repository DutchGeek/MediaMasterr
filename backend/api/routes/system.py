from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import require_admin
from backend.core.service_manager import service_manager
from backend.database import get_db
from backend.database.models import (
    BackgroundJob,
    ProtectedMedia,
    ReclaimCandidate,
    ServiceConfig,
    TaskRun,
    TaskSchedule,
)
from backend.enums import BackgroundJobStatus, Service, Task, TaskStatus
from backend.database.models import User
from backend.scheduler import scheduler
from backend.services.protection.service import ProtectionService

router = APIRouter(prefix="/api/system", tags=["system"])


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


async def _probe_provider(
    *,
    service_type: Service,
    endpoint: str | None,
    enabled: bool,
    default_last_sync: datetime | None,
    db: AsyncSession,
) -> dict[str, object]:
    attempted_at = datetime.now(UTC)
    if not enabled:
        return {
            "key": service_type.value,
            "name": "qBittorrent" if service_type is Service.QBITTORRENT else service_type.value.title(),
            "endpoint": endpoint,
            "connected": False,
            "version": "Disabled",
            "apiVersion": None,
            "responseTimeMs": None,
            "lastSuccessfulSync": _to_iso(default_last_sync),
            "lastAttempt": _to_iso(attempted_at),
            "status": "degraded",
            "reason": "Service disabled",
            "lastError": "Service disabled",
            "httpStatus": None,
        }

    started = perf_counter()
    version: str | None = None
    api_version: str | None = None
    reason = "Connected"
    connected = True
    status = "healthy"
    last_error: str | None = None

    try:
        if service_type is Service.RADARR:
            client = service_manager.radarr
            if client is None:
                raise RuntimeError("Radarr runtime client unavailable")
            system_status = await client.get_system_status()
            version = await client.get_app_version()
            api_version = str(system_status.get("apiVersion") or "") or None
        elif service_type is Service.SONARR:
            client = service_manager.sonarr
            if client is None:
                raise RuntimeError("Sonarr runtime client unavailable")
            system_status = await client.get_system_status()
            version = await client.get_app_version()
            api_version = str(system_status.get("apiVersion") or "") or None
        elif service_type is Service.QBITTORRENT:
            client = service_manager.qbittorrent
            if client is None:
                raise RuntimeError("qBittorrent runtime client unavailable")
            version = await client.get_app_version()
            api_version = await client.get_webapi_version()
        elif service_type is Service.PLEX:
            client = service_manager.plex
            if client is None:
                raise RuntimeError("Plex runtime client unavailable")
            version = await client.get_app_version()
            api_version = await client.get_api_version()
        elif service_type is Service.TAUTULLI:
            client = service_manager.tautulli
            if client is None:
                raise RuntimeError("Tautulli runtime client unavailable")
            version = await client.get_app_version()
            api_version = None
        elif service_type is Service.SEERR:
            client = service_manager.seerr
            if client is None:
                raise RuntimeError("Seerr runtime client unavailable")
            connected = await client.health()
            version = None
            api_version = None
            if not connected:
                raise RuntimeError("Seerr health probe failed")
        else:
            connected = False
            status = "degraded"
            reason = "Diagnostics not supported"
    except Exception as exc:
        connected = False
        status = "down"
        reason = str(exc)
        last_error = reason

    response_time_ms = round((perf_counter() - started) * 1000, 2)

    last_sync = default_last_sync
    if service_type is Service.QBITTORRENT:
        last_sync = None
    if service_type is Service.SEERR:
        last_sync = None
    if service_type is Service.TAUTULLI:
        last_sync = None

    if service_type is Service.QBITTORRENT:
        name = "qBittorrent"
    else:
        name = service_type.value.title()

    return {
        "key": service_type.value,
        "name": name,
        "endpoint": endpoint,
        "connected": connected,
        "version": version or ("Unavailable" if enabled else "Disabled"),
        "apiVersion": api_version,
        "responseTimeMs": response_time_ms,
        "lastSuccessfulSync": _to_iso(last_sync) if connected else None,
        "lastAttempt": _to_iso(attempted_at),
        "status": status,
        "reason": reason,
        "lastError": last_error,
        "httpStatus": 200 if connected else None,
    }


@router.get("/diagnostics")
async def get_system_diagnostics(
    _admin: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    now = datetime.now(UTC)

    health_status = "ok"
    try:
        await db.execute(select(1))
    except Exception:
        health_status = "degraded"

    version_result = await db.execute(
        select(func.max(TaskRun.completed_at)).where(
            TaskRun.task == Task.SYNC_MEDIA,
            TaskRun.status == TaskStatus.COMPLETED,
        )
    )
    last_sync_at = version_result.scalar_one_or_none()

    configs = (
        await db.execute(
            select(ServiceConfig.service_type, ServiceConfig.enabled, ServiceConfig.base_url)
            .where(
                ServiceConfig.service_type.in_(
                    [
                        Service.RADARR,
                        Service.SONARR,
                        Service.QBITTORRENT,
                        Service.PLEX,
                        Service.TAUTULLI,
                        Service.SEERR,
                    ]
                )
            )
        )
    ).all()
    config_by_service = {
        service_type: (bool(enabled), base_url)
        for service_type, enabled, base_url in configs
    }

    provider_types = [
        Service.RADARR,
        Service.SONARR,
        Service.QBITTORRENT,
        Service.PLEX,
        Service.TAUTULLI,
        Service.SEERR,
    ]
    providers = []
    for provider in provider_types:
        enabled, endpoint = config_by_service.get(provider, (False, None))
        providers.append(
            await _probe_provider(
                service_type=provider,
                endpoint=endpoint,
                enabled=enabled,
                default_last_sync=last_sync_at,
                db=db,
            )
        )

    protection_status = await ProtectionService(db).get_status()
    providers.append(
        {
            "key": "protection",
            "name": "Protection",
            "endpoint": protection_status.base_url,
            "connected": bool(protection_status.connected),
            "version": protection_status.provider_version or "Unavailable",
            "apiVersion": None,
            "responseTimeMs": None,
            "lastSuccessfulSync": protection_status.last_sync,
            "lastAttempt": _to_iso(now),
            "status": (
                "healthy" if protection_status.connected else "degraded"
            ),
            "reason": protection_status.message
            or protection_status.connection_status
            or "Protection status unavailable",
            "lastError": None if protection_status.connected else protection_status.message,
            "httpStatus": 200 if protection_status.connected else None,
        }
    )

    total_tasks = int((await db.execute(select(func.count()).select_from(TaskSchedule))).scalar() or 0)
    enabled_tasks = int(
        (
            await db.execute(
                select(func.count()).select_from(TaskSchedule).where(TaskSchedule.enabled.is_(True))
            )
        ).scalar()
        or 0
    )
    running_jobs = int(
        (
            await db.execute(
                select(func.count()).select_from(BackgroundJob).where(
                    BackgroundJob.status == BackgroundJobStatus.RUNNING
                )
            )
        ).scalar()
        or 0
    )

    database_size_bytes: int | None = None
    bind = db.get_bind()
    db_path = str(bind.url.database) if bind is not None and bind.url.database else None
    if db_path and db_path not in {":memory:", ""} and os.path.exists(db_path):
        database_size_bytes = os.path.getsize(db_path)

    reclaim_candidates = int((await db.execute(select(func.count()).select_from(ReclaimCandidate))).scalar() or 0)
    protected_items = int((await db.execute(select(func.count()).select_from(ProtectedMedia))).scalar() or 0)

    return {
        "health": {
            "backend": "healthy" if health_status == "ok" else "degraded",
            "database": "healthy" if health_status == "ok" else "degraded",
            "scheduler": "healthy" if enabled_tasks > 0 else "degraded",
            "decision_engine": "healthy" if enabled_tasks > 0 else "degraded",
            "event_engine": "healthy" if enabled_tasks > 0 else "degraded",
        },
        "providers": providers,
        "scheduler": {
            "running": bool(scheduler.running),
            "job_count": len(scheduler.get_jobs()),
            "total_tasks": total_tasks,
            "enabled_tasks": enabled_tasks,
            "running_jobs": running_jobs,
        },
        "diagnostics": {
            "database_size_bytes": database_size_bytes,
            "cached_objects": reclaim_candidates + protected_items,
            "memory_usage_mb": None,
            "running_jobs": running_jobs,
            "queue_size": int(
                (
                    await db.execute(
                        select(func.count()).select_from(BackgroundJob).where(
                            BackgroundJob.status == BackgroundJobStatus.PENDING
                        )
                    )
                ).scalar()
                or 0
            ),
        },
    }


@router.post("/shutdown")
async def shutdown_app(
    request: Request,
    _admin: Annotated[User, Depends(require_admin)],
) -> dict[str, str]:
    """Gracefully shut down the desktop application process.

    Only available when running in desktop mode (i.e. launched via ``desktop/__main__.py``).
    In pure server mode this returns 503.
    """
    callback = getattr(request.app.state, "shutdown_callback", None)
    if callback is None:
        raise HTTPException(
            status_code=503,
            detail="Shutdown is not available in server mode",
        )

    # schedule the shutdown slightly after this response is sent so the
    # HTTP response has time to flush back to the client first.
    loop = asyncio.get_event_loop()
    loop.call_later(0.5, callback)

    return {"detail": "Shutting down"}
