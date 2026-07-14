<script lang="ts">
  import { onMount } from "svelte";
  import Link2 from "@lucide/svelte/icons/link-2";
  import Database from "@lucide/svelte/icons/database";
  import Spinner from "$lib/components/ui/spinner/spinner.svelte";
  import ErrorBox from "$lib/components/error-box.svelte";
  import { get_api } from "$lib/api";
  import { asDisplayValue, nodeBadgeClass } from "$lib/correlation/view.js";

  interface CorrelationTorrentSummary {
    id: string;
    hash: string | null;
    name: string;
    category: string | null;
    state: string | null;
    save_path: string | null;
    provider: string;
  }

  interface CorrelationNode {
    stage: string;
    label: string;
    status: "known" | "unknown";
    value: string;
    provider: string | null;
    path: string | null;
    metadata: Record<string, unknown> | null;
  }

  interface CorrelationFields {
    torrent: string;
    series: string;
    episode: string;
    movie: string;
    file: string;
    media_server: string;
    protection_status: string;
    watch_status: string;
    import_status: string;
    provider: string;
    storage_path: string;
  }

  interface CorrelationDetail {
    torrent: CorrelationTorrentSummary;
    fields: CorrelationFields;
    nodes: CorrelationNode[];
  }

  let loadingTorrents = $state(true);
  let loadingDetail = $state(false);
  let error = $state("");
  let torrents = $state<CorrelationTorrentSummary[]>([]);
  let selectedId = $state("");
  let detail = $state<CorrelationDetail | null>(null);

  const summaryRows = $derived.by(() => {
    if (!detail) return [];
    const f = detail.fields;
    return [
      ["Torrent", f.torrent],
      ["Series", f.series],
      ["Episode", f.episode],
      ["Movie", f.movie],
      ["File", f.file],
      ["Media Server", f.media_server],
      ["Protection Status", f.protection_status],
      ["Watch Status", f.watch_status],
      ["Import Status", f.import_status],
      ["Provider", f.provider],
      ["Storage Path", f.storage_path],
    ] as const;
  });

  const loadDetail = async (torrentId: string) => {
    if (!torrentId) return;
    loadingDetail = true;
    error = "";
    try {
      detail = await get_api<CorrelationDetail>(
        `/api/correlation/torrents/${torrentId}`,
      );
    } catch (err: any) {
      detail = null;
      error = err?.message ?? "Failed to load relationships.";
    } finally {
      loadingDetail = false;
    }
  };

  const selectTorrent = async (torrentId: string) => {
    selectedId = torrentId;
    await loadDetail(torrentId);
  };

  const load = async () => {
    loadingTorrents = true;
    error = "";
    try {
      const response = await get_api<{ items: CorrelationTorrentSummary[] }>(
        "/api/correlation/torrents",
      );
      torrents = response.items;
      if (torrents.length > 0) {
        selectedId = torrents[0].id;
        await loadDetail(torrents[0].id);
      }
    } catch (err: any) {
      error = err?.message ?? "Failed to load correlation data.";
    } finally {
      loadingTorrents = false;
    }
  };

  onMount(load);
</script>

