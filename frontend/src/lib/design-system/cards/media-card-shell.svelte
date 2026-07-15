<script lang="ts">
  import Images from "@lucide/svelte/icons/images";
  import { BRANDING } from "$lib/branding";
  import { resolvePosterUrl } from "$lib/artwork";
  import { cn } from "$lib/utils.js";
  import LifecycleBadge from "$lib/design-system/badges/lifecycle-badge.svelte";
  import RecommendationRibbon from "$lib/design-system/ribbons/recommendation-ribbon.svelte";
  import HealthStrip from "$lib/design-system/health/health-strip.svelte";
  import type {
    HealthSignal,
    LifecycleState,
    QuickAction,
    RecommendationSeverity,
    RibbonPosition,
  } from "$lib/design-system/model/types";

  let {
    posterUrl = null,
    title,
    subtitle,
    lifecycleState,
    recommendationText,
    recommendationSeverity = "information",
    ribbonPosition = "top_left",
    recommendationSummary,
    healthSignals = [],
    quickActions = [],
    selected = false,
    loading = false,
    skeleton = false,
    hoverable = true,
    posterSize = 176,
    onSelect,
    class: className,
  }: {
    posterUrl?: string | null;
    title: string;
    subtitle?: string;
    lifecycleState?: LifecycleState;
    recommendationText?: string;
    recommendationSeverity?: RecommendationSeverity;
    ribbonPosition?: RibbonPosition;
    recommendationSummary?: string;
    healthSignals?: HealthSignal[];
    quickActions?: QuickAction[];
    selected?: boolean;
    loading?: boolean;
    skeleton?: boolean;
    hoverable?: boolean;
    posterSize?: number;
    onSelect?: () => void;
    class?: string;
  } = $props();

  let posterLoadFailed = $state(false);
  $effect(() => {
    posterUrl;
    posterLoadFailed = false;
  });

  const resolvedPosterUrl = $derived.by(() => {
    return resolvePosterUrl(posterUrl);
  });
</script>

<button
  type="button"
  class={cn(
    "group w-full rounded-[1.75rem] border border-border/70 bg-background/85 p-3 text-left shadow-sm",
    hoverable && "transition hover:-translate-y-1 hover:shadow-lg",
    selected && "ring-2 ring-primary",
    className,
  )}
  onclick={() => onSelect?.()}
>
  {#if skeleton}
    <div class="space-y-3 animate-pulse">
      <div class="h-44 rounded-2xl bg-secondary/60"></div>
      <div class="h-4 w-2/3 rounded bg-secondary/60"></div>
      <div class="h-3 w-1/2 rounded bg-secondary/60"></div>
      <div class="h-10 rounded bg-secondary/60"></div>
    </div>
  {:else}
    <div class="flex gap-3">
      <div
        class="relative overflow-hidden rounded-2xl border border-border/70 bg-gradient-to-br from-secondary/40 to-background"
        style={`width:${Math.round(posterSize * 0.58)}px;height:${posterSize}px`}
      >
        <img
          src={posterLoadFailed ? BRANDING.assets.mediaPlaceholder : resolvedPosterUrl}
          alt={title}
          class="h-full w-full object-cover"
          loading="lazy"
          onerror={() => {
            posterLoadFailed = true;
          }}
        />

        {#if posterLoadFailed}
          <div class="pointer-events-none absolute inset-0 flex items-center justify-center">
            <Images class="size-10 text-muted-foreground/60" />
          </div>
        {/if}

        {#if recommendationText}
          <RecommendationRibbon
            text={recommendationText}
            severity={recommendationSeverity}
            position={ribbonPosition}
          />
        {/if}
      </div>

      <div class="min-w-0 flex-1 space-y-2">
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div class="min-w-0">
            <p class="truncate text-base font-semibold text-foreground">
              {title}
            </p>
            {#if subtitle}
              <p class="truncate text-sm text-muted-foreground">{subtitle}</p>
            {/if}
          </div>
          {#if lifecycleState}
            <LifecycleBadge state={lifecycleState} />
          {/if}
        </div>

        {#if recommendationSummary}
          <p
            class="line-clamp-2 rounded-xl border border-border/70 bg-background/70 px-2.5 py-2 text-xs text-muted-foreground"
          >
            {recommendationSummary}
          </p>
        {/if}

        {#if healthSignals.length > 0}
          <HealthStrip items={healthSignals} />
        {/if}

        {#if quickActions.length > 0}
          <div class="flex flex-wrap gap-2 pt-1">
            {#each quickActions as action}
              <span
                class="rounded-full border border-border/70 bg-background px-2 py-1 text-[11px] text-foreground"
                aria-disabled={action.disabled}
              >
                {action.label}
              </span>
            {/each}
          </div>
        {/if}

        {#if loading}
          <p class="text-xs text-muted-foreground">Loading details...</p>
        {/if}
      </div>
    </div>
  {/if}
</button>
