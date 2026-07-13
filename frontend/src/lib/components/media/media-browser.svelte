<script lang="ts">
  import { onMount, onDestroy, untrack } from "svelte";
  import { get_api, post_api, put_api, delete_api } from "$lib/api";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import LayoutGrid from "@lucide/svelte/icons/layout-grid";
  import MediaGrid from "$lib/components/media/media-grid.svelte";
  import MediaDetailDialog from "$lib/components/media/media-detail-dialog.svelte";
  import DeleteRequestDialog from "$lib/components/media/delete-request-dialog.svelte";
  import ProtectionRequestDialog from "$lib/components/media/protection-request-dialog.svelte";
  import QueryFilterBuilder from "$lib/components/media/query-filter-builder.svelte";
  import Search from "@lucide/svelte/icons/search";
  import {
    ProtectionRequestStatus,
    type DecisionFilterUpsertRequest,
    type MediaFilterCatalogResponse,
    type QueryFilterDefinition,
    type QueryFilterResponse,
    type SmartFilterUpsertRequest,
    MediaType,
    type DeleteRequest,
    type ProtectionRequest,
    type MovieWithStatus,
    type SeriesWithStatus,
    type MediaItem,
    type PaginatedResponse,
  } from "$lib/types/shared";
  import { toast } from "svelte-sonner";
  import {
    createPerPageState,
    createFilterState,
    PER_PAGE_OPTIONS,
  } from "$lib/utils/pagination";

  const sortByOptions = [
    { value: "title", label: "Title" },
    { value: "year", label: "Year" },
    { value: "added_at", label: "Media Server Added" },
    { value: "arr_added_at", label: "Latest Arr File Added" },
    { value: "size", label: "Size" },
    { value: "vote_average", label: "Rating" },
  ];

  interface Props {
    mediaType: MediaType;
  }
  let { mediaType }: Props = $props();

  // mediaType is fixed at the call site (movies.svelte / series.svelte) and
  // never changes, so capturing it once with untrack is intentional.
  const _prefix = untrack(() =>
    mediaType === MediaType.Movie ? "movies" : "series",
  );
  const _perPageStore = createPerPageState(`${_prefix}_per_page`);
  let perPage = $state(_perPageStore.getInitial());

  const _sortByStore = createFilterState(`${_prefix}_sort_by`, "title");
  const _sortOrderStore = createFilterState(`${_prefix}_sort_order`, "asc");
  const _candidatesOnlyStore = createFilterState(
    `${_prefix}_candidates_only`,
    false,
  );
  const _importedFilterStore = createFilterState<number[]>(
    `${_prefix}_imported_filter_ids`,
    [],
  );
  const _decisionFilterStore = createFilterState<number[]>(
    `${_prefix}_decision_filter_ids`,
    [],
  );
  const _smartFilterStore = createFilterState<number[]>(
    `${_prefix}_smart_filter_ids`,
    [],
  );

  let loading = $state(true);
  let error = $state("");
  let mediaData = $state<PaginatedResponse<
    MovieWithStatus | SeriesWithStatus
  > | null>(null);
  let filterCatalog = $state<MediaFilterCatalogResponse | null>(null);

  // filters and search
  let searchQuery = $state("");
  let sortBy = $state(_sortByStore.getInitial());
  let sortOrder = $state(_sortOrderStore.getInitial());
  let candidatesOnly = $state(_candidatesOnlyStore.getInitial());
  let importedFilterIds = $state<number[]>(_importedFilterStore.getInitial());
  let decisionFilterIds = $state<number[]>(_decisionFilterStore.getInitial());
  let smartFilterIds = $state<number[]>(_smartFilterStore.getInitial());
  let filterSearch = $state("");
  let filterBuilderName = $state("");
  let filterBuilderDefinition = $state<QueryFilterDefinition>({
    type: "group",
    combinator: "and",
    clauses: [
      {
        type: "condition",
        field: "decision.state",
        operator: "equals",
        value: "safe_to_delete",
      },
    ],
  });
  let smartFilterName = $state("");
  let editingDecisionFilterId = $state<number | null>(null);
  let editingSmartFilterId = $state<number | null>(null);
  let collapsedImportedGroups = $state<Record<string, boolean>>({});
  let showSmartFilterDialog = $state(false);
  let currentPage = $state(1);
  let pendingOpenMediaId = $state<number | null>(null);

  // poster size control
  const POSTER_SIZE_KEY = "mediamasterr_poster_size";
  const LEGACY_POSTER_SIZE_KEY = "reclaimerr_poster_size";
  let storedPosterSize = localStorage.getItem(POSTER_SIZE_KEY);
  if (!storedPosterSize) {
    const legacyPosterSize = localStorage.getItem(LEGACY_POSTER_SIZE_KEY);
    if (legacyPosterSize) {
      localStorage.setItem(POSTER_SIZE_KEY, legacyPosterSize);
      localStorage.removeItem(LEGACY_POSTER_SIZE_KEY);
      storedPosterSize = legacyPosterSize;
    }
  }
  let posterSize = $state(
    parseInt(storedPosterSize ?? "150"),
  );
  $effect(() => {
    localStorage.setItem(POSTER_SIZE_KEY, posterSize.toString());
  });

  // dialogs
  let showDetailDialog = $state(false);
  let showExceptionDialog = $state(false);
  let showDeleteDialog = $state(false);
  let showFilterManager = $state(false);
  let filterManagerMode = $state<"arr" | "decision">("arr");
  let selectedMedia = $state<MediaItem | null>(null);

  // debounce timer for search
  let searchTimer: ReturnType<typeof setTimeout> | null = null;

  // abort control for API requests
  let abortController: AbortController | null = null;

  // keep track to see if component has mounted to avoid race conditions in
  // the $effect for sort filters
  let mounted = $state(false);

  // computed values based on mediaType
  const isMovie = $derived(mediaType === MediaType.Movie);
  const apiEndpoint = $derived(
    isMovie ? "/api/media/movies" : "/api/media/series",
  );
  const title = $derived(isMovie ? "Movies" : "Series");
  const description = $derived(
    isMovie
      ? "Browse and manage your movie library"
      : "Browse and manage your TV series library",
  );
  const searchPlaceholder = $derived(
    isMovie ? "Search movies..." : "Search series...",
  );

  $effect(() => _sortByStore.save(sortBy));
  $effect(() => _sortOrderStore.save(sortOrder));
  $effect(() => _candidatesOnlyStore.save(candidatesOnly));
  $effect(() => _importedFilterStore.save(importedFilterIds));
  $effect(() => _decisionFilterStore.save(decisionFilterIds));
  $effect(() => _smartFilterStore.save(smartFilterIds));

  // watch for changes in sortBy, sortOrder, candidatesOnly, and perPage to reload
  $effect(() => {
    sortBy;
    sortOrder;
    candidatesOnly;
    perPage;
    importedFilterIds;
    decisionFilterIds;
    smartFilterIds;
    if (mounted) {
      loadMedia(1);
    }
  });

  $effect(() => {
    if (!pendingOpenMediaId || !mediaData) return;
    const match = mediaData.items.find((item) => item.id === pendingOpenMediaId);
    if (match) {
      selectedMedia = match;
      showDetailDialog = true;
      pendingOpenMediaId = null;
    }
  });

  const loadFilterCatalog = async () => {
    try {
      filterCatalog = await get_api<MediaFilterCatalogResponse>(
        `/api/media/filters?media_type=${mediaType}`,
      );
    } catch {
      filterCatalog = null;
    }
  };

  // load media from API with filters and pagination
  const loadMedia = async (page: number = currentPage) => {
    if (abortController) abortController.abort();
    abortController = new AbortController();
    const signal = abortController.signal;

    loading = true;
    error = "";
    currentPage = page;

    try {
      const params = new URLSearchParams({
        page: page.toString(),
        per_page: perPage.toString(),
        sort_by: sortBy,
        sort_order: sortOrder,
      });

      if (searchQuery.trim()) {
        params.append("search", searchQuery.trim());
      }

      if (candidatesOnly) {
        params.append("candidates_only", "true");
      }
      for (const id of importedFilterIds) {
        params.append("arr_filter_ids", id.toString());
      }
      for (const id of decisionFilterIds) {
        params.append("decision_filter_ids", id.toString());
      }
      for (const id of smartFilterIds) {
        params.append("smart_filter_ids", id.toString());
      }

      const data = await get_api<
        PaginatedResponse<MovieWithStatus | SeriesWithStatus>
      >(`${apiEndpoint}?${params.toString()}`, signal);

      // only update state if this request was not aborted
      if (!signal.aborted) {
        mediaData = data;
      }
    } catch (err: any) {
      // ignore abort errors, they are expected
      if (err instanceof DOMException && err.name === "AbortError") return;
      // log and show other errors
      console.error(`Error loading ${title.toLowerCase()}:`, err);
      error = err.message;
      toast.error(`Failed to load ${title.toLowerCase()}: ${err.message}`);
    } finally {
      // only stop loading if this request was not aborted
      if (!signal.aborted) {
        loading = false;
      }
    }
  };

  // handle search input with debounce
  const handleSearch = (event: Event) => {
    const target = event.target as HTMLInputElement;
    searchQuery = target.value;

    // debounce search
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      currentPage = 1;
      loadMedia(1);
    }, 500);
  };

  // when user changes page
  const handlePageChange = (page: number) => {
    currentPage = page;
    loadMedia(page);
  };

  const toggleFilterSelection = (
    source: "imported" | "decision" | "smart",
    filterId: number,
  ) => {
    const mutate = (values: number[]) =>
      values.includes(filterId)
        ? values.filter((id) => id !== filterId)
        : [...values, filterId];
    if (source === "imported") importedFilterIds = mutate(importedFilterIds);
    else if (source === "decision") decisionFilterIds = mutate(decisionFilterIds);
    else smartFilterIds = mutate(smartFilterIds);
  };

  const clearAllFilters = () => {
    importedFilterIds = [];
    decisionFilterIds = [];
    smartFilterIds = [];
  };

  const selectedFilterOptions = $derived.by(() => {
    const all = [
      ...(filterCatalog?.imported ?? []),
      ...(filterCatalog?.native ?? []),
      ...(filterCatalog?.smart ?? []),
    ];
    const selectedIds = new Set([
      ...importedFilterIds,
      ...decisionFilterIds,
      ...smartFilterIds,
    ]);
    return all.filter((option) => {
      const id = option.filter_id;
      return typeof id === "number" && selectedIds.has(id);
    });
  });

  const saveDecisionFilter = async () => {
    const payload: DecisionFilterUpsertRequest = {
      name: filterBuilderName.trim() || "Decision Filter",
      media_type: mediaType,
      definition: filterBuilderDefinition,
    };
    try {
      if (editingDecisionFilterId) {
        await put_api<QueryFilterResponse>(
          `/api/media/query/decision-filters/${editingDecisionFilterId}`,
          payload,
        );
      } else {
        await post_api<QueryFilterResponse>(
          "/api/media/query/decision-filters",
          payload,
        );
      }
      editingDecisionFilterId = null;
      filterBuilderName = "";
      showFilterManager = false;
      await loadFilterCatalog();
    } catch (e: any) {
      toast.error(e?.message ?? "Failed to save decision filter");
    }
  };

  const defaultDecisionDefinition = (): QueryFilterDefinition => ({
    type: "group",
    combinator: "and",
    clauses: [
      {
        type: "condition",
        field: "decision.state",
        operator: "equals",
        value: "safe_to_delete",
      },
    ],
  });

  const openDecisionFilterEditor = (
    option?: NonNullable<MediaFilterCatalogResponse["native"][number]>,
  ) => {
    editingDecisionFilterId = option?.filter_id ?? null;
    filterBuilderName = option?.label ?? "";
    const definition = option?.definition as QueryFilterDefinition | null;
    filterBuilderDefinition = definition ?? defaultDecisionDefinition();
    filterManagerMode = "decision";
    showFilterManager = true;
  };

  const saveSmartFilter = async () => {
    const payload: SmartFilterUpsertRequest = {
      name: smartFilterName.trim() || "Smart Filter",
      media_type: mediaType,
      arr_filter_ids: importedFilterIds,
      decision_filter_ids: decisionFilterIds,
      search: searchQuery.trim() || null,
      candidates_only: candidatesOnly,
      sort_by: sortBy,
      sort_order: sortOrder as "asc" | "desc",
      per_page: perPage,
      poster_size: posterSize,
      view_mode: "grid",
      page: currentPage,
    };
    try {
      if (editingSmartFilterId) {
        await put_api<QueryFilterResponse>(
          `/api/media/query/smart-filters/${editingSmartFilterId}`,
          payload,
        );
      } else {
        await post_api<QueryFilterResponse>("/api/media/query/smart-filters", payload);
      }
      editingSmartFilterId = null;
      smartFilterName = "";
      showSmartFilterDialog = false;
      await loadFilterCatalog();
    } catch (e: any) {
      toast.error(e?.message ?? "Failed to save smart filter");
    }
  };

  const openSmartFilterDialog = () => {
    editingSmartFilterId = null;
    smartFilterName = "";
    showSmartFilterDialog = true;
  };

  const filteredImportedOptions = $derived.by(() => {
    const q = filterSearch.trim().toLowerCase();
    const options = filterCatalog?.imported ?? [];
    if (!q) return options;
    return options.filter((option) => option.label.toLowerCase().includes(q));
  });

  const groupedImportedOptions = $derived.by(() => {
    const grouped = new Map<string, typeof filteredImportedOptions>();
    for (const option of filteredImportedOptions) {
      const group = option.group || "Imported";
      const bucket = grouped.get(group) ?? [];
      bucket.push(option);
      grouped.set(group, bucket);
    }
    return Array.from(grouped.entries()).map(([group, options]) => ({
      group,
      options,
    }));
  });

  const editDecisionFilter = (option: NonNullable<MediaFilterCatalogResponse["native"][number]>) => {
    openDecisionFilterEditor(option);
  };

  const deleteDecisionFilter = async (filterId: number) => {
    try {
      await delete_api(`/api/media/query/decision-filters/${filterId}`);
      decisionFilterIds = decisionFilterIds.filter((id) => id !== filterId);
      if (editingDecisionFilterId === filterId) editingDecisionFilterId = null;
      await loadFilterCatalog();
    } catch (e: any) {
      toast.error(e?.message ?? "Failed to delete decision filter");
    }
  };

  const editSmartFilter = (option: NonNullable<MediaFilterCatalogResponse["smart"][number]>) => {
    if (!option.filter_id) return;
    editingSmartFilterId = option.filter_id;
    smartFilterName = option.label;
    const definition = option.definition as {
      arr_filter_ids?: number[];
      decision_filter_ids?: number[];
      search?: string | null;
      candidates_only?: boolean;
      sort_by?: string;
      sort_order?: "asc" | "desc";
      per_page?: number;
      poster_size?: number;
      view_mode?: string;
      page?: number;
    } | null;
    importedFilterIds = definition?.arr_filter_ids ?? [];
    decisionFilterIds = definition?.decision_filter_ids ?? [];
    searchQuery = definition?.search ?? "";
    candidatesOnly = Boolean(definition?.candidates_only);
    sortBy = definition?.sort_by ?? sortBy;
    sortOrder = definition?.sort_order ?? sortOrder;
    perPage = definition?.per_page ?? perPage;
    posterSize = definition?.poster_size ?? posterSize;
    currentPage = definition?.page ?? currentPage;
    showSmartFilterDialog = true;
    loadMedia(currentPage);
  };

  const openFilterManager = (mode: "arr" | "decision") => {
    filterManagerMode = mode;
    showFilterManager = true;
  };

  const applySmartFilter = (option: NonNullable<MediaFilterCatalogResponse["smart"][number]>) => {
    const definition = option.definition as {
      arr_filter_ids?: number[];
      decision_filter_ids?: number[];
      search?: string | null;
      candidates_only?: boolean;
      sort_by?: string;
      sort_order?: "asc" | "desc";
      per_page?: number;
      poster_size?: number;
      view_mode?: string;
      page?: number;
    } | null;
    importedFilterIds = definition?.arr_filter_ids ?? [];
    decisionFilterIds = definition?.decision_filter_ids ?? [];
    searchQuery = definition?.search ?? "";
    candidatesOnly = Boolean(definition?.candidates_only);
    sortBy = definition?.sort_by ?? sortBy;
    sortOrder = definition?.sort_order ?? sortOrder;
    perPage = definition?.per_page ?? perPage;
    posterSize = definition?.poster_size ?? posterSize;
    currentPage = definition?.page ?? currentPage;
    loadMedia(currentPage);
  };

  const deleteSmartFilter = async (filterId: number) => {
    try {
      await delete_api(`/api/media/query/smart-filters/${filterId}`);
      smartFilterIds = smartFilterIds.filter((id) => id !== filterId);
      if (editingSmartFilterId === filterId) editingSmartFilterId = null;
      await loadFilterCatalog();
    } catch (e: any) {
      toast.error(e?.message ?? "Failed to delete smart filter");
    }
  };

  // when user clicks on a media card to view details
  const handleViewDetails = (media: MediaItem) => {
    selectedMedia = media;
    showDetailDialog = true;
  };

  // when user clicks "Request Exception" from either media card or detail dialog
  const handleRequestException = (media: MediaItem) => {
    selectedMedia = media;
    showExceptionDialog = true;
  };

  // when user clicks "Request Delete" from either media card or detail dialog
  const handleRequestDelete = (media: MediaItem) => {
    selectedMedia = media;
    showDeleteDialog = true;
  };

  // helper: update the matching item's status and selectedMedia consistently
  const upsertStatus = (
    media_id: number,
    patchFn: (oldStatus: any) => Partial<any>,
  ) => {
    if (!mediaData) return;

    mediaData = {
      ...mediaData,
      items: mediaData.items.map((item) =>
        item.id !== media_id
          ? item
          : { ...item, status: { ...item.status, ...patchFn(item.status) } },
      ),
    };

    if (selectedMedia && selectedMedia.id === media_id) {
      selectedMedia = {
        ...selectedMedia,
        status: { ...selectedMedia.status, ...patchFn(selectedMedia.status) },
      };
    }
  };

  // after successful exception request, update only the requested media card in local state
  const handleExceptionSuccess = (request: ProtectionRequest) => {
    const isWholeScope =
      request.media_type === MediaType.Movie
        ? request.movie_version_id == null
        : request.season_id == null && request.episode_id == null;
    if (!isWholeScope) return;

    const isPending = request.status === ProtectionRequestStatus.Pending;
    const isApproved = request.status === ProtectionRequestStatus.Approved;

    upsertStatus(request.media_id, (old) => ({
      has_pending_request: isPending,
      request_id: isPending ? request.id : null,
      request_status: request.status,
      request_reason: request.reason,
      is_protected: isApproved ? true : old.is_protected,
    }));
  };

  // after successful delete request, update only the requested media card in local state
  const handleDeleteSuccess = (request: DeleteRequest) => {
    const isWholeScope =
      request.media_type === MediaType.Movie
        ? request.movie_version_id == null
        : request.season_id == null && request.episode_id == null;
    if (!isWholeScope) return;

    upsertStatus(request.media_id, () => ({
      has_pending_delete_request: true,
      delete_request_id: request.id,
      delete_request_status: request.status,
      delete_request_reason: request.reason,
    }));
  };

  // initial load
  onMount(() => {
    const hashQuery = window.location.hash.split("?")[1] ?? "";
    const searchParams = new URLSearchParams(hashQuery);
    const initialSearch = searchParams.get("search");
    const initialOpen = searchParams.get("open");
    const inspectorRequested = searchParams.get("inspector") === "1";
    if (initialSearch) {
      searchQuery = initialSearch;
    }
    if (initialOpen && inspectorRequested) {
      const parsedId = parseInt(initialOpen, 10);
      pendingOpenMediaId = Number.isNaN(parsedId) ? null : parsedId;
    }
    mounted = true;
    void loadFilterCatalog();
    loadMedia(currentPage);
  });

  // cleanup on unmount
  onDestroy(() => {
    if (searchTimer) clearTimeout(searchTimer);
    if (abortController) abortController.abort();
  });
