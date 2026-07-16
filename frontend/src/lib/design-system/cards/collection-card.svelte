<script lang="ts">
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

  const collectionIcon = $derived.by(() => {
    const key = `${item.id} ${item.title}`.toLowerCase();
    if (key.includes("duplicate")) return "Layers";
    if (key.includes("orphan")) return "Unlink";
    if (key.includes("import")) return "Inbox";
    if (key.includes("torrent")) return "Download";
    if (key.includes("detach")) return "Scissors";
    if (key.includes("broken")) return "Alert";
    if (key.includes("recovery") || key.includes("space")) return "HardDrive";
    return "Folder";
  });

  const riskLabel = $derived.by(() => {
    const risk = item.recommendation?.risk;
    if (risk === "high") return "High";
    if (risk === "medium") return "Medium";
    return "Low";
  });
</script>

<button
  type="button"
  class={`group w-full rounded-[1.75rem] border border-border/70 bg-background/85 p-4 text-left shadow-sm transition hover:-translate-y-1 hover:shadow-lg ${selected ? "ring-2 ring-primary" : ""}`}
  onclick={() => onSelect?.()}
>
  {#if skeleton}
    <div class="space-y-3 animate-pulse">
      <div class="h-9 w-24 rounded bg-secondary/60"></div>
      <div class="h-5 w-2/3 rounded bg-secondary/60"></div>
      <div class="h-4 w-1/2 rounded bg-secondary/60"></div>
      <div class="h-10 rounded bg-secondary/60"></div>
    </div>
  {:else}
    <div class="space-y-3">
      <div class="flex items-center justify-between gap-2">
        <span class="rounded-full border border-border/70 bg-secondary/35 px-2.5 py-1 text-[11px] uppercase tracking-wide text-muted-foreground">
          {collectionIcon}
        </span>
        <span class={`rounded-full px-2 py-0.5 text-[11px] ${riskLabel === "High" ? "bg-destructive/20 text-destructive" : riskLabel === "Medium" ? "bg-yellow-500/20 text-yellow-500" : "bg-green-500/20 text-green-500"}`}>
          Risk: {riskLabel}
        </span>
      </div>
      <div>
        <p class="text-base font-semibold text-foreground">{item.title}</p>
        <p class="text-sm text-muted-foreground">{subtitle}</p>
      </div>
      {#if item.recommendation?.recoverableBytes}
        <p class="text-xs text-muted-foreground">Potential reclaim: {Math.round(item.recommendation.recoverableBytes / 1024 / 1024 / 1024)} GB</p>
      {/if}
      {#if item.recommendation?.message}
        <p class="line-clamp-2 rounded-xl border border-border/70 bg-background/70 px-2.5 py-2 text-xs text-muted-foreground">
          {item.recommendation.message}
        </p>
      {/if}
      {#if loading}
        <p class="text-xs text-muted-foreground">Loading details...</p>
      {/if}
    </div>
  {/if}
</button>
