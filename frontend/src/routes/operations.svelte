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
  import {
    confidenceBarClass,
    confidenceLabel,
    inferCategory,
    isBlockedAsset,
    isNeedsReviewAsset,
    isReadyAsset,
    riskLabel,
    stageStats,
    summarizeBulkAction,
    toggleAssetSelection,
  } from "$lib/operations/workspace-view.js";

  let loading = $state(true);
  let error = $state("");
  let workspace = $state<MieOperationsResponse | null>(null);
  let auditTrail = $state<OperationAuditListResponse | null>(null);

  let selectedStage = $state<WorkflowStageKey>("download");
  let selectedFilter = $state<string | null>(null);
  let selectedMediaType = $state<
    "all" | "movies" | "series" | "anime" | "collections"
  >("all");
  let selectedReadiness = $state<
    | "all"
    | "ready"
    | "blocked"
    | "needs_review"
    | "high_confidence"
    | "low_confidence"
  >("all");
  let showCompleted = $state(false);

  let stageSelections = $state<Record<string, Set<string>>>({});
  let lastClickedByStage = $state<Record<string, string | null>>({});
  let selectedAssetId = $state<string | null>(null);

  let workflowBusy = $state(false);
  let workflowProgress = $state({ total: 0, completed: 0, failed: 0 });
  let workflowError = $state("");
  let workflowResults = $state<OperationWorkflowResponse[]>([]);

  const load = async () => {
    loading = true;
    error = "";
    try {
      workspace = await get_api<MieOperationsResponse>("/api/mie/operations");
      auditTrail = await get_api<OperationAuditListResponse>("/api/operations/audit");
    } catch (e: any) {
      error = e?.message ?? "Failed to load operations workspace";
    } finally {
      loading = false;
    }
  };

  const selectableRecommendationIds = $derived.by(() => {
    return new Set((workspace?.recommendations.items ?? []).map((row) => row.id));
  });

  const stageRows = $derived.by(() => {
    return (workspace?.workflow?.stages ?? []).filter(
      (row) => showCompleted || row.key !== "completed",
    );
  });

  const activeStage = $derived.by(() => {
    return (
      stageRows.find((row) => row.key === selectedStage) ?? stageRows[0] ?? null
    );
  });

  const activeStageAssets = $derived.by(() => activeStage?.assets ?? []);

  const stageFilterRows = $derived.by(() => {
    const counts = new Map<string, number>();
    const labels = new Map(
      (workspace?.workflow?.filters ?? []).map((row) => [row.key, row.title]),
    );

    for (const asset of activeStageAssets) {
      for (const key of asset.filters ?? []) {
        counts.set(key, (counts.get(key) ?? 0) + 1);
      }
    }

    return Array.from(counts.entries())
      .map(([key, count]) => ({
        key,
        title: labels.get(key) ?? key.replaceAll("_", " "),
        count,
      }))
      .sort((a, b) => b.count - a.count || a.title.localeCompare(b.title));
  });

  const filteredAssets = $derived.by(() => {
    return activeStageAssets.filter((asset) => {
      if (selectedFilter && !asset.filters.includes(selectedFilter)) {
        return false;
      }

      if (selectedMediaType !== "all") {
        const category = inferCategory(asset);
        if (category !== selectedMediaType) {
          return false;
        }
      }

      if (selectedReadiness === "ready" && !isReadyAsset(asset)) return false;
      if (selectedReadiness === "blocked" && !isBlockedAsset(asset)) return false;
      if (selectedReadiness === "needs_review" && !isNeedsReviewAsset(asset)) {
        return false;
      }
      if (selectedReadiness === "high_confidence" && (asset.confidence ?? 0) < 85) {
        return false;
      }
      if (selectedReadiness === "low_confidence" && (asset.confidence ?? 0) >= 60) {
        return false;
      }

      return true;
    });
  });

  const orderedFilteredIds = $derived.by(() => filteredAssets.map((asset) => asset.id));

  const selectedIdsInStage = $derived.by(() => {
    const key = activeStage?.key ?? "download";
    return stageSelections[key] ?? new Set<string>();
  });

  const selectedAssets = $derived.by(() => {
    return filteredAssets.filter((asset) => selectedIdsInStage.has(asset.id));
  });

  const selectedRecommendationIds = $derived.by(() => {
    return selectedAssets
      .map((asset) => asset.id)
      .filter((id) => selectableRecommendationIds.has(id));
  });

  const selectedAsset = $derived.by(() => {
    if (!selectedAssetId) return null;
    return filteredAssets.find((asset) => asset.id === selectedAssetId) ?? null;
  });

  const bulkSummary = $derived.by(() => summarizeBulkAction(workflowResults));

  const progressPercent = $derived.by(() => {
    if (!workflowProgress.total) return 0;
    return Math.round((workflowProgress.completed / workflowProgress.total) * 100);
  });

  const setStageSelection = (stageKey: string, next: Set<string>) => {
    stageSelections = {
      ...stageSelections,
      [stageKey]: new Set(next),
    };
  };

  const toggleAsset = (assetId: string, checked: boolean, shiftKey: boolean) => {
    const stageKey = activeStage?.key ?? "download";
    const current = stageSelections[stageKey] ?? new Set<string>();
    const next = toggleAssetSelection(current, orderedFilteredIds, assetId, {
      checked,
      shift: shiftKey,
      lastClickedId: lastClickedByStage[stageKey] ?? null,
    });
    setStageSelection(stageKey, next);
    lastClickedByStage = { ...lastClickedByStage, [stageKey]: assetId };
  };

  const selectAllFiltered = () => {
    const stageKey = activeStage?.key ?? "download";
    const next = new Set(selectedIdsInStage);
    for (const id of orderedFilteredIds) next.add(id);
    setStageSelection(stageKey, next);
  };

  const clearSelection = () => {
    const stageKey = activeStage?.key ?? "download";
    setStageSelection(stageKey, new Set<string>());
  };

  const refreshWorkspace = async () => {
    await load();
  };

  const bulkAction = async (mode: "preview" | "validate" | "execute") => {
    if (!selectedRecommendationIds.length) {
      workflowError = "Select at least one recommendation-backed asset first.";
      return;
    }

    workflowBusy = true;
    workflowError = "";
    workflowResults = [];
    workflowProgress = {
      total: selectedRecommendationIds.length,
      completed: 0,
      failed: 0,
    };

    const results: OperationWorkflowResponse[] = [];
    for (const id of selectedRecommendationIds) {
      try {
        const url =
          mode === "execute"
            ? `/api/operations/recommendations/${id}/execute`
            : `/api/operations/recommendations/${id}/${mode}`;
        const response =
          mode === "execute"
            ? await post_api<OperationWorkflowResponse>(url, {})
            : await get_api<OperationWorkflowResponse>(url);
        results.push(response);
      } catch (e: any) {
        workflowProgress = {
          ...workflowProgress,
          failed: workflowProgress.failed + 1,
        };
        results.push({
          recommendation_id: id,
          preview: {
            target_count: 0,
            estimated_recovery_bytes: 0,
            details: [e?.message ?? "Request failed"],
          },
          validation: {
            valid: false,
            checks: [
              {
                label: "Request",
                passed: false,
                detail: e?.message ?? "Request failed",
              },
            ],
          },
          execution: {
            executed: false,
            result: "failed",
            message: e?.message ?? "Request failed",
            operation_history_id: null,
          },
        });
      } finally {
        workflowProgress = {
          ...workflowProgress,
          completed: workflowProgress.completed + 1,
        };
      }
    }

    workflowResults = results;
    if (mode === "execute") {
      await refreshWorkspace();
    }
    workflowBusy = false;
  };

  const onKeyboardShortcuts = (event: KeyboardEvent) => {
    if (!activeStage) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
      event.preventDefault();
      selectAllFiltered();
      return;
    }
    if (event.key === "Escape") {
      clearSelection();
    }
  };

  const stageCardClass = (key: WorkflowStageKey, active: boolean) => {
    const base = "rounded-2xl border p-4 text-left transition";
    const state = active
      ? "border-primary bg-primary/10"
      : "border-border/70 bg-card/60 hover:bg-card";
    const accent =
      key === "cleanup"
        ? "ring-1 ring-orange-500/30"
        : key === "retention"
          ? "ring-1 ring-blue-500/30"
          : key === "completed"
            ? "ring-1 ring-emerald-500/30"
            : "";
    return `${base} ${state} ${accent}`;
  };

  const posterAlt = (asset: OperationsWorkflowAsset) => `${asset.title} poster`;

  const applyHashSelection = () => {
    const hash = window.location.hash || "";
    const queryIndex = hash.indexOf("?");
    if (queryIndex < 0) return;
    const params = new URLSearchParams(hash.slice(queryIndex + 1));
    const stageValue = params.get("stage") as WorkflowStageKey | null;
    if (stageValue) selectedStage = stageValue;
  };

  onMount(async () => {
    await load();
    applyHashSelection();
  });
