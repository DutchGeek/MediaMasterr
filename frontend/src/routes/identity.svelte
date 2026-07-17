<script lang="ts">
  import { onMount } from "svelte";
  import { get_api, post_api } from "$lib/api";
  import {
    MediaType,
    type IdentityActionResponse,
    type IdentityStudioResponse,
    type IdentitySyncHistoryResponse,
    type IdentitySyncJobResponse,
    type IdentitySyncPreviewResponse,
    type IdentityWorkspaceItem,
    type IdentityWorkspaceResponse,
  } from "$lib/types/shared";

  type StudioTab =
    | "overview"
    | "providers"
    | "artwork"
    | "metadata"
    | "external_ids"
    | "overrides"
    | "history";

  let loading = $state(true);
  let error = $state("");
  let busy = $state(false);

  let search = $state("");
  let mediaFilter = $state<"all" | MediaType>("all");
  let sortBy = $state<"title" | "confidence" | "updated">("title");
  let sortOrder = $state<"asc" | "desc">("asc");
  let page = $state(1);
  let perPage = $state(24);
  let displayMode = $state<"grid" | "list">("grid");

  let workspace = $state<IdentityWorkspaceResponse | null>(null);
  let selectedKeys = $state<Set<string>>(new Set());
  let selectedItem = $state<IdentityWorkspaceItem | null>(null);

  let studioLoading = $state(false);
  let studioError = $state("");
  let studio = $state<IdentityStudioResponse | null>(null);
  let activeTab = $state<StudioTab>("overview");

  let syncPreview = $state<IdentitySyncPreviewResponse | null>(null);
  let syncHistory = $state<IdentitySyncHistoryResponse | null>(null);
  let syncMessage = $state("");

  let overrideField = $state("");
  let overrideValue = $state("");
  let overrideReason = $state("");

  const tabOrder: Array<{ key: StudioTab; label: string }> = [
    { key: "overview", label: "Overview" },
    { key: "providers", label: "Providers" },
    { key: "artwork", label: "Artwork" },
    { key: "metadata", label: "Metadata" },
    { key: "external_ids", label: "External IDs" },
    { key: "overrides", label: "Overrides" },
    { key: "history", label: "History" },
  ];

  const itemKey = (item: IdentityWorkspaceItem): string =>
    `${item.media_type}:${item.media_id}`;

  const mediaLabel = (type: MediaType): string =>
    type === MediaType.Movie ? "Movie" : "Series";

  const conflictClass = (level: string): string => {
    if (level === "high") return "text-destructive";
    if (level === "medium") return "text-amber-500";
    if (level === "low") return "text-yellow-500";
    return "text-emerald-500";
  };

  const totalPages = $derived(workspace?.total_pages ?? 1);
  const items = $derived(workspace?.items ?? []);

  async function loadWorkspace() {
    loading = true;
    error = "";
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("per_page", String(perPage));
      params.set("sort_by", sortBy);
      params.set("sort_order", sortOrder);
      if (search.trim()) params.set("search", search.trim());
      if (mediaFilter !== "all") params.set("media_type", mediaFilter);

      workspace = await get_api<IdentityWorkspaceResponse>(
        `/api/mie/identity?${params.toString()}`,
      );

      if (selectedItem) {
        const refreshed = workspace.items.find(
          (row) => itemKey(row) === itemKey(selectedItem!),
        );
        if (refreshed) {
          selectedItem = refreshed;
        }
      }
    } catch (e: any) {
      error = e?.message ?? "Failed to load Identity workspace";
    } finally {
      loading = false;
    }
  }

  async function loadStudio(item: IdentityWorkspaceItem) {
    selectedItem = item;
    studio = null;
    studioError = "";
    studioLoading = true;
    try {
      studio = await get_api<IdentityStudioResponse>(
        `/api/mie/identity/${item.media_type}/${item.media_id}/studio`,
      );
      activeTab = "overview";
    } catch (e: any) {
      studioError = e?.message ?? "Failed to load studio data";
    } finally {
      studioLoading = false;
    }
  }

  async function loadSyncHistory() {
    try {
      syncHistory = await get_api<IdentitySyncHistoryResponse>(
        "/api/mie/identity/sync-history?limit=25",
      );
    } catch {
      syncHistory = { items: [] };
    }
  }

  async function previewSync() {
    busy = true;
    syncMessage = "";
    try {
      syncPreview = await get_api<IdentitySyncPreviewResponse>(
        "/api/mie/identity/sync-preview",
      );
    } catch (e: any) {
      syncMessage = e?.message ?? "Failed to preview sync";
    } finally {
      busy = false;
    }
  }

  async function runSync() {
    busy = true;
    syncMessage = "";
    try {
      const response = await post_api<IdentitySyncJobResponse>(
        "/api/mie/identity/sync",
        {},
      );
      syncMessage = response.message;
      await loadSyncHistory();
    } catch (e: any) {
      syncMessage = e?.message ?? "Failed to queue sync";
    } finally {
      busy = false;
    }
  }

  async function setCanonical(provider: string) {
    if (!selectedItem) return;
    busy = true;
    syncMessage = "";
    try {
      const response = await post_api<IdentityActionResponse>(
        `/api/mie/identity/${selectedItem.media_type}/${selectedItem.media_id}/canonical`,
        { provider, reason: "Selected in Identity Studio" },
      );
      syncMessage = response.message;
      await loadStudio(selectedItem);
      await loadWorkspace();
    } catch (e: any) {
      syncMessage = e?.message ?? "Failed to set canonical provider";
    } finally {
      busy = false;
    }
  }

  async function saveOverride() {
    if (!selectedItem || !overrideField.trim() || !overrideValue.trim()) return;
    busy = true;
    syncMessage = "";
    try {
      const response = await post_api<IdentityActionResponse>(
        `/api/mie/identity/${selectedItem.media_type}/${selectedItem.media_id}/overrides`,
        {
          field: overrideField.trim(),
          value: overrideValue.trim(),
          reason: overrideReason.trim() || null,
          scope: "media",
        },
      );
      syncMessage = response.message;
      overrideField = "";
      overrideValue = "";
      overrideReason = "";
      await loadStudio(selectedItem);
    } catch (e: any) {
      syncMessage = e?.message ?? "Failed to save override";
    } finally {
      busy = false;
    }
  }

  function toggleSelection(item: IdentityWorkspaceItem) {
    const key = itemKey(item);
    const next = new Set(selectedKeys);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    selectedKeys = next;
  }

  function resetFilters() {
    search = "";
    mediaFilter = "all";
    sortBy = "title";
    sortOrder = "asc";
    page = 1;
    void loadWorkspace();
  }

  onMount(() => {
    void loadWorkspace();
    void loadSyncHistory();
  });
