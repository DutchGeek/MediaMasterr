from __future__ import annotations

from backend.api.main import fastapi_app


def test_operations_workspace_compat_route_exists() -> None:
    paths = set(fastapi_app.openapi().get("paths", {}).keys())
    assert "/api/operations/workspace" in paths
    assert "/api/mie/operations" in paths


def test_dashboard_and_qbittorrent_routes_exist() -> None:
    paths = set(fastapi_app.openapi().get("paths", {}).keys())
    assert "/api/mie/dashboard" in paths
    assert "/api/qbittorrent/overview" in paths
