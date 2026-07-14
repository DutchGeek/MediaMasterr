<script lang="ts">
  import MediaCardShell from "$lib/design-system/cards/media-card-shell.svelte";
  import type { MovieCollectionObject } from "$lib/design-system/model/types";

  let {
    item,
    selected = false,
    loading = false,
    skeleton = false,
    posterSize = 176,
    onSelect,
  }: {
    item: MovieCollectionObject;
    selected?: boolean;
    loading?: boolean;
    skeleton?: boolean;
    posterSize?: number;
    onSelect?: () => void;
  } = $props();

  const subtitle = $derived.by(() => {
    const count = item.movies?.length ?? 0;
    if (count > 0) return `${count} movies`;
    return item.subtitle || "Collection";
  });
</script>

<MediaCardShell
  posterUrl={item.posterUrl}
  title={item.title}
  {subtitle}
  lifecycleState={item.lifecycleState}
  recommendationText={item.recommendation?.risk
    ? `Risk ${item.recommendation.risk}`
    : "Collection Context"}
  recommendationSeverity={item.recommendationSeverity}
  recommendationSummary={item.recommendation?.message}
  healthSignals={item.healthSignals ?? []}
  quickActions={item.quickActions ?? []}
  {selected}
  {loading}
  {skeleton}
  {posterSize}
  {onSelect}
/>
