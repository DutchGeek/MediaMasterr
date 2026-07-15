from __future__ import annotations

from pathlib import Path


def test_media_card_shell_does_not_mutate_state_inside_derived() -> None:
    source = Path(
        "frontend/src/lib/design-system/cards/media-card-shell.svelte"
    ).read_text(encoding="utf-8")

    # Regression guard: card shell delegates artwork behavior to the shared
    # component instead of mutating state while deriving image URLs.
    assert 'import ArtworkImage from "$lib/design-system/media/artwork-image.svelte"' in source
    assert "<ArtworkImage" in source
    assert "posterLoadFailed" not in source
    assert "$derived.by" not in source
