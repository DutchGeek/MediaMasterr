<script lang="ts">
  import CollectionCard from "$lib/design-system/cards/collection-card.svelte";
  import MovieCard from "$lib/design-system/cards/movie-card.svelte";
  import type { MovieCollectionObject, MovieObject } from "$lib/design-system/model/types";

  let {
    collection,
    onSelectMovie,
  }: {
    collection: MovieCollectionObject;
    onSelectMovie?: (movie: MovieObject) => void;
  } = $props();
</script>

<section class="space-y-4 rounded-2xl border border-border/70 bg-card p-4">
  <CollectionCard item={collection} />

  <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
    {#each collection.movies ?? [] as movie}
      <MovieCard item={movie} onSelect={() => onSelectMovie?.(movie)} />
    {/each}
  </div>
</section>
