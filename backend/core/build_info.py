from __future__ import annotations

import json
import os
import socket
import sys
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

from backend.core.__version__ import __version__

STARTUP_TIME = datetime.now(UTC).isoformat(timespec="seconds")

_build_info_cache: dict[str, str | None] | None = None


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"n/a", "na", "none", "null", "unknown", "unavailable"}:
        return None
    return text


def _candidate_paths() -> list[Path]:
    configured_path = _clean_value(os.getenv("APP_BUILD_INFO_FILE"))
    candidates: list[Path] = []
    if configured_path is not None:
        candidates.append(Path(configured_path))
    candidates.extend(
        [
            Path("/app/build_info.json"),
            Path.cwd() / "build_info.json",
        ]
    )
    return candidates


def _load_build_info_file() -> dict[str, str | None]:
    for path in _candidate_paths():
        try:
            if not path.is_file():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            cleaned = {str(k): _clean_value(v) for k, v in payload.items()}
            cleaned["build_info_source"] = str(path)
            return cleaned
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _default_build_info() -> dict[str, str | None]:
    return {
        "application_version": str(__version__),
        "git_sha": None,
        "short_sha": None,
        "branch": None,
        "tag": None,
        "build_date": None,
        "build_time": None,
        "build_timestamp": None,
        "github_workflow_run": None,
        "github_run_number": None,
        "github_repository": None,
        "docker_image_tag": None,
        "docker_image_digest": None,
        "python_version": sys.version.split()[0],
        "backend_version": str(__version__),
        "frontend_version": None,
        "environment": os.getenv("APP_ENVIRONMENT", "development"),
        "running_sha": None,
        "latest_built_sha": None,
        "frontend_sha": None,
        "backend_sha": None,
        "container_id": _clean_value(os.getenv("APP_CONTAINER_ID"))
        or _clean_value(os.getenv("HOSTNAME"))
        or socket.gethostname(),
        "hostname": socket.gethostname(),
        "build_info_source": None,
    }


def load_build_info(*, force: bool = False) -> dict[str, str | None]:
    global _build_info_cache
    if _build_info_cache is not None and not force:
        return _build_info_cache

    info = _default_build_info()
    info.update(_load_build_info_file())
    info["startup_time"] = STARTUP_TIME

    running_sha = info.get("running_sha")
    latest_built_sha = info.get("latest_built_sha")
    frontend_sha = info.get("frontend_sha")
    backend_sha = info.get("backend_sha")

    if (
        running_sha is None
        or latest_built_sha is None
        or frontend_sha is None
        or backend_sha is None
    ):
        status = "Unavailable"
    elif frontend_sha == backend_sha == running_sha == latest_built_sha:
        status = "Matching"
    else:
        status = "Version Mismatch"

    info["status"] = status
    _build_info_cache = info
    return _build_info_cache


def get_build_info() -> dict[str, str | None]:
    return load_build_info()


def reset_build_info_cache() -> None:
    global _build_info_cache
    _build_info_cache = None
