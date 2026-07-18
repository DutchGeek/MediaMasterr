from __future__ import annotations

import asyncio
import json

from backend.api.routes.info import info as info_module
from backend.core import build_info as build_info_module


def test_get_version_returns_build_info_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        info_module,
        "get_build_info",
        lambda: {
            "application_version": "0.6.4",
            "git_sha": "38c31aabc5a6d30621544dd1d51f9088e980b65d",
            "short_sha": "38c31aa",
            "branch": "main",
            "tag": "v0.6.4",
            "build_date": "2026-07-17",
            "build_time": "11:54:59Z",
            "build_timestamp": "2026-07-17T11:54:59Z",
            "github_workflow_run": "Docker Build",
            "github_run_number": "1234",
            "github_repository": "dutchgeek/mediamasterr",
            "docker_image_tag": "ghcr.io/dutchgeek/mediamasterr:38c31aa",
            "docker_image_digest": "unknown",
            "backend_version": "0.6.4",
            "frontend_version": "0.6.4",
            "startup_time": "2026-07-17T11:55:00+00:00",
            "environment": "container",
            "container_id": "container-123",
            "hostname": "host-123",
            "running_sha": "38c31aabc5a6d30621544dd1d51f9088e980b65d",
            "latest_built_sha": "38c31aabc5a6d30621544dd1d51f9088e980b65d",
            "frontend_sha": "38c31aabc5a6d30621544dd1d51f9088e980b65d",
            "backend_sha": "38c31aabc5a6d30621544dd1d51f9088e980b65d",
            "status": "Matching",
        },
    )

    result = asyncio.run(info_module.get_version())

    assert result.git_sha == "38c31aabc5a6d30621544dd1d51f9088e980b65d"
    assert result.short_sha == "38c31aa"
    assert result.branch == "main"
    assert result.tag == "v0.6.4"
    assert result.build_timestamp == "2026-07-17T11:54:59Z"
    assert result.github_workflow_run == "Docker Build"
    assert result.github_run_number == "1234"
    assert result.github_repository == "dutchgeek/mediamasterr"
    assert result.docker_image_tag == "ghcr.io/dutchgeek/mediamasterr:38c31aa"
    assert result.docker_image_digest == "unknown"
    assert result.frontend_version == "0.6.4"
    assert result.backend_version == "0.6.4"
    assert result.running_sha == result.latest_built_sha == result.frontend_sha == result.backend_sha
    assert result.status == "Matching"


def test_load_build_info_reads_artifact_file(monkeypatch, tmp_path) -> None:
    build_info_path = tmp_path / "build_info.json"
    build_info_path.write_text(
        json.dumps(
            {
                "application_version": "0.6.4",
                "git_sha": "abc123",
                "short_sha": "abc123",
                "branch": "main",
                "build_timestamp": "2026-07-17T11:54:59Z",
                "backend_version": "0.6.4",
                "frontend_version": "0.6.4",
                "environment": "container",
                "running_sha": "abc123",
                "latest_built_sha": "abc123",
                "frontend_sha": "abc123",
                "backend_sha": "abc123",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_BUILD_INFO_FILE", str(build_info_path))
    build_info_module.reset_build_info_cache()

    result = build_info_module.load_build_info(force=True)

    assert result["application_version"] == "0.6.4"
    assert result["git_sha"] == "abc123"
    assert result["build_info_source"] == str(build_info_path)
    assert result["status"] == "Matching"


def test_load_build_info_missing_artifact_is_unavailable(monkeypatch, tmp_path) -> None:
    missing_path = tmp_path / "missing-build-info.json"
    monkeypatch.setenv("APP_BUILD_INFO_FILE", str(missing_path))
    monkeypatch.delenv("APP_CONTAINER_ID", raising=False)
    monkeypatch.delenv("HOSTNAME", raising=False)
    build_info_module.reset_build_info_cache()

    result = build_info_module.load_build_info(force=True)

    assert result["build_info_source"] is None
    assert result["git_sha"] is None
    assert result["running_sha"] is None
    assert result["status"] == "Unavailable"
