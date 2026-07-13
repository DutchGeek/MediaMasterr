<script lang="ts">
  import { onMount } from "svelte";
  import { get_api } from "$lib/api";
  import type {
    CleanupPlanListResponse,
    FilesystemConfigResponse,
    OperationsOverviewResponse,
    OperationsRecommendationsResponse,
  } from "$lib/types/shared";

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

  let loading = $state(true);
  let error = $state("");
  let overview = $state<OperationsOverviewResponse | null>(null);
  let recommendations = $state<OperationsRecommendationsResponse | null>(null);
  let filesystem = $state<FilesystemConfigResponse | null>(null);
  let plans = $state<CleanupPlanListResponse | null>(null);
  let selectedCard = $state<string | null>(null);

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

  const visibleRecommendations = $derived.by(() => {
    if (!recommendations) return [];
    if (!selectedCard) return recommendations.items;
    return recommendations.items.filter((item) => item.card_key === selectedCard);
  });

  onMount(() => {
    void load();
  });
</script>

<div class="p-2.5 md:p-8">
  <div class="mx-auto max-w-7xl space-y-4">
    <div>
      <h1 class="text-3xl font-bold text-foreground">Operations</h1>
      <p class="text-muted-foreground">
        Media Intelligence Engine recommendations, filesystem posture, and cleanup planning.
      </p>
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
      <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {#each overview?.cards ?? [] as card}
          <button
            type="button"
            class="rounded-xl border p-4 text-left transition {selectedCard === card.key
              ? 'border-primary bg-primary/10'
              : 'border-border bg-card hover:bg-secondary/30'}"
            onclick={() => (selectedCard = selectedCard === card.key ? null : card.key)}
          >
            <p class="text-xs uppercase tracking-wide text-muted-foreground">{card.title}</p>
            <p class="mt-1 text-3xl font-bold text-foreground">{card.count}</p>
            <p class="mt-2 text-xs text-muted-foreground">{card.description}</p>
          </button>
        {/each}
      </div>

      <div class="grid gap-4 xl:grid-cols-[2fr_1fr]">
        <section class="rounded-xl border border-border bg-card p-4">
          <div class="mb-3 flex items-center justify-between gap-3">
            <h2 class="text-lg font-semibold text-foreground">Recommendations</h2>
            {#if selectedCard}
              <button
                type="button"
                class="rounded border border-border px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
                onclick={() => (selectedCard = null)}
              >
                Clear filter
              </button>
            {/if}
          </div>

          {#if visibleRecommendations.length === 0}
            <p class="text-sm text-muted-foreground">No recommendations for the current filter.</p>
          {:else}
            <div class="space-y-2">
              {#each visibleRecommendations as item}
                <article class="rounded-lg border border-border/70 bg-background/60 p-3">
                  <div class="flex items-start justify-between gap-2">
                    <div>
                      <p class="font-medium text-foreground">{item.title}</p>
                      <p class="text-sm text-muted-foreground">{item.summary}</p>
                    </div>
                    <span class="rounded border border-border px-2 py-1 text-[11px] uppercase tracking-wide text-muted-foreground">
                      {item.safety_level.replace("_", " ")}
                    </span>
                  </div>
                  <div class="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span>Action: {item.action}</span>
                    <span>Recovery: {formatBytes(item.estimated_recovery_bytes)}</span>
                    {#if item.target_id}
                      <span>Target: {item.target_type}#{item.target_id}</span>
                    {/if}
                  </div>
                </article>
              {/each}
            </div>
          {/if}
        </section>

        <section class="space-y-4">
          <div class="rounded-xl border border-border bg-card p-4">
            <h2 class="text-lg font-semibold text-foreground">Filesystem</h2>
            <p class="mt-1 text-sm text-muted-foreground">
              Access mode: <span class="font-medium text-foreground">{filesystem?.access_mode ?? "unknown"}</span>
            </p>
            <div class="mt-3 space-y-2">
              {#each filesystem?.roots ?? [] as root}
                <div class="rounded-lg border border-border/70 bg-background/60 px-3 py-2 text-sm">
                  <p class="font-medium text-foreground">{root.name}</p>
                  <p class="text-xs text-muted-foreground">{root.path}</p>
                </div>
              {/each}
            </div>
          </div>

          <div class="rounded-xl border border-border bg-card p-4">
            <h2 class="text-lg font-semibold text-foreground">Cleanup Plans</h2>
            <div class="mt-3 space-y-2">
              {#each plans?.plans ?? [] as plan}
                <div class="rounded-lg border border-border/70 bg-background/60 px-3 py-2 text-sm">
                  <p class="font-medium text-foreground">{plan.name}</p>
                  <p class="text-xs text-muted-foreground">
                    {plan.operation_count} operations • {formatBytes(plan.estimated_recovery_bytes)} • {plan.status}
                  </p>
                </div>
              {/each}
            </div>
          </div>
        </section>
      </div>
    {/if}
  </div>
</div>
