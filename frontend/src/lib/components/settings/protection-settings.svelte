<script lang="ts">
  import { onMount } from "svelte";
  import { get_api, post_api } from "$lib/api";
  import { Button } from "$lib/components/ui/button/index.js";
  import Spinner from "$lib/components/ui/spinner/spinner.svelte";
  import TestButton from "$lib/components/test-button.svelte";
  import Save from "@lucide/svelte/icons/save";

  type TestStatus = "idle" | "loading" | "success" | "error";

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

  let saving = $state(false);
  let syncing = $state(false);
  let testStatus = $state<TestStatus>("idle");
  let message = $state("");
  let error = $state("");

  let providerDefinition = $state<ProtectionProviderDefinition | null>(null);
  let config = $state<ProtectionConfig | null>(null);
  let form = $state<Record<string, string | boolean>>({
    provider: "reclaimerr",
    auth_method: "web_login",
    base_url: "",
    username: "",
    password: "",
    enabled: true,
  });

  let status = $state<ProtectionStatus | null>(null);

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
    const [definitionPayload, configPayload, statusPayload] = await Promise.all([
      get_api<ProtectionProviderDefinition>("/api/protection/provider"),
      get_api<ProtectionConfig>("/api/protection/config"),
      get_api<ProtectionStatus>("/api/protection/status"),
    ]);
    providerDefinition = definitionPayload;
    config = configPayload;
    form = {
      provider: configPayload.provider,
      auth_method: configPayload.auth_method,
      base_url: configPayload.base_url,
      username: configPayload.username,
      password: "",
      enabled: configPayload.enabled,
    };
    status = statusPayload;
  };

  const testConnection = async () => {
    testStatus = "loading";
    try {
      status = await post_api<ProtectionStatus>("/api/protection/test", {
        provider: getFieldValue("provider"),
        auth_method: getFieldValue("auth_method"),
        base_url: getFieldValue("base_url"),
        username: getFieldValue("username"),
        password: getFieldValue("password"),
        enabled: Boolean(form.enabled),
      });
      message = status.message ?? "Authenticated";
      error = "";
      testStatus = status.connected ? "success" : "error";
    } catch (e: any) {
      error = e?.message ?? "Connection test failed";
      message = "";
      testStatus = "error";
    }
  };

  const save = async () => {
    saving = true;
    try {
      config = await post_api<ProtectionConfig>("/api/protection/config", {
        provider: getFieldValue("provider"),
        auth_method: getFieldValue("auth_method"),
        base_url: getFieldValue("base_url"),
        username: getFieldValue("username"),
        password: getFieldValue("password"),
        enabled: Boolean(form.enabled),
      });
      form = { ...form, password: "" };
      status = await get_api<ProtectionStatus>("/api/protection/status");
      message = "Configuration Saved";
      error = "";
    } catch (e: any) {
      error = e?.message ?? "Failed to save Protection settings";
      message = "";
    } finally {
      saving = false;
    }
  };

  const syncNow = async () => {
    syncing = true;
    try {
      status = await post_api<ProtectionStatus>("/api/protection/sync", {});
      message = status.message ?? "Sync completed";
      error = "";
    } catch (e: any) {
      error = e?.message ?? "Failed to sync Protection";
      message = "";
    } finally {
      syncing = false;
    }
  };

  onMount(async () => {
    await loadConfig();
  });
</script>

<div class="space-y-4">
  <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
    <div class="space-y-4 rounded-lg border border-border bg-card p-4">
      <h3 class="text-sm font-semibold text-foreground">Protection Provider</h3>
      <label class="space-y-1 block">
        <span class="text-sm text-muted-foreground">Provider</span>
        <input
          value={providerDefinition?.display_name ?? "Reclaimerr"}
          disabled
          class="w-full rounded-md border border-border bg-secondary/40 px-3 py-2 text-foreground"
        />
      </label>

      <label class="space-y-1 block">
        <span class="text-sm text-muted-foreground">Authentication Method</span>
        <input
          value={providerDefinition ? formatAuthType(providerDefinition.authentication.type) : "Web Login"}
          disabled
          class="w-full rounded-md border border-border bg-secondary/40 px-3 py-2 text-foreground"
        />
      </label>

      {#each providerDefinition?.authentication.fields ?? [] as field (field.name)}
        <label class="space-y-1 block">
          <span class="text-sm text-muted-foreground">{field.label}</span>
          <input
            value={getFieldValue(field.name)}
            oninput={(event) => setFieldValue(field.name, event.currentTarget.value)}
            type={inputTypeForField(field)}
            class="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
            placeholder={placeholderForField(field)}
            required={field.required}
          />
        </label>
      {/each}
    </div>

    <div class="space-y-3 rounded-lg border border-border bg-card p-4">
      <h3 class="text-sm font-semibold text-foreground">Connection Status</h3>
      <div class="grid grid-cols-2 gap-2 text-sm">
        <span class="text-muted-foreground">Provider</span>
        <span class="text-foreground">{status?.provider ?? "Reclaimerr"}</span>
        <span class="text-muted-foreground">Authentication</span>
        <span class="text-foreground">{status?.authenticated ? "Authenticated" : "Not Authenticated"}</span>
        <span class="text-muted-foreground">Version</span>
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
    </div>
  </div>

  <div class="flex flex-wrap items-center gap-3">
    <TestButton
      onclick={testConnection}
      disabled={saving || syncing}
      status={testStatus}
      class="cursor-pointer"
      size="default"
    >
      Test Connection
    </TestButton>
    <Button onclick={save} disabled={saving || syncing} class="cursor-pointer gap-2">
      {#if saving}
        <Spinner class="size-4" />
      {:else}
        <Save class="size-4" />
      {/if}
      Save
    </Button>
    <Button
      onclick={syncNow}
      disabled={syncing || !(status?.connected ?? false)}
      class="cursor-pointer"
      variant="outline"
    >
      {syncing ? "Syncing..." : "Sync Now"}
    </Button>
  </div>

  {#if testStatus === "loading"}
    <p class="text-sm text-muted-foreground">Connecting...</p>
  {/if}
  {#if message}
    <p class="text-sm text-green-500">{message}</p>
  {/if}
  {#if error}
    <p class="text-sm text-destructive">{error}</p>
  {/if}
</div>
