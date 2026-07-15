from __future__ import annotations

from pathlib import Path


def test_media_card_shell_does_not_mutate_state_inside_derived() -> None:
    source = Path(
        "frontend/src/lib/design-system/cards/media-card-shell.svelte"
    ).read_text(encoding="utf-8")

    # Regression guard: mutating `$state` in `$derived` triggers Svelte
    # state_unsafe_mutation and keeps Operations/qBittorrent pages stuck on loading.
    assert "const resolvedPosterUrl = $derived.by(() => {" in source
    derived_block = source.split("const resolvedPosterUrl = $derived.by(() => {", 1)[1]
    derived_block = derived_block.split("});", 1)[0]
    assert "posterLoadFailed =" not in derived_block
    assert "$effect(() => {" in source
