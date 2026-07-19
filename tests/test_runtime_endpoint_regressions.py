from __future__ import annotations

from backend.api.main import fastapi_app


def test_operations_workspace_compat_route_exists() -> None:
    paths = set(fastapi_app.openapi().get("paths", {}).keys())
    assert "/api/operations/workspace" in paths
    assert "/api/mie/operations" in paths


def test_dashboard_and_qbittorrent_routes_exist() -> None:
    paths = set(fastapi_app.openapi().get("paths", {}).keys())
    assert "/api/mie/dashboard" in paths
    assert "/api/mie/identity" in paths
    assert "/api/mie/identity-canonical" in paths
    assert "/api/mie/identity/{identity_id}" in paths
    assert "/api/mie/identity/sync-preview" in paths
    assert "/api/mie/identity/sync" in paths
    assert "/api/mie/identity/sync-history" in paths
    assert "/api/mie/identity/{media_type}/{media_id}/studio" in paths
    assert "/api/mie/identity/{media_type}/{media_id}/canonical" in paths
    assert "/api/mie/identity/{media_type}/{media_id}/overrides" in paths
    assert "/api/mie/providers" in paths
    assert "/api/mie/external-ids" in paths
    assert "/api/mie/intelligence" in paths
    assert "/api/mie/timeline" in paths
    assert "/api/mie/relationships/{media_type}/{media_id}" in paths
    assert "/api/qbittorrent/overview" in paths
