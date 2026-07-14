<script lang="ts">
  import { onMount } from "svelte";
  import { get_api } from "$lib/api";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import Spinner from "$lib/components/ui/spinner/spinner.svelte";
  import ErrorBox from "$lib/components/error-box.svelte";
  import { createFilterState } from "$lib/utils/pagination";
  import { formatFileSize } from "$lib/utils/formatters";
  import { formatTorrentEta, formatTorrentProgress } from "$lib/qbittorrent/view.js";
  import Download from "@lucide/svelte/icons/download";
  import Upload from "@lucide/svelte/icons/upload";
  import PauseCircle from "@lucide/svelte/icons/pause-circle";
  import CheckCircle2 from "@lucide/svelte/icons/check-circle-2";
  import AlertTriangle from "@lucide/svelte/icons/alert-triangle";
  import Images from "@lucide/svelte/icons/images";
  import Radar from "@lucide/svelte/icons/radar";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import Wrench from "@lucide/svelte/icons/wrench";
  import { toTitleCase } from "$lib/utils/strings";

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
  }

  interface QBittorrentOverviewResponse {
    app_version: string;
    webapi_version: string;
    metrics: QBittorrentMetrics;
    torrents: QBittorrentTorrentItem[];
  }

  const MODULE_KEY = "qbittorrent";
  const STORAGE_PREFIX = `mediamasterr_display_${MODULE_KEY}`;
  const DISPLAY_MODE_KEY = `${STORAGE_PREFIX}_mode`;
  const POSTER_SIZE_KEY = `${STORAGE_PREFIX}_poster_size`;
  const SHOW_TECH_KEY = `${STORAGE_PREFIX}_show_tech`;
  const SORT_KEY = `${STORAGE_PREFIX}_sort`;

  const displayModeStore = createFilterState<"compact" | "comfortable" | "detailed">(
    DISPLAY_MODE_KEY,
    "comfortable",
  );
  const posterSizeStore = createFilterState<number>(POSTER_SIZE_KEY, 176);
  const showTechStore = createFilterState<boolean>(SHOW_TECH_KEY, true);
  const sortStore = createFilterState<string>(SORT_KEY, "progress");

  let loading = $state(true);
  let error = $state("");
  let overview = $state<QBittorrentOverviewResponse | null>(null);
  let displayMode = $state(displayModeStore.getInitial());
  let posterSize = $state(posterSizeStore.getInitial());
  let showTech = $state(showTechStore.getInitial());
  let sortMode = $state(sortStore.getInitial());
  let selectedName = $state<string | null>(null);
  let showOptions = $state(false);

  const stateRibbon = (state: string): { label: string; classes: string } => {
    const lowered = state.toLowerCase();
    if (lowered.includes("error") || lowered.includes("stalled")) {
      return { label: "Attention", classes: "border-rose-500/30 bg-rose-500/15 text-rose-300" };
    }
    if (lowered.startsWith("paused")) {
      return { label: "Paused", classes: "border-amber-500/30 bg-amber-500/15 text-amber-300" };
    }
    if (lowered.includes("upload") || lowered.includes("seed")) {
      return { label: "Seeding", classes: "border-sky-500/30 bg-sky-500/15 text-sky-300" };
    }
    if (lowered.includes("down")) {
      return { label: "Downloading", classes: "border-emerald-500/30 bg-emerald-500/15 text-emerald-300" };
    }
    return { label: toTitleCase(state || "unknown"), classes: "border-border/70 bg-background/80 text-foreground" };
  };

  const healthLabel = (torrent: QBittorrentTorrentItem): string => {
    if (torrent.progress >= 1 && torrent.ratio >= 1) return "Healthy";
    if (torrent.progress >= 1) return "Ready to Seed";
    if (torrent.eta > 0 && torrent.eta < 600) return "Almost There";
    return "Active";
  };

  const healthClasses = (torrent: QBittorrentTorrentItem): string => {
    if (torrent.progress >= 1 && torrent.ratio >= 1) return "border-emerald-500/30 bg-emerald-500/15 text-emerald-300";
    if (torrent.progress >= 1) return "border-sky-500/30 bg-sky-500/15 text-sky-300";
    if (torrent.eta > 0 && torrent.eta < 600) return "border-amber-500/30 bg-amber-500/15 text-amber-300";
    return "border-border/70 bg-background/80 text-foreground";
  };

  const loadOverview = async () => {
    loading = true;
    error = "";
    try {
      overview = await get_api<QBittorrentOverviewResponse>("/api/qbittorrent/overview");
    } catch (err: any) {
      error = err?.message ?? "Failed to load qBittorrent data.";
    } finally {
      loading = false;
    }
  };

  $effect(() => displayModeStore.save(displayMode));
  $effect(() => posterSizeStore.save(posterSize));
  $effect(() => showTechStore.save(showTech));
  $effect(() => sortStore.save(sortMode));

  const cards = $derived.by(() => {
    const metrics = overview?.metrics;
    if (!metrics) return [];
    return [
      { label: "Active Downloads", value: metrics.active_downloads, icon: Download },
      { label: "Active Uploads", value: metrics.active_uploads, icon: Upload },
      { label: "Seeding", value: metrics.seeding, icon: Upload },
      { label: "Paused", value: metrics.paused, icon: PauseCircle },
      { label: "Completed", value: metrics.completed, icon: CheckCircle2 },
      { label: "Stalled", value: metrics.stalled, icon: AlertTriangle },
      { label: "Download Speed", value: `${formatFileSize(metrics.download_speed)}/s`, icon: Download },
      { label: "Upload Speed", value: `${formatFileSize(metrics.upload_speed)}/s`, icon: Upload },
    ];
  });

  const torrents = $derived.by(() => {
    const rows = [...(overview?.torrents ?? [])];
    if (sortMode === "ratio") {
      rows.sort((left, right) => right.ratio - left.ratio);
    } else if (sortMode === "state") {
      rows.sort((left, right) => left.state.localeCompare(right.state));
    } else if (sortMode === "size") {
      rows.sort((left, right) => right.size - left.size);
    } else {
      rows.sort((left, right) => right.progress - left.progress);
    }
    return rows;
  });

  const selectedTorrent = $derived.by(() => torrents.find((item) => item.name === selectedName) ?? null);

  const layoutClass = $derived(
    displayMode === "compact"
      ? "grid gap-3 md:grid-cols-2 xl:grid-cols-3"
      : displayMode === "comfortable"
        ? "grid gap-4 md:grid-cols-2 xl:grid-cols-3"
        : "grid gap-5 md:grid-cols-2 xl:grid-cols-4",
  );

  onMount(loadOverview);
