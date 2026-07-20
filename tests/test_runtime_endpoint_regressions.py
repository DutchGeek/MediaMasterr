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
    assert "/api/mie/media/{media_id}/graph" in paths
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


def test_mie_operations_and_graph_openapi_contracts() -> None:
    schema = fastapi_app.openapi()

    operations_get = schema["paths"]["/api/mie/operations"]["get"]
    operations_ref = operations_get["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    operations_name = operations_ref.rsplit("/", 1)[-1]
    operations_props = set(
        schema["components"]["schemas"][operations_name]["properties"].keys()
    )

    assert {
        "health",
        "issues",
        "issue_summary",
        "graph_summary",
        "timeline_summary",
        "confidence",
        "downloads_health",
        "downloads",
        "workflow",
        "media_policies",
    } <= operations_props

    graph_get = schema["paths"]["/api/mie/media/{media_id}/graph"]["get"]
    graph_ref = graph_get["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    graph_name = graph_ref.rsplit("/", 1)[-1]
    graph_props = set(schema["components"]["schemas"][graph_name]["properties"].keys())

    assert {
        "media_id",
        "media_type",
        "title",
        "graph_generated_at",
        "identity",
        "request_intelligence",
        "arr_intelligence",
        "torrent_intelligence",
        "file_intelligence",
        "artwork_intelligence",
        "timeline",
        "health",
    } <= graph_props
