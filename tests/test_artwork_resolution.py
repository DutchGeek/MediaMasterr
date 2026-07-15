from __future__ import annotations

from backend.core.artwork import (
    CENTRAL_PLACEHOLDER_POSTER_URL,
    resolve_backdrop_url,
    resolve_poster_url,
)


def test_resolve_poster_url_converts_tmdb_paths() -> None:
    assert (
        resolve_poster_url("/abc123.jpg", context="test")
        == "https://image.tmdb.org/t/p/w342/abc123.jpg"
    )


def test_resolve_poster_url_keeps_absolute_urls() -> None:
    url = "https://cdn.example.com/posters/movie.jpg"
    assert resolve_poster_url(url, context="test") == url


def test_resolve_poster_url_falls_back_to_branding_placeholder() -> None:
    assert resolve_poster_url(None, context="test") == CENTRAL_PLACEHOLDER_POSTER_URL


def test_resolve_backdrop_url_converts_tmdb_paths() -> None:
    assert (
        resolve_backdrop_url("/bg-1.jpg")
        == "https://image.tmdb.org/t/p/w1280/bg-1.jpg"
    )
