from __future__ import annotations

from pathlib import Path


def test_frontend_index_uses_base_url_for_branding_assets() -> None:
    index_html = Path("frontend/index.html").read_text(encoding="utf-8")
    assert "%BASE_URL%branding/favicon.ico" in index_html
    assert "%BASE_URL%branding/favicon-32x32.png" in index_html
    assert "%BASE_URL%branding/apple-touch-icon.png" in index_html
    assert "%BASE_URL%branding/site.webmanifest" in index_html
    assert "%BASE_URL%branding/logo.png" in index_html
