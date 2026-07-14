<script lang="ts">
  import MediaCard from "./media-card.svelte";
  import Spinner from "$lib/components/ui/spinner/spinner.svelte";
  import CompactPagination from "$lib/components/compact-pagination.svelte";
  import type {
    MediaItem,
    MediaType,
    PaginatedResponse,
  } from "$lib/types/shared";
  import { formatLibraryDisplayName } from "$lib/utils/library-labels";

  interface Props {
    data: PaginatedResponse<MediaItem> | null;
    mediaType: MediaType;
    loading?: boolean;
    error?: string;
    posterSize?: number;
    onRequestException?: (media: MediaItem) => void;
    onRequestDelete?: (media: MediaItem) => void;
    onViewDetails?: (media: MediaItem) => void;
    onPageChange?: (page: number) => void;
  }

  let {
    data,
    mediaType,
    loading = false,
    error = "",
    posterSize = 150,
    onRequestException,
    onRequestDelete,
    onViewDetails,
    onPageChange,
  }: Props = $props();

  const groupedItems = $derived.by(() => {
    const items = data?.items ?? [];
    const groups = new Map<string, MediaItem[]>();
    for (const media of items) {
      const key = media.status.decision?.library_group ?? "Ungrouped";
      const bucket = groups.get(key) ?? [];
      bucket.push(media);
      groups.set(key, bucket);
    }
    return Array.from(groups.entries()).map(([name, items]) => ({
      name,
      items,
    }));
  });
</script>

<div class="w-full">
  {#if loading}
    <div class="flex justify-center items-center py-20">
      <Spinner class="w-12 h-12 text-primary" />
    </div>
  {:else if error}
    <div class="text-center py-20">
      <p class="text-red-500 text-lg">{error}</p>
    </div>
  {:else if !data || data.items.length === 0}
    <div class="text-center py-20">
      <p class="text-muted-foreground text-lg">
        No {mediaType === "movie" ? "movies" : "series"} found
      </p>
    </div>
  {:else}
    {#each groupedItems as group (group.name)}
      <section class="mb-6">
        <div class="mb-3">
          <h2 class="text-lg font-semibold text-foreground">
            {formatLibraryDisplayName(group.name)}
          </h2>
          <p class="text-xs text-muted-foreground">
            {group.items.length} item{group.items.length === 1 ? "" : "s"} on this
            page
          </p>
        </div>
        <div
          class="grid gap-4 mb-4"
          style="grid-template-columns: repeat(auto-fill, minmax({posterSize}px, 1fr))"
        >
          {#each group.items as media (media.id)}
            <MediaCard
              {media}
              {mediaType}
              {onRequestException}
              {onRequestDelete}
              {onViewDetails}
            />
          {/each}
        </div>
      </section>
    {/each}

    <!-- pagination -->
    {#if data.total_pages > 1}
      <div
        class="flex flex-wrap justify-center gap-2 md:flex-nowrap md:justify-between items-center"
      >
        <p class="text-sm text-muted-foreground">
          Showing {(data.page - 1) * data.per_page + 1} to {Math.min(
            data.page * data.per_page,
            data.total,
          )} of {data.total} items
        </p>

        <CompactPagination
          currentPage={data.page}
          totalPages={data.total_pages}
          maxVisiblePages={3}
          onPageChange={(page) => onPageChange?.(page)}
        />
      </div>
    {/if}
  {/if}
</div>
