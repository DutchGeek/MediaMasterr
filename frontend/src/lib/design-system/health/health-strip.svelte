<script lang="ts">
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import Link2 from "@lucide/svelte/icons/link-2";
  import FolderCheck from "@lucide/svelte/icons/folder-check";
  import Import from "@lucide/svelte/icons/import";
  import Activity from "@lucide/svelte/icons/activity";
  import Tv from "@lucide/svelte/icons/tv";
  import AlertTriangle from "@lucide/svelte/icons/alert-triangle";
  import type { HealthSignal, HealthSignalKind } from "$lib/design-system/model/types";

  let {
    items = [],
  }: {
    items?: HealthSignal[];
  } = $props();

  const icons: Record<HealthSignalKind, typeof ShieldCheck> = {
    protected: ShieldCheck,
    hardlinked: Link2,
    filesystem_verified: FolderCheck,
    imported: Import,
    torrent_active: Activity,
    plex_synced: Tv,
    warning: AlertTriangle,
  };

  const classes: Record<HealthSignalKind, string> = {
    protected: "text-emerald-300 border-emerald-500/30 bg-emerald-500/15",
    hardlinked: "text-sky-300 border-sky-500/30 bg-sky-500/15",
    filesystem_verified: "text-cyan-300 border-cyan-500/30 bg-cyan-500/15",
    imported: "text-violet-300 border-violet-500/30 bg-violet-500/15",
    torrent_active: "text-indigo-300 border-indigo-500/30 bg-indigo-500/15",
    plex_synced: "text-blue-300 border-blue-500/30 bg-blue-500/15",
    warning: "text-rose-300 border-rose-500/30 bg-rose-500/15",
  };
</script>

<div class="flex flex-wrap gap-2">
  {#each items as item}
    {@const Icon = icons[item.kind]}
    <span
      class={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] font-medium ${classes[item.kind]}`}
      title={item.explanation}
    >
      <Icon class="size-3.5" />
      {item.label}
    </span>
  {/each}
</div>
