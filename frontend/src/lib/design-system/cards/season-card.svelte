<script lang="ts">
  import MediaCardShell from "$lib/design-system/cards/media-card-shell.svelte";
  import type { SeasonObject } from "$lib/design-system/model/types";

  let {
    item,
    selected = false,
    loading = false,
    skeleton = false,
    posterSize = 160,
    onSelect,
  }: {
    item: SeasonObject;
    selected?: boolean;
    loading?: boolean;
    skeleton?: boolean;
    posterSize?: number;
    onSelect?: () => void;
  } = $props();

  const subtitle = $derived.by(() => {
    const episodeCount = item.episodes?.length ?? 0;
    const fallback = item.subtitle ?? "Season";
    return episodeCount > 0 ? `${fallback} • ${episodeCount} episodes` : fallback;
  });
</script>

<MediaCardShell
  posterUrl={item.posterUrl}
  title={item.title}
  subtitle={subtitle}
  lifecycleState={item.lifecycleState}
  recommendationText={item.recommendation?.risk ? `Risk ${item.recommendation.risk}` : "Season Action"}
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
