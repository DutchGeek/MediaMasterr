# Design System

## Why This Exists
MediaMasterr now treats visual consistency as an operational safety feature, not decoration.

A shared card language lowers operator error because users do not have to relearn meaning between pages. Lifecycle state, recommendation severity, health signals, and quick actions stay in fixed positions across modules. That makes high-risk items easier to identify and review.

## Core Principles
- Media-first: cards represent assets and lifecycle context before provider internals.
- Context-first: series and collections show parent context before child actions.
- Technical details on demand: diagnostics move into the shared drawer.
- Module isolation: display profiles are independent per module.

## Framework Components
- Model: typed media object hierarchy in frontend/src/lib/design-system/model/types.ts.
- Card shell: visual foundation in frontend/src/lib/design-system/cards/media-card-shell.svelte.
- Type wrappers: movie, collection, series, season, and episode card wrappers.
- Drawer: shared technical workspace in frontend/src/lib/design-system/drawers/media-details-drawer.svelte.
- Display profiles: presets and persistence in frontend/src/lib/design-system/display/.

## Migration Direction
Operations and qBittorrent consume the same visual primitives. Route code focuses on mapping API data into the shared model, rather than rebuilding card UI per page.
