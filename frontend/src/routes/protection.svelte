<script lang="ts">
  import { onMount } from "svelte";
  import { get_api, post_api } from "$lib/api";
  import { BRANDING } from "$lib/branding";
  import { VERSION } from "$lib/version";
  import { formatDate, formatDistanceToNow } from "$lib/utils/date";
  import { formatFileSize } from "$lib/utils/formatters";
  import ErrorBox from "$lib/components/error-box.svelte";

  type ProtectionConfig = {
    provider: string;
    base_url: string;
    api_key_configured: boolean;
    enabled: boolean;
  };

  type ProtectionConfigForm = {
    provider: string;
    base_url: string;
    api_key: string;
    enabled: boolean;
  };

  type ProtectionStatus = {
    connected: boolean;
    provider: string;
    connection_status: string;
    base_url: string | null;
    last_sync: string | null;
    message: string | null;
  };

  type ProtectionStats = {
    connected: boolean;
    provider: string;
    protected_files: number;
    protected_size: number;
    active_rules: number;
    last_sync: string | null;
  };

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

  let config = $state<ProtectionConfig | null>(null);
  let form = $state<ProtectionConfigForm>({
    provider: "reclaimerr",
    base_url: "",
    api_key: "",
    enabled: true,
  });

  let status = $state<ProtectionStatus | null>(null);
  let stats = $state<ProtectionStats | null>(null);
  let rules = $state<ProtectionRule[]>([]);
  let items = $state<ProtectionItem[]>([]);

  let testing = $state(false);
  let saving = $state(false);
  let syncing = $state(false);

  const isConnected = $derived(status?.connected ?? false);
  const lastSyncLabel = $derived(
    status?.last_sync ? formatDistanceToNow(status.last_sync) : "Never",
  );

  const loadConfig = async () => {
    config = await get_api<ProtectionConfig>("/api/protection/config");
    form = {
      provider: config.provider,
      base_url: config.base_url,
      api_key: "",
      enabled: config.enabled,
    };
  };

  const loadPageData = async () => {
    const [statusPayload, statsPayload, rulesPayload, itemsPayload] =
      await Promise.all([
        get_api<ProtectionStatus>("/api/protection/status"),
        get_api<ProtectionStats>("/api/protection/stats"),
        get_api<ProtectionRule[]>("/api/protection/rules"),
        get_api<ProtectionItem[]>("/api/protection/items"),
      ]);

    status = statusPayload;
    stats = statsPayload;
    rules = rulesPayload;
    items = itemsPayload;
  };

  const loadAll = async () => {
    loading = true;
    try {
      await Promise.all([loadConfig(), loadPageData()]);
      error = "";
    } catch (e: any) {
      error = e?.message ?? "Failed to load Protection data";
    } finally {
      loading = false;
    }
  };

  const testConnection = async () => {
    testing = true;
    try {
      status = await post_api<ProtectionStatus>("/api/protection/test", {
        provider: form.provider,
        base_url: form.base_url,
        api_key: form.api_key,
        enabled: form.enabled,
      });
      error = "";
    } catch (e: any) {
      error = e?.message ?? "Connection test failed";
    } finally {
      testing = false;
    }
  };

  const saveSettings = async () => {
    saving = true;
    try {
      config = await post_api<ProtectionConfig>("/api/protection/config", {
        provider: form.provider,
        base_url: form.base_url,
        api_key: form.api_key,
        enabled: form.enabled,
      });
      form.api_key = "";
      await loadPageData();
      error = "";
    } catch (e: any) {
      error = e?.message ?? "Failed to save Protection settings";
    } finally {
      saving = false;
    }
  };

  const syncNow = async () => {
    syncing = true;
    try {
      status = await post_api<ProtectionStatus>("/api/protection/sync", {});
      await loadPageData();
      error = "";
    } catch (e: any) {
      error = e?.message ?? "Failed to sync Protection provider";
    } finally {
      syncing = false;
    }
  };

  onMount(async () => {
    await loadAll();
  });
</script>

