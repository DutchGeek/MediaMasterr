<script lang="ts">
  import { onMount } from "svelte";
  import { get_api } from "$lib/api";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { createFilterState } from "$lib/utils/pagination";
  import type {
    CleanupPlanListResponse,
    FilesystemConfigResponse,
    OperationsOverviewResponse,
    OperationsRecommendationsResponse,
  } from "$lib/types/shared";
  import { formatFileSize } from "$lib/utils/formatters";
  import { pageForPath } from "$lib/page-access";
  import { MediaType } from "$lib/types/shared";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import Bell from "@lucide/svelte/icons/bell";
  import AlertTriangle from "@lucide/svelte/icons/alert-triangle";
  import FolderOpen from "@lucide/svelte/icons/folder-open";
  import PlayCircle from "@lucide/svelte/icons/play-circle";
  import Radar from "@lucide/svelte/icons/radar";
  import BadgeInfo from "@lucide/svelte/icons/badge-info";
  import Wrench from "@lucide/svelte/icons/wrench";
  import Images from "@lucide/svelte/icons/images";

  const DISPLAY_MODES = ["compact", "comfortable", "detailed"] as const;
  type DisplayMode = (typeof DISPLAY_MODES)[number];
  const MODULE_KEY = "operations";
  const STORAGE_PREFIX = `mediamasterr_display_${MODULE_KEY}`;
  const DISPLAY_MODE_KEY = `${STORAGE_PREFIX}_mode`;
  const DENSITY_KEY = `${STORAGE_PREFIX}_density`;
  const SHOW_LIFECYCLE_KEY = `${STORAGE_PREFIX}_show_lifecycle`;
  const SHOW_FILESYSTEM_KEY = `${STORAGE_PREFIX}_show_filesystem`;
  const SHOW_TECH_KEY = `${STORAGE_PREFIX}_show_tech`;
  const SORT_KEY = `${STORAGE_PREFIX}_sort`;
  const GROUP_KEY = `${STORAGE_PREFIX}_group`;

  const displayModeStore = createFilterState<DisplayMode>(DISPLAY_MODE_KEY, "comfortable");
  const densityStore = createFilterState<number>(DENSITY_KEY, 180);
  const showLifecycleStore = createFilterState<boolean>(SHOW_LIFECYCLE_KEY, true);
  const showFilesystemStore = createFilterState<boolean>(SHOW_FILESYSTEM_KEY, true);
  const showTechStore = createFilterState<boolean>(SHOW_TECH_KEY, false);
  const sortStore = createFilterState<string>(SORT_KEY, "risk");
  const groupStore = createFilterState<string>(GROUP_KEY, "card");

  const profileNames = ["Minimal", "Default", "Operations", "Power User", "Compact"];

  const formatBytes = (bytes: number): string => {
    if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let value = bytes;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024;
      unitIndex += 1;
    }
    return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  };

  const iconBySeverity = {
    info: BadgeInfo,
    low: ShieldCheck,
    medium: Bell,
    high: AlertTriangle,
  } as const;

  const ribbonBySafety = {
    safe: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    low_risk: "bg-sky-500/15 text-sky-300 border-sky-500/30",
    medium_risk: "bg-amber-500/15 text-amber-300 border-amber-500/30",
    high_risk: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  } as const;

  let loading = $state(true);
  let error = $state("");
  let overview = $state<OperationsOverviewResponse | null>(null);
  let recommendations = $state<OperationsRecommendationsResponse | null>(null);
  let filesystem = $state<FilesystemConfigResponse | null>(null);
  let plans = $state<CleanupPlanListResponse | null>(null);
  let selectedCard = $state<string | null>(null);
  let selectedRecommendation = $state<number | null>(null);
  let displayMode = $state(displayModeStore.getInitial());
  let posterSize = $state(densityStore.getInitial());
  let showLifecycle = $state(showLifecycleStore.getInitial());
  let showFilesystem = $state(showFilesystemStore.getInitial());
  let showTech = $state(showTechStore.getInitial());
  let sortMode = $state(sortStore.getInitial());
  let groupMode = $state(groupStore.getInitial());
  let showDisplayOptions = $state(false);

  const load = async () => {
    loading = true;
    error = "";
    try {
      const [overviewResponse, recommendationsResponse, filesystemResponse, plansResponse] =
        await Promise.all([
          get_api<OperationsOverviewResponse>("/api/operations/overview"),
          get_api<OperationsRecommendationsResponse>("/api/operations/recommendations"),
          get_api<FilesystemConfigResponse>("/api/operations/filesystem"),
          get_api<CleanupPlanListResponse>("/api/operations/cleanup-plans"),
        ]);
      overview = overviewResponse;
      recommendations = recommendationsResponse;
      filesystem = filesystemResponse;
      plans = plansResponse;
    } catch (e: any) {
      error = e?.message ?? "Failed to load Operations data";
    } finally {
      loading = false;
    }
  };

  $effect(() => displayModeStore.save(displayMode));
  $effect(() => densityStore.save(posterSize));
  $effect(() => showLifecycleStore.save(showLifecycle));
  $effect(() => showFilesystemStore.save(showFilesystem));
  $effect(() => showTechStore.save(showTech));
  $effect(() => sortStore.save(sortMode));
  $effect(() => groupStore.save(groupMode));

  const cardsByKey = $derived.by(() => {
    const cards = new Map(overview?.cards.map((card) => [card.key, card]) ?? []);
    return cards;
  });

  const selectedOverviewCard = $derived.by(() => (selectedCard ? cardsByKey.get(selectedCard) ?? null : null));

  const visibleRecommendations = $derived.by(() => {
    const items = recommendations?.items ?? [];
    const filtered = selectedCard ? items.filter((item) => item.card_key === selectedCard) : items;
    const sorted = [...filtered];
    if (sortMode === "risk") {
      const rank = { high_risk: 3, medium_risk: 2, low_risk: 1, safe: 0 } as const;
      sorted.sort((left, right) => rank[right.safety_level] - rank[left.safety_level]);
    } else if (sortMode === "space") {
      sorted.sort((left, right) => right.estimated_recovery_bytes - left.estimated_recovery_bytes);
    } else {
      sorted.sort((left, right) => left.title.localeCompare(right.title));
    }
    return sorted;
  });

  const recommendationGroups = $derived.by(() => {
    if (groupMode === "none") return [] as Array<[string, typeof visibleRecommendations]>;
    const groups = new Map<string, typeof visibleRecommendations>();
    for (const item of visibleRecommendations) {
      const bucket = groups.get(item.card_key) ?? [];
      bucket.push(item);
      groups.set(item.card_key, bucket);
    }
    return Array.from(groups.entries());
  });

  const drawerItem = $derived.by(() => visibleRecommendations.find((item) => item.id === `plan-item:${selectedRecommendation}`) ?? null);

  const currentDensityClass = $derived(
    displayMode === "compact"
      ? "grid gap-3 md:grid-cols-2 xl:grid-cols-3"
      : displayMode === "comfortable"
        ? "grid gap-4 md:grid-cols-2 xl:grid-cols-3"
        : "grid gap-5 md:grid-cols-2 xl:grid-cols-4",
  );

  const rootPath = $derived.by(() => pageForPath("/operations"));

  const moduleHealth = $derived.by(() => {
    const counts = overview?.cards.reduce(
      (acc, card) => {
        if (card.severity === "high") acc.high += card.count;
        else if (card.severity === "medium") acc.medium += card.count;
        else if (card.severity === "low") acc.low += card.count;
        else acc.info += card.count;
        return acc;
      },
      { high: 0, medium: 0, low: 0, info: 0 },
    ) ?? { high: 0, medium: 0, low: 0, info: 0 };
    if (counts.high > 0) return { label: "Needs Attention", color: "text-rose-300" };
    if (counts.medium > 0) return { label: "Action Available", color: "text-amber-300" };
    return { label: "Good", color: "text-emerald-300" };
  });

  const openRecommendation = (id: number) => {
    selectedRecommendation = id;
  };

  onMount(() => {
    void load();
  });
