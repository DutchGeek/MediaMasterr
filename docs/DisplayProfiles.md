# Display Profiles

## Why Profiles Are Module Scoped
Different modules answer different questions. A profile that works for Operations may hide critical transfer context in qBittorrent. Module-scoped storage prevents cross-module side effects.

## Preset Model
Each module stores:
- active preset id
- built-in presets
- custom presets
- full display configuration per preset

Profiles are persisted in browser storage and loaded through the design-system profile helpers.

## Live Preview
The display options dialog applies edits to a draft configuration and renders a live preview card. This gives immediate feedback and avoids accidental workflow disruptions.

## Reset Behavior
- Reset: discard draft edits for the active preset.
- Reset to defaults: restore module preset set to canonical defaults.
