<script lang="ts">
  import { Input } from "$lib/components/ui/input/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import Search from "@lucide/svelte/icons/search";
  import X from "@lucide/svelte/icons/x";
  import LayoutGrid from "@lucide/svelte/icons/layout-grid";
  import Settings2 from "@lucide/svelte/icons/settings-2";
  import type {
    MediaFilterCatalogResponse,
    MediaFilterOptionResponse,
  } from "$lib/types/shared";
  import { PER_PAGE_OPTIONS } from "$lib/utils/pagination";

  type SortOption = {
    value: string;
    label: string;
  };

  type SelectedFilter = MediaFilterOptionResponse;

  type BulkAction = {
    key: string;
    label: string;
  };

  let {
    searchQuery,
    searchPlaceholder,
    sortBy,
    sortByOptions,
    sortOrder,
    candidatesOnly = false,
    showCandidatesToggle = true,
    filterCatalog = null,
    importedFilterIds = [],
    decisionFilterIds = [],
    smartFilterIds = [],
    selectedFilterOptions = [],
    perPage = 25,
    posterSize = 150,
    viewMode = "grid",
    viewModes = ["grid", "list", "table"],
    selectedCount = 0,
    displayedCount = 0,
    totalCount = 0,
    showSelectDisplayed = false,
    selectDisplayedChecked = false,
    selectDisplayedIndeterminate = false,
    bulkActions = [],
    onSearchInput,
    onSortByChange,
    onSortOrderChange,
    onCandidatesOnlyChange,
    onToggleFilterSelection,
    onOpenFilterManager,
    onOpenSmartFilterDialog,
    onApplySmartFilter,
    onClearAllFilters,
    onPerPageChange,
    onPosterSizeChange,
    onViewModeChange,
    onBulkAction,
    onToggleSelectDisplayed,
    onOpenDisplayOptions,
  }: {
    searchQuery: string;
    searchPlaceholder: string;
    sortBy: string;
    sortByOptions: SortOption[];
    sortOrder: "asc" | "desc";
    candidatesOnly?: boolean;
    showCandidatesToggle?: boolean;
    filterCatalog?: MediaFilterCatalogResponse | null;
    importedFilterIds?: number[];
    decisionFilterIds?: number[];
    smartFilterIds?: number[];
    selectedFilterOptions?: SelectedFilter[];
    perPage?: number;
    posterSize?: number;
    viewMode?: string;
    viewModes?: string[];
    selectedCount?: number;
    displayedCount?: number;
    totalCount?: number;
    showSelectDisplayed?: boolean;
    selectDisplayedChecked?: boolean;
    selectDisplayedIndeterminate?: boolean;
    bulkActions?: BulkAction[];
    onSearchInput: (value: string) => void;
    onSortByChange: (value: string) => void;
    onSortOrderChange: (value: "asc" | "desc") => void;
    onCandidatesOnlyChange: (value: boolean) => void;
    onToggleFilterSelection: (
      source: "imported" | "decision" | "smart",
      filterId: number,
    ) => void;
    onOpenFilterManager: (mode: "arr" | "decision") => void;
    onOpenSmartFilterDialog: () => void;
    onApplySmartFilter: (option: SelectedFilter) => void;
    onClearAllFilters: () => void;
    onPerPageChange: (value: number) => void;
    onPosterSizeChange: (value: number) => void;
    onViewModeChange: (value: string) => void;
    onBulkAction: (key: string) => void;
    onToggleSelectDisplayed?: () => void;
    onOpenDisplayOptions?: () => void;
  } = $props();

  let selectDisplayedRef = $state<HTMLInputElement | null>(null);
  let sortByValue = $state(sortBy);
  let sortOrderValue = $state(sortOrder);

  $effect(() => {
    if (!selectDisplayedRef) return;
    selectDisplayedRef.indeterminate = selectDisplayedIndeterminate;
  });

  $effect(() => {
    sortByValue = sortBy;
  });

  $effect(() => {
    sortOrderValue = sortOrder;
  });
</script>

