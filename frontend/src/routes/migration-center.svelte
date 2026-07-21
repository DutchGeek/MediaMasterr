<script lang="ts">
  import { onMount } from "svelte";
  import { get_api, post_api } from "$lib/api";
  import type {
    MigrationDiscoveryResponse,
    MigrationPlanResponse,
    MigrationRootMapping,
    MigrationWorkspaceResponse,
  } from "$lib/types/shared";
  import { formatFileSize } from "$lib/utils/formatters";

  let loading = $state(true);
  let busy = $state(false);
  let error = $state("");
  let workspace = $state<MigrationWorkspaceResponse | null>(null);
  let discovery = $state<MigrationDiscoveryResponse | null>(null);
  let plan = $state<MigrationPlanResponse | null>(null);
  let sourceConfigId = $state<number | null>(null);
  let destinationConfigId = $state<number | null>(null);
  let rootMappings = $state<MigrationRootMapping[]>([]);
  let recentPlans = $state<
    Array<{
      generated_at: string;
      source: string;
      destination: string;
      item_count: number;
      conflicts: number;
    }>
  >([]);

  const sourceOptions = $derived(workspace?.available_sources ?? []);
  const destinationOptions = $derived(workspace?.available_destinations ?? []);

  const canDiscover = $derived(
    sourceConfigId !== null &&
      destinationConfigId !== null &&
      sourceConfigId !== destinationConfigId,
  );

  const summaryCards = $derived(
    plan
      ? [
          ["Series", String(plan.summary.series_count)],
          ["Movies", String(plan.summary.movie_count)],
          ["Episodes", String(plan.summary.episode_count)],
          ["Files Requiring Copy", String(plan.summary.files_requiring_copy)],
          ["Existing Files", String(plan.summary.existing_files)],
          ["Skipped Files", String(plan.summary.skipped_files)],
          ["Conflicts", String(plan.summary.conflict_count)],
          ["Manual Decisions", String(plan.summary.manual_decision_count)],
        ]
      : [],
  );

  function suggestedMappings(fromDiscovery: MigrationDiscoveryResponse | null) {
    if (!fromDiscovery) return [];
    const destinationRoots = fromDiscovery.destination.roots.map(
      (row) => row.path,
    );
    return fromDiscovery.source.roots.map((root, index) => {
      const exact = destinationRoots.find(
        (candidate) => candidate === root.path,
      );
      return {
        source_root: root.path,
        destination_root:
          exact ?? destinationRoots[index] ?? destinationRoots[0] ?? root.path,
      };
    });
  }

  function ensureSelectedDefaults() {
    if (sourceConfigId === null && sourceOptions.length > 0) {
      sourceConfigId = sourceOptions[0].config_id;
    }
    if (destinationConfigId === null && destinationOptions.length > 0) {
      destinationConfigId =
        destinationOptions.find((row) => row.config_id !== sourceConfigId)
          ?.config_id ?? destinationOptions[0].config_id;
    }
  }

  async function loadWorkspace() {
    loading = true;
    error = "";
    try {
      workspace = await get_api<MigrationWorkspaceResponse>(
        "/api/migration-center/workspace",
      );
      ensureSelectedDefaults();
    } catch (e: any) {
      error = e?.message ?? "Failed to load Migration Center.";
    } finally {
      loading = false;
    }
  }

  async function runDiscovery() {
    if (!canDiscover || sourceConfigId === null || destinationConfigId === null)
      return;
    busy = true;
    error = "";
    plan = null;
    try {
      discovery = await post_api<MigrationDiscoveryResponse>(
        "/api/migration-center/discovery",
        {
          source_config_id: sourceConfigId,
          destination_config_id: destinationConfigId,
        },
      );
      rootMappings = suggestedMappings(discovery);
    } catch (e: any) {
      error = e?.message ?? "Migration discovery failed.";
    } finally {
      busy = false;
    }
  }

  async function buildPlan() {
    if (!canDiscover || sourceConfigId === null || destinationConfigId === null)
      return;
    busy = true;
    error = "";
    try {
      plan = await post_api<MigrationPlanResponse>(
        "/api/migration-center/plan",
        {
          source_config_id: sourceConfigId,
          destination_config_id: destinationConfigId,
          root_mappings: rootMappings,
        },
      );
      const sourceName =
        discovery?.source.instance.name ?? `Source ${sourceConfigId ?? "?"}`;
      const destinationName =
        discovery?.destination.instance.name ??
        `Destination ${destinationConfigId ?? "?"}`;
      recentPlans = [
        {
          generated_at: plan.generated_at,
          source: sourceName,
          destination: destinationName,
          item_count: plan.summary.item_count,
          conflicts: plan.summary.conflict_count,
        },
        ...recentPlans,
      ].slice(0, 6);
      if (typeof window !== "undefined") {
        window.localStorage.setItem(
          "migration_center_recent_plans",
          JSON.stringify(recentPlans),
        );
      }
    } catch (e: any) {
      error = e?.message ?? "Failed to build migration plan.";
    } finally {
      busy = false;
    }
  }

  function addRootMapping() {
    rootMappings = [...rootMappings, { source_root: "", destination_root: "" }];
  }

  function updateRootMapping(
    index: number,
    key: "source_root" | "destination_root",
    value: string,
  ) {
    rootMappings = rootMappings.map((row, rowIndex) =>
      rowIndex === index ? { ...row, [key]: value } : row,
    );
  }

  function removeRootMapping(index: number) {
    rootMappings = rootMappings.filter((_, rowIndex) => rowIndex !== index);
  }

  function formatDuration(minutes: number | null) {
    if (minutes === null || minutes === undefined) return "Unavailable";
    if (minutes <= 0) return "No copy required";
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    if (hours <= 0) return `${minutes} min`;
    return `${hours}h ${remainingMinutes}m`;
  }

  onMount(() => {
    if (typeof window !== "undefined") {
      try {
        const raw = window.localStorage.getItem(
          "migration_center_recent_plans",
        );
        if (raw) {
          recentPlans = JSON.parse(raw);
        }
      } catch {
        // ignore invalid persisted state
      }
    }
    void loadWorkspace();
  });
