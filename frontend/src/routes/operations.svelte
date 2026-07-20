<script lang="ts">
  import { onMount } from "svelte";
  import { get_api, post_api } from "$lib/api";
  import type {
    MieOperationsResponse,
    OperationAuditListResponse,
    OperationWorkflowResponse,
    OperationsWorkflowAsset,
    WorkflowStageKey,
  } from "$lib/types/shared";
  import { formatFileSize } from "$lib/utils/formatters";

  let loading = $state(true);
  let error = $state("");
  let workspace = $state<MieOperationsResponse | null>(null);
  let auditTrail = $state<OperationAuditListResponse | null>(null);

  let selectedStage = $state<WorkflowStageKey>("download");
  let selectedFilter = $state<string | null>(null);
  let selectedMediaType = $state<"all" | "movie" | "series">("all");
  let showCompleted = $state(false);
  let selectedAssetId = $state<string | null>(null);

  let workflowBusyId = $state<string | null>(null);
  let workflowError = $state("");
  let workflowPreview = $state<OperationWorkflowResponse | null>(null);

  const load = async () => {
    loading = true;
    error = "";
    try {
      workspace = await get_api<MieOperationsResponse>("/api/mie/operations");
      auditTrail = await get_api<OperationAuditListResponse>("/api/operations/audit");
    } catch (e: any) {
      error = e?.message ?? "Failed to load operations workflow";
    } finally {
      loading = false;
    }
  };

  const selectableRecommendationIds = $derived.by(() => {
    return new Set((workspace?.recommendations.items ?? []).map((row) => row.id));
  });

  const stageCards = $derived.by(() => {
    const rows = workspace?.workflow.stages ?? [];
    return rows.filter((row) => showCompleted || row.key !== "completed");
  });

  const stage = $derived.by(() => {
    return (
      workspace?.workflow.stages.find((row) => row.key === selectedStage) ??
      workspace?.workflow.stages[0] ??
      null
    );
  });

  const stageFilters = $derived.by(() => {
    const counts = new Map<string, number>();
    for (const row of stage?.assets ?? []) {
      for (const key of row.filters ?? []) {
        counts.set(key, (counts.get(key) ?? 0) + 1);
      }
    }
    const labels = new Map((workspace?.workflow.filters ?? []).map((row) => [row.key, row.title]));
    return Array.from(counts.entries())
      .map(([key, count]) => ({ key, title: labels.get(key) ?? key.replaceAll("_", " "), count }))
      .sort((a, b) => b.count - a.count || a.title.localeCompare(b.title));
  });

  const filteredAssets = $derived.by(() => {
    const rows = stage?.assets ?? [];
    return rows.filter((asset) => {
      const matchesFilter = !selectedFilter || asset.filters.includes(selectedFilter);
      const matchesMedia =
        selectedMediaType === "all" ||
        (selectedMediaType === "movie" && asset.media_type === "movie") ||
        (selectedMediaType === "series" && asset.media_type === "series");
      return matchesFilter && matchesMedia;
    });
  });

  const selectedAsset = $derived.by(() => {
    if (!selectedAssetId) return null;
    return filteredAssets.find((row) => row.id === selectedAssetId) ?? null;
  });

  const canRunWorkflow = $derived.by(() => {
    return !!selectedAssetId && selectableRecommendationIds.has(selectedAssetId);
  });

  const applyHashSelection = () => {
    const hash = window.location.hash || "";
    const queryIndex = hash.indexOf("?");
    if (queryIndex < 0) return;
    const params = new URLSearchParams(hash.slice(queryIndex + 1));
    const stageValue = params.get("stage") as WorkflowStageKey | null;
    const filterValue = params.get("filter");
    if (stageValue) selectedStage = stageValue;
    if (filterValue) selectedFilter = filterValue;
  };

  const runWorkflow = async (action: "preview" | "validate" | "execute") => {
    if (!selectedAssetId || !canRunWorkflow) return;
    workflowBusyId = selectedAssetId;
    workflowError = "";
    try {
      const url =
        action === "execute"
          ? `/api/operations/recommendations/${selectedAssetId}/execute`
          : `/api/operations/recommendations/${selectedAssetId}/${action}`;
      workflowPreview =
        action === "execute"
          ? await post_api<OperationWorkflowResponse>(url, {})
          : await get_api<OperationWorkflowResponse>(url);
      if (action === "execute") {
        await load();
      }
    } catch (e: any) {
      workflowError = e?.message ?? `Failed to ${action} workflow action`;
    } finally {
      workflowBusyId = null;
    }
  };

  const displayValue = (value: string | null | undefined, fallback = "Unknown") => {
    if (!value || !String(value).trim()) return fallback;
    return value;
  };

  const stageClass = (key: WorkflowStageKey, active: boolean) => {
    const base = "rounded-2xl border p-4 text-left transition";
    const state = active
      ? "border-primary bg-primary/10"
      : "border-border/70 bg-card/60 hover:bg-card";
    const accent =
      key === "cleanup"
        ? "ring-1 ring-orange-500/20"
        : key === "retention"
          ? "ring-1 ring-blue-500/20"
          : key === "completed"
            ? "ring-1 ring-emerald-500/20"
            : "";
    return `${base} ${state} ${accent}`;
  };

  onMount(async () => {
    await load();
    applyHashSelection();
  });