<div class="p-2.5 md:p-8">
  <div class="max-w-7xl mx-auto space-y-6">
    <section
      class="rounded-lg border border-border bg-card p-5 md:p-6 flex flex-col md:flex-row md:items-center md:justify-between gap-4"
    >
      <div class="flex items-center gap-3">
        <img
          src={BRANDING.assets.logo}
          alt={`${BRANDING.applicationName} logo`}
          class="h-10 w-auto object-contain"
        />
        <div>
          <h1 class="text-3xl font-bold text-foreground">Protection</h1>
          <p class="text-sm text-muted-foreground">
            Provider: Reclaimerr
          </p>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <span class="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground">
          v{VERSION}
        </span>
        <span
          class={`rounded-full px-3 py-1 text-xs ${isConnected
            ? "bg-green-500/20 text-green-500"
            : "bg-destructive/20 text-destructive"}`}
        >
          {isConnected ? "Connected" : "Disconnected"}
        </span>
        <span class="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground">
          Last sync: {lastSyncLabel}
        </span>
      </div>
    </section>

    <ErrorBox {error} />

    {#if loading}
      <div
        class="bg-card rounded-lg border border-border p-8 text-center text-muted-foreground"
      >
        <div
          class="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-primary border-r-transparent"
        ></div>
        <p class="mt-3">Loading Protection...</p>
      </div>
    {:else}
      <section class="rounded-lg border border-border bg-card p-5 md:p-6 space-y-4">
        <h2 class="text-lg font-semibold text-foreground">Settings</h2>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <label class="space-y-2">
            <span class="text-sm text-muted-foreground">Provider</span>
            <input
              value="Reclaimerr"
              disabled
              class="w-full rounded-md border border-border bg-secondary/40 px-3 py-2 text-foreground"
            />
          </label>

          <label class="space-y-2">
            <span class="text-sm text-muted-foreground">URL</span>
            <input
              bind:value={form.base_url}
              placeholder="https://reclaimerr.internal"
              class="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
            />
          </label>

          <label class="space-y-2">
            <span class="text-sm text-muted-foreground">API Key</span>
            <input
              bind:value={form.api_key}
              placeholder={config?.api_key_configured
                ? "Saved key configured"
                : "Enter API key"}
              class="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
            />
          </label>

          <label class="space-y-2">
            <span class="text-sm text-muted-foreground">Connection Status</span>
            <input
              value={status?.connection_status ?? "unknown"}
              disabled
              class="w-full rounded-md border border-border bg-secondary/40 px-3 py-2 text-foreground"
            />
          </label>
        </div>

        <div class="flex flex-wrap items-center gap-3">
          <button
            onclick={testConnection}
            disabled={testing}
            class="rounded-md bg-secondary px-4 py-2 text-sm font-medium text-secondary-foreground hover:bg-secondary/80 disabled:opacity-60"
          >
            {testing ? "Testing..." : "Test Connection"}
          </button>
          <button
            onclick={saveSettings}
            disabled={saving}
            class="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
          >
            {saving ? "Saving..." : "Save"}
          </button>
          <button
            onclick={syncNow}
            disabled={syncing || !isConnected}
            class="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground hover:bg-accent disabled:opacity-60"
          >
            {syncing ? "Syncing..." : "Sync Now"}
          </button>
          <p class="text-xs text-muted-foreground">
            Last sync: {status?.last_sync ? formatDate(status.last_sync) : "Never"}
          </p>
        </div>
      </section>

      <section class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <article class="bg-card rounded-lg border border-border p-5">
          <p class="text-sm text-muted-foreground">Protected Files</p>
          <p class="text-3xl font-bold text-foreground mt-2">
            {stats?.protected_files ?? 0}
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
            {stats?.last_sync ? formatDistanceToNow(stats.last_sync) : "Never"}
          </p>
        </article>
      </section>

      <section class="bg-card rounded-lg border border-border p-5">
        <h2 class="text-lg font-semibold text-foreground mb-4">Protection Rules</h2>
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
                <tr>
                  <td colspan="5" class="py-6 text-center text-muted-foreground">
                    No protection rules found.
                  </td>
                </tr>
              {:else}
                {#each rules as rule}
                  <tr class="border-b border-border/60">
                    <td class="py-2 text-foreground">{rule.rule}</td>
                    <td class="py-2 text-muted-foreground">{rule.source}</td>
                    <td class="py-2 text-foreground">{rule.protected_items}</td>
                    <td class="py-2 text-foreground">{rule.status}</td>
                    <td class="py-2 text-muted-foreground">
                      {rule.last_updated ? formatDistanceToNow(rule.last_updated) : "Never"}
                    </td>
                  </tr>
                {/each}
              {/if}
            </tbody>
          </table>
        </div>
      </section>

      <section class="bg-card rounded-lg border border-border p-5">
        <h2 class="text-lg font-semibold text-foreground mb-4">Protected Items</h2>
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
                <tr>
                  <td colspan="5" class="py-6 text-center text-muted-foreground">
                    No protected items found.
                  </td>
                </tr>
              {:else}
                {#each items as item}
                  <tr class="border-b border-border/60">
                    <td class="py-2 text-foreground break-all">{item.path}</td>
                    <td class="py-2 text-muted-foreground">{item.reason}</td>
                    <td class="py-2 text-foreground">{item.provider}</td>
                    <td class="py-2 text-muted-foreground">{item.expiration ?? "Never"}</td>
                    <td class="py-2 text-foreground">{item.status}</td>
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
