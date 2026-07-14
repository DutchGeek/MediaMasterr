<script lang="ts">
  import { onMount } from "svelte";
  import { get_api } from "$lib/api";
  import { VERSION } from "$lib/version";
  import BrandLogo from "$lib/components/brand-logo.svelte";
  import { formatDistanceToNow } from "$lib/utils/date";
  import { formatFileSize } from "$lib/utils/formatters";
  import ErrorBox from "$lib/components/error-box.svelte";
  import type {
    ProtectionStatsResponse,
    ProtectionStatusResponse,
  } from "$lib/types/shared";

  type ProtectionRule = {
    rule: string;
    source: string;
    protected_items: number;
    status: string;
    last_updated: string | null;
  };

  type ProtectionItem = {
    path: string;
    reason: string;
    provider: string;
    expiration: string | null;
    status: string;
  };

  let loading = $state(true);
  let error = $state("");

  let status = $state<ProtectionStatusResponse | null>(null);
  let stats = $state<ProtectionStatsResponse | null>(null);
  let rules = $state<ProtectionRule[]>([]);
  let items = $state<ProtectionItem[]>([]);

  const isConnected = $derived(status?.connected ?? false);
  const lastSyncLabel = $derived(
    status?.last_sync
      ? formatDistanceToNow(status.last_sync)
      : "Not synchronized",
  );

  const loadData = async () => {
    loading = true;
    try {
      const [statusPayload, statsPayload, rulesPayload, itemsPayload] =
        await Promise.all([
          get_api<ProtectionStatusResponse>("/api/protection/status"),
          get_api<ProtectionStatsResponse>("/api/protection/stats"),
          get_api<ProtectionRule[]>("/api/protection/rules"),
          get_api<ProtectionItem[]>("/api/protection/items"),
        ]);
      status = statusPayload;
      stats = statsPayload;
      rules = rulesPayload;
      items = itemsPayload;
      error = "";
    } catch (e: any) {
      error = e?.message ?? "Failed to load Protection data";
    } finally {
      loading = false;
    }
  };

  onMount(async () => {
    await loadData();
  });
</script>

