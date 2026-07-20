# Operations Workspace

## Overview
Operations is a lifecycle workspace, not a reporting table. The UI guides operators through Download, Import, Organize, Retention, Cleanup, and Completed lanes while preserving existing recommendation intelligence.

## Poster-First Identity
Each asset card is visually anchored by canonical artwork from the identity/artwork pipeline.

- Card identity block shows poster, title, year, media type, and stage.
- Recommendation becomes the primary action callout.
- Confidence and risk are rendered as visual indicators.
- Recoverable space is shown only when relevant.

When artwork is unavailable, the card shows an explicit placeholder:

- Missing Artwork
- Artwork Repair Available

## Bulk Workflow
Operators can process many assets without leaving the stage.

- Individual checkbox selection.
- Select all for current filtered result.
- Shift range selection.
- Shared selection persists through Preview, Validate, Execute, and targeted refresh.
- Sticky toolbar now uses the shared workspace filter model for ARR, decision, and smart filters.

Preview, Validate, and Execute use existing operations APIs and aggregate results across selected recommendation-backed assets.

## Execution Engine
Execute no longer rebuilds the Operations route.

- Bulk execute starts an async execution session and keeps the workspace visible.
- Live progress shows current asset, current step, completed count, remaining count, elapsed time, and ETA.
- Execution pipeline stages are shown per asset so operators can see when filesystem, identity, metadata, artwork, collections, tags, Plex refresh, ARR sync, or cleanup work is relevant.
- Execution results persist into an execution history feed backed by operation history records.

When an asset completes, the workspace updates only the affected cards and lane counters. Successful work can move cards forward through lifecycle lanes without a manual page reload.

## Explainability and Technical Details
Cards keep decision context readable while hiding implementation-heavy information by default.

- Why? section summarizes operational evidence.
- Technical Details section is collapsed by default and includes graph references, paths, and policy details.

## Stage and Filter Behavior
Stage lanes present workflow state, not static counters.

- Stage cards include Ready, Blocked, Needs Review, and Warnings rollups.
- Filters refine only the active stage.
- Media filters include Movies, Series, Anime, and Collections.
- Readiness filters include Ready, Blocked, Needs Review, High Confidence, and Low Confidence.
- Shared ARR, decision, and smart filters now use the same toolbar contract as other MediaMasterr workspaces.

Selection persists per stage while operators refine filters, and bulk actions run against the shared selected set rather than only the active card grid.

## Inspector
Clicking an asset opens an in-page inspector panel with:

- Poster and identity summary.
- Stage/timeline context.
- Relationship and provider hints.
- Policy information.
- Recommendation and direct action entry points.

This keeps operators in the Operations workflow without route changes.

## Accessibility and Interaction
The workspace supports keyboard-first operation:

- Ctrl/Cmd+A selects all visible assets in the active stage.
- Escape clears the shared selection set.
- Controls include explicit labels for screen reader navigation.
