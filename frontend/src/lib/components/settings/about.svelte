<script lang="ts">
  import { onMount } from "svelte";
  import type { Component } from "svelte";
  import Markdown from "svelte-exmarkdown";
  import { gfmPlugin } from "svelte-exmarkdown/gfm";

  import { get_api } from "$lib/api";
  import { BRANDING } from "$lib/branding";
  import BrandLogo from "$lib/components/brand-logo.svelte";
  import Spinner from "$lib/components/ui/spinner/spinner.svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Select from "$lib/components/ui/select/index.js";

  interface Release {
    version: string;
    date: string | null;
    body: string;
  }

  interface VersionInfo {
    version: string;
    program: string;
    url: string;
    commit_sha: string | null;
    short_sha: string | null;
    build_timestamp: string | null;
    release_channel: string | null;
    docker_tag: string | null;
    docker_image: string | null;
    docker_digest: string | null;
    container_digest: string | null;
    workflow_run_number: string | null;
    workflow_run_attempt: string | null;
    oci_revision: string | null;
    oci_source: string | null;
    oci_version: string | null;
    repository: string | null;
  }

  interface Props {
    svgIcon: Component | null;
  }
  let { svgIcon }: Props = $props();

  const mdPlugins = [gfmPlugin()];

  let loading = $state(true);
  let error = $state<string | null>(null);
  let releases = $state<Release[]>([]);
  let selectedIndex = $state(0);
  let currentVersion = $state<string | null>(null);
  let versionInfo = $state<VersionInfo | null>(null);

  const selected = $derived(releases[selectedIndex] ?? null);

  onMount(async () => {
    try {
      const [rel, ver] = await Promise.all([
        get_api<Release[]>("/api/info/changelog"),
        get_api<VersionInfo>("/api/info/version"),
      ]);
      releases = rel;
      versionInfo = ver;
      currentVersion = ver.version;
      // default to the entry matching the running version, else first
      const match = releases.findIndex((r) => r.version === currentVersion);
      selectedIndex = match >= 0 ? match : 0;
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load changelog.";
    } finally {
      loading = false;
    }
  });
</script>

