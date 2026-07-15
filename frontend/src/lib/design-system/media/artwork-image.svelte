<script lang="ts">
  import Images from "@lucide/svelte/icons/images";
  import { BRANDING } from "$lib/branding";
  import { resolvePosterUrl } from "$lib/artwork";
  import { cn } from "$lib/utils.js";

  let {
    src = null,
    alt = "Artwork",
    class: className,
    imageClass = "h-full w-full object-cover",
    loading = "lazy",
    showFailureIcon = true,
  }: {
    src?: string | null;
    alt?: string;
    class?: string;
    imageClass?: string;
    loading?: "eager" | "lazy";
    showFailureIcon?: boolean;
  } = $props();

  let failed = $state(false);

  $effect(() => {
    src;
    failed = false;
  });

  const resolvedSrc = $derived.by(() => {
    if (failed) return BRANDING.assets.mediaPlaceholder;
    return resolvePosterUrl(src);
  });
</script>

<div class={cn("relative overflow-hidden", className)}>
  <img
    src={resolvedSrc}
    alt={alt}
    class={imageClass}
    loading={loading}
    onerror={() => {
      failed = true;
    }}
  />

  {#if failed && showFailureIcon}
    <div class="pointer-events-none absolute inset-0 flex items-center justify-center">
      <Images class="size-10 text-muted-foreground/60" />
    </div>
  {/if}
</div>
