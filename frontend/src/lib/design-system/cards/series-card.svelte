<script lang="ts">
  import MediaCardShell from "$lib/design-system/cards/media-card-shell.svelte";
  import type { SeriesObject } from "$lib/design-system/model/types";
  import { formatFileSize } from "$lib/utils/formatters";

  let {
    item,
    selected = false,
    loading = false,
    skeleton = false,
    posterSize = 176,
    onSelect,
  }: {
    item: SeriesObject;
    selected?: boolean;
    loading?: boolean;
    skeleton?: boolean;
    posterSize?: number;
    onSelect?: () => void;
  } = $props();

  const subtitle = $derived.by(() => {
    const segments: string[] = [];
    if (item.affectedSeasons !== undefined) segments.push(`${item.affectedSeasons} seasons`);
    if (item.recommendations !== undefined) segments.push(`${item.recommendations} recommendations`);
    if (item.recoverableBytes !== undefined) segments.push(formatFileSize(item.recoverableBytes));
    return segments.join(" • ") || item.subtitle || "Series";
  });
</script>

<MediaCardShell
  posterUrl={item.posterUrl}
  title={item.title}
  subtitle={subtitle}
  lifecycleState={item.lifecycleState}
  recommendationText={item.highestRisk ? `Highest ${item.highestRisk}` : "Series Context"}
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
