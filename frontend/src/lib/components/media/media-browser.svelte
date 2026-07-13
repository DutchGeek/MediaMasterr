<script lang="ts">
  import { onMount, onDestroy, untrack } from "svelte";
  import { get_api } from "$lib/api";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import LayoutGrid from "@lucide/svelte/icons/layout-grid";
  import MediaGrid from "$lib/components/media/media-grid.svelte";
  import MediaDetailDialog from "$lib/components/media/media-detail-dialog.svelte";
  import DeleteRequestDialog from "$lib/components/media/delete-request-dialog.svelte";
  import ProtectionRequestDialog from "$lib/components/media/protection-request-dialog.svelte";
  import Search from "@lucide/svelte/icons/search";
  import {
    ProtectionRequestStatus,
    type MediaFilterCatalogResponse,
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
  const ALL_IMPORTED_FILTERS = "__all_imported__";
  const ALL_DECISION_FILTERS = "__all_decisions__";
  const _importedFilterStore = createFilterState<string>(
    `${_prefix}_imported_filter`,
    ALL_IMPORTED_FILTERS,
  );
  const _decisionFilterStore = createFilterState<string>(
    `${_prefix}_decision_filter`,
    ALL_DECISION_FILTERS,
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
  let importedFilter = $state(_importedFilterStore.getInitial());
  let decisionFilter = $state(_decisionFilterStore.getInitial());
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
  $effect(() => _importedFilterStore.save(importedFilter));
  $effect(() => _decisionFilterStore.save(decisionFilter));

  // watch for changes in sortBy, sortOrder, candidatesOnly, and perPage to reload
  $effect(() => {
    sortBy;
    sortOrder;
    candidatesOnly;
    perPage;
    importedFilter;
    decisionFilter;
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
      if (importedFilter && importedFilter !== ALL_IMPORTED_FILTERS) {
        params.append("arr_tag", importedFilter);
      }
      if (decisionFilter && decisionFilter !== ALL_DECISION_FILTERS) {
        params.append("decision_state", decisionFilter);
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
    <div class="mb-6 flex flex-col gap-2">
      <div class="flex flex-col sm:flex-row gap-2">
        <!-- search -->
        <div class="relative flex-1">
          <Search
            class="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-muted-foreground"
          />
          <Input
            type="text"
            placeholder={searchPlaceholder}
            value={searchQuery}
            oninput={handleSearch}
            class="pl-10 bg-card text-card-foreground placeholder:text-muted-foreground"
          />
        </div>

        <!-- sort by -->
        <div class="flex flex-1 flex-row gap-2">
          <Select.Root type="single" bind:value={sortBy}>
            <Select.Trigger class="flex-10 bg-card text-card-foreground">
              {sortByOptions.find((opt) => opt.value === sortBy)?.label}
            </Select.Trigger>
            <Select.Content class="bg-card">
              {#each sortByOptions as option}
                <Select.Item
                  value={option.value}
                  label={option.label}
                  class="text-card-foreground"
                >
                  {option.label}
                </Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>

          <!-- sort order -->
          <Select.Root type="single" bind:value={sortOrder}>
            <Select.Trigger class="flex-10 bg-card text-card-foreground">
              {sortOrder === "asc" ? "Ascending" : "Descending"}
            </Select.Trigger>
            <Select.Content class="bg-card">
              <Select.Item
                value="asc"
                label="Ascending"
                class="text-card-foreground">Ascending</Select.Item
              >
              <Select.Item
                value="desc"
                label="Descending"
                class="text-card-foreground">Descending</Select.Item
              >
            </Select.Content>
          </Select.Root>
        </div>
      </div>

      <!-- candidates filter + poster size -->
      <div class="flex flex-col sm:flex-row sm:items-center gap-3">
        <label class="flex items-center gap-2 cursor-pointer">
          <Switch bind:checked={candidatesOnly} class="cursor-pointer" />
          <span class="text-sm text-muted-foreground"
            >Reclaim candidates only</span
          >
        </label>

        <div class="flex flex-1 flex-col gap-2 md:flex-row">
          <Select.Root type="single" bind:value={importedFilter}>
            <Select.Trigger class="w-full bg-card text-card-foreground">
              {#if importedFilter && importedFilter !== ALL_IMPORTED_FILTERS}
                {filterCatalog?.imported.find((item) => item.key === importedFilter)
                  ?.label ?? "Imported Filter"}
              {:else}
                Imported ARR Filter
              {/if}
            </Select.Trigger>
            <Select.Content class="bg-card">
              <Select.Item value={ALL_IMPORTED_FILTERS} label="All imported filters" class="text-card-foreground">
                All imported filters
              </Select.Item>
              {#each filterCatalog?.imported ?? [] as option}
                <Select.Item value={option.key} label={option.label} class="text-card-foreground">
                  {option.group} • {option.label}
                </Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>

          <Select.Root type="single" bind:value={decisionFilter}>
            <Select.Trigger class="w-full bg-card text-card-foreground">
              {#if decisionFilter && decisionFilter !== ALL_DECISION_FILTERS}
                {filterCatalog?.native.find((item) => item.key === decisionFilter)
                  ?.label ?? "Decision Filter"}
              {:else}
                MediaMasterr Filter
              {/if}
            </Select.Trigger>
            <Select.Content class="bg-card">
              <Select.Item value={ALL_DECISION_FILTERS} label="All decision filters" class="text-card-foreground">
                All decision filters
              </Select.Item>
              {#each filterCatalog?.native ?? [] as option}
                <Select.Item value={option.key} label={option.label} class="text-card-foreground">
                  {option.label}
                </Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        </div>

        <!-- per page + poster size -->
        <div class="flex items-center gap-3 sm:contents">
          <!-- per page -->
          <Select.Root
            type="single"
            value={perPage.toString()}
            onValueChange={(v) => {
              const n = parseInt(v);
              perPage = n;
              _perPageStore.save(n);
            }}
          >
            <Select.Trigger class="w-28 bg-card text-card-foreground">
              {perPage} / page
            </Select.Trigger>
            <Select.Content class="bg-card">
              {#each PER_PAGE_OPTIONS as option}
                <Select.Item
                  value={option.toString()}
                  label={option.toString()}
                  class="text-card-foreground"
                >
                  {option}
                </Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>

          <label class="flex items-center gap-2 sm:ml-auto">
            <LayoutGrid class="size-4 text-muted-foreground shrink-0" />
            <input
              type="range"
              min="100"
              max="300"
              step="10"
              bind:value={posterSize}
              class="w-24 accent-primary cursor-pointer"
            />
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