</script>

<div class="p-2.5 md:p-8">
  <div class="max-w-7xl mx-auto space-y-4">
    <!-- header -->
    <div>
      <h1 class="text-3xl font-bold text-foreground">{title}</h1>
      <p class="text-muted-foreground">{description}</p>
    </div>

    <!-- filters and search -->
    <div class="space-y-3 rounded-2xl border border-border bg-card/70 p-3 md:p-4">
      <div class="grid gap-3 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div class="space-y-3">
          <div class="flex flex-col gap-2 lg:flex-row">
            <div class="relative flex-1">
              <Search class="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                type="text"
                placeholder={searchPlaceholder}
                value={searchQuery}
                oninput={handleSearch}
                class="pl-10 bg-background text-card-foreground placeholder:text-muted-foreground"
              />
            </div>

            <div class="flex gap-2">
              <Select.Root type="single" bind:value={sortBy}>
                <Select.Trigger class="min-w-40 bg-background text-card-foreground">
                  {sortByOptions.find((opt) => opt.value === sortBy)?.label}
                </Select.Trigger>
                <Select.Content class="bg-card">
                  {#each sortByOptions as option}
                    <Select.Item value={option.value} label={option.label} class="text-card-foreground">
                      {option.label}
                    </Select.Item>
                  {/each}
                </Select.Content>
              </Select.Root>

              <Select.Root type="single" bind:value={sortOrder}>
                <Select.Trigger class="min-w-32 bg-background text-card-foreground">
                  {sortOrder === "asc" ? "Ascending" : "Descending"}
                </Select.Trigger>
                <Select.Content class="bg-card">
                  <Select.Item value="asc" label="Ascending" class="text-card-foreground">Ascending</Select.Item>
                  <Select.Item value="desc" label="Descending" class="text-card-foreground">Descending</Select.Item>
                </Select.Content>
              </Select.Root>
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-3">
            <label class="flex items-center gap-2 rounded-full border border-border/70 bg-background px-3 py-2 cursor-pointer">
              <Switch bind:checked={candidatesOnly} class="cursor-pointer" />
              <span class="text-sm text-muted-foreground">Reclaim candidates only</span>
            </label>

            <div class="flex flex-wrap gap-2">
              <DropdownMenu.Root>
                <DropdownMenu.Trigger>
                  {#snippet child({ props })}
                    <button {...props} type="button" class="rounded-full border border-border px-3 py-2 text-sm text-foreground hover:bg-secondary/50 cursor-pointer">
                      ARR Filters
                    </button>
                  {/snippet}
                </DropdownMenu.Trigger>
                <DropdownMenu.Content align="start" class="w-72">
                  <DropdownMenu.Label>Imported filters</DropdownMenu.Label>
                  <DropdownMenu.Separator />
                  <DropdownMenu.Item onSelect={(event) => { event.preventDefault(); openFilterManager("arr"); }}>
                    Manage filters...
                  </DropdownMenu.Item>
                  <DropdownMenu.Separator />
                  {#each filterCatalog?.imported ?? [] as option}
                    {#if option.filter_id}
                      <DropdownMenu.Item onSelect={(event) => { event.preventDefault(); toggleFilterSelection("imported", option.filter_id!); }}>
                        {option.label}
                        {#if importedFilterIds.includes(option.filter_id)}
                          <span class="ml-auto text-xs text-primary">On</span>
                        {/if}
                      </DropdownMenu.Item>
                    {/if}
                  {/each}
                </DropdownMenu.Content>
              </DropdownMenu.Root>

              <DropdownMenu.Root>
                <DropdownMenu.Trigger>
                  {#snippet child({ props })}
                    <button {...props} type="button" class="rounded-full border border-border px-3 py-2 text-sm text-foreground hover:bg-secondary/50 cursor-pointer">
                      Decision Filters
                    </button>
                  {/snippet}
                </DropdownMenu.Trigger>
                <DropdownMenu.Content align="start" class="w-72">
                  <DropdownMenu.Label>Decision filters</DropdownMenu.Label>
                  <DropdownMenu.Separator />
                  <DropdownMenu.Item onSelect={(event) => { event.preventDefault(); openFilterManager("decision"); }}>
                    Manage decision filters...
                  </DropdownMenu.Item>
                  <DropdownMenu.Separator />
                  {#each filterCatalog?.native ?? [] as option}
                    {#if option.filter_id}
                      <DropdownMenu.Item onSelect={(event) => { event.preventDefault(); toggleFilterSelection("decision", option.filter_id!); }}>
                        {option.label}
                        {#if decisionFilterIds.includes(option.filter_id)}
                          <span class="ml-auto text-xs text-primary">On</span>
                        {/if}
                      </DropdownMenu.Item>
                    {/if}
                  {/each}
                </DropdownMenu.Content>
              </DropdownMenu.Root>

              <DropdownMenu.Root>
                <DropdownMenu.Trigger>
                  {#snippet child({ props })}
                    <button {...props} type="button" class="rounded-full border border-border px-3 py-2 text-sm text-foreground hover:bg-secondary/50 cursor-pointer">
                      Smart Filters
                    </button>
                  {/snippet}
                </DropdownMenu.Trigger>
                <DropdownMenu.Content align="start" class="w-80">
                  <DropdownMenu.Label>Smart filters</DropdownMenu.Label>
                  <DropdownMenu.Separator />
                  <DropdownMenu.Item onSelect={(event) => { event.preventDefault(); openSmartFilterDialog(); }}>
                    Save current view...
                  </DropdownMenu.Item>
                  <DropdownMenu.Separator />
                  {#each filterCatalog?.smart ?? [] as option}
                    {#if option.filter_id}
                      <DropdownMenu.Item onSelect={(event) => { event.preventDefault(); applySmartFilter(option); }}>
                        {option.label}
                      </DropdownMenu.Item>
                    {/if}
                  {/each}
                </DropdownMenu.Content>
              </DropdownMenu.Root>
            </div>
          </div>

          {#if selectedFilterOptions.length > 0}
            <div class="flex flex-wrap gap-2">
              {#each selectedFilterOptions as filter}
                {#if filter.filter_id}
                  <button
                    type="button"
                    class="rounded-full border border-border/70 px-3 py-1 text-xs text-foreground hover:bg-secondary/50 cursor-pointer"
                    onclick={() => {
                      if (filter.kind === "imported_arr") toggleFilterSelection("imported", filter.filter_id!);
                      else if (filter.kind === "smart") toggleFilterSelection("smart", filter.filter_id!);
                      else toggleFilterSelection("decision", filter.filter_id!);
                    }}
                  >
                    {filter.label}
                  </button>
                {/if}
              {/each}
              <button type="button" class="text-xs text-muted-foreground hover:text-foreground cursor-pointer" onclick={clearAllFilters}>
                Clear all
              </button>
            </div>
          {/if}
        </div>

        <div class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
          <Select.Root type="single" value={perPage.toString()} onValueChange={(v) => { const n = parseInt(v); perPage = n; _perPageStore.save(n); }}>
            <Select.Trigger class="bg-background text-card-foreground">
              {perPage} / page
            </Select.Trigger>
            <Select.Content class="bg-card">
              {#each PER_PAGE_OPTIONS as option}
                <Select.Item value={option.toString()} label={option.toString()} class="text-card-foreground">
                  {option}
                </Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>

          <label class="flex items-center gap-2 rounded-xl border border-border/70 bg-background px-3 py-2">
            <LayoutGrid class="size-4 shrink-0 text-muted-foreground" />
            <input type="range" min="100" max="300" step="10" bind:value={posterSize} class="w-28 accent-primary cursor-pointer" />
          </label>
        </div>
      </div>
    </div>

    <!-- media grid -->
    <MediaGrid
      data={mediaData}
      {mediaType}
      {loading}
      {error}
      {posterSize}
      onViewDetails={handleViewDetails}
      onRequestException={handleRequestException}
      onRequestDelete={handleRequestDelete}
      onPageChange={handlePageChange}
    />
  </div>
</div>

<Dialog.Root bind:open={showFilterManager}>
  <Dialog.Content class="flex max-h-[90vh] flex-col sm:max-w-4xl border-ring border-2">
    <Dialog.Header>
      <Dialog.Title>
        {filterManagerMode === "arr" ? "Manage ARR Filters" : "Manage Decision Filters"}
      </Dialog.Title>
      <Dialog.Description>
        {filterManagerMode === "arr"
          ? "Choose imported ARR filters to combine with the current view."
          : "Build and manage recursive decision filters."}
      </Dialog.Description>
    </Dialog.Header>

    <div class="flex-1 space-y-4 overflow-y-auto px-4 py-4">
      {#if filterManagerMode === "arr"}
        <div class="flex items-center justify-between gap-2">
          <Input
            type="text"
            placeholder="Search filters"
            value={filterSearch}
            oninput={(event) => (filterSearch = (event.target as HTMLInputElement).value)}
            class="bg-background"
          />
          <div class="flex gap-2 text-xs">
            <button type="button" class="rounded border border-border px-2 py-1 cursor-pointer" onclick={() => (importedFilterIds = (filterCatalog?.imported ?? []).map((filter) => filter.filter_id ?? -1).filter((id) => id > 0))}>
              Select all
            </button>
            <button type="button" class="rounded border border-border px-2 py-1 cursor-pointer" onclick={() => (importedFilterIds = [])}>
              Clear
            </button>
          </div>
        </div>

        <div class="space-y-3">
          {#each groupedImportedOptions as importedGroup}
            <div class="rounded-xl border border-border/70 bg-card/60 p-3">
              <button type="button" class="mb-3 flex w-full items-center justify-between text-left text-sm font-medium text-card-foreground" onclick={() => (collapsedImportedGroups = { ...collapsedImportedGroups, [importedGroup.group]: !collapsedImportedGroups[importedGroup.group] })}>
                <span>{importedGroup.group}</span>
                <span class="text-xs text-muted-foreground">{collapsedImportedGroups[importedGroup.group] ? "Show" : "Hide"}</span>
              </button>
              {#if !collapsedImportedGroups[importedGroup.group]}
                <div class="grid gap-2 sm:grid-cols-2">
                  {#each importedGroup.options as option}
                    {#if option.filter_id}
                      <label class="flex items-center gap-2 rounded-lg border border-border/60 px-3 py-2 text-sm text-card-foreground">
                        <input type="checkbox" checked={importedFilterIds.includes(option.filter_id)} onchange={() => toggleFilterSelection("imported", option.filter_id!)} />
                        <span>{option.label}</span>
                      </label>
                    {/if}
                  {/each}
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {:else}
        <div class="space-y-3">
          <div class="flex flex-wrap items-center gap-2">
            <Input
              type="text"
              placeholder="Filter name"
              value={filterBuilderName}
              oninput={(event) => (filterBuilderName = (event.target as HTMLInputElement).value)}
              class="min-w-64 flex-1 bg-background"
            />
            <button type="button" class="rounded border border-border px-3 py-2 text-sm cursor-pointer" onclick={() => openDecisionFilterEditor()}>
              New filter
            </button>
          </div>

          <QueryFilterBuilder bind:node={filterBuilderDefinition} />

          <div class="flex flex-wrap justify-end gap-2">
            <button type="button" class="rounded border border-border px-3 py-2 text-sm cursor-pointer" onclick={() => (filterBuilderDefinition = defaultDecisionDefinition())}>
              Reset builder
            </button>
            <button type="button" class="rounded bg-primary px-3 py-2 text-sm text-primary-foreground cursor-pointer" onclick={saveDecisionFilter}>
              Save decision filter
            </button>
          </div>

          <div class="space-y-2">
            <p class="text-sm font-medium text-card-foreground">Saved decision filters</p>
            <div class="grid gap-2">
              {#each filterCatalog?.native ?? [] as option}
                {#if option.filter_id}
                  <div class="flex items-center justify-between gap-3 rounded-lg border border-border/60 px-3 py-2 text-sm">
                    <button type="button" class="flex-1 text-left text-card-foreground" onclick={() => editDecisionFilter(option)}>
                      {option.label}
                    </button>
                    <button type="button" class="text-xs text-muted-foreground hover:text-foreground cursor-pointer" onclick={() => deleteDecisionFilter(option.filter_id!)}>
                      Delete
                    </button>
                  </div>
                {/if}
              {/each}
            </div>
          </div>
        </div>
      {/if}
    </div>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:open={showSmartFilterDialog}>
  <Dialog.Content class="flex max-h-[90vh] flex-col sm:max-w-3xl border-ring border-2">
    <Dialog.Header>
      <Dialog.Title>Save Smart Filter</Dialog.Title>
      <Dialog.Description>
        Save the current search, filter, sort, poster size, and pagination state for quick reuse.
      </Dialog.Description>
    </Dialog.Header>

    <div class="flex-1 space-y-4 overflow-y-auto px-4 py-4">
      <Input
        type="text"
        placeholder="Smart filter name"
        value={smartFilterName}
        oninput={(event) => (smartFilterName = (event.target as HTMLInputElement).value)}
        class="bg-background"
      />

      <div class="grid gap-2 rounded-xl border border-border/70 bg-card/60 p-3 text-sm text-muted-foreground">
        <div>Search: {searchQuery.trim() || "None"}</div>
        <div>Sort: {sortBy} / {sortOrder}</div>
        <div>Page size: {perPage}</div>
        <div>Poster size: {posterSize}</div>
        <div>Candidates only: {candidatesOnly ? "Yes" : "No"}</div>
      </div>

      <div class="space-y-2">
        <p class="text-sm font-medium text-card-foreground">Existing smart filters</p>
        <div class="grid gap-2">
          {#each filterCatalog?.smart ?? [] as option}
            {#if option.filter_id}
              <div class="flex items-center justify-between gap-3 rounded-lg border border-border/60 px-3 py-2 text-sm">
                <button type="button" class="flex-1 text-left text-card-foreground" onclick={() => applySmartFilter(option)}>
                  {option.label}
                </button>
                <div class="flex gap-2">
                  <button type="button" class="text-xs text-muted-foreground hover:text-foreground cursor-pointer" onclick={() => editSmartFilter(option)}>
                    Edit
                  </button>
                  <button type="button" class="text-xs text-muted-foreground hover:text-foreground cursor-pointer" onclick={() => deleteSmartFilter(option.filter_id!)}>
                    Delete
                  </button>
                </div>
              </div>
            {/if}
          {/each}
        </div>
      </div>
    </div>

    <Dialog.Footer class="px-4 pb-4">
      <button type="button" class="rounded border border-border px-3 py-2 text-sm cursor-pointer" onclick={() => (showSmartFilterDialog = false)}>
        Cancel
      </button>
      <button type="button" class="rounded bg-primary px-3 py-2 text-sm text-primary-foreground cursor-pointer" onclick={saveSmartFilter}>
        Save smart filter
      </button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<!-- dialogs -->
<MediaDetailDialog
  bind:open={showDetailDialog}
  media={selectedMedia}
  {mediaType}
  onRequestException={handleRequestException}
  onRequestDelete={handleRequestDelete}
/>

<ProtectionRequestDialog
  bind:open={showExceptionDialog}
  media={selectedMedia}
  {mediaType}
  onSuccess={handleExceptionSuccess}
/>

<DeleteRequestDialog
  bind:open={showDeleteDialog}
  media={selectedMedia}
  {mediaType}
  onSuccess={handleDeleteSuccess}
/>
