<script lang="ts">
  import ArtworkImage from "$lib/design-system/media/artwork-image.svelte";
  import SeasonCard from "$lib/design-system/cards/season-card.svelte";
  import type {
    SeasonObject,
    SeriesObject,
  } from "$lib/design-system/model/types";
  import { formatFileSize } from "$lib/utils/formatters";

  let {
    series,
    onSelectSeason,
  }: {
    series: SeriesObject;
    onSelectSeason?: (season: SeasonObject) => void;
  } = $props();
</script>

<section class="space-y-4 rounded-2xl border border-border/70 bg-card p-4">
  <div class="grid gap-4 md:grid-cols-[220px_1fr]">
    <ArtworkImage
      src={series.posterUrl}
      alt={series.title}
      class="rounded-2xl border border-border/70 bg-background/70 aspect-[2/3]"
      imageClass="h-full w-full object-cover"
    />

    <div class="space-y-2">
      <h2 class="text-xl font-semibold text-foreground">{series.title}</h2>
      <div class="grid gap-2 text-sm text-muted-foreground md:grid-cols-2">
        <p>
          Affected Seasons: {series.affectedSeasons ??
            series.seasons?.length ??
            0}
        </p>
        <p>Recommendations: {series.recommendations ?? 0}</p>
        <p>Recoverable Space: {formatFileSize(series.recoverableBytes ?? 0)}</p>
        <p>Highest Risk: {series.highestRisk ?? "low"}</p>
        <p>Overall Health: {series.overallHealth ?? "unknown"}</p>
        <p>Last Scan: {series.lastScanAt ?? "n/a"}</p>
      </div>
      {#if series.recommendation?.explanation}
        <p
          class="rounded-xl border border-border/60 bg-background/60 p-2 text-xs text-muted-foreground"
        >
          {series.recommendation.explanation}
        </p>
      {/if}
    </div>
  </div>

  <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
    {#each series.seasons ?? [] as season}
      <SeasonCard item={season} onSelect={() => onSelectSeason?.(season)} />
    {/each}
  </div>
</section>