<div class="space-y-6">
  <div class="flex justify-center">
    <BrandLogo widthClass="w-[320px] sm:w-[360px]" />
  </div>

  <div>
    <h2 class="flex items-center gap-3 text-xl font-semibold text-foreground">
      {#if svgIcon}
        {@const Icon = svgIcon}
        <Icon class="size-5" aria-hidden="true" />
      {/if}
      <span class="align-middle">About {BRANDING.applicationName}</span>
    </h2>
    {#if currentVersion}
      <p class="mt-1 text-xs text-muted-foreground">
        {BRANDING.applicationName} v{currentVersion}
      </p>
    {/if}
  </div>

  <hr />

  {#if versionInfo}
    <section class="space-y-3">
      <h3 class="text-foreground">Runtime Metadata</h3>
      <div class="overflow-x-auto rounded-md border border-border/60">
        <table class="w-full min-w-[540px] text-sm">
          <tbody>
            <tr class="border-b border-border/50">
              <td class="px-3 py-2 text-muted-foreground"
                >MediaMasterr Version</td
              >
              <td class="px-3 py-2 text-foreground">{versionInfo.version}</td>
            </tr>
            <tr class="border-b border-border/50">
              <td class="px-3 py-2 text-muted-foreground">Commit SHA</td>
              <td class="px-3 py-2 text-foreground"
                >{versionInfo.commit_sha ?? "n/a"}</td
              >
            </tr>
            <tr class="border-b border-border/50">
              <td class="px-3 py-2 text-muted-foreground">Short SHA</td>
              <td class="px-3 py-2 text-foreground"
                >{versionInfo.short_sha ?? "n/a"}</td
              >
            </tr>
            <tr class="border-b border-border/50">
              <td class="px-3 py-2 text-muted-foreground">Build Timestamp</td>
              <td class="px-3 py-2 text-foreground"
                >{versionInfo.build_timestamp ?? "n/a"}</td
              >
            </tr>
            <tr class="border-b border-border/50">
              <td class="px-3 py-2 text-muted-foreground">Release Channel</td>
              <td class="px-3 py-2 text-foreground"
                >{versionInfo.release_channel ?? "n/a"}</td
              >
            </tr>
            <tr class="border-b border-border/50">
              <td class="px-3 py-2 text-muted-foreground">Docker Tag</td>
              <td class="px-3 py-2 text-foreground"
                >{versionInfo.docker_tag ?? "n/a"}</td
              >
            </tr>
            <tr class="border-b border-border/50">
              <td class="px-3 py-2 text-muted-foreground">Docker Image</td>
              <td class="px-3 py-2 text-foreground"
                >{versionInfo.docker_image ?? "n/a"}</td
              >
            </tr>
            <tr class="border-b border-border/50">
              <td class="px-3 py-2 text-muted-foreground">OCI Revision</td>
              <td class="px-3 py-2 text-foreground"
                >{versionInfo.oci_revision ?? "n/a"}</td
              >
            </tr>
            <tr class="border-b border-border/50">
              <td class="px-3 py-2 text-muted-foreground">OCI Source</td>
              <td class="px-3 py-2 text-foreground">
                {#if versionInfo.oci_source}
                  <a
                    href={versionInfo.oci_source}
                    target="_blank"
                    rel="noopener noreferrer"
                    class="text-primary underline"
                  >
                    {versionInfo.oci_source}
                  </a>
                {:else}
                  n/a
                {/if}
              </td>
            </tr>
            <tr class="border-b border-border/50">
              <td class="px-3 py-2 text-muted-foreground">OCI Version</td>
              <td class="px-3 py-2 text-foreground"
                >{versionInfo.oci_version ?? "n/a"}</td
              >
            </tr>
            <tr class="border-b border-border/50">
              <td class="px-3 py-2 text-muted-foreground">Docker Digest</td>
              <td class="px-3 py-2 text-foreground">
                {versionInfo.docker_digest ??
                  versionInfo.container_digest ??
                  "n/a"}
              </td>
            </tr>
            <tr class="border-b border-border/50">
              <td class="px-3 py-2 text-muted-foreground"
                >Workflow Build Number</td
              >
              <td class="px-3 py-2 text-foreground"
                >{versionInfo.workflow_run_number ?? "n/a"}</td
              >
            </tr>
            <tr class="border-b border-border/50">
              <td class="px-3 py-2 text-muted-foreground"
                >Workflow Run Attempt</td
              >
              <td class="px-3 py-2 text-foreground"
                >{versionInfo.workflow_run_attempt ?? "n/a"}</td
              >
            </tr>
            <tr>
              <td class="px-3 py-2 text-muted-foreground">GitHub Repository</td>
              <td class="px-3 py-2 text-foreground">
                {#if versionInfo.repository}
                  <a
                    href={versionInfo.repository}
                    target="_blank"
                    rel="noopener noreferrer"
                    class="text-primary underline"
                  >
                    {versionInfo.repository}
                  </a>
                {:else}
                  n/a
                {/if}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <hr />
  {/if}

  {#if loading}
    <div class="flex justify-center py-8">
      <Spinner class="w-12 h-12 text-primary" />
    </div>
  {:else if error}
    <div class="rounded-md border border-destructive/40 bg-destructive/10 p-3">
      <p class="text-sm text-destructive">{error}</p>
    </div>
  {:else}
    <!-- support section -->
    <section class="flex flex-col gap-3">
      <h3 class="text-foreground">Getting Support</h3>
      <!-- docs -->
      <article>
        <h2>Documentation</h2>
        <a
          href="https://dutchgeek.github.io/MediaMasterr/"
          target="_blank"
          rel="noopener noreferrer"
          class="text-primary underline"
          >https://dutchgeek.github.io/MediaMasterr/</a
        >
      </article>

      <!-- github discussions -->
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

      <!-- matrix -->
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

      <!-- fluxer -->
      <article>
        <h2>Fluxer</h2>
        <p class="text-sm">
          Once Fluxer V2 is released, we'll have a MediaMasterr channel there as
          well for real time chat. Stay tuned!
        </p>
      </article>
    </section>
    <hr />

    <!-- release notes section -->
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
              {#if selected.version === currentVersion}
                <Badge class="h-4 px-1 text-[10px] leading-none">Current</Badge>
              {/if}
              {#if selected.date}
                <span class="text-xs text-muted-foreground"
                  >{selected.date}</span
                >
              {/if}
            </span>
          {/if}
        </Select.Trigger>
        <Select.Content>
          {#each releases as release, i}
            <Select.Item value={String(i)} class="cursor-pointer">
              <span class="flex items-center gap-2">
                {release.version}
                {#if release.version === currentVersion}
                  <Badge class="h-4 px-1 text-[10px] leading-none"
                    >Current</Badge
                  >
                {/if}
                {#if release.date}
                  <span class="text-xs text-muted-foreground"
                    >{release.date}</span
                  >
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
  {/if}
</div>