<div class="p-2.5 md:p-8">
  <div class="max-w-7xl mx-auto space-y-6">
    <div class="flex items-center gap-3">
      <Link2 class="size-7 text-primary" />
      <div>
        <h1 class="text-3xl font-bold text-foreground">Media Relationships</h1>
        <p class="text-sm text-muted-foreground">
          Read-only media correlation across download, Arr, media-server, watch,
          and protection data.
        </p>
      </div>
    </div>

    {#if loadingTorrents}
      <div class="flex justify-center py-8">
        <Spinner class="w-12 h-12 text-primary" />
      </div>
    {:else if error && !detail}
      <ErrorBox {error} />
    {:else}
      <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <section
          class="rounded-lg border border-border bg-card overflow-hidden"
        >
          <div class="px-4 py-3 border-b border-border flex items-center gap-2">
            <Database class="size-4 text-primary" />
            <h2 class="font-semibold text-foreground">Torrents</h2>
          </div>
          <div class="max-h-[640px] overflow-auto">
            <table class="w-full text-sm">
              <thead class="bg-muted/40 sticky top-0">
                <tr class="text-left text-muted-foreground">
                  <th class="px-3 py-2 font-medium">Name</th>
                  <th class="px-3 py-2 font-medium">Category</th>
                  <th class="px-3 py-2 font-medium">State</th>
                </tr>
              </thead>
              <tbody>
                {#if torrents.length === 0}
                  <tr>
                    <td
                      colspan="3"
                      class="px-3 py-8 text-center text-muted-foreground"
                    >
                      No torrents found.
                    </td>
                  </tr>
                {:else}
                  {#each torrents as torrent}
                    <tr class="border-t border-border/60">
                      <td class="px-3 py-2">
                        <button
                          type="button"
                          class={`text-left w-full truncate rounded px-2 py-1 transition-colors ${selectedId === torrent.id ? "bg-primary/15 text-primary" : "hover:bg-muted/60"}`}
                          title={torrent.name}
                          onclick={() => selectTorrent(torrent.id)}
                        >
                          {torrent.name}
                        </button>
                      </td>
                      <td class="px-3 py-2"
                        >{asDisplayValue(torrent.category)}</td
                      >
                      <td class="px-3 py-2">{asDisplayValue(torrent.state)}</td>
                    </tr>
                  {/each}
                {/if}
              </tbody>
            </table>
          </div>
        </section>

        <section class="space-y-4">
          {#if loadingDetail}
            <div
              class="flex justify-center py-8 rounded-lg border border-border bg-card"
            >
              <Spinner class="w-10 h-10 text-primary" />
            </div>
          {:else if detail}
            <article
              class="rounded-lg border border-border bg-card p-4 space-y-3"
            >
              <h2 class="font-semibold text-foreground">Linked Objects</h2>
              <div class="grid gap-2 sm:grid-cols-2">
                {#each summaryRows as row}
                  <div
                    class="rounded-md border border-border/60 bg-muted/20 px-3 py-2"
                  >
                    <p
                      class="text-xs uppercase tracking-wide text-muted-foreground"
                    >
                      {row[0]}
                    </p>
                    <p class="text-sm text-foreground break-words">
                      {asDisplayValue(row[1])}
                    </p>
                  </div>
                {/each}
              </div>
            </article>

            <article
              class="rounded-lg border border-border bg-card overflow-hidden"
            >
              <div class="px-4 py-3 border-b border-border">
                <h2 class="font-semibold text-foreground">
                  Normalized Correlation Nodes
                </h2>
              </div>
              <div class="overflow-x-auto">
                <table class="w-full min-w-[760px] text-sm">
                  <thead class="bg-muted/40">
                    <tr class="text-left text-muted-foreground">
                      <th class="px-3 py-2 font-medium">Stage</th>
                      <th class="px-3 py-2 font-medium">Value</th>
                      <th class="px-3 py-2 font-medium">Status</th>
                      <th class="px-3 py-2 font-medium">Provider</th>
                      <th class="px-3 py-2 font-medium">Path</th>
                    </tr>
                  </thead>
                  <tbody>
                    {#each detail.nodes as node}
                      <tr class="border-t border-border/60 align-top">
                        <td class="px-3 py-2 text-foreground">{node.label}</td>
                        <td class="px-3 py-2 break-words"
                          >{asDisplayValue(node.value)}</td
                        >
                        <td class="px-3 py-2">
                          <span
                            class={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${nodeBadgeClass(node.status)}`}
                          >
                            {node.status}
                          </span>
                        </td>
                        <td class="px-3 py-2"
                          >{asDisplayValue(node.provider)}</td
                        >
                        <td class="px-3 py-2 break-words"
                          >{asDisplayValue(node.path)}</td
                        >
                      </tr>
                    {/each}
                  </tbody>
                </table>
              </div>
            </article>
          {:else if error}
            <ErrorBox {error} />
          {/if}
        </section>
      </div>
    {/if}
  </div>
</div>
