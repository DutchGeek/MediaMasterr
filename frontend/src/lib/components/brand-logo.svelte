<script lang="ts">
  import { BRANDING } from "$lib/branding";

  let {
    class: className = "",
    widthClass = "w-[200px]",
  }: {
    class?: string;
    widthClass?: string;
  } = $props();
</script>

<img
  src={BRANDING.assets.logo}
  alt={`${BRANDING.applicationName} logo`}
  class={`${widthClass} max-w-full h-auto object-contain ${className}`.trim()}
/>