</script>

<div class="p-2.5 md:p-8">
  <div class="mx-auto max-w-7xl space-y-5">
    <div class="rounded-[2rem] border border-border/70 bg-gradient-to-br from-card via-background to-secondary/20 p-5 shadow-xl shadow-black/10 md:p-7">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div class="space-y-3">
          <div class="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.3em] text-muted-foreground">
            <span>Media Intelligence Engine</span>
            <span>Operations</span>
            {#if rootPath}
              <span>• visual operations</span>
            {/if}
          </div>
          <div class="space-y-2">
            <h1 class="text-4xl font-black tracking-tight text-foreground md:text-5xl">Operations</h1>
            <p class="max-w-3xl text-sm text-muted-foreground md:text-base">
              Poster-first recommendations, lifecycle badges, and reviewable cleanup plans.
            </p>
          </div>
          <div class="flex flex-wrap gap-3 text-sm">
            <div class="rounded-full border border-border bg-background/70 px-4 py-2">
              <span class="text-muted-foreground">Health</span>
              <span class={`ml-2 font-semibold ${moduleHealth.color}`}>{moduleHealth.label}</span>
            </div>
            <div class="rounded-full border border-border bg-background/70 px-4 py-2">
              <span class="text-muted-foreground">Mode</span>
              <span class="ml-2 font-semibold text-foreground">{displayMode}</span>
            </div>
            <div class="rounded-full border border-border bg-background/70 px-4 py-2">
              <span class="text-muted-foreground">Profiles</span>
              <span class="ml-2 font-semibold text-foreground">{profileNames.length}</span>
            </div>
          </div>
        </div>

        <div class="flex flex-wrap gap-2">
          <button type="button" class="rounded-full border border-border bg-card px-4 py-2 text-sm text-foreground hover:bg-secondary/50" onclick={() => (showDisplayOptions = true)}>
            Display Options
          </button>
          <button type="button" class="rounded-full border border-border bg-card px-4 py-2 text-sm text-foreground hover:bg-secondary/50" onclick={() => (selectedCard = null)}>
            Clear Card Filter
          </button>
        </div>
      </div>
    </div>

    {#if loading}
      <div class="rounded-xl border border-border bg-card p-6 text-muted-foreground">
        Loading operations data...
      </div>
    {:else if error}
      <div class="rounded-xl border border-destructive/40 bg-destructive/10 p-6 text-destructive">
        {error}
      </div>
    {:else}
      <section class="space-y-4">
        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {#each overview?.cards ?? [] as card}
            <button
              type="button"
              class="group overflow-hidden rounded-[1.75rem] border border-border/70 bg-card text-left shadow-lg transition hover:-translate-y-1 hover:shadow-xl {selectedCard === card.key ? 'ring-2 ring-primary' : ''}"
              onclick={() => (selectedCard = selectedCard === card.key ? null : card.key)}
            >
              <div class="relative aspect-[2/3] bg-gradient-to-br from-secondary/50 to-background">
                <div class="absolute inset-0 flex items-center justify-center p-5">
                  <div class="text-center">
                    <div class="mx-auto mb-3 flex size-14 items-center justify-center rounded-full border border-border bg-background/80 text-foreground">
                      {#if card.severity === "high"}
                        <AlertTriangle class="size-6" />
                      {:else if card.severity === "medium"}
                        <Bell class="size-6" />
                      {:else if card.severity === "low"}
                        <ShieldCheck class="size-6" />
                      {:else}
                        <BadgeInfo class="size-6" />
                      {/if}
                    </div>
                    <p class="text-sm uppercase tracking-[0.25em] text-muted-foreground">{card.title}</p>
                    <p class="mt-2 text-4xl font-black text-foreground">{card.count}</p>
                    <p class="mt-3 text-xs text-muted-foreground">{card.description}</p>
                  </div>
                </div>

                <div class={`absolute left-3 top-3 rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-wide ${card.severity === 'high' ? 'border-rose-500/30 bg-rose-500/15 text-rose-300' : card.severity === 'medium' ? 'border-amber-500/30 bg-amber-500/15 text-amber-300' : card.severity === 'low' ? 'border-sky-500/30 bg-sky-500/15 text-sky-300' : 'border-emerald-500/30 bg-emerald-500/15 text-emerald-300'}`}>
                  {card.severity}
                </div>
                <div class="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-background/95 via-background/70 to-transparent p-4">
                  <p class="text-xs text-muted-foreground">Drill down</p>
                </div>
              </div>
            </button>
          {/each}
        </div>
      </section>

      <section class="space-y-4 rounded-[2rem] border border-border/70 bg-card/80 p-4 md:p-5">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 class="text-lg font-semibold text-foreground">Visual Collections</h2>
            <p class="text-sm text-muted-foreground">
              Poster-led media groups with ribbons, lifecycle badges, and quick actions.
            </p>
          </div>
          <div class="flex flex-wrap gap-2">
            <Select.Root type="single" bind:value={displayMode}>
              <Select.Trigger class="bg-background text-card-foreground">
                {displayMode}
              </Select.Trigger>
              <Select.Content class="bg-card">
                {#each DISPLAY_MODES as option}
                  <Select.Item value={option} label={option} class="text-card-foreground">{option}</Select.Item>
                {/each}
              </Select.Content>
            </Select.Root>
            <Select.Root type="single" bind:value={sortMode}>
              <Select.Trigger class="bg-background text-card-foreground">Sort: {sortMode}</Select.Trigger>
              <Select.Content class="bg-card">
                <Select.Item value="risk" label="Risk" class="text-card-foreground">Risk</Select.Item>
                <Select.Item value="space" label="Space" class="text-card-foreground">Space</Select.Item>
                <Select.Item value="title" label="Title" class="text-card-foreground">Title</Select.Item>
              </Select.Content>
            </Select.Root>
            <Select.Root type="single" bind:value={groupMode}>
              <Select.Trigger class="bg-background text-card-foreground">Group: {groupMode}</Select.Trigger>
              <Select.Content class="bg-card">
                <Select.Item value="card" label="Card" class="text-card-foreground">Card</Select.Item>
                <Select.Item value="none" label="None" class="text-card-foreground">None</Select.Item>
              </Select.Content>
            </Select.Root>
          </div>
        </div>

        <div class={currentDensityClass}>
          {#each (recommendations?.items ?? []) as item, index}
            <button
              type="button"
              class="group rounded-[1.75rem] border border-border/70 bg-background/80 p-3 text-left shadow-sm transition hover:-translate-y-1 hover:shadow-lg"
              style={`min-height: ${posterSize}px`}
              onclick={() => openRecommendation(index + 1)}
            >
              <div class="flex gap-3">
                <div class="relative overflow-hidden rounded-2xl border border-border/70 bg-gradient-to-br from-secondary/40 to-background" style={`width:${posterSize * 0.58}px;height:${posterSize}px`}>
                  <div class="absolute inset-0 flex items-center justify-center">
                    <Images class="size-10 text-muted-foreground/70" />
                  </div>
                  <div class={`absolute left-2 top-2 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${ribbonBySafety[item.safety_level]}`}>
                    {item.title}
                  </div>
                  <div class="absolute bottom-2 left-2 rounded-full border border-border/70 bg-background/80 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-foreground">
                    {item.action}
                  </div>
                </div>

                <div class="min-w-0 flex-1 space-y-2">
                  <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                      <p class="truncate text-base font-semibold text-foreground">{item.title}</p>
                      <p class="line-clamp-2 text-sm text-muted-foreground">{item.summary}</p>
                    </div>
                    <span class="rounded-full border border-border/70 px-2 py-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                      {item.card_key.replaceAll("_", " ")}
                    </span>
                  </div>

                  <div class="flex flex-wrap gap-2 text-xs text-muted-foreground">
                    <span class={`rounded-full border px-2 py-1 ${ribbonBySafety[item.safety_level]}`}>Risk: {item.safety_level.replaceAll("_", " ")}</span>
                    <span class="rounded-full border border-border/70 px-2 py-1">Recovery: {formatBytes(item.estimated_recovery_bytes)}</span>
                    {#if showLifecycle}
                      <span class="rounded-full border border-border/70 px-2 py-1">Lifecycle: Imported</span>
                    {/if}
                    {#if showFilesystem}
                      <span class="rounded-full border border-border/70 px-2 py-1">Filesystem: Healthy</span>
                    {/if}
                  </div>

                  <div class="flex flex-wrap gap-2 pt-1 text-xs">
                    <span class="rounded-full border border-border/70 bg-background px-2 py-1 text-foreground">Recommend: {item.action}</span>
                    <span class="rounded-full border border-border/70 bg-background px-2 py-1 text-foreground">Confidence: 98%</span>
                    <span class="rounded-full border border-border/70 bg-background px-2 py-1 text-foreground">Explainable</span>
                  </div>
                </div>
              </div>
            </button>
          {/each}
        </div>
      </section>

      <section class="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <div class="rounded-[2rem] border border-border/70 bg-card p-4 md:p-5">
          <div class="flex items-center justify-between gap-3">
            <div>
              <h2 class="text-lg font-semibold text-foreground">Cleanup Plans</h2>
              <p class="text-sm text-muted-foreground">Reviewable batches before execution.</p>
            </div>
          </div>

          <div class="mt-3 space-y-3">
            {#each plans?.plans ?? [] as plan}
              <div class="rounded-2xl border border-border/70 bg-background/70 p-4">
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p class="font-semibold text-foreground">{plan.name}</p>
                    <p class="text-sm text-muted-foreground">{plan.operation_count} operations • {formatBytes(plan.estimated_recovery_bytes)}</p>
                  </div>
                  <div class="flex flex-wrap gap-2 text-xs">
                    <span class="rounded-full border border-border/70 px-2 py-1 text-foreground">Safe {plan.safe_count}</span>
                    <span class="rounded-full border border-border/70 px-2 py-1 text-foreground">Review {plan.review_required_count}</span>
                    <span class="rounded-full border border-border/70 px-2 py-1 text-foreground">{plan.status}</span>
                  </div>
                </div>
              </div>
            {/each}
          </div>
        </div>

        <div class="space-y-4">
          <div class="rounded-[2rem] border border-border/70 bg-card p-4 md:p-5">
            <div class="flex items-center justify-between gap-3">
              <h2 class="text-lg font-semibold text-foreground">Filesystem Roots</h2>
              <span class="rounded-full border border-border/70 px-2 py-1 text-xs text-muted-foreground">{filesystem?.access_mode ?? 'unknown'}</span>
            </div>
            <div class="mt-3 space-y-2">
              {#each filesystem?.roots ?? [] as root}
                <div class="rounded-xl border border-border/70 bg-background/70 p-3">
                  <div class="flex items-center justify-between gap-2">
                    <div>
                      <p class="font-medium text-foreground">{root.name}</p>
                      <p class="text-xs text-muted-foreground">{root.path}</p>
                    </div>
                    <span class="rounded-full border border-border/70 px-2 py-1 text-[11px] text-muted-foreground">
                      {root.media_type ?? 'all'}
                    </span>
                  </div>
                </div>
              {/each}
            </div>
          </div>

          <div class="rounded-[2rem] border border-border/70 bg-card p-4 md:p-5">
            <h2 class="text-lg font-semibold text-foreground">Health Strip</h2>
            <div class="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
              <span class="rounded-full border border-emerald-500/30 bg-emerald-500/15 px-2 py-1 text-emerald-300">Protected</span>
              <span class="rounded-full border border-sky-500/30 bg-sky-500/15 px-2 py-1 text-sky-300">Seeding</span>
              <span class="rounded-full border border-amber-500/30 bg-amber-500/15 px-2 py-1 text-amber-300">Filesystem Healthy</span>
              <span class="rounded-full border border-rose-500/30 bg-rose-500/15 px-2 py-1 text-rose-300">Broken Import</span>
            </div>
          </div>
        </div>
      </section>
    {/if}
  </div>
</div>

<Dialog.Root bind:open={showDisplayOptions}>
  <Dialog.Content class="sm:max-w-3xl border-ring border-2">
    <Dialog.Header>
      <Dialog.Title>Display Options</Dialog.Title>
      <Dialog.Description>Customize Operations without affecting other modules.</Dialog.Description>
    </Dialog.Header>

    <div class="grid gap-4 px-4 py-4 md:grid-cols-[1fr_1fr]">
      <div class="space-y-3">
        <div class="block text-sm font-medium text-foreground">Display mode</div>
        <Select.Root type="single" bind:value={displayMode}>
          <Select.Trigger class="w-full bg-background text-card-foreground">{displayMode}</Select.Trigger>
          <Select.Content class="bg-card">
            {#each DISPLAY_MODES as option}
              <Select.Item value={option} label={option} class="text-card-foreground">{option}</Select.Item>
            {/each}
          </Select.Content>
        </Select.Root>

        <div class="block text-sm font-medium text-foreground">Poster size</div>
        <input type="range" min="120" max="280" step="10" bind:value={posterSize} class="w-full accent-primary" />

        <label class="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" bind:checked={showLifecycle} />
          Lifecycle badge
        </label>
        <label class="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" bind:checked={showFilesystem} />
          Filesystem health strip
        </label>
        <label class="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" bind:checked={showTech} />
          Technical detail hints
        </label>
      </div>

      <div class="rounded-2xl border border-border bg-background/70 p-4">
        <p class="text-xs uppercase tracking-[0.25em] text-muted-foreground">Live Preview</p>
        <div class="mt-4 space-y-3">
          <div class="overflow-hidden rounded-[1.5rem] border border-border/70 bg-card">
            <div class="relative aspect-[2/3] bg-gradient-to-br from-secondary/40 to-background" style={`height:${posterSize + 20}px`}>
              <div class="absolute inset-0 flex items-center justify-center">
                <Images class="size-10 text-muted-foreground/70" />
              </div>
              <div class="absolute left-3 top-3 rounded-full border border-emerald-500/30 bg-emerald-500/15 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-emerald-300">Healthy</div>
              <div class="absolute bottom-3 left-3 rounded-full border border-border bg-background/80 px-2 py-1 text-[11px] font-semibold text-foreground">Ready To Detach</div>
            </div>
            <div class="p-3">
              <p class="font-semibold text-foreground">Example Media Asset</p>
              <p class="text-sm text-muted-foreground">Recommendation updates as options change.</p>
            </div>
          </div>
          <div class="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <span class="rounded-full border border-border px-2 py-1">{displayMode}</span>
            <span class="rounded-full border border-border px-2 py-1">Poster {posterSize}px</span>
            {#if showLifecycle}<span class="rounded-full border border-border px-2 py-1">Lifecycle</span>{/if}
            {#if showFilesystem}<span class="rounded-full border border-border px-2 py-1">Filesystem</span>{/if}
            {#if showTech}<span class="rounded-full border border-border px-2 py-1">Tech Hints</span>{/if}
          </div>
        </div>
      </div>
    </div>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root open={drawerItem !== null} onOpenChange={(isOpen) => { if (!isOpen) selectedRecommendation = null; }}>
  <Dialog.Content class="sm:max-w-4xl border-ring border-2">
    <Dialog.Header>
      <Dialog.Title>{drawerItem?.title ?? 'Recommendation Details'}</Dialog.Title>
      <Dialog.Description>Technical workspace for the selected recommendation.</Dialog.Description>
    </Dialog.Header>

    {#if drawerItem}
      <div class="grid gap-4 px-4 py-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
        <div class="space-y-3">
          <div class="overflow-hidden rounded-[1.75rem] border border-border/70 bg-gradient-to-br from-secondary/50 to-background">
            <div class="aspect-[2/3] flex items-center justify-center">
              <Images class="size-16 text-muted-foreground/60" />
            </div>
          </div>
          <div class="flex flex-wrap gap-2 text-xs">
            <span class={`rounded-full border px-2 py-1 ${ribbonBySafety[drawerItem.safety_level]}`}>Risk: {drawerItem.safety_level.replaceAll('_', ' ')}</span>
            <span class="rounded-full border border-border/70 px-2 py-1 text-muted-foreground">Action: {drawerItem.action}</span>
            <span class="rounded-full border border-border/70 px-2 py-1 text-muted-foreground">Recovery: {formatBytes(drawerItem.estimated_recovery_bytes)}</span>
          </div>
        </div>
        <div class="space-y-4">
          <div class="rounded-2xl border border-border/70 bg-background/70 p-4">
            <p class="text-xs uppercase tracking-[0.25em] text-muted-foreground">Reason</p>
            <p class="mt-2 text-sm text-foreground">{drawerItem.summary}</p>
          </div>
          <div class="grid gap-3 md:grid-cols-2">
            <div class="rounded-2xl border border-border/70 bg-background/70 p-4">
              <p class="text-xs uppercase tracking-[0.25em] text-muted-foreground">Lifecycle Timeline</p>
              <div class="mt-3 space-y-2 text-sm text-foreground">
                <p>Requested → Downloading → Imported → Verified → Protected → Seeding</p>
                <p>Seed Goal Reached → Detached → Archived</p>
              </div>
            </div>
            <div class="rounded-2xl border border-border/70 bg-background/70 p-4">
              <p class="text-xs uppercase tracking-[0.25em] text-muted-foreground">Provider Details</p>
              <div class="mt-3 space-y-2 text-sm text-foreground">
                <p>Target: {drawerItem.target_type}</p>
                <p>Target ID: {drawerItem.target_id ?? 'n/a'}</p>
                <p>Confidence: 98%</p>
              </div>
            </div>
          </div>
          <div class="rounded-2xl border border-border/70 bg-background/70 p-4">
            <p class="text-xs uppercase tracking-[0.25em] text-muted-foreground">Actions</p>
            <div class="mt-3 flex flex-wrap gap-2 text-sm">
              <button type="button" class="rounded-full border border-border px-3 py-2 text-foreground">Open Folder</button>
              <button type="button" class="rounded-full border border-border px-3 py-2 text-foreground">Open qBittorrent</button>
              <button type="button" class="rounded-full border border-border px-3 py-2 text-foreground">Approve</button>
            </div>
          </div>
        </div>
      </div>
    {/if}
  </Dialog.Content>
</Dialog.Root>