</script>

<div class="space-y-4 p-4 md:p-6">
  <div class="rounded-2xl border border-border bg-card p-4 md:p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Identity Center</h1>
        <p class="text-sm text-muted-foreground">
          Compare providers, set canonical sources, apply overrides, and queue
          sync jobs.
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <button
          class="rounded-md border border-border px-3 py-2 text-sm hover:bg-accent"
          onclick={previewSync}
          disabled={busy}
        >
          Preview Sync
        </button>
        <button
          class="rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground hover:opacity-90 disabled:opacity-50"
          onclick={runSync}
          disabled={busy}
        >
          Queue Sync
        </button>
      </div>
    </div>

    {#if syncPreview}
      <div class="mt-4 rounded-lg border border-border/70 bg-muted/30 p-3 text-sm">
        <div>
          Targets: {syncPreview.target_count} | Potential Changes:
          {syncPreview.changed_count}
        </div>
        {#if syncPreview.warnings.length > 0}
          <ul class="mt-2 list-disc pl-5 text-amber-500">
            {#each syncPreview.warnings as warning}
              <li>{warning}</li>
            {/each}
          </ul>
        {/if}
      </div>
    {/if}

    {#if syncMessage}
      <p class="mt-3 text-sm text-muted-foreground">{syncMessage}</p>
    {/if}
  </div>

  <div class="grid gap-4 xl:grid-cols-[1.1fr_1fr]">
    <section class="space-y-3 rounded-2xl border border-border bg-card p-4">
      <div class="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        <input
          class="rounded-md border border-border bg-background px-3 py-2 text-sm"
          placeholder="Search title"
          bind:value={search}
          onkeydown={(event) => {
            if (event.key === "Enter") {
              page = 1;
              void loadWorkspace();
            }
          }}
        />
        <select
          class="rounded-md border border-border bg-background px-3 py-2 text-sm"
          bind:value={mediaFilter}
          onchange={() => {
            page = 1;
            void loadWorkspace();
          }}
        >
          <option value="all">All Media</option>
          <option value={MediaType.Movie}>Movies</option>
          <option value={MediaType.Series}>Series</option>
        </select>
        <div class="flex gap-2">
          <select
            class="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            bind:value={sortBy}
            onchange={() => void loadWorkspace()}
          >
            <option value="title">Sort: Title</option>
            <option value="confidence">Sort: Confidence</option>
            <option value="updated">Sort: Updated</option>
          </select>
          <select
            class="rounded-md border border-border bg-background px-3 py-2 text-sm"
            bind:value={sortOrder}
            onchange={() => void loadWorkspace()}
          >
            <option value="asc">Asc</option>
            <option value="desc">Desc</option>
          </select>
        </div>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-2 text-sm">
        <div class="text-muted-foreground">
          {workspace?.total ?? 0} items | Selected: {selectedKeys.size}
        </div>
        <div class="flex items-center gap-2">
          <select
            class="rounded-md border border-border bg-background px-2 py-1"
            bind:value={displayMode}
          >
            <option value="grid">Grid</option>
            <option value="list">List</option>
          </select>
          <button
            class="rounded-md border border-border px-2 py-1 hover:bg-accent"
            onclick={resetFilters}
          >
            Reset
          </button>
          <button
            class="rounded-md border border-border px-2 py-1 hover:bg-accent"
            onclick={() => void loadWorkspace()}
          >
            Refresh
          </button>
        </div>
      </div>

      {#if loading}
        <div class="rounded-lg border border-border/70 bg-muted/20 p-6 text-sm text-muted-foreground">
          Loading identity rows...
        </div>
      {:else if error}
        <div class="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      {:else if items.length === 0}
        <div class="rounded-lg border border-border/70 bg-muted/20 p-6 text-sm text-muted-foreground">
          No identity rows found for current filters.
        </div>
      {:else}
        <div
          class={displayMode === "grid"
            ? "grid gap-3 md:grid-cols-2"
            : "flex flex-col gap-2"}
        >
          {#each items as item}
            <article
              class="rounded-xl border border-border/70 bg-background p-3 transition hover:border-primary/50"
            >
              <div class="flex items-start gap-3">
                <input
                  type="checkbox"
                  checked={selectedKeys.has(itemKey(item))}
                  onchange={() => toggleSelection(item)}
                />
                {#if item.poster_url}
                  <img
                    src={item.poster_url}
                    alt={item.title}
                    class="h-16 w-12 rounded object-cover"
                  />
                {/if}
                <button
                  class="min-w-0 flex-1 text-left"
                  onclick={() => void loadStudio(item)}
                >
                  <div class="truncate font-medium">{item.title}</div>
                  <div class="text-xs text-muted-foreground">
                    {mediaLabel(item.media_type)} {item.year ?? ""}
                  </div>
                  <div class="mt-2 flex flex-wrap gap-2 text-xs">
                    <span class="rounded bg-muted px-2 py-0.5">
                      Canonical: {item.canonical_provider}
                    </span>
                    <span class="rounded bg-muted px-2 py-0.5">
                      Providers: {item.provider_count}
                    </span>
                    <span class="rounded bg-muted px-2 py-0.5">
                      Confidence: {item.provider_confidence}%
                    </span>
                    <span class={`rounded px-2 py-0.5 ${conflictClass(item.conflict_level)}`}>
                      Conflict: {item.conflict_level}
                    </span>
                  </div>
                </button>
              </div>
            </article>
          {/each}
        </div>

        <div class="flex items-center justify-between pt-2 text-sm">
          <button
            class="rounded-md border border-border px-2 py-1 disabled:opacity-50"
            disabled={page <= 1}
            onclick={() => {
              page -= 1;
              void loadWorkspace();
            }}
          >
            Previous
          </button>
          <div>
            Page {workspace?.page ?? 1} / {totalPages}
          </div>
          <button
            class="rounded-md border border-border px-2 py-1 disabled:opacity-50"
            disabled={(workspace?.page ?? 1) >= totalPages}
            onclick={() => {
              page += 1;
              void loadWorkspace();
            }}
          >
            Next
          </button>
        </div>
      {/if}
    </section>

    <section class="space-y-3 rounded-2xl border border-border bg-card p-4">
      <div>
        <h2 class="text-lg font-semibold">Identity Studio</h2>
        <p class="text-sm text-muted-foreground">
          {#if selectedItem}
            {selectedItem.title} ({mediaLabel(selectedItem.media_type)})
          {:else}
            Select a row to open the comparison studio.
          {/if}
        </p>
      </div>

      {#if studioLoading}
        <div class="rounded-lg border border-border/70 bg-muted/20 p-6 text-sm text-muted-foreground">
          Loading studio...
        </div>
      {:else if studioError}
        <div class="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
          {studioError}
        </div>
      {:else if studio}
        <div class="flex flex-wrap gap-2">
          {#each tabOrder as tab}
            <button
              class={activeTab === tab.key
                ? "rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground"
                : "rounded-md border border-border px-3 py-1 text-xs hover:bg-accent"}
              onclick={() => (activeTab = tab.key)}
            >
              {tab.label}
            </button>
          {/each}
        </div>

        {#if activeTab === "overview"}
          <div class="space-y-2 text-sm">
            <div class="rounded-md border border-border/70 bg-muted/20 p-2">
              Canonical Provider: <strong>{studio.canonical_provider}</strong>
            </div>
            {#each studio.overview as row}
              <div class="rounded-md border border-border/70 p-2">
                <div class="text-xs text-muted-foreground">{row.label}</div>
                {#each row.values as value}
                  <div>
                    {value.provider}: {value.value ?? "-"}
                  </div>
                {/each}
              </div>
            {/each}
          </div>
        {/if}

        {#if activeTab === "providers"}
          <div class="space-y-2 text-sm">
            {#each studio.providers as provider}
              <div class="rounded-md border border-border/70 p-2">
                <div class="flex items-center justify-between gap-2">
                  <div>
                    <strong>{provider.provider}</strong>
                    {#if provider.is_canonical}
                      <span class="ml-2 rounded bg-primary/20 px-2 py-0.5 text-xs">canonical</span>
                    {/if}
                  </div>
                  <button
                    class="rounded-md border border-border px-2 py-1 text-xs hover:bg-accent"
                    onclick={() => void setCanonical(provider.provider)}
                    disabled={busy}
                  >
                    Set Canonical
                  </button>
                </div>
                <div class="text-xs text-muted-foreground">
                  Item: {provider.provider_item_id} | Confidence: {provider.confidence}%
                </div>
                {#if provider.path_tail}
                  <div class="text-xs text-muted-foreground">Path: {provider.path_tail}</div>
                {/if}
              </div>
            {/each}
          </div>
        {/if}

        {#if activeTab === "artwork" || activeTab === "metadata" || activeTab === "external_ids"}
          <div class="space-y-2 text-sm">
            {#each activeTab === "artwork"
              ? studio.artwork
              : activeTab === "metadata"
                ? studio.metadata
                : studio.external_ids as row}
              <div class="rounded-md border border-border/70 p-2">
                <div class="text-xs text-muted-foreground">{row.label}</div>
                {#each row.values as value}
                  <div>
                    {value.provider}: {value.value ?? "-"}
                  </div>
                {/each}
              </div>
            {/each}
          </div>
        {/if}

        {#if activeTab === "overrides"}
          <div class="space-y-3 text-sm">
            <div class="grid gap-2">
              <input
                class="rounded-md border border-border bg-background px-3 py-2"
                placeholder="Field (example: title)"
                bind:value={overrideField}
              />
              <input
                class="rounded-md border border-border bg-background px-3 py-2"
                placeholder="Value"
                bind:value={overrideValue}
              />
              <input
                class="rounded-md border border-border bg-background px-3 py-2"
                placeholder="Reason (optional)"
                bind:value={overrideReason}
              />
              <button
                class="rounded-md bg-primary px-3 py-2 text-primary-foreground hover:opacity-90 disabled:opacity-50"
                onclick={saveOverride}
                disabled={busy || !overrideField.trim() || !overrideValue.trim()}
              >
                Save Override
              </button>
            </div>

            {#each studio.overrides as row}
              <div class="rounded-md border border-border/70 p-2">
                <div>
                  <strong>{row.field}</strong>: {row.value}
                </div>
                <div class="text-xs text-muted-foreground">
                  {row.scope} | {new Date(row.created_at).toLocaleString()}
                </div>
                {#if row.reason}
                  <div class="text-xs text-muted-foreground">{row.reason}</div>
                {/if}
              </div>
            {/each}
          </div>
        {/if}

        {#if activeTab === "history"}
          <div class="space-y-2 text-sm">
            {#each studio.history as row}
              <div class="rounded-md border border-border/70 p-2">
                <div class="font-medium">{row.summary}</div>
                <div class="text-xs text-muted-foreground">
                  {row.action} | {row.result} | {new Date(row.created_at).toLocaleString()}
                </div>
              </div>
            {/each}
            {#if studio.history.length === 0}
              <div class="text-sm text-muted-foreground">No identity actions yet.</div>
            {/if}
          </div>
        {/if}
      {/if}
    </section>
  </div>

  <section class="rounded-2xl border border-border bg-card p-4">
    <h3 class="text-sm font-semibold">Recent Sync History</h3>
    <div class="mt-2 space-y-2 text-sm">
      {#if syncHistory && syncHistory.items.length > 0}
        {#each syncHistory.items as row}
          <div class="rounded-md border border-border/70 p-2">
            <div class="font-medium">{row.summary}</div>
            <div class="text-xs text-muted-foreground">
              {row.action} | {row.result} | {new Date(row.created_at).toLocaleString()}
            </div>
          </div>
        {/each}
      {:else}
        <div class="text-muted-foreground">No sync history entries yet.</div>
      {/if}
    </div>
  </section>
</div>
