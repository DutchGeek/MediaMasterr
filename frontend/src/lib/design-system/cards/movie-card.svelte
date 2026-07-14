<script lang="ts">
  import MediaCardShell from "$lib/design-system/cards/media-card-shell.svelte";
  import type { MovieObject } from "$lib/design-system/model/types";

  let {
    item,
    selected = false,
    loading = false,
    skeleton = false,
    posterSize = 176,
    onSelect,
  }: {
    item: MovieObject;
    selected?: boolean;
    loading?: boolean;
    skeleton?: boolean;
    posterSize?: number;
    onSelect?: () => void;
  } = $props();
</script>

<MediaCardShell
  posterUrl={item.posterUrl}
  title={item.title}
  subtitle={item.subtitle}
  lifecycleState={item.lifecycleState}
  recommendationText={item.recommendation?.risk ? `Risk ${item.recommendation.risk}` : "Recommendation"}
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