</script>

<div class="p-2.5 md:p-8">
  <div class="mx-auto max-w-7xl space-y-6">
    <header class="rounded-[2rem] border border-border/70 bg-gradient-to-br from-card via-background to-secondary/20 p-6 shadow-xl shadow-black/10">
      <p class="text-xs uppercase tracking-[0.3em] text-muted-foreground">
        Media Lifecycle Operations
      </p>
      <h1 class="text-4xl font-black tracking-tight text-foreground">Operations Workflow</h1>
      <p class="mt-2 text-sm text-muted-foreground">
        Move assets from Download to Completed with explicit blockers, recommendations, and next actions.
      </p>
    </header>

    {#if loading}
      <div class="rounded-xl border border-border bg-card p-6 text-muted-foreground">
        Loading operations workflow...
      </div>
    {:else if error}
      <div class="rounded-xl border border-destructive/40 bg-destructive/10 p-6 text-destructive">
        {error}
      </div>
    {:else}
      <section class="space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h2 class="text-lg font-semibold text-foreground">Lifecycle Stages</h2>
          <button
            type="button"
            class={`rounded-full border px-3 py-1.5 text-xs ${showCompleted ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
            onclick={() => (showCompleted = !showCompleted)}
          >
            {showCompleted ? "Hide Completed" : "Show Completed"}
          </button>
        </div>
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
          {#each stageCards as col}
            <button
              type="button"
              class={stageClass(col.key, selectedStage === col.key)}
              onclick={() => {
                selectedStage = col.key;
                selectedFilter = null;
                selectedAssetId = null;
              }}
            >
              <p class="text-xs uppercase tracking-[0.18em] text-muted-foreground">{col.title}</p>
              <p class="mt-2 text-2xl font-black text-foreground">{col.count}</p>
              <p class="mt-1 text-xs text-muted-foreground">{col.description}</p>
            </button>
          {/each}
        </div>
      </section>

      <section class="grid gap-3 xl:grid-cols-3">
        <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
          <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">Current Stage</p>
          <p class="mt-2 text-xl font-bold text-foreground">{stage?.title ?? "n/a"}</p>
          <p class="mt-1 text-xs text-muted-foreground">{stage?.description ?? ""}</p>
        </div>
        <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
          <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">Filtered Assets</p>
          <p class="mt-2 text-xl font-bold text-foreground">{filteredAssets.length}</p>
          <p class="mt-1 text-xs text-muted-foreground">From {stage?.count ?? 0} assets in this stage</p>
        </div>
        <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
          <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">Operations SLO</p>
          <p class="mt-2 text-sm text-foreground">Dashboard &lt;2s • Operations &lt;3s</p>
          <p class="mt-1 text-xs text-muted-foreground">Request-scoped intelligence reuse enabled</p>
        </div>
      </section>

      <section class="space-y-3">
        <h2 class="text-lg font-semibold text-foreground">Stage Filters</h2>
        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class={`rounded-full border px-3 py-1.5 text-xs ${selectedFilter === null ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
            onclick={() => {
              selectedFilter = null;
              selectedAssetId = null;
            }}
          >
            All ({stage?.count ?? 0})
          </button>
          {#each stageFilters as filter}
            <button
              type="button"
              class={`rounded-full border px-3 py-1.5 text-xs ${selectedFilter === filter.key ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
              onclick={() => {
                selectedFilter = filter.key;
                selectedAssetId = null;
              }}
            >
              {filter.title} ({filter.count})
            </button>
          {/each}
        </div>

        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class={`rounded-full border px-3 py-1.5 text-xs ${selectedMediaType === "all" ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
            onclick={() => {
              selectedMediaType = "all";
              selectedAssetId = null;
            }}
          >
            All Media
          </button>
          <button
            type="button"
            class={`rounded-full border px-3 py-1.5 text-xs ${selectedMediaType === "movie" ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
            onclick={() => {
              selectedMediaType = "movie";
              selectedAssetId = null;
            }}
          >
            Movies
          </button>
          <button
            type="button"
            class={`rounded-full border px-3 py-1.5 text-xs ${selectedMediaType === "series" ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
            onclick={() => {
              selectedMediaType = "series";
              selectedAssetId = null;
            }}
          >
            Series
          </button>
        </div>
      </section>

      <section class="space-y-3">
        <h2 class="text-lg font-semibold text-foreground">Affected Assets</h2>
        {#if filteredAssets.length === 0}
          <p class="rounded-2xl border border-border/70 bg-card/60 p-4 text-sm text-muted-foreground">
            No affected assets for the current stage/filter combination.
          </p>
        {:else}
          <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {#each filteredAssets as asset (asset.id)}
              <button
                type="button"
                class={`rounded-2xl border bg-card/60 p-4 text-left transition ${selectedAssetId === asset.id ? "border-primary" : "border-border/70 hover:bg-card"}`}
                onclick={() => {
                  selectedAssetId = asset.id;
                  workflowError = "";
                }}
              >
                <p class="text-xs uppercase tracking-[0.18em] text-muted-foreground">{asset.current_stage}</p>
                <h3 class="mt-1 line-clamp-2 text-base font-semibold text-foreground">{asset.title}</h3>
                <p class="mt-1 text-xs text-muted-foreground">Status: {displayValue(asset.current_status)}</p>
                <p class="mt-1 text-xs text-muted-foreground">Policy: {displayValue(asset.policy_name)}</p>
                <p class="mt-1 text-xs text-muted-foreground">Library: {displayValue(asset.library_location)}</p>
                <p class="mt-1 text-xs text-muted-foreground">Download: {displayValue(asset.download_location)}</p>
                <p class="mt-1 text-xs text-muted-foreground">Torrent: {displayValue(asset.torrent_state)}</p>
                <p class="mt-1 text-xs text-muted-foreground">Import: {displayValue(asset.import_state)}</p>
                <p class="mt-1 text-xs text-muted-foreground">Retention: {displayValue(asset.retention_policy)} {asset.retention_remaining ? `(${asset.retention_remaining})` : ""}</p>
                <p class="mt-2 text-xs text-muted-foreground">Recommendation: {displayValue(asset.recommendation)}</p>
                <p class="mt-1 text-xs text-muted-foreground">Reason: {displayValue(asset.reason)}</p>
                <p class="mt-1 text-xs text-muted-foreground">Next Action: {displayValue(asset.next_action)}</p>
                <p class="mt-1 text-xs text-muted-foreground">After Action: {displayValue(asset.after_action)}</p>
                <p class="mt-1 text-xs text-muted-foreground">Confidence: {asset.confidence ?? 0}%</p>
                <p class="mt-1 text-xs text-muted-foreground">Recoverable: {formatFileSize(asset.estimated_space_recovery ?? 0)}</p>
                <p class="mt-1 text-xs text-muted-foreground">Graph: {(asset.graph_references ?? []).join(" • ") || "No graph references"}</p>
              </button>
            {/each}
          </div>
        {/if}
      </section>

      <section class="space-y-3 sticky bottom-0 z-10 border-t border-border/50 bg-background/95 py-2 backdrop-blur">
        <h2 class="text-lg font-semibold text-foreground">Preview / Validate / Execute</h2>
        <div class="rounded-2xl border border-border/70 bg-card/60 p-4 text-sm">
          <div class="mb-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40"
              onclick={() => runWorkflow("preview")}
              disabled={!canRunWorkflow || workflowBusyId === selectedAssetId}
            >Preview</button>
            <button
              type="button"
              class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40"
              onclick={() => runWorkflow("validate")}
              disabled={!canRunWorkflow || workflowBusyId === selectedAssetId}
            >Validate</button>
            <button
              type="button"
              class="rounded-full border border-primary bg-primary/10 px-3 py-1.5 text-xs text-primary hover:bg-primary/20"
              onclick={() => runWorkflow("execute")}
              disabled={!canRunWorkflow || workflowBusyId === selectedAssetId}
            >Execute</button>
            {#if selectedAssetId && !canRunWorkflow}
              <span class="text-xs text-muted-foreground">
                Workflow actions are available for recommendation-backed assets only.
              </span>
            {/if}
          </div>

          {#if workflowError}
            <p class="text-destructive">{workflowError}</p>
          {/if}

          {#if workflowPreview}
            <p class="font-medium text-foreground">Asset {workflowPreview.recommendation_id}</p>
            <p class="text-muted-foreground">
              Preview: {workflowPreview.preview.target_count} target •
              {formatFileSize(workflowPreview.preview.estimated_recovery_bytes)}
            </p>
            <p class="mt-2 text-muted-foreground">
              Validation: {workflowPreview.validation.valid ? "Passed" : "Failed"}
            </p>
            <ul class="mt-2 space-y-1 text-xs text-muted-foreground">
              {#each workflowPreview.validation.checks as check}
                <li>{check.passed ? "✓" : "✗"} {check.label}: {check.detail}</li>
              {/each}
            </ul>
            <p class="mt-2 text-muted-foreground">
              Execution: {workflowPreview.execution.result} • {workflowPreview.execution.message}
            </p>
          {:else}
            <p class="text-muted-foreground">
              Select an asset and run Preview, Validate, then Execute.
            </p>
          {/if}
        </div>
      </section>

      <section class="space-y-3">
        <h2 class="text-lg font-semibold text-foreground">Media Policies</h2>
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {#each workspace?.media_policies ?? [] as policy}
            <div class="rounded-2xl border border-border/70 bg-card/60 p-4 text-xs">
              <p class="font-semibold text-foreground">{policy.name}</p>
              <p class="mt-1 text-muted-foreground">Destination: {policy.destination_library}</p>
              <p class="mt-1 text-muted-foreground">Retention: {policy.retention_period_days} days</p>
              <p class="mt-1 text-muted-foreground">Min Ratio: {policy.minimum_ratio.toFixed(2)}</p>
              <p class="mt-1 text-muted-foreground">Min Seed: {policy.minimum_seed_time_hours}h</p>
              <p class="mt-1 text-muted-foreground">Cleanup: {policy.cleanup_behavior}</p>
              <p class="mt-1 text-muted-foreground">Protection: {policy.protection_rules.join(" • ") || "none"}</p>
            </div>
          {/each}
        </div>
      </section>

      <section class="space-y-3">
        <h2 class="text-lg font-semibold text-foreground">Audit Log</h2>
        <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
          {#if auditTrail && auditTrail.items.length > 0}
            <div class="space-y-2 text-xs">
              {#each auditTrail.items.slice(0, 10) as row}
                <div class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/50 bg-background/70 px-3 py-2">
                  <span class="text-foreground">{row.action} • {row.target_type}#{row.target_id ?? "n/a"}</span>
                  <span class="text-muted-foreground">{row.result} • {formatFileSize(row.recovery_bytes)}</span>
                </div>
              {/each}
            </div>
          {:else}
            <p class="text-sm text-muted-foreground">No operation history yet.</p>
          {/if}
        </div>
      </section>
    {/if}
  </div>
</div>
