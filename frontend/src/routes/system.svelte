<script lang="ts">
  import { onMount } from "svelte";
  import { get_api, post_api } from "$lib/api";
  import { toast } from "svelte-sonner";
  import { formatDistanceToNow } from "$lib/utils/date";
  import { formatFileSize } from "$lib/utils/formatters";

  type HealthResponse = { status: string };
  type VersionResponse = { version: string; program: string; url: string };
  type TaskItem = {
    id: string;
    name: string;
    status: string;
    next_run: string | null;
    last_run: string | null;
    schedule_type: string;
    enabled: boolean;
  };
  type TasksResponse = {
    tasks: TaskItem[];
    has_main_server: boolean;
  };
  type ServiceInstance = {
    id: number;
    name: string;
    enabled: boolean;
    base_url: string;
    api_key: string;
    extra_settings?: Record<string, unknown>;
    is_main?: boolean | null;
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

  type ProviderDiagnosticStatus = "healthy" | "degraded" | "down";

  type ProviderDiagnostic = {
    key: string;
    name: string;
    endpoint: string | null;
    connected: boolean;
    version: string;
    responseTimeMs: number | null;
    lastSuccessfulSync: string | null;
    lastAttempt: string | null;
    status: ProviderDiagnosticStatus;
    reason: string | null;
    lastError: string | null;
    httpStatus: number | null;
    apiVersion?: string | null;
  };

  type SystemDiagnosticsResponse = {
    health: {
      backend: "healthy" | "degraded" | "down";
      database: "healthy" | "degraded" | "down";
      scheduler: "healthy" | "degraded" | "down";
      decision_engine: "healthy" | "degraded" | "down";
      event_engine: "healthy" | "degraded" | "down";
    };
    providers: ProviderDiagnostic[];
    scheduler: {
      running: boolean;
      job_count: number;
      total_tasks: number;
      enabled_tasks: number;
      running_jobs: number;
    };
    diagnostics: {
      database_size_bytes: number | null;
      cached_objects: number;
      memory_usage_mb: number | null;
      running_jobs: number;
      queue_size: number;
    };
  };

  let loading = $state(true);
  let error = $state("");

  let backendStatus = $state<"healthy" | "degraded" | "down">("down");
  let databaseStatus = $state<"healthy" | "degraded" | "down">("healthy");
  let schedulerStatus = $state<"healthy" | "degraded" | "down">("healthy");
  let decisionEngineStatus = $state<"healthy" | "degraded" | "down">("healthy");
  let eventEngineStatus = $state<"healthy" | "degraded" | "down">("healthy");
  let apiVersion = $state("n/a");
  let programName = $state("MediaMasterr");
  let startedAt = $state(Date.now());

  let providers = $state<ProviderDiagnostic[]>([]);
  let systemDiagnostics = $state<SystemDiagnosticsResponse | null>(null);

  let tasks = $state<TaskItem[]>([]);
  let logs = $state<string[]>([]);

  const uptimeLabel = $derived.by(() => {
    const elapsedMs = Date.now() - startedAt;
    const seconds = Math.floor(elapsedMs / 1000);
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${minutes}m`;
  });

  const statusClass = (status: "healthy" | "degraded" | "down") => {
    if (status === "healthy") return "bg-green-500";
    if (status === "degraded") return "bg-yellow-500";
    return "bg-destructive";
  };

  const statusLabel = (status: "healthy" | "degraded" | "down") => {
    if (status === "healthy") return "Healthy";
    if (status === "degraded") return "Degraded";
    return "Down";
  };

  const formatTimestamp = (value: string | null): string => {
    if (!value) return "n/a";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return parsed.toLocaleString();
  };

  const formatResponseTime = (value: number | null): string => {
    if (value == null) return "n/a";
    return `${value.toFixed(0)} ms`;
  };

  const normalizeProviderStatus = (
    value: string | null | undefined,
  ): ProviderDiagnosticStatus => {
    const lowered = (value ?? "").toLowerCase();
    if (lowered === "healthy" || lowered === "connected") return "healthy";
    if (lowered === "degraded" || lowered === "warning") return "degraded";
    return "down";
  };

  const probeProtectionDiagnostics = (
    protectionStatus: ProtectionStatus,
  ): ProviderDiagnostic => ({
    key: "protection",
    name: "Protection",
    endpoint: protectionStatus.base_url,
    connected: protectionStatus.connected && protectionStatus.authenticated,
    version: protectionStatus.provider_version ?? "n/a",
    responseTimeMs: null,
    lastSuccessfulSync: protectionStatus.last_sync,
    lastAttempt: protectionStatus.last_login,
    status: normalizeProviderStatus(protectionStatus.connection_status),
    reason: protectionStatus.message,
    lastError: protectionStatus.message,
    httpStatus: null,
    apiVersion: null,
  });

  const runMaintenanceAction = async (taskId: string, label: string) => {
    try {
      await post_api(`/api/tasks/tasks/${taskId}/run`, {});
      toast.success(`${label} started`);
      await loadAll();
    } catch (e: any) {
      toast.error(e?.message ?? `Failed to run ${label}`);
    }
  };

  const loadAll = async () => {
    loading = true;
    error = "";
    try {
      const [health, version, diagnostics, taskPayload, protectionStatus] =
        await Promise.all([
          get_api<HealthResponse>("/api/info/health"),
          get_api<VersionResponse>("/api/info/version"),
          get_api<SystemDiagnosticsResponse>("/api/system/diagnostics"),
          get_api<TasksResponse>("/api/tasks/tasks"),
          get_api<ProtectionStatus>("/api/protection/status"),
        ]);

      backendStatus =
        diagnostics.health.backend ??
        (health.status === "ok" ? "healthy" : "degraded");
      databaseStatus = diagnostics.health.database ?? "degraded";
      schedulerStatus = diagnostics.health.scheduler ?? "degraded";
      decisionEngineStatus = diagnostics.health.decision_engine ?? "degraded";
      eventEngineStatus = diagnostics.health.event_engine ?? "degraded";
      apiVersion = version.version;
      programName = version.program;
      systemDiagnostics = diagnostics;

      const diagnosticsProviders = diagnostics.providers;
      const hasProtectionProvider = diagnosticsProviders.some(
        (provider) => provider.key === "protection",
      );
      providers = hasProtectionProvider
        ? diagnosticsProviders
        : [
            ...diagnosticsProviders,
            probeProtectionDiagnostics(protectionStatus),
          ];

      tasks = taskPayload.tasks;

      logs = [];
      for (const task of taskPayload.tasks.slice(0, 5)) {
        if (task.status.toLowerCase() === "error") {
          logs.push(`${task.name}: recent execution error`);
        }
      }
      if (logs.length === 0) {
        logs.push("No recent critical errors");
      }
    } catch (e: any) {
      error = e?.message ?? "Failed to load Operations Center";
      backendStatus = "down";
      schedulerStatus = "degraded";
      decisionEngineStatus = "degraded";
      eventEngineStatus = "degraded";
    } finally {
      loading = false;
    }
  };

  onMount(async () => {
    startedAt = Date.now();
    await loadAll();
  });
</script>

<div class="p-2.5 md:p-8">
  <div class="max-w-7xl mx-auto space-y-6">
    <div>
      <h1 class="text-3xl font-bold text-foreground">System</h1>
      <p class="text-muted-foreground">
        Operations Center for runtime health, providers, jobs, and diagnostics.
      </p>
    </div>

    {#if error}
      <div
        class="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
      >
        {error}
      </div>
    {/if}

    {#if loading}
      <div
        class="rounded-lg border border-border bg-card p-8 text-center text-muted-foreground"
      >
        Loading Operations Center...
      </div>
    {:else}
      <section class="bg-card rounded-lg border border-border p-5">
        <h2 class="text-lg font-semibold text-foreground mb-4">
          System Health
        </h2>
        <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
          {#each [{ label: "Backend Status", value: backendStatus }, { label: "Database Status", value: databaseStatus }, { label: "Scheduler Status", value: schedulerStatus }, { label: "Decision Engine", value: decisionEngineStatus }, { label: "Event Engine", value: eventEngineStatus }] as health}
            <article
              class="rounded-lg border border-border bg-background/40 p-3"
            >
              <p class="text-xs text-muted-foreground">{health.label}</p>
              <div class="mt-2 flex items-center gap-2">
                <span
                  class={`inline-block size-2.5 rounded-full ${statusClass(health.value)}`}
                ></span>
                <span class="text-sm font-medium text-foreground"
                  >{statusLabel(health.value)}</span
                >
              </div>
            </article>
          {/each}
          <article class="rounded-lg border border-border bg-background/40 p-3">
            <p class="text-xs text-muted-foreground">API Version</p>
            <p class="mt-2 text-sm font-medium text-foreground">{apiVersion}</p>
          </article>
          <article class="rounded-lg border border-border bg-background/40 p-3">
            <p class="text-xs text-muted-foreground">Uptime</p>
            <p class="mt-2 text-sm font-medium text-foreground">
              {uptimeLabel}
            </p>
          </article>
        </div>
      </section>

      <section class="bg-card rounded-lg border border-border p-5">
        <h2 class="text-lg font-semibold text-foreground mb-4">
          Provider Diagnostics
        </h2>
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {#each providers as provider}
            <article
              class="rounded-lg border border-border bg-background/40 p-4"
            >
              <div class="flex items-center justify-between gap-2">
                <h3 class="text-sm font-semibold text-foreground">
                  {provider.name}
                </h3>
                <span
                  class={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${provider.status === "healthy" ? "bg-green-500/20 text-green-500" : provider.status === "degraded" ? "bg-yellow-500/20 text-yellow-500" : "bg-destructive/20 text-destructive"}`}
                >
                  {statusLabel(provider.status)}
                </span>
              </div>

              <dl class="mt-3 space-y-1 text-xs">
                <div class="flex justify-between gap-2">
                  <dt class="text-muted-foreground">Connected</dt>
                  <dd class="text-foreground">
                    {provider.connected ? "Yes" : "No"}
                  </dd>
                </div>
                <div class="flex justify-between gap-2">
                  <dt class="text-muted-foreground">Version</dt>
                  <dd class="text-foreground">{provider.version}</dd>
                </div>
                <div class="flex justify-between gap-2">
                  <dt class="text-muted-foreground">Response Time</dt>
                  <dd class="text-foreground">
                    {formatResponseTime(provider.responseTimeMs)}
                  </dd>
                </div>
                <div class="flex justify-between gap-2">
                  <dt class="text-muted-foreground">Last Successful Sync</dt>
                  <dd class="text-foreground">
                    {formatTimestamp(provider.lastSuccessfulSync)}
                  </dd>
                </div>
                <div class="flex justify-between gap-2">
                  <dt class="text-muted-foreground">Last Attempt</dt>
                  <dd class="text-foreground">
                    {formatTimestamp(provider.lastAttempt)}
                  </dd>
                </div>
                <div class="flex justify-between gap-2">
                  <dt class="text-muted-foreground">API Version</dt>
                  <dd class="text-foreground">
                    {provider.apiVersion ?? "n/a"}
                  </dd>
                </div>
                <div class="flex justify-between gap-2">
                  <dt class="text-muted-foreground">Status</dt>
                  <dd class="text-foreground">
                    {statusLabel(provider.status)}
                  </dd>
                </div>
                <div class="flex justify-between gap-2">
                  <dt class="text-muted-foreground">Reason</dt>
                  <dd
                    class="text-foreground text-right max-w-[65%] break-words"
                  >
                    {provider.reason ?? "n/a"}
                  </dd>
                </div>
                <div class="flex justify-between gap-2">
                  <dt class="text-muted-foreground">Endpoint</dt>
                  <dd
                    class="text-foreground text-right max-w-[65%] break-words"
                  >
                    {provider.endpoint ?? "n/a"}
                  </dd>
                </div>
                <div class="flex justify-between gap-2">
                  <dt class="text-muted-foreground">HTTP</dt>
                  <dd class="text-foreground">
                    {provider.httpStatus ?? "n/a"}
                  </dd>
                </div>
                <div class="flex justify-between gap-2">
                  <dt class="text-muted-foreground">Last Error</dt>
                  <dd
                    class="text-foreground text-right max-w-[65%] break-words"
                  >
                    {provider.lastError ?? "None"}
                  </dd>
                </div>
              </dl>
            </article>
          {/each}
        </div>
      </section>

      <section class="bg-card rounded-lg border border-border p-5">
        <h2 class="text-lg font-semibold text-foreground mb-4">Maintenance</h2>
        <div class="flex flex-wrap gap-2">
          <button
            class="rounded-md border border-border px-3 py-2 text-sm cursor-pointer hover:bg-secondary/40"
            onclick={() =>
              runMaintenanceAction("sync_media", "Refresh All Providers")}
            >Refresh All Providers</button
          >
          <button
            class="rounded-md border border-border px-3 py-2 text-sm cursor-pointer hover:bg-secondary/40"
            onclick={() =>
              runMaintenanceAction(
                "scan_cleanup_candidates",
                "Recalculate Decision Engine",
              )}>Recalculate Decision Engine</button
          >
          <button
            class="rounded-md border border-border px-3 py-2 text-sm cursor-pointer hover:bg-secondary/40"
            onclick={() =>
              runMaintenanceAction(
                "sync_linked_data",
                "Recalculate Event Engine",
              )}>Recalculate Event Engine</button
          >
          <button
            class="rounded-md border border-border px-3 py-2 text-sm cursor-pointer hover:bg-secondary/40"
            onclick={() =>
              runMaintenanceAction("sync_linked_data", "Refresh Metadata")}
            >Refresh Metadata</button
          >
          <button
            class="rounded-md border border-border px-3 py-2 text-sm cursor-pointer hover:bg-secondary/40"
            onclick={() =>
              runMaintenanceAction("weekly_house_keeping", "Clear Cache")}
            >Clear Cache</button
          >
          <button
            class="rounded-md border border-border px-3 py-2 text-sm cursor-pointer hover:bg-secondary/40"
            onclick={() =>
              runMaintenanceAction(
                "scan_cleanup_candidates",
                "Rebuild Statistics",
              )}>Rebuild Statistics</button
          >
          <button
            class="rounded-md border border-border px-3 py-2 text-sm cursor-pointer hover:bg-secondary/40"
            onclick={() =>
              runMaintenanceAction("sync_media", "Reload Configuration")}
            >Reload Configuration</button
          >
        </div>
      </section>

      <section class="bg-card rounded-lg border border-border p-5">
        <h2 class="text-lg font-semibold text-foreground mb-4">
          Scheduled Jobs
        </h2>
        <div class="overflow-x-auto">
          <table class="w-full min-w-[720px] text-sm">
            <thead class="text-left text-muted-foreground">
              <tr class="border-b border-border">
                <th class="py-2">Job</th>
                <th class="py-2">Status</th>
                <th class="py-2">Last Run</th>
                <th class="py-2">Next Scheduled Run</th>
              </tr>
            </thead>
            <tbody>
              {#if tasks.length === 0}
                <tr
                  ><td
                    colspan="4"
                    class="py-4 text-center text-muted-foreground"
                    >No jobs available.</td
                  ></tr
                >
              {:else}
                {#each tasks as task}
                  <tr class="border-b border-border/60">
                    <td class="py-2 text-foreground">{task.name}</td>
                    <td class="py-2 text-foreground">{task.status}</td>
                    <td class="py-2 text-muted-foreground"
                      >{task.last_run
                        ? formatDistanceToNow(task.last_run)
                        : "Never"}</td
                    >
                    <td class="py-2 text-muted-foreground"
                      >{task.next_run
                        ? formatDistanceToNow(task.next_run)
                        : "Manual"}</td
                    >
                  </tr>
                {/each}
              {/if}
            </tbody>
          </table>
        </div>
      </section>

      <section class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <article class="bg-card rounded-lg border border-border p-5">
          <h2 class="text-lg font-semibold text-foreground mb-3">Logs</h2>
          <ul class="space-y-2 text-sm">
            {#each logs as line}
              <li class="text-muted-foreground">{line}</li>
            {/each}
          </ul>
        </article>

        <article class="bg-card rounded-lg border border-border p-5">
          <h2 class="text-lg font-semibold text-foreground mb-3">
            Diagnostics
          </h2>
          <dl class="space-y-2 text-sm">
            <div class="flex justify-between">
              <dt class="text-muted-foreground">Program</dt>
              <dd class="text-foreground">{programName}</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-muted-foreground">Database Size</dt>
              <dd class="text-foreground">
                {systemDiagnostics?.diagnostics.database_size_bytes != null
                  ? formatFileSize(
                      systemDiagnostics.diagnostics.database_size_bytes,
                    )
                  : "n/a"}
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-muted-foreground">Cached Objects</dt>
              <dd class="text-foreground">
                {systemDiagnostics?.diagnostics.cached_objects ?? 0}
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-muted-foreground">Memory Usage</dt>
              <dd class="text-foreground">
                {systemDiagnostics?.diagnostics.memory_usage_mb != null
                  ? `${systemDiagnostics.diagnostics.memory_usage_mb.toFixed(1)} MB`
                  : "n/a"}
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-muted-foreground">Running Jobs</dt>
              <dd class="text-foreground">
                {tasks.filter((t) => t.status.toLowerCase() === "running")
                  .length}
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-muted-foreground">Queue Sizes</dt>
              <dd class="text-foreground">
                {systemDiagnostics?.diagnostics.queue_size ?? 0}
              </dd>
            </div>
          </dl>
        </article>
      </section>
    {/if}
  </div>
</div>