</script>

<div class="space-y-6 p-4 md:p-6">
  <header class="rounded-3xl border border-border/70 bg-card/70 p-5">
    <p class="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
      Migration Center
    </p>
    <h1 class="mt-2 text-2xl font-semibold text-foreground">
      Planning Workspace
    </h1>
    <p class="mt-2 text-sm text-muted-foreground">
      Inventory Sonarr and Radarr environments, map roots, and generate a
      read-only migration plan.
    </p>
  </header>

  <section class="rounded-3xl border border-border/70 bg-card/70 p-5">
    <p class="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
      Purpose
    </p>
    <h2 class="mt-2 text-2xl font-semibold text-foreground">
      Plan migrations safely before execution exists
    </h2>
    <p class="mt-2 text-sm text-muted-foreground">
      Migration Center is intentionally planning-only in this release. Use it to
      inspect source and destination inventories, build root mappings, identify
      conflicts, and prepare a validated migration plan.
    </p>
    <div class="mt-4 grid gap-3 md:grid-cols-3">
      <div
        class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
      >
        <p class="text-muted-foreground">Supported Systems</p>
        <p class="mt-1 font-medium text-foreground">Sonarr and Radarr</p>
      </div>
      <div
        class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
      >
        <p class="text-muted-foreground">Current Status</p>
        <p class="mt-1 font-medium text-foreground">
          Discovery and planning only
        </p>
      </div>
      <div
        class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
      >
        <p class="text-muted-foreground">Execution</p>
        <p class="mt-1 font-medium text-foreground">Not enabled in v0.9.5</p>
      </div>
    </div>
    <div class="mt-4 flex flex-wrap gap-2">
      <button
        type="button"
        class="rounded-full border border-primary bg-primary/10 px-4 py-2 text-sm text-primary hover:bg-primary/20 disabled:opacity-50"
        onclick={runDiscovery}
        disabled={!canDiscover || busy}
      >
        Discovery
      </button>
      <button
        type="button"
        class="rounded-full border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
        onclick={buildPlan}
        disabled={!discovery || busy}
      >
        Create Migration Plan
      </button>
    </div>
    <div class="mt-4 rounded-2xl border border-border/60 bg-background/50 p-3">
      <p class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
        Recent migration plans
      </p>
      {#if recentPlans.length === 0}
        <p class="mt-2 text-sm text-muted-foreground">
          No plans have been generated yet in this browser session.
        </p>
      {:else}
        <div class="mt-2 space-y-2 text-sm">
          {#each recentPlans as entry}
            <div class="rounded-xl border border-border/50 bg-card/50 p-2">
              <p class="font-medium text-foreground">
                {entry.source} → {entry.destination}
              </p>
              <p class="text-muted-foreground">
                {new Date(entry.generated_at).toLocaleString()} • Items {entry.item_count}
                • Conflicts {entry.conflicts}
              </p>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  </section>

  {#if loading}
    <div
      class="rounded-2xl border border-border/70 bg-card/60 p-6 text-sm text-muted-foreground"
    >
      Loading Migration Center...
    </div>
  {:else}
    {#if error}
      <div
        class="rounded-2xl border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
      >
        {error}
      </div>
    {/if}

    <section class="grid gap-4 lg:grid-cols-[1.1fr,0.9fr]">
      <div class="rounded-3xl border border-border/70 bg-card/70 p-5">
        <p
          class="text-[11px] uppercase tracking-[0.18em] text-muted-foreground"
        >
          Discovery
        </p>
        <h1 class="mt-2 text-2xl font-semibold text-foreground">
          Build a migration inventory before changing anything
        </h1>
        <p class="mt-2 max-w-3xl text-sm text-muted-foreground">
          Select a source and destination ARR instance. MediaMasterr will
          inspect roots, profiles, tags, metadata settings, and existing media
          paths so you can compare both environments and produce a planning-only
          migration report.
        </p>

        <div class="mt-5 grid gap-3 md:grid-cols-2">
          <label
            class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
          >
            <p
              class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
            >
              Source
            </p>
            <select
              class="mt-2 w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
              bind:value={sourceConfigId}
            >
              {#each sourceOptions as option}
                <option value={option.config_id}>
                  {option.name} ({option.service_type})
                </option>
              {/each}
            </select>
          </label>

          <label
            class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
          >
            <p
              class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
            >
              Destination
            </p>
            <select
              class="mt-2 w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
              bind:value={destinationConfigId}
            >
              {#each destinationOptions as option}
                <option value={option.config_id}>
                  {option.name} ({option.service_type})
                </option>
              {/each}
            </select>
          </label>
        </div>

        <div class="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            class="rounded-full border border-primary bg-primary/10 px-4 py-2 text-sm text-primary hover:bg-primary/20 disabled:opacity-50"
            onclick={runDiscovery}
            disabled={!canDiscover || busy}
          >
            {busy ? "Inspecting..." : "Run Discovery"}
          </button>
          <button
            type="button"
            class="rounded-full border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
            onclick={buildPlan}
            disabled={!discovery || busy}
          >
            {busy ? "Planning..." : "Build Read-Only Plan"}
          </button>
        </div>
      </div>

      <div class="rounded-3xl border border-border/70 bg-card/70 p-5">
        <p
          class="text-[11px] uppercase tracking-[0.18em] text-muted-foreground"
        >
          Execution
        </p>
        <h2 class="mt-2 text-xl font-semibold text-foreground">
          Planning only in v0.9.5
        </h2>
        <p class="mt-2 text-sm text-muted-foreground">
          {workspace?.execution_placeholder}
        </p>
        <div class="mt-4 grid gap-3 sm:grid-cols-2">
          <div
            class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
          >
            <p class="text-muted-foreground">Supported Sources</p>
            <p class="mt-1 font-medium text-foreground">
              {workspace?.supported_services.join(", ")}
            </p>
          </div>
          <div
            class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
          >
            <p class="text-muted-foreground">Supported Destinations</p>
            <p class="mt-1 font-medium text-foreground">
              {workspace?.supported_services.join(", ")}
            </p>
          </div>
        </div>
      </div>
    </section>

    {#if discovery}
      <section class="grid gap-4 xl:grid-cols-2">
        {#each [discovery.source, discovery.destination] as inventory}
          <div class="rounded-3xl border border-border/70 bg-card/70 p-5">
            <div class="flex items-start justify-between gap-3">
              <div>
                <p
                  class="text-[11px] uppercase tracking-[0.18em] text-muted-foreground"
                >
                  {inventory === discovery.source
                    ? "Source Inventory"
                    : "Destination Inventory"}
                </p>
                <h2 class="mt-2 text-xl font-semibold text-foreground">
                  {inventory.instance.name}
                </h2>
                <p class="text-sm text-muted-foreground">
                  {inventory.instance.base_url}
                </p>
              </div>
              <span
                class="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground"
              >
                {inventory.instance.service_type}
              </span>
            </div>

            <div class="mt-4 grid gap-2 sm:grid-cols-3">
              <div
                class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
              >
                <p class="text-muted-foreground">Roots</p>
                <p class="mt-1 font-medium text-foreground">
                  {inventory.summary.root_folder_count}
                </p>
              </div>
              <div
                class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
              >
                <p class="text-muted-foreground">Media</p>
                <p class="mt-1 font-medium text-foreground">
                  {inventory.summary.media_count}
                </p>
              </div>
              <div
                class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
              >
                <p class="text-muted-foreground">Size</p>
                <p class="mt-1 font-medium text-foreground">
                  {formatFileSize(inventory.summary.total_size_bytes)}
                </p>
              </div>
            </div>

            <div class="mt-4 grid gap-4 lg:grid-cols-2">
              <div>
                <p
                  class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                >
                  Root Folders
                </p>
                <div class="mt-2 space-y-2">
                  {#each inventory.roots as root}
                    <div
                      class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
                    >
                      <p class="break-all font-medium text-foreground">
                        {root.path}
                      </p>
                      <p class="mt-1 text-muted-foreground">
                        Free {root.free_space !== null
                          ? formatFileSize(root.free_space)
                          : "Unavailable"}
                      </p>
                    </div>
                  {/each}
                </div>
              </div>
              <div>
                <p
                  class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                >
                  Inventory
                </p>
                <div class="mt-2 space-y-2 text-sm text-muted-foreground">
                  <p>Libraries: {inventory.summary.library_count}</p>
                  <p>Tags: {inventory.summary.tag_count}</p>
                  <p>
                    Quality Profiles: {inventory.summary.quality_profile_count}
                  </p>
                  <p>
                    Language Profiles: {inventory.summary
                      .language_profile_count}
                  </p>
                  <p>Custom Formats: {inventory.summary.custom_format_count}</p>
                  <p>
                    Metadata Profiles: {inventory.summary
                      .metadata_profile_count}
                  </p>
                  <p>Collections: {inventory.summary.collection_count}</p>
                </div>
              </div>
            </div>

            {#if inventory.warnings.length > 0}
              <div
                class="mt-4 rounded-2xl border border-amber-400/30 bg-amber-500/10 p-3 text-sm text-amber-100"
              >
                {#each inventory.warnings as warning}
                  <p>{warning}</p>
                {/each}
              </div>
            {/if}
          </div>
        {/each}
      </section>

      <section class="rounded-3xl border border-border/70 bg-card/70 p-5">
        <div class="flex items-center justify-between gap-3">
          <div>
            <p
              class="text-[11px] uppercase tracking-[0.18em] text-muted-foreground"
            >
              Root Folder Mapping
            </p>
            <h2 class="mt-2 text-xl font-semibold text-foreground">
              Map source roots to destination roots
            </h2>
          </div>
          <button
            type="button"
            class="rounded-full border border-border px-3 py-1 text-sm text-muted-foreground hover:text-foreground"
            onclick={addRootMapping}
          >
            Add Mapping
          </button>
        </div>

        <div class="mt-4 space-y-3">
          {#each rootMappings as mapping, index}
            <div
              class="grid gap-3 rounded-2xl border border-border/60 bg-background/50 p-3 lg:grid-cols-[1fr,1fr,auto]"
            >
              <label class="text-sm">
                <p
                  class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                >
                  Source Root
                </p>
                <input
                  class="mt-2 w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
                  value={mapping.source_root}
                  oninput={(event) =>
                    updateRootMapping(
                      index,
                      "source_root",
                      event.currentTarget.value,
                    )}
                />
              </label>
              <label class="text-sm">
                <p
                  class="text-[11px] uppercase tracking-[0.14em] text-muted-foreground"
                >
                  Destination Root
                </p>
                <input
                  class="mt-2 w-full rounded-xl border border-border bg-background px-3 py-2 text-foreground"
                  value={mapping.destination_root}
                  oninput={(event) =>
                    updateRootMapping(
                      index,
                      "destination_root",
                      event.currentTarget.value,
                    )}
                />
              </label>
              <div class="flex items-end">
                <button
                  type="button"
                  class="rounded-full border border-border px-3 py-2 text-sm text-muted-foreground hover:text-foreground"
                  onclick={() => removeRootMapping(index)}
                >
                  Remove
                </button>
              </div>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    {#if plan}
      <section class="space-y-4">
        <div class="rounded-3xl border border-border/70 bg-card/70 p-5">
          <p
            class="text-[11px] uppercase tracking-[0.18em] text-muted-foreground"
          >
            Migration Plan
          </p>
          <h2 class="mt-2 text-xl font-semibold text-foreground">
            Read-only plan summary
          </h2>
          <p class="mt-2 text-sm text-muted-foreground">
            {plan.execution_placeholder}
          </p>

          <div class="mt-4 grid gap-3 md:grid-cols-4">
            {#each summaryCards as [label, value]}
              <div
                class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
              >
                <p class="text-muted-foreground">{label}</p>
                <p class="mt-1 font-medium text-foreground">{value}</p>
              </div>
            {/each}
          </div>

          <div class="mt-4 grid gap-3 md:grid-cols-3">
            <div
              class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
            >
              <p class="text-muted-foreground">Data Size</p>
              <p class="mt-1 font-medium text-foreground">
                {formatFileSize(plan.summary.total_size_bytes)}
              </p>
            </div>
            <div
              class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
            >
              <p class="text-muted-foreground">Estimated Duration</p>
              <p class="mt-1 font-medium text-foreground">
                {formatDuration(plan.summary.estimated_duration_minutes)}
              </p>
            </div>
            <div
              class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
            >
              <p class="text-muted-foreground">Metadata Plan</p>
              <p class="mt-1 font-medium text-foreground">
                {Object.entries(plan.metadata_plan)
                  .filter(([, enabled]) => enabled)
                  .map(([key]) => key.replaceAll("_", " "))
                  .join(", ")}
              </p>
            </div>
          </div>
        </div>

        <div class="grid gap-4 xl:grid-cols-[1.2fr,0.8fr]">
          <div class="rounded-3xl border border-border/70 bg-card/70 p-5">
            <p
              class="text-[11px] uppercase tracking-[0.18em] text-muted-foreground"
            >
              Planned Items
            </p>
            <div class="mt-3 space-y-3">
              {#each plan.items as item}
                <div
                  class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
                >
                  <div class="flex items-start justify-between gap-3">
                    <div>
                      <p class="font-medium text-foreground">
                        {item.title}{item.year ? ` (${item.year})` : ""}
                      </p>
                      <p class="text-muted-foreground">{item.kind}</p>
                    </div>
                    <span
                      class="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground"
                    >
                      {item.status.replaceAll("_", " ")}
                    </span>
                  </div>
                  <div class="mt-3 grid gap-2 lg:grid-cols-3">
                    <div>
                      <p
                        class="text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
                      >
                        Source
                      </p>
                      <p class="mt-1 break-all text-foreground">
                        {item.source_path ?? "Unavailable"}
                      </p>
                    </div>
                    <div>
                      <p
                        class="text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
                      >
                        Destination
                      </p>
                      <p class="mt-1 break-all text-foreground">
                        {item.destination_path ?? "Not present"}
                      </p>
                    </div>
                    <div>
                      <p
                        class="text-[11px] uppercase tracking-[0.12em] text-muted-foreground"
                      >
                        Mapped Destination
                      </p>
                      <p class="mt-1 break-all text-foreground">
                        {item.mapped_destination_path ?? "Unavailable"}
                      </p>
                    </div>
                  </div>
                  <div class="mt-3 flex flex-wrap gap-3 text-muted-foreground">
                    <span>Size {formatFileSize(item.size_bytes)}</span>
                    <span>Episodes {item.episode_count}</span>
                  </div>
                  {#if item.notes.length > 0}
                    <div class="mt-2 space-y-1 text-muted-foreground">
                      {#each item.notes as note}
                        <p>{note}</p>
                      {/each}
                    </div>
                  {/if}
                </div>
              {/each}
            </div>
          </div>

          <div class="space-y-4">
            <div class="rounded-3xl border border-border/70 bg-card/70 p-5">
              <p
                class="text-[11px] uppercase tracking-[0.18em] text-muted-foreground"
              >
                Conflicts
              </p>
              <div class="mt-3 space-y-3">
                {#if plan.conflicts.length > 0}
                  {#each plan.conflicts as conflict}
                    <div
                      class="rounded-2xl border border-border/60 bg-background/50 p-3 text-sm"
                    >
                      <p class="font-medium text-foreground">
                        {conflict.title}
                      </p>
                      <p class="mt-1 text-muted-foreground">
                        {conflict.description}
                      </p>
                      <p class="mt-2 text-muted-foreground">
                        Source: {conflict.source_value ?? "Unavailable"}
                      </p>
                      <p class="text-muted-foreground">
                        Destination: {conflict.destination_value ??
                          "Unavailable"}
                      </p>
                      <p class="mt-2 text-muted-foreground">
                        Options: {conflict.resolutions.join(", ")}
                      </p>
                    </div>
                  {/each}
                {:else}
                  <p class="text-sm text-muted-foreground">
                    No conflicts were detected in this planning pass.
                  </p>
                {/if}
              </div>
            </div>

            <div class="rounded-3xl border border-border/70 bg-card/70 p-5">
              <p
                class="text-[11px] uppercase tracking-[0.18em] text-muted-foreground"
              >
                Metadata Migration
              </p>
              <div class="mt-3 grid gap-2 text-sm text-muted-foreground">
                {#each Object.entries(plan.metadata_plan) as [key, enabled]}
                  <div
                    class="flex items-center justify-between rounded-2xl border border-border/60 bg-background/50 px-3 py-2"
                  >
                    <span>{key.replaceAll("_", " ")}</span>
                    <span
                      class={enabled
                        ? "text-emerald-200"
                        : "text-muted-foreground"}
                    >
                      {enabled ? "Planned" : "Not planned"}
                    </span>
                  </div>
                {/each}
              </div>
            </div>
          </div>
        </div>
      </section>
    {/if}
  {/if}
</div>