</script>

<svelte:window onkeydown={onKeyboardShortcuts} />

<div class="p-2.5 md:p-8">
  <div class="mx-auto max-w-[1500px] space-y-6">
    <header class="rounded-[2rem] border border-border/70 bg-gradient-to-br from-card via-background to-secondary/20 p-6 shadow-xl shadow-black/10">
      <p class="text-xs uppercase tracking-[0.3em] text-muted-foreground">
        Operations Workspace
      </p>
      <h1 class="text-4xl font-black tracking-tight text-foreground">
        Media Lifecycle Console
      </h1>
      <p class="mt-2 text-sm text-muted-foreground">
        Visual-first lifecycle operations with bulk preview, validation, and execution.
      </p>
    </header>

    {#if loading}
      <div class="rounded-xl border border-border bg-card p-6 text-muted-foreground">
        Loading operations workspace...
      </div>
    {:else if error}
      <div class="rounded-xl border border-destructive/40 bg-destructive/10 p-6 text-destructive">
        {error}
      </div>
    {:else}
      <section class="space-y-3">
        <div class="flex items-center justify-between gap-3">
          <h2 class="text-lg font-semibold text-foreground">Workflow Lanes</h2>
          <button
            type="button"
            class={`rounded-full border px-3 py-1.5 text-xs ${showCompleted ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
            onclick={() => (showCompleted = !showCompleted)}
          >
            {showCompleted ? "Hide Completed" : "Show Completed"}
          </button>
        </div>

        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
          {#each stageRows as stage}
            {@const stats = stageStats(stage.assets)}
            <button
              type="button"
              class={stageCardClass(stage.key, selectedStage === stage.key)}
              onclick={() => {
                selectedStage = stage.key;
                selectedAssetId = null;
              }}
            >
              <p class="text-xs uppercase tracking-[0.18em] text-muted-foreground">{stage.title}</p>
              <p class="mt-2 text-2xl font-black text-foreground">{stage.count}</p>
              <p class="mt-1 text-xs text-muted-foreground">{stage.description}</p>
              <div class="mt-3 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                <span>Ready {stats.ready}</span>
                <span>Blocked {stats.blocked}</span>
                <span>Needs Review {stats.needsReview}</span>
                <span>Warnings {stats.warnings}</span>
              </div>
            </button>
          {/each}
        </div>
      </section>

      <section class="space-y-3">
        <h2 class="text-lg font-semibold text-foreground">Filters</h2>

        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class={`rounded-full border px-3 py-1.5 text-xs ${selectedFilter === null ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
            onclick={() => (selectedFilter = null)}
          >
            All ({activeStage?.count ?? 0})
          </button>
          {#each stageFilterRows as row}
            <button
              type="button"
              class={`rounded-full border px-3 py-1.5 text-xs ${selectedFilter === row.key ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
              onclick={() => (selectedFilter = row.key)}
            >
              {row.title} ({row.count})
            </button>
          {/each}
        </div>

        <div class="flex flex-wrap gap-2">
          {#each ["all", "movies", "series", "anime", "collections"] as option}
            <button
              type="button"
              class={`rounded-full border px-3 py-1.5 text-xs ${selectedMediaType === option ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
              onclick={() => (selectedMediaType = option as typeof selectedMediaType)}
            >
              {option === "all" ? "All Media" : option[0].toUpperCase() + option.slice(1)}
            </button>
          {/each}
        </div>

        <div class="flex flex-wrap gap-2">
          {#each [
            ["all", "All"],
            ["ready", "Ready"],
            ["blocked", "Blocked"],
            ["needs_review", "Needs Review"],
            ["high_confidence", "High Confidence"],
            ["low_confidence", "Low Confidence"],
          ] as [key, label]}
            <button
              type="button"
              class={`rounded-full border px-3 py-1.5 text-xs ${selectedReadiness === key ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
              onclick={() => (selectedReadiness = key as typeof selectedReadiness)}
            >
              {label}
            </button>
          {/each}
        </div>
      </section>

      <section class="sticky top-2 z-20 rounded-2xl border border-border/70 bg-background/95 p-3 shadow backdrop-blur">
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="font-semibold text-foreground">Selected:</span>
          <span class="rounded-full border border-border px-2 py-1 text-xs text-foreground">{selectedAssets.length} Assets</span>
          <span class="rounded-full border border-border px-2 py-1 text-xs text-muted-foreground">Recommendation-backed: {selectedRecommendationIds.length}</span>

          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40" onclick={selectAllFiltered}>Select All</button>
          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40" onclick={clearSelection}>Clear Selection</button>
          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40" onclick={() => bulkAction("preview")} disabled={workflowBusy}>Preview</button>
          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40" onclick={() => bulkAction("validate")} disabled={workflowBusy}>Validate</button>
          <button type="button" class="rounded-full border border-primary bg-primary/10 px-3 py-1.5 text-xs text-primary hover:bg-primary/20" onclick={() => bulkAction("execute")} disabled={workflowBusy}>Execute</button>
          <button type="button" class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40" onclick={refreshWorkspace} disabled={workflowBusy}>Refresh</button>
          <button
            type="button"
            class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40"
            onclick={() => {
              const data = JSON.stringify(selectedAssets, null, 2);
              const blob = new Blob([data], { type: "application/json" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `operations-${activeStage?.key ?? "stage"}-selection.json`;
              a.click();
              URL.revokeObjectURL(url);
            }}
          >
            Export
          </button>
        </div>

        {#if workflowBusy || workflowResults.length > 0 || workflowError}
          <div class="mt-3 rounded-xl border border-border/60 bg-card/60 p-3 text-xs">
            <div class="flex flex-wrap items-center gap-2 text-muted-foreground">
              <span>Assets Selected {selectedRecommendationIds.length}</span>
              <span>Validated {bulkSummary.validated}</span>
              <span>Blocked {bulkSummary.blocked}</span>
              <span>Warnings {bulkSummary.warnings}</span>
              <span>Expected Success {bulkSummary.expectedSuccess}</span>
              <span>Estimated Recovery {formatFileSize(bulkSummary.estimatedRecovery)}</span>
            </div>

            {#if workflowBusy}
              <div class="mt-2">
                <p class="text-muted-foreground">Executing...</p>
                <div class="mt-1 h-2 w-full overflow-hidden rounded-full bg-secondary/50">
                  <div
                    class="h-full bg-primary transition-all"
                    style={`width:${progressPercent}%`}
                  ></div>
                </div>
                <p class="mt-1 text-muted-foreground">
                  Completed {workflowProgress.completed} • Remaining
                  {Math.max(0, workflowProgress.total - workflowProgress.completed)} • Failed {workflowProgress.failed}
                </p>
              </div>
            {/if}

            {#if workflowError}
              <p class="mt-2 text-destructive">{workflowError}</p>
            {/if}
          </div>
        {/if}
      </section>

      <section class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div class="space-y-3">
          <h2 class="text-lg font-semibold text-foreground">Assets in {activeStage?.title ?? "Stage"}</h2>

          {#if filteredAssets.length === 0}
            <p class="rounded-2xl border border-border/70 bg-card/60 p-4 text-sm text-muted-foreground">
              No assets for this stage/filter combination.
            </p>
          {:else}
            <div class="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
              {#each filteredAssets as asset (asset.id)}
                {@const hasPoster = !!asset.poster_url}
                <article
                  class={`rounded-2xl border bg-card/60 p-3 transition ${selectedAssetId === asset.id ? "border-primary" : "border-border/70 hover:bg-card"}`}
                >
                  <div class="mb-2 flex items-start justify-between gap-2">
                    <label class="inline-flex items-center gap-2 text-xs text-muted-foreground">
                      <input
                        type="checkbox"
                        aria-label={`Select ${asset.title}`}
                        checked={selectedIdsInStage.has(asset.id)}
                        onclick={(event) =>
                          toggleAsset(
                            asset.id,
                            (event.currentTarget as HTMLInputElement).checked,
                            (event as MouseEvent).shiftKey,
                          )}
                      />
                      Select
                    </label>
                    <button
                      type="button"
                      class="text-xs text-primary underline-offset-2 hover:underline"
                      onclick={() => (selectedAssetId = asset.id)}
                    >
                      Inspect
                    </button>
                  </div>

                  <button
                    type="button"
                    class="w-full text-left"
                    onclick={() => (selectedAssetId = asset.id)}
                    aria-label={`Open inspector for ${asset.title}`}
                  >
                    {#if hasPoster}
                      <img
                        src={asset.poster_url ?? ""}
                        alt={posterAlt(asset)}
                        class="h-64 w-full rounded-xl object-cover"
                        loading="lazy"
                      />
                    {:else}
                      <div class="flex h-64 w-full flex-col items-center justify-center rounded-xl border border-dashed border-border bg-secondary/30 px-3 text-center">
                        <p class="text-sm font-semibold text-foreground">Missing Artwork</p>
                        <p class="mt-1 text-xs text-muted-foreground">Artwork Repair Available</p>
                      </div>
                    {/if}

                    <div class="mt-3 space-y-2">
                      <h3 class="line-clamp-2 text-base font-semibold text-foreground">{asset.title}</h3>
                      <p class="text-xs text-muted-foreground">
                        {asset.year ?? "Year n/a"} • {asset.media_type ?? "Media n/a"} • {asset.current_stage}
                      </p>

                      <div class="rounded-lg bg-background/70 p-2">
                        <p class="text-xs uppercase tracking-[0.14em] text-muted-foreground">Current Status</p>
                        <p class="mt-1 text-sm text-foreground">{asset.current_status}</p>
                      </div>

                      <div class="rounded-lg bg-background/70 p-2">
                        <p class="text-xs uppercase tracking-[0.14em] text-muted-foreground">Recommendation</p>
                        <p class="mt-1 text-sm font-semibold text-foreground">{asset.next_action.replaceAll("_", " ")}</p>
                        <p class="mt-1 text-xs text-muted-foreground">{asset.recommendation}</p>
                      </div>

                      <div>
                        <div class="flex items-center justify-between text-xs">
                          <span class="text-muted-foreground">Confidence</span>
                          <span class="text-foreground">{confidenceLabel(asset.confidence)} {asset.confidence ?? 0}%</span>
                        </div>
                        <div class="mt-1 h-2 overflow-hidden rounded-full bg-secondary/50">
                          <div class={`h-full ${confidenceBarClass(asset.confidence)}`} style={`width:${asset.confidence ?? 0}%`}></div>
                        </div>
                      </div>

                      <div class="flex flex-wrap items-center gap-2 text-xs">
                        <span class="rounded-full border border-border px-2 py-0.5 text-muted-foreground">Risk {riskLabel(asset.risk_level)}</span>
                        {#if asset.estimated_space_recovery > 0}
                          <span class="rounded-full border border-border px-2 py-0.5 text-muted-foreground">Recoverable {formatFileSize(asset.estimated_space_recovery)}</span>
                        {/if}
                      </div>

                      <details class="rounded-lg border border-border/60 bg-background/40 p-2 text-xs text-muted-foreground">
                        <summary class="cursor-pointer font-medium text-foreground">Why?</summary>
                        <ul class="mt-2 space-y-1">
                          <li>✓ {asset.reason}</li>
                          {#if asset.library_location}<li>✓ Library path verified</li>{/if}
                          {#if asset.torrent_state}<li>✓ Torrent state {asset.torrent_state}</li>{/if}
                          {#if asset.import_state}<li>✓ Import state {asset.import_state}</li>{/if}
                          {#if asset.retention_policy}<li>✓ Retention policy {asset.retention_policy}</li>{/if}
                        </ul>
                      </details>

                      <details class="rounded-lg border border-border/60 bg-background/40 p-2 text-xs text-muted-foreground">
                        <summary class="cursor-pointer font-medium text-foreground">Technical Details</summary>
                        <div class="mt-2 space-y-1">
                          {#if asset.download_location}<p>Download: {asset.download_location}</p>{/if}
                          {#if asset.library_location}<p>Library: {asset.library_location}</p>{/if}
                          {#if asset.policy_name}<p>Policy: {asset.policy_name}</p>{/if}
                          {#if asset.graph_references.length > 0}
                            <p>Graph refs: {asset.graph_references.join(" • ")}</p>
                          {:else}
                            <p>Additional provider information unavailable.</p>
                          {/if}
                        </div>
                      </details>
                    </div>
                  </button>
                </article>
              {/each}
            </div>
          {/if}
        </div>

        <aside class="rounded-2xl border border-border/70 bg-card/60 p-4">
          {#if selectedAsset}
            <h2 class="text-lg font-semibold text-foreground">Inspector</h2>

            <div class="mt-3 space-y-3 text-sm">
              {#if selectedAsset.poster_url}
                <img
                  src={selectedAsset.poster_url}
                  alt={posterAlt(selectedAsset)}
                  class="h-72 w-full rounded-xl object-cover"
                  loading="lazy"
                />
              {:else}
                <div class="flex h-72 w-full items-center justify-center rounded-xl border border-dashed border-border bg-secondary/20 text-xs text-muted-foreground">
                  Missing Artwork • Artwork Repair Available
                </div>
              {/if}

              <div>
                <p class="text-xs uppercase tracking-[0.18em] text-muted-foreground">Identity</p>
                <p class="mt-1 text-foreground">{selectedAsset.title}</p>
                <p class="text-xs text-muted-foreground">
                  {selectedAsset.media_type ?? "media"}
                  {#if selectedAsset.year} • {selectedAsset.year}{/if}
                </p>
              </div>

              <div>
                <p class="text-xs uppercase tracking-[0.18em] text-muted-foreground">Timeline</p>
                <p class="mt-1 text-foreground">Stage {selectedAsset.current_stage}</p>
                <p class="text-xs text-muted-foreground">Status {selectedAsset.current_status}</p>
              </div>

              <div>
                <p class="text-xs uppercase tracking-[0.18em] text-muted-foreground">Relationships</p>
                <p class="text-xs text-muted-foreground">
                  {(selectedAsset.graph_references ?? []).join(" • ") ||
                    "Additional relationship details unavailable."}
                </p>
              </div>

              <div>
                <p class="text-xs uppercase tracking-[0.18em] text-muted-foreground">Providers</p>
                <p class="text-xs text-muted-foreground">
                  {selectedAsset.torrent_state ? `Torrent ${selectedAsset.torrent_state}` : "Provider status unavailable"}
                </p>
              </div>

              <div>
                <p class="text-xs uppercase tracking-[0.18em] text-muted-foreground">Policies</p>
                <p class="text-xs text-muted-foreground">{selectedAsset.policy_name ?? "Policy unavailable"}</p>
                {#if selectedAsset.retention_policy}
                  <p class="text-xs text-muted-foreground">
                    {selectedAsset.retention_policy}
                    {selectedAsset.retention_remaining ? ` (${selectedAsset.retention_remaining})` : ""}
                  </p>
                {/if}
              </div>

              <div>
                <p class="text-xs uppercase tracking-[0.18em] text-muted-foreground">Recommendation</p>
                <p class="mt-1 font-semibold text-foreground">{selectedAsset.next_action.replaceAll("_", " ")}</p>
                <p class="text-xs text-muted-foreground">{selectedAsset.recommendation}</p>
              </div>

              <div class="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40"
                  onclick={() => bulkAction("preview")}
                  disabled={workflowBusy}
                >
                  Preview
                </button>
                <button
                  type="button"
                  class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40"
                  onclick={() => bulkAction("execute")}
                  disabled={workflowBusy}
                >
                  Execute
                </button>
              </div>
            </div>
          {:else}
            <h2 class="text-lg font-semibold text-foreground">Inspector</h2>
            <p class="mt-2 text-sm text-muted-foreground">
              Select an asset card to inspect identity, relationships, policy, and action details.
            </p>
          {/if}
        </aside>
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
