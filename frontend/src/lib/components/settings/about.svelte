<script lang="ts">
  import { onMount } from "svelte";
  import type { Component } from "svelte";
  import Markdown from "svelte-exmarkdown";
  import { gfmPlugin } from "svelte-exmarkdown/gfm";

  import { get_api } from "$lib/api";
  import { BRANDING } from "$lib/branding";
  import BrandLogo from "$lib/components/brand-logo.svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import Spinner from "$lib/components/ui/spinner/spinner.svelte";
  import * as Select from "$lib/components/ui/select/index.js";

  interface Release {
    version: string;
    date: string | null;
    body: string;
  }

  interface VersionInfo {
    application_version: string;
    git_sha: string | null;
    short_sha: string | null;
    branch: string | null;
    tag: string | null;
    build_date: string | null;
    build_time: string | null;
    build_timestamp: string | null;
    github_workflow_run: string | null;
    github_run_number: string | null;
    github_repository: string | null;
    docker_image_tag: string | null;
    docker_image_digest: string | null;
    python_version: string;
    backend_version: string;
    frontend_version: string | null;
    startup_time: string;
    environment: string;
    container_id: string;
    hostname: string;
    running_sha: string | null;
    latest_built_sha: string | null;
    frontend_sha: string | null;
    backend_sha: string | null;
    status: string;
  }

  interface Props {
    svgIcon: Component | null;
  }
  let { svgIcon }: Props = $props();

  const mdPlugins = [gfmPlugin()];

  let loading = $state(true);
  let versionError = $state<string | null>(null);
  let changelogError = $state<string | null>(null);
  let releases = $state<Release[]>([]);
  let selectedIndex = $state(0);
  let versionInfo = $state<VersionInfo | null>(null);
  let lastRefreshedAt = $state<string | null>(null);

  const selected = $derived(releases[selectedIndex] ?? null);

  const displayValue = (value: string | null | undefined): string =>
    value && value.trim() ? value : "Unavailable";

  const apiStatus = $derived(
    versionInfo?.status && versionInfo.status.trim()
      ? versionInfo.status
      : "Unavailable",
  );

  const hasVersionMismatch = $derived(apiStatus === "Version Mismatch");

  const loadData = async () => {
    loading = true;
    versionError = null;
    changelogError = null;

    const [releaseResult, versionResult] = await Promise.allSettled([
      get_api<Release[]>("/api/info/changelog"),
      get_api<VersionInfo>("/api/info/version"),
    ]);

    if (releaseResult.status === "fulfilled") {
      releases = releaseResult.value;
    } else {
      changelogError =
        releaseResult.reason instanceof Error
          ? releaseResult.reason.message
          : "Failed to load release notes.";
    }

    if (versionResult.status === "fulfilled") {
      versionInfo = versionResult.value;
    } else {
      versionInfo = null;
      versionError =
        versionResult.reason instanceof Error
          ? versionResult.reason.message
          : "Failed to load runtime metadata.";
    }

    const currentVersion = versionInfo?.application_version ?? null;
    const match = releases.findIndex((r) => r.version === currentVersion);
    selectedIndex = match >= 0 ? match : 0;
    lastRefreshedAt = new Date().toISOString();
    loading = false;
  };

  const refreshDiagnostics = async () => {
    await loadData();
  };

  const buildSystemReport = () =>
    [
      `${BRANDING.applicationName} System Information`,
      `Generated: ${new Date().toISOString()}`,
      `Application version: ${displayValue(versionInfo?.application_version)}`,
      `Running SHA: ${displayValue(versionInfo?.running_sha)}`,
      `Latest built SHA: ${displayValue(versionInfo?.latest_built_sha)}`,
      `Frontend SHA: ${displayValue(versionInfo?.frontend_sha)}`,
      `Backend SHA: ${displayValue(versionInfo?.backend_sha)}`,
      `Status: ${displayValue(versionInfo?.status)}`,
      `Git SHA: ${displayValue(versionInfo?.git_sha)}`,
      `Short SHA: ${displayValue(versionInfo?.short_sha)}`,
      `Branch: ${displayValue(versionInfo?.branch)}`,
      `Tag: ${displayValue(versionInfo?.tag)}`,
      `Build date: ${displayValue(versionInfo?.build_date)}`,
      `Build time: ${displayValue(versionInfo?.build_time)}`,
      `Build timestamp: ${displayValue(versionInfo?.build_timestamp)}`,
      `GitHub workflow run: ${displayValue(versionInfo?.github_workflow_run)}`,
      `GitHub run number: ${displayValue(versionInfo?.github_run_number)}`,
      `GitHub repository: ${displayValue(versionInfo?.github_repository)}`,
      `Docker image tag: ${displayValue(versionInfo?.docker_image_tag)}`,
      `Docker image digest: ${displayValue(versionInfo?.docker_image_digest)}`,
      `Python version: ${displayValue(versionInfo?.python_version)}`,
      `Backend version: ${displayValue(versionInfo?.backend_version)}`,
      `Frontend version: ${displayValue(versionInfo?.frontend_version)}`,
      `Startup time: ${displayValue(versionInfo?.startup_time)}`,
      `Environment: ${displayValue(versionInfo?.environment)}`,
      `Container ID: ${displayValue(versionInfo?.container_id)}`,
      `Hostname: ${displayValue(versionInfo?.hostname)}`,
      `Browser origin: ${typeof window === "undefined" ? "Unavailable" : window.location.origin}`,
      `Browser path: ${typeof window === "undefined" ? "Unavailable" : window.location.pathname}`,
      `User agent: ${typeof window === "undefined" ? "Unavailable" : window.navigator.userAgent}`,
      `Last refreshed: ${lastRefreshedAt ?? "Unavailable"}`,
    ].join("\n");

  const copySystemReport = async () => {
    const report = buildSystemReport();
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      await navigator.clipboard.writeText(report);
    }
  };

  const downloadDiagnostics = async () => {
    const report = buildSystemReport();
    const blob = new Blob([report], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `mediamasterr-diagnostics-${versionInfo?.short_sha ?? "unknown"}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  onMount(() => {
    void loadData();
  });
</script>

<div class="space-y-6">
  <div class="flex justify-center">
    <BrandLogo width={320} class="sm:w-[360px]" />
  </div>

  <div>
    <h2 class="flex items-center gap-3 text-xl font-semibold text-foreground">
      {#if svgIcon}
        {@const Icon = svgIcon}
        <Icon class="size-5" aria-hidden="true" />
      {/if}
      <span class="align-middle">System Information</span>
    </h2>
    <p class="mt-1 text-xs text-muted-foreground">
      {BRANDING.applicationName} v{displayValue(versionInfo?.application_version)}
    </p>
  </div>

  {#if hasVersionMismatch}
    <div class="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm text-amber-950 dark:text-amber-100">
      <strong>Version Mismatch</strong>
      <p class="mt-1 text-muted-foreground dark:text-amber-100/80">
        The backend and frontend build metadata do not match. Refresh the deployment or rebuild the frontend and backend together.
      </p>
    </div>
  {/if}

  <section class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
    <div class="rounded-xl border border-border/60 bg-muted/20 p-4 shadow-sm">
      <div class="flex items-center justify-between gap-3">
        <h3 class="text-sm font-semibold text-foreground">Running SHA</h3>
        <Badge class="bg-emerald-500/15 text-emerald-700 dark:text-emerald-300">
          {displayValue(versionInfo?.running_sha)}
        </Badge>
      </div>
      <p class="mt-2 text-sm leading-6 text-muted-foreground">
        Current runtime commit reported by the backend.
      </p>
    </div>

    <div class="rounded-xl border border-border/60 bg-muted/20 p-4 shadow-sm">
      <div class="flex items-center justify-between gap-3">
        <h3 class="text-sm font-semibold text-foreground">Latest Built SHA</h3>
        <Badge class="bg-sky-500/15 text-sky-700 dark:text-sky-300">
          {displayValue(versionInfo?.latest_built_sha)}
        </Badge>
      </div>
      <p class="mt-2 text-sm leading-6 text-muted-foreground">
        Commit embedded into the backend build artifact.
      </p>
    </div>

    <div class="rounded-xl border border-border/60 bg-muted/20 p-4 shadow-sm">
      <div class="flex items-center justify-between gap-3">
        <h3 class="text-sm font-semibold text-foreground">Status</h3>
        <Badge
          class={apiStatus === "Matching"
            ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
            : apiStatus === "Version Mismatch"
              ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
              : "bg-muted text-muted-foreground"}
        >
          {apiStatus}
        </Badge>
      </div>
      <p class="mt-2 text-sm leading-6 text-muted-foreground">
        Frontend and backend comparison returned by the API.
      </p>
    </div>
  </section>

  <section class="space-y-3 rounded-2xl border border-border/60 bg-card p-5 shadow-sm">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 class="text-foreground">Deployment Verification</h3>
        <p class="mt-1 text-sm text-muted-foreground">
          The backend is the single source of truth for runtime build metadata.
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onclick={() => void refreshDiagnostics()}>
          Refresh Build Info
        </Button>
        <Button size="sm" variant="secondary" onclick={() => void copySystemReport()}>
          Copy System Report
        </Button>
        <Button size="sm" variant="secondary" onclick={() => void downloadDiagnostics()}>
          Download Diagnostics
        </Button>
      </div>
    </div>

    <div class="grid gap-3 lg:grid-cols-2">
      <div class="rounded-xl border border-border/60 bg-background p-4">
        <h4 class="text-sm font-semibold text-foreground">Core build metadata</h4>
        <dl class="mt-3 space-y-2 text-sm">
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">Application version</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.application_version)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">Git SHA</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.git_sha)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">Short SHA</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.short_sha)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">Branch</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.branch)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">Tag</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.tag)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">Build date</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.build_date)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">Build time</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.build_time)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">Build timestamp</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.build_timestamp)}</dd>
          </div>
        </dl>
      </div>

      <div class="rounded-xl border border-border/60 bg-background p-4">
        <h4 class="text-sm font-semibold text-foreground">Deployment metadata</h4>
        <dl class="mt-3 space-y-2 text-sm">
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">GitHub workflow run</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.github_workflow_run)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">GitHub run number</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.github_run_number)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">GitHub repository</dt>
            <dd class="break-all text-right text-foreground">
              {#if versionInfo?.github_repository}
                <a
                  href={versionInfo.github_repository}
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-primary underline"
                >
                  {versionInfo.github_repository}
                </a>
              {:else}
                Unavailable
              {/if}
            </dd>
          </div>
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">Docker image tag</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.docker_image_tag)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">Docker image digest</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.docker_image_digest)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">Python version</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.python_version)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">Backend version</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.backend_version)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4">
            <dt class="text-muted-foreground">Frontend version</dt>
            <dd class="break-all text-right text-foreground">{displayValue(versionInfo?.frontend_version)}</dd>
          </div>
        </dl>
      </div>

      <div class="rounded-xl border border-border/60 bg-background p-4 lg:col-span-2">
        <h4 class="text-sm font-semibold text-foreground">Runtime environment</h4>
        <dl class="mt-3 grid gap-2 text-sm md:grid-cols-2">
          <div class="flex items-start justify-between gap-4 md:flex-col md:items-start md:gap-1">
            <dt class="text-muted-foreground">Startup time</dt>
            <dd class="break-all text-foreground">{displayValue(versionInfo?.startup_time)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4 md:flex-col md:items-start md:gap-1">
            <dt class="text-muted-foreground">Environment</dt>
            <dd class="break-all text-foreground">{displayValue(versionInfo?.environment)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4 md:flex-col md:items-start md:gap-1">
            <dt class="text-muted-foreground">Container ID</dt>
            <dd class="break-all text-foreground">{displayValue(versionInfo?.container_id)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4 md:flex-col md:items-start md:gap-1">
            <dt class="text-muted-foreground">Hostname</dt>
            <dd class="break-all text-foreground">{displayValue(versionInfo?.hostname)}</dd>
          </div>
          <div class="flex items-start justify-between gap-4 md:flex-col md:items-start md:gap-1">
            <dt class="text-muted-foreground">Browser origin</dt>
            <dd class="break-all text-foreground">{typeof window === "undefined" ? "Unavailable" : window.location.origin}</dd>
          </div>
          <div class="flex items-start justify-between gap-4 md:flex-col md:items-start md:gap-1">
            <dt class="text-muted-foreground">Browser path</dt>
            <dd class="break-all text-foreground">{typeof window === "undefined" ? "Unavailable" : window.location.pathname}</dd>
          </div>
        </dl>
      </div>
    </div>

    {#if versionError || changelogError}
      <div class="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-900 dark:text-amber-200">
        {#if versionError}
          <p>Runtime metadata warning: {versionError}</p>
        {/if}
        {#if changelogError}
          <p class={versionError ? "mt-1" : ""}>Release notes warning: {changelogError}</p>
        {/if}
      </div>
    {/if}
  </section>

  <section class="flex flex-col gap-3">
    <h3 class="text-foreground">Getting Support</h3>
    <article>
      <h2>Documentation</h2>
      <a
        href="https://dutchgeek.github.io/MediaMasterr/"
        target="_blank"
        rel="noopener noreferrer"
        class="text-primary underline"
      >
        https://dutchgeek.github.io/MediaMasterr/
      </a>
    </article>

    <article>
      <h2>GitHub Discussions</h2>
      <p class="text-sm">
        For questions, troubleshooting, or just to chat with the community,
        check out our <a
          href="https://github.com/DutchGeek/MediaMasterr/discussions"
          target="_blank"
          rel="noopener noreferrer"
          class="text-primary underline"
        >
          GitHub Discussions
        </a>
      </p>
    </article>

    <article>
      <h2>Matrix Chat</h2>
      <p class="text-sm">
        Join our Matrix room for real time support and discussion:
        <a
          href="https://matrix.to/#/#mediamasterr:matrix.org"
          target="_blank"
          rel="noopener noreferrer"
          class="text-primary underline"
        >
          #mediamasterr:matrix.org
        </a>
      </p>
    </article>

    <article>
      <h2>Fluxer</h2>
      <p class="text-sm">
        Once Fluxer V2 is released, we'll have a MediaMasterr channel there as
        well for real time chat. Stay tuned!
      </p>
    </article>
  </section>
  <hr />

  <section class="flex flex-col gap-3">
    <h3 class="text-foreground">Release Notes</h3>
    <p class="text-sm text-muted-foreground">
      Select below to view the release notes for each version
    </p>
    <Select.Root
      type="single"
      value={String(selectedIndex)}
      onValueChange={(v) => (selectedIndex = Number(v))}
    >
      <Select.Trigger class="cursor-pointer text-foreground">
        {#if selected}
          <span class="flex items-center gap-2">
            {selected.version}
            {#if selected.version === versionInfo?.application_version}
              <Badge class="h-4 px-1 text-[10px] leading-none">Current</Badge>
            {/if}
            {#if selected.date}
              <span class="text-xs text-muted-foreground">{selected.date}</span>
            {/if}
          </span>
        {/if}
      </Select.Trigger>
      <Select.Content>
        {#each releases as release, i}
          <Select.Item value={String(i)} class="cursor-pointer">
            <span class="flex items-center gap-2">
              {release.version}
              {#if release.version === versionInfo?.application_version}
                <Badge class="h-4 px-1 text-[10px] leading-none">Current</Badge>
              {/if}
              {#if release.date}
                <span class="text-xs text-muted-foreground">{release.date}</span>
              {/if}
            </span>
          </Select.Item>
        {/each}
      </Select.Content>
    </Select.Root>

    {#if selected}
      <div class="bg-muted/50 border rounded-lg p-4 shadow-sm">
        <article class="prose prose-sm dark:prose-invert max-w-none">
          <Markdown md={selected.body} plugins={mdPlugins} />
        </article>
      </div>
    {/if}
  </section>

  {#if loading}
    <div class="flex justify-center py-4">
      <Spinner class="w-8 h-8 text-primary" />
    </div>
  {/if}
</div>
