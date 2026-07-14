export type MediaObjectKind =
  | "movie"
  | "movie_collection"
  | "series"
  | "season"
  | "episode";

export type LifecycleState =
  | "requested"
  | "downloading"
  | "importing"
  | "imported"
  | "verified"
  | "protected"
  | "seeding"
  | "seed_goal_reached"
  | "detached"
  | "archived"
  | "candidate"
  | "deleted";

export type RecommendationSeverity = "healthy" | "information" | "action" | "problem";

export type RibbonPosition =
  | "top_left"
  | "top_right"
  | "bottom_left"
  | "bottom_right"
  | "badge_only";

export type HealthSignalKind =
  | "protected"
  | "hardlinked"
  | "filesystem_verified"
  | "imported"
  | "torrent_active"
  | "plex_synced"
  | "warning";

export interface RecommendationSummary {
  message: string;
  confidence?: number;
  risk?: "low" | "medium" | "high";
  recoverableBytes?: number;
  explanation?: string;
}

export interface QuickAction {
  id: string;
  label: string;
  icon?: string;
  disabled?: boolean;
}

export interface HealthSignal {
  kind: HealthSignalKind;
  label: string;
  explanation: string;
}

export interface MediaObjectBase {
  id: string;
  kind: MediaObjectKind;
  title: string;
  subtitle?: string;
  posterUrl?: string | null;
  lifecycleState?: LifecycleState;
  recommendation?: RecommendationSummary;
  recommendationSeverity?: RecommendationSeverity;
  healthSignals?: HealthSignal[];
  quickActions?: QuickAction[];
}

export interface MovieObject extends MediaObjectBase {
  kind: "movie";
}

export interface EpisodeObject extends MediaObjectBase {
  kind: "episode";
  episodeNumber?: number;
}

export interface SeasonObject extends MediaObjectBase {
  kind: "season";
  seasonNumber?: number;
  episodes?: EpisodeObject[];
}

export interface SeriesObject extends MediaObjectBase {
  kind: "series";
  seasons?: SeasonObject[];
  affectedSeasons?: number;
  recommendations?: number;
  recoverableBytes?: number;
  highestRisk?: "low" | "medium" | "high";
  overallHealth?: string;
  lastScanAt?: string;
}

export interface MovieCollectionObject extends MediaObjectBase {
  kind: "movie_collection";
  movies?: MovieObject[];
}

export type MediaObject =
  | MovieObject
  | MovieCollectionObject
  | SeriesObject
  | SeasonObject
  | EpisodeObject;

export interface DetailsDrawerSection {
  id:
    | "artwork"
    | "lifecycle_timeline"
    | "recommendation"
    | "filesystem"
    | "torrent"
    | "protection"
    | "history"
    | "provider_information"
    | "actions";
  title: string;
  description?: string;
  rows?: Array<{ key: string; value: string }>;
}
