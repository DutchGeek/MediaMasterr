<script lang="ts">
  import { onMount } from "svelte";
  import { get_api } from "$lib/api";
  import {
    CollectionCard,
    DisplayOptionsDialog,
    MediaDetailsDrawer,
    MovieCard,
    loadModuleDisplayState,
    type DetailsDrawerSection,
    type MediaObject,
    type MovieObject,
  } from "$lib/design-system";
  import { formatFileSize } from "$lib/utils/formatters";
  import {
    formatTorrentEta,
    formatTorrentProgress,
  } from "$lib/qbittorrent/view.js";

  interface QBittorrentMetrics {
    active_downloads: number;
    active_uploads: number;
    seeding: number;
    paused: number;
    completed: number;
    stalled: number;
    download_speed: number;
    upload_speed: number;
  }

  interface QBittorrentTorrentItem {
    id: string;
    name: string;
    category: string;
    state: string;
    progress: number;
    size: number;
    ratio: number;
    eta: number;
    download_speed: number;
    upload_speed: number;
    tracker: string | null;
    save_path: string | null;
    imported_status: string;
    correlation_reason: string;
    poster_url: string | null;
    backdrop_url: string | null;
  }

  interface QBittorrentOverviewResponse {
    app_version: string;
    webapi_version: string;
    metrics: QBittorrentMetrics;
    torrents: QBittorrentTorrentItem[];
  }

  let loading = $state(true);
  let error = $state("");
  let overview = $state<QBittorrentOverviewResponse | null>(null);
  let selectedCategory = $state<string | null>(null);
  let selectedAsset = $state<MediaObject | null>(null);
  let drawerOpen = $state(false);
  let displayOptionsOpen = $state(false);
  let posterSize = $state(176);

  const loadOverview = async () => {
    loading = true;
    error = "";
    try {
      overview = await get_api<QBittorrentOverviewResponse>(
        "/api/qbittorrent/overview",
      );
    } catch (err: any) {
      error = err?.message ?? "Failed to load qBittorrent data.";
    } finally {
      loading = false;
    }
  };

  const stateRisk = (state: string): "low" | "medium" | "high" => {
    const lowered = state.toLowerCase();
    if (lowered.includes("error") || lowered.includes("stalled")) return "high";
    if (lowered.startsWith("paused") || lowered.includes("queued"))
      return "medium";
    return "low";
  };

  const stateSeverity = (state: string) => {
    const risk = stateRisk(state);
    if (risk === "high") return "problem" as const;
    if (risk === "medium") return "action" as const;
    return "healthy" as const;
  };

  const lifecycleForTorrent = (torrent: QBittorrentTorrentItem) => {
    if (torrent.progress >= 1 && torrent.ratio >= 1)
      return "protected" as const;
    if (torrent.progress >= 1) return "imported" as const;
    return "requested" as const;
  };

  const importPossible = (torrent: QBittorrentTorrentItem): boolean => {
    return torrent.progress >= 0.999 && torrent.imported_status !== "Imported";
  };

  const categories = $derived.by(() => {
    const map = new Map<string, number>();
    for (const torrent of overview?.torrents ?? []) {
      const key = torrent.category?.trim() || "uncategorized";
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return Array.from(map.entries()).map(([category, count]) => ({
      category,
      count,
    }));
  });

  const collectionCards = $derived.by(() => {
    return categories.map((bucket) => {
      const representative = (overview?.torrents ?? [])
        .filter(
          (torrent) =>
            (torrent.category?.trim() || "uncategorized") === bucket.category,
        )
        .sort((left, right) => right.progress - left.progress)
        .find((torrent) => !!torrent.poster_url);

      return {
      id: bucket.category,
      kind: "movie_collection" as const,
      title: bucket.category,
      subtitle: `${bucket.count} torrent assets`,
      lifecycleState: "imported" as const,
      recommendationSeverity: "information" as const,
      recommendation: {
        message: "Category groups live torrents with correlation-backed artwork.",
        confidence: 0.99,
        risk: "low" as const,
      },
      healthSignals: [
        {
          kind: "torrent_active" as const,
          label: "Torrent Active",
          explanation: "Grouped from live qBittorrent category metadata.",
        },
      ],
      quickActions: [{ id: "open", label: "Open Category" }],
      posterUrl: representative?.poster_url ?? null,
    };
    });
  });

  const torrentCards = $derived.by((): MovieObject[] => {
    return (overview?.torrents ?? [])
      .filter((torrent) => {
        const key = torrent.category?.trim() || "uncategorized";
        return !selectedCategory || selectedCategory === key;
      })
      .sort((left, right) => right.progress - left.progress)
      .map((torrent) => ({
        id: torrent.id,
        kind: "movie",
        title: torrent.name,
        subtitle: `${torrent.category || "uncategorized"} • ${torrent.state} • ${formatTorrentProgress(torrent.progress)}`,
        lifecycleState: lifecycleForTorrent(torrent),
        recommendationSeverity: stateSeverity(torrent.state),
        recommendation: {
          message: `State: ${torrent.state} | Import: ${torrent.imported_status} | ETA: ${formatTorrentEta(torrent.eta)} | Ratio: ${torrent.ratio.toFixed(2)}`,
          confidence: 0.97,
          risk: stateRisk(torrent.state),
          recoverableBytes: torrent.size,
          explanation:
            "Media-first torrent card with transfer state as recommendation context.",
        },
        healthSignals: [
          {
            kind: "torrent_active",
            label: "DL",
            explanation: `${formatFileSize(torrent.download_speed)}/s`,
          },
          {
            kind: "torrent_active",
            label: "UL",
            explanation: `${formatFileSize(torrent.upload_speed)}/s`,
          },
          {
            kind: "filesystem_verified",
            label: "Path",
            explanation: torrent.save_path || "n/a",
          },
          {
            kind: "imported",
            label: "Import",
            explanation: `${torrent.imported_status} (${torrent.correlation_reason})`,
          },
        ],
        quickActions: [
          ...(importPossible(torrent)
            ? [{ id: "import", label: "Import" as const }]
            : []),
          { id: "details", label: "Details" },
          { id: "tracker", label: "Tracker" },
        ],
        posterUrl: torrent.poster_url,
      }));
  });

  const drawerSections = $derived.by((): DetailsDrawerSection[] => {
    const currentAsset = selectedAsset;
    if (!currentAsset) return [];
    const torrent = (overview?.torrents ?? []).find(
      (row) => row.id === currentAsset.id,
    );
    if (!torrent) return [];
    return [
      {
        id: "lifecycle_timeline",
        title: "Lifecycle Timeline",
        rows: [
          { key: "Queued", value: "Observed" },
          {
            key: "Downloading",
            value: torrent.progress < 1 ? "Active" : "Complete",
          },
          {
            key: "Imported",
            value: torrent.imported_status,
          },
          {
            key: "Protected",
            value: torrent.ratio >= 1 ? "Eligible" : "Not yet",
          },
        ],
      },
      {
        id: "recommendation",
        title: "Recommendation",
        rows: [
          { key: "State", value: torrent.state },
          { key: "Risk", value: stateRisk(torrent.state) },
          { key: "Progress", value: formatTorrentProgress(torrent.progress) },
          { key: "ETA", value: formatTorrentEta(torrent.eta) },
        ],
      },
      {
        id: "filesystem",
        title: "Filesystem",
        rows: [
          { key: "Save Path", value: torrent.save_path || "n/a" },
          { key: "Size", value: formatFileSize(torrent.size) },
        ],
      },
      {
        id: "torrent",
        title: "Torrent",
        rows: [
          {
            key: "Download",
            value: `${formatFileSize(torrent.download_speed)}/s`,
          },
          { key: "Upload", value: `${formatFileSize(torrent.upload_speed)}/s` },
          { key: "Ratio", value: torrent.ratio.toFixed(2) },
          { key: "Tracker", value: torrent.tracker || "n/a" },
          { key: "Correlation", value: torrent.correlation_reason },
        ],
      },
      {
        id: "provider_information",
        title: "Provider Information",
        rows: [
          { key: "qBittorrent App", value: overview?.app_version ?? "n/a" },
          { key: "Web API", value: overview?.webapi_version ?? "n/a" },
          { key: "Category", value: torrent.category || "uncategorized" },
        ],
      },
    ];
  });

  const refreshDisplay = () => {
    const profile = loadModuleDisplayState("qbittorrent");
    const preset = profile.presets.find((p) => p.id === profile.activePresetId);
    posterSize = preset?.config.posterSize ?? 176;
  };

  onMount(async () => {
    refreshDisplay();
    await loadOverview();
  });
</script>

<div class="p-2.5 md:p-8">
  <div class="mx-auto max-w-7xl space-y-6">
    <div
      class="rounded-[2rem] border border-border/70 bg-gradient-to-br from-card via-background to-secondary/20 p-6 shadow-xl shadow-black/10"
    >
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p class="text-xs uppercase tracking-[0.3em] text-muted-foreground">
            Transfer Workspace
          </p>
          <h1 class="text-4xl font-black tracking-tight text-foreground">
            qBittorrent
          </h1>
          <p class="mt-2 text-sm text-muted-foreground">
            Media-first torrent assets with context on the card and diagnostics
            in the drawer.
          </p>
          {#if overview}
            <p class="mt-2 text-xs text-muted-foreground">
              App {overview.app_version} • API {overview.webapi_version} • {overview
                .torrents.length} assets
            </p>
          {/if}
        </div>
        <button
          type="button"
          class="rounded-full border border-border bg-card px-4 py-2 text-sm text-foreground hover:bg-secondary/50"
          onclick={() => (displayOptionsOpen = true)}
        >
          Display Options
        </button>
      </div>
    </div>

    {#if loading}
      <div
        class="rounded-xl border border-border bg-card p-6 text-muted-foreground"
      >
        Loading qBittorrent workspace...
      </div>
    {:else if error}
      <div
        class="rounded-xl border border-destructive/40 bg-destructive/10 p-6 text-destructive"
      >
        {error}
      </div>
    {:else}
      <section class="space-y-3">
        <h2 class="text-lg font-semibold text-foreground">Categories</h2>
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {#each collectionCards as item}
            <CollectionCard
              {item}
              selected={selectedCategory === item.id}
              onSelect={() =>
                (selectedCategory =
                  selectedCategory === item.id ? null : item.id)}
              {posterSize}
            />
          {/each}
        </div>
      </section>

      <section class="space-y-3">
        <h2 class="text-lg font-semibold text-foreground">Torrent Assets</h2>
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {#each torrentCards as item}
            <MovieCard
              {item}
              {posterSize}
              onSelect={() => {
                selectedAsset = item;
                drawerOpen = true;
              }}
            />
          {/each}
        </div>
      </section>
    {/if}
  </div>
</div>

<DisplayOptionsDialog
  moduleId="qbittorrent"
  bind:open={displayOptionsOpen}
  onSave={() => {
    refreshDisplay();
  }}
/>

<MediaDetailsDrawer
  bind:open={drawerOpen}
  item={selectedAsset}
  sections={drawerSections}
/>
