<script lang="ts">
  import { cn } from "$lib/utils.js";
  import type { LifecycleState } from "$lib/design-system/model/types";

  let {
    state,
    class: className,
  }: {
    state: LifecycleState;
    class?: string;
  } = $props();

  const labels: Record<LifecycleState, string> = {
    requested: "Requested",
    downloading: "Downloading",
    importing: "Importing",
    imported: "Imported",
    verified: "Verified",
    protected: "Protected",
    seeding: "Seeding",
    seed_goal_reached: "Seed Goal Reached",
    detached: "Detached",
    archived: "Archived",
    candidate: "Candidate",
    deleted: "Deleted",
  };

  const classes: Record<LifecycleState, string> = {
    requested: "border-slate-500/30 bg-slate-500/15 text-slate-200",
    downloading: "border-sky-500/30 bg-sky-500/15 text-sky-300",
    importing: "border-sky-500/30 bg-sky-500/15 text-sky-300",
    imported: "border-emerald-500/30 bg-emerald-500/15 text-emerald-300",
    verified: "border-emerald-500/30 bg-emerald-500/15 text-emerald-300",
    protected: "border-violet-500/30 bg-violet-500/15 text-violet-300",
    seeding: "border-cyan-500/30 bg-cyan-500/15 text-cyan-300",
    seed_goal_reached: "border-cyan-500/30 bg-cyan-500/15 text-cyan-300",
    detached: "border-amber-500/30 bg-amber-500/15 text-amber-300",
    archived: "border-slate-500/30 bg-slate-500/15 text-slate-200",
    candidate: "border-amber-500/30 bg-amber-500/15 text-amber-300",
    deleted: "border-rose-500/30 bg-rose-500/15 text-rose-300",
  };
</script>

<span
  class={cn(
    "inline-flex rounded-full border px-2 py-1 text-[11px] font-semibold uppercase tracking-wide",
    classes[state],
    className,
  )}
>
  {labels[state]}
</span>
