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
    base_url: string;
    api_key_configured: boolean;
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

  let saving = $state(false);
  let syncing = $state(false);
  let testStatus = $state<TestStatus>("idle");
  let message = $state("");
  let error = $state("");

  let config = $state<ProtectionConfig | null>(null);
  let form = $state({
    provider: "reclaimerr",
    base_url: "",
    api_key: "",
    enabled: true,
  });

  let status = $state<ProtectionStatus | null>(null);

  const loadConfig = async () => {
    config = await get_api<ProtectionConfig>("/api/protection/config");
    form = {
      provider: config.provider,
      base_url: config.base_url,
      api_key: "",
      enabled: config.enabled,
    };
    status = await get_api<ProtectionStatus>("/api/protection/status");
  };

  const testConnection = async () => {
    testStatus = "loading";
    try {
      status = await post_api<ProtectionStatus>("/api/protection/test", {
        provider: form.provider,
        base_url: form.base_url,
        api_key: form.api_key,
        enabled: form.enabled,
      });
      message = status.message ?? "Connection successful";
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
        provider: form.provider,
        base_url: form.base_url,
        api_key: form.api_key,
        enabled: form.enabled,
      });
      form.api_key = "";
      status = await get_api<ProtectionStatus>("/api/protection/status");
      message = "Protection settings saved";
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
    <label class="space-y-1">
      <span class="text-sm text-muted-foreground">Provider</span>
      <input
        value="Reclaimerr"
        disabled
        class="w-full rounded-md border border-border bg-secondary/40 px-3 py-2 text-foreground"
      />
    </label>

    <label class="space-y-1">
      <span class="text-sm text-muted-foreground">URL</span>
      <input
        bind:value={form.base_url}
        class="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
        placeholder="e.g. https://reclaimerr.internal"
      />
    </label>

    <label class="space-y-1">
      <span class="text-sm text-muted-foreground">API Key</span>
      <input
        bind:value={form.api_key}
        class="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
        placeholder={config?.api_key_configured ? "Saved key configured" : "Enter API key"}
      />
    </label>

    <label class="space-y-1">
      <span class="text-sm text-muted-foreground">Connection Status</span>
      <input
        value={status?.connection_status ?? "unknown"}
        disabled
        class="w-full rounded-md border border-border bg-secondary/40 px-3 py-2 text-foreground"
      />
    </label>
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

  {#if status?.last_sync}
    <p class="text-xs text-muted-foreground">Last sync: {status.last_sync}</p>
  {/if}
  {#if message}
    <p class="text-sm text-green-500">{message}</p>
  {/if}
  {#if error}
    <p class="text-sm text-destructive">{error}</p>
  {/if}
</div>
