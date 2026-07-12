<script lang="ts">
  import { BRANDING } from "$lib/branding";
  import logoAsset from "$lib/assets/logo.png";

  let {
    class: className = "",
    showTitle = true,
    logoHeightClass = "h-16",
    titleClass = "text-4xl font-bold leading-none text-foreground",
  }: {
    class?: string;
    showTitle?: boolean;
    logoHeightClass?: string;
    titleClass?: string;
  } = $props();
</script>

<div class={`inline-flex items-center gap-5 ${className}`.trim()}>
  <img
    src={logoAsset}
    alt={`${BRANDING.applicationName} logo`}
    class={`${logoHeightClass} w-auto object-contain`.trim()}
  />
  {#if showTitle}
    <span class={titleClass}>{BRANDING.applicationName}</span>
  {/if}
</div>
