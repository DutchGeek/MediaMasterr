<script lang="ts">
  import { post_api } from "$lib/api";

  let shutdownPending = $state(false);
  let message = $state("");
  let error = $state("");

  const shutdownDesktop = async () => {
    shutdownPending = true;
    error = "";
    try {
      const response = await post_api<{ detail: string }>("/api/system/shutdown", {});
      message = response.detail;
    } catch (e: any) {
      error = e?.message ?? "Failed to trigger shutdown";
      message = "";
    } finally {
      shutdownPending = false;
    }
  };
</script>

<div class="p-2.5 md:p-8">
  <div class="max-w-5xl mx-auto space-y-6">
    <div>
      <h1 class="text-3xl font-bold text-foreground">System</h1>
      <p class="text-muted-foreground">Operational controls for this MediaMasterr instance.</p>
    </div>

    <section class="bg-card border border-border rounded-lg p-5 space-y-4">
      <h2 class="text-lg font-semibold text-foreground">Desktop Runtime</h2>
      <p class="text-sm text-muted-foreground">
        This action is only available when MediaMasterr runs in desktop mode.
      </p>
      <button
        onclick={shutdownDesktop}
        disabled={shutdownPending}
        class="rounded-md bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-60"
      >
        {shutdownPending ? "Shutting down..." : "Shutdown Application"}
      </button>

      {#if message}
        <p class="text-sm text-green-500">{message}</p>
      {/if}
      {#if error}
        <p class="text-sm text-destructive">{error}</p>
      {/if}
    </section>
  </div>
</div>
