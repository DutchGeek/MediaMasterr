<script lang="ts">
  import { onMount } from "svelte";
  import { get_api } from "$lib/api";
  import {
    CollectionCard,
    DisplayOptionsDialog,
    MediaDetailsDrawer,
    MovieCard,
    SeriesLayout,
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

  const load = async () => {
    loading = true;
    error = "";
    try {
      workspace = await get_api<MieOperationsResponse>("/api/mie/operations");
    } catch (e: any) {
      error = e?.message ?? "Failed to load Operations data";
    } finally {
      loading = false;
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
      posterUrl:
        rows.find((item) => item.card_key === card.key)?.poster_url ?? null,
      quickActions: [{ id: "open", label: "Open Collection" }],
    }));
  });

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
          message: `${item.summary} Why: ${item.action}.`,
          confidence: 0.98,
          risk:
            item.safety_level === "high_risk"
              ? "high"
              : item.safety_level === "medium_risk"
                ? "medium"
                : "low",
          recoverableBytes: item.estimated_recovery_bytes,
          explanation: `Recommendation is based on media lifecycle, protection status, and recoverable space (${formatFileSize(item.estimated_recovery_bytes)}).`,
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
        ],
        quickActions: [
          { id: "explain", label: "Explain" },
          { id: "review", label: "Review" },
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
          { key: "Primary", value: "Review and apply recommendation" },
          { key: "Secondary", value: "Open technical diagnostics" },
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
      <section class="space-y-3">
        <h2 class="text-lg font-semibold text-foreground">
          Operations Collections
        </h2>
        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {#each collectionCards as item}
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

      {#if mediaSeries.length > 0}
        <section class="space-y-4">
          <h2 class="text-lg font-semibold text-foreground">Series Context</h2>
          {#each mediaSeries as series}
            <SeriesLayout
              {series}
              onSelectSeason={(season) => {
                selectedAsset = season;
                drawerOpen = true;
              }}
            />
          {/each}
        </section>
      {/if}

      {#if mediaMovies.length > 0}
        <section class="space-y-3">
          <h2 class="text-lg font-semibold text-foreground">Movie Actions</h2>
          <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {#each mediaMovies as item}
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
