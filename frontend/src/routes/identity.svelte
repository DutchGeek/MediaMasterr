<script lang="ts">
  import { onMount } from "svelte";
  import { get_api, post_api } from "$lib/api";
  import WorkspaceToolbar from "$lib/components/workspace/workspace-toolbar.svelte";
  import {
    type MediaFilterCatalogResponse,
    type MediaFilterOptionResponse,
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
    | "history"
    | "synchronization"
    | "diagnostics";

  let loading = $state(true);
  let error = $state("");
  let busy = $state(false);

  let search = $state("");
  let mediaFilter = $state<"all" | MediaType>("all");
  let candidatesOnly = $state(false);
  let arrFilterIds = $state<number[]>([]);
  let decisionFilterIds = $state<number[]>([]);
  let smartFilterIds = $state<number[]>([]);
  let filterCatalog = $state<MediaFilterCatalogResponse | null>(null);
  let sortBy = $state<"title" | "confidence" | "updated">("title");
  let sortOrder = $state<"asc" | "desc">("asc");
  let minConfidence = $state<number | null>(null);
  let maxConfidence = $state<number | null>(null);
  let canonicalProviderFilter = $state("");
  let syncStatusFilter = $state("all");
  let artworkStatusFilter = $state("all");
  let metadataStatusFilter = $state("all");
  let identifierStatusFilter = $state("all");
  let overrideStatusFilter = $state("all");
  let conflictLevelFilter = $state("all");
  let needsReviewFilter = $state<"all" | "yes" | "no">("all");
  let page = $state(1);
  let perPage = $state(24);
  let posterSize = $state(160);
  let displayMode = $state<"grid" | "list" | "table">("grid");
  let searchDebounce: ReturnType<typeof setTimeout> | null = null;
  let selectedArtworkByField = $state<Record<string, string>>({});
  let selectedExtendedArtworkByField = $state<Record<string, string>>({});
  let artworkDimensions = $state<Record<string, string>>({});

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
  let syncDecision = $state<"pending" | "approved" | "rejected">("pending");
  let providerTrustOrder = $state<string[]>([]);

  let overrideField = $state("");
  let overrideValue = $state("");
  let overrideReason = $state("");
  let syncBehavior = $state("merge");
  let lockState = $state("unlocked");
  let notes = $state("");

  let externalInput = $state("");
  let externalField = $state("imdb_id");
  let externalValidation = $state<{
    status: "idle" | "valid" | "invalid";
    field: string;
    value: string;
    detail: string;
  }>({
    status: "idle",
    field: "imdb_id",
    value: "",
    detail: "",
  });

  const tabOrder: Array<{ key: StudioTab; label: string }> = [
    { key: "overview", label: "Overview" },
    { key: "providers", label: "Providers" },
    { key: "artwork", label: "Artwork" },
    { key: "metadata", label: "Metadata" },
    { key: "external_ids", label: "External IDs" },
    { key: "overrides", label: "Overrides" },
    { key: "history", label: "History" },
    { key: "synchronization", label: "Synchronization" },
    { key: "diagnostics", label: "Diagnostics" },
  ];

  const providerTrustStorageKey = "identity_provider_trust_order_v1";
  const studioTabStorageKey = "identity_studio_active_tab_v1";
  const defaultProviderTrustOrder = [
    "manual",
    "plex",
    "sonarr",
    "radarr",
    "overseerr",
    "tmdb",
    "tvdb",
    "fanart",
    "jellyfin",
    "emby",
    "trakt",
    "anidb",
    "myanimelist",
    "tvmaze",
  ];

  const extendedArtworkTypes = [
    { key: "collection_poster", label: "Collection Poster" },
    { key: "collection_backdrop", label: "Collection Backdrop" },
    { key: "season_posters", label: "Season Posters" },
    { key: "season_banners", label: "Season Banners" },
    { key: "episode_artwork", label: "Episode Artwork" },
    { key: "anime_artwork", label: "Anime Artwork" },
  ];

  const sortByOptions = [
    { value: "title", label: "Title" },
    { value: "confidence", label: "Confidence" },
    { value: "updated", label: "Updated" },
  ];

  const bulkActions = [
    { key: "refresh_artwork", label: "Refresh Artwork" },
    { key: "validate_identity", label: "Validate Identity" },
    { key: "refresh_metadata", label: "Refresh Metadata" },
    { key: "repair_missing_artwork", label: "Repair Missing Artwork" },
    { key: "synchronize_providers", label: "Synchronize Providers" },
    { key: "apply_canonical_provider", label: "Apply Canonical Provider" },
    { key: "refresh_ids", label: "Refresh IDs" },
    { key: "queue_background_job", label: "Queue Background Job" },
  ];

  const externalIdFields = [
    "tmdb_id",
    "tvdb_id",
    "imdb_id",
    "trakt_id",
    "anidb_id",
    "myanimelist_id",
    "tvmaze_id",
  ];

  const identityStatusOptions = [
    { value: "all", label: "All" },
    { value: "healthy", label: "Healthy" },
    { value: "review", label: "Review" },
    { value: "attention", label: "Attention" },
    { value: "unknown", label: "Unknown" },
  ];

  const conflictOptions = [
    { value: "all", label: "All Conflicts" },
    { value: "none", label: "None" },
    { value: "low", label: "Low" },
    { value: "medium", label: "Medium" },
    { value: "high", label: "High" },
  ];

  const selectedFilterOptions = $derived.by(() => {
    const options: MediaFilterOptionResponse[] = [];
    for (const option of filterCatalog?.imported ?? []) {
      if (option.filter_id && arrFilterIds.includes(option.filter_id)) {
        options.push(option);
      }
    }
    for (const option of filterCatalog?.native ?? []) {
      if (option.filter_id && decisionFilterIds.includes(option.filter_id)) {
        options.push(option);
      }
    }
    for (const option of filterCatalog?.smart ?? []) {
      if (option.filter_id && smartFilterIds.includes(option.filter_id)) {
        options.push(option);
      }
    }
    return options;
  });

  const itemKey = (item: IdentityWorkspaceItem): string =>
    `${item.media_type}:${item.media_id}`;

  const selectedItems = $derived.by(() => {
    const rows = workspace?.items ?? [];
    return rows.filter((row) => selectedKeys.has(itemKey(row)));
  });

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

  const identityHealthLabel = (item: IdentityWorkspaceItem): string => {
    if (item.needs_review) return "Needs Attention";
    if (item.provider_confidence >= 90) return "Healthy";
    if (item.provider_confidence >= 75) return "Review";
    return "Uncertain";
  };

  const resolveRenderableImageUrl = (
    value: string | null | undefined,
  ): string | null => {
    const raw = value?.trim();
    if (!raw) return null;
    if (/^https?:\/\//i.test(raw)) return raw;
    if (/^data:image\//i.test(raw)) return raw;
    if (/^blob:/i.test(raw)) return raw;
    if (raw.startsWith("/")) return raw;
    return `/${raw}`;
  };

  const isValidStudioTab = (value: string): value is StudioTab =>
    tabOrder.some((tab) => tab.key === value);

  const setActiveTab = (tab: StudioTab) => {
    activeTab = tab;
    localStorage.setItem(studioTabStorageKey, tab);
  };

  const metadataValue = (
    row: IdentityStudioResponse["metadata"][number],
    provider: string,
  ) => row.values.find((value) => value.provider === provider)?.value;

  const canonicalValue = (row: {
    values: { is_canonical: boolean; value: string | null }[];
  }) =>
    row.values.find((value) => value.is_canonical)?.value ??
    row.values[0]?.value;

  const providerValues = (row: {
    values: {
      is_canonical: boolean;
      provider: string;
      value: string | null;
      confidence: number;
    }[];
  }) => row.values.filter((value) => !value.is_canonical);

  const providerRank = (provider: string): number => {
    const key = (provider || "").toLowerCase();
    const index = providerTrustOrder.indexOf(key);
    return index >= 0 ? index : providerTrustOrder.length + 100;
  };

  const trustedProviders = $derived.by(() => {
    const rows = [...(studio?.providers ?? [])];
    return rows.sort((a, b) => {
      const diff = providerRank(a.provider) - providerRank(b.provider);
      if (diff !== 0) return diff;
      return b.confidence - a.confidence;
    });
  });

  const providerUpdatedAtLabel = (provider: string): string => {
    const match = trustedProviders.find(
      (candidate) => candidate.provider === provider,
    );
    return match?.updated_at
      ? new Date(match.updated_at).toLocaleString()
      : "Unknown";
  };

  const confidenceStatus = (confidence: number): string => {
    if (confidence >= 90) return "Healthy";
    if (confidence >= 75) return "Review";
    return "Attention";
  };

  const providerSignalPreview = (
    provider: IdentityStudioResponse["providers"][number],
    field: "poster" | "backdrop" | "logo",
  ): string | null => {
    const direct = provider.signals?.[`${field}_url`];
    if (typeof direct === "string" && direct.trim()) return direct;
    const alt = provider.signals?.[`artwork_${field}`];
    if (typeof alt === "string" && alt.trim()) return alt;
    return field === "poster" ? provider.artwork_preview_url : null;
  };

  const providerExternalIdEntries = (
    provider: IdentityStudioResponse["providers"][number],
  ): Array<{ key: string; value: string }> => {
    const entries = Object.entries(provider.signals ?? {})
      .filter(
        ([key, value]) =>
          /(_id|imdb|tmdb|tvdb|trakt|anidb|tvmaze)/i.test(key) && value,
      )
      .slice(0, 8)
      .map(([key, value]) => ({ key, value: String(value) }));
    return entries;
  };

  const metadataDiffers = (
    row: IdentityStudioResponse["metadata"][number],
    provider: string,
  ): boolean => {
    const providerValue =
      row.values.find((value) => value.provider === provider)?.value ?? null;
    return (providerValue ?? "") !== (canonicalValue(row) ?? "");
  };

  const onArtworkImageLoad = (key: string, provider: string, event: Event) => {
    const image = event.currentTarget as HTMLImageElement;
    const dim = `${image.naturalWidth}x${image.naturalHeight}`;
    artworkDimensions = {
      ...artworkDimensions,
      [`${key}:${provider}`]: dim,
    };
  };

  const inferExternalField = (
    raw: string,
  ): { field: string; value: string } | null => {
    const value = raw.trim();
    if (!value) return null;

    const imdbMatch = value.match(/(tt\d{5,10})/i);
    if (imdbMatch)
      return { field: "imdb_id", value: imdbMatch[1].toLowerCase() };

    if (/themoviedb\.org/i.test(value) || /tmdb/i.test(value)) {
      const numeric = value.match(/(\d{2,})/);
      if (numeric) return { field: "tmdb_id", value: numeric[1] };
    }
    if (/thetvdb\.com|tvdb/i.test(value)) {
      const numeric = value.match(/(\d{2,})/);
      if (numeric) return { field: "tvdb_id", value: numeric[1] };
    }
    if (/tvmaze\.com/i.test(value)) {
      const numeric = value.match(/(\d{2,})/);
      if (numeric) return { field: "tvmaze_id", value: numeric[1] };
    }

    if (/^\d+$/.test(value)) return { field: externalField, value };
    return { field: externalField, value };
  };

  async function loadFilterCatalog() {
    try {
      filterCatalog =
        await get_api<MediaFilterCatalogResponse>("/api/media/filters");
    } catch {
      filterCatalog = null;
    }
  }

  function addArrayParams(
    params: URLSearchParams,
    key: string,
    values: number[],
  ) {
    for (const value of values) {
      params.append(key, String(value));
    }
  }

  function parseHashFilters() {
    const hash = window.location.hash || "";
    const queryStart = hash.indexOf("?");
    if (queryStart < 0) return;
    const query = hash.slice(queryStart + 1);
    const params = new URLSearchParams(query);
    if (params.get("needs_review") === "true") {
      needsReviewFilter = "yes";
    }
    if (params.get("media_type") === MediaType.Movie)
      mediaFilter = MediaType.Movie;
    if (params.get("media_type") === MediaType.Series)
      mediaFilter = MediaType.Series;
  }

  async function loadWorkspace() {
    loading = true;
    error = "";
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("per_page", String(perPage));
      params.set("sort_by", sortBy);
      params.set("sort_order", sortOrder);
      params.set("candidates_only", String(candidatesOnly));
      if (search.trim()) params.set("search", search.trim());
      if (mediaFilter !== "all") params.set("media_type", mediaFilter);
      addArrayParams(params, "arr_filter_ids", arrFilterIds);
      addArrayParams(params, "decision_filter_ids", decisionFilterIds);
      addArrayParams(params, "smart_filter_ids", smartFilterIds);
      if (minConfidence !== null)
        params.set("min_confidence", String(minConfidence));
      if (maxConfidence !== null)
        params.set("max_confidence", String(maxConfidence));
      if (canonicalProviderFilter.trim())
        params.set("canonical_provider", canonicalProviderFilter.trim());
      if (syncStatusFilter !== "all")
        params.set("sync_status", syncStatusFilter);
      if (artworkStatusFilter !== "all")
        params.set("artwork_status", artworkStatusFilter);
      if (metadataStatusFilter !== "all")
        params.set("metadata_status", metadataStatusFilter);
      if (identifierStatusFilter !== "all")
        params.set("identifier_status", identifierStatusFilter);
      if (overrideStatusFilter !== "all")
        params.set("override_status", overrideStatusFilter);
      if (conflictLevelFilter !== "all")
        params.set("conflict_level", conflictLevelFilter);
      if (needsReviewFilter === "yes") params.set("needs_review", "true");
      if (needsReviewFilter === "no") params.set("needs_review", "false");

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

  async function upsertOverride(field: string, value: string, reason: string) {
    if (!selectedItem) return;
    busy = true;
    syncMessage = "";
    try {
      const response = await post_api<IdentityActionResponse>(
        `/api/mie/identity/${selectedItem.media_type}/${selectedItem.media_id}/overrides`,
        {
          field,
          value,
          reason,
          scope: "media",
        },
      );
      syncMessage = response.message;
      await loadStudio(selectedItem);
    } catch (e: any) {
      syncMessage = e?.message ?? "Failed to apply override";
    } finally {
      busy = false;
    }
  }

  async function useProviderPreset(
    provider: string,
    mode: "identity" | "artwork" | "metadata" | "everything",
  ) {
    if (!selectedItem) return;
    if (mode === "identity") {
      await setCanonical(provider);
      return;
    }
    if (mode === "artwork") {
      await upsertOverride(
        "artwork_profile",
        provider,
        `Artwork profile from ${provider}`,
      );
      return;
    }
    if (mode === "metadata") {
      await upsertOverride(
        "metadata_profile",
        provider,
        `Metadata profile from ${provider}`,
      );
      return;
    }

    await setCanonical(provider);
    await upsertOverride(
      "sync_provider",
      provider,
      `Unified profile from ${provider}`,
    );
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
    candidatesOnly = false;
    arrFilterIds = [];
    decisionFilterIds = [];
    smartFilterIds = [];
    sortBy = "title";
    sortOrder = "asc";
    minConfidence = null;
    maxConfidence = null;
    canonicalProviderFilter = "";
    syncStatusFilter = "all";
    artworkStatusFilter = "all";
    metadataStatusFilter = "all";
    identifierStatusFilter = "all";
    overrideStatusFilter = "all";
    conflictLevelFilter = "all";
    needsReviewFilter = "all";
    page = 1;
    void loadWorkspace();
  }

  function moveProviderTrust(provider: string, direction: "up" | "down") {
    const key = provider.toLowerCase();
    const next = [...providerTrustOrder];
    const index = next.indexOf(key);
    if (index < 0) return;
    const swapWith = direction === "up" ? index - 1 : index + 1;
    if (swapWith < 0 || swapWith >= next.length) return;
    [next[index], next[swapWith]] = [next[swapWith], next[index]];
    providerTrustOrder = next;
    localStorage.setItem(providerTrustStorageKey, JSON.stringify(next));
  }

  function resetProviderTrustOrder() {
    providerTrustOrder = [...defaultProviderTrustOrder];
    localStorage.setItem(
      providerTrustStorageKey,
      JSON.stringify(defaultProviderTrustOrder),
    );
  }

  function handleSearch(value: string) {
    search = value;
    page = 1;
    if (searchDebounce) clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      void loadWorkspace();
    }, 300);
  }

  function toggleFilterSelection(
    source: "imported" | "decision" | "smart",
    filterId: number,
  ) {
    const target =
      source === "imported"
        ? arrFilterIds
        : source === "decision"
          ? decisionFilterIds
          : smartFilterIds;
    const exists = target.includes(filterId);
    const next = exists
      ? target.filter((id) => id !== filterId)
      : [...target, filterId];
    if (source === "imported") arrFilterIds = next;
    if (source === "decision") decisionFilterIds = next;
    if (source === "smart") smartFilterIds = next;
    page = 1;
    void loadWorkspace();
  }

  function clearAllFilters() {
    arrFilterIds = [];
    decisionFilterIds = [];
    smartFilterIds = [];
    page = 1;
    void loadWorkspace();
  }

  function applySmartFilter(option: MediaFilterOptionResponse) {
    if (!option.filter_id) return;
    if (!smartFilterIds.includes(option.filter_id)) {
      smartFilterIds = [...smartFilterIds, option.filter_id];
      page = 1;
      void loadWorkspace();
    }
  }

  function openFilterManager(_mode: "arr" | "decision") {
    window.location.hash = "#/movies";
  }

  function openSmartFilterDialog() {
    window.location.hash = "#/movies";
  }

  function handleBulkAction(_key: string) {
    const count = selectedItems.length;
    if (_key !== "queue_background_job" && count <= 0) {
      syncMessage = "Select one or more rows before running a bulk action.";
      return;
    }

    if (_key === "apply_canonical_provider") {
      const provider =
        canonicalProviderFilter.trim() || selectedItems[0]?.canonical_provider;
      if (!provider) {
        syncMessage =
          "Select a canonical provider filter or row with provider context first.";
        return;
      }

      busy = true;
      syncMessage = "";
      Promise.all(
        selectedItems.map((row) =>
          post_api<IdentityActionResponse>(
            `/api/mie/identity/${row.media_type}/${row.media_id}/canonical`,
            {
              provider,
              reason: `Bulk apply canonical provider (${provider})`,
            },
          ),
        ),
      )
        .then(() => {
          syncMessage = `Applied canonical provider ${provider} to ${count} item(s).`;
          return loadWorkspace();
        })
        .catch((e: any) => {
          syncMessage =
            e?.message ?? "Failed to apply canonical provider in bulk.";
        })
        .finally(() => {
          busy = false;
        });
      return;
    }

    void runSync();
    syncMessage = `Queued ${_key.replaceAll("_", " ")} for ${Math.max(count, 1)} item(s).`;
  }

  function validateExternalInput() {
    const parsed = inferExternalField(externalInput);
    if (!parsed || !parsed.value) {
      externalValidation = {
        status: "invalid",
        field: externalField,
        value: "",
        detail: "Enter a provider URL or an ID value.",
      };
      return;
    }

    const valid =
      parsed.field === "imdb_id"
        ? /^tt\d{5,10}$/i.test(parsed.value)
        : /^\d+$/i.test(parsed.value);
    externalValidation = {
      status: valid ? "valid" : "invalid",
      field: parsed.field,
      value: parsed.value,
      detail: valid
        ? `Validated as ${parsed.field}.`
        : `Could not validate ${parsed.field} format.`,
    };
  }

  function searchExternal() {
    validateExternalInput();
    if (externalValidation.status !== "valid") return;
    syncMessage = `Search prepared for ${externalValidation.field} ${externalValidation.value}.`;
  }

  async function repairExternalOverride() {
    validateExternalInput();
    if (externalValidation.status !== "valid") return;
    await upsertOverride(
      externalValidation.field,
      externalValidation.value,
      `Repair requested for ${externalValidation.field}`,
    );
  }

  async function approveSync() {
    syncDecision = "approved";
    syncMessage = "Synchronization preview approved. Ready to queue.";
  }

  async function rejectSync() {
    syncDecision = "rejected";
    syncMessage = "Synchronization preview rejected. No changes queued.";
  }

  async function applyExternalOverride() {
    if (externalValidation.status !== "valid") {
      validateExternalInput();
      return;
    }
    await upsertOverride(
      externalValidation.field,
      externalValidation.value,
      `External ID override via Identity Studio (${externalValidation.field})`,
    );
  }

  onMount(() => {
    const savedTrust = localStorage.getItem(providerTrustStorageKey);
    if (savedTrust) {
      try {
        const parsed = JSON.parse(savedTrust);
        if (
          Array.isArray(parsed) &&
          parsed.every((v) => typeof v === "string")
        ) {
          providerTrustOrder = parsed.map((v) => v.toLowerCase());
        } else {
          providerTrustOrder = [...defaultProviderTrustOrder];
        }
      } catch {
        providerTrustOrder = [...defaultProviderTrustOrder];
      }
    } else {
      providerTrustOrder = [...defaultProviderTrustOrder];
    }

    const savedTab = localStorage.getItem(studioTabStorageKey);
    if (savedTab && isValidStudioTab(savedTab)) {
      activeTab = savedTab;
    }

    parseHashFilters();
    void loadFilterCatalog();
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
      <div
        class="mt-4 rounded-lg border border-border/70 bg-muted/30 p-3 text-sm"
      >
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
      <WorkspaceToolbar
        searchQuery={search}
        searchPlaceholder="Search titles, providers, identifiers"
        {sortBy}
        {sortByOptions}
        {sortOrder}
        {candidatesOnly}
        {filterCatalog}
        importedFilterIds={arrFilterIds}
        {decisionFilterIds}
        {smartFilterIds}
        {selectedFilterOptions}
        {perPage}
        {posterSize}
        viewMode={displayMode}
        viewModes={["grid", "list", "table"]}
        selectedCount={selectedKeys.size}
        {bulkActions}
        onSearchInput={handleSearch}
        onSortByChange={(value) => {
          sortBy = value as "title" | "confidence" | "updated";
          page = 1;
          void loadWorkspace();
        }}
        onSortOrderChange={(value) => {
          sortOrder = value;
          page = 1;
          void loadWorkspace();
        }}
        onCandidatesOnlyChange={(value) => {
          candidatesOnly = value;
          page = 1;
          void loadWorkspace();
        }}
        onToggleFilterSelection={toggleFilterSelection}
        onOpenFilterManager={openFilterManager}
        onOpenSmartFilterDialog={openSmartFilterDialog}
        onApplySmartFilter={applySmartFilter}
        onClearAllFilters={clearAllFilters}
        onPerPageChange={(value) => {
          perPage = value;
          page = 1;
          void loadWorkspace();
        }}
        onPosterSizeChange={(value) => (posterSize = value)}
        onViewModeChange={(value) =>
          (displayMode = value as "grid" | "list" | "table")}
        onBulkAction={handleBulkAction}
      />

      <div
        class="grid gap-2 rounded-xl border border-border/70 bg-muted/20 p-3 md:grid-cols-2 xl:grid-cols-4"
      >
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

        <select
          class="rounded-md border border-border bg-background px-3 py-2 text-sm"
          bind:value={conflictLevelFilter}
          onchange={() => {
            page = 1;
            void loadWorkspace();
          }}
        >
          {#each conflictOptions as option}
            <option value={option.value}>{option.label}</option>
          {/each}
        </select>

        <select
          class="rounded-md border border-border bg-background px-3 py-2 text-sm"
          bind:value={needsReviewFilter}
          onchange={() => {
            page = 1;
            void loadWorkspace();
          }}
        >
          <option value="all">Review: All</option>
          <option value="yes">Needs Review</option>
          <option value="no">Review Complete</option>
        </select>

        <select
          class="rounded-md border border-border bg-background px-3 py-2 text-sm"
          bind:value={overrideStatusFilter}
          onchange={() => {
            page = 1;
            void loadWorkspace();
          }}
        >
          <option value="all">Overrides: All</option>
          <option value="manual">Manual Override</option>
          <option value="none">No Override</option>
        </select>

        <select
          class="rounded-md border border-border bg-background px-3 py-2 text-sm"
          bind:value={artworkStatusFilter}
          onchange={() => {
            page = 1;
            void loadWorkspace();
          }}
        >
          {#each identityStatusOptions as option}
            <option value={option.value}>Artwork: {option.label}</option>
          {/each}
        </select>

        <select
          class="rounded-md border border-border bg-background px-3 py-2 text-sm"
          bind:value={metadataStatusFilter}
          onchange={() => {
            page = 1;
            void loadWorkspace();
          }}
        >
          {#each identityStatusOptions as option}
            <option value={option.value}>Metadata: {option.label}</option>
          {/each}
        </select>

        <select
          class="rounded-md border border-border bg-background px-3 py-2 text-sm"
          bind:value={identifierStatusFilter}
          onchange={() => {
            page = 1;
            void loadWorkspace();
          }}
        >
          {#each identityStatusOptions as option}
            <option value={option.value}>Identifiers: {option.label}</option>
          {/each}
        </select>

        <input
          class="rounded-md border border-border bg-background px-3 py-2 text-sm"
          placeholder="Canonical provider (optional)"
          bind:value={canonicalProviderFilter}
          onblur={() => {
            canonicalProviderFilter = canonicalProviderFilter.trim();
            page = 1;
            void loadWorkspace();
          }}
        />
      </div>

      <div class="flex flex-wrap items-center justify-between gap-2 text-sm">
        <div class="text-muted-foreground">
          {workspace?.total ?? 0} items | Selected: {selectedKeys.size}
        </div>
        <div class="flex items-center gap-2">
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
        <div
          class="rounded-lg border border-border/70 bg-muted/20 p-6 text-sm text-muted-foreground"
        >
          Loading identity rows...
        </div>
      {:else if error}
        <div
          class="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
        >
          {error}
        </div>
      {:else if items.length === 0}
        <div
          class="rounded-lg border border-border/70 bg-muted/20 p-6 text-sm text-muted-foreground"
        >
          No identity rows found for current filters.
        </div>
      {:else}
        {#if displayMode === "table"}
          <div class="overflow-hidden rounded-xl border border-border/70">
            <table class="w-full text-left text-sm">
              <thead
                class="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground"
              >
                <tr>
                  <th class="px-3 py-2">Select</th>
                  <th class="px-3 py-2">Title</th>
                  <th class="px-3 py-2">Providers</th>
                  <th class="px-3 py-2">Confidence</th>
                  <th class="px-3 py-2">Health</th>
                  <th class="px-3 py-2">Conflict</th>
                  <th class="px-3 py-2">Needs Review</th>
                </tr>
              </thead>
              <tbody>
                {#each items as item}
                  <tr
                    class="cursor-pointer border-t border-border/50 hover:bg-secondary/20"
                    onclick={() => void loadStudio(item)}
                  >
                    <td class="px-3 py-2">
                      <input
                        type="checkbox"
                        checked={selectedKeys.has(itemKey(item))}
                        onchange={() => toggleSelection(item)}
                        onclick={(event) => event.stopPropagation()}
                      />
                    </td>
                    <td class="px-3 py-2">
                      <div class="font-medium text-foreground">
                        {item.title}
                      </div>
                      <div class="text-xs text-muted-foreground">
                        {mediaLabel(item.media_type)}
                        {item.year ?? ""}
                      </div>
                    </td>
                    <td class="px-3 py-2">{item.provider_count}</td>
                    <td class="px-3 py-2">{item.provider_confidence}%</td>
                    <td class="px-3 py-2">{identityHealthLabel(item)}</td>
                    <td class="px-3 py-2">
                      <span class={conflictClass(item.conflict_level)}
                        >{item.conflict_level}</span
                      >
                    </td>
                    <td class="px-3 py-2">{item.needs_review ? "Yes" : "No"}</td
                    >
                  </tr>
                {/each}
              </tbody>
            </table>
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
                      class="rounded object-cover"
                      style={`height:${Math.round((posterSize * 2) / 25)}px;width:${Math.round((posterSize * 1.35) / 25)}px;`}
                    />
                  {/if}
                  <button
                    class="min-w-0 flex-1 text-left"
                    onclick={() => void loadStudio(item)}
                  >
                    <div class="truncate text-base font-semibold">
                      {item.title}
                    </div>
                    <div class="text-xs text-muted-foreground">
                      {mediaLabel(item.media_type)} • {item.year ??
                        "Unknown Year"}
                    </div>
                    <div class="mt-2 flex flex-wrap gap-2 text-xs">
                      <span class="rounded bg-muted px-2 py-0.5">
                        Canonical: {item.canonical_provider}
                      </span>
                      <span class="rounded bg-muted px-2 py-0.5">
                        Provider Count: {item.provider_count}
                      </span>
                      <span class="rounded bg-muted px-2 py-0.5">
                        Confidence: {item.provider_confidence}%
                      </span>
                      <span class="rounded bg-muted px-2 py-0.5">
                        Health: {identityHealthLabel(item)}
                      </span>
                      <span
                        class={`rounded px-2 py-0.5 ${conflictClass(item.conflict_level)}`}
                      >
                        Conflict: {item.conflict_level}
                      </span>
                      <span class="rounded bg-muted px-2 py-0.5">
                        Artwork: {item.artwork_status}
                      </span>
                      <span class="rounded bg-muted px-2 py-0.5">
                        Metadata: {item.metadata_status}
                      </span>
                      <span class="rounded bg-muted px-2 py-0.5">
                        Identifier: {item.identifier_status}
                      </span>
                      {#if item.needs_review}
                        <span
                          class="rounded bg-destructive/15 px-2 py-0.5 text-destructive"
                        >
                          Needs Review
                        </span>
                      {/if}
                    </div>
                  </button>
                </div>
              </article>
            {/each}
          </div>
        {/if}

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
        <div
          class="rounded-lg border border-border/70 bg-muted/20 p-6 text-sm text-muted-foreground"
        >
          Loading studio...
        </div>
      {:else if studioError}
        <div
          class="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
        >
          {studioError}
        </div>
      {:else if studio}
        <div class="flex flex-wrap gap-2">
          {#each tabOrder as tab}
            <button
              class={activeTab === tab.key
                ? "rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground"
                : "rounded-md border border-border px-3 py-1 text-xs hover:bg-accent"}
              onclick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          {/each}
        </div>

        {#if activeTab === "overview"}
          <div class="grid gap-3 md:grid-cols-2">
            <div class="rounded-xl border border-border/70 bg-muted/20 p-3">
              <div
                class="text-xs uppercase tracking-wide text-muted-foreground"
              >
                Canonical Provider
              </div>
              <div class="mt-1 text-base font-semibold text-foreground">
                {studio.canonical_provider}
              </div>
              <div class="mt-2 text-xs text-muted-foreground">
                Managing this title should feel like curating a collection, not
                editing records.
              </div>
            </div>
            <div class="rounded-xl border border-border/70 bg-muted/20 p-3">
              <div
                class="text-xs uppercase tracking-wide text-muted-foreground"
              >
                Current Selection
              </div>
              <div class="mt-1 text-base font-semibold text-foreground">
                {studio.title} ({studio.year ?? "Unknown Year"})
              </div>
              <div class="mt-2 text-xs text-muted-foreground">
                Use tabs to compare providers, choose artwork, and apply
                canonical identity rules.
              </div>
            </div>

            {#each studio.overview as row}
              <div class="rounded-xl border border-border/70 p-3 text-sm">
                <div class="text-xs text-muted-foreground">{row.label}</div>
                <div class="mt-2 grid gap-2">
                  {#each row.values as value}
                    <div
                      class="rounded-md border border-border/50 bg-background/70 px-2 py-1"
                    >
                      <span
                        class="text-xs uppercase tracking-wide text-muted-foreground"
                      >
                        {value.provider}
                      </span>
                      <div class="text-sm text-foreground">
                        {value.value ?? "-"}
                      </div>
                    </div>
                  {/each}
                </div>
              </div>
            {/each}
          </div>
        {/if}

        {#if activeTab === "providers"}
          <div class="grid gap-3 lg:grid-cols-2 text-sm">
            {#each trustedProviders as provider}
              <article
                class="rounded-xl border border-border/70 bg-background/70 p-3"
              >
                <div class="flex items-start justify-between gap-3">
                  <div>
                    <strong class="text-base">{provider.provider}</strong>
                    {#if provider.is_canonical}
                      <span
                        class="ml-2 rounded bg-primary/20 px-2 py-0.5 text-xs"
                        >canonical</span
                      >
                    {/if}
                    <div class="mt-1 text-xs text-muted-foreground">
                      Last Updated: {provider.updated_at
                        ? new Date(provider.updated_at).toLocaleString()
                        : "Unknown"}
                    </div>
                    <div class="mt-1 text-xs text-muted-foreground">
                      Confidence {provider.confidence}% • IDs {provider.external_ids_count}
                      • Collections {provider.collection_count}
                    </div>
                  </div>

                  {#if providerSignalPreview(provider, "poster")}
                    <img
                      src={providerSignalPreview(provider, "poster") ??
                        undefined}
                      alt={`${provider.provider} poster`}
                      class="h-24 w-16 rounded object-cover"
                    />
                  {/if}
                </div>

                <div class="mt-3 grid gap-2 sm:grid-cols-3">
                  <div
                    class="rounded-md border border-border/60 bg-muted/10 p-2"
                  >
                    <div
                      class="text-[11px] uppercase tracking-wide text-muted-foreground"
                    >
                      Poster
                    </div>
                    {#if providerSignalPreview(provider, "poster")}
                      <img
                        src={providerSignalPreview(provider, "poster") ??
                          undefined}
                        alt={`${provider.provider} poster preview`}
                        class="mt-1 h-20 w-full rounded object-cover"
                      />
                    {:else}
                      <div
                        class="mt-1 rounded bg-secondary/30 px-2 py-4 text-center text-xs text-muted-foreground"
                      >
                        No poster
                      </div>
                    {/if}
                  </div>
                  <div
                    class="rounded-md border border-border/60 bg-muted/10 p-2"
                  >
                    <div
                      class="text-[11px] uppercase tracking-wide text-muted-foreground"
                    >
                      Backdrop
                    </div>
                    {#if providerSignalPreview(provider, "backdrop")}
                      <img
                        src={providerSignalPreview(provider, "backdrop") ??
                          undefined}
                        alt={`${provider.provider} backdrop preview`}
                        class="mt-1 h-20 w-full rounded object-cover"
                      />
                    {:else}
                      <div
                        class="mt-1 rounded bg-secondary/30 px-2 py-4 text-center text-xs text-muted-foreground"
                      >
                        No backdrop
                      </div>
                    {/if}
                  </div>
                  <div
                    class="rounded-md border border-border/60 bg-muted/10 p-2"
                  >
                    <div
                      class="text-[11px] uppercase tracking-wide text-muted-foreground"
                    >
                      Logo
                    </div>
                    {#if providerSignalPreview(provider, "logo")}
                      <img
                        src={providerSignalPreview(provider, "logo") ??
                          undefined}
                        alt={`${provider.provider} logo preview`}
                        class="mt-1 h-20 w-full rounded object-contain bg-black/10"
                      />
                    {:else}
                      <div
                        class="mt-1 rounded bg-secondary/30 px-2 py-4 text-center text-xs text-muted-foreground"
                      >
                        No logo
                      </div>
                    {/if}
                  </div>
                </div>

                <div class="mt-3 grid gap-2 md:grid-cols-2">
                  <div
                    class="rounded-md border border-border/60 bg-background/70 p-2 text-xs"
                  >
                    <div class="font-semibold text-foreground">
                      Metadata Summary
                    </div>
                    {#each studio.metadata.slice(0, 5) as row}
                      <div class="mt-1 flex items-start justify-between gap-2">
                        <span class="text-muted-foreground">{row.label}</span>
                        <span
                          class={metadataDiffers(row, provider.provider)
                            ? "text-amber-500"
                            : "text-foreground"}
                        >
                          {metadataValue(row, provider.provider) ??
                            "Not supplied"}
                        </span>
                      </div>
                    {/each}
                  </div>
                  <div
                    class="rounded-md border border-border/60 bg-background/70 p-2 text-xs"
                  >
                    <div class="font-semibold text-foreground">
                      External IDs
                    </div>
                    {#if providerExternalIdEntries(provider).length > 0}
                      {#each providerExternalIdEntries(provider) as entry}
                        <div
                          class="mt-1 flex items-start justify-between gap-2"
                        >
                          <span class="text-muted-foreground">{entry.key}</span>
                          <span class="text-foreground break-all"
                            >{entry.value}</span
                          >
                        </div>
                      {/each}
                    {:else}
                      <div class="mt-1 text-muted-foreground">
                        No provider IDs exposed.
                      </div>
                    {/if}
                  </div>
                </div>

                <div class="mt-2 text-xs text-muted-foreground">
                  Item: {provider.provider_item_id}
                </div>
                {#if provider.path_tail}
                  <div class="mt-1 text-xs text-muted-foreground break-all">
                    Path: {provider.path_tail}
                  </div>
                {/if}

                <div class="mt-3 grid grid-cols-2 gap-2 text-xs">
                  <button
                    class="rounded-md border border-border px-2 py-1 hover:bg-accent"
                    onclick={() =>
                      void upsertOverride(
                        "id_profile",
                        provider.provider,
                        `External ID profile from ${provider.provider}`,
                      )}
                    disabled={busy}
                  >
                    Use IDs
                  </button>
                  <button
                    class="rounded-md border border-border px-2 py-1 hover:bg-accent"
                    onclick={() =>
                      void useProviderPreset(provider.provider, "artwork")}
                    disabled={busy}
                  >
                    Use Artwork
                  </button>
                  <button
                    class="rounded-md border border-border px-2 py-1 hover:bg-accent"
                    onclick={() =>
                      void useProviderPreset(provider.provider, "metadata")}
                    disabled={busy}
                  >
                    Use Metadata
                  </button>
                  <button
                    class="rounded-md bg-primary px-2 py-1 text-primary-foreground hover:opacity-90"
                    onclick={() =>
                      void useProviderPreset(provider.provider, "everything")}
                    disabled={busy}
                  >
                    Use Everything
                  </button>
                </div>
              </article>
            {/each}
          </div>
        {/if}

        {#if activeTab === "artwork"}
          <div class="space-y-3 text-sm">
            {#each studio.artwork as row}
              <div class="rounded-xl border border-border/70 bg-muted/10 p-3">
                <div class="flex items-center justify-between gap-2">
                  <h3 class="text-sm font-semibold text-foreground">
                    {row.label}
                  </h3>
                  <span class="text-xs text-muted-foreground">
                    Selected: {selectedArtworkByField[row.key] ?? "canonical"}
                  </span>
                </div>

                <div class="mt-2 space-y-2">
                  {#each row.values as value}
                    {@const previewUrl = resolveRenderableImageUrl(value.value)}
                    <label
                      class="block rounded-xl border border-border/70 bg-background/80 p-2"
                    >
                      <div class="flex items-center justify-between gap-2">
                        <div class="flex items-center gap-2">
                          <input
                            type="radio"
                            name={`artwork-${row.key}`}
                            checked={(selectedArtworkByField[row.key] ??
                              "canonical") === value.provider}
                            onchange={() =>
                              (selectedArtworkByField = {
                                ...selectedArtworkByField,
                                [row.key]: value.provider,
                              })}
                          />
                          <div
                            class="text-xs font-medium uppercase tracking-wide text-muted-foreground"
                          >
                            {value.provider}
                          </div>
                        </div>
                      </div>

                      <div class="mt-2 grid gap-3 lg:grid-cols-[220px_1fr]">
                        <div>
                          {#if previewUrl}
                            <img
                              src={previewUrl}
                              alt={`${row.label} from ${value.provider}`}
                              class="h-72 w-full rounded object-cover"
                              onload={(event) =>
                                onArtworkImageLoad(
                                  row.key,
                                  value.provider,
                                  event,
                                )}
                            />
                          {:else}
                            <div
                              class="flex h-72 w-full items-center justify-center rounded bg-secondary/30 p-3 text-center text-xs text-muted-foreground"
                            >
                              No preview image
                            </div>
                          {/if}
                        </div>

                        <div class="grid gap-1 text-xs text-muted-foreground">
                          <div>
                            Resolution: {artworkDimensions[
                              `${row.key}:${value.provider}`
                            ] ?? "Unknown"}
                          </div>
                          <div>Source: {value.provider}</div>
                          <div>
                            Last Updated: {providerUpdatedAtLabel(
                              value.provider,
                            )}
                          </div>
                          <div>Confidence: {value.confidence}%</div>
                          <div>
                            Status: {confidenceStatus(value.confidence)}
                          </div>
                          <div class="break-all text-foreground/80">
                            URL: {previewUrl ?? "Unavailable"}
                          </div>
                        </div>
                      </div>
                    </label>
                  {/each}
                </div>
              </div>
            {/each}

            <div class="rounded-xl border border-border/70 bg-card p-3">
              <div
                class="text-xs uppercase tracking-wide text-muted-foreground"
              >
                Canonical Artwork Profile
              </div>
              <div
                class="mt-2 grid gap-2 text-xs md:grid-cols-2 xl:grid-cols-3"
              >
                {#each studio.artwork as row}
                  <div
                    class="rounded-md border border-border/60 bg-background/70 px-2 py-1"
                  >
                    <span class="font-medium text-foreground">{row.label}</span>
                    <div class="text-muted-foreground">
                      {selectedArtworkByField[row.key] ?? "canonical"}
                    </div>
                  </div>
                {/each}
              </div>
            </div>

            <div class="rounded-xl border border-border/70 bg-card p-3">
              <div
                class="text-xs uppercase tracking-wide text-muted-foreground"
              >
                Extended Artwork Targets
              </div>
              <div class="mt-3 grid gap-3 md:grid-cols-2">
                {#each extendedArtworkTypes as artworkType}
                  <div
                    class="rounded-lg border border-border/60 bg-background/70 p-3"
                  >
                    <div class="font-medium text-foreground">
                      {artworkType.label}
                    </div>
                    <div class="mt-2 space-y-2">
                      {#each trustedProviders as provider}
                        <label
                          class="flex items-center justify-between gap-2 rounded-md border border-border/50 px-2 py-1 text-xs"
                        >
                          <span class="text-foreground"
                            >{provider.provider}</span
                          >
                          <span class="text-muted-foreground"
                            >{confidenceStatus(provider.confidence)}</span
                          >
                          <span class="text-muted-foreground"
                            >{providerUpdatedAtLabel(provider.provider)}</span
                          >
                          <input
                            type="checkbox"
                            checked={(selectedExtendedArtworkByField[
                              artworkType.key
                            ] ?? "") === provider.provider}
                            onchange={() =>
                              (selectedExtendedArtworkByField = {
                                ...selectedExtendedArtworkByField,
                                [artworkType.key]: provider.provider,
                              })}
                          />
                        </label>
                      {/each}
                    </div>
                  </div>
                {/each}
              </div>
            </div>
          </div>
        {/if}

        {#if activeTab === "metadata"}
          <div class="space-y-2 text-sm">
            {#each studio.metadata as row}
              <div class="rounded-xl border border-border/70 p-3">
                <div class="text-sm font-semibold text-foreground">
                  {row.label}
                </div>
                <div class="mt-2 overflow-x-auto">
                  <table class="w-full text-left text-xs">
                    <thead class="text-muted-foreground">
                      <tr>
                        <th class="py-1 pr-2">Current</th>
                        <th class="py-1 pr-2">Provider</th>
                        <th class="py-1">Canonical</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each trustedProviders as provider}
                        {@const providerValue = metadataValue(
                          row,
                          provider.provider,
                        )}
                        <tr class="border-t border-border/50">
                          <td class="py-1 pr-2">{canonicalValue(row) ?? "-"}</td
                          >
                          <td
                            class={`py-1 pr-2 ${
                              providerValue !== (canonicalValue(row) ?? null)
                                ? "text-amber-500"
                                : "text-foreground"
                            }`}
                            >{provider.provider}: {providerValue ??
                              "Not supplied"}</td
                          >
                          <td class="py-1">{canonicalValue(row) ?? "-"}</td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              </div>
            {/each}
          </div>
        {/if}

        {#if activeTab === "external_ids"}
          <div class="space-y-3 text-sm">
            <div class="rounded-xl border border-border/70 bg-muted/20 p-3">
              <div
                class="text-xs uppercase tracking-wide text-muted-foreground"
              >
                ID Tools
              </div>
              <div class="mt-2 grid gap-2 md:grid-cols-[auto_1fr_auto_auto]">
                <select
                  class="rounded-md border border-border bg-background px-3 py-2"
                  bind:value={externalField}
                >
                  {#each externalIdFields as field}
                    <option value={field}>{field}</option>
                  {/each}
                </select>
                <input
                  class="rounded-md border border-border bg-background px-3 py-2"
                  placeholder="Paste ID or provider URL"
                  bind:value={externalInput}
                />
                <button
                  class="rounded-md border border-border px-3 py-2 hover:bg-accent"
                  onclick={searchExternal}
                >
                  Search
                </button>
                <button
                  class="rounded-md border border-border px-3 py-2 hover:bg-accent"
                  onclick={validateExternalInput}
                >
                  Validate
                </button>
                <button
                  class="rounded-md border border-border px-3 py-2 hover:bg-accent"
                  onclick={() => void repairExternalOverride()}
                >
                  Repair
                </button>
                <button
                  class="rounded-md bg-primary px-3 py-2 text-primary-foreground hover:opacity-90"
                  onclick={() => void applyExternalOverride()}
                >
                  Override
                </button>
              </div>
              {#if externalValidation.status !== "idle"}
                <p
                  class={`mt-2 text-xs ${externalValidation.status === "valid" ? "text-emerald-500" : "text-destructive"}`}
                >
                  {externalValidation.detail} ({externalValidation.field}: {externalValidation.value ||
                    "-"})
                </p>
              {/if}
            </div>

            {#each studio.external_ids as row}
              <div class="rounded-xl border border-border/70 p-3">
                <div class="text-sm font-semibold text-foreground">
                  {row.label}
                </div>
                <div class="mt-2 grid gap-2 md:grid-cols-2">
                  {#each row.values as value}
                    <div
                      class="rounded-md border border-border/60 bg-background/70 p-2 text-xs"
                    >
                      <div
                        class="uppercase tracking-wide text-muted-foreground"
                      >
                        {value.provider}
                      </div>
                      <div class="mt-1 text-foreground">
                        {value.value ?? "-"}
                      </div>
                    </div>
                  {/each}
                </div>
              </div>
            {/each}
          </div>
        {/if}

        {#if activeTab === "synchronization"}
          <div class="space-y-3 text-sm">
            <div class="rounded-xl border border-border/70 bg-muted/20 p-3">
              <div
                class="text-xs uppercase tracking-wide text-muted-foreground"
              >
                Preview Changes
              </div>
              <div class="mt-2 grid gap-2 md:grid-cols-2">
                {#each ["plex", "sonarr", "radarr", "overseerr", "local_database"] as system}
                  <div
                    class="rounded-md border border-border/60 bg-background/80 px-2 py-2 text-xs"
                  >
                    <div class="font-medium text-foreground">
                      Will update {system.replaceAll("_", " ")}
                    </div>
                    <div class="mt-1 text-muted-foreground">
                      {trustedProviders.some(
                        (provider) =>
                          provider.provider.toLowerCase() === system,
                      ) || system === "local_database"
                        ? "Pending changes in preview"
                        : "No mapped provider for this title"}
                    </div>
                  </div>
                {/each}
              </div>
              <div class="mt-3 flex flex-wrap gap-2">
                <button
                  class="rounded-md border border-border px-3 py-1 hover:bg-accent"
                  onclick={() => void approveSync()}
                  disabled={busy}>Approve</button
                >
                <button
                  class="rounded-md border border-border px-3 py-1 hover:bg-accent"
                  onclick={() => void rejectSync()}
                  disabled={busy}>Reject</button
                >
                <button
                  class="rounded-md bg-primary px-3 py-1 text-primary-foreground hover:opacity-90"
                  onclick={() => void runSync()}
                  disabled={busy || syncDecision === "rejected"}>Queue</button
                >
              </div>
              <div class="mt-2 text-xs text-muted-foreground">
                Decision: {syncDecision}
              </div>
            </div>

            <div class="grid gap-2 md:grid-cols-3">
              <label class="text-xs text-muted-foreground">
                Sync Behaviour
                <select
                  class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1"
                  bind:value={syncBehavior}
                >
                  <option value="merge">Merge</option>
                  <option value="replace">Replace</option>
                  <option value="artwork_only">Artwork Only</option>
                  <option value="metadata_only">Metadata Only</option>
                </select>
              </label>
              <label class="text-xs text-muted-foreground">
                Lock State
                <select
                  class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1"
                  bind:value={lockState}
                >
                  <option value="unlocked">Unlocked</option>
                  <option value="metadata_locked">Metadata Locked</option>
                  <option value="artwork_locked">Artwork Locked</option>
                  <option value="fully_locked">Fully Locked</option>
                </select>
              </label>
              <label class="text-xs text-muted-foreground">
                Notes
                <input
                  class="mt-1 w-full rounded-md border border-border bg-background px-2 py-1"
                  placeholder="Synchronization notes"
                  bind:value={notes}
                />
              </label>
            </div>

            {#each studio.synchronization as row}
              <div class="rounded-xl border border-border/70 p-3">
                <div class="text-xs text-muted-foreground">{row.label}</div>
                {#each row.values as value}
                  <div class="mt-1 text-sm text-foreground">
                    {value.provider}: {value.value ?? "-"}
                  </div>
                {/each}
              </div>
            {/each}
          </div>
        {/if}

        {#if activeTab === "diagnostics"}
          <div class="space-y-2 text-sm">
            <div class="rounded-xl border border-border/70 bg-muted/20 p-3">
              <div class="flex items-center justify-between gap-2">
                <div>
                  <div
                    class="text-xs uppercase tracking-wide text-muted-foreground"
                  >
                    Provider Trust
                  </div>
                  <div class="text-sm text-foreground">
                    Future decisions honor this order.
                  </div>
                </div>
                <button
                  class="rounded-md border border-border px-2 py-1 text-xs hover:bg-accent"
                  onclick={resetProviderTrustOrder}>Reset</button
                >
              </div>
              <div class="mt-2 space-y-1">
                {#each providerTrustOrder as provider, index}
                  <div
                    class="flex items-center justify-between rounded-md border border-border/60 bg-background/70 px-2 py-1 text-xs"
                  >
                    <span>{index + 1}. {provider}</span>
                    <span class="flex items-center gap-1">
                      <button
                        class="rounded border border-border px-1 hover:bg-accent"
                        onclick={() => moveProviderTrust(provider, "up")}
                        disabled={index === 0}>Up</button
                      >
                      <button
                        class="rounded border border-border px-1 hover:bg-accent"
                        onclick={() => moveProviderTrust(provider, "down")}
                        disabled={index === providerTrustOrder.length - 1}
                        >Down</button
                      >
                    </span>
                  </div>
                {/each}
              </div>
            </div>

            {#each studio.diagnostics as row}
              <div class="rounded-xl border border-border/70 p-3">
                <div class="text-xs text-muted-foreground">{row.label}</div>
                {#each row.values as value}
                  <div class="mt-1 text-sm text-foreground">
                    {value.provider}: {value.value ?? "-"}
                  </div>
                {/each}
              </div>
            {/each}
          </div>
        {/if}

        {#if activeTab === "overrides"}
          <div class="space-y-3 text-sm">
            <div
              class="grid gap-2 rounded-xl border border-border/70 bg-muted/20 p-3 md:grid-cols-2"
            >
              <input
                class="rounded-md border border-border bg-background px-3 py-2"
                placeholder="Field (artwork_profile, metadata_profile, tmdb_id, sync_behavior, lock_state...)"
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
              <input
                class="rounded-md border border-border bg-background px-3 py-2"
                placeholder="Notes"
                bind:value={notes}
              />
              <button
                class="rounded-md bg-primary px-3 py-2 text-primary-foreground hover:opacity-90 disabled:opacity-50 md:col-span-2"
                onclick={saveOverride}
                disabled={busy ||
                  !overrideField.trim() ||
                  !overrideValue.trim()}
              >
                Save Override
              </button>
            </div>

            <div class="overflow-x-auto rounded-xl border border-border/70">
              <table class="w-full text-left text-xs">
                <thead class="bg-muted/40 text-muted-foreground">
                  <tr>
                    <th class="px-3 py-2">Field</th>
                    <th class="px-3 py-2">Current Value</th>
                    <th class="px-3 py-2">Provider Value</th>
                    <th class="px-3 py-2">Override Value</th>
                    <th class="px-3 py-2">Source</th>
                    <th class="px-3 py-2">Validation</th>
                    <th class="px-3 py-2">Modified By</th>
                    <th class="px-3 py-2">Modified</th>
                  </tr>
                </thead>
                <tbody>
                  {#each [...studio.metadata, ...studio.external_ids].slice(0, 12) as row}
                    <tr class="border-t border-border/50">
                      <td class="px-3 py-2 font-medium text-foreground"
                        >{row.key}</td
                      >
                      <td class="px-3 py-2">{canonicalValue(row) ?? "-"}</td>
                      <td class="px-3 py-2"
                        >{providerValues(row)[0]?.value ?? "-"}</td
                      >
                      <td class="px-3 py-2">
                        {studio.overrides.find(
                          (override) => override.field === row.key,
                        )?.value ?? "-"}
                      </td>
                      <td class="px-3 py-2">
                        {studio.overrides.find(
                          (override) => override.field === row.key,
                        )
                          ? "manual"
                          : "provider"}
                      </td>
                      <td class="px-3 py-2">
                        {studio.overrides.find(
                          (override) => override.field === row.key,
                        )
                          ? "applied"
                          : "none"}
                      </td>
                      <td class="px-3 py-2">
                        {studio.overrides.find(
                          (override) => override.field === row.key,
                        )?.created_by_user_id ?? "-"}
                      </td>
                      <td class="px-3 py-2">
                        {studio.overrides.find(
                          (override) => override.field === row.key,
                        )?.created_at
                          ? new Date(
                              studio.overrides.find(
                                (override) => override.field === row.key,
                              )!.created_at,
                            ).toLocaleString()
                          : "-"}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
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
              <div class="flex gap-3">
                <div class="flex flex-col items-center">
                  <div class="mt-1 h-2 w-2 rounded-full bg-primary"></div>
                  <div class="h-full w-px bg-border"></div>
                </div>
                <div class="flex-1 rounded-md border border-border/70 p-2">
                  <div class="font-medium">{row.summary}</div>
                  <div class="text-xs text-muted-foreground">
                    {row.action} | {row.result} | {new Date(
                      row.created_at,
                    ).toLocaleString()}
                  </div>
                </div>
              </div>
            {/each}
            {#if studio.history.length === 0}
              <div class="text-sm text-muted-foreground">
                No identity actions yet.
              </div>
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
              {row.action} | {row.result} | {new Date(
                row.created_at,
              ).toLocaleString()}
            </div>
          </div>
        {/each}
      {:else}
        <div class="text-muted-foreground">No sync history entries yet.</div>
      {/if}
    </div>
  </section>
</div>
