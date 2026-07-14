import type {
  DisplayModuleId,
  DisplayPreset,
  DisplayProfileConfig,
} from "$lib/design-system/display/types";

export const BASE_DEFAULT_CONFIG: DisplayProfileConfig = {
  posterSize: 176,
  cardDensity: "comfortable",
  viewMode: "cards",
  visibleMetadata: ["title", "subtitle"],
  visibleBadges: true,
  visibleRibbons: true,
  ribbonPosition: "top_left",
  visibleHealthStrip: true,
  hoverActions: true,
  quickActions: true,
  sorting: "risk",
  grouping: "context",
  visibleFields: [
    "timeline",
    "recommendation_summary",
    "confidence",
    "risk",
    "recoverable_space",
    "filesystem",
    "protection",
    "ratio",
    "seed_days",
    "tracker",
    "progress",
  ],
};

const withOverrides = (
  overrides: Partial<DisplayProfileConfig>,
): DisplayProfileConfig => ({
  ...BASE_DEFAULT_CONFIG,
  ...overrides,
  visibleMetadata:
    overrides.visibleMetadata ?? BASE_DEFAULT_CONFIG.visibleMetadata,
  visibleFields: overrides.visibleFields ?? BASE_DEFAULT_CONFIG.visibleFields,
});

export const moduleDefaults = (
  moduleId: DisplayModuleId,
): DisplayProfileConfig => {
  if (moduleId === "operations") {
    return withOverrides({
      sorting: "risk",
      grouping: "card",
      posterSize: 184,
      viewMode: "context_grid",
    });
  }
  if (moduleId === "qbittorrent") {
    return withOverrides({
      sorting: "progress",
      grouping: "state",
      posterSize: 170,
      visibleFields: [
        "progress",
        "ratio",
        "seed_days",
        "tracker",
        "filesystem",
      ],
    });
  }
  if (moduleId === "sonarr") {
    return withOverrides({
      grouping: "series",
      sorting: "season",
      viewMode: "context_grid",
    });
  }
  if (moduleId === "radarr") {
    return withOverrides({
      grouping: "collection",
      sorting: "space",
    });
  }
  return withOverrides({});
};

export const builtInPresets = (moduleId: DisplayModuleId): DisplayPreset[] => {
  const base = moduleDefaults(moduleId);
  return [
    { id: "default", name: "Default", builtIn: true, config: base },
    {
      id: "minimal",
      name: "Minimal",
      builtIn: true,
      config: withOverrides({
        ...base,
        visibleHealthStrip: false,
        visibleBadges: false,
        quickActions: false,
        hoverActions: false,
      }),
    },
    {
      id: "compact",
      name: "Compact",
      builtIn: true,
      config: withOverrides({
        ...base,
        posterSize: 144,
        cardDensity: "dense",
      }),
    },
    {
      id: "power_user",
      name: "Power User",
      builtIn: true,
      config: withOverrides({
        ...base,
        visibleFields: [
          "timeline",
          "recommendation_summary",
          "confidence",
          "risk",
          "recoverable_space",
          "filesystem",
          "protection",
          "ratio",
          "seed_days",
          "tracker",
          "progress",
        ],
        viewMode: "diagnostics",
      }),
    },
    {
      id: "operations",
      name: "Operations",
      builtIn: true,
      config: withOverrides({
        ...base,
        sorting: "risk",
        grouping: "context",
      }),
    },
  ];
};
