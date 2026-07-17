from __future__ import annotations

import re

from backend.core.logger import LOG

TMDB_POSTER_BASE_URL = "https://image.tmdb.org/t/p/w342"
TMDB_BACKDROP_BASE_URL = "https://image.tmdb.org/t/p/w1280"
CENTRAL_PLACEHOLDER_POSTER_URL = "/branding/media-placeholder.png"
_KNOWN_PLACEHOLDER_TOKENS = (
    "placeholder",
    "no-poster",
    "no_poster",
    "no-image",
    "no_image",
    "not-found",
    "missing",
)


def resolve_poster_url(
    poster_url: str | None,
    *,
    context: str,
    media_type: str | None = None,
    media_id: int | None = None,
    fallback_reason: str | None = None,
) -> str:
    """Resolve poster URLs to render-safe paths with a centralized fallback."""
    raw = (poster_url or "").strip()
    if not raw:
        reason = fallback_reason or "missing_poster_url"
        LOG.debug(
            "Artwork fallback applied: "
            f"context={context}, media_type={media_type}, media_id={media_id}, reason={reason}"
        )
        return CENTRAL_PLACEHOLDER_POSTER_URL

    lower = raw.lower()
    if lower.startswith(("http://", "https://", "data:")):
        return raw
    if raw.startswith("/branding/"):
        return raw

    normalized = raw if raw.startswith("/") else f"/{raw}"
    return f"{TMDB_POSTER_BASE_URL}{normalized}"


def resolve_backdrop_url(backdrop_url: str | None) -> str | None:
    """Resolve backdrop paths to absolute TMDB URLs when available."""
    raw = (backdrop_url or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    if lower.startswith(("http://", "https://", "data:")):
        return raw
    normalized = raw if raw.startswith("/") else f"/{raw}"
    return f"{TMDB_BACKDROP_BASE_URL}{normalized}"


def is_placeholder_artwork_url(url: str | None) -> bool:
    raw = (url or "").strip().lower()
    if not raw:
        return False
    if raw == CENTRAL_PLACEHOLDER_POSTER_URL.lower():
        return True
    return any(token in raw for token in _KNOWN_PLACEHOLDER_TOKENS)


def normalize_artwork_url_for_hash(url: str | None) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    # Normalize transient query parameters so diagnostics can detect collisions.
    lowered = re.sub(r"\?.*$", "", lowered)
    return lowered
