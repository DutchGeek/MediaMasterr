<script lang="ts">
  import MediaCardShell from "$lib/design-system/cards/media-card-shell.svelte";
  import type { EpisodeObject } from "$lib/design-system/model/types";

  let {
    item,
    selected = false,
    loading = false,
    skeleton = false,
    posterSize = 136,
    onSelect,
  }: {
    item: EpisodeObject;
    selected?: boolean;
    loading?: boolean;
    skeleton?: boolean;
    posterSize?: number;
    onSelect?: () => void;
  } = $props();

  const subtitle = $derived.by(() => {
    if (item.episodeNumber !== undefined) {
      return `Episode ${item.episodeNumber}`;
    }
    return item.subtitle || "Episode";
  });
</script>

<MediaCardShell
  posterUrl={item.posterUrl}
  title={item.title}
  {subtitle}
  lifecycleState={item.lifecycleState}
  recommendationText={item.recommendation?.risk
    ? `Risk ${item.recommendation.risk}`
    : "Episode"}
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