<div class="space-y-3 rounded-2xl border border-border bg-card/70 p-3 md:p-4">
  <div class="grid gap-3 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
    <div class="space-y-3">
      <div class="flex flex-col gap-2 lg:flex-row lg:items-center">
        <div
          class="relative w-full min-w-[280px] lg:w-[320px] lg:max-w-[320px] lg:flex-none"
        >
          <Search
            class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            type="text"
            placeholder={searchPlaceholder}
            value={searchQuery}
            oninput={(event) =>
              onSearchInput((event.target as HTMLInputElement).value)}
            class="h-9 w-full bg-background pl-10 pr-10 text-card-foreground placeholder:text-muted-foreground"
          />
          {#if searchQuery.trim().length > 0}
            <button
              type="button"
              class="absolute right-2 top-1/2 inline-flex size-6 -translate-y-1/2 items-center justify-center rounded-sm text-muted-foreground hover:bg-secondary hover:text-foreground"
              aria-label="Clear search"
              onclick={() => onSearchInput("")}
            >
              <X class="size-4" />
            </button>
          {/if}
        </div>

        <div class="flex gap-2">
          <Select.Root
            type="single"
            bind:value={sortByValue}
            onValueChange={onSortByChange}
          >
            <Select.Trigger
              class="min-w-40 cursor-pointer bg-background text-card-foreground"
            >
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

          <Select.Root
            type="single"
            bind:value={sortOrderValue}
            onValueChange={(value) =>
              onSortOrderChange(value as "asc" | "desc")}
          >
            <Select.Trigger
              class="min-w-32 cursor-pointer bg-background text-card-foreground"
            >
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

      <div class="flex flex-wrap items-center gap-3">
        {#if showCandidatesToggle}
          <label
            class="flex items-center gap-2 rounded-full border border-border/70 bg-background px-3 py-2 cursor-pointer"
          >
            <Switch
              checked={candidatesOnly}
              onCheckedChange={onCandidatesOnlyChange}
              class="cursor-pointer"
            />
            <span class="text-sm text-muted-foreground"
              >Reclaim candidates only</span
            >
          </label>
        {/if}

        <div class="flex flex-wrap gap-2">
          <DropdownMenu.Root>
            <DropdownMenu.Trigger>
              {#snippet child({ props })}
                <button
                  {...props}
                  type="button"
                  class="rounded-full border border-border px-3 py-2 text-sm text-foreground hover:bg-secondary/50 cursor-pointer"
                >
                  ARR Filters
                </button>
              {/snippet}
            </DropdownMenu.Trigger>
            <DropdownMenu.Content align="start" class="w-72">
              <DropdownMenu.Label>Imported filters</DropdownMenu.Label>
              <DropdownMenu.Separator />
              <DropdownMenu.Item
                onSelect={(event) => {
                  event.preventDefault();
                  onOpenFilterManager("arr");
                }}
              >
                Manage filters...
              </DropdownMenu.Item>
              <DropdownMenu.Separator />
              {#each filterCatalog?.imported ?? [] as option}
                {#if option.filter_id}
                  <DropdownMenu.Item
                    onSelect={(event) => {
                      event.preventDefault();
                      onToggleFilterSelection("imported", option.filter_id!);
                    }}
                  >
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
                <button
                  {...props}
                  type="button"
                  class="rounded-full border border-border px-3 py-2 text-sm text-foreground hover:bg-secondary/50 cursor-pointer"
                >
                  Decision Filters
                </button>
              {/snippet}
            </DropdownMenu.Trigger>
            <DropdownMenu.Content align="start" class="w-72">
              <DropdownMenu.Label>Decision filters</DropdownMenu.Label>
              <DropdownMenu.Separator />
              <DropdownMenu.Item
                onSelect={(event) => {
                  event.preventDefault();
                  onOpenFilterManager("decision");
                }}
              >
                Manage decision filters...
              </DropdownMenu.Item>
              <DropdownMenu.Separator />
              {#each filterCatalog?.native ?? [] as option}
                {#if option.filter_id}
                  <DropdownMenu.Item
                    onSelect={(event) => {
                      event.preventDefault();
                      onToggleFilterSelection("decision", option.filter_id!);
                    }}
                  >
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
                <button
                  {...props}
                  type="button"
                  class="rounded-full border border-border px-3 py-2 text-sm text-foreground hover:bg-secondary/50 cursor-pointer"
                >
                  Smart Filters
                </button>
              {/snippet}
            </DropdownMenu.Trigger>
            <DropdownMenu.Content align="start" class="w-80">
              <DropdownMenu.Label>Smart filters</DropdownMenu.Label>
              <DropdownMenu.Separator />
              <DropdownMenu.Item
                onSelect={(event) => {
                  event.preventDefault();
                  onOpenSmartFilterDialog();
                }}
              >
                Save current view...
              </DropdownMenu.Item>
              <DropdownMenu.Separator />
              {#each filterCatalog?.smart ?? [] as option}
                {#if option.filter_id}
                  <DropdownMenu.Item
                    onSelect={(event) => {
                      event.preventDefault();
                      onApplySmartFilter(option);
                    }}
                  >
                    {option.label}
                    {#if smartFilterIds.includes(option.filter_id)}
                      <span class="ml-auto text-xs text-primary">On</span>
                    {/if}
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
                  if (filter.kind === "imported_arr") {
                    onToggleFilterSelection("imported", filter.filter_id!);
                  } else if (filter.kind === "smart") {
                    onToggleFilterSelection("smart", filter.filter_id!);
                  } else {
                    onToggleFilterSelection("decision", filter.filter_id!);
                  }
                }}
              >
                {filter.label}
              </button>
            {/if}
          {/each}
          <button
            type="button"
            class="text-xs text-muted-foreground hover:text-foreground cursor-pointer"
            onclick={onClearAllFilters}
          >
            Clear all
          </button>
        </div>
      {/if}
    </div>

    <div class="grid gap-3 sm:grid-cols-[auto_1fr] sm:items-center">
      <Select.Root
        type="single"
        value={perPage.toString()}
        onValueChange={(v) => onPerPageChange(parseInt(v, 10))}
      >
        <Select.Trigger
          class="w-32 justify-between bg-background text-card-foreground"
        >
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

      <div class="flex items-center gap-2 sm:justify-end">
        <label
          class="flex items-center gap-2 rounded-xl border border-border/70 bg-background px-3 py-2"
        >
          <LayoutGrid class="size-4 shrink-0 text-muted-foreground" />
          <input
            type="range"
            min="100"
            max="300"
            step="10"
            value={posterSize}
            oninput={(event) =>
              onPosterSizeChange(
                parseInt((event.target as HTMLInputElement).value, 10),
              )}
            class="w-24 accent-primary cursor-pointer"
          />
        </label>

        <Select.Root
          type="single"
          value={viewMode}
          onValueChange={onViewModeChange}
        >
          <Select.Trigger class="min-w-24 bg-background text-card-foreground">
            {viewMode}
          </Select.Trigger>
          <Select.Content class="bg-card">
            {#each viewModes as mode}
              <Select.Item
                value={mode}
                label={mode}
                class="text-card-foreground"
              >
                {mode}
              </Select.Item>
            {/each}
          </Select.Content>
        </Select.Root>

        {#if onOpenDisplayOptions}
          <button
            type="button"
            class="rounded-xl border border-border/70 bg-background px-3 py-2 text-sm text-foreground hover:bg-secondary/50"
            onclick={onOpenDisplayOptions}
          >
            <span class="inline-flex items-center gap-1">
              <Settings2 class="size-4" />
              Display
            </span>
          </button>
        {/if}
      </div>
    </div>
  </div>

  <div class="flex flex-wrap items-center justify-between gap-2 text-sm">
    <div class="flex items-center gap-3 text-muted-foreground">
      {#if showSelectDisplayed}
        <label class="flex items-center gap-2">
          <input
            type="checkbox"
            bind:this={selectDisplayedRef}
            checked={selectDisplayedChecked}
            onchange={() => onToggleSelectDisplayed?.()}
          />
          <span>Select Displayed</span>
        </label>
        <div class="leading-tight">
          <div>Showing {displayedCount} of {totalCount}</div>
          <div>Selected: {selectedCount}</div>
        </div>
      {:else}
        <div>Selected: {selectedCount}</div>
      {/if}
    </div>
    <div class="flex flex-wrap gap-2">
      {#if bulkActions.length > 0}
        {#each bulkActions as action}
          <button
            type="button"
            class="rounded-full border border-border px-3 py-1.5 text-xs text-foreground hover:bg-secondary/40"
            onclick={() => onBulkAction(action.key)}
            disabled={selectedCount <= 0}
          >
            {action.label}{selectedCount > 0 ? ` (${selectedCount})` : ""}
          </button>
        {/each}
      {/if}
    </div>
  </div>
</div>
