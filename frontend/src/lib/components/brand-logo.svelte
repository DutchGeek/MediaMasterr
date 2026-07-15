<script lang="ts">
  import { BRANDING } from "$lib/branding";

  let {
    class: className = "",
    width = 200,
  }: {
    class?: string;
    width?: number;
  } = $props();
</script>

<img
  src={BRANDING.assets.logo}
  alt={`${BRANDING.applicationName} logo`}
  style={`width:${Math.max(1, width)}px`}
  class={`block max-w-full max-h-full h-auto object-contain ${className}`.trim()}
/>
