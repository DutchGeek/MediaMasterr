<script lang="ts">
  import { cn } from "$lib/utils.js";
  import type {
    RecommendationSeverity,
    RibbonPosition,
  } from "$lib/design-system/model/types";

  let {
    text,
    severity = "information",
    position = "top_left",
    class: className,
  }: {
    text: string;
    severity?: RecommendationSeverity;
    position?: RibbonPosition;
    class?: string;
  } = $props();

  const severityClasses: Record<RecommendationSeverity, string> = {
    healthy: "border-emerald-500/30 bg-emerald-500/15 text-emerald-300",
    information: "border-sky-500/30 bg-sky-500/15 text-sky-300",
    action: "border-amber-500/30 bg-amber-500/15 text-amber-300",
    problem: "border-rose-500/30 bg-rose-500/15 text-rose-300",
  };

  const positionClasses: Record<RibbonPosition, string> = {
    top_left: "left-3 top-3",
    top_right: "right-3 top-3",
    bottom_left: "left-3 bottom-3",
    bottom_right: "right-3 bottom-3",
    badge_only: "left-3 top-3 relative inline-flex",
  };
</script>

<div
  class={cn(
    "pointer-events-none rounded-full border px-2 py-1 text-[11px] font-semibold uppercase tracking-wide",
    severityClasses[severity],
    position === "badge_only" ? "" : "absolute",
    positionClasses[position],
    className,
  )}
>
  {text}
</div>
