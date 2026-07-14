# Media Cards

## Why Cards Are Unified
Before the framework, each route reimplemented ribbons, health strips, and details handling. This created drift and made risk harder to compare between modules.

Unified cards provide a stable reading pattern:
- Title and subtitle identify the asset.
- Lifecycle badge explains where the asset is in the pipeline.
- Recommendation ribbon summarizes urgency.
- Health strip gives compact status signals.
- Quick actions remain predictable.

## Card Types
- CollectionCard: top-level category context.
- SeriesCard: parent context for season actions.
- SeasonCard: actionable unit for episodic media.
- EpisodeCard: shown in season detail context only.
- MovieCard: single-asset recommendation or transfer unit.

## Operational Benefit
When users move from Operations to qBittorrent, visual interpretation cost is close to zero. That reduces missed warnings and speeds review.