<div class="p-2.5 md:p-8">
  <div class="max-w-7xl mx-auto space-y-6">
    <section
      class="rounded-lg border border-border bg-card p-5 md:p-6 flex flex-col md:flex-row md:items-center md:justify-between gap-4"
    >
      <div class="flex items-center gap-3">
        <BrandLogo widthClass="w-[180px]" />
        <div>
          <h1 class="text-3xl font-bold text-foreground">Protection</h1>
          <p class="text-sm text-muted-foreground">
            Operational protection intelligence. Configure provider settings in
            Settings -> Protection.
          </p>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span
          class="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground"
          >v{VERSION}</span
        >
        <span
          class={`rounded-full px-3 py-1 text-xs ${isConnected ? "bg-green-500/20 text-green-500" : "bg-destructive/20 text-destructive"}`}
        >
          {isConnected ? "Connected" : "Disconnected"}
        </span>
        <span
          class="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground"
          >Last sync: {lastSyncLabel}</span
        >
      </div>
    </section>

    <ErrorBox {error} />

    {#if loading}
      <div
        class="bg-card rounded-lg border border-border p-8 text-center text-muted-foreground"
      >
        Loading Protection...
      </div>
    {:else}
      <section class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <article class="bg-card rounded-lg border border-border p-5">
          <p class="text-sm text-muted-foreground">Protected Files</p>
          <p class="text-3xl font-bold text-foreground mt-2">
            {stats?.protected_files
              ? stats.protected_files
              : "No protected items"}
          </p>
        </article>
        <article class="bg-card rounded-lg border border-border p-5">
          <p class="text-sm text-muted-foreground">Protected Size</p>
          <p class="text-3xl font-bold text-foreground mt-2">
            {formatFileSize(stats?.protected_size ?? 0)}
          </p>
        </article>
        <article class="bg-card rounded-lg border border-border p-5">
          <p class="text-sm text-muted-foreground">Protection Rules</p>
          <p class="text-3xl font-bold text-foreground mt-2">
            {stats?.active_rules ?? 0}
          </p>
        </article>
        <article class="bg-card rounded-lg border border-border p-5">
          <p class="text-sm text-muted-foreground">Last Sync</p>
          <p class="text-2xl font-bold text-foreground mt-2">
            {stats?.last_sync
              ? formatDistanceToNow(stats.last_sync)
              : "Not synchronized"}
          </p>
        </article>
      </section>

      <section class="bg-card rounded-lg border border-border p-5">
        <h2 class="text-lg font-semibold text-foreground mb-4">
          Protection Rules
        </h2>
        <div class="overflow-x-auto">
          <table class="w-full min-w-[700px] text-sm">
            <thead class="text-left text-muted-foreground">
              <tr class="border-b border-border">
                <th class="py-2">Rule</th>
                <th class="py-2">Source</th>
                <th class="py-2">Protected Items</th>
                <th class="py-2">Status</th>
                <th class="py-2">Last Updated</th>
              </tr>
            </thead>
            <tbody>
              {#if rules.length === 0}
                <tr
                  ><td
                    colspan="5"
                    class="py-6 text-center text-muted-foreground"
                    >No protection rules found.</td
                  ></tr
                >
              {:else}
                {#each rules as rule}
                  <tr class="border-b border-border/60">
                    <td class="py-2 text-foreground">{rule.rule}</td>
                    <td class="py-2 text-muted-foreground">{rule.source}</td>
                    <td class="py-2 text-foreground">{rule.protected_items}</td>
                    <td class="py-2 text-foreground">{rule.status}</td>
                    <td class="py-2 text-muted-foreground"
                      >{rule.last_updated
                        ? formatDistanceToNow(rule.last_updated)
                        : "Never"}</td
                    >
                  </tr>
                {/each}
              {/if}
            </tbody>
          </table>
        </div>
      </section>

      <section class="bg-card rounded-lg border border-border p-5">
        <h2 class="text-lg font-semibold text-foreground mb-4">
          Protected Items
        </h2>
        <div class="overflow-x-auto">
          <table class="w-full min-w-[900px] text-sm">
            <thead class="text-left text-muted-foreground">
              <tr class="border-b border-border">
                <th class="py-2">Path</th>
                <th class="py-2">Reason</th>
                <th class="py-2">Provider</th>
                <th class="py-2">Expiration</th>
                <th class="py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {#if items.length === 0}
                <tr
                  ><td
                    colspan="5"
                    class="py-6 text-center text-muted-foreground"
                    >No protected items found.</td
                  ></tr
                >
              {:else}
                {#each items as item}
                  <tr class="border-b border-border/60">
                    <td class="py-2 text-foreground break-all">{item.path}</td>
                    <td class="py-2 text-muted-foreground">{item.reason}</td>
                    <td class="py-2 text-foreground">{item.provider}</td>
                    <td class="py-2 text-muted-foreground"
                      >{item.expiration ?? "Never"}</td
                    >
                    <td class="py-2 text-foreground">{item.status}</td>
                  </tr>
                {/each}
              {/if}
            </tbody>
          </table>
        </div>
      </section>

      <section class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <article class="bg-card rounded-lg border border-border p-5">
          <h2 class="text-lg font-semibold text-foreground">
            Decision Statistics
          </h2>
          <p class="mt-2 text-sm text-muted-foreground">
            Decision-linked protection analytics remain available through
            dashboard decision summaries.
          </p>
        </article>
        <article class="bg-card rounded-lg border border-border p-5">
          <h2 class="text-lg font-semibold text-foreground">
            Upcoming Expirations
          </h2>
          <p class="mt-2 text-sm text-muted-foreground">
            Placeholder: expiration forecasting panel will be added in a
            follow-up release.
          </p>
        </article>
      </section>
    {/if}
  </div>
</div>
