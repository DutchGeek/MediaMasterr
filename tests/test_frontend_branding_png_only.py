from __future__ import annotations

from pathlib import Path


def test_branding_asset_map_uses_png_only() -> None:
    branding_ts = Path("frontend/src/lib/branding.ts").read_text(encoding="utf-8")

    assert "branding/logo.png" in branding_ts
    assert "branding/media-placeholder.png" in branding_ts
    assert "branding/favicon-32x32.png" in branding_ts
    assert "branding/logo.svg" not in branding_ts
    assert "media-placeholder.svg" not in branding_ts
    assert "favicon.ico" not in branding_ts


def test_artwork_fallback_does_not_emit_svg_branding_urls() -> None:
    artwork_ts = Path("frontend/src/lib/artwork.ts").read_text(encoding="utf-8")

    assert "replace(/\\.svg$/i, \".png\")" in artwork_ts
    assert "BRANDING.assets.mediaPlaceholder" in artwork_ts


def test_sync_branding_required_assets_exclude_svg() -> None:
    sync_script = Path("frontend/scripts/sync-branding.mjs").read_text(encoding="utf-8")

    assert '"media-placeholder.png"' in sync_script
    assert '"logo.png"' in sync_script
    assert ".svg" not in sync_script


def test_generated_branding_output_excludes_svg_files() -> None:
    static_branding = Path("frontend/static/branding")
    assert static_branding.exists()

    svg_files = sorted(p.name for p in static_branding.glob("*.svg"))
    assert svg_files == []


def test_manifest_icons_do_not_reference_svg() -> None:
    for manifest_path in [
        Path("branding/web/site.webmanifest"),
        Path("frontend/static/branding/site.webmanifest"),
    ]:
        manifest = manifest_path.read_text(encoding="utf-8")
        assert ".svg" not in manifest
        assert "image/png" in manifest
