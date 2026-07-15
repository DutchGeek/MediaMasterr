from __future__ import annotations

from pathlib import Path


def test_brand_logo_uses_explicit_width_and_sidebar_constrains_height() -> None:
    brand_logo = Path("frontend/src/lib/components/brand-logo.svelte").read_text(
        encoding="utf-8"
    )
    sidebar = Path("frontend/src/lib/components/sidebar.svelte").read_text(
        encoding="utf-8"
    )

    assert "width = 200" in brand_logo
    assert "style={`width:${Math.max(1, width)}px`}" in brand_logo
    assert "max-h-full" in brand_logo
    assert '<BrandLogo width={200} class="max-h-[72px]" />' in sidebar


def test_shared_artwork_component_is_single_card_render_path() -> None:
    artwork_component = Path(
        "frontend/src/lib/design-system/media/artwork-image.svelte"
    ).read_text(encoding="utf-8")
    media_card_shell = Path(
        "frontend/src/lib/design-system/cards/media-card-shell.svelte"
    ).read_text(encoding="utf-8")
    series_layout = Path(
        "frontend/src/lib/design-system/layouts/series-layout.svelte"
    ).read_text(encoding="utf-8")
    details_drawer = Path(
        "frontend/src/lib/design-system/drawers/media-details-drawer.svelte"
    ).read_text(encoding="utf-8")
    dashboard = Path("frontend/src/routes/dashboard.svelte").read_text(
        encoding="utf-8"
    )

    assert "resolvePosterUrl" in artwork_component
    assert "BRANDING.assets.mediaPlaceholder" in artwork_component
    assert "onerror" in artwork_component

    assert "import ArtworkImage" in media_card_shell
    assert "<ArtworkImage" in media_card_shell
    assert "resolvePosterUrl" not in media_card_shell

    assert "import ArtworkImage" in series_layout
    assert "<ArtworkImage" in series_layout
    assert "No poster" not in series_layout

    assert "import ArtworkImage" in details_drawer
    assert "<ArtworkImage" in details_drawer
    assert "No artwork" not in details_drawer

    assert "import { ArtworkImage }" in dashboard
    assert dashboard.count("<ArtworkImage") >= 2


def test_system_page_exposes_actionable_provider_diagnostics_fields() -> None:
    system_route = Path("frontend/src/routes/system.svelte").read_text(
        encoding="utf-8"
    )

    for label in [
        "Connected",
        "Version",
        "Response Time",
        "Last Successful Sync",
        "Last Attempt",
        "Status",
        "Reason",
        "Last Error",
        "Endpoint",
        "HTTP",
    ]:
        assert label in system_route

    assert "/api/protection/status" in system_route
    assert "probeProtectionDiagnostics" in system_route
