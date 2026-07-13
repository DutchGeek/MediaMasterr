<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import Shield from "@lucide/svelte/icons/shield";
  import Trash2 from "@lucide/svelte/icons/trash-2";
  import Hourglass from "@lucide/svelte/icons/hourglass";
  import Play from "@lucide/svelte/icons/play";
  import MonitorPlay from "@lucide/svelte/icons/monitor-play";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import Download from "@lucide/svelte/icons/download";
  import Sprout from "@lucide/svelte/icons/sprout";
  import Rocket from "@lucide/svelte/icons/rocket";
  import type { DecisionInfo } from "$lib/types/shared";
  import { formatFileSize } from "$lib/utils/formatters";

  interface Props {
    decision: DecisionInfo | null;
    compact?: boolean;
  }

  let { decision, compact = false }: Props = $props();

  const toneClass = (tone: string): string => {
    switch (tone) {
      case "green":
        return "border-emerald-500/40 bg-emerald-500/15 text-emerald-100";
      case "blue":
        return "border-sky-500/40 bg-sky-500/15 text-sky-100";
      case "orange":
        return "border-orange-500/40 bg-orange-500/15 text-orange-100";
      case "yellow":
        return "border-amber-500/40 bg-amber-500/15 text-amber-100";
      case "purple":
        return "border-fuchsia-500/40 bg-fuchsia-500/15 text-fuchsia-100";
      case "teal":
        return "border-teal-500/40 bg-teal-500/15 text-teal-100";
      case "gray":
        return "border-slate-500/40 bg-slate-500/15 text-slate-100";
      case "red":
        return "border-red-500/40 bg-red-500/15 text-red-100";
      default:
        return "border-border bg-muted text-foreground";
    }
  };

  const iconFor = (icon: string) => {
    switch (icon) {
      case "shield":
        return Shield;
      case "trash-2":
        return Trash2;
      case "hourglass":
        return Hourglass;
      case "play":
        return Play;
      case "monitor-play":
        return MonitorPlay;
      case "triangle-alert":
        return TriangleAlert;
      case "download":
        return Download;
      case "sprout":
        return Sprout;
      case "rocket":
        return Rocket;
      default:
        return TriangleAlert;
    }
  };
</script>

{#if decision}
  {@const Icon = iconFor(decision.badge.icon)}
  <div class={`rounded-xl border px-3 py-2 backdrop-blur-sm ${toneClass(decision.badge.tone)}`}>
    <div class="flex items-center gap-2">
      <Icon class="size-4 shrink-0" />
      <div class="min-w-0 flex-1">
        <p class="text-[11px] uppercase tracking-[0.18em] opacity-80">{decision.badge.label}</p>
        {#if !compact}
          <p class="text-sm font-semibold line-clamp-1">{decision.display_name}</p>
        {/if}
      </div>
    </div>
    <p class={`mt-1 ${compact ? "text-xs" : "text-sm"} line-clamp-2 opacity-90`}>
      {decision.explanation}
    </p>
    {#if decision.reclaimable_size_bytes != null || decision.remaining_label}
      <div class="mt-2 flex flex-wrap gap-2 text-xs opacity-90">
        {#if decision.reclaimable_size_bytes != null}
          <Badge class="bg-black/20 text-current border-white/10">
            Recoverable {formatFileSize(decision.reclaimable_size_bytes)}
          </Badge>
        {/if}
        {#if decision.remaining_label}
          <Badge class="bg-black/20 text-current border-white/10">
            {decision.remaining_label}
          </Badge>
        {/if}
      </div>
    {/if}
  </div>
{/if}