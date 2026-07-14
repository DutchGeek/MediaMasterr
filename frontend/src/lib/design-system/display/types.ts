import type { RibbonPosition } from "$lib/design-system/model/types";

export type DisplayModuleId =
  | "sonarr"
  | "radarr"
  | "operations"
  | "qbittorrent"
  | "media_browser"
  | `provider_${string}`;

export type CardDensity = "comfortable" | "compact" | "dense";
export type ViewMode = "cards" | "context_grid" | "diagnostics";

export type DisplayField =
  | "timeline"
  | "recommendation_summary"
  | "confidence"
  | "risk"
  | "recoverable_space"
  | "filesystem"
  | "protection"
  | "ratio"
  | "seed_days"
  | "tracker"
  | "progress";

export interface DisplayProfileConfig {
  posterSize: number;
  cardDensity: CardDensity;
  viewMode: ViewMode;
  visibleMetadata: string[];
  visibleBadges: boolean;
  visibleRibbons: boolean;
  ribbonPosition: RibbonPosition;
  visibleHealthStrip: boolean;
  hoverActions: boolean;
  quickActions: boolean;
  sorting: string;
  grouping: string;
  visibleFields: DisplayField[];
}

export interface DisplayPreset {
  id: string;
  name: string;
  builtIn: boolean;
  config: DisplayProfileConfig;
}

export interface ModuleDisplayState {
  activePresetId: string;
  presets: DisplayPreset[];
}
