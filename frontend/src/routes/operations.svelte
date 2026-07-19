<script lang="ts">
  import { onMount } from "svelte";
  import { get_api, post_api } from "$lib/api";
  import {
    CollectionCard,
    DisplayOptionsDialog,
    MediaDetailsDrawer,
    MovieCard,
    SeriesCard,
    loadModuleDisplayState,
    type DetailsDrawerSection,
    type MediaObject,
    type MovieCollectionObject,
    type MovieObject,
    type SeasonObject,
    type SeriesObject,
  } from "$lib/design-system";
  import type {
    MieOperationsResponse,
    OperationAuditListResponse,
    OperationWorkflowResponse,
    OperationsRecommendation,
  } from "$lib/types/shared";
  import { formatFileSize } from "$lib/utils/formatters";

  let loading = $state(true);
  let error = $state("");
  let workspace = $state<MieOperationsResponse | null>(null);
  let selectedCollectionKey = $state<string | null>(null);
  let selectedAsset = $state<MediaObject | null>(null);
  let drawerOpen = $state(false);
  let displayOptionsOpen = $state(false);
  let posterSize = $state(176);
  let showHealthyCollections = $state(false);
  let workflowBusyId = $state<string | null>(null);
  let workflowError = $state("");
  let workflowPreview = $state<OperationWorkflowResponse | null>(null);
  let auditTrail = $state<OperationAuditListResponse | null>(null);
  let selectedRecommendationId = $state<string | null>(null);

  const load = async () => {
    loading = true;
    error = "";
    try {
      workspace = await get_api<MieOperationsResponse>("/api/mie/operations");
      auditTrail = await get_api<OperationAuditListResponse>(
        "/api/operations/audit",
      );
    } catch (e: any) {
      error = e?.message ?? "Failed to load Operations data";
    } finally {
      loading = false;
    }
  };

  const applyHashSelection = () => {
    const hash = window.location.hash || "";
    const queryIndex = hash.indexOf("?");
    if (queryIndex < 0) return;
    const params = new URLSearchParams(hash.slice(queryIndex + 1));
    const collection = params.get("collection");
    const recommendation = params.get("recommendation");
    if (collection) {
      selectedCollectionKey = collection;
      showHealthyCollections = true;
    }
    if (recommendation) {
      selectedRecommendationId = recommendation;
    }
  };

  const runWorkflow = async (
    recommendationId: string,
    action: "preview" | "validate" | "execute",
  ) => {
    selectedRecommendationId = recommendationId;
    workflowBusyId = recommendationId;
    workflowError = "";
    try {
      const url =
        action === "execute"
          ? `/api/operations/recommendations/${recommendationId}/execute`
          : `/api/operations/recommendations/${recommendationId}/${action}`;
      workflowPreview =
        action === "execute"
          ? await post_api<OperationWorkflowResponse>(url, {})
          : await get_api<OperationWorkflowResponse>(url);
      if (action === "execute") {
        auditTrail = await get_api<OperationAuditListResponse>(
          "/api/operations/audit",
        );
      }
    } catch (e: any) {
      workflowError = e?.message ?? `Failed to ${action} operation`;
    } finally {
      workflowBusyId = null;
    }
  };

  const safetyToSeverity = (
    safety: OperationsRecommendation["safety_level"],
  ) => {
    if (safety === "safe") return "healthy" as const;
    if (safety === "low_risk") return "information" as const;
    if (safety === "medium_risk") return "action" as const;
    return "problem" as const;
  };

  const recommendationConfidence = (item: OperationsRecommendation): number => {
    if (typeof item.confidence === "number") {
      return Math.max(0.5, Math.min(0.99, item.confidence / 100));
    }
    if (item.safety_level === "safe") return 0.99;
    if (item.safety_level === "low_risk") return 0.94;
    if (item.safety_level === "medium_risk") return 0.86;
    return 0.78;
  };

  const toLifecycle = (item: OperationsRecommendation) => {
    const action = item.action.toLowerCase();
    if (action.includes("detach")) return "detached" as const;
    if (action.includes("protect")) return "protected" as const;
    if (action.includes("delete") || action.includes("remove"))
      return "candidate" as const;
    return "imported" as const;
  };

  const recommendationsForCollection = $derived.by(() => {
    const rows = workspace?.recommendations.items ?? [];
    if (!selectedCollectionKey) return rows;
    return rows.filter((item) => item.card_key === selectedCollectionKey);
  });

  const collectionCards = $derived.by((): MovieCollectionObject[] => {
    const rows = workspace?.recommendations.items ?? [];
    return (workspace?.overview.cards ?? []).map((card) => ({
      id: card.key,
      kind: "movie_collection" as const,
      title: card.title,
      subtitle: `${card.count} media assets`,
      lifecycleState:
        card.severity === "high"
          ? ("candidate" as const)
          : ("verified" as const),
      recommendationSeverity:
        card.severity === "high"
          ? "problem"
          : card.severity === "medium"
            ? "action"
            : card.severity === "low"
              ? "information"
              : "healthy",
      recommendation: {
        message: card.description,
        confidence: card.severity === "high" ? 0.72 : 0.92,
        risk:
          card.severity === "high"
            ? "high"
            : card.severity === "medium"
              ? "medium"
              : "low",
      },
      healthSignals: [
        {
          kind: card.severity === "high" ? "warning" : "filesystem_verified",
          label: card.severity === "high" ? "Action Needed" : "Healthy",
          explanation: card.description,
        },
      ],
      posterUrl: null,
      quickActions: [{ id: "open", label: "Open Collection" }],
    }));
  });

  const visibleCollectionCards = $derived.by(() => {
    if (showHealthyCollections) return collectionCards;
    return collectionCards.filter((card) => {
      const source = workspace?.overview.cards.find(
        (row) => row.key === card.id,
      );
      return (source?.count ?? 0) > 0;
    });
  });

  const openComparison = (recommendationId: string) => {
    selectedRecommendationId = recommendationId;
    const target =
      mediaMovies.find((item) => item.id === recommendationId) ?? null;
    if (target) {
      selectedAsset = target;
      drawerOpen = true;
    }
  };

  const mediaMovies = $derived.by((): MovieObject[] => {
    return recommendationsForCollection
      .filter(
        (item) =>
          !/series|season|episode/i.test(item.target_type) &&
          !/season\s+\d+/i.test(item.title),
      )
      .map((item) => ({
        id: item.id,
        kind: "movie",
        title: item.title,
        subtitle: item.card_key.replaceAll("_", " "),
        lifecycleState: toLifecycle(item),
        recommendationSeverity: safetyToSeverity(item.safety_level),
        recommendation: {
          message: item.explanation ?? `${item.summary} Why: ${item.action}.`,
          confidence: recommendationConfidence(item),
          risk:
            item.safety_level === "high_risk"
              ? "high"
              : item.safety_level === "medium_risk"
                ? "medium"
                : "low",
          recoverableBytes: item.estimated_recovery_bytes,
          explanation:
            item.explanation ??
            `Recommendation is based on media lifecycle, protection status, and recoverable space (${formatFileSize(item.estimated_recovery_bytes)}).`,
        },
        healthSignals: [
          {
            kind: "imported",
            label: "Imported",
            explanation: "Media is present in the library and correlated.",
          },
          {
            kind: item.safety_level === "high_risk" ? "warning" : "protected",
            label: item.safety_level === "high_risk" ? "Risk" : "Protected",
            explanation: `Risk ${item.safety_level.replaceAll("_", " ")}.`,
          },
          {
            kind: "filesystem_verified",
            label: "Operation Candidate",
            explanation:
              "Action produced from operational correlation and cleanup intelligence.",
          },
        ],
        quickActions: [
          { id: "details", label: "Details" },
          { id: "comparison", label: "Open Comparison" },
        ],
        posterUrl: item.poster_url,
      }));
  });

  const mediaSeries = $derived.by((): SeriesObject[] => {
    const grouped = new Map<string, OperationsRecommendation[]>();
    for (const item of recommendationsForCollection) {
      const seasonal =
        /season\s*(\d+)/i.exec(item.title) || /s(\d{1,2})/i.exec(item.title);
      if (!seasonal && !/series|season|episode/i.test(item.target_type))
        continue;
      const key = item.title.split(" - ")[0].split(":")[0].trim();
      const bucket = grouped.get(key) ?? [];
      bucket.push(item);
      grouped.set(key, bucket);
    }

    return Array.from(grouped.entries()).map(([seriesName, items]) => {
      const posterUrl =
        items.find((item) => item.poster_url)?.poster_url ?? null;
      const seasons: SeasonObject[] = items.map((item, index) => {
        const seasonNo =
          /season\s*(\d+)/i.exec(item.title) || /s(\d{1,2})/i.exec(item.title);
        const seasonLabel = seasonNo
          ? `Season ${seasonNo[1]}`
          : `Season ${index + 1}`;
        return {
          id: `${item.id}-season`,
          kind: "season",
          title: seasonLabel,
          subtitle: item.summary,
          lifecycleState: toLifecycle(item),
          recommendationSeverity: safetyToSeverity(item.safety_level),
          recommendation: {
            message: `${item.summary} Why: ${item.action}.`,
            confidence: 0.98,
            risk:
              item.safety_level === "high_risk"
                ? "high"
                : item.safety_level === "medium_risk"
                  ? "medium"
                  : "low",
            recoverableBytes: item.estimated_recovery_bytes,
            explanation: `Recommendation derived from imported/protected/seed-state signals for ${seasonLabel}.`,
          },
          healthSignals: [
            {
              kind: "filesystem_verified",
              label: "Filesystem Verified",
              explanation: "Season files are present and indexed.",
            },
            {
              kind: "torrent_active",
              label: "Torrent Active",
              explanation:
                "Related transfer activity still exists for this season.",
            },
          ],
          quickActions: [
            { id: "details", label: "Details" },
            { id: "approve", label: "Approve" },
          ],
          episodes: [
            {
              id: `${item.id}-episode`,
              kind: "episode",
              title: "Episode Details",
              subtitle: "Visible only in details drawer",
              lifecycleState: toLifecycle(item),
              recommendationSeverity: safetyToSeverity(item.safety_level),
              recommendation: { message: item.summary },
            },
          ],
        };
      });

      const totalRecovery = items.reduce(
        (sum, row) => sum + row.estimated_recovery_bytes,
        0,
      );
      const highest = items.some((row) => row.safety_level === "high_risk")
        ? "high"
        : items.some((row) => row.safety_level === "medium_risk")
          ? "medium"
          : "low";

      return {
        id: `series-${seriesName.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}`,
        kind: "series",
        title: seriesName,
        subtitle: `${seasons.length} seasons with recommendations`,
        posterUrl,
        lifecycleState: "imported",
        recommendationSeverity:
          highest === "high"
            ? "problem"
            : highest === "medium"
              ? "action"
              : "information",
        recommendation: {
          message:
            "Series context keeps seasons visible while actions are taken season-by-season.",
          confidence: 0.98,
          risk: highest,
          recoverableBytes: totalRecovery,
          explanation:
            "Series cards provide context, while season cards are the operational unit.",
        },
        seasons,
        affectedSeasons: seasons.length,
        recommendations: items.length,
        recoverableBytes: totalRecovery,
        highestRisk: highest,
        overallHealth: highest === "high" ? "Attention" : "Good",
        lastScanAt: workspace?.overview.generated_at,
        healthSignals: [
          {
            kind: "imported",
            label: "Imported",
            explanation: "Series is imported and linked.",
          },
        ],
      };
    });
  });

  const drawerSections = $derived.by((): DetailsDrawerSection[] => {
    if (!selectedAsset) return [];
    const recommendation = selectedAsset.recommendation;
    return [
      {
        id: "lifecycle_timeline",
        title: "Lifecycle Timeline",
        description:
          "Context before detail: timeline explains why this action appears now.",
        rows: [
          { key: "Requested", value: "Complete" },
          { key: "Downloading", value: "Complete" },
          { key: "Imported", value: "Complete" },
          { key: "Protected", value: "Evaluated" },
          {
            key: "Seed Goal Reached",
            value: recommendation?.risk === "low" ? "Yes" : "Pending",
          },
        ],
      },
      {
        id: "recommendation",
        title: "Recommendation",
        rows: [
          {
            key: "Why",
            value:
              recommendation?.explanation ??
              recommendation?.message ??
              "No explanation available",
          },
          { key: "Risk", value: recommendation?.risk ?? "unknown" },
          {
            key: "Confidence",
            value: recommendation?.confidence
              ? `${Math.round(recommendation.confidence * 100)}%`
              : "n/a",
          },
          {
            key: "Estimated Recovery",
            value: formatFileSize(recommendation?.recoverableBytes ?? 0),
          },
        ],
      },
      {
        id: "filesystem",
        title: "Filesystem",
        rows: [
          {
            key: "Access Mode",
            value: workspace?.filesystem.access_mode ?? "unknown",
          },
          {
            key: "Configured Roots",
            value: String(workspace?.filesystem.roots.length ?? 0),
          },
        ],
      },
      {
        id: "torrent",
        title: "Torrent",
        rows: [
          {
            key: "Correlation",
            value: "Media-first view mapped to transfer state",
          },
          { key: "Tracker", value: "See provider information" },
        ],
      },
      {
        id: "protection",
        title: "Protection",
        rows: [{ key: "Policy", value: "Managed by recommendation engine" }],
      },
      {
        id: "history",
        title: "History",
        rows: [
          {
            key: "Last Evaluation",
            value: workspace?.overview.generated_at ?? "n/a",
          },
          {
            key: "Cleanup Plans",
            value: String(workspace?.cleanup_plans.plans.length ?? 0),
          },
        ],
      },
      {
        id: "provider_information",
        title: "Provider Information",
        rows: [{ key: "Source", value: "Operations recommendations API" }],
      },
      {
        id: "actions",
        title: "Actions",
        rows: [
          { key: "Primary", value: "Preview, validate, then execute" },
          {
            key: "Secondary",
            value: "Review audit trail for completed operations",
          },
        ],
      },
    ];
  });

  const refreshDisplay = () => {
    const profile = loadModuleDisplayState("operations");
    const preset = profile.presets.find((p) => p.id === profile.activePresetId);
    posterSize = preset?.config.posterSize ?? 176;
  };

  onMount(async () => {
    refreshDisplay();
    await load();
    applyHashSelection();
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
            Media Intelligence Workspace
          </p>
          <h1 class="text-4xl font-black tracking-tight text-foreground">
            Operations
          </h1>
          <p class="mt-2 text-sm text-muted-foreground">
            Visual collections answer what to do next using media context before
            provider detail.
          </p>
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
        Loading operations workspace...
      </div>
    {:else if error}
      <div
        class="rounded-xl border border-destructive/40 bg-destructive/10 p-6 text-destructive"
      >
        {error}
      </div>
    {:else}
      <section class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
          <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Overall Health
          </p>
          <p class="mt-2 text-3xl font-black text-foreground">
            {workspace?.health.overall_health ?? 0}
          </p>
          <p class="mt-1 text-xs text-muted-foreground">Score out of 100</p>
        </div>
        <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
          <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Issue Summary
          </p>
          <p class="mt-2 text-sm text-foreground">
            Critical {workspace?.issue_summary.critical ?? 0} • High
            {workspace?.issue_summary.high ?? 0} • Medium
            {workspace?.issue_summary.medium ?? 0} • Low
            {workspace?.issue_summary.low ?? 0}
          </p>
          <p class="mt-1 text-xs text-muted-foreground">
            Total {workspace?.issue_summary.total ?? 0}
          </p>
        </div>
        <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
          <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Graph Coverage
          </p>
          <p class="mt-2 text-sm text-foreground">
            {workspace?.graph_summary.total_media ?? 0} assets •
            {workspace?.graph_summary.with_torrents ?? 0} with torrents
          </p>
          <p class="mt-1 text-xs text-muted-foreground">
            Missing files {workspace?.graph_summary.with_missing_files ?? 0}
          </p>
        </div>
        <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
          <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            Explainability
          </p>
          <p class="mt-2 text-sm text-foreground">
            Confidence {workspace?.confidence.score ?? 0}%
          </p>
          <p class="mt-1 line-clamp-2 text-xs text-muted-foreground">
            {(workspace?.confidence.factors ?? []).slice(0, 3).join(" • ")}
          </p>
        </div>
      </section>

      <section class="space-y-3">
        <h2 class="text-lg font-semibold text-foreground">Downloads Health</h2>
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
            <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Active Downloads
            </p>
            <p class="mt-2 text-xl font-bold text-foreground">
              {workspace?.downloads_health.active_downloads ?? 0}
            </p>
          </div>
          <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
            <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Waiting For Import
            </p>
            <p class="mt-2 text-xl font-bold text-foreground">
              {workspace?.downloads_health.completed_waiting_for_import ?? 0}
            </p>
          </div>
          <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
            <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Waiting For Cleanup
            </p>
            <p class="mt-2 text-xl font-bold text-foreground">
              {workspace?.downloads_health.completed_waiting_for_cleanup ?? 0}
            </p>
          </div>
          <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
            <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Failed / Unknown
            </p>
            <p class="mt-2 text-xl font-bold text-foreground">
              {(workspace?.downloads_health.failed_downloads ?? 0) +
                (workspace?.downloads_health.unknown_downloads ?? 0)}
            </p>
          </div>
          <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
            <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Safe To Delete
            </p>
            <p class="mt-2 text-xl font-bold text-foreground">
              {workspace?.downloads_health.safe_to_delete ?? 0}
            </p>
            <p class="mt-1 text-xs text-muted-foreground">
              Recoverable
              {formatFileSize(
                workspace?.downloads_health.recoverable_space ?? 0,
              )}
            </p>
          </div>
        </div>
        <div class="grid gap-3 md:grid-cols-2">
          <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
            <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Imported But Still Present
            </p>
            <p class="mt-2 text-sm text-foreground">
              {workspace?.downloads_health.imported_but_still_present ?? 0}
            </p>
          </div>
          <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
            <p class="text-xs uppercase tracking-[0.2em] text-muted-foreground">
              Total Download Space
            </p>
            <p class="mt-2 text-sm text-foreground">
              {formatFileSize(workspace?.downloads_health.total_download_space ?? 0)}
            </p>
          </div>
        </div>
        <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
          <p class="mb-2 text-sm font-semibold text-foreground">
            Needs Attention (Top 8)
          </p>
          {#if (workspace?.downloads.length ?? 0) > 0}
            <div class="space-y-2 text-xs">
              {#each (workspace?.downloads ?? [])
                .filter((row) => row.cleanup_classification !== "none")
                .slice(0, 8) as row}
                <div class="rounded-lg border border-border/50 bg-background/70 p-2">
                  <p class="font-medium text-foreground">{row.path}</p>
                  <p class="text-muted-foreground">
                    State {row.lifecycle_state} • {row.cleanup_classification}
                    • Confidence {row.confidence_score}%
                  </p>
                  {#if row.cleanup_reason}
                    <p class="text-muted-foreground">{row.cleanup_reason}</p>
                  {/if}
                </div>
              {/each}
            </div>
          {:else}
            <p class="text-sm text-muted-foreground">
              No indexed downloads were detected in configured downloads roots.
            </p>
          {/if}
        </div>
      </section>

      <section class="space-y-3">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h2 class="text-lg font-semibold text-foreground">
            Operations Collections
          </h2>
          <button
            type="button"
            class={`rounded-full border px-3 py-1.5 text-xs ${showHealthyCollections ? "border-primary text-primary" : "border-border text-muted-foreground"}`}
            onclick={() => (showHealthyCollections = !showHealthyCollections)}
          >
            {showHealthyCollections
              ? "Hide Healthy Collections"
              : "Show Healthy Collections"}
          </button>
        </div>
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {#each visibleCollectionCards as item}
            <CollectionCard
              {item}
              selected={selectedCollectionKey === item.id}
              onSelect={() =>
                (selectedCollectionKey =
                  selectedCollectionKey === item.id ? null : item.id)}
              {posterSize}
            />
          {/each}
        </div>
      </section>

      <section class="space-y-3">
        <h2 class="text-lg font-semibold text-foreground">Affected Assets</h2>
        {#if mediaSeries.length === 0 && mediaMovies.length === 0}
          <p class="text-sm text-muted-foreground">
            Select a collection to populate affected assets.
          </p>
        {/if}

        {#if mediaSeries.length > 0}
          <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {#each mediaSeries as series}
              <SeriesCard
                item={series}
                {posterSize}
                onSelect={() => {
                  selectedAsset = series;
                  drawerOpen = true;
                }}
              />
            {/each}
          </div>
        {/if}

        {#if mediaMovies.length > 0}
          <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {#each mediaMovies as item}
              <MovieCard
                {item}
                {posterSize}
                onSelect={() => {
                  selectedRecommendationId = item.id;
                  selectedAsset = item;
                  drawerOpen = true;
                }}
              />
            {/each}
          </div>
        {/if}
      </section>

      <section
        class="space-y-3 sticky bottom-0 z-10 bg-background/95 py-2 backdrop-blur border-t border-border/50"
      >
        <h2 class="text-lg font-semibold text-foreground">
          Operation Workflow
        </h2>
        <div class="rounded-2xl border border-border/70 bg-card/60 p-4 text-sm">
          <div class="mb-3 flex flex-wrap gap-2">
            <button
              type="button"
              class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40"
              onclick={() =>
                selectedRecommendationId &&
                runWorkflow(selectedRecommendationId, "preview")}
              disabled={!selectedRecommendationId ||
                workflowBusyId === selectedRecommendationId}>Preview</button
            >
            <button
              type="button"
              class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40"
              onclick={() =>
                selectedRecommendationId &&
                runWorkflow(selectedRecommendationId, "validate")}
              disabled={!selectedRecommendationId ||
                workflowBusyId === selectedRecommendationId}>Validate</button
            >
            <button
              type="button"
              class="rounded-full border border-primary bg-primary/10 px-3 py-1.5 text-xs text-primary hover:bg-primary/20"
              onclick={() =>
                selectedRecommendationId &&
                runWorkflow(selectedRecommendationId, "execute")}
              disabled={!selectedRecommendationId ||
                workflowBusyId === selectedRecommendationId}>Execute</button
            >
          </div>
          {#if workflowError}
            <p class="text-destructive">{workflowError}</p>
          {/if}
          {#if workflowPreview}
            <p class="font-medium text-foreground">
              Recommendation {workflowPreview.recommendation_id}
            </p>
            <p class="text-muted-foreground">
              Preview: {workflowPreview.preview.target_count} target •
              {formatFileSize(workflowPreview.preview.estimated_recovery_bytes)}
            </p>
            <p class="mt-2 text-muted-foreground">
              Validation: {workflowPreview.validation.valid
                ? "Passed"
                : "Failed"}
            </p>
            <ul class="mt-2 space-y-1 text-xs text-muted-foreground">
              {#each workflowPreview.validation.checks as check}
                <li>
                  {check.passed ? "✓" : "✗"}
                  {check.label}: {check.detail}
                </li>
              {/each}
            </ul>
            <p class="mt-2 text-muted-foreground">
              Execution: {workflowPreview.execution.result} • {workflowPreview
                .execution.message}
            </p>
          {:else}
            <p class="text-muted-foreground">
              Select a recommendation and run Preview → Validate → Execute.
            </p>
          {/if}
        </div>
      </section>

      <section class="space-y-3">
        <h2 class="text-lg font-semibold text-foreground">Audit Log</h2>
        <div class="rounded-2xl border border-border/70 bg-card/60 p-4">
          {#if auditTrail && auditTrail.items.length > 0}
            <div class="space-y-2 text-xs">
              {#each auditTrail.items.slice(0, 10) as row}
                <div
                  class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/50 bg-background/70 px-3 py-2"
                >
                  <span class="text-foreground"
                    >{row.action} • {row.target_type}#{row.target_id ??
                      "n/a"}</span
                  >
                  <span class="text-muted-foreground"
                    >{row.result} • {formatFileSize(row.recovery_bytes)}</span
                  >
                </div>
              {/each}
            </div>
          {:else}
            <p class="text-sm text-muted-foreground">
              No operation history yet.
            </p>
          {/if}
        </div>
      </section>
    {/if}
  </div>
</div>

<DisplayOptionsDialog
  moduleId="operations"
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
