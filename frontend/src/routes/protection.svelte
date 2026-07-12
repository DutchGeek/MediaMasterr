<script lang="ts">
  import { onMount } from "svelte";
  import { get_api, post_api } from "$lib/api";
  import { VERSION } from "$lib/version";
  import { Button } from "$lib/components/ui/button/index.js";
  import Spinner from "$lib/components/ui/spinner/spinner.svelte";
  import BrandLogo from "$lib/components/brand-logo.svelte";
  import { formatDate, formatDistanceToNow } from "$lib/utils/date";
  import { formatFileSize } from "$lib/utils/formatters";
  import ErrorBox from "$lib/components/error-box.svelte";

  type ProtectionConfig = {
    provider: string;
    auth_method: string;
    base_url: string;
    username: string;
    password_configured: boolean;
    configured_auth_fields: string[];
    enabled: boolean;
  };

  type ProtectionAuthField = {
    name: string;
    label: string;
    required: boolean;
    secret?: boolean;
  };

  type ProtectionProviderDefinition = {
    provider: string;
    display_name: string;
    authentication: {
      type: string;
      fields: ProtectionAuthField[];
    };
  };

  type ProtectionConfigForm = Record<string, string | boolean> & {
    provider: string;
    auth_method: string;
    base_url: string;
    username: string;
    password: string;
    enabled: boolean;
  };

  type ProtectionStatus = {
    connected: boolean;
    authenticated: boolean;
    provider: string;
    auth_method: string;
    connection_status: string;
    authentication_status: string;
    base_url: string | null;
    provider_version: string | null;
    last_login: string | null;
    last_sync: string | null;
    capabilities: string[];
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

  let providerDefinition = $state<ProtectionProviderDefinition | null>(null);
  let config = $state<ProtectionConfig | null>(null);
  let form = $state<ProtectionConfigForm>({
    provider: "reclaimerr",
    auth_method: "web_login",
    base_url: "",
    username: "",
    password: "",
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

  const formatAuthType = (value: string): string =>
    value
      .split("_")
      .filter(Boolean)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");

  const getFieldValue = (fieldName: string): string => {
    const value = form[fieldName];
    return typeof value === "string" ? value : "";
  };

  const setFieldValue = (fieldName: string, value: string): void => {
    form = { ...form, [fieldName]: value };
  };

  const isFieldConfigured = (fieldName: string): boolean =>
    config?.configured_auth_fields.includes(fieldName) ?? false;

  const inputTypeForField = (field: ProtectionAuthField): string =>
    field.secret ? "password" : "text";

  const placeholderForField = (field: ProtectionAuthField): string => {
    if (field.secret && isFieldConfigured(field.name)) {
      return `Saved ${field.label.toLowerCase()} configured`;
    }
    return `Enter ${field.label.toLowerCase()}`;
  };

  const loadConfig = async () => {
    const [definitionPayload, configPayload] = await Promise.all([
      get_api<ProtectionProviderDefinition>("/api/protection/provider"),
      get_api<ProtectionConfig>("/api/protection/config"),
    ]);
    providerDefinition = definitionPayload;
    config = configPayload;
    form = {
      provider: configPayload.provider,
      auth_method: configPayload.auth_method,
      base_url: configPayload.base_url,
      username: configPayload.username,
      password: "",
      enabled: true,
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
        provider: getFieldValue("provider"),
        auth_method: getFieldValue("auth_method"),
        base_url: getFieldValue("base_url"),
        username: getFieldValue("username"),
        password: getFieldValue("password"),
        enabled: true,
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
        provider: getFieldValue("provider"),
        auth_method: getFieldValue("auth_method"),
        base_url: getFieldValue("base_url"),
        username: getFieldValue("username"),
        password: getFieldValue("password"),
        enabled: true,
      });
      form = { ...form, password: "" };
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
        <BrandLogo widthClass="w-[180px]" />
        <div>
          <h1 class="text-3xl font-bold text-foreground">Protection</h1>
          <p class="text-sm text-muted-foreground">
            Provider: {providerDefinition?.display_name ?? "Reclaimerr"}
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
      <section class="rounded-lg border border-border bg-card p-5 md:p-6 space-y-3">
        <h2 class="text-lg font-semibold text-foreground">Settings</h2>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div class="space-y-4 rounded-lg border border-border bg-card p-4 h-full">
            <h3 class="text-sm font-semibold text-foreground">Protection Provider</h3>
            <label class="space-y-2 block">
              <span class="text-sm text-muted-foreground">Provider</span>
              <input
                value={providerDefinition?.display_name ?? "Reclaimerr"}
                disabled
                class="w-full rounded-md border border-border bg-secondary/40 px-3 py-2 text-foreground"
              />
            </label>

            <label class="space-y-2 block">
              <span class="text-sm text-muted-foreground">Authentication Method</span>
              <input
                value={providerDefinition ? formatAuthType(providerDefinition.authentication.type) : "Web Login"}
                disabled
                class="w-full rounded-md border border-border bg-secondary/40 px-3 py-2 text-foreground"
              />
            </label>

            {#each providerDefinition?.authentication.fields ?? [] as field (field.name)}
              <label class="space-y-2 block">
                <span class="text-sm text-muted-foreground">{field.label}</span>
                <input
                  type={inputTypeForField(field)}
                  value={getFieldValue(field.name)}
                  oninput={(event) => setFieldValue(field.name, event.currentTarget.value)}
                  placeholder={placeholderForField(field)}
                  class="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                  required={field.required}
                />
              </label>
            {/each}
          </div>

          <div class="space-y-3 rounded-lg border border-border bg-card p-4 h-full">
            <h3 class="text-sm font-semibold text-foreground">Connection Status</h3>
            <div class="grid grid-cols-2 gap-2 text-sm">
              <span class="text-muted-foreground">Connection</span>
              <span class="text-foreground">{status?.connected ? "Connected" : "Disconnected"}</span>
              <span class="text-muted-foreground">Authentication</span>
              <span class="text-foreground">{status?.authenticated ? "Authenticated" : "Not Authenticated"}</span>
              <span class="text-muted-foreground">Provider</span>
              <span class="text-foreground">{status?.provider ?? "Reclaimerr"}</span>
              <span class="text-muted-foreground">Provider Version</span>
              <span class="text-foreground">{status?.provider_version || "Unknown"}</span>
              <span class="text-muted-foreground">Last Login</span>
              <span class="text-foreground">{status?.last_login || "Never"}</span>
              <span class="text-muted-foreground">Last Sync</span>
              <span class="text-foreground">{status?.last_sync || "Never"}</span>
            </div>

            <div>
              <p class="text-sm text-muted-foreground mb-1">Capabilities</p>
              <ul class="space-y-1 text-sm text-foreground">
                {#each status?.capabilities ?? [] as capability}
                  <li>✓ {capability}</li>
                {/each}
              </ul>
            </div>

            {#if status?.message}
              <p class="text-sm text-muted-foreground">{status.message}</p>
            {/if}
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <Button onclick={testConnection} disabled={testing || saving || syncing} variant="secondary" class="cursor-pointer gap-2">
            {#if testing}
              <Spinner class="size-4" />
            {/if}
            Test Connection
          </Button>
          <Button onclick={saveSettings} disabled={saving || testing || syncing} class="cursor-pointer gap-2">
            {#if saving}
              <Spinner class="size-4" />
            {/if}
            Save
          </Button>
          <Button
            onclick={syncNow}
            disabled={syncing || !isConnected || testing || saving}
            variant="outline"
            class="cursor-pointer gap-2"
          >
            {#if syncing}
              <Spinner class="size-4" />
            {/if}
            Sync Now
          </Button>
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
