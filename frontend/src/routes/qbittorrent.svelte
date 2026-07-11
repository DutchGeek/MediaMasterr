<script lang="ts">
  import { onMount } from "svelte";
  import Download from "@lucide/svelte/icons/download";
  import Upload from "@lucide/svelte/icons/upload";
  import PauseCircle from "@lucide/svelte/icons/pause-circle";
  import CheckCircle2 from "@lucide/svelte/icons/check-circle-2";
  import AlertTriangle from "@lucide/svelte/icons/alert-triangle";
  import { get_api } from "$lib/api";
  import {
    formatTorrentEta,
    formatTorrentProgress,
  } from "$lib/qbittorrent/view.js";
  import Spinner from "$lib/components/ui/spinner/spinner.svelte";
  import ErrorBox from "$lib/components/error-box.svelte";
  import { formatFileSize } from "$lib/utils/formatters";
  import { toTitleCase } from "$lib/utils/strings";

  interface QBittorrentMetrics {
    active_downloads: number;
    active_uploads: number;
    seeding: number;
    paused: number;
    completed: number;
    stalled: number;
    download_speed: number;
    upload_speed: number;
  }

  interface QBittorrentTorrentItem {
    name: string;
    category: string;
    state: string;
    progress: number;
    size: number;
    ratio: number;
    eta: number;
    download_speed: number;
    upload_speed: number;
    tracker: string | null;
    save_path: string | null;
  }

  interface QBittorrentOverviewResponse {
    app_version: string;
    webapi_version: string;
    metrics: QBittorrentMetrics;
    torrents: QBittorrentTorrentItem[];
  }

  let loading = $state(true);
  let error = $state("");
  let overview = $state<QBittorrentOverviewResponse | null>(null);

  const cards = $derived.by(() => {
    const metrics = overview?.metrics;
    if (!metrics) return [];
    return [
      {
        label: "Active Downloads",
        value: metrics.active_downloads,
        icon: Download,
      },
      {
        label: "Active Uploads",
        value: metrics.active_uploads,
        icon: Upload,
      },
      {
        label: "Seeding",
        value: metrics.seeding,
        icon: Upload,
      },
      {
        label: "Paused",
        value: metrics.paused,
        icon: PauseCircle,
      },
      {
        label: "Completed",
        value: metrics.completed,
        icon: CheckCircle2,
      },
      {
        label: "Stalled",
        value: metrics.stalled,
        icon: AlertTriangle,
      },
      {
        label: "Download Speed",
        value: `${formatFileSize(metrics.download_speed)}/s`,
        icon: Download,
      },
      {
        label: "Upload Speed",
        value: `${formatFileSize(metrics.upload_speed)}/s`,
        icon: Upload,
      },
    ];
  });

  const loadOverview = async () => {
    loading = true;
    error = "";
    try {
      overview = await get_api<QBittorrentOverviewResponse>(
        "/api/qbittorrent/overview",
      );
    } catch (err: any) {
      error = err?.message ?? "Failed to load qBittorrent data.";
    } finally {
      loading = false;
    }
  };

  onMount(loadOverview);
</script>

<div class="p-2.5 md:p-8">
  <div class="max-w-7xl mx-auto space-y-6">
    <div class="flex flex-col gap-1">
      <h1 class="text-3xl font-bold text-foreground">qBittorrent</h1>
      <p class="text-sm text-muted-foreground">
        Read-only integration. No torrent actions are available from this page.
      </p>
      {#if overview}
        <p class="text-xs text-muted-foreground">
          App {overview.app_version} · Web API {overview.webapi_version}
        </p>
      {/if}
    </div>

    {#if loading}
      <div class="flex justify-center py-8">
        <Spinner class="w-12 h-12 text-primary" />
      </div>
    {:else if error}
      <ErrorBox message={error} onRetry={loadOverview} />
    {:else if overview}
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {#each cards as card}
          <article class="rounded-lg border border-border bg-card p-4">
            <div class="flex items-center justify-between">
              <p class="text-xs uppercase tracking-wide text-muted-foreground">
                {card.label}
              </p>
              <card.icon class="size-4 text-primary" />
            </div>
            <p class="mt-2 text-2xl font-semibold text-foreground">{card.value}</p>
          </article>
        {/each}
      </div>

      <section class="rounded-lg border border-border bg-card overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full min-w-[1200px] text-sm">
            <thead class="bg-muted/40">
              <tr class="text-left text-muted-foreground">
                <th class="px-3 py-2 font-medium">Name</th>
                <th class="px-3 py-2 font-medium">Category</th>
                <th class="px-3 py-2 font-medium">State</th>
                <th class="px-3 py-2 font-medium">Progress</th>
                <th class="px-3 py-2 font-medium">Size</th>
                <th class="px-3 py-2 font-medium">Ratio</th>
                <th class="px-3 py-2 font-medium">ETA</th>
                <th class="px-3 py-2 font-medium">Download Speed</th>
                <th class="px-3 py-2 font-medium">Upload Speed</th>
                <th class="px-3 py-2 font-medium">Tracker</th>
                <th class="px-3 py-2 font-medium">Save Path</th>
              </tr>
            </thead>
            <tbody>
              {#if overview.torrents.length === 0}
                <tr>
                  <td colspan="11" class="px-3 py-8 text-center text-muted-foreground">
                    No torrents found.
                  </td>
                </tr>
              {:else}
                {#each overview.torrents as torrent}
                  <tr class="border-t border-border/60 align-top">
                    <td class="px-3 py-2 max-w-[300px]">
                      <p class="truncate text-foreground" title={torrent.name}>
                        {torrent.name}
                      </p>
                    </td>
                    <td class="px-3 py-2">{torrent.category || "—"}</td>
                    <td class="px-3 py-2">{toTitleCase(torrent.state || "unknown")}</td>
                    <td class="px-3 py-2">{formatTorrentProgress(torrent.progress)}</td>
                    <td class="px-3 py-2">{formatFileSize(torrent.size)}</td>
                    <td class="px-3 py-2">{torrent.ratio.toFixed(2)}</td>
                    <td class="px-3 py-2">{formatTorrentEta(torrent.eta)}</td>
                    <td class="px-3 py-2">{formatFileSize(torrent.download_speed)}/s</td>
                    <td class="px-3 py-2">{formatFileSize(torrent.upload_speed)}/s</td>
                    <td class="px-3 py-2 max-w-[200px]">
                      <p class="truncate" title={torrent.tracker || ""}>
                        {torrent.tracker || "—"}
                      </p>
                    </td>
                    <td class="px-3 py-2 max-w-[320px]">
                      <p class="truncate" title={torrent.save_path || ""}>
                        {torrent.save_path || "—"}
                      </p>
                    </td>
                  </tr>
                {/each}
              {/if}
            </tbody>
          </table>
        </div>
      </section>
    {/if}
  </div>
</div>
