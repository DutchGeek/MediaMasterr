# Media Asset Hierarchy

## Why Hierarchy Matters
Operational safety depends on preserving parent-child context.

If a season appears without its series context, users can misread blast radius. If an episode appears as a top-level entity, recommendations become noisy and less trustworthy.

## Hierarchy Rules
- Series can contain seasons.
- Seasons can contain episodes.
- Episodes are displayed inside season context only.
- Collections aggregate related assets for triage.
- Movies remain standalone assets.

## Workspace Usage
- Operations: uses series layouts and collection grouping to maintain context.
- qBittorrent: maps transfer assets into the same model so health and lifecycle semantics stay consistent.

## Drawer Scope
Detailed provider and filesystem data belongs in the shared drawer. Cards remain concise so scanning stays fast.