</script>

<div class="p-2.5 md:p-8">
  <div class="mx-auto max-w-7xl space-y-6">
    <div class="rounded-[2rem] border border-border/70 bg-gradient-to-br from-card via-background to-secondary/20 p-5 shadow-xl shadow-black/10 md:p-7">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div class="space-y-3">
          <div class="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.3em] text-muted-foreground">
            <span>Media Intelligence Engine</span>
            <span>qBittorrent</span>
            <span>visual queue</span>
          </div>
          <div class="space-y-2">
            <h1 class="text-4xl font-black tracking-tight text-foreground md:text-5xl">qBittorrent</h1>
            <p class="max-w-3xl text-sm text-muted-foreground md:text-base">
              Poster-first torrent cards with health ribbons, lifecycle cues, and technical drill-downs.
            </p>
          </div>
          {#if overview}
            <div class="flex flex-wrap gap-2 text-xs text-muted-foreground">
              <span class="rounded-full border border-border bg-background/70 px-3 py-1">App {overview.app_version}</span>
              <span class="rounded-full border border-border bg-background/70 px-3 py-1">Web API {overview.webapi_version}</span>
              <span class="rounded-full border border-border bg-background/70 px-3 py-1">{overview.torrents.length} torrents</span>
            </div>
          {/if}
        </div>

        <div class="flex flex-wrap gap-2">
          <button type="button" class="rounded-full border border-border bg-card px-4 py-2 text-sm text-foreground hover:bg-secondary/50" onclick={() => (showOptions = true)}>
            Display Options
          </button>
          <button type="button" class="rounded-full border border-border bg-card px-4 py-2 text-sm text-foreground hover:bg-secondary/50" onclick={() => (selectedName = null)}>
            Clear Selection
          </button>
        </div>
      </div>
    </div>

    {#if loading}
      <div class="flex justify-center py-8">
        <Spinner class="h-12 w-12 text-primary" />
      </div>
    {:else if error}
      <ErrorBox {error} />
    {:else if overview}
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {#each cards as card}
          <article class="rounded-[1.5rem] border border-border/70 bg-card p-4 shadow-sm">
            <div class="flex items-center justify-between gap-3">
              <p class="text-xs uppercase tracking-wide text-muted-foreground">{card.label}</p>
              <card.icon class="size-4 text-primary" />
            </div>
            <p class="mt-2 text-2xl font-semibold text-foreground">{card.value}</p>
          </article>
        {/each}
      </div>

      <section class="space-y-4 rounded-[2rem] border border-border/70 bg-card/80 p-4 md:p-5">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 class="text-lg font-semibold text-foreground">Torrent Assets</h2>
            <p class="text-sm text-muted-foreground">Each torrent is rendered as a media card with its own health ribbon.</p>
          </div>
          <div class="flex flex-wrap gap-2">
            <Select.Root type="single" bind:value={displayMode}>
              <Select.Trigger class="bg-background text-card-foreground">{displayMode}</Select.Trigger>
              <Select.Content class="bg-card">
                <Select.Item value="compact" label="Compact" class="text-card-foreground">Compact</Select.Item>
                <Select.Item value="comfortable" label="Comfortable" class="text-card-foreground">Comfortable</Select.Item>
                <Select.Item value="detailed" label="Detailed" class="text-card-foreground">Detailed</Select.Item>
              </Select.Content>
            </Select.Root>
            <Select.Root type="single" bind:value={sortMode}>
              <Select.Trigger class="bg-background text-card-foreground">Sort: {sortMode}</Select.Trigger>
              <Select.Content class="bg-card">
                <Select.Item value="progress" label="Progress" class="text-card-foreground">Progress</Select.Item>
                <Select.Item value="ratio" label="Ratio" class="text-card-foreground">Ratio</Select.Item>
                <Select.Item value="size" label="Size" class="text-card-foreground">Size</Select.Item>
                <Select.Item value="state" label="State" class="text-card-foreground">State</Select.Item>
              </Select.Content>
            </Select.Root>
          </div>
        </div>

        <div class={layoutClass}>
          {#each torrents as torrent}
            <button
              type="button"
              class={`group rounded-[1.75rem] border border-border/70 bg-background/80 p-3 text-left shadow-sm transition hover:-translate-y-1 hover:shadow-lg ${selectedName === torrent.name ? 'ring-2 ring-primary' : ''}`}
              style={`min-height: ${posterSize}px`}
              onclick={() => (selectedName = selectedName === torrent.name ? null : torrent.name)}
            >
              <div class="flex gap-3">
                <div class="relative overflow-hidden rounded-2xl border border-border/70 bg-gradient-to-br from-secondary/40 to-background" style={`width:${posterSize * 0.58}px;height:${posterSize}px`}>
                  <div class="absolute inset-0 flex items-center justify-center">
                    <Images class="size-10 text-muted-foreground/70" />
                  </div>
                  <div class={`absolute left-2 top-2 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${stateRibbon(torrent.state).classes}`}>
                    {stateRibbon(torrent.state).label}
                  </div>
                  <div class={`absolute bottom-2 left-2 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${healthClasses(torrent)}`}>
                    {healthLabel(torrent)}
                  </div>
                </div>

                <div class="min-w-0 flex-1 space-y-2">
                  <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                      <p class="truncate text-base font-semibold text-foreground">{torrent.name}</p>
                      <p class="line-clamp-2 text-sm text-muted-foreground">{torrent.category || 'Uncategorized'} · {formatTorrentProgress(torrent.progress)}</p>
                    </div>
                    <span class="rounded-full border border-border/70 px-2 py-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                      {torrent.ratio.toFixed(2)} ratio
                    </span>
                  </div>

                  <div class="space-y-2">
                    <div class="h-2 overflow-hidden rounded-full bg-border/60">
                      <div class="h-full rounded-full bg-primary" style={`width:${Math.max(2, Math.min(100, torrent.progress * 100))}%`}></div>
                    </div>
                    <div class="flex flex-wrap gap-2 text-xs text-muted-foreground">
                      <span class="rounded-full border border-border/70 px-2 py-1">Size {formatFileSize(torrent.size)}</span>
                      <span class="rounded-full border border-border/70 px-2 py-1">ETA {formatTorrentEta(torrent.eta)}</span>
                      <span class="rounded-full border border-border/70 px-2 py-1">DL {formatFileSize(torrent.download_speed)}/s</span>
                      <span class="rounded-full border border-border/70 px-2 py-1">UL {formatFileSize(torrent.upload_speed)}/s</span>
                    </div>
                    {#if showTech}
                      <div class="flex flex-wrap gap-2 text-xs text-muted-foreground">
                        <span class="rounded-full border border-border/70 px-2 py-1">Tracker {torrent.tracker || 'n/a'}</span>
                        <span class="rounded-full border border-border/70 px-2 py-1">Path {torrent.save_path || 'n/a'}</span>
                      </div>
                    {/if}
                  </div>
                </div>
              </div>
            </button>
          {/each}
        </div>
      </section>
    {/if}
  </div>
</div>

<Dialog.Root open={showOptions} onOpenChange={(isOpen) => (showOptions = isOpen)}>
  <Dialog.Content class="sm:max-w-3xl border-ring border-2">
    <Dialog.Header>
      <Dialog.Title>Display Options</Dialog.Title>
      <Dialog.Description>Adjust qBittorrent without changing any other page.</Dialog.Description>
    </Dialog.Header>

    <div class="grid gap-4 px-4 py-4 md:grid-cols-[1fr_1fr]">
      <div class="space-y-3">
        <div class="text-sm font-medium text-foreground">Display mode</div>
        <Select.Root type="single" bind:value={displayMode}>
          <Select.Trigger class="w-full bg-background text-card-foreground">{displayMode}</Select.Trigger>
          <Select.Content class="bg-card">
            <Select.Item value="compact" label="Compact" class="text-card-foreground">Compact</Select.Item>
            <Select.Item value="comfortable" label="Comfortable" class="text-card-foreground">Comfortable</Select.Item>
            <Select.Item value="detailed" label="Detailed" class="text-card-foreground">Detailed</Select.Item>
          </Select.Content>
        </Select.Root>

        <div class="text-sm font-medium text-foreground">Poster size</div>
        <input type="range" min="120" max="280" step="10" bind:value={posterSize} class="w-full accent-primary" />

        <label class="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" bind:checked={showTech} />
          Show technical detail
        </label>
      </div>

      <div class="rounded-2xl border border-border bg-background/70 p-4">
        <p class="text-xs uppercase tracking-[0.25em] text-muted-foreground">Live Preview</p>
        <div class="mt-4 overflow-hidden rounded-[1.5rem] border border-border/70 bg-card">
          <div class="relative aspect-[2/3] bg-gradient-to-br from-secondary/40 to-background" style={`height:${posterSize + 20}px`}>
            <div class="absolute inset-0 flex items-center justify-center">
              <Radar class="size-10 text-muted-foreground/70" />
            </div>
            <div class="absolute left-3 top-3 rounded-full border border-sky-500/30 bg-sky-500/15 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-sky-300">Healthy</div>
            <div class="absolute bottom-3 left-3 rounded-full border border-border bg-background/80 px-2 py-1 text-[11px] font-semibold text-foreground">Poster View</div>
          </div>
          <div class="p-3">
            <p class="font-semibold text-foreground">Selected Torrent</p>
            <p class="text-sm text-muted-foreground">Layout updates immediately and remains module-scoped.</p>
          </div>
        </div>
      </div>
    </div>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root open={selectedTorrent !== null} onOpenChange={(isOpen) => { if (!isOpen) selectedName = null; }}>
  <Dialog.Content class="sm:max-w-4xl border-ring border-2">
    <Dialog.Header>
      <Dialog.Title>{selectedTorrent?.name ?? 'Torrent Details'}</Dialog.Title>
      <Dialog.Description>Technical drill-down for the selected torrent asset.</Dialog.Description>
    </Dialog.Header>

    {#if selectedTorrent}
      <div class="grid gap-4 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <div class="space-y-3">
          <div class="overflow-hidden rounded-[1.75rem] border border-border/70 bg-gradient-to-br from-secondary/50 to-background">
            <div class="aspect-[2/3] flex items-center justify-center">
              <Images class="size-16 text-muted-foreground/60" />
            </div>
          </div>
          <div class="flex flex-wrap gap-2 text-xs">
            <span class={`rounded-full border px-2 py-1 ${stateRibbon(selectedTorrent.state).classes}`}>{stateRibbon(selectedTorrent.state).label}</span>
            <span class={`rounded-full border px-2 py-1 ${healthClasses(selectedTorrent)}`}>{healthLabel(selectedTorrent)}</span>
            <span class="rounded-full border border-border/70 px-2 py-1 text-muted-foreground">Progress {formatTorrentProgress(selectedTorrent.progress)}</span>
          </div>
        </div>

        <div class="space-y-4">
          <div class="rounded-2xl border border-border/70 bg-background/70 p-4">
            <p class="text-xs uppercase tracking-[0.25em] text-muted-foreground">Summary</p>
            <p class="mt-2 text-sm text-foreground">{selectedTorrent.category || 'Uncategorized'} · {formatFileSize(selectedTorrent.size)} · {selectedTorrent.ratio.toFixed(2)} ratio</p>
          </div>
          <div class="grid gap-3 md:grid-cols-2">
            <div class="rounded-2xl border border-border/70 bg-background/70 p-4">
              <p class="text-xs uppercase tracking-[0.25em] text-muted-foreground">Lifecycle</p>
              <div class="mt-3 space-y-2 text-sm text-foreground">
                <p>Queued → Downloading → Verifying → Seeding → Protected</p>
                <p>Promotion is based on progress and ratio.</p>
              </div>
            </div>
            <div class="rounded-2xl border border-border/70 bg-background/70 p-4">
              <p class="text-xs uppercase tracking-[0.25em] text-muted-foreground">Connection</p>
              <div class="mt-3 space-y-2 text-sm text-foreground">
                <p>Tracker: {selectedTorrent.tracker || 'n/a'}</p>
                <p>Save path: {selectedTorrent.save_path || 'n/a'}</p>
                <p>ETA: {formatTorrentEta(selectedTorrent.eta)}</p>
              </div>
            </div>
          </div>
          <div class="rounded-2xl border border-border/70 bg-background/70 p-4">
            <p class="text-xs uppercase tracking-[0.25em] text-muted-foreground">Actions</p>
            <div class="mt-3 flex flex-wrap gap-2 text-sm">
              <button type="button" class="rounded-full border border-border px-3 py-2 text-foreground">Inspect Files</button>
              <button type="button" class="rounded-full border border-border px-3 py-2 text-foreground">Open Tracker</button>
              <button type="button" class="rounded-full border border-border px-3 py-2 text-foreground">Mark Healthy</button>
            </div>
          </div>
        </div>
      </div>
    {/if}
  </Dialog.Content>
</Dialog.Root>
